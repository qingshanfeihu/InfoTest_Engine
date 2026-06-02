"""配置模块目录

包含各种网络设备配置类型的处理模块。
每个模块必须继承 ConfigModule 基类并实现标准接口。

模块命名规范：
- 文件名: <module_name>_module.py
- 类名: <ModuleName>Module
- MODULE_NAME 属性: 小写模块名
- CONFIG_TYPE 属性: 配置类型描述
"""

from .sdns_module import SdnsModule
from .slb_module import SlbModule

__all__ = ['SdnsModule', 'SlbModule']