"""engine_ledger.json:逐 case 状态机的唯一事实源(原子写,迁移合法性表内置)。

设计(V6 支柱1):E3 实证"修复轮把 pass 卷改坏"——防回退不靠约定靠数据结构:
- 迁移合法性表:`passed → pending_compile` 等非法迁移直接抛错,在数据层写不出来;
- pass 即锁:晋升 passed 时记录卷面 mtime(passed_mtime_lock),merge 前复核;
- 审计字段:每轮派发集落 audit.dispatch_sets,验收门断言 派发集 ⊆ 上轮 fail 集。

per-case 结构:
{autoid: {state, rounds_used, produced_mtime, passed_mtime_lock,
          verdict_history: [..], attribution: {layer, disposition, fix_direction},
          decision_state, frozen: bool, redispatch_reason}}
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# case 状态全集
S_PENDING = "pending_compile"
S_DISPATCHED = "dispatched"
S_PRODUCED = "produced"
S_PENDING_DECISION = "pending_decision"
S_AWAITING_USER = "awaiting_user"
S_PASSED = "passed"              # 已锁(LOCKED_PASS)
S_FAILED_ACTIVE = "failed_active"
S_FAILED_TERMINAL = "failed_terminal"   # frozen/product_defect/env_blocked/attribution_missing
S_ESCALATED = "escalated"

TERMINAL_STATES = {S_PASSED, S_FAILED_TERMINAL, S_AWAITING_USER, S_ESCALATED}

# 迁移合法性表:from → 允许的 to 集合。不在表内的迁移 = 引擎 bug,抛错。
_LEGAL: dict[str, set[str]] = {
    "": {S_PENDING},
    S_PENDING: {S_DISPATCHED},
    S_DISPATCHED: {S_PRODUCED, S_PENDING_DECISION, S_ESCALATED, S_PENDING},
    S_PENDING_DECISION: {S_AWAITING_USER, S_PENDING},          # 拿到决策 → 重派
    S_AWAITING_USER: {S_PENDING},                              # 用户后来答了
    S_PRODUCED: {S_PASSED, S_FAILED_ACTIVE, S_PRODUCED},
    S_FAILED_ACTIVE: {S_PENDING, S_FAILED_TERMINAL, S_PRODUCED, S_FAILED_ACTIVE, S_PASSED},
    # S_PASSED 无出边:pass 即锁。唯一例外经 flip_evidence(双跑翻转)显式豁免。
    S_PASSED: set(),
    S_FAILED_TERMINAL: set(),
    S_ESCALATED: set(),
}


class IllegalTransition(RuntimeError):
    """非法状态迁移=引擎 bug(如把 passed 卷送回重编)——立即崩,不静默。"""


class EngineLedger:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.data: dict = {"cases": {}, "audit": {"dispatch_sets": [], "notes": []}}
        if self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — 损坏按新账开始(引用的盘上事实仍在)
                pass
        self.data.setdefault("cases", {})
        self.data.setdefault("audit", {}).setdefault("dispatch_sets", [])
        self.data["audit"].setdefault("notes", [])

    # ---- 读 ----
    def case(self, autoid: str) -> dict:
        return self.data["cases"].setdefault(autoid, {"state": "", "rounds_used": 0,
                                                      "verdict_history": []})

    def in_state(self, *states: str) -> list[str]:
        return [a for a, c in self.data["cases"].items() if c.get("state") in states]

    def counts(self) -> dict:
        out: dict[str, int] = {}
        for c in self.data["cases"].values():
            s = c.get("state", "")
            out[s] = out.get(s, 0) + 1
        return out

    # ---- 迁移(合法性表强制) ----
    def transition(self, autoid: str, to: str, *, flip_evidence: str = "", **fields) -> None:
        c = self.case(autoid)
        frm = c.get("state", "")
        if to not in _LEGAL.get(frm, set()):
            if frm == S_PASSED and flip_evidence:
                # 双跑翻转豁免(E6 实证 778041):必须带证据,并记审计
                self.data["audit"]["notes"].append(
                    {"autoid": autoid, "event": "pass_flip", "evidence": flip_evidence})
            else:
                raise IllegalTransition(
                    f"case {autoid}: {frm or '(new)'} → {to} 不在迁移合法性表内"
                    + (";passed 卷禁止回炉(E3 修复轮回退事故的机器门)" if frm == S_PASSED else ""))
        c["state"] = to
        c.update(fields)

    def record_dispatch(self, autoids: list[str], *, round_no: int, allowed_from: set[str]) -> None:
        """派发审计:引擎每次派 worker 前登记;重派轮断言 派发集 ⊆ 允许集。"""
        self.data["audit"]["dispatch_sets"].append(
            {"round": round_no, "autoids": sorted(autoids)})
        bad = [a for a in autoids if self.case(a).get("state") not in allowed_from]
        if bad:
            raise IllegalTransition(
                f"派发集越界: {bad} 的状态不在允许集 {sorted(allowed_from)}——"
                "重派只许针对本轮 fail/pending(E3 重编范围失控的机器门)")

    # ---- pass 锁 ----
    def lock_pass(self, autoid: str, xlsx_mtime: float) -> None:
        self.transition(autoid, S_PASSED, passed_mtime_lock=xlsx_mtime)

    def verify_pass_locks(self, outputs_root: Path) -> list[str]:
        """merge 前复核:每个 passed case 的卷面 mtime 必须等于锁定值。返回被篡改清单。"""
        tampered = []
        for aid in self.in_state(S_PASSED):
            lock = self.case(aid).get("passed_mtime_lock")
            xp = outputs_root / aid / "case.xlsx"
            if lock is None or not xp.is_file():
                continue
            if abs(xp.stat().st_mtime - float(lock)) > 1e-6:
                tampered.append(aid)
        return tampered

    # ---- 落盘(原子) ----
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
