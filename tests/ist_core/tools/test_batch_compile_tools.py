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
# 提炼自 ist-verify 确定性核（首跑→拆逐case→四层归因），给 bare main 一键可调：大结果在
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


# ---------------------------------------------------------------------------
# lint 凭证机械门(autoids 路径):合并前每 case 必须在当前 case.xlsx 上过 compile_emit
# 的全部机械门(过门自动落 .grade_credential.json、精确签名 xlsx_mtime)。2026-07-02
# 实证 34-case 零凭证直接合并交付——prompt 层约束在长上下文下会被遗忘,此门确定性强制。
# ---------------------------------------------------------------------------

def _emit_gate_case(autoid: str) -> str:
    """用 compile_emit 落一个最小合法 case 到 outputs/<autoid>/,返回 xlsx 路径。"""
    from main.ist_core.tools.device import compile_emit
    steps = [
        {"E": "APV_0", "F": "cmd_config", "G": "show version", "desc": "观测版本"},
        {"E": "check_point", "F": "found", "G": "Version", "desc": "有版本回显"},
    ]
    out = compile_emit.invoke({
        "autoid": autoid, "steps_json": json.dumps(steps, ensure_ascii=False),
        "out_name": autoid,
    })
    assert "已产出" in out, f"前置 emit 失败: {out}"
    from pathlib import Path
    return str(Path("workspace/outputs") / autoid / "case.xlsx")


def test_merged_autoids_lint_credential_gate():
    """lint 凭证门:emit 过全部机械门即自动落 lint 凭证(source=lint)→ 合并放行。

    实证依据 942 对时点配对:LLM grade verdict 判别力仅 3pp(PASS 56% vs CUT 53%),
    LLM 审 LLM 不构成质量门,质量=机械 lint + 上机 oracle(ist-verify)。
    """
    import shutil
    from pathlib import Path
    aid = "PYTEST_GATE_NOGRADE"
    try:
        _emit_gate_case(aid)
        # emit 落的 lint 凭证放行
        out = compile_emit_merged.invoke({"autoids": json.dumps([aid]),
                                          "out_name": "_pytest_gate_merged"})
        assert "已合并" in out, out
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)
        shutil.rmtree(Path("workspace/outputs") / "_pytest_gate_merged", ignore_errors=True)


def test_merged_autoids_rejects_stale_grade_credential():
    import os
    import shutil
    from pathlib import Path
    aid = "PYTEST_GATE_STALE"
    try:
        xp = Path(_emit_gate_case(aid))
        sj = xp.parent / ".grade_credential.json"
        # 签名指向旧 mtime(重编后没重新 emit);文件 mtime 再新也冒充不了
        sj.write_text(json.dumps({"overall": 0.8, "abstain": False,
                                  "xlsx_mtime": xp.stat().st_mtime - 100}), encoding="utf-8")
        out = compile_emit_merged.invoke({"autoids": json.dumps([aid]),
                                          "out_name": "_pytest_gate_merged"})
        assert "lint 凭证门" in out and "重编后未重新 emit" in out
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)
        shutil.rmtree(Path("workspace/outputs") / "_pytest_gate_merged", ignore_errors=True)


def test_merged_autoids_passes_with_fresh_grade_credential():
    import os
    import shutil
    from pathlib import Path
    aid = "PYTEST_GATE_OK"
    try:
        xp = Path(_emit_gate_case(aid))
        sj = xp.parent / ".grade_credential.json"
        # 有效凭证:签名精确等于当前 xlsx mtime(只有 compile_emit 工具落盘能拿到)
        sj.write_text(json.dumps({"overall": 0.8, "abstain": False,
                                  "xlsx_mtime": xp.stat().st_mtime}), encoding="utf-8")
        out = compile_emit_merged.invoke({"autoids": json.dumps([aid]),
                                          "out_name": "_pytest_gate_merged"})
        assert "lint 凭证门" not in out
        assert "已合并 1 个真 case + 1 哨兵" in out
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)
        shutil.rmtree(Path("workspace/outputs") / "_pytest_gate_merged", ignore_errors=True)


# ---------------------------------------------------------------------------
# steps_json 解析失败的可自诊报错:回显收到参数首尾(供应商拖尾可见)+ 连败升级指引
# ---------------------------------------------------------------------------

def test_emit_parse_error_echoes_param_and_escalates_on_streak():
    from main.ist_core.tools.device import compile_emit
    from main.ist_core.tools.device.emit_xlsx_tool import _emit_fail_streak_clear
    aid = "PYTEST_STREAK_CASE"
    _emit_fail_streak_clear(aid)
    bad = '[{"E":"APV_0","F":"cmd_config","G":"show version"}]trailing-garbage'
    try:
        outs = [compile_emit.invoke({"autoid": aid, "steps_json": bad, "out_name": aid})
                for _ in range(3)]
        # 回显:首段片段可见,含实际长度
        assert "实际收到的参数" in outs[0] and "trailing-garbage" in outs[0]
        # 前两次不带升级指引,第三次起带
        assert "连续" not in outs[0] and "连续 3 次" in outs[2]
        assert "停止重试" in outs[2]
        # 成功一次即清零
        good = '[{"E":"APV_0","F":"cmd_config","G":"show version","desc":"观测"},' \
               '{"E":"check_point","F":"found","G":"Version","desc":"回显"}]'
        ok = compile_emit.invoke({"autoid": aid, "steps_json": good, "out_name": aid})
        assert "已产出" in ok
        out_again = compile_emit.invoke({"autoid": aid, "steps_json": bad, "out_name": aid})
        assert "连续" not in out_again  # streak 已清零,重新从 1 计
    finally:
        import shutil
        from pathlib import Path
        _emit_fail_streak_clear(aid)
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)


# ---------------------------------------------------------------------------
# steps 载荷三通道(P0 结构化):原生数组 / workspace 文件 / 字符串兼容
# ---------------------------------------------------------------------------

_GATE_STEPS = [
    {"E": "APV_0", "F": "cmd_config", "G": "show version", "desc": "观测版本"},
    {"E": "check_point", "F": "found", "G": "Version", "desc": "有版本回显"},
]


def test_emit_native_steps_array():
    from main.ist_core.tools.device import compile_emit
    import shutil
    from pathlib import Path
    aid = "PYTEST_CH_ARRAY"
    try:
        out = compile_emit.invoke({"autoid": aid, "steps": _GATE_STEPS, "out_name": aid})
        assert "已产出" in out
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)


def test_emit_steps_array_stringified_still_accepted():
    from main.ist_core.tools.device import compile_emit
    import shutil
    from pathlib import Path
    aid = "PYTEST_CH_STRARR"
    try:
        out = compile_emit.invoke({"autoid": aid, "steps": json.dumps(_GATE_STEPS),
                                   "out_name": aid})
        assert "已产出" in out
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)


def test_emit_steps_path_channel_and_sandbox():
    from main.ist_core.tools.device import compile_emit
    import shutil
    from pathlib import Path
    aid = "PYTEST_CH_PATH"
    tmp = Path("workspace/tmp"); tmp.mkdir(parents=True, exist_ok=True)
    f = tmp / "steps_pytest_ch.json"
    try:
        f.write_text(json.dumps(_GATE_STEPS), encoding="utf-8")
        out = compile_emit.invoke({"autoid": aid, "steps_path": str(f), "out_name": aid})
        assert "已产出" in out
        # workspace 外路径拒绝
        out2 = compile_emit.invoke({"autoid": aid, "steps_path": "/etc/hosts", "out_name": aid})
        assert "必须在 workspace/ 内" in out2
    finally:
        f.unlink(missing_ok=True)
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)


def test_emit_parse_error_suggests_channel_switch():
    from main.ist_core.tools.device import compile_emit
    from main.ist_core.tools.device.emit_xlsx_tool import _emit_fail_streak_clear
    aid = "PYTEST_CH_SUGGEST"
    _emit_fail_streak_clear(aid)
    bad = json.dumps(_GATE_STEPS) + "push"
    try:
        compile_emit.invoke({"autoid": aid, "steps_json": bad, "out_name": aid})
        out2 = compile_emit.invoke({"autoid": aid, "steps_json": bad, "out_name": aid})
        assert "换通道" in out2 and "steps_path" in out2
    finally:
        _emit_fail_streak_clear(aid)


# ---------------------------------------------------------------------------
# P0 结构化:批量工具入参双收 + autoid 对 xlsx 全集校验
# ---------------------------------------------------------------------------

def test_coerce_json_array_dual_channel():
    from main.ist_core.tools.device.batch_tools import _coerce_json_array
    assert _coerce_json_array(["a", "b"], "x") == (["a", "b"], None)
    assert _coerce_json_array('["a","b"]', "x") == (["a", "b"], None)
    assert _coerce_json_array("", "x") == ([], None)
    arr, err = _coerce_json_array('["a"]push', "x")
    assert arr is None and "原生数组" in err


def test_dev_run_batch_rejects_autoid_not_in_xlsx():
    import shutil
    from pathlib import Path
    from main.ist_core.tools.device import dev_run_batch
    from main.ist_core.tools.device.batch_tools import _xlsx_real_autoids
    aid = "203031750000000001"  # 合法形态的 18 位
    try:
        from main.ist_core.tools.device import compile_emit
        out = compile_emit.invoke({"autoid": aid, "steps": _GATE_STEPS, "out_name": aid})
        assert "已产出" in out
        xp = f"workspace/outputs/{aid}/case.xlsx"
        assert _xlsx_real_autoids(xp) == [aid]
        # 手抄截断 id → 显式拒绝(不静默误匹配)
        res = dev_run_batch.invoke({"xlsx_path": xp, "autoids_json": ["778012"]})
        assert "不在该 xlsx 数据区" in res and "778012" in res
        # 原生数组直收:卷内 id 通过校验(会走到后续 config/设备段,不因参数被拒)
        res2 = dev_run_batch.invoke({"xlsx_path": xp, "autoids_json": '["778012"]'})
        assert "不在该 xlsx 数据区" in res2  # 字符串通道同样校验
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)


# ---------------------------------------------------------------------------
# P1/P2 结构化:submit_attribution 落盘 + last_run merge/round + 瞬态护栏复活
# ---------------------------------------------------------------------------

def test_submit_attribution_evidence_gate_and_writeback(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path
    from main.ist_core.tools.device import submit_attribution, compile_emit
    aid = "203031750000000002"
    try:
        compile_emit.invoke({"autoid": aid, "steps": _GATE_STEPS, "out_name": aid})
        outd = Path("workspace/outputs") / aid
        lr = outd / "last_run.json"
        lr.write_text(json.dumps([{
            "autoid": aid, "verdict": "fail", "_round": 2,
            "causality": "#### Fail Num 1: fail to find: \\b1\\.2\\.3\\.4\\b in:",
            "device_context": "ssh connection timed out while dialing jumphost",
        }], ensure_ascii=False), encoding="utf-8")
        xp = str(outd / "case.xlsx")
        # evidence 非原文子串 → 拒
        r1 = submit_attribution.invoke({
            "xlsx_path": xp, "autoid": aid, "layer": "transient",
            "disposition": "env_blocked", "evidence": "连接超时了(转述)"})
        assert "原文" in r1 and "error" in r1
        # 原文子串 → 落盘
        r2 = submit_attribution.invoke({
            "xlsx_path": xp, "autoid": aid, "layer": "transient",
            "disposition": "env_blocked",
            "evidence": "ssh connection timed out",
            "fix_direction": "等环境恢复后原样复跑"})
        assert "归因已落盘" in r2
        rec = json.loads(lr.read_text(encoding="utf-8"))[0]
        assert rec["_attribution"]["layer"] == "transient"
        assert rec["_attribution"]["round"] == 2
        # defect_candidate 必填字段校验
        r3 = submit_attribution.invoke({
            "xlsx_path": xp, "autoid": aid, "layer": "product_defect",
            "disposition": "defect_candidate",
            "evidence": "ssh connection timed out",
            "defect_candidate": {"repro": "x"}})
        assert "缺必填字段" in r3
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)


def test_digest_merge_keeps_other_rounds_and_revives_transient_guard(monkeypatch):
    """merge 写盘不丢上一轮记录;上轮 _attribution.layer=transient 本轮复现 → 护栏点名。"""
    import shutil
    from pathlib import Path
    from main.ist_core.tools.device import compile_emit, dev_run_batch_digest
    from main.ist_core.tools.device import batch_tools
    aid = "203031750000000003"
    other = "203031750000000099"   # 上一轮跑过、本轮不在结果里的 case
    try:
        compile_emit.invoke({"autoid": aid, "steps": _GATE_STEPS, "out_name": aid})
        outd = Path("workspace/outputs") / aid
        lr = outd / "last_run.json"
        lr.write_text(json.dumps([
            {"autoid": aid, "verdict": "fail", "_round": 1,
             "causality": "#### Fail Num 1: fail to find: PATTERN_X in:",
             "device_context": "dig said NXDOMAIN",
             "_attribution": {"layer": "transient", "disposition": "env_blocked"}},
            {"autoid": other, "verdict": "pass", "_round": 1},
        ], ensure_ascii=False), encoding="utf-8")
        round2 = [{"autoid": aid, "verdict": "fail",
                   "causality": "#### Fail Num 1: fail to find: PATTERN_X in:",
                   "device_context": "dig said NXDOMAIN again"}]
        monkeypatch.setattr(batch_tools.dev_run_batch, "func",
                            lambda *a, **k: json.dumps(round2, ensure_ascii=False))
        out = dev_run_batch_digest.invoke({"xlsx_path": str(outd / "case.xlsx"),
                                           "autoids_json": [aid]})
        assert "上轮归\"瞬态\"本轮复现" in out and aid in out       # 护栏复活(读 _attribution)
        data = {r["autoid"]: r for r in json.loads(lr.read_text(encoding="utf-8"))}
        assert other in data and data[other]["_round"] == 1        # merge 不丢别的记录
        assert data[aid]["_round"] == 2                            # round 自增
        assert data[aid]["_fail_signatures"]                       # 签名落盘
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)


# ---------------------------------------------------------------------------
# P2 结构化:欠定台账落盘 + user_decision 落地门(形态/顺序锚机械核对)
# ---------------------------------------------------------------------------

def test_needs_decision_ledger_written_on_underdetermined():
    import shutil
    from pathlib import Path
    from main.ist_core.tools.device import compile_check_verifiability
    aid = "PYTEST_ND_LEDGER"
    try:
        out = compile_check_verifiability.invoke({
            "autoid": aid, "algo": "rr", "n_requests": 1, "n_pools": 3,
            "claim_kind": "new_member_last"})
        assert "NEEDS_USER_DECISION" in out
        nd = json.loads((Path("workspace/outputs") / aid / "needs_decision.json")
                        .read_text(encoding="utf-8"))
        c = next(x for x in nd["claims"] if x["claim_kind"] == "new_member_last")
        assert c["ordering_sensitive"] is True and c.get("min_requests")
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)


def test_user_decision_gate_blocks_form_and_ordering_downgrade():
    import shutil
    from pathlib import Path
    from main.ist_core.tools.device import compile_emit
    aid = "PYTEST_UD_GATE"
    outd = Path("workspace/outputs") / aid
    try:
        outd.mkdir(parents=True, exist_ok=True)
        (outd / "user_decision.json").write_text(json.dumps({
            "decision": "改过程", "expected_assertion_form": "dist",
            "claim_kinds_preserved": ["new_member_last"]}), encoding="utf-8")
        # 形态违约:用户选 dist,产物只有普通 found → 拒
        r1 = compile_emit.invoke({"autoid": aid, "steps": _GATE_STEPS, "out_name": aid})
        assert "违反用户决策" in r1 and "dist" in r1
        # 形态对但缺顺序锚(new_member_last 只有 present=true 的 member)→ 拒
        steps2 = [
            {"E": "APV_0", "F": "cmd_config", "G": "show version", "desc": "观测"},
            {"E": "check_point", "F": "dist",
             "dist": {"total": 6, "buckets": [
                 {"pattern": "p1", "expect": 2, "tolerance": 1},
                 {"pattern": "p2", "expect": 2, "tolerance": 1},
                 {"pattern": "p3", "expect": 2, "tolerance": 1}]},
             "desc": "分布区间"},
            {"E": "check_point", "F": "member",
             "member": {"ips": ["172.16.35.213"], "present": True}, "desc": "命中新增池"},
        ]
        r2 = compile_emit.invoke({"autoid": aid, "steps": steps2, "out_name": aid})
        assert "顺序锚" in r2
        # 完整:not_found 段接 found 段 → 过 user_decision 门(后续结构门另说)
        steps3 = steps2[:2] + [
            {"E": "check_point", "F": "member",
             "member": {"ips": ["172.16.35.213"], "present": False}, "desc": "覆盖原池一轮未命中新增"},
            {"E": "APV_0", "F": "cmd_config", "G": "show version", "desc": "再观测"},
            {"E": "check_point", "F": "member",
             "member": {"ips": ["172.16.35.213"], "present": True}, "desc": "此后命中新增"},
        ]
        r3 = compile_emit.invoke({"autoid": aid, "steps": steps3, "out_name": aid})
        assert "违反用户决策" not in r3 and "顺序锚" not in r3
    finally:
        shutil.rmtree(outd, ignore_errors=True)


# ---------------------------------------------------------------------------
# P3 结构化:冻结闸门(digest 落 .frozen.json → emit 要求 override_frozen_reason)
# ---------------------------------------------------------------------------

def test_frozen_gate_requires_override_reason():
    import shutil
    from pathlib import Path
    from main.ist_core.tools.device import compile_emit
    aid = "PYTEST_FROZEN"
    outd = Path("workspace/outputs") / aid
    try:
        outd.mkdir(parents=True, exist_ok=True)
        (outd / ".frozen.json").write_text(json.dumps({
            "reason": "连续两轮同签名 fail(同法已证无效)",
            "signatures": ["fail to find: PATTERN_X"]}), encoding="utf-8")
        r1 = compile_emit.invoke({"autoid": aid, "steps": _GATE_STEPS, "out_name": aid})
        assert "已被上机跨轮对照冻结" in r1 and "override_frozen_reason" in r1
        r2 = compile_emit.invoke({"autoid": aid, "steps": _GATE_STEPS, "out_name": aid,
                                  "override_frozen_reason": "断言从写死计数改为分布区间"})
        assert "已产出" in r2
        fz = json.loads((outd / ".frozen.json").read_text(encoding="utf-8"))
        assert fz["overrides"][0]["reason"].startswith("断言从写死")
    finally:
        shutil.rmtree(outd, ignore_errors=True)


def test_digest_repeat_fail_writes_frozen_marker(monkeypatch):
    import shutil
    from pathlib import Path
    from main.ist_core.tools.device import compile_emit, dev_run_batch_digest
    from main.ist_core.tools.device import batch_tools
    aid = "203031750000000004"
    try:
        compile_emit.invoke({"autoid": aid, "steps": _GATE_STEPS, "out_name": aid})
        outd = Path("workspace/outputs") / aid
        (outd / "last_run.json").write_text(json.dumps([
            {"autoid": aid, "verdict": "fail", "_round": 1,
             "causality": "#### Fail Num 1: fail to find: PATTERN_Y in:",
             "device_context": "x"}]), encoding="utf-8")
        round2 = [{"autoid": aid, "verdict": "fail",
                   "causality": "#### Fail Num 1: fail to find: PATTERN_Y in:",
                   "device_context": "x"}]
        monkeypatch.setattr(batch_tools.dev_run_batch, "func",
                            lambda *a, **k: json.dumps(round2, ensure_ascii=False))
        out = dev_run_batch_digest.invoke({"xlsx_path": str(outd / "case.xlsx"),
                                           "autoids_json": [aid]})
        assert "冻结同法重编" in out
        assert (outd / ".frozen.json").is_file()
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)


def test_user_decision_gate_ordering_by_ledger_flag():
    """自创 kind(非 new_member_last)+台账 ordering_sensitive=true → 门同样要求顺序锚。"""
    import shutil
    from pathlib import Path
    from main.ist_core.tools.device import compile_emit
    aid = "PYTEST_UD_LEDGER"
    outd = Path("workspace/outputs") / aid
    try:
        outd.mkdir(parents=True, exist_ok=True)
        (outd / "user_decision.json").write_text(json.dumps({
            "decision": "改过程", "expected_assertion_form": "dist",
            "claim_kinds_preserved": ["rotation_order_after_delete"]}), encoding="utf-8")
        (outd / "needs_decision.json").write_text(json.dumps({
            "autoid": aid, "claims": [
                {"claim_kind": "rotation_order_after_delete", "ordering_sensitive": True}]}),
            encoding="utf-8")
        steps = [
            {"E": "APV_0", "F": "cmd_config", "G": "show version", "desc": "观测"},
            {"E": "check_point", "F": "dist",
             "dist": {"total": 6, "buckets": [
                 {"pattern": "p1", "expect": 3, "tolerance": 1},
                 {"pattern": "p3", "expect": 3, "tolerance": 1}]}, "desc": "分布"},
        ]
        out = compile_emit.invoke({"autoid": aid, "steps": steps, "out_name": aid})
        assert "顺序锚" in out   # 旧版只认 new_member_last 会放行,新版按台账布尔拦
    finally:
        shutil.rmtree(outd, ignore_errors=True)


def test_emit_provenance_trailing_garbage_salvaged():
    """provenance_json 尾部拖尾(JSON 本体合法)→ 前缀抢救继续 emit,不报废。"""
    import shutil
    from pathlib import Path
    from main.ist_core.tools.device import compile_emit
    aid = "PYTEST_PROV_TAIL"
    prov = json.dumps({"autoid": aid, "provisional": True, "steps": [
        {"layer": "G", "source": {"kind": "manual", "ref": "x:1"}},
        {"layer": "V", "source": {"kind": "manual", "ref": "x:2"}}]}) + "push"
    try:
        out = compile_emit.invoke({"autoid": aid, "steps": _GATE_STEPS,
                                   "out_name": aid, "provenance_json": prov})
        assert "已产出" in out and "provenance_json 解析失败" not in out
        assert (Path("workspace/outputs") / aid / "case.provenance.json").is_file()
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)


def test_fanout_produced_field_probes_disk(monkeypatch, tmp_path):
    # 「产没产出」以落盘为准工具化:worker 派发每项带 produced 机读字段
    import main.ist_core.tools.device.batch_tools as bt
    aid_has, aid_none = "203099999999900088", "203099999999900089"
    root = bt._project_root()
    d = root / "workspace" / "outputs" / aid_has
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.xlsx").write_bytes(b"x")
    try:
        monkeypatch.setattr(bt, "_run_skill_fork", lambda *a, **k: ("说产出了但看盘", True), raising=False)
        import json as _json
        out = _json.loads(bt.compile_fanout.func(
            skill="compile-worker",
            briefs_json=[{"key": aid_has, "brief": "b1"}, {"key": aid_none, "brief": "b2"}]))
        by_key = {r["key"]: r for r in out}
        assert by_key[aid_has]["produced"] is True
        assert by_key[aid_none]["produced"] is False
    finally:
        import shutil as _sh
        _sh.rmtree(d, ignore_errors=True)
