"""V8 节点共享底座:路径/事实流装载/视图缓存/指纹/进度 emit/fork 执行器。

V6 差异:无 ledger——真理=事实流,计数=视图现算(counts_update 吃 batch_view)。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import views as V

logger = logging.getLogger(__name__)


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def outputs_root() -> Path:
    return project_root() / "workspace" / "outputs"


def facts_path(state: dict) -> Path:
    ref = str(state.get("facts_ref") or "")
    if ref:
        return project_root() / ref
    return outputs_root() / str(state.get("out_name") or "engine") / "facts.jsonl"


def load_facts(state: dict) -> list[dict]:
    return F.load_facts(facts_path(state))


def append(state: dict, new_facts: list[dict]) -> int:
    return F.append_facts(facts_path(state), new_facts)


def manifest(state: dict) -> dict:
    return read_json(project_root() / str(state.get("manifest_ref") or ""), {}) or {}


def view(state: dict, fs: list[dict] | None = None) -> dict:
    return V.batch_view(fs if fs is not None else load_facts(state), manifest(state))


def counts_update(state: dict, fs: list[dict] | None = None) -> dict:
    """视图 → 条件边计数缓存(INV-7:缓存;真理在事实流)。"""
    vw = view(state, fs)
    c = vw["counts"]
    ask_contra = sum(1 for x in vw["cases"].values()
                     if x["status"] == V.S_CONTRADICTED and x["contradictions"] >= 2)
    return {
        "n_pending": c.get(V.S_PENDING, 0),
        "n_awaiting_user": c.get(V.S_AWAITING_USER, 0),
        "n_authored": c.get(V.S_AUTHORED, 0),
        "n_failed": c.get(V.S_FAILED, 0) + c.get(V.S_CONTRADICTED, 0),
        "n_subset_verified": c.get(V.S_SUBSET_VERIFIED, 0),
        "n_deliverable": c.get(V.S_DELIVERABLE, 0),
        "n_contradicted": c.get(V.S_CONTRADICTED, 0),
        "n_settled_bad": c.get(V.S_ESCALATED, 0) + c.get(V.S_TERMINAL, 0),
        "n_ask_contradiction": ask_contra,
    }


# ── 指纹(裁决-卷面绑定的物理载体,INV-8) ─────────────────────────────────────


def artifact_fingerprint(aid: str) -> str:
    """单案卷面指纹:emit 凭证的 xlsx_mtime(工具层契约不变;无凭证=无指纹)。"""
    cred = read_json(outputs_root() / aid / ".grade_credential.json", {}) or {}
    mt = cred.get("xlsx_mtime")
    return f"{aid}:{mt}" if mt is not None else ""


def volume_fingerprint(pairs: list[tuple[str, str]]) -> str:
    """整卷组成指纹 = sorted (aid, artifact) 的 sha1(组成或任一卷面变即变)。"""
    blob = json.dumps(sorted(pairs), ensure_ascii=False)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


# ── 进度(TUI 契约与 V6 相同:fastlog 行 + engine_tick 事件) ────────────────────


def emit(text: str) -> None:
    try:
        from main.ist_core.tools.device.compile_pipeline import _emit_progress
        _emit_progress(f"[engine] {text}")
    except Exception:  # noqa: BLE001
        logger.debug("engine 进度 emit 失败", exc_info=True)


def emit_tick(state: dict, phase: str, fs: list[dict] | None = None) -> None:
    try:
        from main.ist_core.skills.loader import _fork_emit_event
        vw = view(state, fs)
        _fork_emit_event({"event": "engine_tick",
                          "run": str(state.get("out_name") or "engine"),
                          "phase": phase, "round": int(state.get("vol_seq") or 0),
                          "wave": 0, "counts": vw["counts"],
                          "total": len(vw["cases"])})
    except Exception:  # noqa: BLE001
        logger.debug("engine tick emit 失败", exc_info=True)


def fork_executor(n_items: int):
    from main.ist_core.tools.device.batch_tools import _resolve_concurrency
    from main.ist_core.resilience import AdaptiveLimiter, ForkExecutor
    ceiling = _resolve_concurrency(0, n_items=max(1, n_items))
    limiter = AdaptiveLimiter(start=max(2, ceiling // 2), min_limit=1, max_limit=ceiling)
    wc = float(os.environ.get("IST_FORK_WALLCLOCK_S") or 900)
    return ForkExecutor(limiter, wallclock_s=wc), limiter, ceiling


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def signal(name: str, subject: str, **payload) -> None:
    try:
        from main.ist_core.memory.footprint.signals import emit_signal
        emit_signal(name, subject, source="engine_v8", **payload)
    except Exception:  # noqa: BLE001
        pass
