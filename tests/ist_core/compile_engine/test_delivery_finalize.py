"""交付收尾:非 pass 归档卷 + unsuccessful_cases.md 全量报告 + 清 temp(2026-07-07 用户驱动)。

红线:① 非 pass(缺陷/改描述/升级/上机对不上/设备报错)如实归档,不丢;② md 字段齐全且自足;
③ 清 temp 删中间物、留交付物,IST_ENGINE_KEEP_TEMP 可关;④ 归档走 gate-free(cases_json)通道。
"""
import json

import pytest

from main.ist_core.compile_engine import ledger as L
from main.ist_core.compile_engine.ledger import EngineLedger
from main.ist_core.compile_engine.nodes import _shared as sh
from main.ist_core.compile_engine.nodes import closing

OUT = "cname_test"


@pytest.fixture
def env(tmp_path, monkeypatch):
    outputs = tmp_path / "workspace" / "outputs"
    outputs.mkdir(parents=True)
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    monkeypatch.delenv("IST_ENGINE_KEEP_TEMP", raising=False)
    return tmp_path, outputs


def _led():
    led = EngineLedger("/nonexistent/ledger.json")
    led.data["cases"] = {
        "204651759025035644": {"state": L.S_PASSED, "rounds_used": 1, "verdict_history": ["pass"]},
        "204651759025035453": {"state": L.S_FAILED_TERMINAL, "rounds_used": 1,
                               "verdict_history": ["fail"],
                               "attribution": {"layer": "product_defect", "disposition": "defect_candidate",
                                               "fix_direction": "命令语法与手册一致但设备拒",
                                               "defect_candidate": {"repro": "sdns pool cname …",
                                                                    "ticket_id": "BUG-149877"}}},
        "204651759025035570": {"state": L.S_ESCALATED, "rounds_used": 3,
                               "verdict_history": ["fail", "fail", "fail"],
                               "escalation_reason": "max_rounds_exhausted", "attribution": {}},
        "204651759025035999": {"state": L.S_AWAITING_USER, "rounds_used": 1,
                               "verdict_history": ["fail"], "attribution": {}},
    }
    return led


def _seed(outputs, led):
    base = outputs / OUT
    base.mkdir(parents=True)
    (base / "manifest.json").write_text(json.dumps({"source": "dongkl.txt", "cases": [
        {"autoid": "204651759025035453", "title": "域名关联多个cname服务池",
         "step_intents": [{"desc": "配置cname本地域名", "expected": "返回别名"},
                          {"desc": "down掉服务池", "expected": "不返回"}]}]}, ensure_ascii=False),
        encoding="utf-8")
    (base / "last_run.json").write_text("[]", encoding="utf-8")
    (base / "case.xlsx").write_bytes(b"MAIN")            # 交付物,保留
    (base / "engine_ledger.json").write_text("{}", encoding="utf-8")  # 审计,保留
    for aid in led.data["cases"]:
        d = outputs / aid
        d.mkdir(parents=True)
        (d / "case.xlsx").write_bytes(b"CASE")
        (d / "case.provenance.json").write_text(json.dumps({"steps": [
            {"E": "APV_0", "F": "cmd_config", "G": "sdns pool cname cname1 cname1.a.com",
             "layer": "G", "source": {"kind": "footprint", "ref": "sdns.pool"}}]}, ensure_ascii=False),
            encoding="utf-8")
    (outputs / "204651759025035999" / "user_decision.json").write_text(
        json.dumps({"decision": "改描述", "note": "歧义待厘清"}, ensure_ascii=False), encoding="utf-8")
    sub = outputs / f"{OUT}_fails_r1"
    sub.mkdir()
    (sub / "last_run.json").write_text("[]", encoding="utf-8")


def _rep(led):
    return {"cases": {aid: {"verdicts": cc["verdict_history"],
                            "fail_evidence": [{"round": 1, "verdict": "fail",
                                               "device_context": "APV(config)#sdns pool cname …\n^ 语法拒绝"}],
                            "attribution": cc.get("attribution", {})}
                      for aid, cc in led.data["cases"].items()}}


def test_fail_category():
    assert closing._fail_category({"disposition": "defect_candidate"}, L.S_FAILED_TERMINAL) == "产品缺陷"
    assert closing._fail_category({"layer": "G"}, L.S_FAILED_TERMINAL) == "设备执行报错/语法拒绝"
    assert closing._fail_category({"layer": "V"}, L.S_FAILED_TERMINAL) == "上机输出与编写不符"
    assert closing._fail_category({}, L.S_ESCALATED) == "编写卡死/引擎穷尽(升级人工)"
    assert closing._fail_category({}, L.S_AWAITING_USER) == "改描述/待人工厘清"


def test_nonpass_excludes_pass():
    aids = closing._nonpass_autoids(_led())
    assert "204651759025035644" not in aids
    assert set(aids) == {"204651759025035453", "204651759025035570", "204651759025035999"}


def test_md_has_all_required_fields(env):
    _, outputs = env
    led = _led()
    _seed(outputs, led)
    closing._write_unsuccessful_md(led, {}, _rep(led), OUT)
    md = (outputs / OUT / "unsuccessful_cases.md").read_text(encoding="utf-8")
    assert "204651759025035644" not in md                      # passed 不进
    assert "产品缺陷" in md and "BUG-149877" in md              # 分类 + bug
    assert "域名关联多个cname服务池" in md and "down掉服务池" in md and "不返回" in md  # 脑图原始
    assert "sdns pool cname cname1 cname1.a.com" in md         # 自动化
    assert "改描述" in md and "歧义待厘清" in md                # ask_user 改动
    assert "Round 1" in md and "语法拒绝" in md                 # 逐轮 CUT + 设备原文
    assert "命令语法与手册一致但设备拒" in md                    # main 判断


def test_cleanup_deletes_temp_keeps_deliverables(env):
    _, outputs = env
    led = _led()
    _seed(outputs, led)
    (outputs / OUT / "unsuccessful_cases.md").write_text("md", encoding="utf-8")
    (outputs / OUT / "engine_report.json").write_text("{}", encoding="utf-8")
    n = closing._cleanup_temp(led, OUT)
    assert n >= 6
    assert not (outputs / "204651759025035453").exists()       # per-autoid dir
    assert not (outputs / f"{OUT}_fails_r1").exists()          # 子集卷
    assert not (outputs / OUT / "manifest.json").exists()      # 中间 JSON
    assert not (outputs / OUT / "last_run.json").exists()
    for keep in ("case.xlsx", "engine_report.json", "unsuccessful_cases.md", "engine_ledger.json"):
        assert (outputs / OUT / keep).exists(), keep           # 交付物/审计保留


def test_cleanup_keep_temp_env(env, monkeypatch):
    _, outputs = env
    led = _led()
    _seed(outputs, led)
    monkeypatch.setenv("IST_ENGINE_KEEP_TEMP", "1")
    assert closing._cleanup_temp(led, OUT) == 0
    assert (outputs / "204651759025035453").exists()


def test_archive_gate_free_all_nonpass(env, monkeypatch):
    _, outputs = env
    led = _led()
    _seed(outputs, led)
    import main.ist_core.tools.device.precedent_tools as pt
    import main.ist_core.tools.device.emit_xlsx_tool as ex
    monkeypatch.setattr(pt, "_load_case_rows",
                        lambda p: [{"E": "APV_0", "F": "cmd_config", "G": "x"}])
    seen = {}

    def _fake_merged(cases_json="", out_name="", **kw):
        seen["cases_json"] = cases_json
        seen["out_name"] = out_name
        (outputs / out_name).mkdir(parents=True, exist_ok=True)
        (outputs / out_name / "case.xlsx").write_bytes(b"ARCH")
        return "ok"

    monkeypatch.setattr(ex.compile_emit_merged, "func", _fake_merged)
    ref = closing._archive_unsuccessful(led, OUT)
    assert ref and ref.endswith(f"{OUT}_unsuccessful/case.xlsx")
    assert seen["out_name"] == f"{OUT}_unsuccessful"
    aids = {c["autoid"] for c in json.loads(seen["cases_json"])}   # gate-free 通道
    assert aids == {"204651759025035453", "204651759025035570", "204651759025035999"}
