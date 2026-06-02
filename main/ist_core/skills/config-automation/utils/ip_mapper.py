#!/usr/bin/env python3
"""IP地址映射器

将示例IP地址映射到真实环境IP地址。
VIP / listener 等虚拟 IP 生成为网段上未被占用的任意 IP；
real server / service 等后端 IP 使用拓扑中真实的服务器 IP。
"""

import ipaddress
import re
from typing import Dict, List, Optional, Set

from .topology_parser import NetworkTopology


class IpMapper:
    """IP地址映射器 - 将示例IP映射到真实环境IP"""

    EXAMPLE_NETWORKS = [
        ipaddress.IPv4Network('10.0.0.0/8'),
        ipaddress.IPv4Network('192.168.0.0/16'),
        ipaddress.IPv4Network('172.16.0.0/19'),
        ipaddress.IPv4Network('127.0.0.0/8'),
    ]

    # VIP 生成优先使用的网段（业务段 > 服务器段 > 接入段 > 管理段）
    VIP_SEGMENTS = [
        ipaddress.IPv4Network('172.16.34.0/24'),
        ipaddress.IPv4Network('172.16.35.0/24'),
        ipaddress.IPv4Network('172.16.33.0/24'),
        ipaddress.IPv4Network('172.16.32.0/24'),
    ]

    def __init__(self, topology: NetworkTopology):
        self.topology = topology

    def is_example_ip(self, ip_str: str) -> bool:
        """判断是否为示例IP地址"""
        try:
            ip = ipaddress.IPv4Address(ip_str.split('/')[0])
            return any(ip in network for network in self.EXAMPLE_NETWORKS)
        except ValueError:
            return False

    def find_device_ips(self, device_type: str, subnet: str = None) -> List[str]:
        """查找指定类型设备的IP地址"""
        devices = self.topology.get_device_by_type(device_type)
        all_ips = []
        for device in devices:
            if subnet:
                ips = device.get_usable_ipv4(subnet)
            else:
                ips = device.ipv4_addresses
            all_ips.extend(ips)
        return all_ips

    def _collect_used_ips(self) -> Set[str]:
        """收集拓扑中所有已被设备占用的 IP（裸 IP，不含子网掩码）。"""
        used: set[str] = set()
        for ip_str in self.topology.get_all_ips():
            bare = ip_str.split('/')[0]
            used.add(bare)
        return used

    # VIP 起始主机号：跳过 .1-.49（保留网关等基础设施地址）
    VIP_HOST_MIN = 50

    def generate_unused_vip(self, used_ips: Optional[Set[str]] = None) -> str:
        """在优先网段中生成一个未被占用的 VIP。

        按 VIP_SEGMENTS 顺序扫描，从 .50 开始（跳过网关等低号地址），
        返回第一个未被任何设备使用的 IP。
        """
        used = set(used_ips or self._collect_used_ips())
        for segment in self.VIP_SEGMENTS:
            for host in segment.hosts():
                host_str = str(host)
                octets = host_str.split('.')
                host_num = int(octets[-1])
                if host_num < self.VIP_HOST_MIN:
                    continue
                if host_str in used:
                    continue
                return host_str
        raise ValueError("no unused IP available in any VIP segment")

    @staticmethod
    def _extract_vip_ips(parsed_data: dict) -> Set[str]:
        """从模块解析结果中提取 VIP 类 IP（virtual / listener）。

        遍历 parsed_data 中所有 dict/list，收集其自身键名或任意父键名
        包含 'virtual'/'listener'/'vip' 的子结构中的 IP。
        """
        vip_ips: set[str] = set()
        ip_re = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')

        def _walk(obj, parent_keys: list[str]):
            if isinstance(obj, str):
                # bare string in a list (e.g. listeners: ['10.0.0.1'])
                for m in ip_re.finditer(obj):
                    ip = m.group(1)
                    if any(
                        'virtual' in key.lower()
                        or 'listener' in key.lower()
                        or 'vip' in key.lower()
                        for key in parent_keys
                    ):
                        vip_ips.add(ip)
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, str):
                        for m in ip_re.finditer(v):
                            ip = m.group(1)
                            all_keys = [k] + parent_keys
                            if any(
                                'virtual' in key.lower()
                                or 'listener' in key.lower()
                                or 'vip' in key.lower()
                                for key in all_keys
                            ):
                                vip_ips.add(ip)
                    else:
                        _walk(v, [k] + parent_keys)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item, parent_keys)

        _walk(parsed_data, [])
        return vip_ips

    def generate_mapping(self, parsed_data: dict) -> dict:
        """生成IP映射表。

        - VIP / listener 类 IP → 从网段中生成未被占用的新 IP
        - 其他示例 IP（后端服务等）→ 使用拓扑中真实的服务器 IP
        """
        mapping: dict[str, str] = {}

        # 收集已占用 IP 集合（VIP 不能抢已有设备的 IP）
        used_ips = self._collect_used_ips()

        # 识别哪些示例 IP 是 VIP
        vip_ips = self._extract_vip_ips(parsed_data)

        # 后端 IP 池：服务器 IP（去重，去除子网掩码）
        server_pool: list[str] = []
        for ip in self.find_device_ips('服务器'):
            bare = ip.split('/')[0]
            if bare not in server_pool:
                server_pool.append(bare)

        # 提取所有 IP
        all_ips: list[str] = []
        ip_pattern = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b')

        def extract_ips(data):
            if isinstance(data, str):
                all_ips.extend(ip_pattern.findall(data))
            elif isinstance(data, dict):
                for value in data.values():
                    extract_ips(value)
            elif isinstance(data, list):
                for item in data:
                    extract_ips(item)

        extract_ips(parsed_data)

        server_idx = 0
        for ip in all_ips:
            if not self.is_example_ip(ip):
                continue
            if ip in mapping:
                continue

            if ip in vip_ips:
                # VIP → 生成未占用的新 IP，并标记为已用（避免多个 VIP 抢同一 IP）
                new_vip = self.generate_unused_vip(used_ips)
                mapping[ip] = new_vip
                used_ips.add(new_vip)
            elif server_pool and server_idx < len(server_pool):
                mapping[ip] = server_pool[server_idx]
                server_idx += 1

        return mapping
