"""V3 approach A：确定性编译流水线 qa_compile_pipeline。"""

from __future__ import annotations

import json

from main.ist_core.tools.device import compile_pipeline as CP


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
                             manual_glob="10.5_cli__part*.md", groups={})
    # 五要素都在
    assert "需求：autoid=111" in b
    assert "10.5" in b
    assert "A组 / 算法测试" in b
    assert "observe-then-assert" in b   # 规则
    assert "qa_footprint_lookup" in b    # 指路
    assert "只生成 draft" in b           # 边界
    # 零硬编码：不出现具体设备命令
    assert "sdns listener" not in b
    assert "命中第一个pool" in b          # 脑图期望如实带入


def test_version_guard():
    r = CP.qa_compile_pipeline.invoke({"mindmap_path": "x.txt", "product_version": ""})
    assert r.startswith("error") and "product_version" in r
    r2 = CP.qa_compile_pipeline.invoke({"mindmap_path": "", "product_version": "10.5"})
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
    def fake_fork(skill, brief):
        if skill == "ist_draft_v3":
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

    import main.ist_core.tools.device.compile_prep as prep_mod
    import main.ist_core.tools.device.emit_xlsx_tool as em
    import main.ist_core.skills.loader as loader_mod
    monkeypatch.setattr(prep_mod, "qa_compile_prep", _Fake(fake_prep))
    monkeypatch.setattr(em, "qa_emit_xlsx_merged", _Fake(fake_merge))
    monkeypatch.setattr(loader_mod, "execute_fork_skill", fake_fork)

    res = CP._run_pipeline("dongkl.txt", "10.5", "t_pipe",
                           draft_skill="ist_draft_v3", grade_skill="ist_grade_v3")
    # 两 case 各 draft 一次 + grade 一次，全 PASS → merge 2
    assert ("prep", "dongkl.txt") in calls
    assert ("draft", "111") in calls and ("draft", "222") in calls
    assert calls.count(("grade", "ist_grade_v3")) == 2
    assert ("merge", 2) in calls
    assert sorted(res["done"]) == ["111", "222"]
    assert not res["escalated"]


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

    def fake_fork(skill, brief):
        if skill == "ist_draft_v3":
            n_draft["n"] += 1
            aid = brief.split("autoid=")[1].split("，")[0].strip()
            cdir = root / "workspace" / "outputs" / aid
            cdir.mkdir(parents=True, exist_ok=True)
            _write_min_xlsx(cdir / "case.xlsx", aid)
            return f"xlsx: {aid}"
        return "VERDICT: CUT 断言太弱，未覆盖动态行为"

    import main.ist_core.tools.device.compile_prep as prep_mod
    import main.ist_core.tools.device.emit_xlsx_tool as em
    import main.ist_core.skills.loader as loader_mod
    monkeypatch.setattr(prep_mod, "qa_compile_prep", _Fake(lambda d: "ok"))
    monkeypatch.setattr(em, "qa_emit_xlsx_merged", _Fake(lambda d: "merged"))
    monkeypatch.setattr(loader_mod, "execute_fork_skill", fake_fork)

    res = CP._run_pipeline("x.txt", "10.5", "t_esc",
                           draft_skill="ist_draft_v3", grade_skill="ist_grade_v3")
    assert res["done"] == []
    assert "111" in res["escalated"]
    assert n_draft["n"] == CP._MAX_REWORK_ROUNDS  # 重做到上限


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
    out = ("qa_confidence_score 给 overall=0.2 / CUT，但我批判性看待——"
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
