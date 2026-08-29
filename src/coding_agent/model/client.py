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
from dataclasses import dataclass
from typing import Any

import httpx2 as _httpx
from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from coding_agent.config import AgentConfig
from coding_agent.model.types import ModelResponse, TokenUsage, ToolCall


@dataclass(frozen=True, slots=True)
class MissingCredentialsError(RuntimeError):
    """Raised when the active provider has no resolved API key.

    ``provider`` and ``suggestion`` are surfaced so the CLI/TUI can render
    a redacted, actionable error without leaking SDK internals.
    """

    provider: str
    suggestion: str

    def __str__(self) -> str:  # pragma: no cover - trivial formatting
        return (
            f"No API key resolved for provider {self.provider!r}. "
            f"{self.suggestion}"
        )


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
        proxy: str | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries

        # 默认禁用 httpx 的 env proxy 读取
        # 原因：很多用户 shell 中配置了 socks:// 之类不被 httpx 认识的 proxy scheme，
        # 会导致 "Unknown scheme for proxy URL" 错误。
        # 如需走代理访问 API，请显式传 proxy= 参数（如 "http://127.0.0.1:7890"）。
        http_client = _httpx.Client(trust_env=False, proxy=proxy)
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
            http_client=http_client,
        )

    @classmethod
    def from_config(cls, config: AgentConfig) -> ModelClient:
        """Construct from an :class:`AgentConfig` produced by ``load_config``.

        If the active provider has no resolved API key, raise
        :class:`MissingCredentialsError` rather than constructing a half-broken
        client. This is the single chokepoint where credential errors are
        surfaced; ``AgentLoop`` and the TUI catch it and display a redacted
        message instead of letting the OpenAI SDK emit its own.
        """
        if not config.api_key:
            from coding_agent.config import CROSS_PROVIDER_ENV

            envs = {
                "deepseek": "DEEPSEEK_API_KEY",
                "openai": "OPENAI_API_KEY",
                "glm": "GLM_API_KEY",
                "qwen": "QWEN_API_KEY",
                "kimi": "KIMI_API_KEY",
            }
            provider_env = envs.get(config.active_provider, CROSS_PROVIDER_ENV)
            suggestion = (
                f"Set {provider_env} in your shell, or pass --env-file pointing "
                f"to a file containing {provider_env}=... "
                f"(or {CROSS_PROVIDER_ENV}=... as a cross-provider override)."
            )
            raise MissingCredentialsError(
                provider=config.active_provider,
                suggestion=suggestion,
            )

        return cls(
            api_key=config.api_key,
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
            except Exception:
                # 不可重试错误（如 schema 错误）
                raise

        raise RuntimeError(f"ModelClient failed after {self.max_retries} retries: {last_err}")

    def chat(
        self,
        messages: list[dict],
        max_tokens: int = 500,
        temperature: float | None = None,
    ) -> str:
        """纯对话模式（不传 tools）。

        适用于闲聊 / 问答 / 解释类任务，不进入 Agent 工具循环。
        """
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=self.temperature if temperature is None else temperature,
        )
        return resp.choices[0].message.content or ""

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
