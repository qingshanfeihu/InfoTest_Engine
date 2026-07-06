"""应用版本单一读取点(pyproject 为源)。

三个展示位(TUI 欢迎横幅 / /version 命令 / CLI --version)曾各自硬编码,随发布
漂移(1.0.4/1.0.5 并存实证)。editable 安装下 ``importlib.metadata`` 停留在
``pip install -e`` 时刻的值,pyproject.toml 才是源码树的即时事实源——优先读它,
非源码树部署(wheel)再回落包元数据。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def app_version() -> str:
    try:
        import tomllib
        pp = Path(__file__).resolve().parents[2] / "pyproject.toml"
        if pp.is_file():
            v = (tomllib.loads(pp.read_text(encoding="utf-8"))
                 .get("project", {}).get("version"))
            if v:
                return str(v)
    except Exception:  # noqa: BLE001
        pass
    try:
        from importlib.metadata import version
        return version("infotest-engine")
    except Exception:  # noqa: BLE001
        return "unknown"
