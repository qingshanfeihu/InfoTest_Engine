# -*- coding: utf-8 -*-
"""S6 命令存在性呈报门(V8.5 片1)回归。

覆盖:清单加载与匹配规则(单 token 头的枚举/参数判定——668059 回放的机械核心)、
emit 门呈报形态(needs_decision 台账+拒落卷)、两条逃生通道(行级证据/用户裁决)、
问询组题(command_existence 题面)、env 逃生口。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.case_compiler.command_inventory import (available_versions, load_inventory,
                                                  match_command, nearest_heads)

ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------- 清单与匹配
def test_inventory_loads_and_is_sane():
    inv = load_inventory("10.5")
    assert inv is not None
    assert "10.5" in available_versions()
    stats = inv["stats"]
    assert stats["unique_heads"] > 2000, "清单头数量异常(解析器回归?)"
    assert stats["coverage_excl_noise"] >= 0.99, "覆盖率自检失败(签名格式漂移?)"


@pytest.mark.parametrize("cmd", [
    "sdns on",                                   # 单 token 头+枚举({on|off})
    "sdns listener 172.16.34.70",                # 多词头+参数
    "sdns host name www.a.com",                  # 多词头
    "slb virtual http v1 172.16.34.70 80",       # 多词头+多参数
    "ip address vlan100 172.16.34.70 24",        # L3 写
    "write file",                                # 持久化族
    "write net tftp 172.16.35.231 a.cfg",        # 子动词形态
    "no sdns listener 172.16.34.70",             # no 变体(手册分立记载)
    "show sdns listener",                        # show 变体
    "clear sdns all",                            # clear 域
    "ping 172.16.34.70",                         # 单 token 头+参数位
])
def test_known_good_commands_hit(cmd):
    r = match_command(cmd, version="10.5")
    assert r["decided"] and r["hit"], f"真机 PASS 卷同型命令被误报: {cmd!r} → {r}"


@pytest.mark.parametrize("cmd", [
    "sdns fulldns on",        # 668059 病灶:不得经裸 `sdns` 头假通过
    "sdns fulldns",
    "no sdns fulldns on",     # no 剥离重试后仍不得命中
])
def test_fulldns_misses(cmd):
    r = match_command(cmd, version="10.5")
    assert r["decided"] and not r["hit"], f"668059 回放失败——fulldns 假通过: {cmd!r} → {r}"


def test_non_command_lines_undecided():
    for junk in ("", "   ", "# comment", "…"):
        assert not match_command(junk, version="10.5")["decided"]


def test_nearest_heads_helpful():
    near = nearest_heads("sdns fulldns on", version="10.5")
    assert near and all(h.startswith("sdns") for h in near)


# ---------------------------------------------------------------- emit 门形态
def _emit(autoid: str, steps: list, **kw):
    from main.ist_core.tools.device.emit_xlsx_tool import compile_emit
    return compile_emit.func(autoid=autoid, steps=steps,
                             init_commands="sdns on", out_name=autoid, **kw)


def _steps_with(cmd: str) -> list:
    # 断言 pattern 不得是观测命令文本的子串(恒真必崩门在岗,会先于本门拦截)
    return [
        {"E": "APV_0", "F": "cmd_config", "G": cmd, "desc": "被测配置"},
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener", "desc": "观测"},
        {"E": "check_point", "F": "found", "G": r"172\.16\.34\.70", "desc": "断言"},
    ]


@pytest.fixture()
def aid(tmp_path, monkeypatch):
    autoid = "203699999999000001"
    outd = ROOT / "workspace" / "outputs" / autoid
    yield autoid
    import shutil
    shutil.rmtree(outd, ignore_errors=True)


def test_gate_reports_and_refuses(aid):
    out = _emit(aid, _steps_with("sdns fulldns on"))
    assert out.startswith("error: command-existence gate"), out
    assert "NEEDS_USER_DECISION" in out and "command_existence_evidence" in out
    nd = ROOT / "workspace" / "outputs" / aid / "needs_decision.json"
    assert nd.is_file(), "呈报台账未落盘"
    claims = json.loads(nd.read_text(encoding="utf-8"))["claims"]
    ce = [c for c in claims if c.get("claim_kind") == "command_existence"]
    assert ce and ce[0]["command"] == "sdns fulldns on"
    assert "手册" in ce[0]["reason"]  # 检索证明(user-facing 中文)
    assert not (ROOT / "workspace" / "outputs" / aid / "case.xlsx").exists(), "拒落卷失败"
    assert not (ROOT / "workspace" / "outputs" / aid / ".grade_credential.json").exists()


def test_gate_evidence_escape_manual_ref(aid):
    inv = load_inventory("10.5")
    src = inv["heads"]["sdns listener"]["src"]          # 真实存在的行级引用
    # 用「手册确实记载的命令」+对应行证据:门先未命中才会查证据——构造一个
    # 清单外但手册正文有的形态不稳定;此处直接验证证据校验器本身的判定。
    from main.ist_core.tools.device.emit_xlsx_tool import _verify_command_evidence
    ok, note = _verify_command_evidence(src, ["sdns listener 1.2.3.4"])
    assert ok, note
    ok2, _ = _verify_command_evidence(src, ["sdns fulldns on"])
    assert not ok2, "证据窗口不含命令词面时必须拒绝"
    ok3, _ = _verify_command_evidence("dev_help: `sdns fulldns ?` accepted on device",
                                      ["sdns fulldns on"])
    assert ok3, "设备 attestation 形态应接受"


def test_gate_evidence_escape_end_to_end(aid):
    out = _emit(aid, _steps_with("sdns fulldns on"),
                command_existence_evidence="dev_help: verified `sdns fulldns ?` on device")
    assert not out.startswith("error: command-existence gate"), out


def test_gate_user_decision_escape(aid):
    outd = ROOT / "workspace" / "outputs" / aid
    outd.mkdir(parents=True, exist_ok=True)
    (outd / "needs_decision.json").write_text(json.dumps({
        "autoid": aid, "claims": [{"claim_kind": "command_existence",
                                   "command": "sdns fulldns on", "reason": "x"}]}),
        encoding="utf-8")
    (outd / "user_decision.json").write_text(json.dumps({
        "autoid": aid, "decision": "改过程"}), encoding="utf-8")
    out = _emit(aid, _steps_with("sdns fulldns on"))
    assert not out.startswith("error: command-existence gate"), "同键不复问((20))失效"


def test_gate_env_off(aid, monkeypatch):
    monkeypatch.setenv("IST_COMMAND_EXISTENCE_GATE", "0")
    out = _emit(aid, _steps_with("sdns fulldns on"))
    assert not out.startswith("error: command-existence gate")


def test_gate_passes_clean_volume(aid):
    out = _emit(aid, _steps_with("sdns host name www.a.com"))
    assert not out.startswith("error: command-existence gate"), out


# ---------------------------------------------------------------- 问询组题
def test_questions_command_existence_wording(tmp_path):
    from main.ist_core.compile_engine_v8.questions import build_questions, validate_questions
    aid = "203699999999000002"
    ledgers = {aid: {"autoid": aid, "claims": [{
        "claim_kind": "command_existence", "command": "sdns fulldns on",
        "reason": "命令『sdns fulldns on』在 10.5 版本手册命令集未命中", "min_requests": 0,
        "ordering_sensitive": False}]}}
    qs = build_questions(ledgers)
    assert len(qs) == 1
    q = qs[0]
    assert "查无记载" in q["question"] and aid[-6:] in q["question"]
    assert [o["label"] for o in q["options"]] == ["改过程", "改预期", "改描述"]
    assert "挂起" in q["options"][2]["description"]      # fulldns 类正确出口
    assert validate_questions(qs, ledgers)
