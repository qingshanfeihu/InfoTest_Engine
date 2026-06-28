"""V3 approach A：确定性编译流水线 compile_pipeline。"""

from __future__ import annotations

import importlib
import json

# 工具名 compile_pipeline 与其所在模块同名 → device 包属性被工具对象遮蔽
# （`from device import compile_pipeline` 会拿到 StructuredTool 而非模块）；
# 用 importlib 取真模块以访问内部 helper / 做 monkeypatch。
CP = importlib.import_module("main.ist_core.tools.device.compile_pipeline")


def _case():
    return {
        "autoid": "111",
        "title": "sdns host rr算法",
        "group_path": ["A组", "算法测试"],
        "step_intents": [
            {"desc": "配置pool rr算法", "expected": ""},
            {"desc": "客户端发请求", "expected": "命中第一个pool"},
        ],
    }


def test_brief_template_has_five_elements_and_no_commands():
    b = CP._build_case_brief(_case(), product_version="10.5",
                             manual_glob="10.5_cli__part*.md")
    # 五要素都在
    assert "需求：autoid=111" in b
    assert "10.5" in b
    assert "A组 / 算法测试" in b
    assert "observe-then-assert" in b   # 规则
    assert "kb_footprint" in b    # 指路
    assert "只生成 draft" in b           # 边界
    # 零硬编码：不出现具体设备命令
    assert "sdns listener" not in b
    assert "命中第一个pool" in b          # 脑图期望如实带入


def test_version_guard():
    r = CP.compile_pipeline.invoke({"mindmap_path": "x.txt", "product_version": ""})
    assert r.startswith("error") and "product_version" in r
    r2 = CP.compile_pipeline.invoke({"mindmap_path": "", "product_version": "10.5"})
    assert r2.startswith("error") and "mindmap_path" in r2


def test_pipeline_per_case_no_barrier(monkeypatch):
    """per-case 流水线：每 case 独立 draft→grade，无屏障。mock execute_fork_skill + prep + merge。

    验证：draft 落 xlsx、grade 判 PASS、PASS 进 merge、无 escalated。
    """
    calls = []
    root = CP._project_root()
    outdir = root / "workspace" / "outputs" / "t_pipe"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "manifest.json").write_text(json.dumps({
        "cases": [_case(), {**_case(), "autoid": "222", "title": "case2"}],
        "groups": {},
    }, ensure_ascii=False), encoding="utf-8")

    class _Fake:
        def __init__(self, fn): self._fn = fn
        def invoke(self, d): return self._fn(d)

    def fake_prep(d):
        calls.append(("prep", d.get("mindmap_path")))
        return "manifest 已产"

    def fake_merge(d):
        cs = json.loads(d["cases_json"]); calls.append(("merge", len(cs)))
        return f"已产出 {len(cs)} case"

    # execute_fork_skill(skill, brief)：draft brief 含"需求："→落 xlsx 返回路径；
    # grade brief 含"xlsx_path="→返回 PASS。
    def fake_fork(skill, brief, tag="", summary_sink=None):
        if skill == "ist_compile_draft":
            # 从 brief 提 autoid
            aid = brief.split("autoid=")[1].split("，")[0].strip()
            calls.append(("draft", aid))
            cdir = root / "workspace" / "outputs" / aid
            cdir.mkdir(parents=True, exist_ok=True)
            _write_min_xlsx(cdir / "case.xlsx", aid)
            return f"xlsx: workspace/outputs/{aid}/case.xlsx"
        else:
            calls.append(("grade", skill))
            return "VERDICT: PASS 覆盖目标行为"

    prep_mod = importlib.import_module("main.ist_core.tools.device.compile_prep")
    import main.ist_core.tools.device.emit_xlsx_tool as em
    import main.ist_core.skills.loader as loader_mod
    monkeypatch.setattr(prep_mod, "compile_prep", _Fake(fake_prep))
    monkeypatch.setattr(em, "compile_emit_merged", _Fake(fake_merge))
    monkeypatch.setattr(loader_mod, "execute_fork_skill", fake_fork)

    res = CP._run_pipeline("dongkl.txt", "10.5", "t_pipe",
                           draft_skill="ist_compile_draft", grade_skill="ist_compile_grade")
    # 两 case 各 draft 一次 + grade 一次，全 PASS → merge 2
    assert ("prep", "dongkl.txt") in calls
    assert ("draft", "111") in calls and ("draft", "222") in calls
    assert calls.count(("grade", "ist_compile_grade")) == 2
    assert ("merge", 2) in calls
    assert sorted(res["done"]) == ["111", "222"]
    assert not res["escalated"]


def test_pipeline_observability_aggregates_llm_and_tool_calls(monkeypatch):
    """Phase 0：pipeline 聚合每 case draft/grade fork 的 LLM 往返 + 工具调用次数。

    mock 的 execute_fork_skill 经 summary_sink 回传可观测指标（模拟真 fork 的统计），
    验证 result['observability'] 汇总正确——这是「预检索是否真减少 LLM 调用/查找」的度量。
    """
    root = CP._project_root()
    outdir = root / "workspace" / "outputs" / "t_obs"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "manifest.json").write_text(json.dumps({
        "cases": [_case(), {**_case(), "autoid": "222", "title": "case2"}],
        "groups": {},
    }, ensure_ascii=False), encoding="utf-8")

    class _Fake:
        def __init__(self, fn): self._fn = fn
        def invoke(self, d): return self._fn(d)

    def fake_fork(skill, brief, tag="", summary_sink=None):
        if skill == "ist_compile_draft":
            aid = brief.split("autoid=")[1].split("，")[0].strip()
            cdir = root / "workspace" / "outputs" / aid
            cdir.mkdir(parents=True, exist_ok=True)
            _write_min_xlsx(cdir / "case.xlsx", aid)
            if summary_sink is not None:   # draft fork：5 轮 LLM + probe/footprint 各几次
                summary_sink.update({"ai_rounds": 5,
                                     "tool_calls": {"dev_probe": 2, "kb_footprint": 3}})
            return f"xlsx: {aid}"
        if summary_sink is not None:       # grade fork：2 轮 LLM + 1 次 compile_score
            summary_sink.update({"ai_rounds": 2, "tool_calls": {"compile_score": 1}})
        return "判定：PASS"

    prep_mod = importlib.import_module("main.ist_core.tools.device.compile_prep")
    import main.ist_core.tools.device.emit_xlsx_tool as em
    import main.ist_core.skills.loader as loader_mod
    monkeypatch.setattr(prep_mod, "compile_prep", _Fake(lambda d: "ok"))
    monkeypatch.setattr(em, "compile_emit_merged", _Fake(lambda d: "merged"))
    monkeypatch.setattr(loader_mod, "execute_fork_skill", fake_fork)

    res = CP._run_pipeline("x.txt", "10.5", "t_obs",
                           draft_skill="ist_compile_draft", grade_skill="ist_compile_grade")
    obs = res["observability"]["total"]
    # 2 case，各 draft(ai=5)+grade(ai=2) → draft_llm=10 grade_llm=4 合计=14
    assert obs["draft_llm_rounds"] == 10
    assert obs["grade_llm_rounds"] == 4
    assert obs["total_llm_rounds"] == 14
    # 工具：dev_probe 2×2=4, kb_footprint 3×2=6, compile_score 1×2=2
    assert obs["tool_calls"]["dev_probe"] == 4
    assert obs["tool_calls"]["kb_footprint"] == 6
    assert obs["tool_calls"]["compile_score"] == 2
    assert set(res["observability"]["per_case"].keys()) == {"111", "222"}
    # 渲染行：要削减的成本键(dev_probe/kb_footprint)排在普通工具前 + 进 phases
    line = CP._format_observability(obs)
    assert "dev_probe=4" in line and "kb_footprint=6" in line
    assert line.index("dev_probe") < line.index("compile_score")
    assert any("观测(LLM/查找成本" in p for p in res["phases"])


def test_pipeline_escalates_after_max_rounds(monkeypatch):
    """grade 持续 CUT → ≤N 轮后 escalate，不进 merge。"""
    root = CP._project_root()
    outdir = root / "workspace" / "outputs" / "t_esc"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "manifest.json").write_text(json.dumps({"cases": [_case()], "groups": {}},
                                                     ensure_ascii=False), encoding="utf-8")
    n_draft = {"n": 0}

    class _Fake:
        def __init__(self, fn): self._fn = fn
        def invoke(self, d): return self._fn(d)

    def fake_fork(skill, brief, tag="", summary_sink=None):
        if skill == "ist_compile_draft":
            n_draft["n"] += 1
            aid = brief.split("autoid=")[1].split("，")[0].strip()
            cdir = root / "workspace" / "outputs" / aid
            cdir.mkdir(parents=True, exist_ok=True)
            _write_min_xlsx(cdir / "case.xlsx", aid)
            return f"xlsx: {aid}"
        return "VERDICT: CUT 断言太弱，未覆盖动态行为"

    prep_mod = importlib.import_module("main.ist_core.tools.device.compile_prep")
    import main.ist_core.tools.device.emit_xlsx_tool as em
    import main.ist_core.skills.loader as loader_mod
    monkeypatch.setattr(prep_mod, "compile_prep", _Fake(lambda d: "ok"))
    monkeypatch.setattr(em, "compile_emit_merged", _Fake(lambda d: "merged"))
    monkeypatch.setattr(loader_mod, "execute_fork_skill", fake_fork)

    res = CP._run_pipeline("x.txt", "10.5", "t_esc",
                           draft_skill="ist_compile_draft", grade_skill="ist_compile_grade")
    assert res["done"] == []
    assert "111" in res["escalated"]
    assert n_draft["n"] == CP._MAX_REWORK_ROUNDS  # 重做到上限


def _setup_single_case(monkeypatch, out_name, fake_fork):
    """公共脚手架：单 case manifest + mock prep/merge/fork，返回 _run_pipeline 结果。"""
    root = CP._project_root()
    outdir = root / "workspace" / "outputs" / out_name
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "manifest.json").write_text(json.dumps({"cases": [_case()], "groups": {}},
                                                     ensure_ascii=False), encoding="utf-8")

    class _Fake:
        def __init__(self, fn): self._fn = fn
        def invoke(self, d): return self._fn(d)

    prep_mod = importlib.import_module("main.ist_core.tools.device.compile_prep")
    import main.ist_core.tools.device.emit_xlsx_tool as em
    import main.ist_core.skills.loader as loader_mod
    monkeypatch.setattr(prep_mod, "compile_prep", _Fake(lambda d: "ok"))
    monkeypatch.setattr(em, "compile_emit_merged", _Fake(lambda d: "merged"))
    monkeypatch.setattr(loader_mod, "execute_fork_skill", fake_fork)
    return CP._run_pipeline("x.txt", "10.5", out_name,
                            draft_skill="ist_compile_draft", grade_skill="ist_compile_grade")


def test_draft_recursion_escalates_immediately_no_rework(monkeypatch):
    """Fix E：draft 返回 [recursion-limit] → 恰好 1 次 draft 尝试即 escalate，不做 3 轮等价重做。"""
    n_draft = {"n": 0}

    def fake_fork(skill, brief, tag="", summary_sink=None):
        if skill == "ist_compile_draft":
            n_draft["n"] += 1
            return ("ERROR: fork skill 'ist_compile_draft' execution failed: "
                    "[recursion-limit] Recursion limit of 200 reached")
        return "判定：PASS"

    res = _setup_single_case(monkeypatch, "t_recursion", fake_fork)
    assert res["done"] == []
    assert "111" in res["escalated"]
    assert n_draft["n"] == 1                      # 不再 _MAX_REWORK_ROUNDS 轮等价重做
    reason = res["escalated"]["111"]
    assert reason["rounds"][0]["verdict"] == "DRAFT_RECURSION"
    assert "递归" in reason["summary"]


def test_fork_wallclock_timeout_escalates_and_not_transient(monkeypatch):
    """Fix A：单 fork 超 _FORK_WALLCLOCK_S → 返回 [fork-wallclock]、escalate；该标记非 transient。"""
    import time as _t
    monkeypatch.setattr(CP, "_FORK_WALLCLOCK_S", 0.2)
    n_draft = {"n": 0}

    def fake_fork(skill, brief, tag="", summary_sink=None):
        if skill == "ist_compile_draft":
            n_draft["n"] += 1
            _t.sleep(1.0)                          # 超 0.2s 墙钟 → 看门狗放弃等待
            return "xlsx: never"
        return "判定：PASS"

    res = _setup_single_case(monkeypatch, "t_wallclock", fake_fork)
    assert res["done"] == []
    assert "111" in res["escalated"]
    assert n_draft["n"] == 1                      # wallclock 也立即 escalate，不重做
    # [fork-wallclock] 标记不应被判 transient（否则会被 4× 重试放大）
    from main.ist_core.resilience import is_transient_error
    assert not is_transient_error(f"ERROR: [fork-wallclock] 超 {int(CP._FORK_WALLCLOCK_S)}s")


def test_fork_run_token_propagates_into_watchdog_thread(monkeypatch):
    """Fix A 回归红线：copy_context 把 _current_run_token 带进看门狗线程，dev_probe single-flight 不破。"""
    from main.ist_core.tools.device import run_case
    seen = {}

    def fake_fork(skill, brief, tag="", summary_sink=None):
        seen[skill] = run_case._current_run_token.get()   # 看门狗线程内读 contextvar
        if skill == "ist_compile_draft":
            aid = brief.split("autoid=")[1].split("，")[0].strip()
            cdir = CP._project_root() / "workspace" / "outputs" / aid
            cdir.mkdir(parents=True, exist_ok=True)
            _write_min_xlsx(cdir / "case.xlsx", aid)
            return f"xlsx: {aid}"
        return "判定：PASS"

    res = _setup_single_case(monkeypatch, "t_token", fake_fork)
    assert res["done"] == ["111"]
    assert seen.get("ist_compile_draft", "").startswith("run-")   # 非 None、是本 run token


def test_transient_retry_capped_by_total_wallclock(monkeypatch):
    """Fix B：transient ERROR 在总墙钟超时即停退，不跑满 _TRANSIENT_RETRIES+1 次。"""
    monkeypatch.setattr(CP, "_FORK_TRANSIENT_WALLCLOCK_S", 0.0)   # 总墙钟立即到点
    monkeypatch.setattr(CP, "_TRANSIENT_BASE_SLEEP", 0.0)
    n_draft = {"n": 0}

    def fake_fork(skill, brief, tag="", summary_sink=None):
        if skill == "ist_compile_draft":
            n_draft["n"] += 1
            return "ERROR: fork skill 'ist_compile_draft' execution failed: Request timed out"
        return "判定：PASS"

    res = _setup_single_case(monkeypatch, "t_transcap", fake_fork)
    # 每轮 _fork_call 因总墙钟=0 只做 1 次尝试（不再 transient 重试 4 次）；DRAFT_FAIL 走满 N 轮重做。
    # 有 Fix B：N 轮 × 1 = N 次；无 Fix B：N 轮 × (4 重试+1) = N×5 次。断言落在前者。
    assert n_draft["n"] == CP._MAX_REWORK_ROUNDS
    assert n_draft["n"] < CP._MAX_REWORK_ROUNDS * (CP._TRANSIENT_RETRIES + 1)
    assert "111" in res["escalated"]


def _write_min_xlsx(path, autoid):
    """写一个最小的、_load_case_rows 能读的 case.xlsx（数据区从 29 行起，含 check_point）。"""
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    ws.cell(29, 1, autoid)
    # case 意图是 "rr算法"，配置区须真配 rr method（满足 B 层变体保真门，否则判"算法缺配"回流）
    ws.cell(29, 5, "APV_0"); ws.cell(29, 6, "cmds_config")
    ws.cell(29, 7, "sdns on\nsdns host method www.x.com rr")
    ws.cell(30, 5, "APV_0"); ws.cell(30, 6, "cmd_config"); ws.cell(30, 7, "show sdns listener")
    ws.cell(31, 5, "check_point"); ws.cell(31, 6, "found"); ws.cell(31, 7, "172.16.34.1")
    wb.save(path)


# --- grade 裁定解析：取最后裁定词，治"讨论工具CUT后自己判PASS"被误读 ---
def test_verdict_clean_pass():
    assert CP._parse_grade_verdict("## 审批结论：PASS 覆盖目标行为") is True


def test_verdict_clean_cut():
    assert CP._parse_grade_verdict("## 审批结论：CUT 断言太弱") is False


def test_verdict_discuss_cut_then_conclude_pass():
    """grade 先复核 confidence_score 的 CUT，再下 PASS 结论 → 应判 PASS（取末位）。"""
    out = ("compile_score 给 overall=0.2 / CUT，但我批判性看待——"
           "它孤立评估断言，忽略了序列语义。\n\n## 最终裁定：PASS")
    assert CP._parse_grade_verdict(out) is True


def test_verdict_discuss_pass_then_conclude_cut():
    """反向：先说某条像 PASS，最终结论 CUT → 应判 CUT。"""
    out = ("断言1看似 PASS，但整体未覆盖动态行为。\n\n## 最终裁定：CUT 需补命中断言")
    assert CP._parse_grade_verdict(out) is False


def test_verdict_error_is_not_pass():
    assert CP._parse_grade_verdict("ERROR: fork 超时") is False


def test_verdict_neither_word_is_not_pass():
    assert CP._parse_grade_verdict("（grade 没给明确裁定）") is False


def test_verdict_cut_then_trailing_pass_mention_is_cut():
    """fix B：CUT 结论后跟"…改成 X 才能 PASS"的重做意见——结构化标记须判 CUT，
    不被朴素 rfind 把末尾的 PASS 误读成通过、放弱断言进 merge。"""
    out = ("断言只 found 了一个域名，没覆盖计数行为。\n\n"
           "## 判定：CUT\n建议改成 found_times 计数断言，才能达到 PASS 标准。")
    assert CP._parse_grade_verdict(out) is False


def test_verdict_marker_pass_takes_precedence():
    """有结构化标记时以标记为准（即便后文又提了 CUT 词）。"""
    out = "## 判定：PASS\n（注意别再写成 CUT 式弱断言）"
    assert CP._parse_grade_verdict(out) is True


def test_load_case_rows_preserves_i_column_for_found_times(tmp_path):
    """fix A：_load_case_rows 必须读回第 9 列(I)，否则 merge 丢 found_times 次数 / input_var。"""
    import openpyxl
    from main.ist_core.tools.device.precedent_tools import _load_case_rows
    wb = openpyxl.Workbook(); ws = wb.active
    ws.cell(29, 1, "AID1")
    ws.cell(29, 5, "APV_0"); ws.cell(29, 6, "cmd_config"); ws.cell(29, 7, "show sdns listener")
    ws.cell(30, 5, "check_point"); ws.cell(30, 6, "found_times")
    ws.cell(30, 7, "sdns listener"); ws.cell(30, 9, "16")   # I 列=次数
    p = tmp_path / "case.xlsx"; wb.save(p)
    rows = _load_case_rows(str(p))
    ft = [r for r in rows if r.get("F") == "found_times"]
    assert ft and ft[0].get("I") == "16", f"I 列(found_times 次数)丢失: {rows}"


def test_merge_roundtrip_keeps_found_times_count(tmp_path, monkeypatch):
    """fix A 端到端：emit(found_times,I=16) → _load_case_rows → compile_emit_merged，
    合并产物的 found_times 仍带次数 16（而非被丢成 None → 上机恒 fail）。"""
    import json as _json
    import openpyxl
    from main.ist_core.tools.device.emit_xlsx_tool import compile_emit, compile_emit_merged
    from main.ist_core.tools.device.precedent_tools import _load_case_rows
    # 关掉可达性等门的干扰：直接用合法占位命令 + 不触发拓扑门
    steps = [
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener", "desc": "查看"},
        {"E": "check_point", "F": "found_times", "G": "sdns listener", "I": "16", "desc": "断言16条"},
    ]
    out = compile_emit.invoke({"autoid": "AIDX", "steps_json": _json.dumps(steps, ensure_ascii=False),
                               "init_commands": "sdns on", "out_name": "_pytest_idrop"})
    assert "已产出" in out, out
    root = CP._project_root()
    xlsx = root / "workspace" / "outputs" / "_pytest_idrop" / "case.xlsx"
    rows = _load_case_rows(str(xlsx))
    merged = compile_emit_merged.invoke(
        {"cases_json": _json.dumps([{"autoid": "AIDX", "title": "t", "steps": rows}], ensure_ascii=False),
         "out_name": "_pytest_idrop_merged"})
    assert "已合并" in merged, merged
    mx = root / "workspace" / "outputs" / "_pytest_idrop_merged" / "case.xlsx"
    wm = openpyxl.load_workbook(str(mx), data_only=True).active
    found = False
    for r in range(29, wm.max_row + 1):
        if str(wm.cell(r, 6).value or "") == "found_times":
            assert str(wm.cell(r, 9).value or "") == "16", "合并后 found_times 次数丢失（fix A 回归）"
            found = True
    assert found, "合并产物里没找到 found_times 步"
    # 清理
    import shutil
    shutil.rmtree(root / "workspace" / "outputs" / "_pytest_idrop", ignore_errors=True)
    shutil.rmtree(root / "workspace" / "outputs" / "_pytest_idrop_merged", ignore_errors=True)
