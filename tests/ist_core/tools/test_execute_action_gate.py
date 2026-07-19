# -*- coding: utf-8 -*-
"""#56 execute 动作名精确集门（A 层必崩门族新成员）红绿守门 + 存量零误杀反扫。

起因（#51-A §4 离线仿真）：execute 的 dispatch（dic_operation.execute:57）先精确匹配
（get_same）失败才落 fuzzy（SequenceMatcher≥0.8，:72）——40 动作名两两算出 9 对 ≥0.8 碰撞，
5 对语义反转（健检 UP⇄DOWN 0.812 / 绑定⇄检查 0.897 / 用户⇄数据 0.833 / AXFR⇄IXFR 0.944）。
一个写不精确的动作名会**静默派到语义相反的 func**，device 侧不可见（不像 cmd 错有 ^ 拒）。
门：F=execute 行的 G 动作名必须 ∈ 注册表精确闭集（从 mirror apv_action/client_action +
synonyms 解析，不手抄），否则拒 + 给候选提示但**不自动改写**（自动纠正=把 fuzzy 隐患搬到门上）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from main.ist_core.tools.device import structural_gate as SG


def _gate(rows):
    r = SG.StructuralResult()
    SG._check_execute_action_registry(rows, r)
    return r


def _codes(r):
    return [v.code for v in r.violations]


# ── 闭集：从 mirror 解析、非手抄 ──────────────────────────────────────────────


def test_closed_set_parsed_from_mirror_nonempty():
    names = SG._execute_action_names()
    assert len(names) >= 40, f"闭集过小，疑解析失败：{len(names)}"
    # 命令映射键 + synonyms 值都在（归一化）
    assert SG._norm_action("访问") in names                       # client_action 键
    assert SG._norm_action("指定Service健康检查UP") in names       # apv_action 键
    assert SG._norm_action("响应内容为") in names                 # apv_synonyms 值
    assert SG._norm_action("访问url") in names                    # client_synonyms 值


def test_fail_open_when_registry_unreadable(monkeypatch):
    """mirror 读不到→空注册表→门 fail-open（不误杀，§33-37 分发闭集纪律）。"""
    monkeypatch.setattr(SG, "_execute_action_registry", lambda: {})
    r = _gate([{"E": "APV_0", "F": "execute", "G": "任何乱写的动作：x"}])
    assert _codes(r) == [], "空注册表应 fail-open 零违例"


# ── 红绿：精确放行 / 改述拒 ──────────────────────────────────────────────────


def test_exact_action_name_accepted():
    assert _codes(_gate([{"E": "clientc", "F": "execute", "G": "访问：https://1.1.1.1"}])) == []
    assert _codes(_gate([{"E": "APV_0", "F": "execute", "G": "指定Service健康检查UP：svc1"}])) == []


def test_synonym_value_accepted():
    # get_same 精确面也认 synonyms 值，门须一致放行
    assert _codes(_gate([{"E": "clientc", "F": "execute", "G": "发送http请求：x"}])) == []
    assert _codes(_gate([{"E": "APV_0", "F": "execute", "G": "server返回：hello"}])) == []


def test_paraphrase_rejected_with_hint_no_autorewrite():
    row = {"E": "APV_0", "F": "execute", "G": "指定Service健康检查上线：svc1"}
    r = _gate([row])
    assert _codes(r) == ["execute_action_not_in_registry"]
    detail = r.violations[0].detail
    assert "不自动改写" in detail and "有意识" in detail        # 明示不自动纠正
    assert "指定Service健康检查UP" in detail                    # 候选提示含真实近名
    assert row["G"] == "指定Service健康检查上线：svc1"          # 门未改写输入行


def test_semantic_inversion_near_name_caught():
    """语义反转隐患坐实：一个改述名若落 fuzzy 会派到 UP/DOWN 之一——门在精确面即拦下，
    不给 fuzzy 机会。"""
    for bad in ("健康检查状态UP", "指定类型健康检查上", "批量绑定错误码"):
        r = _gate([{"E": "APV_0", "F": "execute", "G": f"{bad}：x"}])
        assert _codes(r) == ["execute_action_not_in_registry"], bad


def test_action_name_extraction_matches_dispatch():
    """动作名抽取复刻 dic_operation.execute:58（全角冒号前段，贪婪到末个 ：）。"""
    assert SG._execute_action_of("访问：a：b") == "访问：a"      # 贪婪到末个 ：
    assert SG._execute_action_of("访问") == "访问"              # 无冒号=整串
    # 无冒号的精确名照样放行
    assert _codes(_gate([{"E": "clientc", "F": "execute", "G": "访问"}])) == []


def test_non_execute_rows_untouched():
    rows = [
        {"E": "APV_0", "F": "cmd_config", "G": "slb virtual service vs1"},
        {"E": "check_point", "F": "found", "G": r"\bUP\b"},
        {"E": "test_env", "F": "server231", "G": "systemctl stop nginx"},
    ]
    assert _codes(_gate(rows)) == []


def test_registered_in_mandatory_gate_set():
    """集成：check_crash_gates_mandatory 含 execute 动作门（改述 execute 行整批必拒）。"""
    r = SG.check_crash_gates_mandatory(
        [{"E": "APV_0", "F": "execute", "G": "乱写的健康检查：svc", "H": None, "I": None}]
    )
    assert "execute_action_not_in_registry" in [v.code for v in r.violations]


# ── 存量零误杀反扫（105 卷语料 execute 行数=0，门无从误杀）──────────────────────

_CORPUS = pathlib.Path(__file__).resolve().parents[3] / "docs/forensics/team4_theory_corpus_extract.jsonl"


@pytest.mark.skipif(not _CORPUS.exists(), reason="105 卷语料 forensics 文件不在")
def test_retro_scan_corpus_zero_execute_rows():
    """#56 零误杀铁证（我方产出面）：105 卷交付语料 f_sequence 里 execute 行数=0——门对存量
    我方卷无从误杀（leader 预测的 emptiness，作为测试证据固化）。"""
    n_execute = 0
    for line in _CORPUS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        n_execute += sum(1 for f in (d.get("f_sequence") or []) if f == "execute")
    assert n_execute == 0, f"存量语料出现 {n_execute} 个 execute 行，需人工核对门是否误杀"


_SMOKE = pathlib.Path(__file__).resolve().parents[3] / "knowledge/framework/mirror/smoke_test"


@pytest.mark.skipif(not _SMOKE.exists(), reason="smoke_test 金标准卷不在")
def test_gold_standard_execute_rows_all_in_registry():
    """#56 spec addendum 交叉核验（leader 令，零误杀最强证据）：380 金标准卷全部 F=execute
    行的 G 动作名必须 100% ∈ 解析闭集——**含 synonyms 形态**（get_same 精确面）。false-kill
    合法 synonym 比无门更糟，本测把"金标准零 false-kill"固化。任一 miss=parser 缺陷或金标准
    异常（皆 finding）。实测 2208 execute 行 100% 命中、0 未命中。"""
    import openpyxl
    reg = SG._execute_action_registry()
    total = miss = 0
    misses = []
    for xp in _SMOKE.rglob("*.xlsx"):
        try:
            wb = openpyxl.load_workbook(xp, read_only=True, data_only=True)
        except Exception:
            continue
        for ws in wb.worksheets:
            for row in ws.iter_rows(min_row=1, values_only=True):
                if not row or len(row) < 7 or str(row[5]).strip() != "execute":
                    continue
                total += 1
                na = SG._norm_action(
                    SG._execute_action_of(str(row[6]) if row[6] is not None else ""))
                if na not in reg:
                    miss += 1
                    if len(misses) < 10:
                        misses.append((xp.parent.name, na))
        wb.close()
    assert total > 0, "金标准卷未发现 execute 行，交叉核验前提不成立（非空断言防 vacuous）"
    assert miss == 0, \
        f"金标准 {total} execute 行有 {miss} 个动作名不在闭集（parser 缺陷/金标准异常）：{misses}"
