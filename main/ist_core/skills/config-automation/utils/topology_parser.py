#!/usr/bin/env python3
"""网络拓扑解析器

解析网络拓扑Markdown文档，提取设备信息和IP地址。
"""

import ipaddress
import re
from typing import Dict, List, Optional


class NetworkTopology:
    def __init__(self):
        self.devices: Dict[str, Device] = {}

    def add_device(self, name: str, device_type: str, ipv4_addresses: List[str], ipv6_addresses: List[str] = None):
        self.devices[name] = Device(name, device_type, ipv4_addresses, ipv6_addresses or [])

    def get_device_by_type(self, device_type: str) -> List['Device']:
        return [d for d in self.devices.values() if d.device_type == device_type]

    def get_device(self, name: str) -> Optional['Device']:
        return self.devices.get(name)

    def get_all_ips(self) -> List[str]:
        """获取所有设备的IP地址"""
        all_ips = []
        for device in self.devices.values():
            all_ips.extend(device.ipv4_addresses)
            all_ips.extend(device.ipv6_addresses)
        return all_ips

    def __len__(self):
        return len(self.devices)


class Device:
    def __init__(self, name: str, device_type: str, ipv4_addresses: List[str], ipv6_addresses: List[str]):
        self.name = name
        self.device_type = device_type
        self.ipv4_addresses = ipv4_addresses
        self.ipv6_addresses = ipv6_addresses

    def get_usable_ipv4(self, subnet: str = None) -> List[str]:
        """获取可用的IPv4地址，可选按子网过滤"""
        if subnet:
            subnet_obj = ipaddress.IPv4Network(subnet, strict=False)
            return [ip for ip in self.ipv4_addresses if ipaddress.IPv4Address(ip.split('/')[0]) in subnet_obj]
        return self.ipv4_addresses

    def __repr__(self):
        return f"Device(name={self.name}, type={self.device_type}, ipv4={self.ipv4_addresses})"


class TopologyParser:
    """网络拓扑文档解析器"""

    _SEPARATOR_RE = re.compile(r'^-+\s*$')

    @staticmethod
    def _split_cell(cell_text: str | None) -> list[str]:
        """Split a table cell on <br> tags and newlines, returning non-empty trimmed parts."""
        if not cell_text:
            return []
        text = cell_text.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
        return [p.strip() for p in text.split('\n') if p.strip()]

    @staticmethod
    def parse_markdown(file_path: str) -> NetworkTopology:
        """解析网络拓扑Markdown文档"""
        topology = NetworkTopology()

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 匹配设备层级部分
        device_section_pattern = re.compile(
            r'### 第(\d+)层：(\S+)\s*\n((?:\s*\|[^\n]+\|\s*\n)+)',
            re.DOTALL
        )

        for match in device_section_pattern.finditer(content):
            layer_number = match.group(1)
            layer_name = match.group(2).strip()
            table_content = match.group(3)

            # 解析表格行
            rows = re.findall(r'\|([^|]+)\|([^|]+)\|([^|]+)\|?', table_content)

            if not rows:
                continue

            # 获取表头
            header = rows[0]
            header_cols = [h.strip().lower() for h in header]

            # 判断是否为设备IP表格（包含IPv4地址列）
            has_ipv4 = any('ipv4' in col or '地址' in col for col in header_cols)

            for row in rows[1:]:
                name = row[0].strip()
                col1 = row[1].strip()
                col2 = row[2].strip()

                if not name or name == '设备名称':
                    continue

                # skip separator rows (e.g. "----------")
                if TopologyParser._SEPARATOR_RE.match(name):
                    continue

                if has_ipv4:
                    # 这是IP地址表格
                    ipv4_list = TopologyParser._split_cell(col1)
                    ipv6_list = TopologyParser._split_cell(col2)

                    device_type = TopologyParser._map_layer_to_type(layer_name)
                    topology.add_device(name, device_type, ipv4_list, ipv6_list)

        return topology

    @staticmethod
    def _map_layer_to_type(layer_name: str) -> str:
        """将层级名称映射到设备类型"""
        layer_map = {
            '客户端层': '客户端',
            '接入层交换机': '交换机',
            '路由层': '路由器',
            '核心层交换机': '交换机',
            '应用交付层': '负载均衡',
            '汇聚层交换机': '交换机',
            '服务器层': '服务器',
            '控制台': '控制台',
        }
        for key, value in layer_map.items():
            if key in layer_name:
                return value
        return '其他'
