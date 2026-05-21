"""JSONL sink for persisting typed QA agent events."""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from main.qa_agent.events import QaAgentEvent

_LOG_ROOT = Path("logs")


class JsonlFileSink:
    """Write events to one ``run-{run_id}.jsonl`` file per run."""

    def __init__(self, *, log_dir: Path | None = None, retain_days: int = 14) -> None:
        self.log_dir = Path(log_dir) if log_dir else _LOG_ROOT
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._fhs: dict[str, Any] = {}
        self._retain_days = retain_days
        self._rotate()

    def __call__(self, event: QaAgentEvent) -> None:
        run_id = event.get("run_id") or "unknown"
        fh = self._fhs.get(run_id)
        if fh is None:
            path = self.log_dir / f"run-{run_id}.jsonl"
            fh = open(path, "a", encoding="utf-8")
            self._fhs[run_id] = fh

        fh.write(json.dumps(event, ensure_ascii=False, default=str))
        fh.write("\n")
        fh.flush()

    def close(self) -> None:
        for fh in self._fhs.values():
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass
        self._fhs.clear()

    def _rotate(self) -> None:
        cutoff = _dt.datetime.now() - _dt.timedelta(days=self._retain_days)
        for path in self.log_dir.glob("run-*.jsonl"):
            try:
                if _dt.datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                    path.unlink()
            except Exception:  # noqa: BLE001
                pass
