# -*- coding: utf-8 -*-
"""(30) 承载链第零层:设备可达性——锚生产 `_apply_device_unreachable_demotion`
与 merge `s0_parked_for` / `fold_common_cause_cases`(T-1/T-2 禁复刻自测)。
"""
from __future__ import annotations

import json

from tests.ist_core.compile_engine_v8.test_broken_third_state import A  # noqa: F401


def test_digest_demotes_fails_when_device_unreachable():
    """T-1:锚生产降级入口——不可达时 fail→broken(blocked)。"""
    from main.ist_core.tools.device import batch_tools as BT
    out = [{"autoid": A, "verdict": "fail"}, {"autoid": "x", "verdict": "pass"}]
    BT._apply_device_unreachable_demotion(out, probe=lambda: False)
    assert out[0]["verdict"] == "broken" and out[0]["device_unreachable"]
    assert out[0].get("broken_subtype") == "blocked"
    assert out[1]["verdict"] == "pass"


def test_probe_unknown_does_not_demote():
    """T-1:探测未知=不改判。"""
    from main.ist_core.tools.device import batch_tools as BT
    out = [{"autoid": A, "verdict": "fail"}]
    BT._apply_device_unreachable_demotion(out, probe=lambda: None)
    assert out[0]["verdict"] == "fail"


def test_run_refuses_when_device_unreachable(monkeypatch, tmp_path):
    """run 入口拒跑:失联时上机=整轮盲跑零信息。"""
    from main.ist_core.tools.device import batch_tools as BT
    monkeypatch.setattr(BT, "_probe_device_reachable", lambda env=None: False)
    xlsx = tmp_path / "case.xlsx"
    xlsx.write_bytes(b"x")
    out = BT.dev_run_batch.func(str(xlsx), autoids_json=[A])
    d = json.loads(out)
    assert d.get("error") == "device_unreachable"


def test_group_fold_and_broadcast_semantics():
    """T-2:锚生产 fold_common_cause_cases——同 (kind,basis,污染者) 折叠;跨 kind 不合。"""
    from main.ist_core.compile_engine_v8.nodes import fold_common_cause_cases
    payload = [
        {"autoid": "A1", "kind": "bed"}, {"autoid": "A2", "kind": "bed"},
        {"autoid": "S1", "kind": "suspended"},
        {"autoid": "B1", "kind": "cap"}]
    diags = {"A1": {"basis": "s0", "polluters": [{"aid": "P"}]},
             "A2": {"basis": "s0", "polluters": [{"aid": "P"}]},
             "S1": {"basis": "s0", "polluters": [{"aid": "P"}]}}
    folded, leader_map = fold_common_cause_cases(payload, lambda a: diags.get(a, {}))
    assert len(folded) == 3 and leader_map == {"A2": "A1"}
    assert "S1" not in leader_map
    ans = {"A1": {"answer": "挂起到下批", "token": "suspend"}}
    for m, l in leader_map.items():
        if m not in ans and l in ans:
            ans[m] = ans[l]
    assert ans["A2"]["token"] == "suspend"


def test_bed_wording_no_overclaim():
    """题面文案与证据强度匹配:必要条件推断不得用「唯一根治」断言语气。"""
    from main.ist_core.compile_engine_v8.engine_tool import _contradiction_question
    q = _contradiction_question({
        "autoid": "203600000000000001", "kind": "bed",
        "evidence": "basis", "group_aids": ["203600000000000001", "203600000000000002"]})
    assert "唯一根治" not in q["question"]
    assert "必要条件推断" in q["question"]
    assert "2 个同因用例" in q["question"] and "应用到全部" in q["question"]


def test_resume_releases_s0_parking():
    """resume 与 retry 同权威——恢复挂起案后停车位必须放行。"""
    from main.ist_core.compile_engine_v8.nodes import _user_retry_after_s0
    aid = "203600000000000001"
    fs = [{"ev": "diagnosis", "aid": aid, "h_position": "h_s0"},
          {"ev": "resumed", "aid": aid}]
    assert _user_retry_after_s0(fs, aid) is True
    assert _user_retry_after_s0(list(reversed(fs)), aid) is False


def test_s0_diagnosis_bed_anchor():
    """T-2 中项:锚生产 s0_parked_for——换床旧诊断失效;同床/无锚保守停车。"""
    from main.ist_core.compile_engine_v8.nodes import s0_parked_for
    aid = "203600000000000001"
    base = [{"ev": "authored", "aid": aid, "round": 1, "artifact": "a1"},
            {"ev": "verdict", "aid": aid, "run_id": "r1", "ctx": "delivery",
             "result": "fail", "artifact": "a1", "volume": "v1", "signatures": []},
            {"ev": "attribution", "aid": aid, "round": 1, "run_id": "r1",
             "layer": "E", "disposition": "rerun_isolated", "evidence": "e"}]

    def parked(diag_bed, cur_bed):
        fs = base + [{"ev": "diagnosis", "aid": aid, "h_position": "h_s0",
                      **({"bed": diag_bed} if diag_bed else {})}]
        return s0_parked_for(fs, aid, cur_bed)

    assert parked("93", "105") is False
    assert parked("93", "93") is True
    assert parked("", "105") is True


def test_cross_bed_refutes_s0():
    """同卷面同签名 fail 跨两床复现=s₀ 被反驳。"""
    from main.ist_core.compile_engine_v8.nodes import _cross_bed_refuted
    aid = "203600000000000001"
    last = {"ev": "verdict", "aid": aid, "result": "fail", "artifact": "a1",
            "signatures": ["sig-X"], "bed": "105"}
    mine = [{"ev": "verdict", "aid": aid, "result": "fail", "artifact": "a1",
             "signatures": ["sig-X"], "bed": "93"}, last]
    assert _cross_bed_refuted(mine, last) is True
    mine_same = [dict(mine[0], bed="105"), last]
    assert _cross_bed_refuted(mine_same, last) is False
    mine_diff = [dict(mine[0], signatures=["sig-Y"]), last]
    assert _cross_bed_refuted(mine_diff, last) is False
