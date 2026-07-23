"""X11 床账接线验收(THEORY 2.7.7 (25)(26)+R4):快照 diff→己方交叉验证→机械逆放
→残余入账→下批接力。金标准形态=run9 vlan100 跨批污染(233 建 vlan 未还原)。
"""
from __future__ import annotations

import json

import pytest

from main.ist_core.compile_engine_v8 import bed as B

H = "10.4.127.93"

BEFORE = {"interface_addresses": {"failed": False, "lines": [
    'ip address "port1" 172.16.35.70 255.255.255.0',
    'ip address "port2" 172.16.34.70 255.255.255.0',
]}}
AFTER_POLLUTED = {"interface_addresses": {"failed": False, "lines": [
    'ip address "port1" 172.16.35.70 255.255.255.0',
    'ip address "vlan100" 172.16.34.70 255.255.255.0',
]}}
# run9 实录形态:233 卷面执行过的命令面(sends command 行)
CORPUS = ("172.16.35.70 - sends command in config: no ip address port2 4\n"
          "172.16.35.70 - sends command in config: vlan port2 vlan100 100\n"
          "172.16.35.70 - sends command in config: ip address vlan100 172.16.34.70 24\n")


def test_diff_detects_233_shape():
    d = B.bed_diff(BEFORE, AFTER_POLLUTED)
    assert d["interface_addresses"]["added"] == ['ip address "vlan100" 172.16.34.70 255.255.255.0']
    assert d["interface_addresses"]["removed"] == ['ip address "port2" 172.16.34.70 255.255.255.0']


def test_diff_skips_failed_probe_channels():
    """任一侧探测失败=比不出=未知,不误报(R4-G2 诚实边界;探针失败≠残留的姊妹)。"""
    bad_after = {"interface_addresses": {"failed": True, "lines": []}}
    assert B.bed_diff(BEFORE, bad_after) == {}


_PAIRS = {"ip address": {"no": "no ip address"}}   # inverse_forms 最小假体(head→no 逆元)

# LLM 后备/entity_gate 的输入形态(own_writes_by_command 产出的己方 diff 子集)
_OWN_DIFF = {"interface_addresses": {
    "added": ['ip address "vlan100" 172.16.34.70 255.255.255.0'],
    "removed": ['ip address "port2" 172.16.34.70 255.255.255.0']}}


def test_own_writes_by_command_cross_validation():
    """S4 兑现②(旧 own_writes 判据已删):diff 行「己方」iff 案面 config 命令创建过
    该对象;removed 基线行案面无创建命令(只主动 no 过)→ foreign 不猜重建;
    命令面空(别人批的漂移)→ 全 foreign 只报不动。"""
    d = B.bed_diff(BEFORE, AFTER_POLLUTED)
    cmds = B.parse_config_commands(CORPUS)
    own, foreign = B.own_writes_by_command(d, cmds, _PAIRS)
    assert own["interface_addresses"]["added"] == [
        'ip address "vlan100" 172.16.34.70 255.255.255.0']   # 案面创建过 → 己方
    assert foreign["interface_addresses"]["removed"] == [
        'ip address "port2" 172.16.34.70 255.255.255.0']     # 案面只 no 过 → 不重建基线
    own2, foreign2 = B.own_writes_by_command(d, [], _PAIRS)
    assert not own2 and "interface_addresses" in foreign2


def test_restore_via_llm_generation_open_gates_closed():
    """行动论 (22) 实现形态:恢复命令生成归 LLM(零模板零场景枚举——vlan/路由/ACL
    同一条路);机械双门=实体越界门+执行验证。"""
    def fake_llm(sys_p, user_p):
        assert "vlan100" in user_p                    # diff 原文喂给 LLM
        return '["no ip address vlan100 4", "ip address port2 172.16.34.70 24"]'

    cmds = B.restore_via_llm(_OWN_DIFF, fake_llm)
    ok, rejected = B.entity_gate(cmds, _OWN_DIFF)
    assert ok == ["no ip address vlan100 4", "ip address port2 172.16.34.70 24"]
    assert rejected == []


def test_entity_gate_blocks_out_of_scope_commands():
    """越界门:LLM 命令只许碰 diff 内实体——碰别的接口/IP 一律拒(INV-9 的机械面)。"""
    ok, rejected = B.entity_gate(
        ["no ip address vlan100 4", "no ip address port3 4", "clear slb all"], _OWN_DIFF)
    assert ok == ["no ip address vlan100 4"]
    assert "no ip address port3 4" in rejected        # port3 不在 diff 实体集
    assert "clear slb all" in rejected                 # R-7:无实体的全局命令一律拒


def test_restore_via_llm_unparseable_is_conservative_empty():
    cmds = B.restore_via_llm({"x": {"added": ["y 1"], "removed": []}},
                             lambda s, u: "I think you should…(prose, no JSON)")
    assert cmds == []


def test_ledger_roundtrip_with_payload(tmp_path):
    B.bed_record(tmp_path, H, "created", "interface_addresses", "b1:interface_addresses",
                 batch="b1", payload={"commands": ["no ip address vlan100 4"]})
    items = B.bed_unrestored(tmp_path, H)
    assert len(items) == 1
    assert items[0]["payload"]["commands"] == ["no ip address vlan100 4"]
    B.bed_record(tmp_path, H, "restored", "interface_addresses", "b1:interface_addresses",
                 batch="b2")
    assert B.bed_unrestored(tmp_path, H) == []


def test_snapshot_only_probe_not_a_residue(tmp_path):
    """interface_addresses 合法地址恒在:不得进 bed_check 残留判定(恒弹问询=幽灵回归)。"""
    outputs = {
        "show ip address": "host=1.2.3.4  mode=show\n--- output ---\n"
                           'ip address "port1" 172.16.35.70 255.255.255.0\nAPV#',
        "show segment name": "host=1.2.3.4  mode=show\n--- output ---\nAPV#",
        "show synconfig peer": "host=1.2.3.4  mode=show\n--- output ---\nAPV#",
        "show sdns config file": "host=1.2.3.4  mode=show\n--- output ---\nAPV#",
    }

    def probe(cmd):
        if "version" in cmd:
            return " Software Version : InfosecOS Beta.APV-HG-K.10.5.0.585"
        return outputs.get(cmd, "(no output)")

    rep = B.bed_check(probe, "InfosecOS_Beta_APV_HG_K_10_5_0_568",
                      root=tmp_path, host=H)
    assert rep["findings"] == [] and rep["needs_ask"] is False
    snap = B.bed_snapshot(probe)
    assert snap["interface_addresses"]["lines"]      # 但快照收录它


# ── 节点集成:closing 收敛 + bed_gate 接力 ────────────────────────────────────


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    from main.ist_core.compile_engine_v8 import _shared as sh
    from main.ist_core.compile_engine_v8 import nodes as N
    outputs = tmp_path / "outputs"
    mdir = outputs / "b1"
    mdir.mkdir(parents=True)
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(sh, "emit_tick", lambda *a, **k: None)
    monkeypatch.setattr(sh, "emit_summary", lambda *a, **k: None)
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": []})
    monkeypatch.setattr(sh, "facts_path", lambda s: mdir / "facts.jsonl")
    monkeypatch.setattr(sh, "case_rows", lambda aid: [])
    import main.ist_core.compile_engine_v8.uncertain as U8
    monkeypatch.setattr(U8, "_ingest_uncertain_observations", lambda led: None)
    return {"tmp": tmp_path, "mdir": mdir, "N": N, "sh": sh, "mp": monkeypatch}


def test_closing_converges_own_drift_and_ledgers_residue(rig):
    """闭环上半:批后 diff→己方逆放;逆放不净的残余入床账(payload 带恢复命令)。"""
    N, mp, tmp = rig["N"], rig["mp"], rig["tmp"]
    (rig["mdir"] / "bed_before.json").write_text(json.dumps(BEFORE), encoding="utf-8")
    lr = rig["mdir"] / "last_run.json"
    lr.write_text(json.dumps([{"autoid": "a", "device_context": CORPUS}]), encoding="utf-8")
    executed: list[str] = []
    # 设备顽固:恢复命令接受但状态不变(残余应入账,payload 带 diff 供下批 LLM 再生成)
    mp.setattr(N, "_probe_fn", lambda c: json.dumps(AFTER_POLLUTED) and _fake_show(c))
    mp.setattr(N, "_exec_fn", lambda c: executed.append(c) or "status: success")
    mp.setattr(N, "_bed_llm_fn",
               lambda s, u: '["no ip address vlan100 4", "ip address port2 172.16.34.70 24"]')
    state = {"out_name": "b1", "bed_host": H,
             "last_run_ref": str(lr.relative_to(tmp))}
    out = N.closing(state)
    assert out["phase_status"] == "done"
    # S4 兑现②(#76):vlan100 有案面创建命令 `ip address vlan100 172.16.34.70 24`,
    # 走机械逆放(negation of the create cmd,作用域=原命令全文),不再是 LLM 猜的
    # `no ip address vlan100 4`。port2 removed 无案面创建命令(案面只 `no ip address
    # port2`——案主动删的基线),归 foreign 只报不动:引擎不猜着重建基线(交框架 IP
    # 恢复契约),这正是 run18 根因修复的对称面——恢复只碰案面真创建过的对象。
    assert "no ip address vlan100 172.16.34.70 24" in executed        # 己方漂移机械逆放
    assert not any(c.startswith("ip address port2") for c in executed)  # 不猜重建基线
    items = B.bed_unrestored(tmp, H)
    assert items and items[0]["kind"] == "interface_addresses"
    assert items[0]["payload"]["added"]               # diff 随账(下批接力再生成)
    rep = json.loads((rig["mdir"] / "engine_report.json").read_text(encoding="utf-8"))
    assert "床账" in rep["bed"]["closure"] or "恢复" in rep["bed"]["closure"]


def _fake_show(cmd):
    if "ip address" in cmd:
        return ("--- output ---\n"
                'ip address "port1" 172.16.35.70 255.255.255.0\n'
                'ip address "vlan100" 172.16.34.70 255.255.255.0\nAPV#')
    return "--- output ---\nAPV#"


def test_bed_gate_relay_restores_from_ledger(rig):
    """闭环下半:下批 bed_gate 读账→机械逆放(零问询,(26))→restored 配平。"""
    N, mp, tmp = rig["N"], rig["mp"], rig["tmp"]
    B.bed_record(tmp, H, "created", "interface_addresses", "b0:interface_addresses",
                 batch="b0", payload={"commands": ["no ip address vlan100 4",
                                                   "ip address port2 172.16.34.70 24"]})
    executed: list[str] = []
    mp.setattr(N, "_exec_fn", lambda c: executed.append(c) or "status: success")
    mp.setattr(N, "_bed_llm_fn",
               lambda s, u: (_ for _ in ()).throw(AssertionError("LLM called for ledgered cmds!")))
    mp.setattr(N, "_probe_fn", lambda c: (
        " Software Version : InfosecOS Beta.APV-HG-K.10.5.0.585" if "version" in c
        else "--- output ---\nAPV#"))
    mp.setattr(N, "interrupt", lambda p: (_ for _ in ()).throw(AssertionError("asked!")))
    import main.case_compiler.config as CFG

    class _J:  # 最小 config 假体
        host = H

    class _C:
        jumphost = _J()
        build = "InfosecOS_Beta_APV_HG_K_10_5_0_568"

    mp.setattr(CFG, "get_config", lambda: _C())
    out = N.bed_gate({"out_name": "b1"})
    assert out["phase_status"] == "ok"                 # 零问询直达放行
    assert executed == ["no ip address vlan100 4", "ip address port2 172.16.34.70 24"]
    assert B.bed_unrestored(tmp, H) == []              # 账配平


def test_bed_gate_stuck_ledger_escalates_to_ask(rig):
    """R-9:账内项恢复穷尽仍未成 → 并入呈报(needs_ask),绝不静默悬账。
    用 segments(非 snapshot_only 残留面)——interface_addresses 纯 added 已由 run18
    修复改为「跳过不自动删」,不再走恢复→stuck 路径(见 test_baseline_face_*)。"""
    N, mp, tmp = rig["N"], rig["mp"], rig["tmp"]
    B.bed_record(tmp, H, "created", "segments", "b0:segments",
                 batch="b0", payload={"commands": [], "added": ["segment x 1"], "removed": []})
    mp.setattr(N, "_bed_llm_fn", lambda s, u: "[]")     # 生成失败(空)
    mp.setattr(N, "_exec_fn", lambda c: "status: success")
    mp.setattr(N, "_probe_fn", lambda c: (
        " Software Version : InfosecOS Beta.APV-HG-K.10.5.0.585" if "version" in c
        else "--- output ---\nAPV#"))
    asked = {}
    mp.setattr(N, "interrupt", lambda p: asked.update(p) or {"decision": "停止"})
    import main.case_compiler.config as CFG

    class _J:
        host = H

    class _C:
        jumphost = _J()
        build = "InfosecOS_Beta_APV_HG_K_10_5_0_568"

    mp.setattr(CFG, "get_config", lambda: _C())
    out = N.bed_gate({"out_name": "b1"})
    assert out["phase_status"] == "bed_blocked"        # 用户答停止
    finds = asked.get("report", {}).get("findings") or []
    assert any(f.get("ledger_stuck") for f in finds)   # 悬账进了呈报
    assert B.bed_unrestored(tmp, H)                    # 账仍在(留待人工/下批)


def test_evidence_suspect_gate_detects_misattribution(rig, monkeypatch):
    """I2 归属一致性门(#67 防御侧):附件 dig 目标与卷面不相交=疑似错位;
    相交/单侧空=不误报(run9 248 拿到 233 输出的金标准形态)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_load_case_rows", lambda aid: [
        {"E": "test_env", "F": "routera", "G": "dig @172.16.34.70 autotest.com A +short"}])
    rec_bad = {"device_context": "; <<>> DiG 9.16.1 <<>> @172.16.34.71 autotest.com A +short\n"
                                 ";; connection timed out"}
    s = N._evidence_suspect(rec_bad, "a1")
    assert s and s["evidence_targets"] == ["172.16.34.71"]
    assert s["sheet_targets"] == ["172.16.34.70"]
    rec_ok = {"device_context": "; <<>> DiG 9.16.1 <<>> @172.16.34.70 autotest.com A +short"}
    assert N._evidence_suspect(rec_ok, "a1") is None          # 相交=正常
    assert N._evidence_suspect({"device_context": "no dig here"}, "a1") is None  # 单侧空


def test_evidence_suspect_at_host_non_dig_m21(rig, monkeypatch):
    """M-21:@host/IP 通用形态——非 dig 取证错位也要检出。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_load_case_rows", lambda aid: [
        {"E": "test_env", "F": "routera", "G": "curl @172.16.34.70/status"}])
    rec_bad = {"device_context": "client hit @172.16.34.71/status\nHTTP/1.1 200"}
    s = N._evidence_suspect(rec_bad, "a1")
    assert s and "172.16.34.71" in s["evidence_targets"]
    assert "172.16.34.70" in s["sheet_targets"]


def test_heartbeat_begin_case_semantic_line():
    """#66:进度序号首选框架语义行 begin case(路径行被排除后仍有信号)。"""
    import re
    autoids = ["203601753067655154", "203601753067655173"]
    log = ("cmd: pytest smoke_test/sdns/ist_staging_sdns/203601753067655154/test_xlsx.py\n"
           "#######   begin case: 203601753067655173\nsome output")
    begins = re.findall(r"begin case:\s*(\d{18})", log)
    assert begins and autoids.index(begins[-1]) + 1 == 2      # 第2/2,不再恒0


# ── B-3:closing 床恢复重 diff 的己方过滤(foreign 不入己床账)+ verified 谎报 ──────

_B3_BEFORE = {"segments": {"failed": False, "lines": ["segment base 1"]},
              "tenant_configs": {"failed": False, "lines": ["tc base"]}}
_B3_POLLUTED = {"segments": {"failed": False,
                             "lines": ["segment base 1", "segment vlan100 2"]},
                "tenant_configs": {"failed": False,
                                   "lines": ["tc base", "tc foreign 9"]}}
_B3_RESTORED = {"segments": {"failed": False, "lines": ["segment base 1"]},
                "tenant_configs": {"failed": False,
                                   "lines": ["tc base", "tc foreign 9"]}}


def _b3_setup(rig, snaps):
    """公共夹具:案面只创建 segment vlan100 2;tc foreign 9=他人同床漂移(案面无创建命令)。"""
    N, mp, tmp = rig["N"], rig["mp"], rig["tmp"]
    (rig["mdir"] / "bed_before.json").write_text(json.dumps(_B3_BEFORE), encoding="utf-8")
    lr = rig["mdir"] / "last_run.json"
    lr.write_text(json.dumps([{"autoid": "a", "device_context":
                               "h - sends command in config: segment vlan100 2\n"}]),
                  encoding="utf-8")
    it = iter(snaps)
    mp.setattr(N.B, "bed_snapshot", lambda fn: next(it))
    mp.setattr(N.B, "_inverse_pairs", lambda: {"segment": {"no": "no segment"}})
    executed: list[str] = []
    mp.setattr(N, "_exec_fn", lambda c: executed.append(c) or "status: success")
    state = {"out_name": "b1", "bed_host": H, "last_run_ref": str(lr.relative_to(tmp))}
    return executed, state


def test_closing_foreign_drift_not_recorded_as_own_B3(rig):
    """B-3 红绿:执行恢复命令后的重拍是全量 diff,foreign(案面未创建)物理仍在设备上
    必在其中——修前 `if cmds:` 分支无己方过滤,foreign 被 bed_record 记成本引擎产物
    (下批 bed_gate 接力对无预存命令账项走 LLM 生成+自指 entity_gate → 自动删非己方
    配置,INV-9 越界);且 foreign 共存使 residual 恒非空 → verified 恒空谎报
    「复探未清零」。修后:foreign 不入账;己方清零 → verified=cmds(验证通过如实)。"""
    executed, state = _b3_setup(rig, [_B3_POLLUTED, _B3_RESTORED])
    out = rig["N"].closing(state)
    assert out["phase_status"] == "done"
    assert executed == ["no segment vlan100 2"]          # 己方机械逆放执行了
    assert B.bed_unrestored(rig["tmp"], H) == []          # foreign 未入己床账(主断言)
    rep = json.loads((rig["mdir"] / "engine_report.json").read_text(encoding="utf-8"))
    closure = rep["bed"]["closure"]
    assert "验证通过" in closure and "复探未清零" not in closure   # verified 谎报同修
    assert "非己方漂移" in closure                          # foreign 只报不动(呈报面保留)


def test_closing_own_residue_recorded_foreign_excluded_B3(rig):
    """B-3 对照(防过修):己方残余未清零时照常入账(own 过滤≠全丢);foreign 同批共存
    仍排除;verified 如实为空(己方确实未清零,不再是 foreign 引起的恒空)。"""
    executed, state = _b3_setup(rig, [_B3_POLLUTED, _B3_POLLUTED])   # 顽固:复探未清
    out = rig["N"].closing(state)
    assert out["phase_status"] == "done"
    assert executed == ["no segment vlan100 2"]
    items = B.bed_unrestored(rig["tmp"], H)
    assert [i["kind"] for i in items] == ["segments"]     # 只己方残余入账,foreign 排除
    rep = json.loads((rig["mdir"] / "engine_report.json").read_text(encoding="utf-8"))
    assert "复探未清零" in rep["bed"]["closure"]          # 己方未清→verified 如实空
