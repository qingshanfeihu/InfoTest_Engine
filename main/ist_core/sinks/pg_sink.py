"""PgAuditSink — 已禁用（2026-07-23，项目已接入 langfuse，不再需要单独维护 audit_log）。

原功能：Redis 缓存 + 后台消费者批量写 PostgreSQL ist_audit.audit_log 表。
保留代码供参考，PgAuditSink 类不再被任何入口注册。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PgAuditSink:
    """审计日志 sink — 已禁用。注册为 no-op 占位，防止外部 import 报错。"""

    def __init__(self, **kwargs) -> None:
        logger.debug("PgAuditSink 已禁用（langfuse 替代），跳过初始化")

    def __call__(self, event) -> None:
        pass

    def shutdown(self, timeout: float = 5.0) -> None:
        pass

