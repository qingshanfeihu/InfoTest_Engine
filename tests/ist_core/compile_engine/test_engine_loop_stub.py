"""stub 全循环门(P1-G1b/G1c):假 worker+假 digest 跑完整闭环。

轮1 上机 2 fail/1 pass → 定向重编(重派集==fail 集)→ 轮2 子集全 pass →
终验整卷全 pass → 写回 → report.delivered_all_pass。
并验:pass 卷 mtime 全程不变(E3 回退锁)/audit 派发集/终态计数。
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

import main.ist_core.compile_engine.nodes.compile_phase as CP
import main.ist_core.compile_engine.nodes as N
import main.ist_core.compile_engine.nodes.verify_phase as VP
import main.ist_core.compile_engine.nodes._shared as SH
from main.ist_core.compile_engine.graph import build_compile_engine_graph

_ROOT = Path(__file__).resolve().parents[3]
_OUT = "engine_stub_ut"
_AIDS = ["203099999999900501", "203099999999900502", "203099999999900503"]


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    # 隔离 outputs 根(节点全经 _shared 取路径)
    out_root = tmp_path / "outputs"
    out_root.mkdir()
    monkeypatch.setattr(SH, "project_root", lambda: tmp_path)
    monkeypatch.setattr(SH, "outputs_root", lambda: out_root)
    monkeypatch.setattr(SH, "emit", lambda text: None)

    # prep stub:manifest+cases
    def fake_prep(state):
        out_name = _OUT
        (out_root / out_name).mkdir(exist_ok=True)
        mf = out_root / out_name / "manifest.json"
        mf.write_text(json.dumps({"cases": [{"autoid": a} for a in _AIDS]}), encoding="utf-8")
        led = SH.load_ledger({**state, "out_name": out_name,
                              "ledger_ref": f"outputs/{out_name}/engine_ledger.json"})
        from main.ist_core.compile_engine import ledger as L
        for a in _AIDS:
            if not led.case(a).get("state"):
                led.transition(a, L.S_PENDING)
        led.save()
        return {"phase_status": "ok", "out_name": out_name,
                "manifest_ref": f"outputs/{out_name}/manifest.json",
                "ledger_ref": str(led.path.relative_to(tmp_path)),
                "round": 0, "wave": 0, **SH.counts_update(led)}
    monkeypatch.setattr(N, "prep", fake_prep)   # 图从 nodes 包 getattr 绑定节点

    # worker stub:落 xlsx + produced
    def fake_dispatch(executor, aid, brief, t0):
        d = out_root / aid
        d.mkdir(exist_ok=True)
        (d / "case.xlsx").write_bytes(b"x" + aid.encode())
        from main.ist_core.compile_engine import ledger as L
        return L.S_PRODUCED, "stub"
    monkeypatch.setattr(CP, "_dispatch_one", fake_dispatch)
    monkeypatch.setattr(SH, "fork_executor", lambda n: (object(), _NullLimiter(), 2))

    # 探针 stub:干净
    import main.ist_core.tools.device.compile_pipeline as PIPE
    monkeypatch.setattr(PIPE, "_grade_extract_facts", lambda aid: {}, raising=False)

    # merge stub:拼一个合并卷文件
    import main.ist_core.tools.device.emit_xlsx_tool as EM

    def fake_merged(autoids=None, out_name="", **kw):
        d = out_root / out_name
        d.mkdir(exist_ok=True)
        (d / "case.xlsx").write_text(",".join(sorted(autoids or [])), encoding="utf-8")
        return f"已合并 {len(autoids or [])}"
    monkeypatch.setattr(EM.compile_emit_merged, "func", staticmethod(fake_merged))

    # digest stub:轮1 = 502/503 fail(_attribution: reflow),501 pass;轮2+ = 全 pass
    import main.ist_core.tools.device.batch_tools as BT
    calls = {"n": 0}

    def fake_digest(xlsx_path, *a, **kw):
        calls["n"] += 1
        xp = Path(xlsx_path)
        aids = xp.read_text(encoding="utf-8").split(",")
        recs = []
        for aid in aids:
            fail = calls["n"] == 1 and aid in (_AIDS[1], _AIDS[2])
            recs.append({"autoid": aid, "verdict": "fail" if fail else "pass",
                         "device_context": "stub ctx",
                         "_attribution": ({"layer": "V", "disposition": "reflow",
                                           "fix_direction": "stub fix"} if fail else {})})
        (xp.parent / "last_run.json").write_text(json.dumps(recs), encoding="utf-8")
        return "digest ok"
    monkeypatch.setattr(BT.dev_run_batch_digest, "func", staticmethod(fake_digest))

    # writeback stub:零副作用
    monkeypatch.setattr(N, "writeback", lambda state: {"phase_status": "ok"})
    yield


class _NullLimiter:
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_engine_ticks_selfcontained_counts(monkeypatch):
    """engine_tick 事件门:节点边界+每 case 落账后发,自含全量 counts(消费端纯覆盖)。"""
    import main.ist_core.skills.loader as loader
    events: list[dict] = []
    monkeypatch.setattr(loader, "_fork_emit_event", lambda r: events.append(r))

    graph = build_compile_engine_graph()
    graph.invoke({"mindmap_path": "x.txt", "product_version": "10.5",
                  "out_name": _OUT, "max_rounds": 3},
                 {"configurable": {"thread_id": "t-tick"}, "recursion_limit": 60})

    ticks = [e for e in events if e.get("event") == "engine_tick"]
    assert ticks, "引擎全程未发 engine_tick"
    phases = {t["phase"] for t in ticks}
    assert {"worker_fanout", "merge", "run_digest", "attribute", "report"} <= phases
    for t in ticks:
        assert t["run"] == _OUT
        assert t["total"] == len(_AIDS), "counts 必须自含全量(乱序/丢事件容忍的前提)"
        assert set(t["counts"]) == {"pending", "dispatched", "produced", "pending_decision",
                                    "awaiting_user", "passed", "failed_active",
                                    "failed_terminal", "escalated"}
    # worker_fanout 每 case 落账即 tick:首轮 3 case + 重编轮 ≥2
    assert sum(1 for t in ticks if t["phase"] == "worker_fanout") >= len(_AIDS)
    assert ticks[-1]["phase"] == "report" and ticks[-1]["counts"]["passed"] == len(_AIDS)


def test_full_loop_to_delivered():
    graph = build_compile_engine_graph()
    res = graph.invoke({"mindmap_path": "x.txt", "product_version": "10.5",
                        "out_name": _OUT, "max_rounds": 3},
                       {"configurable": {"thread_id": "t1"}, "recursion_limit": 60})
    led = SH.load_ledger({"out_name": _OUT,
                          "ledger_ref": f"outputs/{_OUT}/engine_ledger.json"})
    rep = json.loads((SH.outputs_root() / _OUT / "engine_report.json").read_text(encoding="utf-8"))

    assert rep["outcome"] == "delivered_all_pass", rep
    assert rep["totals"]["passed"] == 3
    assert rep["rounds"] >= 2                       # 首跑+子集复验(+终验)
    # 回退锁:501 首轮 pass 后卷面 mtime 不再变(fake worker 只在重派时写文件)
    dispatches = rep["audit"]["dispatch_sets"]
    assert dispatches[0]["autoids"] == sorted(_AIDS)
    # 重派集 == 轮1 fail 集(不多不少)
    redisp = dispatches[1]["autoids"]
    assert redisp == sorted([_AIDS[1], _AIDS[2]]), redisp
    # pass 卷 mtime 锁在账
    assert led.case(_AIDS[0]).get("passed_mtime_lock")


def test_prep_error_emits_engine_tick(monkeypatch, tmp_path):
    """prep 失败早退仍发 engine_tick(TUI 引擎卡不卡在旧态)。"""
    import main.ist_core.skills.loader as loader
    events: list[dict] = []
    monkeypatch.setattr(loader, "_fork_emit_event", lambda r: events.append(r))

    # 脑图不存在 → compile_prep 报错且不落 manifest → prep 早退 error
    res = CP.prep({"mindmap_path": "no_such_mindmap.txt", "out_name": "dongkl"})
    assert res["phase_status"] == "error"
    ticks = [e for e in events if e.get("event") == "engine_tick"]
    assert len(ticks) == 1
    assert ticks[0]["phase"] == "prep"
    assert ticks[0]["run"] == "dongkl"


def test_ask_decision_validate_error_emits_engine_tick(monkeypatch, tmp_path):
    """ask_decision 模板自检失败早退仍发 engine_tick。"""
    out_root = SH.outputs_root()
    import main.ist_core.skills.loader as loader
    from main.ist_core.compile_engine import ledger as L

    events: list[dict] = []
    monkeypatch.setattr(loader, "_fork_emit_event", lambda r: events.append(r))

    out_name = "askq_err_ut"
    (out_root / out_name).mkdir(exist_ok=True)
    led_path = out_root / out_name / "engine_ledger.json"
    led = L.EngineLedger(led_path)
    aid = _AIDS[0]
    led.transition(aid, L.S_PENDING)
    led.transition(aid, L.S_DISPATCHED)
    led.transition(aid, L.S_PENDING_DECISION)
    led.save()

    aid_dir = out_root / aid
    aid_dir.mkdir(exist_ok=True)
    (aid_dir / "needs_decision.json").write_text(
        json.dumps({"claims": [{"reason": "stub", "claim_kind": "distribution"}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(CP, "validate_questions", lambda _q, _l: False)

    state = {"out_name": out_name,
             "ledger_ref": f"outputs/{out_name}/engine_ledger.json", "round": 0}
    res = CP.ask_decision(state)
    assert res["phase_status"] == "error"
    ticks = [e for e in events if e.get("event") == "engine_tick"]
    assert len(ticks) == 1
    assert ticks[0]["phase"] == "ask_decision"
    assert ticks[0]["run"] == out_name
