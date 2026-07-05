"""节点共享底座:路径解析/ledger 装载/计数聚合/进度 emit/fork 执行器。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from main.ist_core.compile_engine import ledger as L

logger = logging.getLogger(__name__)


def project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def outputs_root() -> Path:
    return project_root() / "workspace" / "outputs"


def load_ledger(state: dict) -> L.EngineLedger:
    ref = state.get("ledger_ref") or ""
    path = project_root() / ref if ref else (
        outputs_root() / str(state.get("out_name") or "engine") / "engine_ledger.json")
    return L.EngineLedger(path)


def counts_update(led: L.EngineLedger) -> dict:
    """由 ledger 聚合出条件边所需的全部机读计数(state 只放计数,明细在盘)。"""
    c = led.counts()
    return {
        "n_pending_compile": c.get(L.S_PENDING, 0),
        "n_pending_decision": c.get(L.S_PENDING_DECISION, 0),
        "n_awaiting_user": c.get(L.S_AWAITING_USER, 0),
        "n_produced": c.get(L.S_PRODUCED, 0),
        "n_passed": c.get(L.S_PASSED, 0),
        "n_failed_active": c.get(L.S_FAILED_ACTIVE, 0),
        "n_failed_terminal": c.get(L.S_FAILED_TERMINAL, 0) + c.get(L.S_ESCALATED, 0),
    }


def emit(text: str) -> None:
    """进度到 TUI(bus evidence 行)+fastlog,复用 pipeline 通道;失败静默。"""
    try:
        from main.ist_core.tools.device.compile_pipeline import _emit_progress
        _emit_progress(f"[engine] {text}")
    except Exception:  # noqa: BLE001
        logger.debug("engine 进度 emit 失败", exc_info=True)


def fork_executor(n_items: int):
    """[llm] 孔的执行器:AdaptiveLimiter+看门狗+transient 重试(步骤1 抽取件)。"""
    from main.ist_core.tools.device.batch_tools import _resolve_concurrency
    from main.ist_core.resilience import AdaptiveLimiter, ForkExecutor
    ceiling = _resolve_concurrency(0, n_items=max(1, n_items))
    limiter = AdaptiveLimiter(start=max(2, ceiling // 2), min_limit=1, max_limit=ceiling)
    return ForkExecutor(limiter), limiter, ceiling


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def env_flag(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() not in ("0", "false", "no")
