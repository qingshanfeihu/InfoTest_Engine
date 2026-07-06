"""Footprint 写核路径穿越/越权防御回归（安全评审高危+中危项，补测试盲区）。

覆盖：① router 白名单丢弃穿越 feature_id；② merger 写盘前 relative_to 收敛挡 target_file 逃逸；
③ evidence_file 限定只读手册根（agent 自供 workspace 证据不认，防幻觉门架空）；④ 端到端：
穿越 provenance 经 writeback_verified_case 不写到 footprint 根外。"""

from __future__ import annotations

import main.ist_core.memory.footprint.merger as mg
from main.ist_core.memory.footprint.router import route_facts, _feature_id_safe
from main.ist_core.memory.footprint.merger import merge_fact, _resolve_evidence_path
from main.ist_core.memory.footprint.schema import RawFact, RoutedFact
from main.case_compiler.provenance_ir import CaseProvenance, StepIR, StepSource
from main.ist_core.memory.compile_writeback import writeback_verified_case


def _cli_fact(feature_path, syntax="sdns listener 1.1.1.1"):
    return RawFact(fact_kind="cli_command", feature_path=feature_path,
                   fact_key=syntax, cli_syntax=syntax, parameters=[],
                   evidence_file="x.md", evidence_quote=syntax)


def test_feature_id_safe_whitelist():
    assert _feature_id_safe("sdns.listener")
    assert _feature_id_safe("slb.real.http")
    assert _feature_id_safe("no_slb-real")
    assert not _feature_id_safe("../../../tmp/x")
    assert not _feature_id_safe("a/b")
    assert not _feature_id_safe("..")
    assert not _feature_id_safe(".hidden")
    assert not _feature_id_safe("")


def test_router_drops_traversal_feature_path():
    """穿越 feature_path → route_facts 丢弃(不产 RoutedFact)；合法的照常路由。"""
    assert len(route_facts([_cli_fact(["sdns", "listener"])])) == 1
    assert route_facts([_cli_fact(["../../../../../../tmp/ist_pwned"])]) == []


def test_merger_convergence_blocks_target_file_escape(tmp_path):
    """即便 RoutedFact.target_file 带穿越(绕过 router),merge_fact 写盘前收敛→skip,不写根外。"""
    fdir = tmp_path / "footprints"
    fdir.mkdir()
    escape = tmp_path / "ESCAPED.json"
    routed = RoutedFact(fact=_cli_fact(["sdns", "listener"]), level="leaf",
                        target_file="nodes/../../ESCAPED.json")
    res = merge_fact(routed, fdir)
    assert res.action == "skip" and "escapes" in res.detail
    assert not escape.exists()   # footprint 根外文件绝不被创建


def test_evidence_file_in_workspace_rejected(tmp_path, monkeypatch):
    """evidence_file 指向 agent 可写区 workspace（agent 自写的文件）→ 不认(防幻觉门被架空)；
    只读手册根内的证据照常认。"""
    monkeypatch.setattr(mg, "_project_root", lambda: tmp_path)
    md = tmp_path.joinpath(*mg._MARKDOWN_ROOT)
    md.mkdir(parents=True)
    (md / "real_manual.md").write_text("sdns listener 1.1.1.1", encoding="utf-8")
    # 只读手册根内 basename 命中 → 认
    assert _resolve_evidence_path("real_manual.md") is not None
    # agent 自供:workspace 里的文件 → 不认(即便真存在)
    evil = tmp_path / "workspace" / "outputs" / "feat"
    evil.mkdir(parents=True)
    (evil / "evil.md").write_text("sdns listener 9.9.9.9", encoding="utf-8")
    assert _resolve_evidence_path("workspace/outputs/feat/evil.md") is None


def test_writeback_traversal_provenance_no_escape(tmp_path):
    """端到端:G 命令首 token 是穿越串 → writeback 零写入、footprint 根外无落盘。"""
    fdir = tmp_path / "footprints"
    fdir.mkdir()
    escape = tmp_path / "PWNED.json"
    prov = CaseProvenance(autoid="a1", steps=[
        StepIR("APV_0", "cmd_config", "../../../../PWNED listener 1.1.1.1", "G",
               StepSource("footprint", "sdns.listener")),
    ])
    res = writeback_verified_case(prov, fdir, on_device_passed=True)
    assert res.g_facts_written == 0
    assert not escape.exists()
