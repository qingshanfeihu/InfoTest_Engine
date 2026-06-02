#!/usr/bin/env python3
"""模块管理器

管理配置处理模块的注册、发现和调用。
"""

import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Type


class ConfigModule:
    """配置模块基类，所有配置模块必须继承此类"""
    
    MODULE_NAME = "base"
    CONFIG_TYPE = "unknown"
    
    def identify(self, config_text: str) -> bool:
        """判断是否匹配该模块"""
        return False
    
    def parse(self, config_text: str) -> dict:
        """解析配置为结构化数据"""
        return {}
    
    def generate_config(self, parsed_data: dict, ip_mapping: dict, **kwargs) -> str:
        """生成配置脚本"""
        return ""
    
    def generate_verify(self, parsed_data: dict, ip_mapping: dict, **kwargs) -> str:
        """生成验证脚本"""
        return ""
    
    def get_variable_map(self) -> dict:
        """获取模块变量映射"""
        return {}


class ModuleManager:
    """配置模块管理器"""
    
    def __init__(self):
        self.modules: List[Type[ConfigModule]] = []
    
    def register_module(self, module_class: Type[ConfigModule]):
        """注册配置模块"""
        self.modules.append(module_class)
        print(f"[+] 已注册配置模块: {module_class.MODULE_NAME} ({module_class.CONFIG_TYPE})")
    
    def discover_modules(self, modules_dir: str):
        """自动发现并注册模块"""
        modules_path = Path(modules_dir)
        if not modules_path.exists():
            return
        
        for file in modules_path.glob("*_module.py"):
            module_name = file.stem.replace("_module", "")
            module_path = f"modules.{file.stem}"
            
            try:
                spec = importlib.util.spec_from_file_location(module_path, str(file))
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if isinstance(attr, type) and issubclass(attr, ConfigModule) and attr != ConfigModule:
                            self.register_module(attr)
            except Exception as e:
                print(f"[-] 加载模块失败 {module_name}: {e}")
    
    def identify_module(self, config_text: str) -> Optional[ConfigModule]:
        """根据配置文本识别对应的模块"""
        for module_class in self.modules:
            instance = module_class()
            if instance.identify(config_text):
                return instance
        return None
    
    def get_all_modules(self) -> List[str]:
        """获取所有已注册模块名称"""
        return [m.MODULE_NAME for m in self.modules]