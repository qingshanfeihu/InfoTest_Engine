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
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "runtime" / "compiler_config.json"


def _load_file_config() -> dict:
    """读 runtime/compiler_config.json（缺失/损坏→空 dict，不挂）。"""
    try:
        if _CONFIG_PATH.is_file():
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
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

    # 配置生效等待秒数（W-settle：配置变更后断言前插入 time/sleep；防 rr 轮转/状态刷新未完成即断言）
    settle_seconds: int = 5

    # rr/wrr 统计断言重写开关（report-only 增强：把脆弱的逐次绝对 IP 断言换成池级 Hit 分布断言）。
    # 仅对识别到 sdns host method rr|wrr 的 case 生效，非 rr/wrr case 一律 no-op（向后兼容）。
    rr_rewrite_enabled: bool = True
    # 重写 Hit 容差（多核抖动余量）+ 模式（tolerance/exact/nonzero）。
    rr_rewrite_tolerance: int = 1
    rr_rewrite_mode: str = "tolerance"

    # 三确定性变换（assertion-fix / rr-rewrite / settle）的执行路由开关（Phase 2 双路）。
    # False（默认）→ 走 pipeline 内联调用（事实源仍是三个 .py，行为零变化）；
    # True → 经 skill_lib.verify_runner 调三技能 verify.py，逐字节等价（opt-in 等价证明）。
    use_skill_transforms: bool = False

    # 闸硬阻断开关（red line 落地）。False（默认）→ 五重闸 report-only（仅写 notes，行为零变化）；
    # True → validate_stage 对**非 passthrough（agent 合成）产物**的阻断类违规
    # （W6 无溯源断言 / W1-W3 / X2 / W4-W5 / X1 syntax_error）抛 GateBlocked，case 进 rejected 不上机。
    # passthrough（框架既验证原件）永不硬阻断。
    gate_hard_block: bool = False

    # Step D：无 passthrough 先例的 case 是否走合成路径（检索最近邻 + LLM 改编 + spec 定律）。
    # False（默认）→ 无先例直接 rejected（run_all 原 passthrough-only 语义，行为零变化）；
    # True → 路由到合成，让 agent 真正编写新用例（zhaiyq 时序类靠此解锁）。配合 gate_hard_block
    # 守 red line：合成产物的无溯源断言被 W6 拦。env IST_SYNTH_NO_PRECEDENT。
    synthesize_without_precedent: bool = False

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
        # 三确定性变换路由开关：env > 文件 > 默认（False），并强制成 bool。
        _ust = _pick("IST_USE_SKILL_TRANSFORMS", fc, "use_skill_transforms",
                     cls.use_skill_transforms)
        use_skill_transforms = (
            _ust if isinstance(_ust, bool)
            else str(_ust).strip().lower() in ("1", "true", "yes", "on")
        )
        # 闸硬阻断开关：env > 文件 > 默认（False），强制成 bool。
        _ghb = _pick("IST_GATE_HARD_BLOCK", fc, "gate_hard_block", cls.gate_hard_block)
        gate_hard_block = (
            _ghb if isinstance(_ghb, bool)
            else str(_ghb).strip().lower() in ("1", "true", "yes", "on")
        )
        # Step D 合成开关：env > 文件 > 默认（False），强制成 bool。
        _syn = _pick("IST_SYNTH_NO_PRECEDENT", fc, "synthesize_without_precedent",
                     cls.synthesize_without_precedent)
        synthesize_without_precedent = (
            _syn if isinstance(_syn, bool)
            else str(_syn).strip().lower() in ("1", "true", "yes", "on")
        )
        return cls(
            build=_pick("IST_DEVICE_BUILD", fc, "build", cls.build),
            target_version=_pick("IST_TARGET_VERSION", fc, "target_version", cls.target_version),
            staging_module=_pick("IST_STAGING_MODULE", fc, "staging_module", cls.staging_module),
            settle_seconds=int(_pick("IST_SETTLE_SECONDS", fc, "settle_seconds", cls.settle_seconds)),
            mysql_host=_pick("IST_MYSQL_HOST", fc, "mysql_host", cls.mysql_host),
            mysql_db=_pick("IST_MYSQL_DB", fc, "mysql_db", cls.mysql_db),
            mysql_user=_pick("IST_MYSQL_USER", fc, "mysql_user", cls.mysql_user),
            jumphost=jh,
            xlsx=xl,
            default_init_lines=(init or list(cls().default_init_lines)),
            use_skill_transforms=use_skill_transforms,
            gate_hard_block=gate_hard_block,
            synthesize_without_precedent=synthesize_without_precedent,
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
