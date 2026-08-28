"""TUI 路由测试。

Regression: 之前的 commit 286ccf9 用启发式判断中文输入为闲聊（heuristic 判断错误地把"帮我写个脚本"识别为 chat）。

新版本：
- 默认所有非 / 前缀输入走 Agent 模式
- /chat 才走 chat
- /workspace /clear 是显式命令
"""

import pytest

from coding_agent.tui.routing import CommandKind, route_input


class TestDefaultRoutesToAgent:
    """核心断言：非 / 前缀的输入必须进 Agent，不能被启发式劫持到 Chat。"""

    def test_english_coding_task(self):
        r = route_input("build a personal portfolio website")
        assert r.kind is CommandKind.AGENT
        assert r.payload == "build a personal portfolio website"

    def test_chinese_coding_task_writes_script(self):
        r = route_input("帮我写一个脚本")
        assert r.kind is CommandKind.AGENT, (
            "中文 coding 任务不应被误判为闲聊"
        )
        assert r.payload == "帮我写一个脚本"

    def test_chinese_coding_task_website(self):
        r = route_input("帮我写一个个人网站")
        assert r.kind is CommandKind.AGENT

    def test_chinese_short_phrase(self):
        r = route_input("我们直接规划结构吧")
        assert r.kind is CommandKind.AGENT, (
            "短中文短语不应被当成闲聊"
        )

    def test_chinese_fix_request(self):
        r = route_input("修复这个错误")
        assert r.kind is CommandKind.AGENT

    def test_chinese_add_feature(self):
        r = route_input("添加一个登录功能")
        assert r.kind is CommandKind.AGENT

    def test_chinese_test_request(self):
        r = route_input("运行 pytest 看看通过没")
        assert r.kind is CommandKind.AGENT

    def test_greeting(self):
        """即使 'hello' 也要走 Agent（用户没显式 /chat）"""
        r = route_input("你好啊")
        assert r.kind is CommandKind.AGENT


class TestChatRequiresExplicitPrefix:
    """/chat 前缀才走 chat；不带前缀即使是闲聊也走 Agent。"""

    def test_chat_with_prefix(self):
        r = route_input("/chat 你好")
        assert r.kind is CommandKind.CHAT
        assert r.payload == "你好"

    def test_chat_with_long_message(self):
        r = route_input("/chat 帮我解释一下 Agent 是什么")
        assert r.kind is CommandKind.CHAT
        assert r.payload == "帮我解释一下 Agent 是什么"

    def test_chat_no_payload(self):
        r = route_input("/chat ")
        assert r.kind is CommandKind.CHAT
        assert r.payload == ""

    def test_plain_greeting_is_agent(self):
        """即使只是打招呼，没有 /chat 前缀也要走 Agent（Agent 自己会处理）"""
        r = route_input("hi")
        assert r.kind is CommandKind.AGENT


class TestWorkspaceCommand:
    def test_workspace_with_path(self):
        r = route_input("/workspace /tmp/foo")
        assert r.kind is CommandKind.WORKSPACE
        assert r.payload == "/tmp/foo"

    def test_workspace_no_path(self):
        r = route_input("/workspace")
        assert r.kind is CommandKind.WORKSPACE
        assert r.payload == ""


class TestClearCommand:
    def test_clear(self):
        r = route_input("/clear")
        assert r.kind is CommandKind.CLEAR


class TestUnknownCommand:
    def test_unknown_slash(self):
        r = route_input("/foo bar baz")
        assert r.kind is CommandKind.UNKNOWN
        assert r.payload == "/foo"

    def test_help_not_recognized(self):
        r = route_input("/help")
        assert r.kind is CommandKind.UNKNOWN


class TestEdgeCases:
    def test_empty_string(self):
        r = route_input("")
        assert r.kind is CommandKind.AGENT
        assert r.payload == ""

    def test_whitespace_only(self):
        r = route_input("   \n  ")
        assert r.kind is CommandKind.AGENT

    def test_text_with_slash_in_middle(self):
        """中间带 / 的句子不应被当成命令"""
        r = route_input("请帮我看看 /etc/hosts")
        assert r.kind is CommandKind.AGENT
        assert r.payload == "请帮我看看 /etc/hosts"