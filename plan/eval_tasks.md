# L1 自建任务设计

> 这五个任务覆盖核心能力：**Bug Fix / Feature / 模糊需求 / 回归型修复 / Greenfield**。

---

## 总览

| 任务 | 类型 | 主要验证能力 | 难度 |
|------|------|--------------|------|
| A safe_divide | Bug Fix | 定位、修改、pytest | ⭐ |
| B cache_clear | Feature + Test | 多文件、新建方法 + 测试 | ⭐⭐ |
| C config_friendly | 模糊需求 | 自主探索、读 test 推断意图 | ⭐⭐⭐ |
| D chunked_robust | 回归型修复 | Failure-Aware Refresh 价值 | ⭐⭐⭐⭐ |
| E todo_cli | Greenfield | 从零建项目 + 完整结构 | ⭐⭐⭐ |

---

## A：safe_divide（明确 Bug Fix）

**目录**：`eval/tasks/A_safe_divide/`

### src/math_utils.py
```python
def safe_divide(a: float, b: float) -> float:
    """Divide a by b. Returns 0 if b is 0."""
    return a / b  # BUG


def average(values: list[float]) -> float:
    if not values:
        raise ValueError("empty")
    return safe_divide(sum(values), len(values))
```

### tests/test_math_utils.py
```python
import pytest
from src.math_utils import safe_divide, average


def test_safe_divide_normal():
    assert safe_divide(10, 2) == 5.0


def test_safe_divide_by_zero():
    assert safe_divide(10, 0) == 0.0


def test_average_uses_safe_divide():
    assert average([10, 20, 30]) == 20.0


def test_average_empty_raises():
    with pytest.raises(ValueError):
        average([])
```

### task.md
```markdown
# 任务 A：修复 safe_divide

math_utils.py 中的 safe_divide(a, b) 在 b=0 时应该返回 0.0，
但当前实现会抛 ZeroDivisionError。

请修改 src/math_utils.py 使所有测试通过，然后运行 pytest 验证。
```

---

## B：cache_clear（Feature + Test）

**目录**：`eval/tasks/B_cache_clear/`

### src/cache.py
```python
class Cache:
    def __init__(self):
        self._store = {}

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value):
        self._store[key] = value

    # TODO: 实现 clear() 方法
```

### tests/test_cache.py
```python
from src.cache import Cache


def test_get_set():
    c = Cache()
    c.set("a", 1)
    assert c.get("a") == 1


def test_clear_removes_all():
    c = Cache()
    c.set("a", 1); c.set("b", 2)
    c.clear()
    assert c.get("a") is None
    assert c.get("b") is None


def test_clear_on_empty():
    c = Cache()
    c.clear()
    assert c.get("a") is None
```

### task.md
```markdown
# 任务 B：为 Cache 添加 clear()

Cache 类缺少 clear() 方法。请：
1. 在 src/cache.py 中实现 clear()
2. 确保 tests/test_cache.py 全部通过
3. 完成后运行 pytest
```

---

## C：config_friendly（模糊需求）

**目录**：`eval/tasks/C_config_friendly/`

### src/config.py
```python
import json
from pathlib import Path


def load_config(path: str) -> dict:
    """Load JSON config from path."""
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text)
```

### tests/test_config.py
```python
import json
import pytest
from src.config import load_config


def test_load_valid(tmp_path):
    p = tmp_path / "ok.json"
    p.write_text(json.dumps({"host": "localhost", "port": 8080}))
    assert load_config(str(p)) == {"host": "localhost", "port": 8080}


def test_load_missing_file_returns_empty(tmp_path):
    assert load_config(str(tmp_path / "nope.json")) == {}


def test_load_partial_returns_defaults(tmp_path):
    p = tmp_path / "partial.json"
    p.write_text(json.dumps({"host": "localhost"}))
    cfg = load_config(str(p))
    assert cfg.get("host") == "localhost"
    assert cfg.get("port") == 8080
```

### task.md
```markdown
# 任务 C：让配置加载更友好

当前 load_config 在文件缺失或字段不全时直接崩溃。请改进它，
使其在以下情况更健壮：
- 配置文件不存在 → 返回 {}
- 配置文件缺少字段 → 补默认值

defaults: port=8080, host="localhost", debug=false
完成后运行 pytest 验证。
```

---

## D：chunked_robust（回归型修复）

**目录**：`eval/tasks/D_chunked_robust/`

### src/chunker.py
```python
def list_chunked(items: list, size: int) -> list[list]:
    """Split items into chunks of given size."""
    chunks = []
    for i in range(0, len(items), size):
        chunks.append(items[i:i + size])
    return chunks
```

### tests/test_chunker.py
```python
import pytest
from src.chunker import list_chunked


def test_chunk_basic():
    assert list_chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunk_size_one():
    assert list_chunked([1, 2, 3], 1) == [[1], [2], [3]]


def test_chunk_empty():
    assert list_chunked([], 3) == []


def test_chunk_size_zero_or_negative_raises():
    with pytest.raises(ValueError):
        list_chunked([1, 2], 0)
    with pytest.raises(ValueError):
        list_chunked([1, 2], -1)
```

### task.md
```markdown
# 任务 D：list_chunked 健壮性

当 size <= 0 时，当前 list_chunked 会进入死循环或返回空列表。
请修改使其抛 ValueError("size must be positive")。

注意：保留 chunks.append(items[i:i + size]) 的核心循环逻辑，
不要改成 if size > 0 提前返回这种绕过的方案。

完成后运行 pytest 验证。
```

**考点**：朴素方案 `if size <= 0: raise` 会让 pytest 通过，但绕过核心循环、违反任务约束。Agent 是否能"读懂任务约束 + 验证自己的方案"是关键。

---

## E：todo_cli（Greenfield）

**目录**：`eval/tasks/E_todo_cli/`

### task.md
```markdown
# 任务 E：实现 Todo CLI

在当前空目录从零构建一个命令行 Todo 工具，要求：

- 支持 `add <text>`、`list`、`done <id>`、`remove <id>` 四个子命令
- 数据持久化到 todos.json
- 提供 `tests/` 目录和 pytest 测试
- 通过 `python -m todo` 运行

完成后确保 pytest 通过。
```

**预期产出**：
```
.
├── todo/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   └── store.py
├── tests/
│   └── test_todo.py
└── todos.json  # 运行后生成
```

---

## 评测协议

每次跑：

```bash
python -m eval.run_task \
    --task eval/tasks/A_safe_divide \
    --model deepseek-chat \
    --max-steps 30 \
    --timeout 600
```

评测脚本逻辑：

1. 把 task 的 src/ 和 tests/ 拷贝到 `/tmp/eval_<task>_<ts>/`
2. 启动 Agent，task.md 作为 initial task
3. Agent finish 后，在 workspace 跑 pytest
4. 记录 passed/total, steps, model_calls, tokens, duration, stop_reason
5. 写 `runs/run_<task>_<timestamp>/{trajectory.jsonl, final.diff, result.json}`

汇总到 `eval/results/summary.csv`：
```
task,resolved,steps,model_calls,tokens,duration_s,stop_reason
A_safe_divide,True,4,3,4521,28.3,finish
B_cache_clear,True,7,5,8932,52.1,finish
C_config_friendly,True,12,9,14203,98.4,finish
D_chunked_robust,False,18,15,22104,180.0,max_steps
E_todo_cli,True,22,18,31204,205.7,finish
```