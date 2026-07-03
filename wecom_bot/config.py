"""配置管理：从环境变量 & 项目 environment 文件加载。"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_project_env() -> None:
    env_path = _PROJECT_ROOT / "environment"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
    except Exception:
        pass


_load_project_env()


@dataclass
class WeComConfig:
    token: str = field(default_factory=lambda: os.environ.get("WECOM_TOKEN", ""))
    encoding_aes_key: str = field(
        default_factory=lambda: os.environ.get("WECOM_ENCODING_AES_KEY", "")
    )
    corp_id: str = field(default_factory=lambda: os.environ.get("WECOM_CORP_ID", ""))
    agent_id: int = field(
        default_factory=lambda: int(os.environ.get("WECOM_AGENT_ID", "0"))
    )
    app_secret: str = field(
        default_factory=lambda: os.environ.get("WECOM_APP_SECRET", "")
    )

    @property
    def is_valid(self) -> bool:
        return bool(
            self.token and self.encoding_aes_key and self.corp_id
            and self.agent_id and self.app_secret
        )

    def validate(self) -> None:
        missing = []
        if not self.token:
            missing.append("WECOM_TOKEN")
        if not self.encoding_aes_key:
            missing.append("WECOM_ENCODING_AES_KEY")
        elif len(self.encoding_aes_key) != 43:
            raise ValueError(
                f"WECOM_ENCODING_AES_KEY 长度必须为 43，实际: {len(self.encoding_aes_key)}"
            )
        if not self.corp_id:
            missing.append("WECOM_CORP_ID")
        if not self.agent_id:
            missing.append("WECOM_AGENT_ID")
        if not self.app_secret:
            missing.append("WECOM_APP_SECRET")
        if missing:
            raise ValueError(f"缺少必填环境变量: {', '.join(missing)}")


@dataclass
class ServerConfig:
    host: str = field(default_factory=lambda: os.environ.get("WECOM_BOT_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("WECOM_BOT_PORT", "8088")))
    sync_timeout: int = field(
        default_factory=lambda: int(os.environ.get("WECOM_SYNC_TIMEOUT", "5"))
    )
    ist_timeout: int = field(
        default_factory=lambda: int(os.environ.get("WECOM_IST_TIMEOUT", "300"))
    )


wecom_config = WeComConfig()
server_config = ServerConfig()
