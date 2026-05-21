"""项目根目录 ``environment`` 加载与百炼 / DashScope API Key 别名（供管线与 LangChain 共用）。"""

from __future__ import annotations

import os
from pathlib import Path


def langchain_ensure_dashscope_api_key_from_aliases() -> None:
    """若未设置 ``DASHSCOPE_API_KEY``，则从百炼常用别名复制（控制台与文档常称百炼 Key）。"""
    cur = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if cur:
        return
    for name in ("BAILIAN_API_KEY",):
        alt = (os.environ.get(name) or "").strip()
        if alt:
            os.environ["DASHSCOPE_API_KEY"] = alt
            return


def langchain_load_dotenv_if_present() -> None:
    """从项目根加载 ``environment``（dotenv 语法；不覆盖已有环境变量），并应用 Key 别名。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        langchain_ensure_dashscope_api_key_from_aliases()
        return
    root = Path(__file__).resolve().parent.parent
    env_path = root / "environment"
    if env_path.is_file():
        load_dotenv(env_path, override=False)
    langchain_ensure_dashscope_api_key_from_aliases()
