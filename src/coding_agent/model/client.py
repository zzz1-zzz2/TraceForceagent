"""ModelClient：与 OpenAI 兼容 API 交互。

支持的 provider（通过 base_url 切换）：
- DeepSeek: https://api.deepseek.com/v1
- GLM-4:    https://open.bigmodel.cn/api/paas/v4
- Qwen:     https://dashscope.aliyuncs.com/compatible-mode/v1
- Kimi:     https://api.moonshot.cn/v1
- OpenAI:   https://api.openai.com/v1
"""

from __future__ import annotations

import time
from typing import Any

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from coding_agent.config import AgentConfig
from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall


class ModelClient:
    """LLM API 客户端（Adapter Pattern）。

    统一接口：generate(messages, tools) -> ModelResponse
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self._client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    @classmethod
    def from_config(cls, config: AgentConfig) -> "ModelClient":
        """从 AgentConfig 构造。"""
        # 兼容多 provider 的 API key
        api_key = (
            config.api_key
            or ""
        )
        if not api_key:
            # 尝试从常见环境变量读取
            import os

            api_key = (
                os.environ.get("DEEPSEEK_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("GLM_API_KEY")
                or os.environ.get("QWEN_API_KEY")
                or os.environ.get("KIMI_API_KEY")
                or ""
            )
        return cls(
            api_key=api_key,
            base_url=config.active_base_url,
            model=config.active_model,
            temperature=config.temperature,
        )

    def generate(self, messages: list[dict], tools: list[dict] | None = None) -> ModelResponse:
        """调用 LLM，返回归一化的 ModelResponse。

        支持 streaming 累积（V1 简化：非流式一次性返回）。
        错误重试：网络 / 429 / 5xx，指数退避。
        """
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                }
                if tools:
                    kwargs["tools"] = tools

                resp = self._client.chat.completions.create(**kwargs)
                return self._parse_response(resp)

            except RateLimitError as e:
                last_err = e
                # 429：长退避
                time.sleep(2 ** (attempt + 2))
            except APITimeoutError as e:
                last_err = e
                time.sleep(2 ** attempt)
            except APIError as e:
                # 5xx 错误可重试
                if e.status_code and 500 <= e.status_code < 600:
                    last_err = e
                    time.sleep(2 ** attempt)
                else:
                    raise
            except Exception as e:
                # 不可重试错误（如 schema 错误）
                raise

        raise RuntimeError(f"ModelClient failed after {self.max_retries} retries: {last_err}")

    def _parse_response(self, resp: Any) -> ModelResponse:
        """把 OpenAI SDK 响应归一为 ModelResponse。"""
        choice = resp.choices[0]
        message = choice.message
        tool_calls: list[ToolCall] = []

        for tc in (message.tool_calls or []):
            import json as _json

            try:
                args = _json.loads(tc.function.arguments)
            except _json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                    raw_arguments=tc.function.arguments,
                )
            )

        usage = TokenUsage(
            input_tokens=getattr(resp.usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(resp.usage, "completion_tokens", 0) or 0,
        )

        return ModelResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "",
            usage=usage,
            raw=resp,
        )