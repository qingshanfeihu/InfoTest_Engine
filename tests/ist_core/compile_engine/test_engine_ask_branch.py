"""欠定分支门(P1-G1d)+resume 门(P1-G1f)。

守:worker 报欠定→图 interrupt 挂起(payload 含 autoid 全名+顺序语义句)→
Command(resume=答案) 续跑→user_decision 由工具落盘→重派;非交互答案→awaiting_user
不阻塞其余;checkpoint 下中断后重 invoke 从挂起点继续(prep/worker 零重跑)。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import main.ist_core.compile_engine.nodes.compile_phase as CP
import main.ist_core.compile_engine.nodes as N
import main.ist_core.compile_engine.nodes._shared as SH
from main.ist_core.compile_engine.graph import build_compile_engine_graph
from main.ist_core.compile_engine import ledger as L

_OUT = "engine_ask_ut"
_A_OK = "203099999999900601"
_A_UD = "203099999999900602"   # 欠定 case(ordering_sensitive)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    out_root = tmp_path / "outputs"
    out_root.mkdir()
    monkeypatch.setattr(SH, "project_root", lambda: tmp_path)
    monkeypatch.setattr(SH, "outputs_root", lambda: out_root)
    monkeypatch.setattr(SH, "emit", lambda text: None)
    calls = {"prep": 0, "dispatch": 0}

    def fake_prep(state):
        calls["prep"] += 1
        (out_root / _OUT).mkdir(exist_ok=True)
        led = SH.load_ledger({"out_name": _OUT,
                              "ledger_ref": f"outputs/{_OUT}/engine_ledger.json"})
        for a in (_A_OK, _A_UD):
            if not led.case(a).get("state"):
                led.transition(a, L.S_PENDING)
        led.save()
        return {"phase_status": "ok", "out_name": _OUT,
                "manifest_ref": f"outputs/{_OUT}/manifest.json",
                "ledger_ref": str(led.path.relative_to(tmp_path)),
                "round": 0, "wave": 0, **SH.counts_update(led)}
    monkeypatch.setattr(N, "prep", fake_prep)

    def fake_dispatch(executor, aid, brief, t0):
        calls["dispatch"] += 1
        d = out_root / aid
        d.mkdir(exist_ok=True)
        if aid == _A_UD and not (d / "user_decision.json").is_file():
            (d / "needs_decision.json").write_text(json.dumps({
                "autoid": aid, "claims": [{
                    "claim_kind": "absolute_position", "ordering_sensitive": True,
                    "reason": "绝对位置不可证伪", "min_requests": 3,
                    "suggested_fix": "改预期"}]}, ensure_ascii=False), encoding="utf-8")
            return L.S_PENDING_DECISION, "stub 欠定"
        (d / "case.xlsx").write_bytes(b"x")
        return L.S_PRODUCED, "stub"
    monkeypatch.setattr(CP, "_dispatch_one", fake_dispatch)
    monkeypatch.setattr(SH, "fork_executor", lambda n: (object(), _Null(), 2))
    import main.ist_core.tools.device.compile_pipeline as PIPE
    monkeypatch.setattr(PIPE, "_grade_extract_facts", lambda aid: {}, raising=False)

    # 先问后落门的台账:补一条含 autoid 的问答记录到 tmp 根(工具读真实 runtime——
    # 这里直接 patch compile_user_decision 内的 root 不可行,改放行:写记录进真实
    # runtime 会污染——patch verifiability_tool 的 Path 解析太深。简化:monkeypatch
    # 工具 func 为记录调用的假实现(门语义已有独立回归 test_user_decision_tool)。
    ud_calls = []
    import main.ist_core.tools.device.verifiability_tool as VT

    def fake_ud(aid, decision, assertion_form="", note="", drop_ordering=False):
        ud_calls.append({"aid": aid, "decision": decision, "form": assertion_form,
                         "drop": drop_ordering})
        (out_root / aid / "user_decision.json").write_text(json.dumps(
            {"autoid": aid, "decision": decision,
             "expected_assertion_form": assertion_form}), encoding="utf-8")
        return "已落盘"
    monkeypatch.setattr(VT.compile_user_decision, "func", staticmethod(fake_ud))

    def fake_merged(autoids=None, out_name="", **kw):
        d = out_root / out_name
        d.mkdir(exist_ok=True)
        (d / "case.xlsx").write_text(",".join(sorted(autoids or [])), encoding="utf-8")
        return "已合并"
    import main.ist_core.tools.device.emit_xlsx_tool as EM
    monkeypatch.setattr(EM.compile_emit_merged, "func", staticmethod(fake_merged))

    def fake_digest(xlsx_path, *a, **kw):
        xp = Path(xlsx_path)
        aids = xp.read_text(encoding="utf-8").split(",")
        (xp.parent / "last_run.json").write_text(json.dumps(
            [{"autoid": a, "verdict": "pass"} for a in aids]), encoding="utf-8")
        return "ok"
    import main.ist_core.tools.device.batch_tools as BT
    monkeypatch.setattr(BT.dev_run_batch_digest, "func", staticmethod(fake_digest))
    monkeypatch.setattr(N, "writeback", lambda state: {"phase_status": "ok"})
    yield calls, ud_calls


class _Null:
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _init_state():
    return {"mindmap_path": "x.txt", "product_version": "10.5",
            "out_name": _OUT, "max_rounds": 3}


def test_interrupt_payload_and_resume_to_delivery(_env):
    calls, ud_calls = _env
    graph = build_compile_engine_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "ask1"}, "recursion_limit": 60}
    res = graph.invoke(_init_state(), cfg)
    intr = res.get("__interrupt__")
    assert intr, "欠定应触发图级挂起"
    payload = intr[0].value
    qs = payload["questions"]
    text = json.dumps(qs, ensure_ascii=False)
    assert _A_UD in text and "顺序语义" in text            # autoid 全名+顺序句
    # 用户答「改预期」(选项文本已写明放弃顺序)
    res2 = graph.invoke(Command(resume={_A_UD: "改预期"}), cfg)
    assert not res2.get("__interrupt__")
    assert ud_calls and ud_calls[0]["aid"] == _A_UD
    assert ud_calls[0]["drop"] is True                     # 改预期+ordering → 显式放弃
    rep = json.loads((SH.outputs_root() / _OUT / "engine_report.json").read_text(encoding="utf-8"))
    assert rep["outcome"] == "delivered_all_pass"
    # resume 后 prep 幂等重跑但 case 不重置(ledger 已有状态)
    assert calls["prep"] >= 1


def test_non_interactive_marks_awaiting_and_delivers_rest(_env):
    calls, ud_calls = _env
    graph = build_compile_engine_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "ask2"}, "recursion_limit": 60}
    res = graph.invoke(_init_state(), cfg)
    assert res.get("__interrupt__")
    res2 = graph.invoke(Command(resume={"_non_interactive": True}), cfg)
    rep = json.loads((SH.outputs_root() / _OUT / "engine_report.json").read_text(encoding="utf-8"))
    assert rep["outcome"] == "delivered_with_labels"       # 601 pass + 602 awaiting
    assert rep["totals"]["passed"] == 1
    assert rep["cases"][_A_UD]["state"] == "awaiting_user"
    assert not ud_calls                                     # 没批过就绝不落决策


def test_resume_after_crash_skips_completed_phases(_env, monkeypatch):
    # resume 门(P1-G1f):digest 首调抛错中断 → 同 thread 重 invoke → 从断点继续,
    # worker 不重派(dispatch 计数不增)。
    calls, _ = _env
    import main.ist_core.tools.device.batch_tools as BT
    real = BT.dev_run_batch_digest.func
    state = {"boom": True}

    def flaky(xlsx_path, *a, **kw):
        if state.pop("boom", False):
            raise RuntimeError("simulated crash")
        return real(xlsx_path, *a, **kw)
    monkeypatch.setattr(BT.dev_run_batch_digest, "func", staticmethod(flaky))

    graph = build_compile_engine_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "resume1"}, "recursion_limit": 60}
    res = graph.invoke(_init_state(), cfg)
    if res.get("__interrupt__"):
        with pytest.raises(RuntimeError, match="simulated crash"):
            graph.invoke(Command(resume={_A_UD: "改预期"}), cfg)
    d_before = calls["dispatch"]
    res2 = graph.invoke(None, cfg)          # 崩后重 invoke:从 run_digest 续
    assert calls["dispatch"] == d_before    # worker 零重派
    rep = json.loads((SH.outputs_root() / _OUT / "engine_report.json").read_text(encoding="utf-8"))
    assert rep["outcome"] == "delivered_all_pass"
