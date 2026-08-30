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
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx2 as _httpx
from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from coding_agent.config import AgentConfig
from coding_agent.model.streaming import ModelStreamAccumulator, ModelStreamDelta
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

    # Streaming is enabled only on fully initialized clients. Keeping the
    # class default false preserves compatibility with lightweight test doubles
    # constructed via ``ModelClient.__new__``.
    supports_streaming = False

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
        self.supports_streaming = True

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
                status_code = getattr(e, "status_code", None)
                if status_code and 500 <= status_code < 600:
                    last_err = e
                    time.sleep(2 ** attempt)
                else:
                    raise
            except Exception:
                # 不可重试错误（如 schema 错误）
                raise

        raise RuntimeError(f"ModelClient failed after {self.max_retries} retries: {last_err}")

    def generate_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> Iterator[ModelStreamDelta]:
        """Yield provider-neutral deltas from an OpenAI-compatible stream.

        The stream itself is transient; callers that need a durable response
        should feed the deltas to :class:`ModelStreamAccumulator` and call
        ``finish`` after iteration.  Retry behavior matches ``generate`` but a
        retry only starts before any delta has been yielded.
        """
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            yielded = False
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "stream": True,
                }
                if tools:
                    kwargs["tools"] = tools
                stream = self._client.chat.completions.create(**kwargs)
                for chunk in stream:
                    for delta in self._parse_stream_chunk(chunk):
                        yielded = True
                        yield delta
                return
            except RateLimitError as e:
                last_err = e
                if yielded:
                    raise
                time.sleep(2 ** (attempt + 2))
            except APITimeoutError as e:
                last_err = e
                if yielded:
                    raise
                time.sleep(2 ** attempt)
            except APIError as e:
                status_code = getattr(e, "status_code", None)
                if status_code and 500 <= status_code < 600:
                    last_err = e
                    if yielded:
                        raise
                    time.sleep(2 ** attempt)
                else:
                    raise
            except Exception:
                raise
        raise RuntimeError(f"ModelClient streaming failed after {self.max_retries} retries: {last_err}")

    def generate_stream_response(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ModelResponse:
        """Collect ``generate_stream`` into the existing durable response type."""
        accumulator = ModelStreamAccumulator()
        for delta in self.generate_stream(messages=messages, tools=tools):
            accumulator.add(delta)
        return accumulator.finish()

    def _parse_stream_chunk(self, chunk: Any) -> list[ModelStreamDelta]:
        """Normalize one OpenAI-compatible ``ChatCompletionChunk``."""
        choices = getattr(chunk, "choices", None) or []
        usage = getattr(chunk, "usage", None)
        usage_value = None
        if usage is not None:
            usage_value = TokenUsage(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            )
        if not choices:
            return [ModelStreamDelta(usage=usage_value)] if usage_value else []
        deltas: list[ModelStreamDelta] = []
        for choice in choices:
            delta = getattr(choice, "delta", None)
            if delta is None:
                deltas.append(ModelStreamDelta(
                    finish_reason=getattr(choice, "finish_reason", None) or "",
                    usage=usage_value,
                ))
                continue
            tool_calls = getattr(delta, "tool_calls", None) or []
            if not tool_calls:
                deltas.append(ModelStreamDelta(
                    text=getattr(delta, "content", None) or "",
                    finish_reason=getattr(choice, "finish_reason", None) or "",
                    usage=usage_value,
                ))
                continue
            for call in tool_calls:
                function = getattr(call, "function", None)
                deltas.append(ModelStreamDelta(
                    text=getattr(delta, "content", None) or "",
                    tool_call_index=getattr(call, "index", None),
                    tool_call_id=getattr(call, "id", None) or "",
                    tool_name=getattr(function, "name", None) or "" if function else "",
                    arguments_delta=getattr(function, "arguments", None) or "" if function else "",
                    finish_reason=getattr(choice, "finish_reason", None) or "",
                    usage=usage_value,
                ))
        return deltas

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
            messages=messages,  # type: ignore[arg-type]
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

            parse_error: str | None = None
            try:
                args = _json.loads(tc.function.arguments)
            except _json.JSONDecodeError as exc:
                # P2-1E.1: 不再静默退化为 {}，保留错误诊断以便 parser
                # 构造明确的协议失败（is_protocol_failure=True）。
                args = {}
                parse_error = str(exc)
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                    raw_arguments=tc.function.arguments,
                    arguments_parse_error=parse_error,
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
