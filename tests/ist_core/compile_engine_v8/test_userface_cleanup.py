# -*- coding: utf-8 -*-
"""D+1 族性机械清扫守门（短号/截断族，用户可见面）。

族性缺陷（此前 D16/F-TUI-2/D14 逐个冒）一次锁死:
- 短号族:面板题面/报告标题首引=全 aid + 尾号(B 模式,消歧 + 先问后落门老记录回退凭证);
  重复引用尾号可。守门:各欠定面板题面含全 aid。
- 截断族:用户可见辅助截断带明示省略「…」(clip_text/_ellip),决策依据不截。
"""
from __future__ import annotations

import pathlib

from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8.questions import (
    build_questions, clip_text, build_ask_question,
    _source_label_cn, _strip_md, _annotate_autoids, recompile_times,
)
from main.ist_core.compile_engine_v8.render import _ellip

A = "203601753067668000"


# ── ①族收口批守门:D22 源标签白名单 / Z7 md / D26 autoid / D29 重编次数 / D25 黑话 ──────────


def test_d22_source_label_whitelist_only():
    """D22:源标签只给结构锚白名单命中;内部产物(attr_evidence/manifest)→None 脱敏——**不从
    文件名推 quote 语义**(强字典/C1 红线)。"""
    assert _source_label_cn("device_context") == "实机回显"
    assert _source_label_cn("workspace/outputs/x/last_run.json") == "实机回显"
    assert _source_label_cn(
        "knowledge/data/markdown/product/manual_10.5/cli_10.5_Chapter20.md") == "CLI 手册 10.5 第20章"
    assert _source_label_cn("workspace/outputs/205/attr_evidence.json") is None   # 内部产物→脱敏
    assert _source_label_cn("workspace/outputs/zhaiyq/manifest.json") is None


def test_d22_strip_md_protects_identifier_underscore():
    """D22-Z7:_strip_md 剥 md 强调,但 `host_name` 内下划线(CommonMark intraword)不剥断。"""
    assert _strip_md("**show sdns** _[host_name]_").strip() == "show sdns [host_name]"
    assert "host_name" in _strip_md("_[host_name]_")       # 标识符完整、未被斜体剥断
    assert "**" not in _strip_md("**粗体**") and "粗体" in _strip_md("**粗体**")


def test_d22_sides_desensitize_to_ordinals():
    """D22:两个内部产物源→「记载甲/乙」(相异、无 .json 文件名泄漏)。"""
    c = {"autoid": A, "kind": "panel", "cap_reached": False,
         "panel": {"conflict_shape": "other", "hypothesis": "h", "ask": "?",
                   "sides": [{"source_ref": "workspace/outputs/x/attr_evidence.json", "quote": "dig a"},
                             {"source_ref": "workspace/outputs/y/manifest.json", "quote": "step b"}]}}
    q = build_ask_question(c)["question"]
    assert "记载甲" in q and "记载乙" in q
    assert "attr_evidence" not in q and ".json" not in q and "manifest" not in q


def test_d26_annotate_autoids_bare_sibling():
    """D26:题面自由文本裸 18 位 autoid 追尾号;已带尾号不双标;幂等。"""
    assert _annotate_autoids("同批 205271757988589432 已裁") == "同批 205271757988589432(尾号 589432) 已裁"
    once = _annotate_autoids("案 205271757988589432 x")
    assert _annotate_autoids(once) == once            # 幂等
    who = "用例 205271757988589432(尾号 589432)"
    assert _annotate_autoids(who) == who              # B 模式首引不双标


def test_d29_recompile_times_single_source_and_cap():
    """D29:重编次数=rounds-1 单一源;cap 题面显「重编 2 次」(3 轮 authored=1 初编+2 重编)。"""
    assert recompile_times(3) == 2 and recompile_times(1) == 0 and recompile_times(0) == 0
    q = build_ask_question({"autoid": A, "kind": "cap", "rounds": 3})["question"]
    assert "重编 2 次" in q and "重编 3" not in q


def test_z7_no_literal_bold_markers_in_source():
    """Z7:code 模板手写 md 加粗(TUI 不渲染 md=字面泄)已从用户面字符串删净。"""
    src = pathlib.Path(N.__file__).parent.joinpath("questions.py").read_text(encoding="utf-8")
    for bolded in ["顺序语义**保留**", "顺序语义将**放弃**", "**无案尾恢复步**",
                   "**疑似测试床状态污染**", "**必要条件推断", "**本案自身的命令写法**"]:
        assert bolded not in src, f"Z7 字面加粗残留:{bolded}"


def test_d25_no_s0_jargon_in_status_emit_source():
    """D25:状态行 emit 的 s₀ 黑话堆叠已人话化(emit 在引擎逻辑内,源级守门;用完整 emit 短语,
    不误伤含「保留深归因」的 dev-facing 注释)。"""
    src = pathlib.Path(N.__file__).read_text(encoding="utf-8")
    for emit_phrase in ["s₀ 假设被反驳,保留深归因", "s₀ 配对命中但日志含独立异常行",
                        "s₀ 配对命中但回显含自身执行失败", "fork 判 s₀ 但机械配对判无污染者"]:
        assert emit_phrase not in src, f"D25 状态行 emit 黑话残留:{emit_phrase}"


def _q(led):
    qs = build_questions(led)
    return qs[0]["question"] if qs else ""


def test_command_existence_panel_carries_full_aid():
    """:291 漏网修:存在性面板题面此前尾号-only,现全 aid+尾号(B 模式)。"""
    q = _q({A: {"claims": [{"claim_kind": "command_existence",
                            "command": "show sdns xxx"}]}})
    assert A in q, "存在性面板题面缺全 aid(短号漏网)"
    assert f"尾号 {A[-6:]}" in q


def test_command_existence_panel_self_contained_no_external_ref():
    """:299 虚指修(Design 时序案):命令 >3 用示例+计数「其余为同类命令」自足,**不指向交付报告等
    外部载体**(答题时报告 closing 才产、当下不存在,指向必不可达)。"""
    q = _q({A: {"claims": [{"claim_kind": "command_existence", "command": f"cmd{i}"}
                           for i in range(5)]}})
    assert "见交付报告" not in q and "见报告" not in q, "残留外部载体虚指(时序不可达)"
    assert "其余为同类" in q and "共 5 条" in q          # 示例+计数自足


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
