"""测试用例编译器单一事实源（Stage A：去硬编码）。

消除审计发现的 34+ 处硬编码（IP / 路径 / 口令 / build 名 / 模块名 / xlsx 行号 /
autoid 计划 / 白名单），收口到一个配置对象。三层优先级（高→低）：

  1. 环境变量（`IST_*` 前缀，运行时覆盖）
  2. `runtime/compiler_config.json`（可选，落盘配置；不入 git，含敏感项）
  3. 代码内安全默认（非敏感：路径骨架 / 列号 / 拓扑模板）

敏感项（跳转机口令 / MySQL 口令）**只**从 env 或 runtime 配置读，代码默认一律空，
绝不硬编码明文。读取时按 key 名引用，不回显值。

跳转机侧（`device_mcp_server/`，Py3.8 离线）不导入本模块——它有自己的常量来源
（部署时由 env / 配置注入），本模块服务 IST-Core 本地侧（3.11）。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "runtime" / "compiler_config.json"


def _load_file_config() -> dict:
    """读 runtime/compiler_config.json（缺失/损坏→空 dict，不挂）。"""
    try:
        if _CONFIG_PATH.is_file():
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("配置文件读取/解析失败: %s", _CONFIG_PATH, exc_info=True)
    return {}


def _pick(env_key: str, file_cfg: dict, file_key: str, default: Any) -> Any:
    """三层取值：env > 文件 > 默认。空串视为未设置。"""
    v = os.environ.get(env_key)
    if v is not None and str(v).strip() != "":
        return v
    if file_key in file_cfg and file_cfg[file_key] not in (None, ""):
        return file_cfg[file_key]
    return default


@dataclass
class JumphostConfig:
    """跳转机 SSH 接入（口令敏感，仅 env/文件，默认空）。"""

    host: str = "10.4.127.103"
    user: str = "test"
    apv_src: str = "/home/test/apv_src"
    server_path: str = "/home/test/mcp_server/server.py"
    py38: str = "/home/test/apv_src/.python3.8/bin/python"
    password_env: str = "IST_JUMPHOST_PASS"   # 口令从此 env 读，不落盘

    @property
    def server_cmd(self) -> str:
        return f"cd {self.apv_src} && {self.py38} {self.server_path}"


@dataclass
class XlsxLayout:
    """xlsx 模板结构（动态探测兜底默认；探测优先，见 detect_layout）。"""

    header_row: int = 28        # R28 表头（A-I）
    data_start: int = 29        # R29 数据区起始
    header_anchor: str = "自动化ID"   # A 列表头锚点文本（探测用）
    n_cols: int = 9             # A..I


@dataclass
class CompilerConfig:
    """编译器顶层配置（单一事实源）。"""

    # 目标固件
    build: str = "InfosecOS_Beta_APV_HG_K_10_5_0_568"
    target_version: str = "10.5.0.568"

    # staging 模块归属（sdns 测试床）
    staging_module: str = "sdns"

    # MySQL 结果库（口令敏感；host 可被 conf 覆盖，见 result_db）
    mysql_host: str = ""               # 空=从跳转机 conf [other] mysql_ip 读
    mysql_db: str = "smoke_test"
    mysql_user: str = "root"
    mysql_password_env: str = "IST_MYSQL_PASS"   # 口令优先 env，缺则框架内置约定

    jumphost: JumphostConfig = field(default_factory=JumphostConfig)
    xlsx: XlsxLayout = field(default_factory=XlsxLayout)

    # 文件级前置 init：**默认空,不写死任何命令**。
    # agent 必须自己查清要测的功能该建什么前置(看该模块 conftest 清的是什么、看同类先例 init、grep 手册),在 init 里自建全。
    # 仅当用户在 config 文件里显式配了 default_init(某测试床固定拓扑)才用它。
    default_init_lines: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "CompilerConfig":
        """三层加载：env > runtime/compiler_config.json > 默认。"""
        fc = _load_file_config()
        jh_fc = fc.get("jumphost", {}) or {}
        xl_fc = fc.get("xlsx", {}) or {}

        jh = JumphostConfig(
            host=_pick("IST_JUMPHOST_HOST", jh_fc, "host", JumphostConfig.host),
            user=_pick("IST_JUMPHOST_USER", jh_fc, "user", JumphostConfig.user),
            apv_src=_pick("IST_APV_SRC", jh_fc, "apv_src", JumphostConfig.apv_src),
            server_path=_pick("IST_MCP_SERVER_PATH", jh_fc, "server_path", JumphostConfig.server_path),
            py38=_pick("IST_JUMPHOST_PY38", jh_fc, "py38", JumphostConfig.py38),
        )
        xl = XlsxLayout(
            header_row=int(_pick("IST_XLSX_HEADER_ROW", xl_fc, "header_row", XlsxLayout.header_row)),
            data_start=int(_pick("IST_XLSX_DATA_START", xl_fc, "data_start", XlsxLayout.data_start)),
            header_anchor=_pick("IST_XLSX_HEADER_ANCHOR", xl_fc, "header_anchor", XlsxLayout.header_anchor),
        )
        init = fc.get("default_init")
        if not isinstance(init, list) or not init:
            init = None
        return cls(
            build=_pick("IST_DEVICE_BUILD", fc, "build", cls.build),
            target_version=_pick("IST_TARGET_VERSION", fc, "target_version", cls.target_version),
            staging_module=_pick("IST_STAGING_MODULE", fc, "staging_module", cls.staging_module),
            mysql_host=_pick("IST_MYSQL_HOST", fc, "mysql_host", cls.mysql_host),
            mysql_db=_pick("IST_MYSQL_DB", fc, "mysql_db", cls.mysql_db),
            mysql_user=_pick("IST_MYSQL_USER", fc, "mysql_user", cls.mysql_user),
            jumphost=jh,
            xlsx=xl,
            default_init_lines=(init or list(cls().default_init_lines)),
        )

    def default_init_g(self) -> str:
        """文件级前置块（cmds_config 的 G 列：每行前导 4 空格）。

        **默认空**——不写死任何模块命令。agent 必须自建 init(它先查清要测模块该建什么)。
        仅当用户在 config 文件显式配了 default_init 时返回它(某测试床固定拓扑)。
        """
        return "\n".join("    " + line for line in self.default_init_lines)

    def to_dict(self) -> dict:
        return asdict(self)


_CACHED: Optional[CompilerConfig] = None


def get_config(reload: bool = False) -> CompilerConfig:
    """进程级单例。reload=True 强制重读（测试 / 配置热更）。"""
    global _CACHED
    if _CACHED is None or reload:
        _CACHED = CompilerConfig.load()
    return _CACHED


# ── 自动化环境池（多跳板机并行 runner）────────────────────────────────────────
# 4 套**独立设备床**的并行环境(2026-06-24 实测确认:跳板机/OS/凭据一致,框架走 Path A
# 克隆旧 mcp_server 到新机)。每个环境 = 一台跳板机 + 各自的框架 stdio MCP server。
# 默认**只用现役 103**(零行为变化);``IST_ENV_POOL_ENABLED`` 真值才启用 4 机池。
# 设备床是「隔离但地址相同」的克隆,故 4 个环境共用同一份 network_topology.json。

# 默认 4 机(末位=环境 id 后缀)；可被 IST_ENV_POOL_HOSTS(逗号分隔)或 runtime 配置覆盖。
_DEFAULT_POOL_HOSTS = ["10.4.127.103", "10.4.127.93", "10.4.127.79", "10.4.127.105"]


@dataclass
class Environment:
    """单个自动化运行环境（跳板机 + 框架 stdio MCP server）。口令仍从 ``pass_env`` 读,不落盘。"""

    id: str
    jumphost: str
    ssh_user: str = "test"
    ssh_port: int = 22
    pass_env: str = "IST_JUMPHOST_PASS"
    apv_src: str = "/home/test/apv_src"
    server_path: str = "/home/test/mcp_server/server.py"
    py38: str = "/home/test/apv_src/.python3.8/bin/python"
    mcp_url: str = ""                          # http://<host>:8000/mcp（HTTP 传输备用，当前走 stdio）
    topology: str = "network_topology.json"    # knowledge/data/auto_env/ 下的拓扑文件（克隆环境共用）

    @property
    def server_cmd(self) -> str:
        return f"cd {self.apv_src} && {self.py38} {self.server_path}"


def _pool_enabled() -> bool:
    """环境池总开关。默认**关**（只用现役单环境 103，零行为变化）；置真值才启用 4 机池。"""
    return (os.environ.get("IST_ENV_POOL_ENABLED") or "0").strip().lower() in (
        "1", "true", "on", "yes",
    )


def load_environments() -> list["Environment"]:
    """返回环境列表。

    - 池**关**（默认）：返回单环境 = 现役跳板机（沿用 JumphostConfig，行为同今天）。
    - 池**开**：runtime/compiler_config.json 的 ``environments`` 列表优先；否则
      ``IST_ENV_POOL_HOSTS``（逗号分隔）；再否则内置 4 机默认。所有环境沿用现役
      JumphostConfig 的 user/路径（Path A 克隆，完全一致）。
    """
    cfg = get_config()
    jh = cfg.jumphost

    def _mk(host: str) -> Environment:
        host = host.strip()
        return Environment(
            id=f"env-{host.rsplit('.', 1)[-1]}",
            jumphost=host, ssh_user=jh.user, pass_env=jh.password_env,
            apv_src=jh.apv_src, server_path=jh.server_path, py38=jh.py38,
            mcp_url=f"http://{host}:8000/mcp",
        )

    if not _pool_enabled():
        return [_mk(jh.host)]

    fc = _load_file_config()
    raw = fc.get("environments")
    if isinstance(raw, list) and raw:
        out: list[Environment] = []
        for item in raw:
            if not isinstance(item, dict) or not item.get("jumphost"):
                continue
            host = str(item["jumphost"]).strip()
            out.append(Environment(
                id=str(item.get("id") or f"env-{host.rsplit('.', 1)[-1]}"),
                jumphost=host,
                ssh_user=str(item.get("ssh_user") or jh.user),
                ssh_port=int(item.get("ssh_port") or 22),
                pass_env=str(item.get("pass_env") or jh.password_env),
                apv_src=str(item.get("apv_src") or jh.apv_src),
                server_path=str(item.get("server_path") or jh.server_path),
                py38=str(item.get("py38") or jh.py38),
                mcp_url=str(item.get("mcp_url") or f"http://{host}:8000/mcp"),
                topology=str(item.get("topology") or "network_topology.json"),
            ))
        if out:
            return out

    env_hosts = (os.environ.get("IST_ENV_POOL_HOSTS") or "").strip()
    hosts = [h.strip() for h in env_hosts.split(",") if h.strip()] if env_hosts else list(_DEFAULT_POOL_HOSTS)
    # 去重保序
    seen: set[str] = set()
    hosts = [h for h in hosts if not (h in seen or seen.add(h))]
    return [_mk(h) for h in hosts]


def detect_xlsx_layout(grid: list[list[Any]], cfg: Optional[CompilerConfig] = None) -> XlsxLayout:
    """从已读 grid 动态探测表头行/数据起始行（不写死 R28/R29）。

    判据：A 列等于 header_anchor（如 '自动化ID'）的行 = 表头行，下一行 = 数据起始。
    探测失败回退到 cfg 默认（兜底，保持旧行为）。grid 为 0-based 行列表。
    """
    cfg = cfg or get_config()
    anchor = cfg.xlsx.header_anchor
    for idx, row in enumerate(grid):
        a = row[0] if row else None
        if a is not None and str(a).strip() == anchor:
            # grid 0-based → openpyxl 1-based 行号 = idx + 1
            header_1based = idx + 1
            return XlsxLayout(
                header_row=header_1based,
                data_start=header_1based + 1,
                header_anchor=anchor,
                n_cols=cfg.xlsx.n_cols,
            )
    return cfg.xlsx
