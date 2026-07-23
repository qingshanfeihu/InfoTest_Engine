"""TraceCollector — 已禁用（2026-07-23，项目已接入 langfuse，不再需要单独维护 trace 表）。

原功能：对话轮次 trace 聚合采集器，写入 ist_audit.trace。
保留 TraceCollector 类为 no-op 占位，防止外部 import 报错。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TraceCollector:
    """对话轮次 trace 采集器 — 已禁用。no-op 占位。"""

    def __init__(self) -> None:
        logger.debug("TraceCollector 已禁用（langfuse 替代），跳过初始化")

    def __call__(self, event) -> None:
        pass
