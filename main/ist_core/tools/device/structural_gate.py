"""v2 结构约束门（correct-by-construction，论文命题3.18 / PLAN_footprint_v2_compile.md §2.2）。

与 grade(LLM 语义自评)**独立**的确定性强制——执行**结构约束**，不碰**骨架选择**：
- ① 命令头∈手册 allowlist（footprint 已有的命令集）——挡幻觉/越界命令；
- ② 断言对象挂在某前序观测算子（show/dig 产出回显的步骤）的值域上——根治 655203 悬空断言；
- ③ 绑定 IP∈env_facts 可达表（已由 emit_xlsx_tool._gate_unreachable_ips 做，这里不重复）。

红线（§七）：只执行**与意图无关的类型规则**（命令合法性、断言非悬空、IP 可达），
绝不替 LLM 决定"测什么/什么命令序列/什么断言形态"（H_G≠0 的语义决策永远 LLM）。

只在 v2 编译链启用（qa_emit_xlsx(strict_structural=True)）；v1 默认 False，行为零变化。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 命令操作前缀（与 footprint extractor._OP_PREFIXES 对齐）：剥掉再取命令主体 token
_OP_PREFIXES = ("no", "show", "clear")
# 参数记法 / 具体值 token：<x> [x] {a|b}、纯数字、IP、引号串 → 不是命令主体 token
_VALUE_TOK_RE = re.compile(r"^([<\[{].*|.*[|].*|\d.*|[\"'].*|.*\.\d+.*)$")
# 观测算子：check_point 校验的是“上一个非 check_point 步骤”的回显输出。
# 产出可匹配回显的算子：test_env 触发（dig/query）、APV 的 show/统计类命令。
# 用词边界匹配（避免 "listener" 命中 "list"、"display" 误伤等子串假阳性）。
_OBSERVE_RE = re.compile(
    r"\b(show|statistics|stat|display|dig|nslookup|get|list)\b", re.IGNORECASE
)


@dataclass
class StructuralViolation:
    code: str          # cmd_not_in_allowlist | dangling_assertion
    detail: str
    step_index: int = -1


@dataclass
class StructuralResult:
    ok: bool = True
    violations: list[StructuralViolation] = field(default_factory=list)

    def add(self, code: str, detail: str, step_index: int = -1) -> None:
        self.ok = False
        self.violations.append(StructuralViolation(code, detail, step_index))

    def render(self, autoid: str) -> str:
        lines = [f"case {autoid} 违反结构约束（correct-by-construction 门，与 grade 独立）："]
        for v in self.violations:
            loc = f"step[{v.step_index}] " if v.step_index >= 0 else ""
            lines.append(f"  - [{v.code}] {loc}{v.detail}")
        lines.append(
            "\n这些是与意图无关的**结构**错误（命令合法性 / 断言是否悬空），"
            "确定性可判、必须改对——不是骨架选择问题。修正后重新 emit。"
        )
        return "\n".join(lines)


def _command_head_tokens(cmd: str) -> list[str]:
    """从一条 CLI 命令取命令主体 token 序列（剥 no/show/clear 前缀、剥参数值）。

    "sdns listener 172.16.34.70 53" → ["sdns","listener"]
    "no slb real http rs1"          → ["slb","real","http"]
    "show sdns service status"      → ["sdns","service","status"]
    """
    toks = cmd.strip().split()
    while toks and toks[0].lower() in _OP_PREFIXES:
        toks = toks[1:]
    out: list[str] = []
    for t in toks:
        tl = t.strip().lower()
        if not tl:
            continue
        # 命令主体只取连续的字母 token；遇到第一个参数值 token 即停
        if not re.match(r"^[a-z][a-z0-9_-]*$", tl) or _VALUE_TOK_RE.match(tl):
            break
        out.append(tl)
    return out


def _load_allowlist_prefixes() -> tuple[set[str], set[str]]:
    """从 footprint 知识树取命令 allowlist。

    返回 (full_command_keys, module_roots)：
    - full_command_keys: 所有节点 feature_id 的点分形式（如 "sdns.listener"），
      以及每个节点 cli.commands 里命令的主体 token 路径；
    - module_roots: 一级模块名（feature_id 首 token，如 "sdns"/"slb"）。

    footprint 缺失/空 → 返回空集（调用方据此降级为不拦，避免误杀）。
    """
    full: set[str] = set()
    roots: set[str] = set()
    try:
        from main.ist_core.memory.footprint import get_footprint_index
        idx = get_footprint_index()
        for fid in idx.list_nodes():
            full.add(fid)
            roots.add(fid.split(".")[0])
    except Exception as exc:  # noqa: BLE001
        logger.debug("structural_gate 读 footprint 失败: %s", exc)
    return full, roots


def _check_command_allowlist(steps: list, init: str, result: StructuralResult) -> None:
    """命令头∈allowlist：APV 配置步骤 + init 的命令主体 token 路径须命中 footprint。

    分级判定（防 footprint 文法不全误杀，§八风险）：
    - footprint 空 → 整体跳过（不拦）；
    - 命令所属**一级模块**（首 token）不在 footprint 任何模块里 → 判违规（明显越界/幻觉）；
    - 模块在、但具体命令路径不在 → 只 logger 记录、不拦（footprint 可能没覆盖到该子命令）。
    """
    full, roots = _load_allowlist_prefixes()
    if not roots:
        return  # footprint 不可用 → 降级不拦

    def _check_one(cmd: str, idx: int) -> None:
        head = _command_head_tokens(cmd)
        if not head:
            return
        module = head[0]
        if module not in roots:
            result.add(
                "cmd_not_in_allowlist",
                f"命令 {cmd!r} 的模块 {module!r} 不在手册命令树任何模块中"
                f"（已知模块: {', '.join(sorted(roots))}）——疑似越界/幻觉命令。",
                idx,
            )

    # init 可能多行
    for line in (init or "").splitlines():
        line = line.strip()
        if line:
            _check_one(line, -1)
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        e = str(s.get("E", "")).strip()
        f = str(s.get("F", "")).strip()
        if e.startswith("APV") and f in ("cmd_config", "cmds_config"):
            for line in str(s.get("G", "") or "").splitlines():
                line = line.strip()
                if line:
                    _check_one(line, i)


def _is_observation_step(step: dict) -> bool:
    """该步骤是否产出可被 check_point 文本匹配的回显（观测算子）。

    test_env 触发（dig/clientc/routera 等）天然产出回显；APV 的 show/统计类命令产出回显；
    APV 的纯配置（cmd_config 写配置）不产回显，不算观测算子。
    """
    e = str(step.get("E", "")).strip()
    f = str(step.get("F", "")).strip()
    g = str(step.get("G", "") or "")
    if e == "test_env":
        return True  # dig/clientc/routera 等触发都回显
    if e.startswith("APV"):
        return bool(_OBSERVE_RE.search(f) or _OBSERVE_RE.search(g))
    return False


def _check_dangling_assertions(steps: list, result: StructuralResult) -> None:
    """断言非悬空：每个 check_point 前必须存在**某个前序观测算子步骤**产出可匹配的回显。

    框架契约：check_point 校验“上一个非 check_point 步骤”的输出。若某 check_point 之前
    最近的非 check_point 步骤不是观测算子（如紧跟在一条写配置后、或开篇就断言），
    则断言无回显可匹配 → 悬空 → 上机 Hit=0 必 fail（655203 崩溃类）。与意图无关、机械可判。
    """
    seen_observation = False
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        e = str(s.get("E", "")).strip()
        if e == "check_point":
            if not seen_observation:
                result.add(
                    "dangling_assertion",
                    "该断言之前没有任何观测算子步骤（show/dig/统计类产出回显）"
                    "——断言无输出可匹配，上机 Hit=0 必 fail。"
                    "在断言前加一个产出回显的观测步骤（如 show / dig）。",
                    i,
                )
            # check_point 不改变 seen_observation（它消费上一步输出，不产出新回显）
        else:
            seen_observation = _is_observation_step(s)


def check_structural_constraints(autoid: str, steps: list, init: str = "") -> StructuralResult:
    """v2 结构约束门入口：命令 allowlist + 断言非悬空（IP 可达由 emit 既有门做）。

    返回 StructuralResult；ok=False 时 emit 应拒绝并把 render() 反馈给 draft 让它改。
    """
    result = StructuralResult()
    if not isinstance(steps, list):
        return result
    _check_command_allowlist(steps, init, result)
    _check_dangling_assertions(steps, result)
    return result

