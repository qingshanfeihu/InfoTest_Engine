"""闭环写回回归(V4 步骤4,定理3.22:上机 PASS 写回先例库,ρ_k 编译期增长)。

实证反面:写回链路长期未生效,V 轮 worker 把上一轮已验证过的坑原样重踩。
机械门:上机 oracle(last_run verdict==pass)+ 凭证新鲜(写回的就是上机那份)。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from main.ist_core.tools.device import compile_emit
from main.ist_core.tools.device.precedent_tools import (
    _INTENT_INDEX_PATH,
    _MIRROR,
    compile_writeback,
)

AID = "203031750000000901"


@pytest.fixture()
def verified_case(tmp_path):
    blocks = [
        {"kind": "CONFIG", "cmds": ["sdns on", "sdns listener 172.16.34.70",
                                    "sdns host name wb.com", "sdns service ip s1 172.16.35.213",
                                    "sdns pool name p1", "sdns pool service p1 s1",
                                    "sdns host pool wb.com p1"], "desc": "基线"},
        {"kind": "OBSERVE_ASSERT", "host": "routera", "cmd": "dig @172.16.34.70 wb.com",
         "asserts": [{"op": "found", "pattern": r"\b172\.16\.35\.213\b"}]},
    ]
    out = compile_emit.invoke({"autoid": AID, "blocks": blocks, "out_name": AID})
    assert "produced structurally-correct" in out
    lr = Path("workspace/outputs") / AID / "last_run.json"
    lr.write_text(json.dumps([{"autoid": AID, "verdict": "pass"}]), encoding="utf-8")
    yield lr
    shutil.rmtree(Path("workspace/outputs") / AID, ignore_errors=True)
    (_MIRROR / f"verified_{AID}.xlsx").unlink(missing_ok=True)
    try:
        idx = json.loads(_INTENT_INDEX_PATH.read_text(encoding="utf-8"))
        if idx.pop(f"verified_{AID}.xlsx", None) is not None:
            _INTENT_INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    except Exception:
        pass


def test_writeback_pass_case(verified_case):
    r = compile_writeback.invoke({"autoid": AID, "last_run_path": str(verified_case),
                                  "intent_path": "测试 > 写回验证"})
    assert "已写回" in r
    assert (_MIRROR / f"verified_{AID}.xlsx").is_file()
    idx = json.loads(_INTENT_INDEX_PATH.read_text(encoding="utf-8"))
    assert idx.get(f"verified_{AID}.xlsx") == ["测试 > 写回验证"]


def test_writeback_rejects_fail_verdict(verified_case):
    lr = Path("workspace/outputs") / AID / "lr_fail.json"
    lr.write_text(json.dumps([{"autoid": AID, "verdict": "fail"}]), encoding="utf-8")
    r = compile_writeback.invoke({"autoid": AID, "last_run_path": str(lr)})
    assert r.startswith("error") and "PASS" in r


def test_writeback_rejects_stale_volume(verified_case):
    # 凭证之后直改卷面 → mtime 不匹配 → 拒(上机验证的不是这份)
    import os
    xp = Path("workspace/outputs") / AID / "case.xlsx"
    os.utime(xp)
    r = compile_writeback.invoke({"autoid": AID, "last_run_path": str(verified_case)})
    assert r.startswith("error") and "改过" in r


def test_writeback_rejects_path_traversal():
    """autoid 路径穿越拒绝(安全评审高危项 2026-07-04):未净化 aid 可写穿沙箱。"""
    for aid in ["../../../../tmp/pwned", "../../evil", "..", "a/b", "x;y"]:
        r = compile_writeback.invoke({"autoid": aid, "last_run_path": "workspace/x.json"})
        assert r.startswith("error"), (aid, r)


def test_writeback_rejects_absolute_last_run(verified_case):
    r = compile_writeback.invoke({"autoid": AID, "last_run_path": "/etc/passwd"})
    assert r.startswith("error") and "workspace" in r
