# -*- coding: utf-8 -*-
"""D+1 族性机械清扫守门（短号/截断族，用户可见面）。

族性缺陷（此前 D16/F-TUI-2/D14 逐个冒）一次锁死:
- 短号族:面板题面/报告标题首引=全 aid + 尾号(B 模式,消歧 + 先问后落门老记录回退凭证);
  重复引用尾号可。守门:各欠定面板题面含全 aid。
- 截断族:用户可见辅助截断带明示省略「…」(clip_text/_ellip),决策依据不截。
"""
from __future__ import annotations

from main.ist_core.compile_engine_v8.questions import build_questions, clip_text
from main.ist_core.compile_engine_v8.render import _ellip

A = "203601753067668000"


def _q(led):
    qs = build_questions(led)
    return qs[0]["question"] if qs else ""


def test_command_existence_panel_carries_full_aid():
    """:291 漏网修:存在性面板题面此前尾号-only,现全 aid+尾号(B 模式)。"""
    q = _q({A: {"claims": [{"claim_kind": "command_existence",
                            "command": "show sdns xxx"}]}})
    assert A in q, "存在性面板题面缺全 aid(短号漏网)"
    assert f"尾号 {A[-6:]}" in q


def test_verification_forbidden_panels_carry_full_aid():
    """三元组/禁令面板题面全 aid+尾号(#37 B / 既有)。"""
    tri = _q({A: {"claims": [{"claim_kind": "verification_path_absent",
                              "test_point": "x", "obstacle": "y",
                              "equivalent": {"procedure": "p", "preserves": "q"}}]}})
    fm = _q({A: {"claims": [{"claim_kind": "forbidden_mechanism",
                             "reason": "r", "proposed_equivalent": "e"}]}})
    assert A in tri and f"尾号 {A[-6:]}" in tri
    assert A in fm and f"尾号 {A[-6:]}" in fm


def test_ellip_and_cliptext_mark_truncation():
    """截断族:辅助超长明示省略「…」(不无痕硬截,zhaiyq 血泪)。"""
    long = "命令" * 200
    assert _ellip(long, 160).endswith("…") and len(_ellip(long, 160)) <= 161
    assert _ellip("短", 160) == "短"                       # 不超不加省略号
    assert clip_text(long, 200).endswith("…")              # questions 侧同族


def test_no_naive_shortnum_in_panel_title_family():
    """机械族门:欠定面板题面无「用例 尾6位」裸用(必须全 aid 或全 aid+尾号)。"""
    for kind, claim in [
        ("command_existence", {"claim_kind": "command_existence", "command": "c"}),
        ("forbidden_mechanism", {"claim_kind": "forbidden_mechanism", "reason": "r",
                                 "proposed_equivalent": "e"}),
        ("verification_path_absent", {"claim_kind": "verification_path_absent",
                                      "test_point": "t", "obstacle": "o",
                                      "equivalent": {"procedure": "p", "preserves": "q"}}),
    ]:
        q = _q({A: {"claims": [claim]}})
        # 题面出现的 aid 引用必带全号(全 aid 在场即合格;尾号可作补充)
        assert A in q, f"{kind} 面板题面短号裸用(缺全 aid)"


def test_no_double_stop_when_source_ends_with_period():
    """双句号族:源数据(test_point/obstacle/reason)本身以句号结尾时,题面不出现「。。」
    (变量赋值处 _rstrip_stop 剥末尾句读)。"""
    # 三元组:tp/obs 带句号
    tri = _q({A: {"claims": [{"claim_kind": "verification_path_absent",
                              "test_point": "验证 write mem 不持久化。", "obstacle": "环境无法重启。",
                              "equivalent": {"procedure": "p。", "preserves": "q"}}]}})
    assert "。。" not in tri, f"三元组题面双句号:{tri!r}"
    # 禁令:reason 带句号
    fm = _q({A: {"claims": [{"claim_kind": "forbidden_mechanism",
                             "reason": "意图要求重启设备。", "proposed_equivalent": "clear 运行面。"}]}})
    assert "。。" not in fm, f"禁令题面双句号:{fm!r}"
