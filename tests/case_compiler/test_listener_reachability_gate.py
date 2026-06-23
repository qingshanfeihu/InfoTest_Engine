"""触发可达性门:listener/VIP/dig 目标必须落在「触发设备够得着」的 APV 接口段。

根因(655233 类):listener 配在 APV 纯管理/纯后端段接口(那段没路由器/客户端),
dig/curl 源够不着 → 上机必不解析。规则全部从拓扑 type 字段派生,零硬编码 IP,
对 dig/curl/任意触发通用。本测试用**合成 fixture**(不依赖生产 KB),验证派生+门契约。
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def synth_facts(tmp_path, monkeypatch):
    """合成一个最小测试床:
    - 10.0.1.0/24: LB 接口 + 路由器(触发够得着)→ listener-able
    - 10.0.2.0/24: LB 接口 + 服务器,无触发设备 → 触发够不着(禁配 listener)
    """
    doc = {
        "devices": [
            {"name": "lb0", "type": "负载均衡", "ipv4": ["10.0.1.10/24", "10.0.2.10/24"]},
            {"name": "r0", "type": "路由器", "ipv4": ["10.0.1.99/24"]},
            {"name": "srv0", "type": "服务器", "ipv4": ["10.0.2.50/24"]},
        ]
    }
    p = tmp_path / "topo.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    import main.ist_core.tools._shared.env_facts as ef
    monkeypatch.setattr(ef, "_TOPOLOGY_JSON", p)
    ef.get_env_facts.cache_clear()
    yield ef
    ef.get_env_facts.cache_clear()


def test_derivation_splits_listenerable_vs_blind(synth_facts):
    f = synth_facts.get_env_facts()
    # 10.0.1.10 同段有路由器 → 可配 listener;10.0.2.10 同段只有服务器 → 触发够不着
    assert f.listener_ips() == ["10.0.1.10"]
    assert f.unreachable_lb_ips() == ["10.0.2.10"]
    # 服务器后端 IP 不变
    assert "10.0.2.50" in f.service_ips()


def test_gate_rejects_blind_listener(synth_facts):
    from main.ist_core.tools.device.emit_xlsx_tool import _gate_unreachable_listener
    steps = [
        {"E": "APV_0", "F": "cmd_config", "G": "sdns listener 10.0.2.10 53"},
        {"E": "test_env", "F": "routera", "G": "dig @10.0.2.10 www.x.com"},
    ]
    msg = _gate_unreachable_listener("c1", steps)
    assert msg is not None
    assert "10.0.2.10" in msg
    assert "10.0.1.10" in msg  # 指出正确可用 IP


def test_gate_passes_reachable_listener(synth_facts):
    from main.ist_core.tools.device.emit_xlsx_tool import _gate_unreachable_listener
    steps = [
        {"E": "APV_0", "F": "cmd_config", "G": "sdns listener 10.0.1.10 53"},
        {"E": "test_env", "F": "routera", "G": "dig @10.0.1.10 www.x.com"},
    ]
    assert _gate_unreachable_listener("c2", steps) is None


def test_gate_also_catches_curl_target(synth_facts):
    """对 curl(SLB)同样生效——门只看 IP 是否触发够不着,不针对具体命令。"""
    from main.ist_core.tools.device.emit_xlsx_tool import _gate_unreachable_listener
    steps = [
        {"E": "APV_0", "F": "cmd_config", "G": "slb virtual http vs1 10.0.2.10 80"},
        {"E": "test_env", "F": "clientc", "G": "curl http://10.0.2.10/"},
    ]
    msg = _gate_unreachable_listener("c3", steps)
    assert msg is not None and "10.0.2.10" in msg


def test_gate_rejects_invented_nonstar_dig_target(synth_facts):
    """C 兜底:dig 目标落在可达子网内、但非 ★ listener、非后端 → 凭空编的 IP,打回。

    denylist 抓不到(10.0.1.50 不是任何已知接口、也不在盲段);allowlist 兜住。
    """
    from main.ist_core.tools.device.emit_xlsx_tool import _gate_unreachable_listener
    steps = [
        {"E": "APV_0", "F": "cmd_config", "G": "sdns listener 10.0.1.10 53"},   # listener 取了 ★
        {"E": "test_env", "F": "routera", "G": "dig @10.0.1.50 www.x.com +short"},  # 但 dig 打了个编的 .50
    ]
    msg = _gate_unreachable_listener("c5", steps)
    assert msg is not None
    assert "10.0.1.50" in msg
    assert "10.0.1.10" in msg   # 指出正确 ★


def test_gate_allows_backend_as_target(synth_facts):
    """后端 service IP 作 curl/dig 目标不误拦(它是合法的真实可达后端)。"""
    from main.ist_core.tools.device.emit_xlsx_tool import _gate_unreachable_listener
    steps = [
        {"E": "test_env", "F": "clientc", "G": "curl http://10.0.2.50/health"},  # 10.0.2.50 = srv0 后端
    ]
    assert _gate_unreachable_listener("c6", steps) is None


def test_empty_topology_degrades_open(tmp_path, monkeypatch):
    """JSON 缺失 → 宽松降级不拦(与其它门一致)。"""
    import main.ist_core.tools._shared.env_facts as ef
    monkeypatch.setattr(ef, "_TOPOLOGY_JSON", tmp_path / "missing.json")
    ef.get_env_facts.cache_clear()
    from main.ist_core.tools.device.emit_xlsx_tool import _gate_unreachable_listener
    steps = [{"E": "APV_0", "F": "cmd_config", "G": "sdns listener 9.9.9.9 53"}]
    assert _gate_unreachable_listener("c4", steps) is None
    ef.get_env_facts.cache_clear()
