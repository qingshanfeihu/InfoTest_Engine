"""E10b 工具壳接线回归：sequence_json 序列↔周期自洽（advisory）+ cycle_kind 数据现查映射。

通用性红线（2026-07-16 用户裁决）：纯函数只认**周期语义类** cycle_kind；「算法名→语义类」
映射在壳层从 domain_grammar.json `algorithm_classes` **数据现查**（uniform_rotation 命中→判、
distribution 命中但非 uniform→None fail-open、都不中→none 确定性映射）——新算法=加 JSON
条目零代码，.py 内零算法语义。
"""

from __future__ import annotations

import json

from main.ist_core.tools.device.verifiability_tool import (
    compile_check_verifiability,
    _cycle_kind_from_algo,
    _parse_sequence_json,
)

AID = "203600000000000012"
# 778012 恒假形态：前 3 not_found + 后 5 全 found（P=4 由 n_pools 供给）
SEQ_CONTRADICTORY = json.dumps(["not_found", "not_found", "not_found",
                                "found", "found", "found", "found", "found"])
SEQ_OK = json.dumps(["not_found", "found", None, "not_found", None, "found"])  # r=1 mod 4 可满足


def _redirect_ledger(tmp_path, monkeypatch):
    import main.ist_core.tools.device.verifiability_tool as vt

    def _redirected(aid, kind, entry):
        nd = tmp_path / aid
        nd.mkdir(parents=True, exist_ok=True)
        p = nd / "needs_decision.json"
        data = {"autoid": aid, "claims": []}
        if p.is_file():
            data = json.loads(p.read_text())
        data["claims"] = [c for c in data["claims"] if c.get("claim_kind") != kind]
        data["claims"].append({**entry, "claim_kind": kind})
        p.write_text(json.dumps(data, ensure_ascii=False))
        return True

    monkeypatch.setattr(vt, "_land_needs_decision", _redirected)


def test_cycle_kind_from_algo_data_driven():
    """映射走 grammar 数据：rr∈uniform_rotation→判；wrr∈distribution 非 uniform→None
    fail-open（剩余类语义未钉死）；ga 非分布→none（确定性映射）；空→None。"""
    assert _cycle_kind_from_algo("rr") == "uniform_rotation"
    assert _cycle_kind_from_algo("wrr") is None
    assert _cycle_kind_from_algo("gwrr") is None
    assert _cycle_kind_from_algo("ga") == "none"
    assert _cycle_kind_from_algo("") is None


def test_parse_sequence_json_contract():
    ok = _parse_sequence_json(SEQ_OK)
    assert ok == ([1, 5], [0, 3])                      # null 跳过、序号保位
    assert isinstance(_parse_sequence_json("[1,2]"), str)      # 非法元素 → error 文本
    assert isinstance(_parse_sequence_json("{"), str)          # 坏 JSON → error 文本
    assert isinstance(_parse_sequence_json('{"a":1}'), str)    # 非数组 → error 文本


def test_sequence_contradiction_overrides_to_needs_decision(tmp_path, monkeypatch):
    """rr（grammar 现查→uniform_rotation）+ 恒假排布 → 覆盖为 NEEDS_USER_DECISION，
    台账落独立 sequence_periodicity 条目（ordering_sensitive）。"""
    _redirect_ledger(tmp_path, monkeypatch)
    out = compile_check_verifiability.func(
        autoid=AID, algo="rr", n_requests=8, n_pools=4,
        claim_kind="rotation_order", sequence_json=SEQ_CONTRADICTORY)
    assert "NEEDS_USER_DECISION" in out and "恒假" in out
    data = json.loads((tmp_path / AID / "needs_decision.json").read_text())
    kinds = {c["claim_kind"] for c in data["claims"]}
    assert "sequence_periodicity" in kinds
    seq_claim = next(c for c in data["claims"] if c["claim_kind"] == "sequence_periodicity")
    assert seq_claim["ordering_sensitive"] is True


def test_sequence_satisfiable_keeps_main_verdict(tmp_path, monkeypatch):
    """可满足排布不覆盖：主判定 VERIFIABLE 照常返回并附序列自查说明。"""
    _redirect_ledger(tmp_path, monkeypatch)
    out = compile_check_verifiability.func(
        autoid=AID, algo="rr", n_requests=6, n_pools=4,
        claim_kind="rotation_order", sequence_json=SEQ_OK)
    assert out.startswith("VERIFIABLE")
    assert "序列自洽自查" in out


def test_sequence_check_gated_by_switch_and_claim_kind(tmp_path, monkeypatch):
    """开关关/claim_kind 不在附加集 → 序列检查不跑（恒假排布也不拦）。"""
    _redirect_ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("IST_SEQ_CONSISTENCY_CHECK", "0")
    out = compile_check_verifiability.func(
        autoid=AID, algo="rr", n_requests=8, n_pools=4,
        claim_kind="rotation_order", sequence_json=SEQ_CONTRADICTORY)
    assert out.startswith("VERIFIABLE")            # 开关关：主判定照常
    monkeypatch.delenv("IST_SEQ_CONSISTENCY_CHECK")
    out2 = compile_check_verifiability.func(
        autoid=AID, algo="rr", n_requests=30, n_pools=3,
        claim_kind="distribution", sequence_json=SEQ_CONTRADICTORY)
    assert out2.startswith("VERIFIABLE")           # distribution 不在附加集：不跑序列检查


def test_sequence_unknown_cycle_kind_failopen(tmp_path, monkeypatch):
    """wrr（grammar 无 uniform 语义→None）恒假排布也放行——未知不误杀；
    显式 cycle_kind=uniform_rotation 传入则语义抽取优先、照判。"""
    _redirect_ledger(tmp_path, monkeypatch)
    out = compile_check_verifiability.func(
        autoid=AID, algo="wrr", n_requests=8, n_pools=4,
        claim_kind="rotation_order", sequence_json=SEQ_CONTRADICTORY)
    assert out.startswith("VERIFIABLE")
    out2 = compile_check_verifiability.func(
        autoid=AID, algo="wrr", n_requests=8, n_pools=4,
        claim_kind="rotation_order", sequence_json=SEQ_CONTRADICTORY,
        cycle_kind="uniform_rotation")
    assert "NEEDS_USER_DECISION" in out2


def test_docstring_declares_new_claim_kind_and_sequence():
    """LLM-facing 契约：claim_kind 参数描述含 cross_client_landing 枚举（parse_docstring
    把 Args 段拆进参数 schema——LLM 看到的正是这里）；sequence_json/cycle_kind 参数在 schema。"""
    props = compile_check_verifiability.args_schema.model_json_schema()["properties"]
    ck_desc = props.get("claim_kind", {}).get("description", "")
    assert "cross_client_landing" in ck_desc, "claim_kind 枚举缺新维——worker 不知道有这维"
    assert "captured_relation" in ck_desc      # 与用户拍板 form 词汇对齐（team-lead 冻结）
    assert "sequence_json" in props and "cycle_kind" in props
    seq_desc = props.get("sequence_json", {}).get("description", "")
    assert "not_found" in seq_desc             # 用法契约在参数描述里
