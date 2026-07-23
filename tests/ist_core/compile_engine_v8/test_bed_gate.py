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


def test_build_probe_failure_is_probe_failed_not_mismatch(tmp_path):
    """build 探针自身失败=床态未知(probe_failed),不是"版本不匹配/unknown"——
    2026-07-13 实证:105 床 SSH 挂死,空版本被呈报成「⚠ 版本不匹配:设备(空)」。"""
    rep = bed_check(_probe("error: probe failed"), CFG, root=tmp_path, host="h")
    assert rep["anchor"]["status"] == "probe_failed" and rep["needs_ask"]
    ba = [f for f in rep["findings"] if f["kind"] == "build_anchor"]
    assert ba and ba[0].get("probe_failed") is True


def test_unparseable_build_is_honest_unknown(tmp_path):
    """探针跑通、回显却解析不出版本号 → unknown(如实报告,不猜)。"""
    rep = bed_check(_probe("Software Version line without colon 10.5.0.585"),
                    CFG, root=tmp_path, host="h")
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


def test_probe_annotation_note_is_false_residue_fixed_by_raw_bed_probe(tmp_path):
    """回归#3:dev_probe 的空探针时机语义 note 被 bed_check 误当"分区配置残留"(yzg 实证)。
    根因=bed 探针走注 note 的路(annotate=True);修法A=bed 走原始探针(annotate=False)。
    本测试锚住因果链:note 进 bed_check=假残留;去掉 note(原始回显)=干净。"""
    from main.ist_core.tools.device.run_case import _annotate_if_empty_probe
    raw_empty = "=== dev_probe (fastmcp apv_ssh) ===\ncommand: show segment name\nstatus: success\n"
    note_leaked = _annotate_if_empty_probe(raw_empty)             # annotate=True 的产物(带 note)
    assert "re-probing emptiness" in note_leaked                 # 确认注入了 note

    # 旧行为:note 泄漏进 bed_check → 误报 segments 残留(根因复现)
    leak = bed_check(_probe(DEV_585, {"show segment name": note_leaked}),
                     CFG, root=tmp_path, host="h")
    assert any(f["kind"] == "segments" for f in leak["findings"])
    assert leak["needs_ask"] is True

    # 修法A:bed 走 annotate=False,空探针只回原始 banner(无 note)→ 干净床零假残留
    fixed = bed_check(_probe(DEV_585, {"show segment name": raw_empty}),
                      CFG, root=tmp_path, host="h")
    assert not any(f["kind"] == "segments" for f in fixed["findings"])
    assert fixed["needs_ask"] is False


def test_bed_probe_fn_returns_raw_no_annotation_note(monkeypatch):
    """回归#3 端到端(修法A 接线):bed 专用 nodes._probe_fn 走 annotate=False,空探针回显
    不含时机语义 note(与 worker 侧 dev_probe 带-note 便利分离)——bed_check 不再误报假残留。"""
    import main.case_compiler.device_mcp_client as mcp
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(
        mcp, "probe_via_fastmcp",
        lambda *a, **k: {"text": "command: show segment name\nstatus: success\n"})
    out = N._probe_fn("show segment name")               # bed 专用路(annotate=False)
    assert "re-probing emptiness" not in out             # bed 路:原始事实,零 note
    assert out.startswith("=== dev_probe")               # 仍是探针原文(banner 在)
    # 对照:worker 侧 _do_probe 默认 annotate=True 仍带 note(OBS-15 便利不回归)
    from main.ist_core.tools.device.run_case import _do_probe
    assert "re-probing emptiness" in _do_probe("show segment name")


# ── 初始化清理(2026-07-10 用户裁决:开工必净) ─────────────────────────────────

def _fake_grammar_with_ref():
    """合成清理引用(非交互):真实 sdns_config_files 引用带 interactive_confirm 会被跳过,
    执行路径用合成通道测。"""
    return {"bed_probes": {"cleanup_refs": {
        "fake_channel": {"cmd": "clear fake residue", "provenance": "测试用"}}}}


def test_bed_cleanup_executes_grammar_ref_and_records_ledger(tmp_path, monkeypatch):
    """有文法清理引用的 kind → config 通道执行+回显校验 success+记床账;无引用 → skipped。"""
    import main.ist_core.compile_engine_v8.bed as bedmod
    monkeypatch.setattr(bedmod, "load_grammar", _fake_grammar_with_ref)
    from main.ist_core.compile_engine_v8.bed import bed_cleanup, _ledger_path
    ran: list[str] = []

    def exec_cfg(cmd: str) -> str:
        ran.append(cmd)
        return f"host=x  mode=config\ncommand: {cmd}\nstatus: success\n--- output ---\n"

    findings = [{"kind": "fake_channel", "detail": "residue1"},
                {"kind": "segments", "detail": "seg1"},          # 无清理引用
                {"kind": "build_anchor", "detail": {}}]          # 版本锚不清
    out = bed_cleanup(exec_cfg, findings, root=tmp_path, host="h", batch="b")
    assert [c["kind"] for c in out["cleaned"]] == ["fake_channel"]
    assert out["failed"] == [] and out["skipped"] == ["segments"]
    assert ran == ["clear fake residue"]                 # 命令来自文法数据,非硬编码
    led = _ledger_path(tmp_path, "h").read_text(encoding="utf-8")
    assert '"cleaned"' in led and "fake_channel" in led


def test_bed_cleanup_device_rejection_reported_not_lied(tmp_path, monkeypatch):
    """设备拒绝(status: error,2026-07-10 show 通道实证)→ failed 如实上报,零床账,不谎报已清。"""
    import main.ist_core.compile_engine_v8.bed as bedmod
    monkeypatch.setattr(bedmod, "load_grammar", _fake_grammar_with_ref)
    from main.ist_core.compile_engine_v8.bed import bed_cleanup, _ledger_path
    out = bed_cleanup(lambda c: f"command: {c}\nstatus: error\n--- output ---\n",
                      [{"kind": "fake_channel", "detail": "x"}],
                      root=tmp_path, host="h")
    assert out["cleaned"] == []
    assert [f["kind"] for f in out["failed"]] == ["fake_channel"]
    assert not _ledger_path(tmp_path, "h").is_file()     # 失败不记 cleaned 账


def test_bed_cleanup_never_touches_unknown_kinds(tmp_path):
    from main.ist_core.compile_engine_v8.bed import bed_cleanup
    ran: list[str] = []
    out = bed_cleanup(lambda c: ran.append(c) or "", 
                      [{"kind": "synconfig_peer", "detail": "peer cfg"}],
                      root=tmp_path, host="h")
    assert out["cleaned"] == [] and out["skipped"] == ["synconfig_peer"]
    assert ran == []                                     # 零执行:无引用绝不动手


def test_phantom_findings_metadata_and_headers_filtered(tmp_path):
    """幽灵残留回归(2026-07-10 两轮实证):组合元数据行 host=IP  mode=show 与
    空列表的段落头/列头不构成残留;三通道实际全空 → 零发现零问询。"""
    empty_outputs = {
        "show segment name": "=== apv_ssh_execute ===\nhost=1.2.3.4  mode=show\ncommand: show segment name\nstatus: success\n--- output ---\nAPV#",
        "show synconfig peer": "host=1.2.3.4  mode=show\n--- output ---\n\nAPV#",
        "show sdns config file": ("host=1.2.3.4  mode=show\n--- output ---\n"
                                   "Running configuration backup files: \n"
                                   "length     date/time            name                 hmac-sm3\n\nAPV#"),
    }
    rep = bed_check(_probe(DEV_585, empty_outputs), CFG, root=tmp_path, host="h")
    assert rep["findings"] == [] and rep["needs_ask"] is False


def test_interactive_confirm_cleanup_skipped_not_lied(tmp_path):
    """需交互确认(YES)的清理引用:单发通道做不完 → skipped,绝不执行(会卡确认提示且误判成功)。"""
    from main.ist_core.compile_engine_v8.bed import bed_cleanup
    ran: list[str] = []
    out = bed_cleanup(lambda c: ran.append(c) or "status: success",
                      [{"kind": "sdns_config_files", "detail": "x"}],
                      root=tmp_path, host="h")
    assert out["cleaned"] == [] and out["skipped"] == ["sdns_config_files"]
    assert ran == []


def test_probe_failure_reported_as_unknown_not_residue(tmp_path):
    """探针失败≠残留(2026-07-11 yzg 验收实证):设备拒绝探针命令(% Invalid + ^)
    曾被"非空即报"当成分区残留——失败=床态未知,单独归类如实呈报。"""
    outputs = {
        "show segment name": ("host=1.2.3.4  mode=show\ncommand: show segment name\n"
                              "status: success\n--- output ---\n"
                              "% Invalid input: command 'show segment name' is invalid on this device\n"
                              "show segment name\n    ^"),
        "show synconfig peer": "host=1.2.3.4  mode=show\n--- output ---\nAPV#",
        "show sdns config file": "host=1.2.3.4  mode=show\n--- output ---\nAPV#",
    }
    rep = bed_check(_probe(DEV_585, outputs), CFG, root=tmp_path, host="h")
    seg = [f for f in rep["findings"] if f["kind"] == "segments"]
    assert seg and seg[0].get("probe_failed") is True
    assert rep["needs_ask"] is True                     # 床态未知也要问,但如实
    assert all(f.get("probe_failed") for f in rep["findings"])   # 不误报其他通道
    # 题面:探测未完成,不说"有残留"
    import main.ist_core.compile_engine_v8.engine_tool as ET
    captured = {}

    def _fake_panel(qs):
        captured["q"] = qs[0]["question"]
        return {"decision": "停止"}

    orig = ET._panel
    ET._panel = _fake_panel
    try:
        ET._bridge({"kind": "bed_gate", "report": {
            "anchor": {"status": "match", "device": "InfosecOS Beta.APV-HG-K.10.5.0.585"},
            "findings": rep["findings"], "cleanup": {}}})
    finally:
        ET._panel = orig
    assert "探测未完成" in captured["q"] and "床态未知" in captured["q"]
    assert "仍有残留" not in captured["q"]


def test_probe_failure_status_error_and_tool_error_forms(tmp_path):
    """契约级失败形态全覆盖:fastmcp status:error 行/工具 error: 前缀同样归探测失败。"""
    outputs = {
        "show segment name": "host=1.2.3.4  mode=show\nstatus: error\n--- output ---\nsomething",
        "show synconfig peer": "error: ssh channel closed",
        "show sdns config file": "host=1.2.3.4  mode=show\n--- output ---\nAPV#",
    }
    rep = bed_check(_probe(DEV_585, outputs), CFG, root=tmp_path, host="h")
    failed = {f["kind"] for f in rep["findings"] if f.get("probe_failed")}
    assert failed == {"segments", "sync_peers"}
    assert not [f for f in rep["findings"] if not f.get("probe_failed")]


# ── 2026-07-13 实弹回归:SSH 挂死床(105)的四种谎报形态 ───────────────────────

_SSH_DEAD = ("=== dev_probe (fastmcp apv_ssh) ===\n"
             "error: SSH to 172.16.35.70 failed: [Errno None] "
             "Unable to connect to port 22 on 172.16.35.70")


def test_probe_failure_fastmcp_banner_error_form(tmp_path):
    """fastmcp 路径把 SSH 失败包在来源横幅后——曾穿门被判成"分区配置残留"+
    床账 4 条垃圾 created(93 床实录);横幅后的 error 契约行必须归探测失败。"""
    outputs = {"show segment name": _SSH_DEAD, "show synconfig peer": _SSH_DEAD,
               "show sdns config file": _SSH_DEAD}
    rep = bed_check(_probe(_SSH_DEAD, outputs), CFG, root=tmp_path, host="h")
    assert rep["anchor"]["status"] == "probe_failed"
    assert rep["needs_ask"] is True
    assert rep["findings"] and all(f.get("probe_failed") for f in rep["findings"])


def test_bed_snapshot_fastmcp_banner_error_marks_failed(tmp_path):
    """快照同病:SSH 挂死通道必须 failed=True(diff 才会跳过)——曾 failed=false
    把报错行当内容,批后 diff 出垃圾"漂移"入床账(bed_ledger/10.4.127.93 实录)。"""
    from main.ist_core.compile_engine_v8.bed import bed_snapshot
    snap = bed_snapshot(lambda cmd: _SSH_DEAD)
    assert snap and all(v.get("failed") is True for v in snap.values())


def test_probe_transient_invalid_retried_not_asked(tmp_path):
    """探针瞬态失败复探消解(run18 实弹;2026-07-11 同型前科):合法 show 命令单次被
    设备回 `% Invalid input`(框架 SSH 读窗串位),复探即成功——不复探=一次瞬态就产
    「通道床态未知」假问询打断用户,而床是干净的。"""
    _INVALID = ("host=1.2.3.4  mode=show\n--- output ---\n"
                "% Invalid input: command 'show sdns config file' is invalid\n"
                "show sdns config file\n    ^")
    calls: dict = {}

    def flaky(cmd: str) -> str:
        calls[cmd] = calls.get(cmd, 0) + 1
        if "version" in cmd:
            return DEV_585
        # 首探 invalid(瞬态),复探成功(空列表:只有段落头)
        if calls[cmd] == 1:
            return _INVALID
        return ("host=1.2.3.4  mode=show\n--- output ---\n"
                "Running configuration backup files:\nAPV#")

    rep = bed_check(flaky, CFG, root=tmp_path, host="h")
    assert rep["needs_ask"] is False           # 复探成功 → 零问询
    assert not rep["findings"]                 # 既不报残留也不报探测失败
    assert rep["anchor"]["status"] == "match"


def test_probe_persistent_failure_still_reported(tmp_path):
    """持续失败(复探仍失败)如实报 probe_failed——复探不得掩盖真失败。"""
    dead = "error: SSH to 1.2.3.4 failed: connection refused"
    rep = bed_check(lambda cmd: dead, CFG, root=tmp_path, host="h")
    assert rep["needs_ask"] is True
    assert rep["findings"] and all(f.get("probe_failed") for f in rep["findings"])


def test_probe_resilient_returns_first_echo_on_double_failure():
    """两次都失败返回首次回显(复探路径的新错误不得覆盖原始诊断信息)。"""
    from main.ist_core.compile_engine_v8.bed import probe_resilient
    seq = iter(["error: first failure", "error: second different failure"])
    out = probe_resilient(lambda cmd: next(seq), "show x")
    assert out == "error: first failure"


def test_bridge_common_cause_merges_dead_device_question(tmp_path):
    """题面共因合题:同一失败签名覆盖 ≥2 路探针(含版本锚)→ 一句"疑似设备不可达",
    不再摊成「残留×3+探测未完成+版本不匹配」五段误导题(105 床实弹形态)。"""
    outputs = {"show segment name": _SSH_DEAD, "show synconfig peer": _SSH_DEAD,
               "show sdns config file": (
                   "=== dev_probe ===\ncommand: show sdns config file\n"
                   "status: error\nprobe failed: [Errno None] Unable to connect "
                   "to port 22 on 172.16.35.70")}
    rep = bed_check(_probe(_SSH_DEAD, outputs), CFG, root=tmp_path, host="h")
    import main.ist_core.compile_engine_v8.engine_tool as ET
    captured = {}

    def _fake_panel(qs):
        captured["q"] = qs[0]["question"]
        return {"decision": "停止"}

    orig = ET._panel
    ET._panel = _fake_panel
    try:
        ET._bridge({"kind": "bed_gate", "report": {
            "anchor": rep["anchor"], "findings": rep["findings"], "cleanup": {}}})
    finally:
        ET._panel = orig
    q = captured["q"]
    assert "同因失败" in q and "疑似设备不可达" in q
    assert "版本锚" in q                                  # build 锚并入同因组
    assert "仍有残留" not in q and "版本不匹配" not in q   # 两个谎报形态都不许再出现


def test_bridge_unknown_anchor_says_unknown_not_mismatch():
    """版本解析不出(探针跑通)→ 题面说"版本未知",不说"版本不匹配:设备(空)"。"""
    import main.ist_core.compile_engine_v8.engine_tool as ET
    captured = {}

    def _fake_panel(qs):
        captured["q"] = qs[0]["question"]
        return {"decision": "停止"}

    orig = ET._panel
    ET._panel = _fake_panel
    try:
        ET._bridge({"kind": "bed_gate", "report": {
            "anchor": {"status": "unknown", "device": "", "config": CFG},
            "findings": [{"kind": "build_anchor",
                          "detail": {"status": "unknown", "device": "", "config": CFG}}],
            "cleanup": {}}})
    finally:
        ET._panel = orig
    assert "版本未知" in captured["q"] and "版本不匹配" not in captured["q"]


def test_bridge_mirror_sync_is_not_residue_wording():
    """mirror_sync 是引擎内部发现——题面按其 detail 原文呈报,不叫"残留"。"""
    import main.ist_core.compile_engine_v8.engine_tool as ET
    captured = {}

    def _fake_panel(qs):
        captured["q"] = qs[0]["question"]
        return {"decision": "停止"}

    orig = ET._panel
    ET._panel = _fake_panel
    try:
        ET._bridge({"kind": "bed_gate", "report": {
            "anchor": {"status": "match", "device": "InfosecOS Beta.APV-HG-K.10.5.0.585"},
            "findings": [{"kind": "mirror_sync", "probe_failed": False,
                          "detail": "盘上框架镜像与真机框架不一致(文件:lib/test_xlsx.py)"
                                    "——请确认框架是否升级并更新镜像"}],
            "cleanup": {}}})
    finally:
        ET._panel = orig
    assert "盘上框架镜像与真机框架不一致" in captured["q"]
    assert "残留" not in captured["q"]


def test_mirror_sync_finding_never_enters_cleanup(tmp_path, monkeypatch):
    """mirror_sync 不是设备残留——不得进 bed_cleanup(否则虚占"引擎不认识"计数)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    from main.ist_core.compile_engine_v8 import _shared as sh
    outputs = {
        "show segment name": "host=1.2.3.4  mode=show\n--- output ---\nAPV#",
        "show synconfig peer": "host=1.2.3.4  mode=show\n--- output ---\nAPV#",
        "show sdns config file": "host=1.2.3.4  mode=show\n--- output ---\nAPV#",
    }
    monkeypatch.setattr(N, "_probe_fn", _probe(DEV_585, outputs))
    import main.ist_core.compile_engine_v8.mirror_anchor as MA
    monkeypatch.setattr(MA, "check_sync",
                        lambda _exec: {"status": "mismatch", "diffs": ["lib/test_xlsx.py"]})
    monkeypatch.setattr(N.B, "bed_cleanup",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("cleanup called")))
    monkeypatch.setattr(sh, "outputs_root", lambda: tmp_path / "outputs")
    monkeypatch.setattr(sh, "facts_path", lambda s: tmp_path / "facts.jsonl")
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": []})
    monkeypatch.setattr(N, "interrupt", lambda p: {"decision": "停止"})
    out = N.bed_gate({"out_name": "b1"})
    assert out["phase_status"] == "bed_blocked"   # 到达问询;cleanup 从未被调


def test_probe_failed_findings_never_enter_cleanup(tmp_path, monkeypatch):
    """probe_failed 项不进清理(没有清理对象;bed_gate residue 过滤)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    from main.ist_core.compile_engine_v8 import _shared as sh
    import main.ist_core.compile_engine_v8.mirror_anchor as MA
    outputs = {
        "show segment name": ("host=1.2.3.4  mode=show\n--- output ---\n"
                              "% Invalid input: nope\nshow segment name\n    ^"),
        "show synconfig peer": "host=1.2.3.4  mode=show\n--- output ---\nAPV#",
        "show sdns config file": "host=1.2.3.4  mode=show\n--- output ---\nAPV#",
    }
    monkeypatch.setattr(N, "_probe_fn", _probe(DEV_585, outputs))
    # 单测不真 SSH 跳板机(曾真连 103 并写 .sync_anchor.json——网络依赖+副作用)
    monkeypatch.setattr(MA, "check_sync", lambda _exec: {"status": "unknown",
                                                         "reason": "stubbed"})
    monkeypatch.setattr(N.B, "bed_cleanup",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("cleanup called")))
    monkeypatch.setattr(sh, "outputs_root", lambda: tmp_path / "outputs")
    monkeypatch.setattr(sh, "facts_path", lambda s: tmp_path / "facts.jsonl")
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": []})
    monkeypatch.setattr(N, "interrupt", lambda p: {"decision": "停止"})
    out = N.bed_gate({"out_name": "b1"})
    assert out["phase_status"] == "bed_blocked"   # 用户答停止;cleanup 从未被调


# ── C1 维护日志通道((38) 写者全集;run12 五次修床误判形态回放) ─────────────────

def _log_maint(root, host="h"):
    """run12 真实修床命令面:拆 vlan/bond+恢复 port2 基线。"""
    from main.ist_core.compile_engine_v8.bed import bed_record
    bed_record(root, host, "maintenance", "manual", "maint:t1",
               payload={"who": "jiangyongze", "why": "run12 拆床",
                        "commands": ["no vlan vlan100", "no bond interface bond1",
                                     "ip address port2 172.16.34.70 255.255.255.0"]})


def test_c1_maintenance_tokens_roundtrip(tmp_path):
    from main.ist_core.compile_engine_v8.bed import maintenance_tokens
    _log_maint(tmp_path)
    toks = maintenance_tokens(tmp_path, "h")
    assert {"vlan100", "bond1", "port2", "172.16.34.70"} <= toks
    assert "255.255.255.0" not in toks                    # 掩码不算身份
    assert maintenance_tokens(tmp_path, "other-host") == set()


def test_c1_maintained_residue_explained_no_ask(tmp_path):
    """维护写 ≠ 非己方残留:登记后 bed_check 不再为它弹问询(finding 保留+标注)。"""
    from main.ist_core.compile_engine_v8.bed import bed_record
    bed_record(tmp_path, "h", "maintenance", "manual", "maint:t2",
               payload={"commands": ["no segment maint_seg1"]})
    extra = {"show segment name": "segment: maint_seg1  status: active"}
    rep = bed_check(_probe(DEV_585, extra), CFG, root=tmp_path, host="h")
    f = next(f for f in rep["findings"] if f["kind"] == "segments")
    assert f.get("maintenance_explained") is True         # 如实标注,非静默丢弃
    assert rep["needs_ask"] is False


def test_c1_unlogged_residue_still_asks(tmp_path):
    """没登记就没解释:同形态残留照旧走非己方 ask(修完必登记的纪律有牙齿)。"""
    extra = {"show segment name": "segment: maint_seg1  status: active"}
    rep = bed_check(_probe(DEV_585, extra), CFG, root=tmp_path, host="h")
    assert rep["needs_ask"] is True


def test_c1_partial_overlap_not_explained(tmp_path):
    """finding 里混有维护面之外的实体 → 不解释(全覆盖判据,宽松侧防漏报)。"""
    from main.ist_core.compile_engine_v8.bed import bed_record
    bed_record(tmp_path, "h", "maintenance", "manual", "maint:t3",
               payload={"commands": ["no segment maint_seg1"]})
    extra = {"show segment name": "segment: maint_seg1\nsegment: rogue_seg9"}
    rep = bed_check(_probe(DEV_585, extra), CFG, root=tmp_path, host="h")
    f = next(f for f in rep["findings"] if f["kind"] == "segments")
    assert not f.get("maintenance_explained")
    assert rep["needs_ask"] is True


def test_c1_split_maintained_closing_diff(tmp_path):
    """closing 批后收敛:port2 恢复行从 foreign 分流为 maintained(run12 误报封堵)。"""
    from main.ist_core.compile_engine_v8.bed import maintenance_tokens, split_maintained
    _log_maint(tmp_path)
    maint = maintenance_tokens(tmp_path, "h")
    foreign = {"interface_addresses": {
        "added": ["port2 172.16.34.70 255.255.255.0"],
        "removed": ["vlan100 172.16.34.70 255.255.255.0",
                    "colleague0 10.9.9.9 255.255.255.0"]}}
    left, maintained = split_maintained(foreign, maint)
    assert maintained["interface_addresses"]["added"] == ["port2 172.16.34.70 255.255.255.0"]
    assert "vlan100 172.16.34.70 255.255.255.0" in maintained["interface_addresses"]["removed"]
    assert left["interface_addresses"]["removed"] == ["colleague0 10.9.9.9 255.255.255.0"]
    # 无维护记录 → 原样返回,零行为变化
    l2, m2 = split_maintained(foreign, set())
    assert l2 == foreign and m2 == {}


def test_c1_digit_free_residue_not_whitewashed(tmp_path):
    """redline 抓漏回归:纯字母实体名产零 token,聚合判定对它失明——按行判定后,
    混入 digit-free 真残留(rogue)的 finding 必不解释、照旧弹 ask。"""
    from main.ist_core.compile_engine_v8.bed import bed_record
    bed_record(tmp_path, "h", "maintenance", "manual", "maint:t4",
               payload={"commands": ["no segment maint_seg1"]})
    extra = {"show segment name": "segment: maint_seg1\nsegment: rogue"}
    rep = bed_check(_probe(DEV_585, extra), CFG, root=tmp_path, host="h")
    f = next(f for f in rep["findings"] if f["kind"] == "segments")
    assert not f.get("maintenance_explained")
    assert rep["needs_ask"] is True


def test_cleanup_recheck_preserves_mirror_and_closure_H10(tmp_path, monkeypatch):
    """H-10:清理复检不得蒸发 mirror_sync/bed_closure_failed——旧整体重赋值会让用户看不到。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    from main.ist_core.compile_engine_v8 import _shared as sh
    from main.ist_core.compile_engine_v8 import facts as F
    import main.ist_core.compile_engine_v8.mirror_anchor as MA

    facts_file = tmp_path / "facts.jsonl"
    facts_file.write_text("", encoding="utf-8")
    F.append_facts(facts_file, [
        {"ev": "bed_closure_failed", "aid": "", "host": "h", "run_id": "bc:h10:1",
         "reason": "crashed"}])
    calls = {"n": 0}
    residue = [{"kind": "segments", "detail": "leftover", "probe_failed": False}]

    def fake_check(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"host": "h", "probes": {}, "findings": list(residue),
                    "needs_ask": True, "anchor": {"status": "match", "device": "x"},
                    "ours_unrestored": []}
        return {"host": "h", "probes": {}, "findings": [], "needs_ask": False,
                "anchor": {"status": "match", "device": "x"}, "ours_unrestored": []}

    monkeypatch.setattr(N.B, "bed_check", fake_check)
    monkeypatch.setattr(N.B, "bed_unrestored", lambda *a, **k: [])
    monkeypatch.setattr(N.B, "bed_snapshot", lambda fn: {})
    monkeypatch.setattr(N.B, "bed_cleanup",
                        lambda *a, **k: {"cleaned": [{"kind": "segments"}],
                                         "failed": [], "skipped": []})
    monkeypatch.setattr(MA, "check_sync",
                        lambda _e: {"status": "mismatch", "diffs": ["lib/x.py"]})
    monkeypatch.setattr(sh, "outputs_root", lambda: tmp_path / "outputs")
    monkeypatch.setattr(sh, "facts_path", lambda s: facts_file)
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": []})
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "emit", lambda *a, **k: None)
    monkeypatch.setattr(sh, "counts_update", lambda *a, **k: {})
    captured = {}
    monkeypatch.setattr(N, "interrupt",
                        lambda p: captured.update(p) or {"decision": "继续"})
    out = N.bed_gate({"out_name": "b1"})
    assert out["phase_status"] == "ok"
    assert calls["n"] == 2  # 初检 + 复检
    kinds = [f.get("kind") for f in (captured.get("report") or {}).get("findings", [])]
    assert "mirror_sync" in kinds
    assert "bed_closure_failed" in kinds
    fs = F.load_facts(facts_file)
    assert any(f.get("question_id") == "bedclosure:bc:h10:1" for f in fs
               if f.get("ev") == "decision")


def test_foreign_asks_even_when_ours_nonempty_H13(tmp_path):
    """H-13:ours 恒非空(snapshot_only 留账)不得关掉 foreign 残留的 needs_ask。"""
    from main.ist_core.compile_engine_v8.bed import snapshot_only_channels
    so = sorted(snapshot_only_channels())[0]
    bed_record(tmp_path, "h", "created", so, "hist:so1",
               payload={"added": ["port9 1.1.1.1 255.255.255.0"], "removed": [],
                        "commands": []})
    extra = {"show segment name": "segment: rogue_seg  status: active"}
    rep = bed_check(_probe(DEV_585, extra), CFG, root=tmp_path, host="h")
    assert rep["ours_unrestored"], "ours 应非空(留账未复原)"
    assert any(f.get("kind") == "segments" for f in rep["findings"])
    assert rep["needs_ask"] is True


def test_llm_restore_reprobe_rejects_unclean_H14(tmp_path, monkeypatch):
    """H-14:LLM 恢复执行 echo 无错但目标 added 行仍在 → 不得标 restored,进 stuck 问询。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    from main.ist_core.compile_engine_v8 import _shared as sh
    import main.ist_core.compile_engine_v8.mirror_anchor as MA

    facts_file = tmp_path / "facts.jsonl"
    facts_file.write_text("", encoding="utf-8")
    # 己方未复原:segments 账,无预存 commands → 走 LLM 后备
    bed_record(tmp_path, "h", "created", "segments", "seg:rogue",
               batch="b1",
               payload={"added": ["segment: rogue_seg  status: active"],
                        "removed": [], "commands": []})
    snap_lines = {"segments": {"lines": ["segment: rogue_seg  status: active"]}}
    monkeypatch.setattr(N.B, "bed_unrestored",
                        lambda *a, **k: [{
                            "kind": "segments", "id": "seg:rogue",
                            "payload": {"added": ["segment: rogue_seg  status: active"],
                                        "removed": [], "commands": []}}])
    monkeypatch.setattr(N.B, "restore_via_llm",
                        lambda d, fn: ["no segment rogue_seg"])
    monkeypatch.setattr(N.B, "entity_gate",
                        lambda cmds, d: (list(cmds), []))
    monkeypatch.setattr(N, "_exec_fn", lambda c: "status: success")
    monkeypatch.setattr(N.B, "_probe_failed", lambda t: False)
    # 复探快照:added 行仍在
    monkeypatch.setattr(N.B, "bed_snapshot", lambda fn: snap_lines)
    monkeypatch.setattr(N.B, "bed_check", lambda *a, **k: {
        "host": "h", "probes": {}, "findings": [], "needs_ask": False,
        "anchor": {"status": "match", "device": "x"}, "ours_unrestored": []})
    monkeypatch.setattr(MA, "check_sync", lambda _e: {"status": "match"})
    monkeypatch.setattr(sh, "outputs_root", lambda: tmp_path / "outputs")
    monkeypatch.setattr(sh, "facts_path", lambda s: facts_file)
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": []})
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "emit", lambda *a, **k: None)
    monkeypatch.setattr(sh, "counts_update", lambda *a, **k: {})
    captured = {}
    monkeypatch.setattr(N, "interrupt",
                        lambda p: captured.update(p) or {"decision": "继续"})
    recorded = []
    monkeypatch.setattr(N.B, "bed_record",
                        lambda *a, **k: recorded.append(k.get("ev") or a[2] if len(a) > 2 else k))
    # bed_record signature: (root, host, ev, kind, ident, ...)
    def spy_record(root, host, ev, kind, ident, **kw):
        recorded.append(ev)
    monkeypatch.setattr(N.B, "bed_record", spy_record)
    N.bed_gate({"out_name": "b1"})
    assert "restored" not in recorded
    kinds = [f.get("kind") for f in (captured.get("report") or {}).get("findings", [])]
    assert any(f.get("ledger_stuck") for f in (captured.get("report") or {}).get("findings", []))
