"""token_daily_summary 聚合任务。

从 ist_audit.audit_log 提取 LLM 调用的 token 使用数据，
按 (user_id, date, model_name) 聚合写入 ist_audit.token_daily_summary。

用法：
    # 手动聚合昨天
    python -m main.ist_core.auth.token_aggregator

    # 聚合指定日期
    python -m main.ist_core.auth.token_aggregator 2026-06-28

    # 程序内调用
    from main.ist_core.auth.token_aggregator import aggregate_daily_tokens
    aggregate_daily_tokens(date(2026, 6, 28))
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from main.ist_core.pricing import compute_cost_rmb

logger = logging.getLogger(__name__)


def aggregate_daily_tokens(target_date: Optional[date] = None) -> int:
    """聚合指定日期的 token 使用数据。

    Args:
        target_date: 目标日期，默认昨天。

    Returns:
        写入/更新的行数。
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).date() - timedelta(days=1)

    from main.ist_core.auth.db import get_pg_connection

    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            # 从 audit_log 聚合当天 LLM 事件
            cur.execute("""
                SELECT
                    user_id,
                    DATE(recorded_at AT TIME ZONE 'UTC') AS d,
                    COALESCE(model_name, 'unknown') AS model_name,
                    COUNT(*)                          AS call_count,
                    COALESCE(SUM(token_input), 0)     AS input_tokens,
                    COALESCE(SUM(token_output), 0)    AS output_tokens,
                    COALESCE(SUM(token_cache_hit), 0) AS cache_hit,
                    COALESCE(SUM(token_cache_miss), 0) AS cache_miss
                FROM ist_audit.audit_log
                WHERE event_kind IN ('llm_end', 'llm_start')
                  AND user_id IS NOT NULL
                  AND DATE(recorded_at AT TIME ZONE 'UTC') = %s
                GROUP BY user_id, DATE(recorded_at AT TIME ZONE 'UTC'), model_name
            """, (target_date,))
            rows = cur.fetchall()

            if not rows:
                logger.info("token_aggregator: %s 无 LLM 事件", target_date)
                return 0

            upserted = 0
            for row in rows:
                model = row["model_name"]
                cost = compute_cost_rmb(
                    model,
                    input_miss=row["input_tokens"] - row["cache_hit"],
                    input_hit=row["cache_hit"],
                    output=row["output_tokens"],
                )
                cur.execute("""
                    INSERT INTO ist_audit.token_daily_summary
                        (user_id, date, model_name, call_count,
                         input_tokens, output_tokens, cache_hit, cache_miss, cost_rmb)
                    VALUES (%(user_id)s, %(date)s, %(model_name)s, %(call_count)s,
                            %(input_tokens)s, %(output_tokens)s, %(cache_hit)s, %(cache_miss)s, %(cost_rmb)s)
                    ON CONFLICT (user_id, date, model_name)
                    DO UPDATE SET
                        call_count   = EXCLUDED.call_count,
                        input_tokens = EXCLUDED.input_tokens,
                        output_tokens = EXCLUDED.output_tokens,
                        cache_hit    = EXCLUDED.cache_hit,
                        cache_miss   = EXCLUDED.cache_miss,
                        cost_rmb     = EXCLUDED.cost_rmb
                """, {
                    "user_id": row["user_id"],
                    "date": row["d"],
                    "model_name": model,
                    "call_count": row["call_count"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "cache_hit": row["cache_hit"],
                    "cache_miss": row["cache_miss"],
                    "cost_rmb": cost,
                })
                upserted += 1

            logger.info("token_aggregator: %s 聚合 %d 行", target_date, upserted)
            return upserted
    finally:
        conn.close()


def main() -> None:
    """CLI 入口。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    else:
        target = None

    count = aggregate_daily_tokens(target)
    print(f"聚合完成：{count} 行")


if __name__ == "__main__":
    main()
