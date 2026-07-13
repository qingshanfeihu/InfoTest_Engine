"""数学公式模型修复的回归锁定：
F1 先例分数读结构化分（不再正则抠显示文本，修 config-only 轴误判 0）;
F2 observe_ops 单一事实源（grade_extract 共用；原 confidence_f 消费方已随死代码删除）。
（F3 score_case 三测随 confidence_f 删除——grade 链 2026-07-07 已删,生产零调用。）
全部确定性可断言。
"""
from __future__ import annotations

import re


# ── F1: 先例分数走结构化排序分，覆盖 config-only(相似度X)轴 ──────────────────
def test_precedent_best_structured_score_covers_config_only_axis(monkeypatch):
    import main.ist_core.tools.device.precedent_tools as pt
    monkeypatch.setattr(pt, "_load_mirror_corpus", lambda: [
        {"fn": "a.xlsx", "cfg_tokens": {"sdns", "host", "pool"},
         "seq": [("APV_0", "cmd_config", "sdns on")]},
    ])
    monkeypatch.setattr(pt, "_cmd_tokens", lambda c: ({"sdns", "host"} if c else set()))
    # config-only 轴：my_config 有、intent 空 → tag="相似度X"
    best, text = pt.precedent_best_and_text(my_config="sdns host", intent="", limit=2)
    assert best > 0                         # 结构化分(cfg_sim=2/3)，旧正则会从"相似度X"抠成 0
    assert "config structure axis" in text   # 确认走的是 config-only 显示格式
    # 回归证据：旧正则对"相似度X"任一分支都不匹配 → 会误判 0
    OLD_RE = re.compile(r"意图([\d.]+)|配置([\d.]+)\+意图([\d.]+)")
    assert OLD_RE.search(text) is None


def test_precedent_best_empty_axes_returns_zero(monkeypatch):
    import main.ist_core.tools.device.precedent_tools as pt
    monkeypatch.setattr(pt, "_cmd_tokens", lambda c: set())
    best, text = pt.precedent_best_and_text(my_config="", intent="", limit=2)
    assert best == 0.0 and text == ""


# ── F2: observe_ops 单一事实源 ────────────────────────────────────────────────
def test_observe_ops_classification():
    from main.case_compiler.observe_ops import object_tokens, observe_kind, config_existence_check
    assert observe_kind("show sdns host") == "config_query"
    assert observe_kind("dig @1.2.3.4 foo A +short") == "behavior"
    assert observe_kind("show statistics sdns") == "behavior"      # stat → 行为观测
    assert observe_kind("clear sdns session") == ""                # 非 show/dig → 非观测
    assert object_tokens("clear sdns session persistence") == ["sdns", "session", "persistence"]
    assert object_tokens("1.2.3.4") == []                         # 丢 IP
    is_ce, m = config_existence_check(
        "show sdns host persistence", "sdns host persistence", ["sdns host persistence 3600 x"])
    assert is_ce and m                                            # show + expect⊆前序配置 = 配置存在性
    is_ce2, _ = config_existence_check("dig @ip foo", "sdns host", ["sdns host x"])
    assert not is_ce2                                             # dig 行为观测 → 非配置存在性


def test_is_observe_command_covers_display():
    """F4(Q4-fix): display 算观测步；get/list 已从算子词表移除(避免 access-list 误匹配)。"""
    from main.case_compiler.observe_ops import is_observe_command
    for c in ("show sdns host", "dig @1.2.3.4 x", "display foo",
              "curl http://x", "nslookup y", "ping z"):
        assert is_observe_command(c), c
    for c in ("sdns host x", "clear sdns session", "", "failed to execute the command",
              "get bar", "list baz", "get-config"):
        assert not is_observe_command(c), c


# ── 强字典→结构化事实：问题12(失败 config 回显) + 问题13(not_found 状态变更) ────────
# (F3 score_case 三测随 confidence_f 死代码删除,2026-07-13——grade 链 2026-07-07 已删,
#  score_case 生产零调用;observe_ops 单一事实源由上方 test_observe_ops_classification 覆盖)
def test_config_existence_distinguishes_found_vs_not_found():
    """问题13：config_existence_check 按 F 列算子定性——found(配置)=恒真存在性(True,cfg)；
    not_found(配置)=验移除/覆盖、非恒真(False)，但 cfg 非空保留「该配置配过」供状态变更判定。"""
    from main.case_compiler.observe_ops import config_existence_check
    ob, ctx = "show sdns host lastresort pool", ["sdns host lastresort pool test.com p1"]
    expect = "sdns host lastresort pool test.com p1"
    assert config_existence_check(ob, expect, ctx, "found") == (True, ctx[0])        # found→恒真存在性
    assert config_existence_check(ob, expect, ctx, "not_found") == (False, ctx[0])   # not_found→非恒真,留cfg
    assert config_existence_check(ob, "sdns host xyz", ctx, "not_found") == (False, "")  # 没配过→无cfg


def test_is_observation_step_reads_f_column_not_grep_g():
    """问题12：_is_observation_step 用 F 列方法名(框架结构化契约)判产回显，不 grep G 列关键字。
    cmd_config(单条 return output、失败也回显错误文字)=产回显；cmds_config(多条 return None)=不产。"""
    from main.ist_core.tools.device.structural_gate import _is_observation_step
    # 失败配置命令(cmd_config 单条)——G 不含 show/dig，旧 _OBSERVE_RE grep G 会误判不产回显
    assert _is_observation_step({"E": "APV_0", "F": "cmd_config", "G": "sdns host pool x p11"}) is True
    assert _is_observation_step({"E": "APV_0", "F": "cmds_config", "G": "sdns on\nsdns listener"}) is False
    assert _is_observation_step({"E": "test_env", "F": "routera", "G": "dig"}) is True
    assert _is_observation_step({"E": "check_point", "F": "found", "G": "x"}) is False


def test_golden_failed_command_pattern_not_dangling():
    """问题12：金标准写法(失败命令 cmd_config 单条→紧接断言、不插 show)不再误判 dangling；
    但多条 cmds_config(真 return None、found(None) 崩)仍被拦(防崩溃边界完整)。"""
    from main.ist_core.tools.device.structural_gate import check_structural_constraints
    golden = [
        {"E": "APV_0", "F": "cmds_config", "G": "sdns on\nsdns listener 172.16.34.70"},
        {"E": "APV_0", "F": "cmd_config", "G": "sdns host pool autotest.com p11"},
        {"E": "check_point", "F": "found", "G": "A maximum of (10) SDNS pools"},
    ]
    assert not any(v.code == "dangling_assertion"
                   for v in check_structural_constraints("994957", golden).violations)
    bad = [
        {"E": "APV_0", "F": "cmds_config", "G": "sdns on\nsdns host pool x p11"},
        {"E": "check_point", "F": "found", "G": "A maximum"},
    ]
    assert any(v.code == "dangling_assertion"
               for v in check_structural_constraints("x", bad).violations)
