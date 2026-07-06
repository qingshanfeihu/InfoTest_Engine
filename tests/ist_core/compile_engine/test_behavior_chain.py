"""行为知识链回归(V6 支柱2b):候选登记门→PASS 晋升→预检索命中。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.tools.knowledge.behavior_tool import submit_behavior_fact

_ROOT = Path(__file__).resolve().parents[3]
_A = "203099999999900701"


@pytest.fixture()
def case_dir(tmp_path, monkeypatch):
    # submit_behavior_fact 读真实 workspace——建真实临时 case 目录
    import shutil
    d = _ROOT / "workspace" / "outputs" / _A
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    import openpyxl
    from main.case_compiler.config import get_config
    # 直接借 emit 造合法卷太重;写最小卷面(表头锚+一行 APV 命令)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["x"] * 9)
    ws.append(["自动化ID"] + [""] * 8)
    ws.append([_A, "P1", "1", "d", "APV_0", "cmd_config", "show statistics sdns pool p1", "", ""])
    wb.save(d / "case.xlsx")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_candidate_requires_cmd_on_sheet(case_dir):
    out = submit_behavior_fact.func(_A, "show sdns magic", "多行回显")
    assert "error" in out and "不在该 case 卷面" in out
    out2 = submit_behavior_fact.func(_A, "show statistics sdns pool p1",
                                     "该命令回显为多行结构,断言需跨行匹配")
    assert "已登记" in out2
    cands = json.loads((case_dir / "behavior_candidates.json").read_text(encoding="utf-8"))
    assert len(cands) == 1


def test_promotion_only_on_pass(case_dir, tmp_path, monkeypatch):
    # 候选在;PASS 台账在临时根;footprint 在临时目录——晋升链全隔离
    submit_behavior_fact.func(_A, "show statistics sdns pool p1", "多行回显,断言需跨行")
    import main.ist_core.compile_engine.nodes._shared as SH
    import main.ist_core.compile_engine.nodes.closing as CL
    from main.ist_core.memory.footprint import merger as M

    led_root = tmp_path
    (led_root / "runtime" / "logs").mkdir(parents=True)
    (led_root / "runtime" / "logs" / "verified_runs.jsonl").write_text(
        json.dumps({"autoid": _A, "verdict": "pass", "run_ts": 5.0,
                    "apv_cmds": ["show statistics sdns pool p1"]}) + "\n", encoding="utf-8")
    monkeypatch.setattr(SH, "project_root", lambda: led_root)
    monkeypatch.setattr(SH, "outputs_root", lambda: _ROOT / "workspace" / "outputs")
    monkeypatch.setattr(SH, "emit", lambda t: None)
    monkeypatch.setattr(M, "_project_root", lambda: led_root)
    fp_dir = tmp_path / "footprints"
    import main.knowledge_paths as KP
    monkeypatch.setattr(CL, "_promote_behavior_candidates",
                        CL._promote_behavior_candidates)   # 保持原函数
    monkeypatch.setattr(KP, "KNOWLEDGE_FOOTPRINTS", fp_dir)

    class _Led:
        data = {"audit": {"notes": []}}
    CL._promote_behavior_candidates(_A, _Led())
    nodes = list(fp_dir.rglob("*.json"))
    assert nodes, "PASS 候选应晋升入库"
    body = json.dumps(json.loads(nodes[0].read_text(encoding="utf-8")), ensure_ascii=False)
    assert "多行" in body and "device_run" not in body.replace("device_verified", "")

    # fail 台账 → 不晋升(重建干净 footprint)
    import shutil
    shutil.rmtree(fp_dir, ignore_errors=True)
    (led_root / "runtime" / "logs" / "verified_runs.jsonl").write_text(
        json.dumps({"autoid": _A, "verdict": "fail", "run_ts": 6.0,
                    "apv_cmds": ["show statistics sdns pool p1"]}) + "\n", encoding="utf-8")
    CL._promote_behavior_candidates(_A, _Led())
    assert not list(fp_dir.rglob("*.json")), "fail 卷候选绝不晋升"


def test_prefetch_brings_back_seeded_behavior():
    # P2-G3:曾撞坑 case 的意图 → 预检索块含种入的行为知识(重撞防止的机器断言)
    # worker 真正消费的是 lookup 渲染(leaf 含 Behaviors 节;行为知识挂叶不挂父)
    from main.ist_core.tools.knowledge.footprint_lookup import kb_footprint
    body = kb_footprint.func("statistics sdns pool")
    assert "多行" in body or "跨行" in body, f"lookup 渲染应含行为知识: {body[:300]}"
