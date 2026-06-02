#!/usr/bin/env python3
"""通用配置自动化生成器

支持多种网络设备配置格式，自动从网络拓扑文档提取真实IP地址，
将示例配置转换为可直接部署的自动化脚本。
"""

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from utils import NetworkTopology, TopologyParser, IpMapper, ModuleManager, ConfigModule


class DefaultModule(ConfigModule):
    """默认模块（当没有匹配的专用模块时使用）"""
    
    MODULE_NAME = "default"
    CONFIG_TYPE = "通用配置"
    
    def identify(self, config_text: str) -> bool:
        return True
    
    def parse(self, config_text: str) -> dict:
        lines = config_text.strip().split('\n')
        commands = []
        ip_pattern = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('!'):
                continue
            commands.append({
                'line': line,
                'ips': ip_pattern.findall(line),
            })
        
        return {'commands': commands, 'raw_text': config_text}
    
    def generate_config(self, parsed_data: dict, ip_mapping: dict, **kwargs) -> str:
        target_device = kwargs.get('target_device', 'unknown')
        lines = []
        lines.append(f"# ========== 配置脚本 ==========")
        lines.append(f"# 配置类型: {self.CONFIG_TYPE}")
        lines.append(f"# 目标设备: {target_device}")
        lines.append(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if ip_mapping:
            mapping_str = ', '.join(f'{k}->{v}' for k, v in ip_mapping.items())
            lines.append(f"# IP映射: {mapping_str}")
        
        lines.append("")
        
        for cmd in parsed_data.get('commands', []):
            line = cmd['line']
            for old_ip, new_ip in ip_mapping.items():
                line = line.replace(old_ip, new_ip)
            lines.append(line)
        
        return '\n'.join(lines)
    
    def generate_verify(self, parsed_data: dict, ip_mapping: dict) -> str:
        lines = []
        lines.append(f"# ========== 验证脚本 ==========")
        lines.append(f"# 配置类型: {self.CONFIG_TYPE}")
        lines.append(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("# 验证命令（请根据实际设备类型调整）")
        lines.append("# show running-config")
        return '\n'.join(lines)


class ConfigGenerator:
    """主配置生成器"""
    
    def __init__(self, topology_file: str, modules_dir: str = None):
        self.topology = TopologyParser.parse_markdown(topology_file)
        self.module_manager = ModuleManager()
        
        if modules_dir:
            self.module_manager.discover_modules(modules_dir)
    
    def process_config(self, config_text: str, target_device: str = 'APV0') -> dict:
        """处理配置文本，生成配置脚本和验证脚本"""
        
        module = self.module_manager.identify_module(config_text)
        if not module:
            module = DefaultModule()
        
        print(f"[+] 识别到配置类型: {module.CONFIG_TYPE}")
        
        parsed_data = module.parse(config_text)
        print(f"[+] 解析完成，配置项数量: {len(parsed_data)}")
        
        ip_mapper = IpMapper(self.topology)
        ip_mapping = ip_mapper.generate_mapping(parsed_data)
        print(f"[+] IP映射完成，映射数量: {len(ip_mapping)}")
        
        variable_map = module.get_variable_map()
        
        config_script = module.generate_config(parsed_data, ip_mapping, target_device=target_device)
        verify_script = module.generate_verify(parsed_data, ip_mapping)
        
        return {
            'module_name': module.MODULE_NAME,
            'config_type': module.CONFIG_TYPE,
            'parsed_data': parsed_data,
            'ip_mapping': ip_mapping,
            'variable_map': variable_map,
            'config_script': config_script,
            'verify_script': verify_script,
        }
    
    def write_output(self, result: dict, output_dir: str):
        """将结果写入输出文件"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        module_name = result['module_name']
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        config_path = output_path / f'config_{module_name}_{timestamp}.txt'
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(result['config_script'])
        print(f"[+] 配置脚本已写入: {config_path}")
        
        verify_path = output_path / f'verify_{module_name}_{timestamp}.txt'
        with open(verify_path, 'w', encoding='utf-8') as f:
            f.write(result['verify_script'])
        print(f"[+] 验证脚本已写入: {verify_path}")
        
        mapping_path = output_path / f'mapping_{module_name}_{timestamp}.json'
        with open(mapping_path, 'w', encoding='utf-8') as f:
            json.dump({
                'ip_mapping': result['ip_mapping'],
                'variable_map': result['variable_map'],
            }, f, indent=2, ensure_ascii=False)
        print(f"[+] 映射表已写入: {mapping_path}")
        
        return {
            'config_file': str(config_path),
            'verify_file': str(verify_path),
            'mapping_file': str(mapping_path),
        }


def main():
    parser = argparse.ArgumentParser(description='通用配置自动化生成器')
    parser.add_argument('--topology', required=True, help='网络拓扑文档路径')
    parser.add_argument('--config', required=True, help='配置文本或配置文件路径')
    parser.add_argument('--output-dir', default='.', help='输出目录')
    parser.add_argument('--target-device', default='APV0', help='目标设备名称')
    parser.add_argument('--modules-dir', default=None, help='模块目录路径')
    args = parser.parse_args()
    
    print(f"[+] 正在初始化配置生成器")
    generator = ConfigGenerator(args.topology, args.modules_dir)
    print(f"[+] 已加载 {len(generator.module_manager.modules)} 个配置模块")
    
    if os.path.isfile(args.config):
        with open(args.config, 'r', encoding='utf-8') as f:
            config_text = f.read()
        print(f"[+] 已读取配置文件: {args.config}")
    else:
        config_text = args.config
        print("[+] 使用命令行提供的配置文本")
    
    print("[+] 正在处理配置...")
    result = generator.process_config(config_text, args.target_device)
    
    print("[+] 正在写入输出文件...")
    files = generator.write_output(result, args.output_dir)
    
    print("\n" + "="*60)
    print("IP映射表:")
    print("="*60)
    print("原始值\t\t实际映射值")
    print("-"*60)
    for old_ip, new_ip in result['ip_mapping'].items():
        print(f"{old_ip}\t\t{new_ip}")
    print("="*60)
    
    if result['variable_map']:
        print("\n" + "="*60)
        print("变量映射表:")
        print("="*60)
        print("变量名\t\t值")
        print("-"*60)
        for var_name, value in result['variable_map'].items():
            print(f"{var_name}\t\t{value}")
        print("="*60)


if __name__ == '__main__':
    main()