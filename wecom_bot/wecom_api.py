"""企微 API 客户端（纯同步 requests，供后台线程调用）。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

from .config import wecom_config

logger = logging.getLogger("wecom_bot.api")

_WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


class WeComAPIClient:
    def __init__(self, corp_id: str, app_secret: str, agent_id: int) -> None:
        self._corp_id = corp_id
        self._app_secret = app_secret
        self._agent_id = agent_id
        self._token: str = ""
        self._token_expires_at: float = 0.0
        self._lock = threading.Lock()

    def get_access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at - 120:
            return self._token

        with self._lock:
            if self._token and now < self._token_expires_at - 120:
                return self._token

            url = f"{_WECOM_API_BASE}/gettoken"
            params = {"corpid": self._corp_id, "corpsecret": self._app_secret}
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            errcode = data.get("errcode", -1)
            if errcode != 0:
                raise RuntimeError(
                    f"获取 access_token 失败: errcode={errcode} "
                    f"errmsg={data.get('errmsg', 'unknown')}"
                )

            self._token = data["access_token"]
            self._token_expires_at = now + data.get("expires_in", 7200)
            logger.info("access_token 已刷新")
            return self._token

    def send_markdown(self, content: str, touser: str) -> dict[str, Any]:
        token = self.get_access_token()
        url = f"{_WECOM_API_BASE}/message/send?access_token={token}"
        body: dict[str, Any] = {
            "touser": touser,
            "msgtype": "markdown",
            "agentid": self._agent_id,
            "markdown": {"content": content},
        }
        resp = requests.post(url, json=body, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode", -1) != 0:
            logger.error("推送 Markdown 失败: errcode=%s", data.get("errcode"))
        else:
            logger.info("Markdown 已推送至 %s", touser)
        return data

    def send_text(self, content: str, touser: str) -> dict[str, Any]:
        token = self.get_access_token()
        url = f"{_WECOM_API_BASE}/message/send?access_token={token}"
        body: dict[str, Any] = {
            "touser": touser,
            "msgtype": "text",
            "agentid": self._agent_id,
            "text": {"content": content},
        }
        resp = requests.post(url, json=body, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode", -1) != 0:
            logger.error("推送文本失败: errcode=%s", data.get("errcode"))
        return data


_api_client: WeComAPIClient | None = None


def get_api_client() -> WeComAPIClient:
    global _api_client
    if _api_client is None:
        _api_client = WeComAPIClient(
            corp_id=wecom_config.corp_id,
            app_secret=wecom_config.app_secret,
            agent_id=wecom_config.agent_id,
        )
    return _api_client
