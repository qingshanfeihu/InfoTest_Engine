"""E 列对象规范化（ef = entity/fixture spec）。

把 .py 先例代码里的对象名（设备别名 Seg0/APV0_C/apv_0、check_point、主机名等）
归一成 xlsx 标准 E 列对象名（APV_0 / check_point / test_env / time）。corpus 解析 .py
先例时用它还原 E 列；framework_sync 同步时一并采集 conftest 的 fixture 别名。

设计红线：**不写死某个测试床的 {APV_0, APV_1} 具体集合**——按结构规则归一
（APV+序号 → APV_<n>；断言/环境/等待关键字保留；其余主机名归 test_env）。
这样换测试床/加设备不用改代码。无法归类的返回 None（调用方跳过该行）。
"""
from __future__ import annotations

import re
from functools import lru_cache

# xlsx E 列的标准对象类别（结构性枚举，非某测试床专属）
_CHECK = "check_point"
_ENV = "test_env"
_TIME = "time"

# 断言/环境/等待 关键字 → 标准类别（结构语义，与具体设备无关）
_KEYWORD_CANON = {
    "check_point": _CHECK, "checkpoint": _CHECK, "check": _CHECK,
    "test_env": _ENV, "testenv": _ENV, "env": _ENV,
    "time": _TIME, "sleep": _TIME, "wait": _TIME,
}

# 被测设备别名的形态：APV / Seg(ment) / DUT + 可选序号/后缀（APV0_C、Seg0、apv_0、DUT1…）
_DEVICE_RE = re.compile(r"^(?:apv|seg(?:ment)?|dut)[_-]?(\d+)?", re.IGNORECASE)


class EfSpec:
    """E 列对象规范化器。device_aliases 可由 conftest fixture 采集补充（运行时注入）。"""

    def __init__(self, device_aliases: dict[str, str] | None = None):
        # 额外的"别名→标准名"映射（如 conftest 里 routera→test_env），可选注入
        self.device_aliases = {k.lower(): v for k, v in (device_aliases or {}).items()}

    def canon_object(self, obj: str | None) -> str | None:
        """把先例里的对象名归一成 xlsx 标准 E 列对象。无法归类返回 None。"""
        if not obj:
            return None
        raw = obj.strip().strip("\"'")
        if not raw:
            return None
        low = raw.lower()
        # 1) 显式注入的别名优先
        if low in self.device_aliases:
            return self.device_aliases[low]
        # 2) 断言/环境/等待 关键字
        if low in _KEYWORD_CANON:
            return _KEYWORD_CANON[low]
        # 3) 被测设备别名 → APV_<序号>（无序号默认 0）
        m = _DEVICE_RE.match(low)
        if m:
            idx = m.group(1) if m.group(1) is not None else "0"
            return f"APV_{idx}"
        # 4) 其余按主机名归到 test_env（routera/clientc 等测试机）
        if re.match(r"^[a-z][a-z0-9_]*$", low):
            return _ENV
        return None


@lru_cache(maxsize=1)
def get_ef_spec() -> EfSpec:
    """进程级单例（corpus 解析先例时复用）。"""
    return EfSpec()
