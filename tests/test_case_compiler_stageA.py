"""测试用例编译器 v2 — 阶段 A 去硬编码 + 单一事实源回归套件。

固化阶段 A 的不变量：

- **config 三层优先级**：env > runtime/compiler_config.json > 代码默认。
- **敏感项默认空**：跳转机/MySQL 口令绝不硬编码明文（password_env 指向 env key）。
- **xlsx 结构动态探测**：从模板表头锚点定位 header/data 行，不写死 R28/R29；
  探测失败回退默认。
- **default_init_g**：文件级前置块每行前导 4 空格。
- **result_db.bare_autoid / query_results 凭据外置**：env 覆盖优先。

不触网、不连设备、不依赖 pymysql（query_results 的 DB 路径在跳转机侧）。
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from main.case_compiler import config as cc_config
from main.case_compiler.config import (
    CompilerConfig, JumphostConfig, XlsxLayout, get_config, detect_xlsx_layout,
)


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """每个测试前后清掉 config 单例，避免 env 串扰。"""
    cc_config._CACHED = None
    yield
    cc_config._CACHED = None


# ── 三层优先级 ───────────────────────────────────────────────────────


def test_defaults_when_no_env_no_file(tmp_path, monkeypatch):
    """无 env、无文件 → 代码默认。"""
    for k in ("IST_DEVICE_BUILD", "IST_JUMPHOST_HOST", "IST_XLSX_HEADER_ROW"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(cc_config, "_CONFIG_PATH", tmp_path / "nonexistent.json")
    cfg = get_config(reload=True)
    assert cfg.build == "InfosecOS_Beta_APV_HG_K_10_5_0_568"
    assert cfg.jumphost.host == "10.4.127.103"
    assert cfg.xlsx.header_row == 28
    assert cfg.xlsx.data_start == 29


def test_file_config_overrides_default(tmp_path, monkeypatch):
    """runtime/compiler_config.json 覆盖代码默认。"""
    for k in ("IST_DEVICE_BUILD", "IST_JUMPHOST_HOST"):
        monkeypatch.delenv(k, raising=False)
    cfgfile = tmp_path / "compiler_config.json"
    cfgfile.write_text(
        '{"build": "BUILD_FROM_FILE", "jumphost": {"host": "1.2.3.4"}, '
        '"xlsx": {"header_row": 10, "data_start": 11}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(cc_config, "_CONFIG_PATH", cfgfile)
    cfg = get_config(reload=True)
    assert cfg.build == "BUILD_FROM_FILE"
    assert cfg.jumphost.host == "1.2.3.4"
    assert cfg.xlsx.header_row == 10
    assert cfg.xlsx.data_start == 11


def test_env_overrides_file_and_default(tmp_path, monkeypatch):
    """env 优先级最高，盖过文件与默认。"""
    cfgfile = tmp_path / "compiler_config.json"
    cfgfile.write_text('{"build": "BUILD_FROM_FILE"}', encoding="utf-8")
    monkeypatch.setattr(cc_config, "_CONFIG_PATH", cfgfile)
    monkeypatch.setenv("IST_DEVICE_BUILD", "BUILD_FROM_ENV")
    monkeypatch.setenv("IST_JUMPHOST_HOST", "9.9.9.9")
    cfg = get_config(reload=True)
    assert cfg.build == "BUILD_FROM_ENV"
    assert cfg.jumphost.host == "9.9.9.9"


def test_empty_env_falls_through(tmp_path, monkeypatch):
    """空串 env 视为未设置，回退到下一层。"""
    monkeypatch.delenv("IST_DEVICE_BUILD", raising=False)
    monkeypatch.setattr(cc_config, "_CONFIG_PATH", tmp_path / "none.json")
    monkeypatch.setenv("IST_DEVICE_BUILD", "")
    cfg = get_config(reload=True)
    assert cfg.build == "InfosecOS_Beta_APV_HG_K_10_5_0_568"


# ── 敏感项默认空 ─────────────────────────────────────────────────────


def test_secrets_never_hardcoded():
    """口令字段在配置对象里绝不是明文——只暴露 password_env key 名。"""
    cfg = CompilerConfig()
    assert cfg.jumphost.password_env == "IST_JUMPHOST_PASS"
    assert cfg.mysql_password_env == "IST_MYSQL_PASS"
    # 配置对象本身不含口令值字段
    d = cfg.to_dict()
    flat = str(d).lower()
    assert "click1" not in flat
    assert "password" not in [k.lower() for k in d.keys()]


# ── 派生属性 ─────────────────────────────────────────────────────────


def test_server_cmd_composed():
    jh = JumphostConfig(apv_src="/x/apv", py38="/x/py", server_path="/x/srv.py")
    assert jh.server_cmd == "cd /x/apv && /x/py /x/srv.py"


def test_default_init_g_indented():
    # default_init 默认空（不写死任何模块命令——消除 sdns 硬编码，见 ist-compile 架构）。
    cfg = CompilerConfig()
    assert cfg.default_init_g() == ""
    # 仅当显式配置 default_init 时才返回内容，且每行 4 空格缩进。
    cfg2 = CompilerConfig(default_init_lines=["foo on", "bar set 1"])
    lines = cfg2.default_init_g().splitlines()
    assert len(lines) == 2
    assert all(ln.startswith("    ") for ln in lines)
    assert lines[0].strip() == "foo on"


# ── xlsx 结构动态探测 ────────────────────────────────────────────────


def test_detect_layout_finds_anchor():
    """A 列锚点在第 5 行（0-based idx=4）→ header_row=5, data_start=6。"""
    grid = [
        ["说明", None], ["x", None], ["y", None], ["z", None],
        ["自动化ID", "优先级"],   # idx=4 → 1-based row 5
        ["203...", "P1"],
    ]
    layout = detect_xlsx_layout(grid)
    assert layout.header_row == 5
    assert layout.data_start == 6


def test_detect_layout_fallback_when_no_anchor():
    """无锚点 → 回退到 cfg 默认（保持旧行为，不挂）。"""
    grid = [["a"], ["b"], ["c"]]
    cfg = get_config(reload=True)
    layout = detect_xlsx_layout(grid, cfg)
    assert layout.header_row == cfg.xlsx.header_row
    assert layout.data_start == cfg.xlsx.data_start


def test_detect_layout_custom_anchor(monkeypatch, tmp_path):
    """自定义锚点（如英文表头）也能探测。"""
    monkeypatch.setattr(cc_config, "_CONFIG_PATH", tmp_path / "none.json")
    monkeypatch.setenv("IST_XLSX_HEADER_ANCHOR", "AutoID")
    cfg = get_config(reload=True)
    grid = [["x"], ["AutoID", "Pri"], ["1", "P1"]]
    layout = detect_xlsx_layout(grid, cfg)
    assert layout.header_row == 2
    assert layout.data_start == 3


# ── result_db 凭据外置 ───────────────────────────────────────────────


def test_result_db_creds_env_override(monkeypatch):
    """query_results 的凭据可被 env 覆盖（不连 DB，只验证读取逻辑）。

    通过 mock pymysql.connect 捕获实际传入的 user/passwd/db。
    """
    import sys
    import types
    captured = {}

    fake_pymysql = types.ModuleType("pymysql")

    class _FakeConn:
        def cursor(self):
            class _Cur:
                def execute(self, *a, **k): pass
                def fetchall(self): return []
                def close(self): pass
            return _Cur()
        def close(self): pass

    def _connect(**kw):
        captured.update(kw)
        return _FakeConn()

    fake_pymysql.connect = _connect
    monkeypatch.setitem(sys.modules, "pymysql", fake_pymysql)
    monkeypatch.setenv("IST_MYSQL_USER", "envuser")
    monkeypatch.setenv("IST_MYSQL_PASS", "envpass")
    monkeypatch.setenv("IST_MYSQL_DB", "envdb")

    from main.device_mcp_server.result_db import query_results
    query_results("10.0.0.1", "SomeBuild", ["123"])
    assert captured["user"] == "envuser"
    assert captured["passwd"] == "envpass"
    assert captured["db"] == "envdb"
