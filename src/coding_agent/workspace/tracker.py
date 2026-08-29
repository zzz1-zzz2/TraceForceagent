"""WorkspaceChangeTracker (P2-1E.3).

替换"按 tool name 猜 mutation"的旧实现。每个 tool 执行前后对 workspace
做有界快照，真实、持久的文件变化才进入 modified_files /
last_mutation_step / ready_to_finish=False。

设计要点：
- Snapshot 是 path/type/size/mtime/mode 的有界映射；
  对 ≤ HASH_BOUND 的文件额外存 content_hash，用于"恢复原状不计入 mutation"。
- 不跟随 symlink；保护 .git；排除常见噪声目录。
- 拒绝"恢复原状"作为净变化（前后 hash 一致 → 不记录）。
- 跨 Git / 非 Git workspace：Git 模式借助 ``git status --porcelain=v2``
  拿到精确相对路径集合，再 stat；非 Git 模式走 ``os.walk`` 上限封顶。
- Diff 只在调用时计算，不持久化中间状态。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Snapshot 上限：避免巨大 workspace 把内存 / 时间拖垮。
MAX_SNAPSHOT_ENTRIES = 5000
MAX_WALK_DEPTH = 10
# 对 ≤ 此大小的文件计算 content hash，用于"恢复原状"判定。
HASH_BOUND_BYTES = 256 * 1024
# 单次 snapshot 中最多 hash 的累计字节数（防止几万个 256KB 文件把 CPU 跑满）。
MAX_TOTAL_HASH_BYTES = 4 * 1024 * 1024
# 不进入 snapshot 的目录（防止 .git 内部 / 构建产物噪声）。
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".pytest_cache", ".tox", ".mypy_cache",
    ".ruff_cache", "target",  # Rust/Java 输出
})
# 文件读失败的兜底大小（用于 IOError 时不污染 diff）。
_READ_ERROR_SIZE = -1


@dataclass(frozen=True, slots=True)
class FileEntry:
    """单个文件 / 目录 / symlink 的有界描述。"""

    path: str  # 相对 workspace 的 POSIX 路径
    kind: str  # "file" | "dir" | "symlink"
    size: int  # 文件字节数；目录为 0；symlink 为 link 长度
    mtime_ns: int  # mtime，单位 ns
    mode: int  # st_mode 权限位
    content_hash: str | None = None  # 仅 file + ≤ HASH_BOUND_BYTES 时存在


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    """一次 workspace 快照。"""

    entries: tuple[FileEntry, ...]
    taken_at: float
    is_git: bool

    def as_dict(self) -> dict[str, FileEntry]:
        """O(N) 构建 path → entry 字典，供 diff 使用。"""
        return {entry.path: entry for entry in self.entries}

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self.entries)


@dataclass(frozen=True, slots=True)
class WorkspaceChange:
    """两个 snapshot 之间的真实净变化。"""

    created: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.created or self.modified or self.deleted)

    def all_paths(self) -> tuple[str, ...]:
        return (*self.created, *self.modified, *self.deleted)

    def summary(self) -> str:
        """面向 trajectory 的简短摘要。"""
        if not self.has_changes:
            return "no net workspace changes"
        parts: list[str] = []
        if self.created:
            parts.append(f"+{len(self.created)} created")
        if self.modified:
            parts.append(f"~{len(self.modified)} modified")
        if self.deleted:
            parts.append(f"-{len(self.deleted)} deleted")
        return ", ".join(parts)


def _safe_read_bytes(path: Path, *, bound: int) -> bytes:
    """读取 ≤ bound 字节的文件内容；出错返回 b''。"""
    try:
        with path.open("rb") as fh:
            return fh.read(bound + 1)
    except OSError:
        return b""


def _hash_for_entry(path: Path, size: int) -> str | None:
    """对 ≤ HASH_BOUND_BYTES 的文件返回 sha256 hex；否则返回 None。

    仅在 _collect_file 中调用，size 已确认 ≤ HASH_BOUND_BYTES。
    """
    if size < 0 or size > HASH_BOUND_BYTES:
        return None
    data = _safe_read_bytes(path, bound=HASH_BOUND_BYTES)
    if not data and size > 0:
        return None
    return hashlib.sha256(data).hexdigest()


def _collect_file(abs_path: Path, rel: str, *, hash_budget: list[int]) -> FileEntry | None:
    """构造一个 file 的 FileEntry；预算耗尽则跳过 hash。"""
    try:
        st = abs_path.lstat()  # 不跟随 symlink
    except OSError:
        return None
    size = int(st.st_size)
    if size > HASH_BOUND_BYTES:
        return FileEntry(
            path=rel, kind="file", size=size, mtime_ns=int(st.st_mtime_ns),
            mode=int(st.st_mode), content_hash=None,
        )
    if hash_budget[0] <= 0:
        # 没预算了，跳过 hash 但仍记录元数据。
        return FileEntry(
            path=rel, kind="file", size=size, mtime_ns=int(st.st_mtime_ns),
            mode=int(st.st_mode), content_hash=None,
        )
    content_hash = _hash_for_entry(abs_path, size)
    if content_hash is not None:
        # 把这次读取计入预算。
        hash_budget[0] -= min(size, HASH_BOUND_BYTES)
    return FileEntry(
        path=rel, kind="file", size=size, mtime_ns=int(st.st_mtime_ns),
        mode=int(st.st_mode), content_hash=content_hash,
    )


def _iter_walk_files(
    workspace: Path, *, max_depth: int = MAX_WALK_DEPTH,
) -> Iterable[tuple[Path, str, bool]]:
    """非 Git 模式下产出 (abs_path, rel_posix, is_symlink) 三元组。

    不跟随 symlink；跳过常见噪声目录。注意：不调用 abs_path.resolve()，
    因为 resolve 会跟随 symlink，使 symlink 路径被替换成目标路径。
    """
    workspace = workspace.resolve()
    for root, dirs, files in os.walk(workspace, followlinks=False):
        # 修剪 dirs 列表：跳过 _SKIP_DIRS，并按 depth 截断。
        try:
            rel_root = Path(root).relative_to(workspace)
        except ValueError:
            continue
        depth = 0 if rel_root == Path(".") else len(rel_root.parts)
        if depth >= max_depth:
            dirs.clear()
        else:
            dirs[:] = [
                d for d in sorted(dirs) if d not in _SKIP_DIRS
            ]

        for name in sorted(files):
            abs_path = Path(root) / name
            is_link = abs_path.is_symlink()
            try:
                # 不能 resolve(): 会跟随 symlink。用 parent.relative_to 构造 rel。
                rel_path = Path(root).relative_to(workspace) / name
            except ValueError:
                continue
            yield abs_path, rel_path.as_posix(), is_link


def _is_git_repo(workspace: Path) -> bool:
    return (workspace / ".git").exists() or (
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(workspace), capture_output=True, text=True, check=False,
        ).returncode == 0
    )


def _git_listed_paths(workspace: Path) -> list[str] | None:
    """在 Git 模式下取"git 视野内"的完整路径集合。

    ``git ls-files -co --others --exclude-standard -z`` 一次性返回：
    - ``-c``：已 tracked 的文件（按 HEAD/index 状态）；
    - ``-o``：untracked；
    - ``--exclude-standard``：尊重 .gitignore。

    这是为了让 snapshot 包含"完整"路径集合（不仅是 porcelain v2 的"变化"集合），
    否则 diff 会出现"原 tracked 文件首次被修改时误判为 created"。

    返回 None 表示 git 调用失败，回落到非 Git 模式。
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-co", "--others", "--exclude-standard", "-z"],
            cwd=str(workspace), capture_output=True, text=True, check=False,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout or ""
    paths: list[str] = [
        chunk for chunk in raw.split("\x00") if chunk
    ]
    return paths


def _safe_rel(abs_path: Path, workspace: Path) -> str | None:
    try:
        return abs_path.resolve(strict=False).relative_to(workspace).as_posix()
    except ValueError:
        return None


def snapshot_workspace(workspace: Path, *, prefer_git: bool = True) -> WorkspaceSnapshot:
    """对 workspace 做一次有界快照。

    - Git 模式：先取 ``git status --porcelain=v2`` 列出的"可能变化"路径，
      再 stat 它们；同时额外 stat 工作区根目录的存在感（用于 created/deleted）。
    - 非 Git 模式：``os.walk`` 整棵树，受 MAX_SNAPSHOT_ENTRIES / MAX_WALK_DEPTH 限制。
    - 不跟随 symlink；保护 .git 等噪声目录。
    """
    import time
    workspace = workspace.resolve()
    is_git = prefer_git and _is_git_repo(workspace)
    entries: list[FileEntry] = []
    hash_budget = [MAX_TOTAL_HASH_BYTES]

    def _add_file(abs_path: Path, rel: str) -> None:
        if len(entries) >= MAX_SNAPSHOT_ENTRIES:
            return
        # 跳过 symlink（lstat 已不跟随）
        if abs_path.is_symlink():
            try:
                st = abs_path.lstat()
                entries.append(FileEntry(
                    path=rel, kind="symlink",
                    size=int(st.st_size),
                    mtime_ns=int(st.st_mtime_ns),
                    mode=int(st.st_mode),
                    content_hash=None,
                ))
            except OSError:
                pass
            return
        entry = _collect_file(abs_path, rel, hash_budget=hash_budget)
        if entry is not None:
            entries.append(entry)

    if is_git:
        paths = _git_listed_paths(workspace) or []
        for rel in paths:
            abs_path = workspace / rel
            if not abs_path.exists():
                # 文件被删除：在 snapshot 中也保留为 deleted 标记（kind=deleted）。
                try:
                    # 试图读取索引态 mtime；放弃 → 用 0。
                    entries.append(FileEntry(
                        path=rel, kind="deleted", size=0,
                        mtime_ns=0, mode=0, content_hash=None,
                    ))
                except Exception:  # pragma: no cover - 防御
                    pass
                continue
            _add_file(abs_path, rel)
        # 同时记录 .git 目录存在性（防止"删了 .git"被误判为普通目录变化）。
        git_dir = workspace / ".git"
        if git_dir.exists():
            try:
                st = git_dir.lstat()
                entries.append(FileEntry(
                    path=".git", kind="dir", size=0,
                    mtime_ns=int(st.st_mtime_ns), mode=int(st.st_mode),
                    content_hash=None,
                ))
            except OSError:
                pass
    else:
        for abs_path, rel, is_link in _iter_walk_files(workspace):
            if is_link:
                try:
                    st = abs_path.lstat()
                except OSError:
                    continue
                if len(entries) < MAX_SNAPSHOT_ENTRIES:
                    entries.append(FileEntry(
                        path=rel, kind="symlink",
                        size=int(st.st_size),
                        mtime_ns=int(st.st_mtime_ns),
                        mode=int(st.st_mode),
                        content_hash=None,
                    ))
                continue
            _add_file(abs_path, rel)

    return WorkspaceSnapshot(
        entries=tuple(entries),
        taken_at=time.time(),
        is_git=is_git,
    )


def diff_snapshots(
    prev: WorkspaceSnapshot, curr: WorkspaceSnapshot,
) -> WorkspaceChange:
    """计算两个 snapshot 之间的真实净变化。

    规则：
    - prev 有 curr 没有 → deleted
    - curr 有 prev 没有 → created
    - 都有：path/kind/size/mtime/mode 全部相同 → unchanged
      - 如果 prev.content_hash 与 curr.content_hash 都存在且不同 → modified
      - 否则（任一 hash 缺失）若 size/mtime/mode 变化 → modified（保守）
    """
    prev_map = prev.as_dict()
    curr_map = curr.as_dict()
    created: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []

    for path, curr_entry in curr_map.items():
        prev_entry = prev_map.get(path)
        if prev_entry is None:
            created.append(path)
            continue
        if prev_entry.kind == "deleted" or curr_entry.kind == "deleted":
            # 任何一方声明 deleted 即视为 modified（净变化包含"它存在过"）。
            modified.append(path)
            continue
        if _entries_equal(prev_entry, curr_entry):
            continue
        modified.append(path)

    for path, prev_entry in prev_map.items():
        if path not in curr_map and prev_entry.kind != "deleted":
            deleted.append(path)

    created.sort()
    modified.sort()
    deleted.sort()
    return WorkspaceChange(
        created=tuple(created),
        modified=tuple(modified),
        deleted=tuple(deleted),
    )


def _entries_equal(a: FileEntry, b: FileEntry) -> bool:
    """两条 FileEntry 是否指向"同一持久状态"。

    规则：
    1. kind 必须一致；否则不同。
    2. 两边都有 content_hash：hash 一致 *且* mode 一致 → 视为相同
       （恢复原状后 mtime 更新但内容/权限未变）。
       hash 一致但 mode 变化（chmod）→ 仍计为 modified。
    3. 缺 hash 时按 (size, mtime_ns, mode) 严格比较。
    """
    if a.kind != b.kind:
        return False
    if a.content_hash is not None and b.content_hash is not None:
        if a.content_hash != b.content_hash:
            return False
        # hash 相同但 mode 变了 → 仍算修改（chmod / permission 变化）。
        return a.mode == b.mode
    # 缺 hash：回退到元数据严格比较。
    return (a.size, a.mtime_ns, a.mode) == (b.size, b.mtime_ns, b.mode)


class WorkspaceChangeTracker:
    """对单个 workspace 提供 take_snapshot + diff 的便捷封装。

    用法（在 AgentLoop 中）：
        tracker = WorkspaceChangeTracker(workspace)
        ...
        prev = tracker.snapshot()
        observation = tool.execute(action.arguments, runtime)
        change = tracker.diff_since(prev)
        if change.has_changes:
            state.record_workspace_change(change, step=state.step_count)
    """

    def __init__(self, workspace: Path, *, prefer_git: bool = True):
        self.workspace = Path(workspace).resolve()
        self._prefer_git = prefer_git
        self._last_snapshot: WorkspaceSnapshot | None = None

    def snapshot(self) -> WorkspaceSnapshot:
        """立刻拍快照；同时保留为 _last_snapshot，供 diff_since 使用。"""
        snap = snapshot_workspace(self.workspace, prefer_git=self._prefer_git)
        self._last_snapshot = snap
        return snap

    def diff_since(self, prev: WorkspaceSnapshot) -> WorkspaceChange:
        """与传入的 prev 对比；不会修改 _last_snapshot。"""
        curr = self.snapshot()
        return diff_snapshots(prev, curr)

    @property
    def last_snapshot(self) -> WorkspaceSnapshot | None:
        return self._last_snapshot
