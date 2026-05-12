from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelPresetConfig(BaseModel):
    """命名预设：可覆盖 model 的任意字段，未写的项沿用当前 model 根配置。"""

    model_name: str = ""
    description: str = ""
    provider: Literal["mock", "openai_compatible", "tongyi"] | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int | None = None


class ModelConfig(BaseModel):
    provider: Literal["mock", "openai_compatible", "tongyi"] = "mock"
    model_name: str = ""
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: int = 60
    presets: dict[str, ModelPresetConfig] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    max_steps: int = 8
    max_tool_failures: int = 3
    system_prompt: str = ""


class ProjectConfig(BaseModel):
    root: str = "."
    ignore_patterns: list[str] = Field(default_factory=list)


class ToolConfig(BaseModel):
    read_file_max_chars: int = 12000
    read_file_max_size_bytes: int = 256 * 1024  # 256KB，读取前检查文件大小
    search_max_results: int = 50  # 历史字段；search_text 默认条数见 search_default_head_limit
    search_default_head_limit: int = 250
    search_use_ripgrep: bool = False  # True：优先调用 rg；False：纯 Python（默认，适合禁 exe）
    command_timeout_seconds: int = 20
    command_output_max_chars: int = 12000


class SkillsConfig(BaseModel):
    directory: str = "./skills"


class CommandPolicyConfig(BaseModel):
    default_mode: Literal["allow", "deny", "approval"] = "approval"
    deny_rules: list[str] = Field(
        default_factory=lambda: [
            "curl", "wget", "ssh", "scp", "del", "rmdir", "rm ",
            "python -m http.server", "python3 -m http.server",
        ]
    )
    ask_rules: list[str] = Field(
        default_factory=lambda: ["python", "python3", "py ", "pip", "git commit", "git push", "pytest", "mvn test"]
    )
    allow_rules: list[str] = Field(
        default_factory=lambda: ["git status", "git diff", "git log", "dir", "type"]
    )
    blocked_patterns: list[str] = Field(
        default_factory=lambda: [
            "http://", "https://", "http.server", "SimpleHTTPServer",
            ".sh", ".bat", ".exe",
        ]
    )
    deny_operators: list[str] = Field(
        default_factory=lambda: [
            "|", ">", ">>", "<", "&&", "||", "$(",
            "&", ";", "\n", "\r",
        ]
    )
    # Backward-compatible aliases for older config files.
    blocked_prefixes: list[str] = Field(default_factory=list)
    approval_required_prefixes: list[str] = Field(default_factory=list)
    allowed_prefixes: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if self.blocked_prefixes:
            self.deny_rules = [*self.deny_rules, *self.blocked_prefixes]
        if self.approval_required_prefixes:
            self.ask_rules = [*self.ask_rules, *self.approval_required_prefixes]
        if self.allowed_prefixes:
            self.allow_rules = [*self.allow_rules, *self.allowed_prefixes]


class LoggingConfig(BaseModel):
    level: str = "INFO"


class AgentRoleInlineConfig(BaseModel):
    name: str = ""
    role: str = ""
    tools: list[str] = Field(default_factory=list)
    system_prompt_extra: str = ""


class TeamInlineConfig(BaseModel):
    mode: Literal["coordinate", "route"] = "coordinate"
    max_parallel: int = 2
    max_rounds: int = 2
    timeout_seconds: int = 300  # 整个team执行的超时时间
    max_retries: int = 2  # SubAgent失败重试次数
    max_context_messages: int = 40  # SubAgent上下文最大消息数
    trim_keep_recent: int = 20  # 裁剪时保留的最近消息数
    max_total_tokens: int = 0  # 最大token使用量限制，0表示不限制
    checkpoint_dir: str = ".code-agent/checkpoints"  # checkpoint保存目录
    roles: list[AgentRoleInlineConfig] = Field(default_factory=list)


class ContextConfig(BaseModel):
    """对话上下文与 token 预算（估算值，用于防超长与限流前兆）。"""

    budget_tokens_warn: int = 60_000
    """估算超过此值时提示用户（每轮用户输入开始时最多提示一次）。"""
    budget_tokens_compact: int = 90_000
    """估算超过此值时自动压缩历史（0 表示关闭）。需消息条数 > 4 才触发与 /compact 一致。"""
    tool_message_max_chars: int = 10_000
    """写入历史的单条 tool 返回最大字符数，超出截断。"""
    compact_keep_recent: int = 6
    """压缩时保留的最近消息条数（与粗粒度 apply_compact 一致）。"""
    compact_source_max_chars: int = 80_000
    """送入摘要模型的原文最大字符数，超出截断头尾。"""
    compact_auto_use_llm: bool = False
    """为 true 时，触发自动压缩也走模型摘要（多一次 API 调用）；默认 false 仍用粗粒度。"""


class AppConfig(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    command_policy: CommandPolicyConfig = Field(default_factory=CommandPolicyConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    team: TeamInlineConfig = Field(default_factory=TeamInlineConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)


# code-agent 安装根目录：src/code_agent/config.py → src/code_agent → src → <project_root>
_INSTALL_ROOT = Path(__file__).resolve().parent.parent.parent


class EnvSettings(BaseSettings):
    """从环境变量（含 .env 文件）读取运行时配置。

    .env 查找顺序（先找到先用）：
      1. 当前工作目录的 .env
      2. code-agent 安装目录的 .env（pip install -e 场景）
    """

    model_config = SettingsConfigDict(
        env_prefix="CODE_AGENT_",
        env_file=[".env", str(_INSTALL_ROOT / ".env")],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    config: str = "config/default.yaml"
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    project_root: str = "."


def _resolve_config_path(raw: str) -> Path:
    p = Path(raw)
    if p.is_file():
        return p
    pkg_root = Path(__file__).resolve().parent.parent.parent
    candidate = pkg_root / raw
    if candidate.is_file():
        return candidate
    return p


def apply_model_preset(model: ModelConfig, preset_key: str) -> None:
    """将命名预设合并进 model（就地修改）。presets 字典本身不变。"""
    if preset_key not in model.presets:
        raise KeyError(preset_key)
    preset = model.presets[preset_key]
    if preset.model_name:
        model.model_name = preset.model_name
    if preset.provider is not None:
        model.provider = preset.provider
    if preset.base_url is not None:
        model.base_url = preset.base_url
    if preset.api_key is not None:
        model.api_key = preset.api_key
    if preset.timeout_seconds is not None:
        model.timeout_seconds = preset.timeout_seconds


def load_config(config_path: str | None = None) -> AppConfig:
    env = EnvSettings()
    effective_path = _resolve_config_path(config_path or env.config)
    if effective_path.is_file():
        data = yaml.safe_load(effective_path.read_text(encoding="utf-8")) or {}
    else:
        data = {}
    config = AppConfig.model_validate(data)

    if env.provider:
        config.model.provider = env.provider
    if env.model:
        config.model.model_name = env.model
    if env.api_key:
        config.model.api_key = env.api_key
    if env.base_url:
        config.model.base_url = env.base_url
    if env.project_root:
        config.project.root = env.project_root

    return config
