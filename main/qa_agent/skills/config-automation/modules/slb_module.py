#!/usr/bin/env python3
"""SLB配置模块

处理负载均衡器的SLB（Server Load Balancing）配置。
"""

from datetime import datetime
import re

from utils.module_manager import ConfigModule


class SlbModule(ConfigModule):
    """SLB负载均衡配置处理模块"""

    MODULE_NAME = "slb"
    CONFIG_TYPE = "SLB负载均衡配置"

    VIRTUAL_PATTERN = re.compile(
        r'slb\s+virtual\s+(\S+)\s+\"([^\"]+)\"\s+(\S+)(?:\s+(.*))?'
    )
    REAL_PATTERN = re.compile(
        r'slb\s+real\s+(\S+)\s+\"([^\"]+)\"\s+(\S+)(?:\s+(.*))?'
    )
    GROUP_METHOD_PATTERN = re.compile(
        r'slb\s+group\s+method\s+\"([^\"]+)\"\s+(\S+)'
    )
    GROUP_MEMBER_PATTERN = re.compile(
        r'slb\s+group\s+member\s+\"([^\"]+)\"\s+\"([^\"]+)\"(?:\s+(.*))?'
    )
    POLICY_PATTERN = re.compile(
        r'slb\s+policy\s+default\s+\"([^\"]+)\"\s+\"([^\"]+)\"'
    )

    def identify(self, config_text: str) -> bool:
        lines = config_text.strip().split('\n')
        slb_count = sum(
            1 for line in lines
            if line.strip().startswith('slb ')
        )
        return slb_count >= 2

    def parse(self, config_text: str) -> dict:
        lines = config_text.strip().split('\n')
        ip_pattern = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')

        parsed = {
            'virtuals': [],
            'reals': [],
            'groups': {},
            'policies': [],
            'raw_commands': [],
        }

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('!'):
                continue

            parsed['raw_commands'].append(line)

            if match := self.VIRTUAL_PATTERN.match(line):
                vtype = match.group(1)
                name = match.group(2)
                ip = match.group(3)
                extra = match.group(4) or ''
                ips = ip_pattern.findall(ip)
                parsed['virtuals'].append({
                    'type': vtype,
                    'name': name,
                    'ip': ip,
                    'extra': extra,
                    'ips': ips if ips else [ip],
                })

            elif match := self.REAL_PATTERN.match(line):
                rtype = match.group(1)
                name = match.group(2)
                ip = match.group(3)
                extra = match.group(4) or ''
                ips = ip_pattern.findall(ip)
                parsed['reals'].append({
                    'type': rtype,
                    'name': name,
                    'ip': ip,
                    'extra': extra,
                    'ips': ips if ips else [ip],
                })

            elif match := self.GROUP_METHOD_PATTERN.match(line):
                group_name = match.group(1)
                method = match.group(2)
                parsed['groups'][group_name] = {
                    'method': method,
                    'members': [],
                }

            elif match := self.GROUP_MEMBER_PATTERN.match(line):
                group_name = match.group(1)
                real_name = match.group(2)
                extra = match.group(3) or ''
                if group_name not in parsed['groups']:
                    parsed['groups'][group_name] = {
                        'method': 'unknown',
                        'members': [],
                    }
                parsed['groups'][group_name]['members'].append({
                    'real_name': real_name,
                    'extra': extra,
                })

            elif match := self.POLICY_PATTERN.match(line):
                virtual_name = match.group(1)
                group_name = match.group(2)
                parsed['policies'].append({
                    'virtual': virtual_name,
                    'group': group_name,
                })

        return parsed

    def generate_config(self, parsed_data: dict, ip_mapping: dict, **kwargs) -> str:
        target_device = kwargs.get('target_device', 'unknown')
        lines = []

        lines.append("# ========== SLB配置脚本 ==========")
        lines.append(f"# 配置类型: {self.CONFIG_TYPE}")
        lines.append(f"# 目标设备: {target_device}")
        lines.append(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        if ip_mapping:
            mapping_str = ', '.join(f'{k}->{v}' for k, v in ip_mapping.items())
            lines.append(f"# IP映射: {mapping_str}")

        lines.append("")

        if parsed_data.get('virtuals'):
            lines.append("# 虚拟服务配置")
            for v in parsed_data['virtuals']:
                new_ip = ip_mapping.get(v['ip'], v['ip'])
                for old_ip, new_ip_val in ip_mapping.items():
                    new_ip = new_ip.replace(old_ip, new_ip_val)
                extra = v.get('extra', '')
                if extra:
                    lines.append(
                        f'slb virtual {v["type"]} "{v["name"]}" {new_ip} {extra}'
                    )
                else:
                    lines.append(
                        f'slb virtual {v["type"]} "{v["name"]}" {new_ip}'
                    )
            lines.append("")

        if parsed_data.get('reals'):
            lines.append("# 真实服务器配置")
            for r in parsed_data['reals']:
                new_ip = ip_mapping.get(r['ip'], r['ip'])
                for old_ip, new_ip_val in ip_mapping.items():
                    new_ip = new_ip.replace(old_ip, new_ip_val)
                extra = r.get('extra', '')
                if extra:
                    lines.append(
                        f'slb real {r["type"]} "{r["name"]}" {new_ip} {extra}'
                    )
                else:
                    lines.append(
                        f'slb real {r["type"]} "{r["name"]}" {new_ip}'
                    )
            lines.append("")

        if parsed_data.get('groups'):
            lines.append("# 组配置")
            for group_name, info in parsed_data['groups'].items():
                if info.get('method') and info['method'] != 'unknown':
                    lines.append(
                        f'slb group method "{group_name}" {info["method"]}'
                    )
                for member in info.get('members', []):
                    extra = member.get('extra', '')
                    if extra:
                        lines.append(
                            f'slb group member "{group_name}" '
                            f'"{member["real_name"]}" {extra}'
                        )
                    else:
                        lines.append(
                            f'slb group member "{group_name}" '
                            f'"{member["real_name"]}"'
                        )
            lines.append("")

        if parsed_data.get('policies'):
            lines.append("# 策略配置")
            for p in parsed_data['policies']:
                lines.append(
                    f'slb policy default "{p["virtual"]}" "{p["group"]}"'
                )
            lines.append("")

        return '\n'.join(lines)

    def generate_verify(self, parsed_data: dict, ip_mapping: dict) -> str:
        lines = []

        lines.append("# ========== SLB验证脚本 ==========")
        lines.append(f"# 配置类型: {self.CONFIG_TYPE}")
        lines.append(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        lines.append("# 查看虚拟服务状态")
        lines.append("show slb virtual-server")
        lines.append("")

        lines.append("# 查看真实服务器状态")
        lines.append("show slb real-server")
        lines.append("")

        if parsed_data.get('virtuals'):
            lines.append("# 逐虚拟服务详情")
            for v in parsed_data['virtuals']:
                lines.append(f"show slb virtual-server \"{v['name']}\"")
            lines.append("")

        if parsed_data.get('reals'):
            lines.append("# 逐真实服务器详情")
            for r in parsed_data['reals']:
                lines.append(f"show slb real-server \"{r['name']}\"")
            lines.append("")

        if parsed_data.get('groups'):
            lines.append("# 组配置查看")
            lines.append("show slb group")
            lines.append("")

        lines.append("# 流量统计")
        lines.append("show slb statistics")
        lines.append("")

        lines.append("# 运行配置检查")
        lines.append("show running-config | include slb")

        return '\n'.join(lines)

    def get_variable_map(self) -> dict:
        return {
            '${SLB_VIRTUAL_NAME}': '虚拟服务名称',
            '${SLB_VIRTUAL_IP}': '虚拟服务VIP地址',
            '${SLB_REAL_NAME}': '真实服务器名称',
            '${SLB_REAL_IP}': '真实服务器IP地址',
            '${SLB_GROUP_NAME}': '组名称',
            '${SLB_GROUP_METHOD}': '负载均衡方法 (rr/lc/wlc)',
            '${SLB_POLICY_DEFAULT}': '默认策略绑定的组',
        }
