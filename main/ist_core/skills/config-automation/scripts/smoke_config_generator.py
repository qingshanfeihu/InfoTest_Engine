#!/usr/bin/env python3
"""config-automation 手工冒烟脚本(非 pytest,无断言,靠人读输出判断)。

运行: python main/ist_core/skills/config-automation/scripts/smoke_config_generator.py
依赖 knowledge/data/auto_env/network_topology_rag.md;输出落
workspace/outputs/config_automation_test/。原先放在 skill 包内 tests/ 目录但
pytest 从不收集(死测试假象)——按 skill 标准包布局迁到 scripts/。
"""

import subprocess
import sys
from pathlib import Path

SAMPLE_SDNS_CONFIG = """
sdns on
sdns listener 10.0.0.1
sdns host name www.example.com 60
sdns service ip srv_web 192.168.1.10 0
sdns pool name pool_web 3 1
sdns pool service pool_web srv_web
sdns host pool www.example.com pool_web
"""

SAMPLE_FIREWALL_CONFIG = """
firewall enable
firewall rule 10 permit ip source 10.0.0.0 255.255.255.0 destination 172.16.0.0 255.255.0.0
firewall rule 20 deny ip source any destination any
"""

SAMPLE_ROUTING_CONFIG = """
ip route 192.168.100.0 255.255.255.0 10.0.0.254
ip route 172.16.200.0 255.255.255.0 10.0.0.253
"""

def run_test(config_type, config_text):
    print(f"\n{'='*70}")
    print(f"测试配置类型: {config_type}")
    print('='*70)
    
    skill_dir = Path(__file__).parent.parent
    project_root = Path(__file__).resolve().parents[5]
    topology_path = project_root / "knowledge" / "data" / "auto_env" / "network_topology_rag.md"
    modules_dir = skill_dir / 'modules'
    output_dir = project_root / "workspace" / "outputs" / "config_automation_test"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = skill_dir / f'test_{config_type.lower()}_config.txt'
    with open(config_file, 'w', encoding='utf-8') as f:
        f.write(config_text.strip())
    
    print(f"[+] 测试配置文件: {config_file}")
    print(f"[+] 网络拓扑文件: {topology_path}")
    print(f"[+] 模块目录: {modules_dir}")
    print(f"[+] 输出目录: {output_dir}")
    print()
    
    result = subprocess.run([
        sys.executable, str(skill_dir / 'config_generator.py'),
        '--topology', str(topology_path),
        '--config', str(config_file),
        '--output-dir', str(output_dir),
        '--modules-dir', str(modules_dir),
        '--target-device', 'APV0'
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✓ 配置生成成功!")
        print("输出:")
        print(result.stdout)
    else:
        print("✗ 配置生成失败!")
        print("错误:")
        print(result.stderr)
    
    config_file.unlink(missing_ok=True)

def main():
    print("通用配置自动化生成器测试")
    print("="*70)
    
    run_test("SDNS", SAMPLE_SDNS_CONFIG)
    run_test("Firewall", SAMPLE_FIREWALL_CONFIG)
    run_test("Routing", SAMPLE_ROUTING_CONFIG)
    
    print("\n" + "="*70)
    print("所有测试完成!")
    print(f"输出文件已保存到: {Path(__file__).resolve().parents[5] / 'workspace' / 'outputs' / 'config_automation_test'}")

if __name__ == '__main__':
    main()