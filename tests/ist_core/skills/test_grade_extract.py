"""grade_extract — offline 信号契约。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_GE_PATH = (
    Path(__file__).resolve().parents[3]
    / "main/ist_core/skills/ist-compile-grade/scripts/grade_extract.py"
)


def _load_grade_extract():
    spec = importlib.util.spec_from_file_location("grade_extract", _GE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ge():
    return _load_grade_extract()


def test_query_object_invalid_false_offline_even_if_observe_g_looks_like_error(ge, monkeypatch):
    """观测步 G 是命令(show)不是回显；命令文本含 error-like 子串(invalid)也不该判 query_object_invalid。

    （原 fixture 用 G="failed to execute the command" 不含 show/dig、压根不被识别为观测步，
    observe_command 恒空——是 fixture 不真实、非代码 bug。改用真实 show 观测命令 + 内嵌 error 词，
    真正验「offline 不把观测命令文本当设备回显跑 has_cli_error」。）
    """
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns host name invalid"},
        {"E": "check_point", "F": "found", "G": "foo"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    cp = ge.extract("fake.xlsx", "-")["check_points"][0]
    assert cp["query_object_invalid"] is False
    assert cp["observe_command"] == "show sdns host name invalid"


def test_expect_is_error_echo_still_detected_for_spec_conflict(ge, monkeypatch):
    """expect 字段上的错误回显探针（spec_conflict）与 observe 命令探针无关。"""
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns host"},
        {"E": "check_point", "F": "found", "G": "syntax error near token"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    # 无 provenance → kind 空，spec_conflict 不触发；只验 expect_is_error_echo
    cp = ge.extract("fake.xlsx", "-")["check_points"][0]
    assert cp["query_object_invalid"] is False
    assert cp["expect_is_error_echo"] is True


def test_not_found_config_is_state_change_genuine_v(ge, monkeypatch):
    """问题13：show 上的 not_found(配过的配置)=状态变更验证(配置被覆盖/移除后消失)=真 V，
    治「只能用 show 观测的覆盖/删除类」(应急池覆盖 105969)被钉死 genuine_v=0、连续 CUT。"""
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": "sdns host lastresort pool test.com p1"},
        {"E": "APV_0", "F": "cmd_config", "G": "sdns host lastresort pool test.com p2"},
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns host lastresort pool"},
        {"E": "check_point", "F": "not_found", "G": "sdns host lastresort pool test.com p1"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    cp = ge.extract("fake.xlsx", "-")["check_points"][0]
    assert cp["mode"] == "not_found" and cp["observe_kind"] == "config_query"
    assert cp["is_config_existence_check"] is False    # not_found(配置) = 验移除、非恒真存在性
    assert cp["is_genuine_v_assertion"] is True        # 状态变更 = 真 V 覆盖（修复前死要 behavior→False）
    # 对照：found(同配置) 才是恒真配置存在性、非真 V
    rows2 = rows[:3] + [{"E": "check_point", "F": "found", "G": "sdns host lastresort pool test.com p1"}]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows2)
    cp2 = ge.extract("fake.xlsx", "-")["check_points"][0]
    assert cp2["is_config_existence_check"] is True     # found(配置) = 恒真存在性
    assert cp2["is_genuine_v_assertion"] is False


# ── 分布区间断言（算法类 rr/wrr）信号 ────────────────────────────────────────────

def test_distribution_assertion_detected_by_bounded_range(ge, monkeypatch):
    """rr + 有界区间正则(emit dist 展开形态) → is_distribution_assertion，has_distribution_assertion，无 gap。"""
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": 'sdns host method "x" "rr"'},
        {"E": "APV_0", "F": "cmd_config", "G": "show statistics sdns pool p1"},
        {"E": "check_point", "F": "found", "G": "m1[^\\n]*Hit:\\s*(?<!\\d)(?:[8-9]|1[0-2])(?!\\d)"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    r = ge.extract("fake.xlsx", "-")
    cp = r["check_points"][0]
    assert cp["is_distribution_assertion"] is True
    assert cp["count_tautology_suspect"] is False
    assert r["has_distribution_method"] is True
    assert r["has_distribution_assertion"] is True
    assert r["distribution_coverage_gap_suspect"] is False


def test_unbounded_hit_is_tautology_and_gap(ge, monkeypatch):
    """wrr + 无界 Hit:\\d+ → count_tautology_suspect，且配了分布算法却无分布区间 → coverage gap（回归探针）。"""
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": 'sdns host method "x" "wrr"'},
        {"E": "APV_0", "F": "cmd_config", "G": "show statistics sdns pool p1"},
        {"E": "check_point", "F": "found", "G": "Hit:\\s+\\d+"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    r = ge.extract("fake.xlsx", "-")
    cp = r["check_points"][0]
    assert cp["count_tautology_suspect"] is True
    assert cp["is_distribution_assertion"] is False
    assert r["has_distribution_method"] is True
    assert r["count_tautology_count"] == 1
    assert r["distribution_coverage_gap_suspect"] is True


def test_ga_method_not_distribution(ge, monkeypatch):
    """ga（优先级故障切换）不是分布算法 → has_distribution_method False、不触发 gap。"""
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": 'sdns host method "x" "ga"'},
        {"E": "test_env", "F": "clientc", "G": "dig @172.16.34.70 x A +short", "H": "v1"},
        {"E": "test_env", "F": "clientc", "G": "dig @172.16.34.70 x A +short"},
        {"E": "check_point", "F": "found", "G": "", "H": "v1"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    r = ge.extract("fake.xlsx", "-")
    assert r["has_distribution_method"] is False
    assert r["distribution_coverage_gap_suspect"] is False


# ── 写死单次命中落点（observe-then-assert）信号：778012 根因回归探针 ──────────────────

def test_hardcoded_hit_ip_and_count_flagged_under_rr(ge, monkeypatch):
    """rr + dig found 写死成员 IP + 写死 Hit:固定数 → 两个 hardcoded 信号都亮（778012 带病 PASS 形态，必拦）。"""
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": 'sdns host method "x" "rr"'},
        {"E": "test_env", "F": "clientc", "G": "dig @172.16.34.70 x A +short"},
        {"E": "check_point", "F": "found", "G": "\\b172\\.16\\.35\\.213\\b"},   # 写死单次命中落点 IP
        {"E": "APV_0", "F": "cmd_config", "G": "show statistics sdns pool p1"},
        {"E": "check_point", "F": "found", "G": "Hit:\\s+1"},                   # 写死固定命中计数
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    r = ge.extract("fake.xlsx", "-")
    assert r["check_points"][0]["asserts_literal_hit_ip"] is True
    assert r["check_points"][1]["count_hardcoded_suspect"] is True
    assert r["hardcoded_hit_ip_suspect"] is True
    assert r["hardcoded_count_suspect"] is True
    assert r["asserts_literal_hit_ip_count"] == 1
    assert r["count_hardcoded_count"] == 1
    # 写死 Hit:1 不是无界 \d+，不该被 count_tautology 误判（这正是旧探针盲区）
    assert r["count_tautology_count"] == 0


def test_literal_ip_not_flagged_under_ga(ge, monkeypatch):
    """ga（确定性映射）下 dig found 写死 IP 合法（始终命中最高优先级成员）→ 不误杀为 hardcoded_hit_ip。"""
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": 'sdns host method "x" "ga"'},
        {"E": "test_env", "F": "clientc", "G": "dig @172.16.34.70 x A +short"},
        {"E": "check_point", "F": "found", "G": "\\b172\\.16\\.35\\.213\\b"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    r = ge.extract("fake.xlsx", "-")
    assert r["check_points"][0]["asserts_literal_hit_ip"] is False
    assert r["hardcoded_hit_ip_suspect"] is False


# ── 命中归属锚点（membership_derived）信号：new_member_unanchored_suspect ──────────────

def _fake_provenance(kinds_by_cp_idx: dict):
    """构造 grade_extract 期望形状的 provenance-like 对象：.steps[i].E/.layer/.source.kind/.ref。
    只需给出「第几个 check_point 对应哪个 source.kind」，非 check_point 步随意占位即可
    （extract() 只按「第 k 个 check_point」对齐 provenance，不按行号）。"""
    from types import SimpleNamespace
    n = max(kinds_by_cp_idx) + 1 if kinds_by_cp_idx else 0
    steps = []
    for i in range(n):
        kind = kinds_by_cp_idx.get(i, "")
        steps.append(SimpleNamespace(E="check_point", layer="V",
                                      source=SimpleNamespace(kind=kind, ref="")))
    return SimpleNamespace(steps=steps)


def test_membership_derived_not_flagged_as_hardcoded_hit_ip(ge, monkeypatch):
    """member 声明展开的 found(成员集合) 标 membership_derived 时，不该被误判成写死单点落点
    （回归：修复前 asserts_literal_hit_ip 的排除表漏了 membership_derived，会误杀合法的命中归属锚点）。"""
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": 'sdns host method "x" "rr"'},
        {"E": "test_env", "F": "clientc", "G": "dig @172.16.34.70 x A +short"},
        {"E": "check_point", "F": "found", "G": "\\b(?:172\\.16\\.35\\.226|172\\.16\\.35\\.232)\\b"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance",
                         lambda _p: _fake_provenance({0: "membership_derived"}))
    r = ge.extract("fake.xlsx", "-")
    assert r["check_points"][0]["source_kind"] == "membership_derived"
    assert r["check_points"][0]["asserts_literal_hit_ip"] is False
    assert r["hardcoded_hit_ip_suspect"] is False


def test_member_anchor_shape_not_flagged_without_provenance(ge, monkeypatch):
    """无 provenance（compile-worker 主路现状：不传 provenance_json）时，member_regex_for_ips
    生成的 `\\b(?:ip)\\b` 形态仍不该被误判——形状签名兜底，不完全依赖 source_kind（778012
    实测过：主路 compile-worker 确实不写 provenance，纯靠 source_kind 排除会在这条链路失效）。
    单成员场景（`(?:` 里只有 1 个 IP、没有 `|` 交替）也要覆盖——不能只认多成员 alternation。"""
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": 'sdns host method "x" "rr"'},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 x A +short"},
        {"E": "check_point", "F": "found", "G": "\\b(?:172\\.16\\.35\\.225)\\b"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)  # 无 provenance
    r = ge.extract("fake.xlsx", "-")
    assert r["check_points"][0]["source_kind"] == ""       # 确认真的没有 provenance 兜底
    assert r["check_points"][0]["asserts_literal_hit_ip"] is False
    assert r["hardcoded_hit_ip_suspect"] is False


def test_has_membership_anchor_detected_without_provenance(ge, monkeypatch):
    """case 级 has_membership_anchor 双通道识别：无 provenance 时靠形状签名（回归：eval 脚本
    此前直接复刻 source_kind 判断，在 compile-worker 主路(不传 provenance)下永远判 False）。"""
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": 'sdns host method "x" "rr"'},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 x A +short"},
        {"E": "check_point", "F": "not_found", "G": "\\b(?:172\\.16\\.35\\.225)\\b"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    r = ge.extract("fake.xlsx", "-")
    assert r["check_points"][0]["is_membership_anchor"] is True
    assert r["has_membership_anchor"] is True


def test_bare_literal_ip_without_group_still_flagged(ge, monkeypatch):
    """对照：没有 `(?:...)` 包裹的裸字面 IP（手写写死单点的典型形态）该拦的还是要拦——
    形状签名只排除 member 那种非捕获组形态，不放宽对真正写死单点的判定。"""
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": 'sdns host method "x" "rr"'},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 x A +short"},
        {"E": "check_point", "F": "found", "G": "\\b172\\.16\\.35\\.213\\b"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    r = ge.extract("fake.xlsx", "-")
    assert r["check_points"][0]["asserts_literal_hit_ip"] is True
    assert r["hardcoded_hit_ip_suspect"] is True


def test_new_member_unanchored_suspect_detects_unreferenced_new_pool(ge, monkeypatch):
    """中途新增绑定的 pool（p4），其成员 IP 从未在任何 check_point 出现过 → suspect（778012 型缺陷：
    全程只用 H 捕获比同异，从未拿新增 pool 的成员集合去锚）。"""
    rows = [
        {"E": "APV_0", "F": "cmds_config",
         "G": "sdns pool name p1\nsdns service ip s1 172.16.35.213 80\n"
              "sdns pool service p1 s1\nsdns host pool test.com p1"},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 test.com +short", "H": "v1"},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 test.com +short"},
        {"E": "check_point", "F": "not_found", "G": "", "H": "v1"},   # 第一个 check_point
        {"E": "APV_0", "F": "cmds_config",                            # 中途新增 p4
         "G": "sdns service ip s4 172.16.35.226 80\nsdns pool name p4\n"
              "sdns pool service p4 s4\nsdns host pool test.com p4"},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 test.com +short", "H": "v2"},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 test.com +short"},
        {"E": "check_point", "F": "not_found", "G": "", "H": "v2"},   # 第二个 check_point，仍未提 p4 的 IP
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    r = ge.extract("fake.xlsx", "-")
    assert r["unanchored_new_pools"] == ["p4"]
    assert r["new_member_unanchored_suspect"] is True


def test_new_member_anchored_not_suspect(ge, monkeypatch):
    """同上场景，但后段用 member 锚点(found 成员集合)引用了 p4 的成员 IP → 不该报 unanchored。"""
    rows = [
        {"E": "APV_0", "F": "cmds_config",
         "G": "sdns pool name p1\nsdns service ip s1 172.16.35.213 80\n"
              "sdns pool service p1 s1\nsdns host pool test.com p1"},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 test.com +short", "H": "v1"},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 test.com +short"},
        {"E": "check_point", "F": "not_found", "G": "", "H": "v1"},
        {"E": "APV_0", "F": "cmds_config",
         "G": "sdns service ip s4 172.16.35.226 80\nsdns pool name p4\n"
              "sdns pool service p4 s4\nsdns host pool test.com p4"},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 test.com +short"},
        {"E": "check_point", "F": "found", "G": "\\b(?:172\\.16\\.35\\.226)\\b"},  # member 锚点引用 p4 成员 IP
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    r = ge.extract("fake.xlsx", "-")
    assert r["unanchored_new_pools"] == []
    assert r["new_member_unanchored_suspect"] is False


def test_new_member_unanchored_ignores_upfront_pools(ge, monkeypatch):
    """所有 pool 都在第一个 check_point 之前一次性绑定完（不是"中途新增"）→ 不触发该信号
    （即使断言里也没提到 p2 的 IP——它跟 p1 一样是一开始就绑定的，不是新增场景）。"""
    rows = [
        {"E": "APV_0", "F": "cmds_config",
         "G": "sdns pool name p1\nsdns service ip s1 172.16.35.213 80\n"
              "sdns pool service p1 s1\nsdns host pool test.com p1\n"
              "sdns pool name p2\nsdns service ip s2 172.16.35.214 80\n"
              "sdns pool service p2 s2\nsdns host pool test.com p2"},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 test.com +short", "H": "v1"},
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 test.com +short"},
        {"E": "check_point", "F": "not_found", "G": "", "H": "v1"},
    ]
    monkeypatch.setattr(ge, "_load_rows", lambda _p: rows)
    monkeypatch.setattr(ge, "_load_provenance", lambda _p: None)
    r = ge.extract("fake.xlsx", "-")
    assert r["unanchored_new_pools"] == []
    assert r["new_member_unanchored_suspect"] is False
