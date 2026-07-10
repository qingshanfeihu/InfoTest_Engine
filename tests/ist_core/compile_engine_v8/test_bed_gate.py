"""床态体检门宪法测试:INV-5(锚差拦截零设备轮)+INV-9(床权边界)+版本距离策略+床账配对。"""
from __future__ import annotations

from main.ist_core.compile_engine_v8.bed import (
    version_family, anchor_verdict, bed_record, bed_unrestored, bed_check,
)

CFG = "InfosecOS_Beta_APV_HG_K_10_5_0_568"
DEV_585 = " Software Version : InfosecOS Beta.APV-HG-K.10.5.0.585\n Host name : APV"
DEV_1046 = " Software Version : InfosecOS Beta.APV-HG-K.10.4.6.170\n Host name : APV"


def _probe(build_echo, extra=None):
    extra = extra or {}
    def fn(cmd: str) -> str:
        if "version" in cmd:
            return build_echo
        return extra.get(cmd, "(no output)")
    return fn


# ── 版本距离策略:同族放行(568vs585),跨 minor 必拦(yzg@103 场景) ───────────────

def test_version_family_and_same_family_match():
    assert version_family(CFG) == (10, 5)
    assert version_family("InfosecOS Beta.APV-HG-K.10.5.0.585") == (10, 5)
    v = anchor_verdict("InfosecOS Beta.APV-HG-K.10.5.0.585", CFG)
    assert v["status"] == "match"


def test_inv5_cross_minor_mismatch_triggers_ask(tmp_path):
    rep = bed_check(_probe(DEV_1046), CFG, root=tmp_path, host="10.4.127.103")
    assert rep["anchor"]["status"] == "mismatch"
    assert rep["needs_ask"] is True
    assert any(f["kind"] == "build_anchor" for f in rep["findings"])


def test_unparseable_build_is_honest_unknown(tmp_path):
    rep = bed_check(_probe("error: probe failed"), CFG, root=tmp_path, host="h")
    assert rep["anchor"]["status"] == "unknown" and rep["needs_ask"]


def test_precedent_drift_noted_not_blocking():
    v = anchor_verdict("InfosecOS Beta.APV-HG-K.10.5.0.585", CFG,
                       precedent_build="InfosecOS_Beta_APV_HG_K_10_4_6_170")
    assert v["status"] == "match" and "precedent_drift" in v


# ── 床账:created/restored 配对;跨批接力 ─────────────────────────────────────

def test_bed_ledger_pairing(tmp_path):
    bed_record(tmp_path, "10.4.127.93", "created", "segment", "s1", batch="b1")
    bed_record(tmp_path, "10.4.127.93", "created", "sdns_config_file", "f1", batch="b1")
    bed_record(tmp_path, "10.4.127.93", "restored", "segment", "s1", batch="b1")
    left = bed_unrestored(tmp_path, "10.4.127.93")
    assert len(left) == 1 and left[0]["id"] == "f1"      # 崩溃未复原的下批可见


# ── INV-9 床权边界:非己方残留只 ask,己方未复原可自动清 ────────────────────────

def test_inv9_foreign_residue_asks_never_cleans(tmp_path):
    extra = {"show segment name": "segment: colleague_seg1  status: active"}
    rep = bed_check(_probe(DEV_585, extra), CFG, root=tmp_path, host="h")
    assert rep["anchor"]["status"] == "match"
    assert any(f["kind"] == "segments" for f in rep["findings"])
    assert rep["needs_ask"] is True                       # 有异物且床账无据 → 问
    assert rep["ours_unrestored"] == []


def test_inv9_our_unrestored_enables_auto_path(tmp_path):
    bed_record(tmp_path, "h", "created", "sdns_config_file", "sdns_test", batch="yzg")
    extra = {"show sdns config file": "sdns_test.conf"}
    rep = bed_check(_probe(DEV_585, extra), CFG, root=tmp_path, host="h")
    assert rep["ours_unrestored"] and rep["ours_unrestored"][0]["id"] == "sdns_test"
    assert rep["needs_ask"] is False                      # 己方账内产物:自动恢复路径


def test_clean_bed_clean_pass(tmp_path):
    rep = bed_check(_probe(DEV_585), CFG, root=tmp_path, host="h")
    assert rep["needs_ask"] is False and rep["findings"] == []


# ── 初始化清理(2026-07-10 用户裁决:开工必净) ─────────────────────────────────

def test_bed_cleanup_executes_grammar_ref_and_records_ledger(tmp_path):
    """有文法清理引用的 kind → 执行清理命令+记床账;无引用的 kind → skipped 不动手。"""
    from main.ist_core.compile_engine_v8.bed import bed_cleanup, _ledger_path
    ran: list[str] = []

    def probe(cmd: str) -> str:
        ran.append(cmd)
        return "cleared"

    findings = [{"kind": "sdns_config_files", "detail": "sdns_test.conf"},
                {"kind": "segments", "detail": "seg1"},          # 无清理引用
                {"kind": "build_anchor", "detail": {}}]          # 版本锚不清
    out = bed_cleanup(probe, findings, root=tmp_path, host="h", batch="b")
    assert [c["kind"] for c in out["cleaned"]] == ["sdns_config_files"]
    assert out["skipped"] == ["segments"]
    assert ran and "clear" in ran[0]                     # 命令来自文法数据,非硬编码
    led = _ledger_path(tmp_path, "h").read_text(encoding="utf-8")
    assert '"cleaned"' in led and "sdns_config_files" in led


def test_bed_cleanup_never_touches_unknown_kinds(tmp_path):
    from main.ist_core.compile_engine_v8.bed import bed_cleanup
    ran: list[str] = []
    out = bed_cleanup(lambda c: ran.append(c) or "", 
                      [{"kind": "synconfig_peer", "detail": "peer cfg"}],
                      root=tmp_path, host="h")
    assert out["cleaned"] == [] and out["skipped"] == ["synconfig_peer"]
    assert ran == []                                     # 零执行:无引用绝不动手
