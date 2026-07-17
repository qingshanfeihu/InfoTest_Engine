"""F1 期望可疑臂(§18.11 五稿;(40) 第七类,K §2.12.1)。

- 词表:_DISPS 扩 expectation_suspect(满射不变量随 (40) 第七类同步)。
- panel 併呈机械门(评审 D21 活锁防护):expectation_suspect 必须携同轮
  submit_ask_panel(outputs/<aid>/ask_panel.json 在盘)——否则 author 不重编、
  merge 不复跑、无 ask 目标=活锁。裁决折叠既有终态,不新增 @99 终态。
- remedies:该处置无分支→队列空=「ask 合法」,恰是设计(引擎无单方修法权)。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from main.ist_core.tools.device.fail_attribution import submit_attribution
from main.ist_core.compile_engine_v8 import _shared as _sh

_A = "203099999999900088"


def _out():
    # F-Py-9b-2:原 outputs 目录模块常量(import 时=生产)改测试时求值——随全局 fixture 落 tmp。
    return _sh.outputs_root() / _A


@pytest.fixture(autouse=True)
def _clean():
    shutil.rmtree(_out(), ignore_errors=True)
    yield
    shutil.rmtree(_out(), ignore_errors=True)


def test_expectation_suspect_requires_panel():
    out = submit_attribution.func(xlsx_path="workspace/outputs/none.xlsx", autoid=_A,
                                  layer="V", disposition="expectation_suspect",
                                  evidence="x", fix_direction="d")
    assert str(out).startswith("error") and "submit_ask_panel" in str(out)


def test_expectation_suspect_passes_gate_with_panel():
    _out().mkdir(parents=True, exist_ok=True)
    (_out() / "ask_panel.json").write_text(json.dumps(
        {"autoid": _A, "conflict_shape": "expected_vs_observed"}, ensure_ascii=False),
        encoding="utf-8")
    out = submit_attribution.func(xlsx_path="workspace/outputs/none.xlsx", autoid=_A,
                                  layer="V", disposition="expectation_suspect",
                                  evidence="x", fix_direction="d")
    # panel 门放行后落到后续台账/路径校验(与本门无关的错误),不得再是 panel 错误
    assert "submit_ask_panel" not in str(out)


def test_unknown_disposition_still_rejected():
    out = submit_attribution.func(xlsx_path="x", autoid=_A, layer="V",
                                  disposition="not_a_disp", evidence="e")
    assert str(out).startswith("error") and "expectation_suspect" in str(out)


def test_remedies_empty_queue_for_expectation_suspect():
    """队列空=「ask 合法」(引擎无单方修法权;面板由併呈门保证在场)。"""
    from main.ist_core.compile_engine_v8.remedies import derive_queue
    from main.ist_core.compile_engine_v8 import views as V
    mine = [{"ev": "authored", "aid": _A, "round": 1},
            {"ev": "verdict", "aid": _A, "result": "fail", "run_id": "r1"},
            {"ev": "attribution", "aid": _A, "round": 1, "layer": "V",
             "disposition": "expectation_suspect", "run_id": "r1"}]
    vw = {"cases": {_A: {"status": V.S_FAILED, "rounds": 1}}}
    q = derive_queue(mine, vw, _A, max_rounds=3)
    assert q == []
