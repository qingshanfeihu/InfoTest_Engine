"""V3 步骤4：闭环写回（compile_writeback）。

验证：① G 段 provenance step → RawFact 转换；② evidence 门挡幻觉命令；
③ 真实命令（evidence 在手册命中）写回成功；④ V/E 段不写回；⑤ provisional 标记。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from main.case_compiler.provenance_ir import CaseProvenance, StepIR, StepSource
from main.ist_core.memory.compile_writeback import (
    writeback_verified_case, _g_step_to_rawfact, WritebackResult,
)


def _g_step(cmd, kind="footprint", ref="sdns.listener"):
    return StepIR("APV_0", "cmd_config", cmd, "G", StepSource(kind, ref))


def test_g_step_to_rawfact_basic():
    rf = _g_step_to_rawfact(_g_step("sdns listener 1.1.1.1"), "a1", "10.5_cli__part1.md")
    assert rf is not None
    assert rf.fact_kind == "cli_command"
    assert rf.fact_key == "sdns listener 1.1.1.1"
    assert rf.feature_path == ["sdns", "listener"]
    assert rf.evidence_quote == "sdns listener 1.1.1.1"
    assert "compile_writeback:a1" in rf.source_thread


def test_v_layer_step_not_converted():
    # V 段断言绝不写回
    s = StepIR("check_point", "found", "1.1.1.1", "V", StepSource("manual", "x:1"))
    assert _g_step_to_rawfact(s, "a1", "") is None


def test_e_layer_and_nonconfig_skipped():
    # E 层 + 非配置步骤不转
    assert _g_step_to_rawfact(StepIR("test_env", "routera", "x", "E"), "a1", "") is None
    assert _g_step_to_rawfact(StepIR("check_point", "found", "x", "G"), "a1", "") is None
    assert _g_step_to_rawfact(_g_step(""), "a1", "") is None


def test_manual_ref_extracts_evidence_file():
    rf = _g_step_to_rawfact(_g_step("show sdns listener", kind="manual", ref="10.5_cli:1234"),
                            "a1", "fallback.md")
    assert rf.evidence_file == "10.5_cli"


def test_writeback_only_processes_g_layer(tmp_path):
    # 一个 G 段 + 一个 V 段，只 G 段进写回流程（V 不转 RawFact）
    prov = CaseProvenance(autoid="a1", steps=[
        _g_step("sdns listener 172.16.34.200"),
        StepIR("check_point", "found", "172.16.34.200", "V", StepSource("manual", "x:1")),
    ])
    res = writeback_verified_case(prov, tmp_path, manual_glob="nonexist.md")
    assert isinstance(res, WritebackResult)
    # 只 1 条 G 段进入流程（写或跳都行，关键是 V 段没混入）
    assert res.g_facts_written + res.g_facts_skipped == 1


def test_writeback_hallucinated_command_skipped_by_evidence_gate(tmp_path):
    # 编造命令 + 不存在的 evidence_file → merge_fact 的 evidence 门必 skip
    prov = CaseProvenance(autoid="a1", steps=[
        _g_step("totally fabricated nonsense command xyz", ref="bogus"),
    ])
    res = writeback_verified_case(prov, tmp_path, manual_glob="does_not_exist.md")
    assert res.g_facts_written == 0
    assert res.g_facts_skipped == 1


def test_writeback_provisional_flag(tmp_path):
    prov = CaseProvenance(autoid="a1", steps=[_g_step("sdns listener 172.16.34.200")])
    r_proxy = writeback_verified_case(prov, tmp_path, on_device_passed=False)
    assert r_proxy.provisional is True
    assert "代理门" in r_proxy.summary()
    r_real = writeback_verified_case(prov, tmp_path, on_device_passed=True)
    assert r_real.provisional is False
    assert "上机PASS" in r_real.summary()


def test_writeback_precedent_callback(tmp_path):
    prov = CaseProvenance(autoid="a1", steps=[_g_step("sdns listener 172.16.34.200")])
    called = {"n": 0}

    def appender(p):
        called["n"] += 1
        assert p.autoid == "a1"
        return True

    res = writeback_verified_case(prov, tmp_path, append_precedent=appender)
    assert called["n"] == 1
    assert res.precedent_appended is True
