"""S4 兑现②:bed-diff 恢复机械逆放先行(#76,run18 根因修复)。

run18 高危 bug 的根因:own_writes 旧判据「diff 行 token 在 corpus 文本任意位置出现」
把 yzg 案 `dig @172.16.34.70`(访问)误当成「案面创建了 port2」→ 归己方 → LLM 删基线。
修:己方判据升级为「案面 config 命令里有创建该对象的命令」(框架回显
`sends command in config: <cmd>`),恢复命令从该创建命令机械取 no 逆元——访问过的
基线实体在案面无创建命令,机械派生不出删除命令。
"""
from __future__ import annotations

from main.ist_core.compile_engine_v8 import bed as B

# inverse_forms 有 `ip address`→`no ip address`(Chapter2:91);pairs 从真 grammar 读
PAIRS = B._inverse_pairs()

# 案面回显:配了 vlan100 接口地址(创建),并 dig 访问了基线 172.16.34.70(非创建)
CORPUS = (
    "172.16.35.70 - sends command in config: vlan port2 vlan100 100\n"
    'APV_0 - sends command in config: ip address vlan100 172.16.34.70 24\n'
    "172.16.35.70 - executes command: dig @172.16.34.70 autotest.com A +short\n"
    "172.16.35.70 - sends command in test: dig @172.16.34.70 autotest.com A +short\n"
)


def test_parse_config_commands_only_config_channel():
    cmds = B.parse_config_commands(CORPUS)
    assert "vlan port2 vlan100 100" in cmds
    assert "ip address vlan100 172.16.34.70 24" in cmds
    # dig 走 test/executes 通道,不是 config 写,不采纳
    assert not any("dig" in c for c in cmds)


def test_run18_baseline_access_not_own():
    """run18 根因:基线 port2 172.16.34.70 只被 dig 访问(案面无 ip address port2
    创建命令)→ 判 foreign(不碰),即便旧判据会因 corpus 含该 IP 误判己方。"""
    config_cmds = B.parse_config_commands(CORPUS)
    diff = {"interface_addresses": {
        "added": ['ip address "port2" 172.16.34.70 255.255.255.0'], "removed": []}}
    own, foreign = B.own_writes_by_command(diff, config_cmds, PAIRS)
    assert own == {}                                     # 案面没创建 port2 → 非己方
    assert "interface_addresses" in foreign
    # 机械逆放也不生成任何删除命令
    cmds, residual = B.restore_mechanical(diff, config_cmds, PAIRS)
    assert cmds == []
    assert not any("no ip address" in c for c in cmds)


def test_run9_created_object_mechanically_reverted():
    """run9:案面 `ip address vlan100 …` 创建了 vlan100 → 己方 → 机械逆放 no 逆元
    (作用域=原命令全文,天然不越界),零 LLM。"""
    config_cmds = B.parse_config_commands(CORPUS)
    diff = {"interface_addresses": {
        "added": ['ip address "vlan100" 172.16.34.70 255.255.255.0'], "removed": []}}
    own, foreign = B.own_writes_by_command(diff, config_cmds, PAIRS)
    assert "interface_addresses" in own                  # 案面创建过 → 己方
    cmds, residual = B.restore_mechanical(own, config_cmds, PAIRS)
    assert cmds == ["no ip address vlan100 172.16.34.70 24"]   # negation of the create cmd
    assert residual == {}


def test_removed_object_replays_create_command():
    """removed(对象消失)→ 重放案面创建命令(重建)。"""
    config_cmds = B.parse_config_commands(CORPUS)
    diff = {"interface_addresses": {
        "added": [], "removed": ['ip address "vlan100" 172.16.34.70 255.255.255.0']}}
    own, _ = B.own_writes_by_command(diff, config_cmds, PAIRS)
    cmds, residual = B.restore_mechanical(own, config_cmds, PAIRS)
    assert cmds == ["ip address vlan100 172.16.34.70 24"]       # 重放原命令
    assert residual == {}


def test_no_inverse_only_clear_falls_to_residual():
    """只有 clear 逆元(no 为 null)的 head 不机械逆放(clear 是聚合复位,会误伤旁邻)
    → 残余走 LLM 后备。用一个 no=null 的构造模拟。"""
    pairs = {"foo bar": {"no": None, "clear": "clear foo bar"}}
    config_cmds = ["foo bar obj7 1.2.3.4"]
    diff = {"seg": {"added": ["foo bar obj7 1.2.3.4"], "removed": []}}
    own, _ = B.own_writes_by_command(diff, config_cmds, pairs)
    assert "seg" in own                                  # 有创建命令 → 己方
    cmds, residual = B.restore_mechanical(own, config_cmds, pairs)
    assert cmds == []                                    # no 逆元缺失 → 不机械逆放
    assert "seg" in residual                             # 残余走 LLM 后备


def test_empty_pairs_conservative_all_foreign():
    """inverse_forms 读失败(pairs 空)→ 全归 foreign(保守:宁可不恢复也不误删)。"""
    diff = {"seg": {"added": ["ip address vlan100 1.2.3.4"], "removed": []}}
    own, foreign = B.own_writes_by_command(diff, ["ip address vlan100 1.2.3.4"], {})
    assert own == {} and "seg" in foreign
