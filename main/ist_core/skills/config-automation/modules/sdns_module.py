#!/usr/bin/env python3
"""SDNS配置模块

处理负载均衡器的SDNS（智能DNS）配置。
"""

from datetime import datetime
import re

from utils.module_manager import ConfigModule


class SdnsModule(ConfigModule):
    """SDNS配置处理模块"""
    
    MODULE_NAME = "sdns"
    CONFIG_TYPE = "SDNS域名服务配置"
    
    LISTENER_PATTERN = re.compile(r'sdns\s+listener\s+(\S+)')
    SERVICE_PATTERN = re.compile(r'sdns\s+service\s+ip\s+(\S+)\s+(\S+)\s+(\d+)')
    HOST_PATTERN = re.compile(r'sdns\s+host\s+name\s+(\S+)\s+(\d+)')
    POOL_NAME_PATTERN = re.compile(r'sdns\s+pool\s+name\s+(\S+)\s+(\d+)\s+(\d+)')
    POOL_SERVICE_PATTERN = re.compile(r'sdns\s+pool\s+service\s+(\S+)\s+(\S+)')
    HOST_POOL_PATTERN = re.compile(r'sdns\s+host\s+pool\s+(\S+)\s+(\S+)')
    
    def identify(self, config_text: str) -> bool:
        lines = config_text.strip().split('\n')
        sdns_count = sum(1 for line in lines if line.strip().startswith('sdns '))
        return sdns_count >= 2
    
    def parse(self, config_text: str) -> dict:
        lines = config_text.strip().split('\n')
        
        parsed = {
            'enabled': False,
            'listeners': [],
            'services': {},
            'hosts': {},
            'pools': {},
            'pool_services': {},
            'host_pools': {},
            'raw_commands': [],
        }
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('!'):
                continue
            
            parsed['raw_commands'].append(line)
            
            if line == 'sdns on':
                parsed['enabled'] = True
            
            elif match := self.LISTENER_PATTERN.match(line):
                parsed['listeners'].append(match.group(1))
            
            elif match := self.SERVICE_PATTERN.match(line):
                name = match.group(1)
                ip = match.group(2)
                weight = int(match.group(3))
                parsed['services'][name] = {'ip': ip, 'weight': weight}
            
            elif match := self.HOST_PATTERN.match(line):
                name = match.group(1)
                ttl = int(match.group(2))
                parsed['hosts'][name] = ttl
            
            elif match := self.POOL_NAME_PATTERN.match(line):
                name = match.group(1)
                min_srv = int(match.group(2))
                max_srv = int(match.group(3))
                parsed['pools'][name] = {'min': min_srv, 'max': max_srv}
            
            elif match := self.POOL_SERVICE_PATTERN.match(line):
                pool_name = match.group(1)
                service_name = match.group(2)
                if pool_name not in parsed['pool_services']:
                    parsed['pool_services'][pool_name] = []
                parsed['pool_services'][pool_name].append(service_name)
            
            elif match := self.HOST_POOL_PATTERN.match(line):
                host_name = match.group(1)
                pool_name = match.group(2)
                parsed['host_pools'][host_name] = pool_name
        
        return parsed
    
    def generate_config(self, parsed_data: dict, ip_mapping: dict, **kwargs) -> str:
        target_device = kwargs.get('target_device', 'unknown')
        lines = []
        
        lines.append("# ========== SDNS配置脚本 ==========")
        lines.append(f"# 配置类型: {self.CONFIG_TYPE}")
        lines.append(f"# 目标设备: {target_device}")
        lines.append(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if ip_mapping:
            mapping_str = ', '.join(f'{k}->{v}' for k, v in ip_mapping.items())
            lines.append(f"# IP映射: {mapping_str}")
        
        lines.append("")
        
        lines.append("# 全局配置")
        lines.append("sdns on" if parsed_data.get('enabled') else "# sdns on (未启用)")
        lines.append("")
        
        if parsed_data.get('listeners'):
            lines.append("# 监听配置")
            for listener in parsed_data['listeners']:
                ip = ip_mapping.get(listener, listener)
                lines.append(f"sdns listener {ip}")
            lines.append("")
        
        if parsed_data.get('hosts'):
            lines.append("# 域名配置")
            for host_name, ttl in parsed_data['hosts'].items():
                lines.append(f"sdns host name {host_name} {ttl}")
            lines.append("")
        
        if parsed_data.get('services'):
            lines.append("# 服务配置")
            for service_name, info in parsed_data['services'].items():
                ip = ip_mapping.get(info['ip'], info['ip'])
                lines.append(f"sdns service ip {service_name} {ip} {info['weight']}")
            lines.append("")
        
        if parsed_data.get('pools'):
            lines.append("# 池配置")
            for pool_name, info in parsed_data['pools'].items():
                lines.append(f"sdns pool name {pool_name} {info['min']} {info['max']}")
            lines.append("")
        
        if parsed_data.get('pool_services'):
            lines.append("# 池服务关联")
            for pool_name, services in parsed_data['pool_services'].items():
                for service in services:
                    lines.append(f"sdns pool service {pool_name} {service}")
            lines.append("")
        
        if parsed_data.get('host_pools'):
            lines.append("# 域名池关联")
            for host_name, pool_name in parsed_data['host_pools'].items():
                lines.append(f"sdns host pool {host_name} {pool_name}")
        
        return '\n'.join(lines)
    
    def generate_verify(self, parsed_data: dict, ip_mapping: dict) -> str:
        lines = []
        
        lines.append("# ========== SDNS验证脚本 ==========")
        lines.append(f"# 配置类型: {self.CONFIG_TYPE}")
        lines.append(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        lines.append("# 查看SDNS状态")
        lines.append("show sdns status")
        lines.append("")
        
        lines.append("# 查看监听配置")
        lines.append("show sdns listener")
        lines.append("")
        
        if parsed_data.get('hosts'):
            lines.append("# 查看域名配置")
            for host_name in parsed_data['hosts'].keys():
                lines.append(f"show sdns host name {host_name}")
            lines.append("")
        
        if parsed_data.get('services'):
            lines.append("# 查看服务配置")
            for service_name in parsed_data['services'].keys():
                lines.append(f"show sdns service ip {service_name}")
            lines.append("")
        
        if parsed_data.get('pools'):
            lines.append("# 查看池配置")
            for pool_name in parsed_data['pools'].keys():
                lines.append(f"show sdns pool name {pool_name}")
                if pool_name in parsed_data.get('pool_services', {}):
                    lines.append(f"show sdns pool service {pool_name}")
            lines.append("")
        
        if parsed_data.get('host_pools'):
            lines.append("# 查看域名池关联")
            lines.append("show sdns host pool")
            lines.append("")
        
        if parsed_data.get('listeners') and parsed_data.get('hosts'):
            listener_ip = ip_mapping.get(parsed_data['listeners'][0], parsed_data['listeners'][0])
            first_host = list(parsed_data['hosts'].keys())[0]
            lines.append("# 模拟DNS查询验证")
            lines.append(f"show sdns query match {listener_ip.split('/')[0]} {first_host}")
            lines.append("")
        
        if parsed_data.get('hosts'):
            first_host = list(parsed_data['hosts'].keys())[0]
            lines.append("# 查看域名汇总信息")
            lines.append(f"show sdns summary {first_host}")
        
        return '\n'.join(lines)
    
    def get_variable_map(self) -> dict:
        return {
            '${SDNS_LISTENER}': 'SDNS监听地址',
            '${SDNS_SERVICE_IP}': '后端服务IP地址',
            '${SDNS_HOST_NAME}': '域名',
            '${SDNS_TTL}': 'DNS缓存时间(秒)',
            '${SDNS_POOL_NAME}': '池名称',
            '${SDNS_POOL_MIN}': '池最小服务数',
            '${SDNS_POOL_MAX}': '池最大服务数',
        }