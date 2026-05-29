"""LangSmith sink for forwarding business-level QA agent events."""

from __future__ import annotations

import logging
import os
from typing import Any

from main.ist_core.events import IstCoreEvent

logger = logging.getLogger(__name__)


class LangSmithSink:
    """Best-effort LangSmith feedback sink controlled by ``LANGSMITH_TRACING``."""

    def __init__(self, *, project: str | None = None) -> None:
        self.enabled = (os.environ.get("LANGSMITH_TRACING") or "").strip().lower() == "true"
        self.project = project or os.environ.get("LANGSMITH_PROJECT") or "ultra_agent_qa"
        self._client: Any | None = None

        if self.enabled:
            try:
                from langsmith import Client  # type: ignore[import-not-found]

                self._client = Client()
            except Exception as exc:  # noqa: BLE001
                logger.warning("LangSmith Client initialization failed: %s", exc)
                self.enabled = False

    def __call__(self, event: IstCoreEvent) -> None:
        if not self.enabled or self._client is None:
            return

        try:
            self._client.create_feedback(
                run_id=event.get("run_id") or "",
                key=f"qa_agent.{event.get('kind')}",
                score=None,
                value={
                    "payload": event.get("payload"),
                    "tags": event.get("tags"),
                    "usage": event.get("usage"),
                    "elapsed_ms": event.get("elapsed_ms"),
                },
            )
        except Exception:  # noqa: BLE001
            pass
