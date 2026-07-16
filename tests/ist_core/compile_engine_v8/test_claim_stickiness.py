"""N1 替代验收(2026-07-16):claim 级证据粘性 + user_stop 台账本体分离。

理论回炉裁决(team3_theory_challenge §2.2):硬处置单调律被否——517027 一手复核
r1 dc 是误判、r3 降级是正确纠错,真正丢的是 r2 的另一条 claim(粒度在 claim 级);
r99 env_blocked 三例全是用户停批记账(layer=E/evidence=user),两类本体混用一个字段。
正解=①claim 级证据粘性(机械保留+注入归因 brief 为必须消费事实+静默消失落审计)
②user_stop 独立事实分离生命周期记账与语义归因(路由零变化)。
"""
from __future__ import annotations

import json

from tests.ist_core.compile_engine_v8.test_graph_scenarios import (  # noqa: F401
    AIDS, FakeDevice, rig, _run_graph, _report)

from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import render as RD

A = "209030000000000001"


# ── 单元:strong_claims 派生(517027 形态) ─────────────────────────────────────


def _att(rnd, disp, claim, ev, rid=None, **kw):
    return {"ev": "attribution", "aid": A, "round": rnd, "run_id": rid or f"r{rnd}",
            "layer": "V", "disposition": disp, "fix_direction": claim,
            "evidence": ev, **kw}


def test_strong_claims_full_history_517027_shape():
    """同标签多条独立 claim 全保留;r3 reflow 改判不清除 r1/r2 的主张。"""
    fs = [_att(1, "defect_candidate", "SDNS 不返回 AAAA 记录", "no AAAA in answer"),
          _att(2, "defect_candidate", "超时条目不清除 Timeout=0", "Timeout=0 still present"),
          _att(3, "reflow", "Round1 缺陷已修复", "uses IPv6 service IP now")]
    claims = F.strong_claims(fs, A)
    assert len(claims) == 2
    assert claims[0]["claim"] == "SDNS 不返回 AAAA 记录"
    assert claims[1]["evidence"] == "Timeout=0 still present"


def test_user_sourced_and_empty_evidence_not_claims():
    """用户裁决记账行(evidence=user)与零证据行不是设备证据主张。"""
    fs = [_att(99, "defect_candidate", "user confirmed", "user"),
          _att(1, "expectation_suspect", "no evidence claim", "")]
    assert F.strong_claims(fs, A) == []


def test_strong_claims_dedup_same_claim_across_rounds():
    """同 (disposition, claim) 跨轮重复只记首轮(防 churn 刷屏)。"""
    fs = [_att(1, "defect_candidate", "同一主张", "ev round1"),
          _att(2, "defect_candidate", "同一主张", "ev round2")]
    claims = F.strong_claims(fs, A)
    assert len(claims) == 1 and claims[0]["round"] == 1


# ── 单元:render 的本体分离面 ───────────────────────────────────────────────────


def test_diagnosis_skips_user_stop_bookkeeping_row():
    """「怎么判断的」取语义归因:517027 型案显示站立的缺陷主张,
    不显示 user_stop 记账行的假语义(契约形态 disposition=user_stop)。"""
    mine = [_att(2, "defect_candidate", "超时条目不清除", "Timeout=0 still present",
                 layer="product_defect"),
            _att(99, "user_stop", "user decision: 停止该案", "user", layer="user")]
    out = RD.diagnosis_text(mine, None)
    assert "疑似产品缺陷" in out and "Timeout=0" in out
    assert "环境" not in out


def test_remedy_user_stop_wording_and_dc_pointer():
    """user_stop 记账在:结论说「按你的止损裁决收尾」不说环境;
    历史达过 dc 的指到缺陷候选单(N1 floor 报告面)。"""
    mine = [_att(2, "defect_candidate", "超时条目不清除", "Timeout=0 still present"),
            {"ev": "user_stop", "aid": A, "question_id": "cap:x:3",
             "answer": "停止该案", "token": "stop"},
            _att(99, "user_stop", "user decision: 停止该案", "user", layer="user")]
    out = RD.remedy_text([], mine, None)
    assert "止损裁决" in out and "环境" not in out
    assert "defect_candidates.md" in out
    assert RD.leak_scan(out) == []


def test_remedy_legacy_env_blocked_wording_unchanged():
    """旧事实(无 user_stop 标记)走旧文案——向后兼容,历史批渲染不变。"""
    mine = [{"ev": "decision", "aid": A, "question_id": "q", "answer": "停止该案"},
            _att(99, "env_blocked", "user decision: 停止", "user")]
    out = RD.remedy_text([], mine, None)
    assert "按环境/取舍收尾" in out


# ── e2e:cap→停止 全链(收账透传/粘性注入/审计事实/user_stop/floor 单) ─────────────


def test_e2e_claim_stickiness_and_user_stop(rig):
    """AIDS[1] 恒 fail 三轮:attributor r1 判 dc(带表单)、后续 reflow(churn 复刻)
    → cap 问询答「停止该案」→ closing。断言五项修复的全链接线。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    c_fail = AIDS[1]
    briefs_seen: list[dict] = []
    attr_calls = {"n": 0}

    def fork(skill, brief, *, tag="", effort=""):
        env = json.loads(brief.splitlines()[0])
        aid = str(env.get("autoid"))
        if skill == "compile-worker":
            d = rig["outputs"] / aid
            d.mkdir(exist_ok=True)
            xp = d / "case.xlsx"
            xp.write_text("volume", encoding="utf-8")
            (d / ".grade_credential.json").write_text(
                json.dumps({"xlsx_mtime": xp.stat().st_mtime, "source": "lint"}),
                encoding="utf-8")
            return "done\nSTATUS: produced\nARTIFACT: case.xlsx"
        briefs_seen.append(env)
        attr_calls["n"] += 1
        from main.ist_core.tools.device.fail_attribution import _LAST_RUN_LOCK
        lrp = rig["tmp"] / str(env.get("last_run_path"))
        with _LAST_RUN_LOCK:   # 读改写整段持真锁(K1 池化后的假体纪律)
            data = json.loads(lrp.read_text(encoding="utf-8"))
            for r in data:
                if str(r.get("autoid")) == aid:
                    if attr_calls["n"] == 1:
                        r["_attribution"] = {
                            "layer": "product_defect", "disposition": "defect_candidate",
                            "fix_direction": "超时条目不清除(Timeout=0 仍在表)",
                            "evidence": f"echo for {aid} (fail)",
                            "defect_candidate": {
                                "repro": "配置会话保持并等待超时",
                                "expected_with_source": "手册:超时条目应清除",
                                "actual": "Timeout=0 条目跨超时存活"}}
                    else:
                        r["_attribution"] = {"layer": "V", "disposition": "reflow",
                                             "fix_direction": "round1 缺陷已修复",
                                             "evidence": f"echo for {aid} (fail)"}
            lrp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return "VERDICT: landed"
    rig["monkeypatch"].setattr(N, "_FORK_OVERRIDE", fork)

    dev = FakeDevice(lambda aid, ctx, n: "fail" if aid == c_fail else "pass")
    asked: list[dict] = []

    def answers(payload):
        asked.append(payload)
        return {c_fail: "停止该案"}

    res, *_ = _run_graph(rig, dev, resume_answers=answers)
    fs = F.load_facts(rig["outputs"] / rig["out_name"] / "facts.jsonl")
    mine = [f for f in fs if str(f.get("aid")) == c_fail]

    # ⓪ 接线包 2e:cap 题 item 携 claim_history(键名冻结,全轮归因史、r99 不入)
    # ——churn 后 r1 dc 主张仍在题面数据(517027「题面失忆」修复的引擎侧)
    cap_items = [it for p in asked for it in (p.get("cases") or [])
                 if it.get("kind") == "cap" and it.get("autoid") == c_fail]
    assert cap_items and cap_items[0].get("claim_history")
    _hist = cap_items[0]["claim_history"]
    assert any(h["disposition"] == "defect_candidate" for h in _hist)
    assert all(set(h) >= {"round", "layer", "disposition", "claim", "evidence"}
               for h in _hist)                       # 乙契约键形态逐字

    # ① P0 C20 收账透传:dc 表单进事实流(不再随 last_run 湮灭)
    dc_atts = [f for f in mine if f.get("ev") == "attribution"
               and f.get("disposition") == "defect_candidate"
               and isinstance(f.get("defect_candidate"), dict)]
    assert dc_atts and dc_atts[0]["defect_candidate"]["actual"] == "Timeout=0 条目跨超时存活"

    # ② N1b 注入:第二次归因派发的 brief env 携历史强 claim(必须消费事实)
    later = [e for e in briefs_seen if e.get("strong_claims")]
    assert later, "第二轮起归因 env 必须携带 strong_claims"
    sc = later[0]["strong_claims"]
    assert sc["claims"][0]["disposition"] == "defect_candidate"
    assert "Timeout=0" in sc["claims"][0]["claim"]
    assert "must" in sc["note"] or "not silently vanish" in sc["note"]

    # ③ N1b 审计:dc 被 reflow 覆盖 → strong_claim_unaddressed 落账(不硬拒)
    unaddr = [f for f in mine if f.get("ev") == "strong_claim_unaddressed"]
    assert unaddr and unaddr[0]["to"] == "reflow"
    assert any("defect_candidate@r" in p for p in unaddr[0]["prior"])

    # ④ N1a user_stop 分离(契约形态):独立事实 + 记账行 layer:"user"/
    # disposition:"user_stop"(非 env 题面),不再写假的"环境阻塞"语义;
    # 终态路由不变(views/report_gate 终态元组已收 user_stop)
    us = [f for f in mine if f.get("ev") == "user_stop"]
    assert us and us[0]["token"] == "stop" and us[0]["answer"] == "停止该案"
    stop_att = [f for f in mine if f.get("ev") == "attribution"
                and int(f.get("round") or 0) == 99]
    assert stop_att and stop_att[-1]["disposition"] == "user_stop"
    assert stop_att[-1]["layer"] == "user"
    rep = _report(rig)
    assert rep["cases"][c_fail]["status"] == "failed_terminal"

    # ⑤ P0 C20 floor:dc 虽被 reflow 覆盖、案终态 user-stop,候选单仍列它(带轨迹)
    mdir = rig["outputs"] / rig["out_name"]
    assert (mdir / "defect_candidates.json").is_file()
    data = json.loads((mdir / "defect_candidates.json").read_text(encoding="utf-8"))
    entry = next(e for e in data if e["autoid"] == c_fail)
    assert entry["form"]["repro"] and entry["claims"]
    trail = [t["disposition"] for t in entry["disposition_trail"]]
    assert "defect_candidate" in trail and "reflow" in trail
    assert rep["defect_candidates"]["count"] >= 1

    # ⑥ F11′ 对照:同组兄弟 pass → env 携 sibling_contrast + 事实落账(键名冻结)
    assert any(e.get("sibling_contrast") for e in briefs_seen)
    scf = [f for f in mine if f.get("ev") == "sibling_contrast"]
    assert scf and isinstance(scf[0].get("passed"), list)
