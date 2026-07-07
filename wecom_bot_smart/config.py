"""配置管理：从 environment 文件加载。"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    env_path = _PROJECT_ROOT / "environment"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
    except Exception:
        pass


_load_env()


@dataclass
class SmartBotConfig:
    """企微智能机器人配置。

    鉴权只需 Bot ID + Secret，无需 CorpID / EncodingAESKey。
    企微后台「应用管理 → 智能机器人 → API 模式 → 使用长连接」取得。
    """

    bot_id: str = field(
        default_factory=lambda: os.environ.get("WECOM_SMART_BOT_ID", "")
    )
    secret: str = field(
        default_factory=lambda: os.environ.get("WECOM_SMART_SECRET", "")
    )
    gateway_url: str = field(
        default_factory=lambda: os.environ.get("WECOM_SMART_GATEWAY_URL", "")
    )

    @property
    def is_valid(self) -> bool:
        return bool(self.bot_id and self.secret and self.gateway_url)

    def validate(self) -> None:
        missing = []
        if not self.bot_id:
            missing.append("WECOM_SMART_BOT_ID")
        if not self.secret:
            missing.append("WECOM_SMART_SECRET")
        if not self.gateway_url:
            missing.append("WECOM_SMART_GATEWAY_URL")
        if missing:
            raise ValueError(f"缺少必填环境变量: {', '.join(missing)}")


@dataclass
class ServerConfig:
    """IST-Core 调用配置。"""
    ist_timeout: int = field(
        default_factory=lambda: int(os.environ.get("WECOM_SMART_IST_TIMEOUT", "600"))
    )
    # MCP 文档工具端点（企微后台「可使用权限」授权后复制的 streamableHTTP URL）
    mcp_doc_url: str = field(
        default_factory=lambda: os.environ.get("WECOM_SMART_MCP_DOC_URL", "")
    )


smart_config = SmartBotConfig()
server_config = ServerConfig()
