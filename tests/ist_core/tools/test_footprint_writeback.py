"""compile_footprint_writeback @tool 薄包装：包装逻辑（读+解析 provenance、错误跳过、定位
footprint 根、返回形态）。核心写回逻辑（只写 G 段 / evidence 门 / provisional）由
tests/ist_core/memory/test_compile_writeback.py 覆盖，这里只测**包装**不重测内核。"""

from __future__ import annotations

from main.case_compiler.provenance_ir import CaseProvenance, StepIR, StepSource
from main.ist_core.tools.knowledge.footprint_writeback import compile_footprint_writeback

_wb = getattr(compile_footprint_writeback, "func", compile_footprint_writeback)


def _setup_sandbox(tmp_path, monkeypatch):
    """file_tools 沙箱根 + KNOWLEDGE_FOOTPRINTS 指到 tmp。返回 (workspace outputs 目录, footprint 根)。"""
    import main.ist_core.tools.deepagent.file_tools as ft
    import main.knowledge_paths as kp
    ws = tmp_path / "workspace"
    outd = ws / "outputs" / "feat"
    outd.mkdir(parents=True)
    (tmp_path / "knowledge" / "data").mkdir(parents=True)
    monkeypatch.setattr(ft, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ft, "_AGENT_ROOT", tmp_path / "knowledge" / "data")
    monkeypatch.setattr(ft, "_WORKSPACE_ROOT", ws)
    monkeypatch.delenv("IST_SESSION_DIR", raising=False)
    monkeypatch.delenv("IST_USER_DIR", raising=False)
    fdir = tmp_path / "footprints"
    fdir.mkdir()
    monkeypatch.setattr(kp, "KNOWLEDGE_FOOTPRINTS", fdir)   # 工具内部 import 时读到它
    return outd, fdir


def _write_prov(outd, autoid, steps):
    (outd / "case.provenance.json").write_text(
        CaseProvenance(autoid=autoid, steps=steps).to_json(), encoding="utf-8")
    return "workspace/outputs/feat/case.provenance.json"


def test_writeback_missing_provenance_skips_not_errors(tmp_path, monkeypatch):
    """provenance 路径不存在 → 如实"跳过写回"，不抛异常（归因退化，不该崩 verify 流程）。"""
    _setup_sandbox(tmp_path, monkeypatch)
    out = _wb("a1", "workspace/outputs/feat/nope.json", True)
    assert "跳过写回" in out


def test_writeback_unparseable_provenance_skips(tmp_path, monkeypatch):
    """provenance 坏 JSON → 跳过、不崩。"""
    outd, _ = _setup_sandbox(tmp_path, monkeypatch)
    (outd / "case.provenance.json").write_text("{ not json", encoding="utf-8")
    out = _wb("a1", "workspace/outputs/feat/case.provenance.json", True)
    assert "跳过写回" in out


def test_writeback_happy_path_returns_summary(tmp_path, monkeypatch):
    """有 G 段的真 PASS → 调内核写回、返回带 autoid + 真PASS 标记的汇总（写/跳由 evidence 门定）。"""
    outd, fdir = _setup_sandbox(tmp_path, monkeypatch)
    steps = [
        StepIR("APV_0", "cmd_config", "sdns listener 1.1.1.1", "G",
               StepSource("footprint", "sdns.listener")),
        StepIR("check_point", "found", "1.1.1.1", "V", StepSource("manual", "x:1")),  # V 不写回
    ]
    rel = _write_prov(outd, "a1", steps)
    out = _wb("a1", rel, True)
    assert "footprint 写回 autoid=a1" in out
    assert "真PASS" in out          # on_device_passed=True 标记


def test_writeback_provisional_tag_when_not_on_device(tmp_path, monkeypatch):
    """on_device_passed=False → provisional 标记（代理门，未上机真 PASS）。"""
    outd, _ = _setup_sandbox(tmp_path, monkeypatch)
    steps = [StepIR("APV_0", "cmd_config", "sdns listener 2.2.2.2", "G",
                    StepSource("footprint", "sdns.listener"))]
    rel = _write_prov(outd, "a2", steps)
    out = _wb("a2", rel, False)
    assert "provisional" in out
