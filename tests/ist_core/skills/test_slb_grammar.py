# -*- coding: utf-8 -*-
"""#51-C SLB grammar 合并 eval（Theory 草稿 + LLM-Eng verbatim fine-check，四关前锁契约）。

单写者合入 `domain_grammar.json` 的 SLB first-batch（G1/G2）文法回归守门：
  4 statement（virtual/real define + group_member + policy_default）
  + 2 reference_closure（member→real / policy→vs）。

**fine-check 回归锚**（我的增值，防漂移/防 rubber-stamp 回潮）：
  ① IPv6 vip/rsip 必捕（金标准 167 个 IPv6 VS）；② port 可选（`slb real dns r1 <ip>` 无 port 存在）；
  ③ `slb real health`/`slb real enable` 不得被 real-define 误捕（前者是附加健检 `<hc_name> <real_service>…`
     首参非 real、金标准 0 用；后者是 toggle）；④ Theory 原 slb_real_health_bind + slb_health_needs_real
     已 DROP（金标准真健康形态是 `slb virtual health on|off` VS-toggle，无 real 引用）——不得回潮；
  ⑤ policy 闭包收窄为 policy→vs（单-name 命名空间限制，policy→group DEFERRED）。
纪律：2026-07-13 命令注入红线（零 suggested_teardown）；footprint_node/silently_accepted 留空(device-pending)。
"""
from __future__ import annotations

import json

from main.case_compiler import domain_grammar as dg

_SLB_STMTS = ("slb_virtual_service_define", "slb_real_service_define",
              "slb_group_member", "slb_policy_default")


def test_slb_statements_present_with_provenance():
    g = dg.load_grammar()
    for sid in _SLB_STMTS:
        assert sid in g["statements"], f"{sid} 未入文法"
        assert g["statements"][sid].get("provenance"), f"{sid} 缺出处（文法层红线）"
        assert dg.stmt_re(sid).pattern == g["statements"][sid]["pattern"]


def test_slb_virtual_captures_name_vip_ipv4_and_ipv6():
    """fine-check ①：vip 须捕 IPv4 与 IPv6（金标准 167 个 IPv6 VS，Theory 原 [\\d.] 会漏）。"""
    r = dg.stmt_re("slb_virtual_service_define")
    m4 = r.search("slb virtual https https-vs 172.16.34.100 443 arp")
    assert m4.group("name") == "https-vs" and m4.group("vip") == "172.16.34.100"
    m6 = r.search("slb virtual tcps v1 3ffc::75 443")
    assert m6.group("name") == "v1" and m6.group("vip") == "3ffc::75"
    # 引号 VS 名
    assert r.search('slb virtual http "v1" 172.16.34.100 80 arp 0').group("name") == "v1"


def test_slb_real_port_optional_and_excludes_health_enable():
    """fine-check ②③：port 可选；health/enable 不被 real-define 误捕。"""
    r = dg.stmt_re("slb_real_service_define")
    assert r.search("slb real http rs1 172.16.35.231 80 0 tcp 1 1").group("name") == "rs1"
    assert r.search("slb real dns r1 172.16.34.71").group("name") == "r1"  # 无 port
    # 附加健检（首参 a1=hc_name 非 real）与 toggle 不得误命中
    assert r.search("slb real health a1 rs1 172.16.165.73 80 tcp") is None
    assert r.search("slb real enable server213") is None


def test_slb_health_bind_statement_and_closure_dropped():
    """fine-check ④：Theory 原 slb_real_health_bind + slb_health_needs_real 已 DROP，不得回潮
    （金标准 0 用 `slb real health`，真形态 `slb virtual health on|off` 无 real 引用）。"""
    g = dg.load_grammar()
    assert "slb_real_health_bind" not in g["statements"]
    cids = {c["id"] for c in dg.reference_closures()}
    assert "slb_health_needs_real" not in cids


def _closure(cid):
    return next(c for c in dg.reference_closures() if c["id"] == cid)


def test_slb_member_needs_real_closure():
    """member 引用的 real 未 define → 悬空；先 define 后引用 → 空。"""
    c = _closure("slb_group_member_needs_real")
    assert dg.dangling_references(c, ["slb group member g1 r9"]) == ["r9"]
    assert dg.dangling_references(
        c, ["slb real http r1 172.16.35.231 80", "slb group member g1 r1"]) == []


def test_slb_policy_needs_vs_closure():
    """fine-check ⑤：policy 绑的 VS 未 define → 悬空；已 define → 空；show 前导跳过。"""
    c = _closure("slb_policy_needs_vs")
    assert dg.dangling_references(c, ["slb policy default v9 g1"]) == ["v9"]
    assert dg.dangling_references(
        c, ["slb virtual http v1 172.16.34.100 80", "slb policy default v1 g1"]) == []
    assert dg.dangling_references(c, ["show slb policy default v1 g1"]) == []


def test_slb_closures_device_pending_fields_empty():
    """leader 令：footprint_node/silently_accepted device-pending，留空不臆造。"""
    for cid in ("slb_group_member_needs_real", "slb_policy_needs_vs"):
        c = _closure(cid)
        assert not c.get("footprint_node"), f"{cid} footprint_node 应留空(device-pending)"
        assert not c.get("silently_accepted"), f"{cid} silently_accepted 应留空(device-pending)"


def test_slb_grammar_no_command_suggestion_injection():
    """2026-07-13 红线：SLB 加料只放结构 pattern+provenance，零命令建议。"""
    g = dg.load_grammar()
    blobs = [json.dumps(g["statements"][s], ensure_ascii=False) for s in _SLB_STMTS]
    for cid in ("slb_group_member_needs_real", "slb_policy_needs_vs"):
        blobs.append(json.dumps(_closure(cid), ensure_ascii=False))
    for blob in blobs:
        assert "suggested_teardown" not in blob
