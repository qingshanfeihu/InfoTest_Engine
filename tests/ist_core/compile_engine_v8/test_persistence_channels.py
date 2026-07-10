"""持久化通道判定/排序/共存检查(数据驱动;yzg 保存族+手册取证场景固化)。"""
from __future__ import annotations

from main.ist_core.compile_engine_v8.persistence import (
    case_channels, order_volume, coexist_violations,
)


def C(aid, *g_lines, assert_g="x"):
    steps = [{"E": "APV_0", "F": "cmds_config", "G": "\n".join(g_lines)},
             {"E": "check_point", "F": "found", "G": assert_g}]
    return {"autoid": aid, "steps": steps}


def test_local_disk_family_detected_yzg_save_cases():
    c = C("a1", "sdns on", "sdns listener 172.16.34.70 53")
    c["steps"].insert(1, {"E": "APV_0", "F": "cmd_config", "G": "write file sdns_test"})
    c["steps"].insert(2, {"E": "APV_0", "F": "cmd_config", "G": "config file sdns_test"})
    assert "local_disk" in case_channels(c["steps"])


def test_peer_and_segment_families_detected():
    assert "peer_node" in case_channels(C("a2", "synconfig to unit2")["steps"])
    assert "peer_node" in case_channels(C("a3", "ha synconfig runtime on")["steps"])
    assert "segment_fs" in case_channels(C("a4", "segment name s1")["steps"])
    assert "segment_fs" in case_channels(C("a5", "no segment s1")["steps"])


def test_clean_case_hits_nothing_and_assert_lines_ignored():
    clean = C("c1", "sdns on", "sdns host name t.com", assert_g="write memory")  # 断言里写 write 不算命令
    assert case_channels(clean["steps"]) == set()


def test_order_volume_moves_drawer_cases_to_tail_preserving_order():
    cases = [C("c1", "sdns on"),
             C("d1", "write memory"),
             C("c2", "sdns listener 172.16.34.70"),
             C("d2", "config net tftp 1.1.1.1 f.cfg"),
             C("c3", "show version")]
    ordered, moved = order_volume(cases)
    assert [c["autoid"] for c in ordered] == ["c1", "c2", "c3", "d1", "d2"]
    assert moved == ["d1", "d2"]


def test_order_volume_noop_when_no_drawer_cases():
    cases = [C("c1", "sdns on"), C("c2", "show version")]
    ordered, moved = order_volume(cases)
    assert [c["autoid"] for c in ordered] == ["c1", "c2"] and moved == []


def test_coexist_check_ha_bootup_vs_config_reload():
    cases = [C("h1", "ha synconfig bootup on"),
             C("s1", "write memory"),               # 不在互斥 b 侧
             C("s2", "config memory")]              # b 侧命中
    v = coexist_violations(cases)
    assert len(v) == 1
    assert v[0]["channel"] == "ha_sync_state_x_config_reload"
    assert v[0]["side_a"] == ["h1"] and "s2" in v[0]["side_b"]


def test_coexist_clean_volume_no_violation():
    assert coexist_violations([C("c1", "sdns on"), C("s1", "config memory")]) == []
