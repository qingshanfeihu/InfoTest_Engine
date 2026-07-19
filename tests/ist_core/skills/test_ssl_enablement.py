# -*- coding: utf-8 -*-
"""#52 SSL enablement 批 eval（eval-first，四关前锁契约）。

三处资产的回归守门（改任一处必先过本文件）：
  ① 文法层 `domain_grammar.json`：ssl_host_define + ssl_cert_activate_ref statement
     + ssl_cert_activate_needs_host_define 悬空引用闭包（带 provenance、无命令注入）；
  ② `contracts.md`：SSL dispatch 检索面段（指向 mirror dispatch 源，非内联清单）
     + S1-S5 静默失败面表；
  ③ `compile-attributor.md`：[A24] SSL 静默失败面 pointer（归因 SSL fail 前查 contracts）。

纪律锚：数据按引用（方法清单留 mirror 源、prompt/JSON 只指路）；2026-07-13 命令注入红线
（文法层只放结构 pattern+provenance，零 suggested_teardown）；⑥C 双射/熔断由
test_rule_attribution.py 另守，本文件只守 SSL enablement 内容在场与行为。
"""
from __future__ import annotations

import json
from pathlib import Path

from main.case_compiler import domain_grammar as dg

_ROOT = Path(__file__).resolve().parents[3]
_REFS = _ROOT / "main/ist_core/skills/ist-compile-engine/references"
_ATTRIBUTOR = _ROOT / "main/ist_core/agents/compile-attributor.md"

_SSL_CLOSURE = "ssl_cert_activate_needs_host_define"


# ── ① 文法层：statement 入库 + provenance + 可编译 ──────────────────────────────


def test_ssl_statements_present_with_provenance():
    g = dg.load_grammar()
    for sid in ("ssl_host_define", "ssl_cert_activate_ref"):
        assert sid in g["statements"], f"{sid} 未入文法"
        assert g["statements"][sid].get("provenance"), f"{sid} 缺出处（文法层红线）"
        # pattern 已预编译且与源一致
        assert dg.stmt_re(sid).pattern == g["statements"][sid]["pattern"]


def test_ssl_statements_capture_name_group():
    """闭包依赖 name 命名组：define/ref 各自捕获（含引号变体）。"""
    hd = dg.stmt_re("ssl_host_define")
    assert hd.search("ssl host virtual vh1").group("name") == "vh1"
    assert hd.search('ssl host real "rh1"').group("name") == "rh1"
    ar = dg.stmt_re("ssl_cert_activate_ref")
    assert ar.search('ssl activate certificate "vh1" 1 "" all').group("name") == "vh1"
    assert ar.search("ssl deactivate certificate rh1").group("name") == "rh1"


# ── ① 文法层：悬空引用闭包行为 ────────────────────────────────────────────────


def _closure():
    return next(c for c in dg.reference_closures() if c["id"] == _SSL_CLOSURE)


def test_ssl_closure_flags_activate_without_host_define():
    """activate 引用的 host 无 ssl host virtual/real 定义 → 悬空（证书激活无宿主）。"""
    assert dg.dangling_references(_closure(), ["ssl activate certificate vh1"]) == ["vh1"]


def test_ssl_closure_passes_well_formed_sequence():
    """先 define 后 activate → 无悬空（金标准 sdns_ssl_conn 序）。"""
    assert dg.dangling_references(
        _closure(), ["ssl host virtual vh1", "ssl activate certificate vh1"]) == []


def test_ssl_closure_normalizes_case_and_quotes():
    """SSL 名 CLI 大小写不敏感 + 引用带引号：归一后仍匹配，不误报。"""
    assert dg.dangling_references(
        _closure(), ["ssl host virtual VH1", 'ssl activate certificate "vh1"']) == []


def test_ssl_closure_skips_show_query():
    """前导 show=查询非引用，跳过（不当作悬空引用）。"""
    assert dg.dangling_references(_closure(), ["show ssl certificate vh1"]) == []


def test_ssl_grammar_no_command_suggestion_injection():
    """2026-07-13 红线：文法层 SSL 加料只放结构 pattern+provenance，零命令建议。"""
    g = dg.load_grammar()
    blobs = [json.dumps(g["statements"][sid], ensure_ascii=False)
             for sid in ("ssl_host_define", "ssl_cert_activate_ref")]
    blobs.append(json.dumps(_closure(), ensure_ascii=False))
    for blob in blobs:
        assert "suggested_teardown" not in blob


# ── ② contracts.md：SSL dispatch 检索面 + S1-S5（数据按引用） ─────────────────


def test_contracts_ssl_dispatch_points_at_mirror_sources():
    txt = (_REFS / "contracts.md").read_text(encoding="utf-8")
    assert "SSL dispatch" in txt, "contracts 缺 SSL dispatch 段"
    # 指向 mirror dispatch 源（数据按引用、非内联 25 方法清单）
    for src in ("ssl_comm", "dic_operation", "test_xlsx.py", "env.py"):
        assert src in txt, f"SSL dispatch 段缺 mirror 源指针 {src}"
    # sm2 3 参订正（#50 CC2）在场，防 worker 按 RSA 2 参编坏行
    assert "3 args" in txt and "keyType" in txt


def test_contracts_ssl_silent_failure_faces_s1_to_s5():
    txt = (_REFS / "contracts.md").read_text(encoding="utf-8")
    for face in ("S1", "S2", "S3", "S4", "S5"):
        assert face in txt, f"SSL 静默失败面缺 {face}"


# ── ③ compile-attributor.md：[A24] SSL 静默失败面 pointer ─────────────────────


def test_attributor_a24_ssl_silent_failure_pointer():
    txt = _ATTRIBUTOR.read_text(encoding="utf-8")
    assert "[A24]" in txt, "attributor 缺 [A24] marker（⑥C 双射另由 test_rule_attribution 守）"
    low = " ".join(txt.split()).lower()
    assert "ssl" in low and "silent" in low, "attributor [A24] 缺 SSL 静默失败面知识"
    assert "contracts" in low, "attributor [A24] 未指向 contracts（数据按引用）"
