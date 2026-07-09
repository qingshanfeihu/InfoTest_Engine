"""Langfuse sink：把业务级 QA agent 事件作为 score 转发到 Langfuse（2026-07-09 替代
LangSmith feedback sink）。

主链路追踪走 ``observability.get_langfuse_handler``（LangChain callback）；本 sink 是
补充通道——把 EventBus 上的业务事件(评审结论/上机裁决等)作为 score 挂到对应 trace。
best-effort：门控 + 任何失败静默(观测设施绝不阻断主流程)。dormant(未接入 runner)时零开销。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from main.ist_core.events import IstCoreEvent

logger = logging.getLogger(__name__)


class LangfuseSink:
    """由 ``LANGFUSE_TRACING_ENABLED`` + key 门控的 best-effort Langfuse score sink。"""

    def __init__(self) -> None:
        gate = (os.environ.get("LANGFUSE_TRACING_ENABLED") or "").strip().lower()
        self.enabled = (gate not in ("0", "false", "no", "off")) and bool(
            os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))
        self._client: Any | None = None
        if self.enabled:
            try:
                from langfuse import get_client
                self._client = get_client()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Langfuse client 初始化失败: %s", exc)
                self.enabled = False

    def __call__(self, event: IstCoreEvent) -> None:
        if not self.enabled or self._client is None:
            return
        trace_id = event.get("trace_id") or event.get("run_id")
        if not trace_id:
            return   # 无 trace 锚可挂,跳过(langchain run_id ≠ langfuse trace_id 时也安全)
        try:
            self._client.create_score(
                trace_id=str(trace_id),
                name=f"qa_agent.{event.get('kind')}",
                value=0,
                comment=str({
                    "payload": event.get("payload"),
                    "tags": event.get("tags"),
                    "usage": event.get("usage"),
                    "elapsed_ms": event.get("elapsed_ms"),
                })[:1000],
            )
        except Exception:  # noqa: BLE001
            pass
