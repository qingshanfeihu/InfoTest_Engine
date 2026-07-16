"""F11′ 对照差分验收(2026-07-16,advisory 证据注入形态)。

理论回炉裁决(team3_theory_challenge §2.5):机械改 disposition 被否——
①对照 PASS 可能空真(778012 三连假过);②多维差异下"证伪哪条前提"欠定;
③床污染批会批量假触发。降为:机械装配 sibling_contrast 事实((44) 非空真前置
先筛)注入归因孔,判断留给 attributor;2 轮同签名复现∧非空真对照在场→advisory
陈述(禁第三轮同向重编的建议,非机械执行)。键名 sibling_contrast 冻结(乙队题面读同键)。
e2e 注入与事实落账见 test_claim_stickiness::test_e2e_claim_stickiness_and_user_stop ⑥。
"""
from __future__ import annotations

import json

import pytest

from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import views as V

A_ME, A_SIB, A_OTHER = "203600000000000101", "203600000000000102", "203600000000000103"


@pytest.fixture()
def contrast_rig(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    manifest = {"cases": [
        {"autoid": A_ME, "title": "IPv6 会话保持超时", "group_path": ["功能", "会话保持"]},
        {"autoid": A_SIB, "title": "IPv4 会话保持超时", "group_path": ["功能", "会话保持"]},
        {"autoid": A_OTHER, "title": "全域名", "group_path": ["功能", "全域名"]}]}
    monkeypatch.setattr(sh, "manifest", lambda st: manifest)
    lr = tmp_path / "last_run.json"
    lr.write_text(json.dumps([{"autoid": A_SIB, "verdict": "pass"}]), encoding="utf-8")
    return {"tmp": tmp_path, "lr_ref": "last_run.json"}


def _sib_pass_facts(lr_ref, anomaly=False):
    """兄弟案 delivery pass 的最小事实(evidence_ref 指向 rig 的 last_run)。"""
    return [{"ev": "authored", "aid": A_SIB, "round": 1, "artifact": "s1"},
            {"ev": "verdict", "aid": A_SIB, "run_id": "rs", "ctx": "delivery",
             "result": "pass", "artifact": "s1", "volume": "v",
             "signatures": [], "evidence_ref": lr_ref}]


def _vw(me_status=V.S_FAILED, sib_status=V.S_DELIVERABLE, frozen=False):
    return {"cases": {
        A_ME: {"status": me_status, "frozen": frozen},
        A_SIB: {"status": sib_status, "frozen": False},
        A_OTHER: {"status": V.S_FAILED, "frozen": False}}}


def test_sibling_contrast_split_same_group_only(contrast_rig):
    """同组兄弟分裂 passed/failed(aid 尾6+title 首行);异组不入。"""
    fs = _sib_pass_facts(contrast_rig["lr_ref"])
    out = N._sibling_contrast(A_ME, {}, fs, _vw())
    assert out is not None
    assert out["passed"] == [{"aid_tail": A_SIB[-6:], "title": "IPv4 会话保持超时"}]
    assert all(A_OTHER[-6:] != p["aid_tail"] for p in out["passed"] + out["failed"])
    assert "your judgement" in out["note"]          # 差分解释权留给孔
    assert "advisory" not in out                     # 未冻结:无禁同向建议


def test_vacuous_pass_excluded_from_contrast(contrast_rig):
    """(44) 非空真前置:对照 PASS 案记录含执行失败形态 → 剔出对照集
    (778012 三连假过——拿空真 PASS 机械"证伪"真前提=拿假证据翻真案)。"""
    lr = contrast_rig["tmp"] / "last_run.json"
    lr.write_text(json.dumps([{"autoid": A_SIB, "verdict": "pass",
                               "anomaly_lines": ["connection timed out"]}]),
                  encoding="utf-8")
    fs = _sib_pass_facts(contrast_rig["lr_ref"])
    out = N._sibling_contrast(A_ME, {}, fs, _vw())
    assert out is None or out["passed"] == []


def test_pass_without_record_is_vacuous_conservative(contrast_rig):
    """记录读不到=不可判 → 保守不作对照(无凭据的 PASS 不给假证据)。"""
    fs = [{"ev": "authored", "aid": A_SIB, "round": 1, "artifact": "s1"},
          {"ev": "verdict", "aid": A_SIB, "run_id": "rs", "ctx": "delivery",
           "result": "pass", "artifact": "s1", "volume": "v",
           "signatures": [], "evidence_ref": "nonexistent.json"}]
    assert N._pass_is_vacuous(fs, A_SIB) is True
    fs2 = _sib_pass_facts(contrast_rig["lr_ref"])
    assert N._pass_is_vacuous(fs2, A_SIB) is False


def test_advisory_on_frozen_with_nonvacuous_contrast(contrast_rig):
    """2 轮同签名复现(frozen)∧ 非空真对照 PASS 在场 → advisory 陈述在
    (禁第三轮同向重编的建议;由 attributor 判,不机械改 disposition)。"""
    fs = _sib_pass_facts(contrast_rig["lr_ref"])
    out = N._sibling_contrast(A_ME, {}, fs, _vw(frozen=True))
    assert "advisory" in out
    assert "third same-direction reflow" in out["advisory"]
    assert "expectation_suspect" in out["advisory"]


def test_contrast_switch_off(contrast_rig, monkeypatch):
    """IST_SIBLING_CONTRAST_INJECT=0 → 不注入不落事实。"""
    monkeypatch.setenv("IST_SIBLING_CONTRAST_INJECT", "0")
    fs = _sib_pass_facts(contrast_rig["lr_ref"])
    assert N._sibling_contrast(A_ME, {}, fs, _vw()) is None


def test_no_group_no_contrast(contrast_rig, monkeypatch):
    """无 group_path 的案不构造对照(脑图组是对照条件锚)。"""
    monkeypatch.setattr(sh, "manifest", lambda st: {"cases": [
        {"autoid": A_ME, "title": "t"}, {"autoid": A_SIB, "title": "t2"}]})
    fs = _sib_pass_facts(contrast_rig["lr_ref"])
    assert N._sibling_contrast(A_ME, {}, fs, _vw()) is None
