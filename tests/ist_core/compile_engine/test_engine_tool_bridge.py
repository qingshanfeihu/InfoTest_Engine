"""薄工具桥接门:interrupt payload ↔ ask_user 面板 ↔ Command(resume);
返回摘要证据门:escalated/终态 case 必须附设备回显原文摘录(复述禁凭记忆重构)。"""
from __future__ import annotations

from main.ist_core.tools.device.engine_tool import _bridge_ask, _summarize_report


def test_bridge_maps_headers_to_autoids(monkeypatch):
    import main.ist_core.tools.ask_user as AU
    seen = []

    def fake_ask(questions):
        seen.append(questions)
        return ('User has answered your questions: '
                '"欠定·900601"="改过程（加请求次数）". "欠定·900602"="改预期"')
    monkeypatch.setattr(AU.ask_user, "func", staticmethod(fake_ask))
    qs = [{"header": "欠定·900601", "question": "q1", "_autoid": "203099999999900601",
           "options": [], "multiSelect": False},
          {"header": "欠定·900602", "question": "q2", "_autoid": "203099999999900602",
           "options": [], "multiSelect": False}]
    ans = _bridge_ask(qs)
    assert ans["203099999999900601"].startswith("改过程")
    assert ans["203099999999900602"] == "改预期"
    # 内部键(_autoid)不外发给面板
    assert all(not any(k.startswith("_") for k in q) for q in seen[0])


def test_bridge_non_interactive(monkeypatch):
    import main.ist_core.tools.ask_user as AU
    monkeypatch.setattr(AU.ask_user, "func",
                        staticmethod(lambda q: "error: 当前为非交互模式,ask_user 不可用"))
    ans = _bridge_ask([{"header": "h", "question": "q", "_autoid": "a", "options": [],
                        "multiSelect": False}])
    assert ans == {"_non_interactive": True}


def test_summary_carries_escalation_evidence():
    """escalated/终态 case 逐条带 reason + 末轮 device_context 摘录 + 盘上指路。"""
    rep = {
        "outcome": "delivered_with_labels", "rounds": 3,
        "totals": {"cases": 2, "passed": 1, "escalated": 1},
        "cases": {
            "203099999999900601": {"state": "passed"},
            "203099999999900602": {
                "state": "escalated",
                "escalation_reason": "max_rounds_exhausted",
                "fail_evidence": [
                    {"round": 1, "verdict": "fail", "device_context": "r1 echo"},
                    {"round": 2, "verdict": "fail",
                     "device_context": "sdns pool member add ... ^ ERROR"},
                ]},
        },
    }
    out = _summarize_report(rep, "workspace/outputs/b/engine_report.json", "b")
    assert "…900602" in out and "max_rounds_exhausted" in out
    assert "^ ERROR" in out, "必须内联末轮设备回显原文摘录"
    assert "r1 echo" not in out, "只内联末轮,逐轮全量走盘上引用"
    assert "workspace/outputs/b/last_run.json" in out
    assert "凭记忆重构" in out


def test_summary_all_pass_has_no_evidence_section():
    rep = {"outcome": "delivered_all_pass", "rounds": 1,
           "totals": {"cases": 1, "passed": 1},
           "cases": {"203099999999900601": {"state": "passed"}}}
    out = _summarize_report(rep, "workspace/outputs/b/engine_report.json", "b")
    assert "凭记忆重构" not in out and "升级人工]" not in out
