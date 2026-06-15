"""env_facts 可达性投影 + emit 校验门 + ssh 校验复用 的单测。

验证白名单投影(非死字典):可达 = 拓扑 JSON 派生的精确 IP ∪ 子网;示例 IP(1.1.1.1 等)不可达。
"""
from __future__ import annotations

import json

import pytest

from main.ist_core.tools._shared import env_facts as ef


# ── 用合成事实源,避免依赖真实 JSON 内容(测投影逻辑本身) ──────────────
@pytest.fixture
def facts():
    return ef.EnvFacts({
        "devices": [
            {"name": "APV0", "type": "负载均衡",
             "ipv4": ["172.16.34.70/24", "172.16.35.70/24"], "ipv6": ["3ffb::70/64"]},
            {"name": "server231", "type": "服务器",
             "ipv4": ["172.16.35.231/24", "172.16.35.232/24"], "ipv6": []},
            {"name": "APV_exec", "type": "负载均衡",
             "ipv4": ["172.16.6.84"], "ipv6": []},  # 无掩码,精确可达
        ]
    })


class TestReachability:
    def test_exact_device_ip_reachable(self, facts):
        assert facts.is_reachable("172.16.34.70")
        assert facts.is_reachable("172.16.35.231")

    def test_in_subnet_vip_reachable(self, facts):
        # 段内未占用 IP(VIP/listener)→ 可达
        assert facts.is_reachable("172.16.34.50")
        assert facts.is_reachable("172.16.35.99")

    def test_no_mask_device_exact_only(self, facts):
        assert facts.is_reachable("172.16.6.84")       # 精确匹配
        assert not facts.is_reachable("172.16.6.85")   # 无子网派生,邻居不可达

    def test_example_ips_unreachable(self, facts):
        # 病根:这些示例 IP 必须判不可达(黑名单字典治不了,白名单投影能)
        for ip in ["1.1.1.1", "2.2.2.2", "3.3.3.3", "10.0.0.5", "192.168.1.1", "8.8.8.8"]:
            assert not facts.is_reachable(ip), f"{ip} 应判不可达"

    def test_out_of_topology_subnet_unreachable(self, facts):
        # 同 172.16 大段但不在任何设备子网 → 不可达(证明是按子网派生,非按私有大段)
        assert not facts.is_reachable("172.16.99.99")

    def test_ipv6_exact_whitelist(self, facts):
        assert facts.is_reachable("3ffb::70")          # 登记的 IPv6 精确可达
        assert not facts.is_reachable("3ffb::999")     # 未登记 IPv6 不可达

    def test_cidr_input_tolerated(self, facts):
        assert facts.is_reachable("172.16.34.70/24")


class TestUnreachableExtraction:
    def test_picks_only_unreachable(self, facts):
        text = "service 1.1.1.1; pool member 2.2.2.2; listener virtual 172.16.34.50"
        assert facts.unreachable_ipv4s(text) == ["1.1.1.1", "2.2.2.2"]

    def test_all_reachable_returns_empty(self, facts):
        text = "service 172.16.35.231; listener 172.16.34.70"
        assert facts.unreachable_ipv4s(text) == []

    def test_dedup_preserves_order(self, facts):
        text = "1.1.1.1 then 2.2.2.2 then 1.1.1.1 again"
        assert facts.unreachable_ipv4s(text) == ["1.1.1.1", "2.2.2.2"]


class TestSupply:
    def test_service_ips_are_server_type(self, facts):
        ips = facts.service_ips()
        assert "172.16.35.231" in ips and "172.16.35.232" in ips
        assert "172.16.34.70" not in ips  # APV 是负载均衡,非后端服务器

    def test_subnets_derived(self, facts):
        nets = facts.reachable_subnets()
        assert "172.16.34.0/24" in nets and "172.16.35.0/24" in nets

    def test_summary_mentions_real_ip_and_warns_examples(self, facts):
        s = facts.summary_for_agent()
        assert "172.16.35.231" in s
        assert "1.1.1.1" in s  # 警示句里点名示例 IP


class TestEmptyFactsDegrade:
    def test_missing_json_permissive(self, monkeypatch):
        # JSON 缺失 → 模块级便捷函数宽松降级,不拦任何 IP(避免阻断全流程)
        empty = ef.EnvFacts({"devices": []})
        monkeypatch.setattr(ef, "get_env_facts", lambda: empty)
        assert ef.unreachable_ipv4s("1.1.1.1 2.2.2.2") == []
        assert ef.is_reachable("1.1.1.1") is True


class TestRealJsonFactsSource:
    """跑真实 JSON 事实源,确认生成的文件结构能被投影正确消费。"""

    def test_real_json_loads_and_projects(self):
        facts = ef.get_env_facts()
        if not facts.devices:
            pytest.skip("真实 JSON 事实源不存在")
        # 真实环境应判这些示例 IP 不可达,真实服务器 IP 可达
        assert not facts.is_reachable("1.1.1.1")
        assert facts.is_reachable("172.16.35.231")
        assert "172.16.35.231" in facts.service_ips()


class TestEmitGate:
    """emit 校验门:配置/触发用不可达 IP 必须打回。"""

    def test_gate_rejects_unreachable_service_ip(self, monkeypatch):
        from main.ist_core.tools.device import emit_xlsx_tool as et
        # 用合成事实源注入
        synth = ef.EnvFacts({"devices": [
            {"name": "s", "type": "服务器", "ipv4": ["172.16.35.231/24"], "ipv6": []}]})
        monkeypatch.setattr(et, "get_env_facts", lambda: synth, raising=False)
        # 直接调门函数(它内部 import get_env_facts,需 patch env_facts 模块)
        monkeypatch.setattr(ef, "get_env_facts", lambda: synth)
        steps = [{"E": "APV_0", "F": "cmds_config", "G": "sdns service 1.1.1.1"},
                 {"E": "check_point", "F": "found", "G": "ok"}]
        msg = et._gate_unreachable_ips("123", steps, init="")
        assert msg is not None and "1.1.1.1" in msg

    def test_gate_passes_reachable(self, monkeypatch):
        from main.ist_core.tools.device import emit_xlsx_tool as et
        synth = ef.EnvFacts({"devices": [
            {"name": "s", "type": "服务器", "ipv4": ["172.16.35.231/24"], "ipv6": []}]})
        monkeypatch.setattr(ef, "get_env_facts", lambda: synth)
        steps = [{"E": "APV_0", "F": "cmds_config", "G": "sdns service 172.16.35.231"},
                 {"E": "check_point", "F": "found", "G": "ok"}]
        assert et._gate_unreachable_ips("123", steps, init="") is None

    def test_gate_ignores_checkpoint_text(self, monkeypatch):
        # check_point 的期望文本里的 IP 不该被拦(那是断言匹配目标,不是要连的设备)
        from main.ist_core.tools.device import emit_xlsx_tool as et
        synth = ef.EnvFacts({"devices": [
            {"name": "s", "type": "服务器", "ipv4": ["172.16.35.231/24"], "ipv6": []}]})
        monkeypatch.setattr(ef, "get_env_facts", lambda: synth)
        steps = [{"E": "APV_0", "F": "cmds_config", "G": "sdns service 172.16.35.231"},
                 {"E": "check_point", "F": "found", "G": "1.1.1.1"}]  # 断言目标含1.1.1.1
        assert et._gate_unreachable_ips("123", steps, init="") is None
