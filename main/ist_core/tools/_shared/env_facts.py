"""环境事实源(权威投影)——网络拓扑的唯一真相,供"可达性校验"与"真值供给"共用。

设计意图(对齐项目第一原则:零硬编码、纯引导):
- **不是死字典**:本模块不写任何具体 IP、网段、设备类型常量。所有事实来自
  ``knowledge/data/auto_env/network_topology.json``(可编辑的事实源)。换测试床只改 JSON,代码不动。
- **白名单投影,非黑名单翻译**:不去枚举"什么是示例 IP"(1.1.1.1/10.x… 无穷无尽),
  而是从拓扑客观派生"什么 IP 可达"= 设备精确 IP ∪ 设备子网。可达集之外一律非法。
  这样 1.1.1.1 不是"被翻译掉",而是**压根不在可达集** → 不是合法参数。
- **两个用途同一事实源**:
    1. 供给(draft 写 IP 前查真值):``service_ips()`` / ``summary_for_agent()``
    2. 校验门(emit 出口兜底):``is_reachable(ip)`` / ``unreachable_ipv4s(text)``

子网从设备 IP 的 CIDR 掩码**派生**(如 172.16.35.231/24 → 172.16.35.0/24),不写死网段。
无掩码的散落设备(如执行用 APV)按精确 IP 可达。
"""
from __future__ import annotations

import functools
import ipaddress
import json
import logging
import re

from main import knowledge_paths as _kp

logger = logging.getLogger(__name__)

_TOPOLOGY_JSON = _kp.KNOWLEDGE_AUTO_ENV_TOPOLOGY_JSON
_ACTIONS_JSON = _kp.KNOWLEDGE_AUTO_ENV_ACTIONS_JSON

_IPV4_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
# 后端/服务类设备类型(派生 service_ips 用)——这些词本身来自 JSON 的 type 字段,不是写死的领域规则
_SERVER_TYPES = ("服务器",)


class EnvFacts:
    """拓扑事实源的内存投影。从 JSON 派生:设备精确 IP 集、可达子网集、按类型分组的 IP。"""

    def __init__(self, doc: dict):
        self._doc = doc
        self.devices: list[dict] = doc.get("devices", [])
        self._exact_ips: set[str] = set()        # IPv4 + IPv6 裸地址,精确匹配用
        self._subnets: list[ipaddress.IPv4Network] = []
        self._build()

    def _build(self) -> None:
        seen_subnets: set[str] = set()
        for dev in self.devices:
            for cidr in dev.get("ipv4", []):
                bare = cidr.split("/")[0]
                self._exact_ips.add(bare)
                if "/" in cidr:
                    try:
                        net = ipaddress.ip_network(cidr, strict=False)
                    except ValueError:
                        continue
                    if str(net) not in seen_subnets:
                        seen_subnets.add(str(net))
                        self._subnets.append(net)
            # IPv6 仅做精确白名单(不派生子网)——保持与历史 ssh.py 行为一致,不误拒 IPv6 设备
            for v6 in dev.get("ipv6", []):
                self._exact_ips.add(v6.split("/")[0])

    # ── 校验门用 ─────────────────────────────────────────────────────────
    def is_reachable(self, ip: str) -> bool:
        """IP 是否可达:精确等于某设备 IP(v4/v6),或落在某设备 IPv4 子网内。可达集之外(如 1.1.1.1)→ False。"""
        bare = (ip or "").split("/")[0].strip()
        if bare in self._exact_ips:
            return True
        try:
            addr = ipaddress.IPv4Address(bare)
        except ValueError:
            return False  # 非 IPv4(含未登记的 IPv6)且不在精确集 → 不可达
        return any(addr in net for net in self._subnets)

    def unreachable_ipv4s(self, text: str) -> list[str]:
        """从一段文本里挑出所有**不可达**的 IPv4 字面(去重保序)。空=全可达。"""
        out: list[str] = []
        for m in _IPV4_RE.finditer(text or ""):
            ip = m.group(1)
            if ip not in out and not self.is_reachable(ip):
                out.append(ip)
        return out

    # ── 供给用 ───────────────────────────────────────────────────────────
    def service_ips(self) -> list[str]:
        """后端服务器类设备的真实可达 IP(draft 写 service/pool 后端时该用这些)。"""
        out: list[str] = []
        for dev in self.devices:
            if any(t in dev.get("type", "") for t in _SERVER_TYPES):
                for cidr in dev.get("ipv4", []):
                    bare = cidr.split("/")[0]
                    if bare not in out:
                        out.append(bare)
        return out

    def reachable_subnets(self) -> list[str]:
        return [str(n) for n in self._subnets]

    def summary_for_agent(self) -> str:
        """给 draft 子 agent 的事实摘要:可达子网 + 后端服务器真实 IP + 设备清单。"""
        lines = ["=== 本测试床网络事实源(写 IP 只能用这里的真实可达值)==="]
        lines.append(f"可达子网(IP 必须落在其中之一): {', '.join(self.reachable_subnets())}")
        lines.append(f"后端服务器真实 IP(service/pool 后端用): {', '.join(self.service_ips())}")
        lines.append("设备清单:")
        for dev in self.devices:
            ips = ", ".join(dev.get("ipv4", []))
            lines.append(f"  {dev.get('name')} [{dev.get('type')}]: {ips}")
        lines.append("VIP/listener 用段内未占用 IP(不与上述设备 IP 冲突即可)。")
        lines.append("禁止裸用 1.1.1.1/2.2.2.2/10.x/192.168.x 等示例 IP——它们不可达,上机 dig 必失败。")
        return "\n".join(lines)


@functools.lru_cache(maxsize=1)
def get_env_facts() -> EnvFacts:
    """进程级单例。JSON 缺失时返回空事实源(is_reachable 恒 True,即放行——避免误杀,与 ssh.py 一致的宽松降级)。"""
    if not _TOPOLOGY_JSON.exists():
        logger.warning("env facts JSON 不存在: %s;可达校验降级为放行。", _TOPOLOGY_JSON)
        return EnvFacts({"devices": []})
    try:
        doc = json.loads(_TOPOLOGY_JSON.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("env facts JSON 解析失败: %s;可达校验降级为放行。", exc)
        return EnvFacts({"devices": []})
    return EnvFacts(doc)


def is_reachable(ip: str) -> bool:
    """便捷:IP 是否在拓扑可达集内。空事实源(JSON 缺失)→ 恒 True(宽松降级)。"""
    facts = get_env_facts()
    if not facts.devices:
        return True
    return facts.is_reachable(ip)


def unreachable_ipv4s(text: str) -> list[str]:
    """便捷:文本里的不可达 IPv4 列表。空事实源 → 空列表(不拦)。"""
    facts = get_env_facts()
    if not facts.devices:
        return []
    return facts.unreachable_ipv4s(text)
