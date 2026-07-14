"""F6 禁令机制意图路由(§18.11 五稿;写保存族 σ 链断裂的类修复)。

链路:文法词表(意图侧,CJK 安全)→ author 盖章扫描(intent.json 标记)→ brief 下发
要点先行指令 → emit 硬门(user_decision.json 落盘前拒落卷=先问后落机械强制)。
误报语义=呈报非硬拒:字面命中(如「重启计数」)经面板一答放行(H1 机制类免 form)。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import _shared as sh

_ROOT = Path(__file__).resolve().parents[3]
_A = "203099999999900066"
_OUT = _ROOT / "workspace" / "outputs" / _A


@pytest.fixture(autouse=True)
def _clean():
    shutil.rmtree(_OUT, ignore_errors=True)
    yield
    shutil.rmtree(_OUT, ignore_errors=True)


def _stamp_with_title(monkeypatch, title):
    monkeypatch.setattr(sh, "manifest", lambda st: {"cases": [
        {"autoid": _A, "title": title, "step_intents": [], "group_path": ["功能", "配置保存"]}]})
    N._stamp_intent(_A, {})
    return json.loads((_OUT / "intent.json").read_text(encoding="utf-8"))


# ── 盖章扫描 ────────────────────────────────────────────────────────────────

def test_stamp_flags_reboot_intent(monkeypatch):
    """「执行write file后重启设备」→ 命中 reboot 族(CJK 子串,668015 原题形态)。"""
    it = _stamp_with_title(monkeypatch, "1.配置port 为53.执行write file后重启设备\n2.查看sdns listener")
    fams = {h["family"] for h in it.get("forbidden_mechanism") or []}
    assert "reboot" in fams


def test_stamp_clean_intent_not_flagged(monkeypatch):
    it = _stamp_with_title(monkeypatch, "1.配置sdns listener,使用全域名功能")
    assert "forbidden_mechanism" not in it


def test_stamp_english_boundary_no_false_hit(monkeypatch):
    """英文条目带显式边界:'rebooted-counter-x' 里的子串不命中(CJK 条目才是子串语义)。"""
    it = _stamp_with_title(monkeypatch, "check prereboots counter field")
    assert "forbidden_mechanism" not in it


# ── emit 硬门(先问后落) ─────────────────────────────────────────────────────

def test_emit_gate_blocks_until_user_decision(monkeypatch):
    from main.ist_core.tools.device.emit_xlsx_tool import _gate_forbidden_mechanism
    _stamp_with_title(monkeypatch, "执行write all后重启设备")
    err = _gate_forbidden_mechanism(_A)
    assert err and "bed-forbidden mechanism" in err and "重启" in err
    # 用户裁决落盘(H1:机制类免 form)→ 门放行
    (_OUT / "user_decision.json").write_text(json.dumps(
        {"autoid": _A, "decision": "改过程", "note": "重启→clear 验证(模型条件等价)"},
        ensure_ascii=False), encoding="utf-8")
    assert _gate_forbidden_mechanism(_A) is None


def test_emit_gate_noop_without_stamp():
    """无盖章(非引擎路径/存量)→ 门不触发,零回归。"""
    from main.ist_core.tools.device.emit_xlsx_tool import _gate_forbidden_mechanism
    assert _gate_forbidden_mechanism(_A) is None


# ── brief 下发块 ────────────────────────────────────────────────────────────

def test_brief_carries_forbidden_block(monkeypatch):
    from main.ist_core.compile_engine_v8 import briefs as BR
    _stamp_with_title(monkeypatch, "执行write net后重启设备")
    b = BR.build_brief(_A, {"manifest_ref": "", "max_rounds": 3}, [])
    assert "<forbidden_mechanism" in b and "compile_report_underdetermined" in b
    # 裁决已落盘 → 指令块撤(worker 按 user_decision 编写,不再重复呈报)
    (_OUT / "user_decision.json").write_text(json.dumps(
        {"autoid": _A, "decision": "改过程", "note": "clear 验证"}, ensure_ascii=False),
        encoding="utf-8")
    b2 = BR.build_brief(_A, {"manifest_ref": "", "max_rounds": 3}, [])
    assert "<forbidden_mechanism" not in b2
