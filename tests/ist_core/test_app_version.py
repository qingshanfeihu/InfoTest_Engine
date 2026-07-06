"""app_version:pyproject 单一事实源(editable 安装下 metadata 滞后于源码树)。"""
from main.common.version import app_version


def test_app_version_reads_pyproject_live():
    v = app_version()
    assert v not in ("", "unknown")
    from pathlib import Path
    import tomllib
    expect = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert v == expect      # 与源码树 pyproject 即时一致,不锁具体值
