"""批量编译工具：compile_emit_merged 合并契约 + batch_tools 输入校验。

合并 xlsx 是"每脑图一个 excel"的打包核心。最关键的契约：N 个真 case + 1 个
垫底哨兵，前 N 个真 case 全部走正常执行路径（框架延迟执行模型，见 emit_xlsx_tool
_build_sentinel）。标题可重名不去重，autoid 是主键，每 case 自带 init。
"""

from __future__ import annotations

import json

from main.ist_core.tools.device import compile_emit_merged, dev_run_batch


def _cases():
    return [
        {"autoid": "B100", "init": "cfg a1\ncfg a2", "title": "case A",
         "steps": [{"E": "test_env", "F": "clientc", "G": "dig x", "desc": "t"},
                   {"E": "check_point", "F": "found", "G": "1.1.1.1", "desc": "hit"}]},
        {"autoid": "B101", "init": "cfg b1", "title": "dup-title",
         "steps": [{"E": "test_env", "F": "clientc", "G": "dig y", "desc": "t"},
                   {"E": "check_point", "F": "abs_found", "G": "OK", "desc": "hit"}]},
        {"autoid": "B102", "init": "", "title": "dup-title",  # 无 init（短自包含型）
         "steps": [{"E": "APV_0", "F": "cmd_config", "G": "show version", "desc": "x"},
                   {"E": "check_point", "F": "found", "G": "Version", "desc": "v"}]},
    ]


def test_merged_emit_appends_single_sentinel_and_keeps_all_cases(tmp_path):
    out = compile_emit_merged.invoke(
        {"cases_json": json.dumps(_cases()), "out_name": "_pytest_merged"})
    assert "已合并 3 个真 case + 1 哨兵" in out
    # round-trip 必须回读出 4 个 case（3 真 + 1 哨兵），顺序正确，哨兵垫底
    assert "'case_count': 4" in out
    assert "'999999999999999'" in out
    assert out.index("B100") < out.index("B101") < out.index("B102")
    assert "'check_point_count': 3" in out


def test_merged_emit_does_not_dedupe_titles_but_rejects_dup_autoid():
    # 标题重名（dup-title 出现两次）允许；autoid 重复必须拒
    bad = _cases()
    bad[1]["autoid"] = "B100"  # 与第一个撞 autoid
    out = compile_emit_merged.invoke({"cases_json": json.dumps(bad)})
    assert "error" in out and "重复" in out


def test_merged_emit_rejects_case_without_checkpoint():
    bad = [{"autoid": "C1", "init": "", "steps": [
        {"E": "APV_0", "F": "cmd_config", "G": "show version", "desc": "x"}]}]
    out = compile_emit_merged.invoke({"cases_json": json.dumps(bad)})
    assert "error" in out and "check_point" in out


def test_merged_emit_rejects_empty():
    assert "error" in compile_emit_merged.invoke({"cases_json": "[]"})
    assert "error" in compile_emit_merged.invoke({"cases_json": "not json"})


def test_run_batch_rejects_bad_autoids():
    out = dev_run_batch.invoke({"xlsx_path": "x.xlsx", "autoids_json": "[]"})
    assert "error" in out
    out2 = dev_run_batch.invoke({"xlsx_path": "x.xlsx", "autoids_json": "nope"})
    assert "error" in out2


def test_run_batch_rejects_missing_xlsx():
    out = dev_run_batch.invoke(
        {"xlsx_path": "does/not/exist.xlsx", "autoids_json": json.dumps(["A1"])})
    assert "error" in out and "不存在" in out


# ---------------------------------------------------------------------------
# 整份单跑核心逻辑（mock FrameworkMCPClient，不碰真设备，与端到端跑零冲突）
#
# dev_run_batch 的新契约（O(N) 修复）：整份 xlsx **只 deliver+run 一次**（框架把整份当套件
# 整跑），再从 submit staging 一把读回所有 case 的逐 check_point 裁决；verdict 取每 case 专属
# 日志的 #### Success/Fail Num；非 pass 附 device_context。下面用假 client 验证这些不变量。
# ---------------------------------------------------------------------------

import re as _re  # noqa: E402

import pytest  # noqa: E402


class _FakeClient:
    """假框架 client：整份只提交一次，fetch_batch_details 一把返回所有 case 日志。

    instances 记录开了几个 client（单会话应只 1 个）。
    """

    instances: list["_FakeClient"] = []

    def __init__(self, *, deliver=None, run=None, details=None, ctx="dev-ctx"):
        self._deliver = deliver or {}
        self._run = run if run is not None else {"task_id": "T1"}
        self._details = details or {}     # {inner_autoid: detail_text}
        self._ctx = ctx
        self.calls: list[tuple[str, str]] = []
        _FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def deliver(self, module, autoid, path):
        self.calls.append(("deliver", autoid))
        return self._deliver

    def run_and_wait(self, module, autoid, build, autoids, max_s):
        self.calls.append(("run", autoid))
        return self._run

    def fetch_batch_details(self, submit_autoid):
        self.calls.append(("batch_details", submit_autoid))
        return self._details

    def fetch_device_context_under(self, submit_autoid, inner_autoid):
        self.calls.append(("ctx", inner_autoid))
        return self._ctx

    def fetch_task_log_errors(self, task_id, max_chars=2800):
        self.calls.append(("task_log", task_id))
        return getattr(self, "_task_log", "")


def _make_merged_xlsx(tmp_path):
    """产一个真合并 xlsx，返回 (路径, autoids)。"""
    out = compile_emit_merged.invoke(
        {"cases_json": json.dumps(_cases()), "out_name": "_pytest_runbatch"})
    m = _re.search(r"→ (\S+case\.xlsx)", out)
    assert m, f"未从 emit 输出解析到路径: {out}"
    return m.group(1), ["B100", "B101", "B102"]


@pytest.fixture
def _patch_client(monkeypatch):
    _FakeClient.instances = []

    def _install(**kwargs):
        import main.case_compiler.device_mcp_client as dmc
        monkeypatch.setattr(dmc, "FrameworkMCPClient",
                            lambda *a, **k: _FakeClient(**kwargs))
    return _install


def test_run_batch_one_submit_collects_all(tmp_path, _patch_client):
    """整份只 deliver+run 一次（O(N) 关键），再一把读回全部 case 裁决。"""
    path, autoids = _make_merged_xlsx(tmp_path)
    _patch_client(run={"task_id": "T1"},
                  details={a: "#### Success Num 1: ok" for a in autoids})

    out = dev_run_batch.invoke({"xlsx_path": path, "autoids_json": json.dumps(autoids),
                               "module": "sdns", "build": "b1"})
    recs = json.loads(out)
    assert [r["autoid"] for r in recs] == autoids
    assert all(r["verdict"] == "pass" for r in recs)

    assert len(_FakeClient.instances) == 1   # 单会话
    calls = _FakeClient.instances[0].calls
    # 整份只 deliver 一次、run 一次（不再 per-autoid 重复整跑）
    assert len([c for c in calls if c[0] == "deliver"]) == 1
    assert len([c for c in calls if c[0] == "run"]) == 1
    assert ("batch_details", "B100") in calls   # 用首个 autoid 作 submit/staging


def test_run_batch_verdict_from_per_case_log(tmp_path, _patch_client):
    """verdict 取每 case 专属日志的 #### Success/Fail Num；无日志→unknown；非 pass 附 device_context。"""
    path, autoids = _make_merged_xlsx(tmp_path)
    _patch_client(run={"task_id": "T1"}, details={
        "B100": "#### Success Num 1: ok\n#### Success Num 2: ok",   # pass
        "B101": "#### Fail Num 1: fail to find X in: ",             # fail
        # B102 无日志 → unknown（未执行到/被跳过）
    })
    out = dev_run_batch.invoke({"xlsx_path": path, "autoids_json": json.dumps(autoids)})
    by = {r["autoid"]: r for r in json.loads(out)}
    assert by["B100"]["verdict"] == "pass"
    assert by["B101"]["verdict"] == "fail"
    assert by["B102"]["verdict"] == "unknown"
    # 非 pass 附 device_context，pass 不附（省体积）
    assert "device_context" in by["B101"] and "device_context" in by["B102"]
    assert "device_context" not in by["B100"]


def test_run_batch_extracts_causality(tmp_path, _patch_client):
    """causality 抽 Success/Fail Num 行；task_id 透传。"""
    path, autoids = _make_merged_xlsx(tmp_path)
    _patch_client(run={"task_id": "T1"}, details={
        "B100": "noise\n#### Success Num 3: ok\n#### Fail Num 0\nmore noise",
        "B101": "#### Success Num 1: ok",
        "B102": "#### Success Num 1: ok",
    })
    out = dev_run_batch.invoke({"xlsx_path": path, "autoids_json": json.dumps(autoids)})
    r0 = json.loads(out)[0]
    assert r0["task_id"] == "T1"
    assert "Success Num 3" in r0["causality"]


def test_run_batch_busy_on_submit(tmp_path, _patch_client):
    """整份提交撞全局锁 → 整批返回 busy 结构（agent 据此等待/重试），不误判为编译错误。"""
    path, autoids = _make_merged_xlsx(tmp_path)
    _patch_client(run={"busy": True, "error": "device_busy",
                       "message": "环境忙：正在验证上一个用例，已运行 50s"})
    out = dev_run_batch.invoke({"xlsx_path": path, "autoids_json": json.dumps(autoids)})
    res = json.loads(out)
    assert res.get("busy") is True and "环境忙" in res.get("message", "")


def test_run_batch_deliver_fail_errors(tmp_path, _patch_client):
    """deliver 失败（整份交付不上去）→ 直接报错，不继续。"""
    path, autoids = _make_merged_xlsx(tmp_path)
    _patch_client(deliver={"error": "deliver boom"})
    out = dev_run_batch.invoke({"xlsx_path": path, "autoids_json": json.dumps(autoids)})
    res = json.loads(out)
    assert "error" in res and "deliver" in res["error"]
