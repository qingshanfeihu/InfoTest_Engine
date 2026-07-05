"""性能双病灶回归(2026-07-04 dongkl 闭环取证驱动)。

两个实测浪费源:
- token:凭证新鲜 PASS 的卷被反复重派 grade fork(单 fork 300k-1M 输入,收口期十余次
  ≈5-10M token 零信息增量)→ compile_fanout 短路。
- 上机:staging 目录跨 run 复用,被打断执行的旧日志被新 digest 收割成假结果(0/34、
  1/34 两轮),假 fail 又触发无效修复轮 → run-identity(deliver 时刻跳板机 epoch)绑定,
  旧日志判 stale 不产 verdict。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from main.ist_core.tools.device import compile_emit, submit_verdict
from main.ist_core.tools.device.batch_tools import compile_fanout
from main.case_compiler.device_mcp_client import FrameworkMCPClient

AID = "203031750000000301"

_STEPS = [
    {"D": "配置", "E": "APV_0", "F": "cmds_config",
     "G": "sdns on\nsdns listener 172.16.34.70\nsdns host name t.com\nsdns service ip s1 172.16.35.213\nsdns pool name p1\nsdns pool service p1 s1\nsdns host pool t.com p1"},
    {"D": "触发", "E": "test_env", "F": "routera", "G": "dig @172.16.34.70 t.com"},
    {"D": "断言", "E": "check_point", "F": "found", "G": r"\b172\.16\.35\.213\b"},
]


@pytest.fixture()
def fresh_pass_case():
    compile_emit.invoke({"autoid": AID, "steps": _STEPS, "out_name": AID})
    out = submit_verdict.invoke({"autoid": AID, "verdict": "PASS",
                                 "xlsx_path": f"workspace/outputs/{AID}/case.xlsx"})
    assert "已提交" in out
    yield AID
    shutil.rmtree(Path("workspace/outputs") / AID, ignore_errors=True)


def test_fanout_skips_fresh_pass_grade(fresh_pass_case):
    r = compile_fanout.invoke({"skill": "ist-compile-grade",
                               "briefs_json": [{"key": AID, "brief": "重新审批"}]})
    arr = json.loads(r)
    assert len(arr) == 1 and "SKIPPED_FRESH_PASS" in arr[0]["output"]


def test_fanout_force_regrade_bypasses_skip(fresh_pass_case):
    # 假 skill 名让 fork 立即失败——只验证没有被短路(短路项 output 含 SKIPPED)
    r = compile_fanout.invoke({"skill": "grade_no_such_skill",
                               "briefs_json": [{"key": AID, "brief": "b"}],
                               "force_regrade": True})
    assert "SKIPPED" not in json.loads(r)[0].get("output", "")


def test_fanout_non_grade_skill_not_skipped(fresh_pass_case):
    r = compile_fanout.invoke({"skill": "worker_no_such_skill",
                               "briefs_json": [{"key": AID, "brief": "b"}]})
    assert "SKIPPED" not in json.loads(r)[0].get("output", "")


def test_fanout_stale_credential_not_skipped(fresh_pass_case):
    # 卷面变了(mtime 变)→ 凭证过期 → 必须重派(不短路)
    xp = Path("workspace/outputs") / AID / "case.xlsx"
    import os
    os.utime(xp)  # touch
    r = compile_fanout.invoke({"skill": "grade_no_such_skill",
                               "briefs_json": [{"key": AID, "brief": "b"}]})
    assert "SKIPPED" not in json.loads(r)[0].get("output", "")


class _FakeSSH:
    """离线仿真 fetch_batch_details 的 SSH 通道(协议:<<<CASE:aid|mtime>>>body)。"""
    def __init__(self, raw: str):
        self._raw = raw
    def exec_command(self, cmd, timeout=0):
        raw = self._raw
        class _O:
            def read(self):
                return raw.encode()
        return None, _O(), None


def test_fetch_batch_details_marks_stale_logs():
    fake = FrameworkMCPClient.__new__(FrameworkMCPClient)
    fake._c = _FakeSSH("<<<CASE:OLD1|100>>>#### Fail Num 1"
                       "<<<CASE:NEW1|9999999999>>>#### Success Num 1")
    d = fake.fetch_batch_details("SUBMIT", min_epoch=5000)
    assert d["OLD1"] == FrameworkMCPClient.STALE_LOG_MARK
    assert "Success" in d["NEW1"]
    # min_epoch=0(不启用)→ 全收,兼容旧行为
    d2 = fake.fetch_batch_details("SUBMIT", min_epoch=0)
    assert "Fail" in d2["OLD1"]
