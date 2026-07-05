"""成品卷 lint 门回归(2026-07-04 dongkl 闭环取证驱动)。

事故:orchestrator 用 run_python 直改 case.xlsx 绕过 compile_emit 的崩溃门,
直改版带"dig(H)后直接断言"形态,上机 result=None 抛 TypeError 崩整份 pytest
(39 秒截断、34 case 只跑 1 个,连续两轮)。修复:lint 挂到凭证(submit_verdict/
compile_score)与合并(emit_merged)的必经之路——任何来源的卷面都逃不过。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import openpyxl
import pytest

from main.ist_core.tools.device import compile_emit, compile_emit_merged, submit_verdict
from main.ist_core.tools.device.structural_gate import lint_xlsx_case

AID = "203031750000000201"

_STEPS = [
    {"D": "配置基线", "E": "APV_0", "F": "cmds_config",
     "G": "sdns on\nsdns listener 172.16.34.70\nsdns host name t.com\nsdns service ip s1 172.16.35.213\nsdns pool name p1\nsdns pool service p1 s1\nsdns host pool t.com p1"},
    {"D": "触发", "E": "test_env", "F": "routera", "G": "dig @172.16.34.70 t.com"},
    {"D": "断言", "E": "check_point", "F": "found", "G": r"\b172\.16\.35\.213\b"},
]


@pytest.fixture()
def emitted_case():
    out = compile_emit.invoke({"autoid": AID, "steps": _STEPS, "out_name": AID})
    assert "已产出" in out
    xp = Path("workspace/outputs") / AID / "case.xlsx"
    yield xp
    shutil.rmtree(xp.parent, ignore_errors=True)


def _corrupt(xp: Path, mutate) -> None:
    wb = openpyxl.load_workbook(xp)
    mutate(wb.active)
    wb.save(xp)


def _find_row(ws, col: int, needle: str) -> int:
    for row in ws.iter_rows(min_row=2):
        if needle in str(row[col - 1].value or ""):
            return row[0].row
    raise AssertionError(f"找不到含 {needle!r} 的行")


def test_lint_clean_case_passes(emitted_case):
    res = lint_xlsx_case(emitted_case)
    assert res.ok, [v.code for v in res.violations]


def test_lint_catches_dangling_assertion(emitted_case):
    def mutate(ws):
        r = _find_row(ws, 7, "dig @")
        ws.cell(r, 8).value = "v1"  # dig 加 H → result 不更新 → 后续断言悬空
    _corrupt(emitted_case, mutate)
    res = lint_xlsx_case(emitted_case)
    assert any(v.code == "dangling_assertion" for v in res.violations)


def test_lint_catches_invalid_regex(emitted_case):
    def mutate(ws):
        r = _find_row(ws, 6, "found")
        ws.cell(r, 7).value = r"172\.16\.35\.213[^"
    _corrupt(emitted_case, mutate)
    res = lint_xlsx_case(emitted_case)
    assert any(v.code == "assertion_regex_invalid" for v in res.violations)


def test_lint_catches_short_mode_status_assertion(emitted_case):
    def mutate(ws):
        rd = _find_row(ws, 7, "dig @")
        ws.cell(rd, 7).value = str(ws.cell(rd, 7).value) + " +short"
        ra = _find_row(ws, 6, "found")
        ws.cell(ra, 7).value = r"status:\s*NOERROR"
    _corrupt(emitted_case, mutate)
    res = lint_xlsx_case(emitted_case)
    assert any(v.code == "short_mode_status_assertion" for v in res.violations)


def test_lint_catches_undefined_capture_ref(emitted_case):
    def mutate(ws):
        ra = _find_row(ws, 6, "found")
        ws.cell(ra, 8).value = "ghost_reg"
    _corrupt(emitted_case, mutate)
    res = lint_xlsx_case(emitted_case)
    assert any(v.code == "undefined_capture_ref" for v in res.violations)


def test_lint_catches_dns_label_over_63(emitted_case):
    def mutate(ws):
        rd = _find_row(ws, 7, "dig @")
        ws.cell(rd, 7).value = "dig @172.16.34.70 www." + "x" * 120 + ".com"
    _corrupt(emitted_case, mutate)
    res = lint_xlsx_case(emitted_case)
    assert any(v.code == "dns_label_over_63" for v in res.violations)


def test_submit_verdict_rejects_pass_on_lint_violation(emitted_case):
    def mutate(ws):
        r = _find_row(ws, 7, "dig @")
        ws.cell(r, 8).value = "v1"
    _corrupt(emitted_case, mutate)
    out = submit_verdict.invoke({"autoid": AID, "verdict": "PASS",
                                 "xlsx_path": str(emitted_case)})
    assert out.startswith("error") and "lint" in out
    # CUT 放行且违例并进 caveats(重做者可见)
    out2 = submit_verdict.invoke({"autoid": AID, "verdict": "CUT", "root_cause": "可修复",
                                  "caveats": ["r2 dig 带 H 后直接断言"],
                                  "xlsx_path": str(emitted_case)})
    assert "已提交" in out2
    cred = json.loads((emitted_case.parent / ".grade_credential.json").read_text())
    assert any("lint" in c for c in cred["caveats"])


def test_submit_verdict_rejects_malformed_autoid(emitted_case):
    out = submit_verdict.invoke({"autoid": AID[:17], "verdict": "PASS",
                                 "xlsx_path": str(emitted_case)})
    assert out.startswith("error") and "18 位" in out


def test_submit_verdict_flip_needs_line_evidence(emitted_case):
    ok = submit_verdict.invoke({"autoid": AID, "verdict": "PASS",
                                "xlsx_path": str(emitted_case)})
    assert "已提交" in ok
    # 同卷面(内容未变)翻 CUT:无行级证据 → 拒
    flip = submit_verdict.invoke({"autoid": AID, "verdict": "CUT", "root_cause": "可修复",
                                  "caveats": ["感觉断言不够好"],
                                  "xlsx_path": str(emitted_case)})
    assert flip.startswith("error") and "行级" in flip
    # 带行号 → 放
    flip2 = submit_verdict.invoke({"autoid": AID, "verdict": "CUT", "root_cause": "可修复",
                                   "caveats": ["r3 断言集合漏了成员"],
                                   "xlsx_path": str(emitted_case)})
    assert "已提交" in flip2


def test_emit_merged_rejects_lint_violation(emitted_case):
    # 直改场景全真模拟:凭证新鲜 PASS,但卷面在凭证后被改坏 → 合并 lint 最后防线拦下
    ok = submit_verdict.invoke({"autoid": AID, "verdict": "PASS",
                                "xlsx_path": str(emitted_case)})
    assert "已提交" in ok

    def mutate(ws):
        r = _find_row(ws, 7, "dig @")
        ws.cell(r, 8).value = "v1"
    _corrupt(emitted_case, mutate)
    credp = emitted_case.parent / ".grade_credential.json"
    cred = json.loads(credp.read_text())
    cred["xlsx_mtime"] = emitted_case.stat().st_mtime  # 伪造签名(直改者能做到的极限)
    credp.write_text(json.dumps(cred))
    try:
        merged = compile_emit_merged.invoke({"autoids": [AID], "out_name": "_pytest_lint_merged"})
        assert merged.startswith("error") and "lint" in merged and AID in merged
    finally:
        shutil.rmtree(Path("workspace/outputs") / "_pytest_lint_merged", ignore_errors=True)
