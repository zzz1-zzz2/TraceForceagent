"""TUI 路由逻辑（独立于 Textual App，便于测试）。

路由规则：
- "/clear"             → Command.CLEAR
- "/workspace <path>"  → Command.WORKSPACE, 携带 path
- "/chat <msg>"        → Command.CHAT, 携带 msg
- "/..."               → Command.UNKNOWN
- 其他                  → Command.AGENT，携带 raw task
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CommandKind(StrEnum):
    AGENT = "agent"  # 默认：完整工具循环
    CHAT = "chat"  # 多轮纯对话
    WORKSPACE = "workspace"
    CLEAR = "clear"
    UNKNOWN = "unknown"


@dataclass
class Route:
    kind: CommandKind
    payload: str = ""  # workspace 路径 / chat 消息 / agent task


def route_input(raw: str) -> Route:
    """把用户输入解析为 Route。空字符串视作 AGENT（被调用方会跳过空消息）。"""
    text = raw.strip()
    if not text:
        return Route(kind=CommandKind.AGENT, payload="")

    if text == "/clear":
        return Route(kind=CommandKind.CLEAR)

    if text.startswith("/workspace"):
        rest = text[len("/workspace"):].strip()
        return Route(kind=CommandKind.WORKSPACE, payload=rest)

    if text.startswith("/chat"):
        rest = text[len("/chat"):].strip()
        return Route(kind=CommandKind.CHAT, payload=rest)

    if text.startswith("/"):
        return Route(kind=CommandKind.UNKNOWN, payload=text.split()[0])

    # 默认走 Agent
    return Route(kind=CommandKind.AGENT, payload=text)
