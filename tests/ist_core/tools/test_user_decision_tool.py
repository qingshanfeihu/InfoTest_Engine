"""compile_user_decision 回归:锚从台账机械取,不经手抄(2026-07-05 工具化)。

守:①ordering_sensitive claim 强制 member 形态+forbidden 带降级项;②显式 drop_ordering
才放弃ordering anchor;③min_requests 取台账最大;④改描述不落形态约束;⑤与 emit 出口门同语义。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from main.ist_core.tools.device import compile_user_decision

_ROOT = Path(__file__).resolve().parents[3]
_A = "203099999999900077"
_OUT = _ROOT / "workspace" / "outputs" / _A


@pytest.fixture(autouse=True)
def _clean():
    shutil.rmtree(_OUT, ignore_errors=True)
    yield
    shutil.rmtree(_OUT, ignore_errors=True)


def _ledger(claims):
    _OUT.mkdir(parents=True, exist_ok=True)
    (_OUT / "needs_decision.json").write_text(
        json.dumps({"autoid": _A, "claims": claims}, ensure_ascii=False), encoding="utf-8")
    # 「先问后落」门:测试补一条含该 autoid 的问答记录(真实链路由 ask_user 工具自动落)。
    # 取径经 runtime_path——pytest 下=tmp,与门读侧同径,不再污染生产台账(2426 条 ts=0 前科)
    from main.common.runtime_paths import runtime_path
    qa = runtime_path("ask_user_answers.jsonl")
    qa.parent.mkdir(parents=True, exist_ok=True)
    with qa.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": 0, "questions": [f"测试 {_A}"], "answers": {"t": "改"}},
                           ensure_ascii=False) + "\n")


def _ud():
    return json.loads((_OUT / "user_decision.json").read_text(encoding="utf-8"))


def test_ledger_facts_copied_not_judged():
    # 工具只复制台账事实(ordering anchor/最大 min_requests),不代判形态——form 显式传
    _ledger([{"claim_kind": "new_member_last", "min_requests": 4, "ordering_sensitive": True},
             {"claim_kind": "weight_ratio", "min_requests": 46, "ordering_sensitive": False}])
    out = compile_user_decision.func(_A, "改过程", assertion_form="member")
    assert "已落盘" in out
    ud = _ud()
    assert ud["expected_assertion_form"] == "member"
    assert ud["claim_kinds_preserved"] == ["new_member_last"]   # 台账原件复制
    assert ud["min_requests"] == 46                              # 取台账最大,不均一化


def test_drop_ordering_requires_explicit_flag():
    _ledger([{"claim_kind": "new_member_last", "min_requests": 4, "ordering_sensitive": True}])
    compile_user_decision.func(_A, "改预期", assertion_form="captured_relation", drop_ordering=True)
    ud = _ud()
    assert ud["expected_assertion_form"] == "captured_relation"
    assert ud["claim_kinds_preserved"] == [] and ud["ordering_dropped_by_user"] is True


def test_form_must_be_explicit():
    # 形态是语义决策,工具不代填默认——缺 form 直接拒
    _ledger([{"claim_kind": "weight_ratio", "min_requests": 6, "ordering_sensitive": False}])
    out = compile_user_decision.func(_A, "改过程")
    assert "error" in out and "assertion_form" in out
    assert compile_user_decision.func(_A, "改预期", assertion_form="dist").startswith("已落盘")


def test_describe_decision_no_form_constraint():
    _ledger([{"claim_kind": "absolute_position", "min_requests": 2, "ordering_sensitive": True}])
    compile_user_decision.func(_A, "改描述", note="用户说这条其实测的是缓存")
    ud = _ud()
    assert "expected_assertion_form" not in ud and ud["note"]


def test_bad_inputs_rejected():
    assert "error" in compile_user_decision.func("123", "改过程")
    assert "error" in compile_user_decision.func(_A, "随便改")
    _ledger([])
    assert "error" in compile_user_decision.func(_A, "改过程", assertion_form="magic")


def test_ask_before_decide_gate():
    # 「先问后落」:没有含该 case 指代的真实问答记录 → 拒绝落盘(越权事故的 A 层预防)
    aid2 = "203099999999900078"
    d2 = _ROOT / "workspace" / "outputs" / aid2
    import shutil as _sh
    _sh.rmtree(d2, ignore_errors=True)
    try:
        out = compile_user_decision.func(aid2, "改过程")
        assert "error" in out and "问答记录" in out
        assert not (d2 / "user_decision.json").exists()
    finally:
        _sh.rmtree(d2, ignore_errors=True)


# ── H1(§18.11 横切,2026-07-14 对抗评审 BLOCKER):form 按 claim_kind 条件化 ──────
# 机制类 claim(验证路径缺失/禁令机制)的「改过程」=换实现路径,无 dist/member 形态
# 可选;旧无条件 form 门使引擎侧 ask_decision(不传 form)落盘必败→问询活锁。

def test_mech_only_ledger_lands_without_form():
    """台账全机制类 + 改过程不传 form → 落盘成功,note(等价实现原文)保留,无形态键。"""
    _ledger([{"claim_kind": "forbidden_mechanism",
              "reason": "intent requires reboot; bed forbids it"}])
    out = compile_user_decision.func(_A, "改过程",
                                     note="重启→clear 验证(等价实现,模型条件)")
    assert "已落盘" in out
    ud = _ud()
    assert ud["decision"] == "改过程"
    assert "clear 验证" in ud["note"]
    assert "expected_assertion_form" not in ud


def test_verification_path_absent_lands_without_form():
    """655248 型(verification_path_absent)+ 改预期不传 form → 落盘成功。"""
    _ledger([{"claim_kind": "verification_path_absent",
              "reason": "HA FIP not realizable on this bed"}])
    out = compile_user_decision.func(_A, "改预期", note="换可实现观测")
    assert "已落盘" in out


def test_command_existence_lands_without_form():
    """§18.14 D1:command_existence(换版本内命令)免 form → 改过程落盘成功(不活锁)。"""
    _ledger([{"claim_kind": "command_existence", "command": "sdns fulldns on"}])
    out = compile_user_decision.func(_A, "改过程", note="换 sdns dnssec 形态")
    assert "已落盘" in out and "expected_assertion_form" not in _ud()


def test_missing_teardown_lands_without_form():
    """§18.14 D1:missing_teardown(补恢复步)免 form → 改过程落盘成功(不活锁)。"""
    _ledger([{"claim_kind": "missing_teardown", "suggested_tau": ["no sdns listener"]}])
    out = compile_user_decision.func(_A, "改过程", note="案尾补 no 回放")
    assert "已落盘" in out


def test_form_kind_ledger_still_requires_form():
    """含形态类 claim → form 门不变(形态是语义决策,工具不代判)。"""
    _ledger([{"claim_kind": "weight_ratio", "min_requests": 46}])
    out = compile_user_decision.func(_A, "改过程")
    assert str(out).startswith("error")


def test_form_kind_lands_with_explicit_form():
    """§18.14 D1②:形态类带 assertion_form(=q['_form'])→ 落盘成功(engine _land 传 form
    后不再活锁;此前 ask_decision 从不传 form 致 distribution 类经改过程恒拒重问)。"""
    _ledger([{"claim_kind": "distribution", "min_requests": 20}])
    out = compile_user_decision.func(_A, "改过程", note="加请求数到可验", assertion_form="dist")
    assert "已落盘" in out and _ud().get("expected_assertion_form") == "dist"


def test_mixed_ledger_still_requires_form():
    """机制类+形态类混合台账 → 仍强制 form(保守)。"""
    _ledger([{"claim_kind": "forbidden_mechanism"},
             {"claim_kind": "weight_ratio", "min_requests": 4}])
    out = compile_user_decision.func(_A, "改过程")
    assert str(out).startswith("error")
