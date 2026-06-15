"""批量编译工具：qa_emit_xlsx_merged 合并契约 + batch_tools 输入校验。

合并 xlsx 是"每脑图一个 excel"的打包核心。最关键的契约：N 个真 case + 1 个
垫底哨兵，前 N 个真 case 全部走正常执行路径（框架延迟执行模型，见 emit_xlsx_tool
_build_sentinel）。标题可重名不去重，autoid 是主键，每 case 自带 init。
"""

from __future__ import annotations

import json

from main.ist_core.tools.device import qa_emit_xlsx_merged, qa_run_batch


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
    out = qa_emit_xlsx_merged.invoke(
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
    out = qa_emit_xlsx_merged.invoke({"cases_json": json.dumps(bad)})
    assert "error" in out and "重复" in out


def test_merged_emit_rejects_case_without_checkpoint():
    bad = [{"autoid": "C1", "init": "", "steps": [
        {"E": "APV_0", "F": "cmd_config", "G": "show version", "desc": "x"}]}]
    out = qa_emit_xlsx_merged.invoke({"cases_json": json.dumps(bad)})
    assert "error" in out and "check_point" in out


def test_merged_emit_rejects_empty():
    assert "error" in qa_emit_xlsx_merged.invoke({"cases_json": "[]"})
    assert "error" in qa_emit_xlsx_merged.invoke({"cases_json": "not json"})


def test_run_batch_rejects_bad_autoids():
    out = qa_run_batch.invoke({"xlsx_path": "x.xlsx", "autoids_json": "[]"})
    assert "error" in out
    out2 = qa_run_batch.invoke({"xlsx_path": "x.xlsx", "autoids_json": "nope"})
    assert "error" in out2


def test_run_batch_rejects_missing_xlsx():
    out = qa_run_batch.invoke(
        {"xlsx_path": "does/not/exist.xlsx", "autoids_json": json.dumps(["A1"])})
    assert "error" in out and "不存在" in out


# ---------------------------------------------------------------------------
# 串行上机核心逻辑（mock FrameworkMCPClient，不碰真设备，与端到端跑零冲突）
#
# qa_run_batch 的硬约束：一条 SSH 会话内 for 循环顺序 deliver+run+取明细；某 case
# error 不中断后续；verdict 来自框架真实裁决。下面用假 client 验证这些不变量。
# ---------------------------------------------------------------------------

import re as _re  # noqa: E402

import pytest  # noqa: E402


class _FakeClient:
    """记录调用顺序的假框架 client，按 autoid 脚本化返回。

    instances 类属性记录"开了几个 client"——串行复用单会话应只开 1 个。
    """

    instances: list["_FakeClient"] = []

    def __init__(self, scripts):
        # scripts: {autoid: {"deliver": {...}, "run": {...}, "detail": "..."}}
        self._scripts = scripts
        self.calls: list[tuple[str, str]] = []  # (op, autoid) 全局顺序
        _FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def deliver(self, module, autoid, path):
        self.calls.append(("deliver", autoid))
        return self._scripts.get(autoid, {}).get("deliver", {})

    def run_and_wait(self, module, autoid, build, autoids, max_s):
        self.calls.append(("run", autoid))
        return self._scripts.get(autoid, {}).get("run", {"results": {autoid: "pass"}})

    def fetch_case_detail(self, autoid):
        self.calls.append(("detail", autoid))
        return self._scripts.get(autoid, {}).get("detail", "")


def _make_merged_xlsx(tmp_path):
    """产一个真合并 xlsx，返回 (路径, autoids)。"""
    out = qa_emit_xlsx_merged.invoke(
        {"cases_json": json.dumps(_cases()), "out_name": "_pytest_runbatch"})
    m = _re.search(r"→ (\S+case\.xlsx)", out)
    assert m, f"未从 emit 输出解析到路径: {out}"
    return m.group(1), ["B100", "B101", "B102"]


@pytest.fixture
def _patch_client(monkeypatch):
    _FakeClient.instances = []

    def _install(scripts):
        import main.case_compiler.device_mcp_client as dmc
        monkeypatch.setattr(dmc, "FrameworkMCPClient",
                            lambda *a, **k: _FakeClient(scripts))
    return _install


def test_run_batch_serial_order_single_session(tmp_path, _patch_client):
    """三个 case 必须按输入顺序 deliver→run→detail，且只开一条会话。"""
    path, autoids = _make_merged_xlsx(tmp_path)
    _patch_client({a: {"run": {"results": {a: "pass"}}, "detail": "Success Num: 1"}
                   for a in autoids})

    out = qa_run_batch.invoke({"xlsx_path": path, "autoids_json": json.dumps(autoids),
                               "module": "sdns", "build": "b1"})
    recs = json.loads(out)
    assert [r["autoid"] for r in recs] == autoids
    assert all(r["verdict"] == "pass" for r in recs)

    # 只开 1 个 client（复用单 SSH 会话）
    assert len(_FakeClient.instances) == 1
    # 每个 autoid 严格 deliver→run→detail，且 case 间不交错（串行）
    calls = _FakeClient.instances[0].calls
    assert calls == [
        ("deliver", "B100"), ("run", "B100"), ("detail", "B100"),
        ("deliver", "B101"), ("run", "B101"), ("detail", "B101"),
        ("deliver", "B102"), ("run", "B102"), ("detail", "B102"),
    ]


def test_run_batch_error_does_not_halt_remaining(tmp_path, _patch_client):
    """中间 case deliver 失败，后续 case 仍必须继续上机。"""
    path, autoids = _make_merged_xlsx(tmp_path)
    _patch_client({
        "B100": {"run": {"results": {"B100": "pass"}}, "detail": "Success Num: 1"},
        "B101": {"deliver": {"error": "deliver boom"}},  # 中间炸
        "B102": {"run": {"results": {"B102": "fail"}}, "detail": "Fail Num: 2"},
    })
    out = qa_run_batch.invoke({"xlsx_path": path, "autoids_json": json.dumps(autoids)})
    recs = json.loads(out)
    assert len(recs) == 3  # 三条都有记录，不中断
    assert recs[0]["verdict"] == "pass"
    assert recs[1]["verdict"] == "error" and "deliver" in recs[1]["detail_tail"]
    assert recs[2]["verdict"] == "fail"  # 中间炸后第三个照常跑
    # B101 run 不应被调用（deliver 失败即 continue）
    calls = _FakeClient.instances[0].calls
    assert ("run", "B101") not in calls
    assert ("run", "B102") in calls


def test_run_batch_extracts_verdict_and_causality(tmp_path, _patch_client):
    """verdict 取框架 results；causality 抽 Success/Fail Num 行。"""
    path, autoids = _make_merged_xlsx(tmp_path)
    _patch_client({
        "B100": {"run": {"results": {"B100": "pass"}, "task_id": "T1"},
                 "detail": "noise\nSuccess Num: 3\nFail Num: 0\nmore noise"},
        "B101": {"run": {"results": {"B101": "pass"}}, "detail": "x"},
        "B102": {"run": {"results": {"B102": "pass"}}, "detail": "x"},
    })
    out = qa_run_batch.invoke({"xlsx_path": path, "autoids_json": json.dumps(autoids)})
    recs = json.loads(out)
    r0 = recs[0]
    assert r0["task_id"] == "T1"
    assert "Success Num: 3" in r0["causality"] and "Fail Num: 0" in r0["causality"]


def test_run_batch_marks_busy_verdict_when_device_locked(tmp_path, _patch_client):
    """run_and_wait 撞锁返回 busy 时，run_batch 标 verdict=busy(非 error)，且不中断后续。"""
    path, autoids = _make_merged_xlsx(tmp_path)
    _patch_client({
        "B100": {"run": {"results": {"B100": "pass"}}, "detail": "Success Num: 1"},
        # B101 撞锁：run_and_wait 返回 busy 结构
        "B101": {"run": {"busy": True, "error": "device_busy",
                         "message": "环境忙：正在验证用例 B100，已运行 50s"}},
        "B102": {"run": {"results": {"B102": "pass"}}, "detail": "Success Num: 1"},
    })
    out = qa_run_batch.invoke({"xlsx_path": path, "autoids_json": json.dumps(autoids)})
    recs = json.loads(out)
    assert recs[0]["verdict"] == "pass"
    assert recs[1]["verdict"] == "busy" and "环境忙" in recs[1]["detail_tail"]
    assert recs[2]["verdict"] == "pass"   # busy 不中断后续
