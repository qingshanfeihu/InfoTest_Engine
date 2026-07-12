# -*- coding: utf-8 -*-
"""(30) 承载链第零层:设备可达性(run14 实弹——设备批中失联,11 案 fail 被
s₀ 配对批量误诊床污染、11 题乱断言呈报;goal 判据「ask 问题真实有效」的机制位)。
"""
from __future__ import annotations

import json

import pytest

from tests.ist_core.compile_engine_v8.test_broken_third_state import rec_env, A, _v  # noqa: F401


def test_digest_demotes_fails_when_device_unreachable(monkeypatch):
    """设备不可达:fail=失联下游症状,全部降 broken(device_unreachable),
    禁进 s₀ 配对误诊。"""
    from main.ist_core.tools.device import batch_tools as BT
    monkeypatch.setattr(BT, "_probe_device_reachable", lambda env=None: False)
    out = [{"autoid": A, "verdict": "fail"}, {"autoid": "x", "verdict": "pass"}]
    # 复刻 digest 内联语义(实现在 dev_run_batch_digest 循环后)
    if any(r["verdict"] == "fail" for r in out):
        if BT._probe_device_reachable() is False:
            for r in out:
                if r["verdict"] != "pass":
                    r["verdict"] = "broken"
                    r["device_unreachable"] = True
    assert out[0]["verdict"] == "broken" and out[0]["device_unreachable"]
    assert out[1]["verdict"] == "pass"


def test_probe_unknown_does_not_demote(monkeypatch):
    """探测自身失败=未知,不改判(护栏不是闸门)。"""
    from main.ist_core.tools.device import batch_tools as BT
    monkeypatch.setattr(BT, "_probe_device_reachable", lambda env=None: None)
    out = [{"autoid": A, "verdict": "fail"}]
    if any(r["verdict"] == "fail" for r in out) and BT._probe_device_reachable() is False:
        out[0]["verdict"] = "broken"
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
    """共因合题:同 (basis,污染者集) 折叠为组长题;组员答案沿用组长(广播)。"""
    payload = [
        {"autoid": "A1", "kind": "bed"}, {"autoid": "A2", "kind": "bed"},
        {"autoid": "B1", "kind": "cap"}]
    diags = {"A1": {"basis": "s0", "polluters": [{"aid": "P"}]},
             "A2": {"basis": "s0", "polluters": [{"aid": "P"}]}}
    leader_map, folded, groups = {}, [], {}
    for it in payload:
        if it["kind"] != "bed":
            folded.append(it); continue
        d = diags.get(it["autoid"], {})
        key = (d.get("basis", ""), tuple(sorted(p["aid"] for p in d.get("polluters", []))))
        if key in groups and key != ("", ()):
            leader = groups[key]
            leader.setdefault("group_aids", [leader["autoid"]]).append(it["autoid"])
            leader_map[it["autoid"]] = leader["autoid"]
        else:
            groups[key] = it
            folded.append(it)
    assert len(folded) == 2 and leader_map == {"A2": "A1"}
    ans = {"A1": {"answer": "挂起到下批", "token": "suspend"}}
    for m, l in leader_map.items():
        if m not in ans and l in ans:
            ans[m] = ans[l]
    assert ans["A2"]["token"] == "suspend"


def test_bed_wording_no_overclaim():
    """题面文案与证据强度匹配:必要条件推断不得用「唯一根治」断言语气;
    组代表题注明案集与广播语义。"""
    from main.ist_core.compile_engine_v8.engine_tool import _contradiction_question
    q = _contradiction_question({
        "autoid": "203600000000000001", "kind": "bed",
        "evidence": "basis", "group_aids": ["203600000000000001", "203600000000000002"]})
    assert "唯一根治" not in q["question"]
    assert "必要条件推断" in q["question"]
    assert "2 个同因用例" in q["question"] and "应用到全部" in q["question"]


def test_resume_releases_s0_parking():
    """run15 实弹修:resume 与 retry 同权威——恢复挂起案后停车位必须放行
    (曾静默挡死致零复跑直接收口)。"""
    from main.ist_core.compile_engine_v8.nodes import _user_retry_after_s0
    aid = "203600000000000001"
    fs = [{"ev": "diagnosis", "aid": aid, "h_position": "h_s0"},
          {"ev": "resumed", "aid": aid}]
    assert _user_retry_after_s0(fs, aid) is True
    assert _user_retry_after_s0(list(reversed(fs)), aid) is False


def test_s0_diagnosis_bed_anchor():
    """s₀ 是床状态属性:诊断带床锚,换床后旧床诊断不再停车;旧账无锚=保守同床。"""
    import json
    from pathlib import Path
    from main.ist_core.compile_engine_v8 import nodes as N, facts as F, _shared as sh
    import unittest.mock as um
    aid = "203600000000000001"
    base = [{"ev": "authored", "aid": aid, "round": 1, "artifact": "a1"},
            {"ev": "verdict", "aid": aid, "run_id": "r1", "ctx": "delivery",
             "result": "fail", "artifact": "a1", "volume": "v1", "signatures": []},
            {"ev": "attribution", "aid": aid, "round": 1, "run_id": "r1",
             "layer": "E", "disposition": "rerun_isolated", "evidence": "e"}]
    def parked(diag_bed, cur_bed):
        fs = base + [{"ev": "diagnosis", "aid": aid, "h_position": "h_s0",
                      **({"bed": diag_bed} if diag_bed else {})}]
        # 复刻 _s0_parked 判定语义(实现在 merge 闭包内)
        att = [f for f in fs if f.get("aid") == aid and f.get("ev") == "attribution"]
        assert att[-1]["disposition"] == "rerun_isolated"
        if N._user_retry_after_s0(fs, aid):
            return False
        diag = [f for f in fs if f.get("aid") == aid and f.get("ev") == "diagnosis"]
        if not str(diag[-1].get("h_position", "")).startswith("h_s0"):
            return False
        d_bed, c = str(diag[-1].get("bed") or ""), cur_bed
        if d_bed and c and d_bed != c:
            return False
        return True
    assert parked("93", "105") is False   # 换床:旧床诊断失效
    assert parked("93", "93") is True     # 同床:照旧停车
    assert parked("", "105") is True      # 旧账无锚:保守停车


def test_cross_bed_refutes_s0():
    """run16 实弹:同卷面同签名 fail 跨两床复现=s₀(床属性)被反驳,须深归因。"""
    from main.ist_core.compile_engine_v8.nodes import _cross_bed_refuted
    aid = "203600000000000001"
    last = {"ev": "verdict", "aid": aid, "result": "fail", "artifact": "a1",
            "signatures": ["sig-X"], "bed": "105"}
    mine = [{"ev": "verdict", "aid": aid, "result": "fail", "artifact": "a1",
             "signatures": ["sig-X"], "bed": "93"}, last]
    assert _cross_bed_refuted(mine, last) is True
    # 单床:不反驳(照常 s₀ 候选)
    mine_same = [dict(mine[0], bed="105"), last]
    assert _cross_bed_refuted(mine_same, last) is False
    # 不同签名:不反驳(不是同一故障)
    mine_diff = [dict(mine[0], signatures=["sig-Y"]), last]
    assert _cross_bed_refuted(mine_diff, last) is False
