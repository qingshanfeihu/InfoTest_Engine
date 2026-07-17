# -*- coding: utf-8 -*-
"""#74-② merge 单案预检(run13 二次实证:单案凭证拒绝曾 error→closing 全批零上机)。

契约:凭证过期/lint 违例的案落 emit_invalid 事实打回重编(fold 回 pending),
其余照常合并——单案违例不再拖死全批。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from main.ist_core.tools.device.emit_xlsx_tool import precheck_merge_case
from main.ist_core.compile_engine_v8 import views as V
from main.ist_core.compile_engine_v8 import _shared as _sh
A = "203699999999000801"


@pytest.fixture()
def emitted_case():
    """真 emit 产一份带新鲜凭证的卷(过全部机械门)。"""
    from main.ist_core.tools.device.emit_xlsx_tool import compile_emit
    steps = [
        {"E": "APV_0", "F": "cmds_config", "G": "sdns on\nsdns listener 172.16.34.70 53"},
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener"},
        {"E": "check_point", "F": "found", "G": r"172\.16\.34\.70"},
        {"E": "APV_0", "F": "cmds_config", "G": "no sdns listener\nno sdns on"},
    ]
    out = compile_emit.func(autoid=A, steps=steps, init_commands="", out_name=A)
    assert "produced structurally-correct xlsx" in out, out[:300]
    yield _sh.outputs_root() / A
    import shutil
    shutil.rmtree(_sh.outputs_root() / A, ignore_errors=True)


def test_precheck_fresh_case_ready(emitted_case):
    assert precheck_merge_case(A) is None


def test_precheck_catches_post_emit_tamper(emitted_case):
    """emit 后直改卷面(run13 668015 形态)→ 凭证过期,预检拒。"""
    xp = emitted_case / "case.xlsx"
    time.sleep(0.02)
    xp.touch()   # mtime 变=卷面在凭证之后被动过
    reason = precheck_merge_case(A)
    assert reason and "凭证过期" in reason


def test_precheck_missing_credential(emitted_case):
    (emitted_case / ".grade_credential.json").unlink()
    reason = precheck_merge_case(A)
    assert reason and "缺 lint 凭证" in reason


def test_precheck_missing_xlsx():
    assert precheck_merge_case("203699999999000999") is not None


# ---------------------------------------------------------------- fold 语义
def test_fold_emit_invalid_returns_to_pending():
    """emit_invalid 晚于最新 authored → 回待编写;重编(新 authored)后解除。"""
    aid = A
    fs = [{"ev": "authored", "aid": aid, "round": 1, "artifact": "a1"}]
    manifest = {"cases": [{"autoid": aid}]}
    assert V.batch_view(fs, manifest)["cases"][aid]["status"] == V.S_AUTHORED
    fs.append({"ev": "emit_invalid", "aid": aid, "reason": "stale credential",
               "artifact": "a1"})
    assert V.batch_view(fs, manifest)["cases"][aid]["status"] == V.S_PENDING
    fs.append({"ev": "authored", "aid": aid, "round": 2, "artifact": "a2"})
    assert V.batch_view(fs, manifest)["cases"][aid]["status"] == V.S_AUTHORED


def test_fold_emit_invalid_not_terminal_priority():
    """终态/挂起优先级高于 emit_invalid 打回(打回不覆盖用户裁决)。"""
    aid = A
    fs = [{"ev": "authored", "aid": aid, "round": 1, "artifact": "a1"},
          {"ev": "emit_invalid", "aid": aid, "reason": "x", "artifact": "a1"},
          {"ev": "suspended", "aid": aid, "reason": "user"}]
    assert V.batch_view(fs, {"cases": [{"autoid": aid}]})["cases"][aid]["status"] == V.S_SUSPENDED
