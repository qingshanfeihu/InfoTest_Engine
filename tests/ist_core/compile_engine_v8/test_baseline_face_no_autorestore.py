"""平台基线面(snapshot_only)绝不自动恢复(run18 实弹,最高危 bug)。

run18@79 实录:批前 `show ip address` 探针被 SSH 读窗串位截断成 1 行(status:success
故未判 failed,probe_resilient 救不了截断),批后完整 6 个接口地址被误判成「本批漂移」,
own_writes 因案面配过 port2/port3 归为己方 → restore_via_llm 生成
`no ip address port2 172.16.34.70`(删管理 IP)→ entity_gate 放行(实体确在错误的
diff 里)→ 执行。四道防线因源头 diff 错而全失效,设备靠框架 IP 恢复契约侥幸存活。

根治=平台基线面(接口地址等 test_env 拓扑管理的状态面)的漂移永不驱动自动恢复命令,
只呈报/入账。
"""
from __future__ import annotations

from main.ist_core.compile_engine_v8 import bed as B


def test_snapshot_only_channels_includes_interface_addresses():
    so = B.snapshot_only_channels()
    assert "interface_addresses" in so   # grammar bed_probes 标了 snapshot_only


def test_restorable_diff_excludes_baseline_face():
    """run18 精确回放:接口地址漂移 → observe_only(不进 restorable)。"""
    diff = {
        "interface_addresses": {
            "added": ['ip address "port2" 172.16.34.70 255.255.255.0',
                      'ip address "port3" 172.16.32.70 255.255.255.0'],
            "removed": []},
        "segments": {"added": ["seg-real-residue"], "removed": []},
    }
    restorable, observe_only = B.restorable_diff(diff)
    assert "interface_addresses" in observe_only     # 基线面只呈报
    assert "interface_addresses" not in restorable
    assert "segments" in restorable                  # 真残留仍走恢复
    assert "segments" not in observe_only


def test_baseline_face_with_removed_still_restorable():
    """run9 vlan100 不受伤:基线面若有 removed(批前快照见证消失=完整可信),照常恢复。
    这是方案 C 的关键——区分 run18(纯 added,截断)与 run9(有 removed,真替换)。"""
    diff = {"interface_addresses": {
        "added": ['ip address "vlan100" 172.16.34.70 255.255.255.0'],
        "removed": ['ip address "port2" 172.16.34.70 255.255.255.0']}}
    restorable, observe_only = B.restorable_diff(diff)
    assert "interface_addresses" in restorable       # 有 removed → 可恢复
    assert not observe_only


def test_baseline_drift_never_reaches_restore_via_llm(monkeypatch):
    """端到端:只有 interface_addresses 漂移时,restore_via_llm 收到空 own(零删除命令)。"""
    diff = {"interface_addresses": {
        "added": ['ip address "port2" 172.16.34.70 255.255.255.0'], "removed": []}}
    restorable, _ = B.restorable_diff(diff)
    # 本批命令面确实碰过 port2(测试配置)——但 restorable 已空,own_writes 无输入
    own, foreign = B.own_writes(restorable, 'slb config on port2 172.16.34.70')
    assert own == {}                                 # 零己方漂移 → 零恢复命令
    called = {"n": 0}

    def _spy_llm(sys_p, user):
        called["n"] += 1
        return "[]"

    if own:                                           # 防御:own 空则根本不该调 LLM
        B.restore_via_llm(own, _spy_llm)
    assert called["n"] == 0


def test_entity_gate_still_guards_real_residue():
    """真残留通道的恢复仍受 entity_gate 约束(基线面剥离不削弱其他防线)。"""
    diff = {"segments": {"added": ["segment vlan100 real"], "removed": []}}
    restorable, observe_only = B.restorable_diff(diff)
    assert restorable and not observe_only
    # 无实体 token 的全局命令仍被 entity_gate 拒(回归 R-7)
    ok, rejected = B.entity_gate(["clear all"], restorable)
    assert ok == [] and rejected == ["clear all"]
