"""Agent 配置：使用 Pydantic Settings 从环境变量与 .env 读取。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseSettings):
    """Agent 运行时配置。

    设计原则：所有可调参数集中在此，便于 benchmark 时按任务微调。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM API ---
    active_model: str = Field(default="deepseek-chat", description="当前使用的模型")
    active_base_url: str = Field(
        default="https://api.deepseek.com/v1",
        description="当前使用的 OpenAI 兼容 base URL",
    )
    api_key: str = Field(default="", description="从 DEEPSEEK_API_KEY / OPENAI_API_KEY 等读取")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    # --- Agent 行为参数 ---
    max_steps: int = Field(default=50, gt=0)
    max_model_calls: int = Field(default=80, gt=0)
    max_wall_time: int = Field(default=1800, gt=0, description="秒")
    command_timeout: int = Field(default=60, gt=0, description="单条 shell 命令超时")
    max_tool_output: int = Field(default=50000, gt=0, description="字节")

    # --- Context ---
    context_budget: int = Field(default=32000, gt=0, description="Active Context token 上限")
    recent_turns: int = Field(default=10, gt=0, description="Recent Interaction 保留轮数")

    # --- 模式开关 ---
    enable_failure_refresh: bool = Field(default=True)
    benchmark_mode: bool = Field(default=False, description="禁止 ask_user 等交互行为")

    # --- 日志 ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    log_json: bool = Field(default=True)

    # --- Workspace ---
    workspace_root: Path = Field(default=Path("./workspace"))


def load_config() -> AgentConfig:
    """加载配置：优先 .env，其次环境变量。"""
    return AgentConfig()