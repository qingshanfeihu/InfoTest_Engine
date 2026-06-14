"""归纳技能质量契约静态门（A-B 闸晋升前的结构证据校验）。

A-B 闸是**行为**证据（设备首跑通过率）；质量契约是**结构**证据：强制归纳技能
继承同事手写技能的金标准纪律，并拦截已记录反模式（见 plan「归纳技能质量契约」节
与 memory/no-per-case-hardcoding.md）。两道门都过才晋升。

本模块只实现 plan 第一批四项静态检查（全部离线、确定性、零 LLM）：

  ① 逐 case 硬编码（**blocking**）——AST 解析 verify.py，发现「autoid 级长数字串
     字面量出现在分支 / 比较 / match 模式里」即拒。对应反模式 `if autoid == "778012"`。
  ② when_to_use 缺 TRIGGER / SKIP（**blocking**）——同事技能 TRIGGER+SKIP 范式缺一即拒。
  ③ 缺 verify_script 声明 / 文件不存在 / 不可解析（**blocking**）——无确定性离线校验脚本
     的技能不得入 A-B 闸（SkillsBench：缺确定性验证的自生成技能平均 -1.3pp）。
  ④ params 缺但 body 有疑似硬值（**minor**）——参数槽未声明却在 body 出现 IP / 长数字串
     等魔法字面量，提示去实例化不彻底（咨询级，不阻断）。

四条红线的落实方式：
  - **禁逐 case 硬编码**：① 用 `ast` 解析而非字符串匹配，且只看分支/比较/match 上下文，
    不误伤期望映射等数据字面量；判定算法对任意 autoid 通用（从不看具体 autoid 值）。
  - **禁正则猜语义**：本模块所有正则（数字串 / IP）只做**确定性词法识别已知格式**，
    不推断「这命令是什么意图」；TRIGGER/SKIP 走子串成员判定，亦为词法。
  - **确定性**：同输入同输出，纯静态分析，无运行时 grep / 随机。
  - **证据接地**：本门是结构门；命令的 empirical/manual 接地由 grounding.py 负责，
    不在本批次范围（保持模块单一职责）。

输入采用鸭子类型（dict 或带属性的对象，如 schema.SkillSpec），故本模块不 import
skill_lib 包内其它模块，可独立加载、独立测试。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional, Union

# ── 严重度常量 ────────────────────────────────────────────────────────
BLOCKING = "blocking"   # 命中即拒，不得入 A-B 闸
MINOR = "minor"         # 咨询级提示，不阻断晋升

# 契约规则码（稳定标识，供 ab_gate / 看板按码统计）
CODE_HARDCODED_CASE_ID = "HARDCODED_CASE_ID"            # ①
CODE_MISSING_TRIGGER = "MISSING_TRIGGER"                # ②
CODE_MISSING_SKIP = "MISSING_SKIP"                      # ②
CODE_MISSING_VERIFY_SCRIPT = "MISSING_VERIFY_SCRIPT"    # ③ 未声明
CODE_VERIFY_SCRIPT_NOT_FOUND = "VERIFY_SCRIPT_NOT_FOUND"        # ③ 文件不存在
CODE_VERIFY_SCRIPT_UNPARSEABLE = "VERIFY_SCRIPT_UNPARSEABLE"    # ③ 不可解析
CODE_UNPARAMETERIZED_HARDVALUE = "UNPARAMETERIZED_HARDVALUE"    # ④


# ── 词法识别器（仅做确定性格式识别，不推断语义）─────────────────────────
#
# autoid 在本项目恒为 6 位（778012/593516/...）。阈值取 ≥6 位精准命中 autoid 量级，
# 同时天然避开 4 位年份（2026）、≤5 位端口（80/443/8080/65535）等合法字面量，
# 把误报压到最低。这是「已知格式词法识别」，非语义推断。
_CASEID_DIGIT_RUN = re.compile(r"\d{6,}")

# 点分四段 IPv4 字面量（body 硬值嗅探用）。同为词法识别。
_IPV4_LITERAL = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


@dataclass
class Finding:
    """一条契约校验结论。

    severity == BLOCKING 拦截晋升；MINOR 仅提示。location 形如
    ``verify.py:42`` / ``when_to_use`` / ``body`` / ``skill``，evidence 为命中片段。
    """

    code: str
    severity: str
    message: str
    location: str = ""
    evidence: str = ""

    @property
    def is_blocking(self) -> bool:
        return self.severity == BLOCKING

    def __str__(self) -> str:
        loc = f" @{self.location}" if self.location else ""
        ev = f" :: {self.evidence}" if self.evidence else ""
        return f"[{self.severity.upper()}][{self.code}]{loc} {self.message}{ev}"


# ── 鸭子类型字段访问 ──────────────────────────────────────────────────

def _field_of(skill: Any, name: str, default: Any = None) -> Any:
    """从 dict 或带属性对象（schema.SkillSpec）统一取字段。"""
    if isinstance(skill, dict):
        return skill.get(name, default)
    return getattr(skill, name, default)


# ── ① 逐 case 硬编码 AST 检测 ─────────────────────────────────────────

def _caseid_in_literal(value: Any) -> Optional[str]:
    """若字面量看起来是 autoid 量级标识（≥6 位数字串），返回命中的数字串，否则 None。

    bool 是 int 子类，需先排除（True/False 不是 case-id）。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        digits = str(abs(value))
        return digits if len(digits) >= 6 else None
    if isinstance(value, str):
        m = _CASEID_DIGIT_RUN.search(value)
        return m.group(0) if m else None
    return None


def _iter_constants(node: ast.AST) -> Iterator[ast.Constant]:
    """遍历子树里的所有 Constant 节点（含 node 自身）。"""
    for n in ast.walk(node):
        if isinstance(n, ast.Constant):
            yield n


def _scan_hardcoded_caseids(tree: ast.AST, location_file: str) -> list[Finding]:
    """扫描 AST：autoid 级长数字串字面量出现在比较 / match 模式里 → 逐 case 硬编码。

    **只看分支 / 比较 / match 上下文**，刻意不看普通赋值与字典值，以免误伤
    expected_hits={"778012": 3} 这类合法期望数据；判定全程不依赖具体 autoid 取值，
    换一批用例仍成立（守「禁逐 case 硬编码」红线）。
    """
    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()  # (lineno, caseid) 去重

    def _record(const_node: ast.Constant, caseid: str, ctx: str) -> None:
        lineno = getattr(const_node, "lineno", 0)
        key = (lineno, caseid)
        if key in seen:
            return
        seen.add(key)
        findings.append(Finding(
            code=CODE_HARDCODED_CASE_ID,
            severity=BLOCKING,
            message=(f"verify_script 用 autoid 级字面量 {caseid!r} 作{ctx}，"
                     f"属逐 case 硬编码（规则须对任意 case 通用，禁 if autoid == 具体值）"),
            location=f"{location_file}:{lineno}" if lineno else location_file,
            evidence=caseid,
        ))

    for node in ast.walk(tree):
        # 比较：if autoid == "778012" / autoid in {"778012", ...} / x != 778012
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for operand in operands:
                for const in _iter_constants(operand):
                    cid = _caseid_in_literal(const.value)
                    if cid:
                        _record(const, cid, "分支比较")
        # match autoid: case "778012": ...
        elif isinstance(node, ast.Match):
            for case in node.cases:
                for const in _iter_constants(case.pattern):
                    cid = _caseid_in_literal(const.value)
                    if cid:
                        _record(const, cid, "match 模式")

    return findings


# ── ② when_to_use TRIGGER/SKIP 范式 ──────────────────────────────────

def _check_when_to_use(when_to_use: str) -> list[Finding]:
    """同事技能 TRIGGER+SKIP 范式：必须同时含触发关键词与 SKIP 条件，缺一即拒。

    走子串成员判定（词法），不推断语义。兼容 "TRIGGER:" / "Trigger keywords" /
    "Trigger phrases" / "触发" 等写法，以及 "SKIP when" / "SKIP:" / "跳过"。
    """
    findings: list[Finding] = []
    text = (when_to_use or "")
    low = text.lower()

    has_trigger = ("trigger" in low) or ("触发" in text)
    has_skip = ("skip" in low) or ("跳过" in text)

    if not has_trigger:
        findings.append(Finding(
            code=CODE_MISSING_TRIGGER,
            severity=BLOCKING,
            message="when_to_use 缺 TRIGGER 触发关键词列表（须按同事技能 TRIGGER+SKIP 范式）",
            location="when_to_use",
        ))
    if not has_skip:
        findings.append(Finding(
            code=CODE_MISSING_SKIP,
            severity=BLOCKING,
            message="when_to_use 缺 SKIP 转交 / 跳过条件（须按同事技能 TRIGGER+SKIP 范式）",
            location="when_to_use",
        ))
    return findings


# ── ④ params 缺但 body 有疑似硬值 ────────────────────────────────────

def _has_params(skill: Any) -> bool:
    """params 槽是否已声明（非空 dict / 非空可迭代）。"""
    params = _field_of(skill, "params", None)
    if params is None:
        return False
    try:
        return len(params) > 0
    except TypeError:
        return bool(params)


def _sniff_body_hardvalues(body: str) -> list[str]:
    """词法嗅探 body 中的疑似魔法字面量（IPv4 / autoid 级长数字串），去重保序。"""
    text = body or ""
    hits: list[str] = []
    seen: set[str] = set()
    for m in _IPV4_LITERAL.finditer(text):
        v = m.group(0)
        if v not in seen:
            seen.add(v)
            hits.append(v)
    for m in _CASEID_DIGIT_RUN.finditer(text):
        v = m.group(0)
        if v not in seen:
            seen.add(v)
            hits.append(v)
    return hits


def _check_params_vs_body(skill: Any) -> list[Finding]:
    if _has_params(skill):
        return []  # 已声明参数槽，本项不再嗅探（task 范围限定「params 缺但…」）
    body = str(_field_of(skill, "body", "") or "")
    hits = _sniff_body_hardvalues(body)
    if not hits:
        return []
    sample = ", ".join(hits[:8])
    return [Finding(
        code=CODE_UNPARAMETERIZED_HARDVALUE,
        severity=MINOR,
        message=("未声明 params 槽，但 body 出现疑似魔法字面量（IP / 长数字串）；"
                 "建议去实例化为参数槽并溯源（empirical/manual），否则恐属未参数化硬值"),
        location="body",
        evidence=sample,
    )]


# ── 主入口 ───────────────────────────────────────────────────────────

def check_contract(
    skill: Any,
    *,
    skill_dir: Optional[Union[str, Path]] = None,
    verify_source: Optional[str] = None,
) -> list[Finding]:
    """对一条（归纳或手写）技能做质量契约静态校验，返回 Finding 列表。

    参数
    ----
    skill : dict 或带属性对象（如 schema.SkillSpec）。读取字段
        ``when_to_use`` / ``verify_script`` / ``params`` / ``body``（鸭子类型）。
    skill_dir : 技能目录，用于把相对 ``verify_script`` 解析为绝对路径并做存在性校验。
        若 skill 自带 ``skill_dir`` 属性，可省略本参数。
    verify_source : 可选，直接传入 verify.py 源码字符串（供归纳循环在草案落盘前预检，
        或测试免写文件）。给出时跳过文件存在性校验，直接 AST 解析该源码。

    判定
    ----
    - ② when_to_use 始终校验。
    - ③ verify_script 声明 / 文件 / 可解析性校验；据此决定能否进入 ① AST 扫描。
    - ① 仅在拿到可解析的 verify 源码时执行。
    - ④ params vs body 始终校验（独立于 verify_script）。

    无 blocking finding 即结构门通过（仍需 A-B 行为门）。
    """
    findings: list[Finding] = []

    # ② when_to_use TRIGGER/SKIP
    findings.extend(_check_when_to_use(str(_field_of(skill, "when_to_use", "") or "")))

    # ③ verify_script 声明 / 文件 / 可解析性 → 决定能否 AST 扫描
    verify_script = _field_of(skill, "verify_script", None)
    verify_tree: Optional[ast.AST] = None
    verify_loc = "verify.py"

    if verify_source is not None:
        # 草案 / 测试直传源码：跳过文件存在性，直接解析
        try:
            verify_tree = ast.parse(verify_source)
        except SyntaxError as exc:
            findings.append(Finding(
                code=CODE_VERIFY_SCRIPT_UNPARSEABLE,
                severity=BLOCKING,
                message=f"verify_script 源码无法解析（离线校验不可跑通）：{exc.msg}",
                location=f"{verify_loc}:{exc.lineno or 0}",
            ))
    elif not verify_script or not str(verify_script).strip():
        findings.append(Finding(
            code=CODE_MISSING_VERIFY_SCRIPT,
            severity=BLOCKING,
            message="未声明 verify_script；无确定性离线校验脚本的技能不得入 A-B 闸",
            location="skill",
        ))
    else:
        verify_loc = str(verify_script)
        path = Path(verify_script)
        if not path.is_absolute():
            base = skill_dir if skill_dir is not None else _field_of(skill, "skill_dir", None)
            if base is not None:
                path = Path(base) / path
        if not path.is_file():
            findings.append(Finding(
                code=CODE_VERIFY_SCRIPT_NOT_FOUND,
                severity=BLOCKING,
                message=f"verify_script 声明的文件不存在：{path}",
                location=verify_loc,
            ))
        else:
            try:
                verify_tree = ast.parse(path.read_text(encoding="utf-8"))
                verify_loc = path.name
            except (SyntaxError, OSError) as exc:
                findings.append(Finding(
                    code=CODE_VERIFY_SCRIPT_UNPARSEABLE,
                    severity=BLOCKING,
                    message=f"verify_script 无法解析 / 读取（离线校验不可跑通）：{exc}",
                    location=verify_loc,
                ))

    # ① 逐 case 硬编码 AST 扫描（仅在拿到可解析源码时）
    if verify_tree is not None:
        findings.extend(_scan_hardcoded_caseids(verify_tree, verify_loc))

    # ④ params 缺但 body 有疑似硬值
    findings.extend(_check_params_vs_body(skill))

    return findings


def has_blocking(findings: list[Finding]) -> bool:
    """findings 中是否存在 blocking 项（结构门是否未过）。"""
    return any(f.is_blocking for f in findings)


def passes_contract(skill: Any, **kwargs: Any) -> bool:
    """便捷判定：技能是否通过结构门（无 blocking finding）。

    供 ab_gate 在晋升前调用：``passes_contract`` 为 False 直接废稿，不进 A-B 行为门。
    """
    return not has_blocking(check_contract(skill, **kwargs))
