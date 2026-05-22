"""Cron 入口：触发 IST-Core 记忆 Dream 任务。

参考 cc-haha src/services/autoDream/，但走系统 crontab 调度而非 ide 长跑。

Crontab 示例（凌晨 3 点跑）：

    0 3 * * * cd /path/to/InfoTest_Engine && \
        .venv/bin/python -m scripts.maintenance.memory_dream \
        >> logs/dream.log 2>&1

退出码：
    0 — 成功（含被五道闸跳过的情况）
    1 — Dream 执行异常
"""

from __future__ import annotations

import logging
import sys

from main.langchain_env import langchain_load_dotenv_if_present, langchain_ensure_dashscope_api_key_from_aliases
langchain_load_dotenv_if_present()
langchain_ensure_dashscope_api_key_from_aliases()

from main.qa_agent.memory.dream import DreamTask, should_run_dream
from main.qa_agent.memory.backend import build_memory_backend, get_default_root
from main.qa_agent.memory.store import MemoryStore


def _build_llm():
    """复用 main.function_llm.chat_completion 作为 dream consolidate 阶段的 LLM。

    返回 (prompt: str) -> str 的闭包；失败时返回 None，consolidate 自然 skip。
    """
    try:
        import os
        import requests
        from main.function_llm import chat_completion

        api_key = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
        if not api_key:
            logging.warning("DASHSCOPE_API_KEY 未配置，dream LLM 关闭")
            return None
        session = requests.Session()

        def _wrapper(prompt: str) -> str:
            import json
            result = chat_completion(
                session, api_key,
                "你是 IST-Core 的 Dream 整理助手，输出严格 JSON。",
                prompt,
                max_tokens=4096,
                temperature=0.1,
            )
            return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
        return _wrapper
    except Exception as exc:
        logging.warning("function_llm.chat_completion 不可用: %s", exc)
        return None


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("memory_dream")

    ok, reason = should_run_dream()
    if not ok:
        logger.info("[dream] skip: %s", reason)
        return 0

    backend = build_memory_backend()
    store = MemoryStore(backend, get_default_root())
    # 启动时把磁盘 AGENTS.md 同步到 backend，consolidate 阶段才能读到最新
    try:
        store.sync_agents_md_to_backend()
    except Exception as exc:
        logger.debug("sync AGENTS.md 失败: %s", exc)

    task = DreamTask(store=store, llm_chat=_build_llm())
    try:
        report = task.run()
        logger.info("[dream] %s", report)
        for d in report.decisions:
            logger.info("[dream] decision: %s", d)
        return 0
    except Exception as exc:
        logger.exception("[dream] 异常退出: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
