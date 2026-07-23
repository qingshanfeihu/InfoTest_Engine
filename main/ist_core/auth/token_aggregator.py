"""token_daily_summary 聚合任务 — 已禁用（2026-07-23，项目已接入 langfuse）。

原功能：从 ist_audit.audit_log 提取 LLM 调用的 token 使用数据，
按 (user_id, date, model_name) 聚合写入 ist_audit.token_daily_summary。
保留 aggregate_daily_tokens 函数为 no-op，防止外部 import 报错。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


def aggregate_daily_tokens(target_date: Optional[date] = None) -> int:
    """token 聚合已禁用（langfuse 替代）。返回 0。"""
    logger.debug("aggregate_daily_tokens 已禁用（langfuse 替代）")
    return 0


def main() -> None:
    """CLI 入口。"""
    print("token_aggregator 已禁用（langfuse 替代）")


if __name__ == "__main__":
    main()
