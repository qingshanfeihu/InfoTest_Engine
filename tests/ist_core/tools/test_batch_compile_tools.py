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


def test_parse_autoids_arg_not_given_falls_through():
    from main.ist_core.tools.device.emit_xlsx_tool import _parse_autoids_arg

    assert _parse_autoids_arg(None) == (None, None)
    assert _parse_autoids_arg("") == (None, None)
    assert _parse_autoids_arg("   ") == (None, None)
    assert _parse_autoids_arg([]) == (None, None)


def test_parse_autoids_arg_given_but_empty_errors():
    from main.ist_core.tools.device.emit_xlsx_tool import _parse_autoids_arg

    aids, err = _parse_autoids_arg("[]")
    assert aids == [] and err and "解析为空" in err

    aids, err = _parse_autoids_arg(["", "  "])
    assert aids == [] and err and "无有效 id" in err

    aids, err = _parse_autoids_arg("  ,  , ")
    assert aids == [] and err and "解析为空" in err


def test_parse_autoids_arg_valid_inputs():
    from main.ist_core.tools.device.emit_xlsx_tool import _parse_autoids_arg

    assert _parse_autoids_arg(["B100", "B101"]) == (["B100", "B101"], None)
    assert _parse_autoids_arg('["B100","B101"]') == (["B100", "B101"], None)
    assert _parse_autoids_arg("B100,B101") == (["B100", "B101"], None)


def test_merged_emit_autoids_empty_json_errors_not_cases_json():
    """显式传 autoids='[]' 应走 autoids 分支报错，不应误落到 cases_json。"""
    out = compile_emit_merged.invoke({"autoids": "[]", "cases_json": "[]"})
    assert "error" in out and "autoids" in out and "解析为空" in out


def test_merged_emit_blank_autoids_falls_through_to_cases_json():
    """空串 autoids 应走 cases_json（与未传 autoids 等价）。"""
    out = compile_emit_merged.invoke({"autoids": "", "cases_json": "[]"})
    assert "error" in out and "需传 autoids" in out or "cases_json" in out


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

    def run_and_wait(self, module, autoid, build, autoids, max_s, progress_cb=None):
        self.calls.append(("run", autoid))
        # 模拟两次轮询进度回调（results 渐增 + log_tail），供进度 fastlog 测试
        if progress_cb is not None:
            progress_cb({"results": {"B100": {}}, "log_tail": "case B100 running"})
            progress_cb({"results": {"B100": {}, "B101": {}}, "log_tail": "case B101 running"})
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


# ── dev_run_batch_digest：整份上机 + 逐 case 四层归因 + 明细落 workspace ──────────
# 提炼自 ist_verify 确定性核（首跑→拆逐case→四层归因），给 bare main 一键可调：大结果在
# **进程内**消化，agent 只拿几 KB 分类摘要（不被 offload），深挖再 fs_read/grep 明细文件。
# 测试用 mock dev_run_batch.func 隔离 digest 的 value-add（分类/计数/落盘/精简返回），不碰真设备。

def _digest_setup_sandbox(tmp_path, monkeypatch):
    """把 file_tools 沙箱根指到 tmp，建 workspace/outputs/feat/case.xlsx（占位存在即可，
    digest 不读它内容，只用它的父目录定 last_run.json 落点）。返回 feature 目录。"""
    import main.ist_core.tools.deepagent.file_tools as ft
    ws = tmp_path / "workspace"
    outd = ws / "outputs" / "feat"
    outd.mkdir(parents=True)
    (outd / "case.xlsx").write_bytes(b"PK\x03\x04stub")
    (tmp_path / "knowledge" / "data").mkdir(parents=True)
    monkeypatch.setattr(ft, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ft, "_AGENT_ROOT", tmp_path / "knowledge" / "data")
    monkeypatch.setattr(ft, "_WORKSPACE_ROOT", ws)
    monkeypatch.delenv("IST_SESSION_DIR", raising=False)
    monkeypatch.delenv("IST_USER_DIR", raising=False)
    return outd


# 机械预判只认 ^（设备语法拒绝）→ G；其余 fail 一律 undetermined（原文交 LLM 归因）。
_DIGEST_SYNTH = [
    {"autoid": "A_pass", "verdict": "pass", "causality": "successed to find 1.1.1.1", "detail_tail": "ok"},
    {"autoid": "A_g", "verdict": "fail", "causality": "fail to find", "detail_tail": "x",
     "device_context": "APV(config)#sdns pool cnome p1\nsdns pool cnome p1\n          ^\nFailed to execute the command"},  # G：^ 语法拒绝
    {"autoid": "A_e", "verdict": "fail", "causality": "fail to find", "detail_tail": "x",
     "device_context": "dig: no answer from server"},          # 待归因（旧表判 E）
    {"autoid": "A_v", "verdict": "fail", "causality": "fail to find 2.2.2.2", "detail_tail": "x",
     "device_context": "ANSWER 2.2.2.2 (expected 3.3.3.3)"},   # 待归因（旧表默认 V）
    {"autoid": "A_t", "verdict": "fail", "causality": "fail", "detail_tail": "x",
     "device_context": "ssh connection timed out"},            # 待归因（旧表误判瞬态不回流）
    {"autoid": "A_u", "verdict": "unknown", "causality": "", "detail_tail": "",
     "framework_traceback": "Traceback (most recent call last)\nKeyError: 'pool'"},
]


def test_digest_classifies_counts_and_persists(tmp_path, monkeypatch):
    from main.ist_core.tools.device import batch_tools, dev_run_batch_digest
    outd = _digest_setup_sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(batch_tools.dev_run_batch, "func",
                        lambda *a, **k: json.dumps(_DIGEST_SYNTH, ensure_ascii=False))
    out = dev_run_batch_digest.invoke(
        {"xlsx_path": "workspace/outputs/feat/case.xlsx", "autoids_json": '["A_pass"]'})
    # 计数 + 分层（P/F(G(^)/待归因)/unknown）——机械只认 ^，其余不猜
    assert "P:1" in out and "F:4" in out and "unknown:1" in out
    assert "G(^拒绝):1 待归因:3" in out
    # 逐 case：^ 拒绝点名被拒命令原文；其余标待归因（不再猜 E/V/瞬态）
    assert "A_g | fail | G(^)" in out and "配置被拒" in out and "sdns pool cnome" in out
    assert "A_e | fail | - | 待归因" in out
    assert "A_v | fail | - | 待归因" in out
    assert "A_t | fail | - | 待归因" in out
    assert "A_u | unknown" in out and "KeyError" in out
    # 全量明细落 workspace：缩进 JSON、可 json.load、6 条齐全
    lr = outd / "last_run.json"
    assert lr.exists()
    data = json.loads(lr.read_text(encoding="utf-8"))
    assert len(data) == 6 and data[1]["autoid"] == "A_g"
    assert lr.read_text(encoding="utf-8").count("\n") > 6   # indent=2 → 多行，fs_read 可分页


def test_digest_passes_through_device_busy(tmp_path, monkeypatch):
    """上机 error/device_busy → digest 原样透传，不崩、不落假 last_run。"""
    from main.ist_core.tools.device import batch_tools, dev_run_batch_digest
    outd = _digest_setup_sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(batch_tools.dev_run_batch, "func",
                        lambda *a, **k: json.dumps({"error": "device_busy", "busy": True}))
    out = dev_run_batch_digest.invoke(
        {"xlsx_path": "workspace/outputs/feat/case.xlsx", "autoids_json": '["A"]'})
    assert "device_busy" in out
    assert not (outd / "last_run.json").exists()   # 出错不落盘


def test_digest_flags_found_times_crash_as_compile_defect(tmp_path, monkeypatch):
    """unknown 带 found_times 崩溃 traceback → digest 醒目标"文件级崩溃(编译缺陷,非框架bug)"，
    把 bare main 最易犯的"框架bug/无需改excel"误判**在工具层纠正**（这是 goal 的核心）。"""
    from main.ist_core.tools.device import batch_tools, dev_run_batch_digest
    _digest_setup_sandbox(tmp_path, monkeypatch)
    crashed = [
        {"autoid": "203031753342777976", "verdict": "pass", "causality": "successed to find"},
        {"autoid": "203031753342778072", "verdict": "unknown", "causality": "",
         "framework_traceback": "E  TypeError: found_times() missing 1 required positional argument: 'times'"},
        {"autoid": "203031754277681841", "verdict": "unknown", "causality": "",
         "framework_traceback": "found_times() missing"},
    ]
    monkeypatch.setattr(batch_tools.dev_run_batch, "func",
                        lambda *a, **k: json.dumps(crashed, ensure_ascii=False))
    out = dev_run_batch_digest.invoke(
        {"xlsx_path": "workspace/outputs/feat/case.xlsx", "autoids_json": '["A"]'})
    assert "文件级崩溃" in out and "编译缺陷" in out and "非框架bug" in out
    assert "found_times" in out and "重编" in out
    assert "级联" in out                       # 说清 unknown 是级联、非各自失败
    assert "excel" in out                      # 明确 excel 要动（纠正"无需改excel"误判）


def test_digest_cross_run_repeat_and_transient_recur(tmp_path, monkeypatch):
    """跨轮对照(确定性止损地基):同签名连续两轮 fail + 上轮"瞬态"标签本轮复现,摘要必须点名。

    实证(dongkl 第四→五轮):上轮归"瞬态"的 5 个 case 下一轮 100% 复现 fail=全部误归;
    同签名 fail 连续多轮被逐 case 重编无效烧钱。瞬态定义=不可复现——复现即系统性问题,
    该判定纯机械(比对两轮 last_run.json),不靠 LLM 自觉。
    注:新版机械预判不再产 transient 标签(见 fail_attribution 收缩重写);"上轮瞬态复现"
    分支保留用于兼容旧格式 last_run.json / LLM 归因后回写的标签——本测试手工构造旧格式验证。
    """
    from main.ist_core.tools.device import batch_tools, dev_run_batch_digest
    outd = _digest_setup_sandbox(tmp_path, monkeypatch)
    round1 = [
        {"autoid": "R_sig", "verdict": "fail", "causality": "#### Fail Num 1: fail to find \\b1.2.3.4\\b in:",
         "device_context": "ANSWER 5.6.7.8 (expected 1.2.3.4)"},          # 签名 \b1.2.3.4\b
        {"autoid": "R_trans", "verdict": "fail", "causality": "fail",
         "device_context": "ssh connection timed out"},
        {"autoid": "R_ok", "verdict": "pass", "causality": "successed to find"},
    ]
    monkeypatch.setattr(batch_tools.dev_run_batch, "func",
                        lambda *a, **k: json.dumps(round1, ensure_ascii=False))
    out1 = dev_run_batch_digest.invoke(
        {"xlsx_path": "workspace/outputs/feat/case.xlsx", "autoids_json": '["R_sig"]'})
    assert "跨轮对照" not in out1                       # 首轮无上一轮,不报
    # 模拟旧格式/LLM 回写:R_trans 上轮被归瞬态(新版机械预判不产该标签,但旧数据存在)
    lr = outd / "last_run.json"
    data1 = json.loads(lr.read_text(encoding="utf-8"))
    for r in data1:
        if r["autoid"] == "R_trans":
            r["_digest_layer"] = "transient"
    lr.write_text(json.dumps(data1, ensure_ascii=False, indent=2), encoding="utf-8")

    round2 = [
        {"autoid": "R_sig", "verdict": "fail", "causality": "#### Fail Num 1: fail to find \\b1.2.3.4\\b in:",
         "device_context": "ANSWER 5.6.7.8 (expected 1.2.3.4)"},          # 同签名再 fail
        {"autoid": "R_trans", "verdict": "fail", "causality": "fail",
         "device_context": "ssh connection timed out"},                    # "瞬态"复现
        {"autoid": "R_ok", "verdict": "pass", "causality": "successed to find"},
    ]
    monkeypatch.setattr(batch_tools.dev_run_batch, "func",
                        lambda *a, **k: json.dumps(round2, ensure_ascii=False))
    out2 = dev_run_batch_digest.invoke(
        {"xlsx_path": "workspace/outputs/feat/case.xlsx", "autoids_json": '["R_sig"]'})
    assert "跨轮对照" in out2 and "R_sig" in out2       # 同签名连续两轮点名
    assert "冻结同法重编" in out2                        # 止损指引
    assert "上轮归\"瞬态\"本轮复现" in out2 and "R_trans" in out2   # 误归瞬态点名(旧标签兼容)
    data2 = json.loads((outd / "last_run.json").read_text(encoding="utf-8"))
    sig_rec = next(r for r in data2 if r["autoid"] == "R_sig")
    assert sig_rec.get("_repeat_fail_same_signature") is True
