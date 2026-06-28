"""grade_extract — offline 信号契约。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_GE_PATH = (
    Path(__file__).resolve().parents[3]
    / "main/ist_core/skills/ist_compile_grade/scripts/grade_extract.py"
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
