"""v2 结构约束门（correct-by-construction，论文命题3.18 / PLAN_footprint_v2_compile.md §2.2）。

与 grade(LLM 语义自评)**独立**的确定性强制——执行**结构约束**，不碰**骨架选择**：
- ① 命令头∈手册 allowlist（footprint 已有的命令集）——挡幻觉/越界命令；
- ② 断言对象挂在某前序观测算子（show/dig 产出回显的步骤）的值域上——根治 655203 悬空断言；
- ③ 绑定 IP∈env_facts 可达表（已由 emit_xlsx_tool._gate_unreachable_ips 做，这里不重复）。

红线（§七）：只执行**与意图无关的类型规则**（命令合法性、断言非悬空、IP 可达），
绝不替 LLM 决定"测什么/什么命令序列/什么断言形态"（H_G≠0 的语义决策永远 LLM）。

只在 v2 编译链启用（compile_emit(strict_structural=True)）；v1 默认 False，行为零变化。
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
    """该步骤是否让框架 `result` 持有非 None 回显（可被 check_point `re.search`，不抛 TypeError）。

    判据是**框架的结构化契约（F 列方法名）**，不是 grep G 列命令关键字——后者会把"失败的单条配置
    命令"误判成无回显（994957：`sdns host pool … p11` 不含 show/dig，却真回显错误文字 `A maximum
    of 10…`，逼 draft 多插一步 show 把 result 冲掉、断言读错缓冲）。框架事实：
      - test_env 触发（dig/clientc/routera 等）→ 回显。
      - APV `cmd_config`（**单条**，apv_ssh.py:151 `return output`）→ 回显；失败命令回显错误文字、
        成功命令回显 prompt，均非 None、可被断言。
      - APV `cmds_config`（**多条**，apv_ssh.py:166-169 遍历调 cmd_config 但**不收集返回值**）→ None。
    （test_xlsx.py:309 `result = func()`，func 即该 F 列方法：cmd_config 返回 output、cmds_config 返回 None。）
    """
    e = str(step.get("E", "")).strip()
    f = str(step.get("F", "")).strip()
    if e == "test_env":
        return True  # dig/clientc/routera 等触发都回显
    if e.startswith("APV"):
        return f == "cmd_config"   # 单条 cmd_config 产 result 回显；cmds_config（多条）返回 None
    return False


def _check_dangling_assertions(steps: list, result: StructuralResult) -> None:
    """断言的 result 来源必须有效——否则框架 ``found(None)`` 抛 TypeError、**整份文件崩溃**
    （pytest 用例异常退出，该 case 之后的 case 全不执行；实证一个坏断言拖垮 31→只跑 4）。

    框架契约（实证 lib/test_xlsx.py + check_point.py）：
    - 非 check_point 步**仅当不带 H(save_as)** 时 `result = func(...)`；带 H 的步只把输出存进
      寄存器、**不更新 result**。
    - 配置步 `cmds_config/cmd_config` 的 func() 返回 None（不产回显）。
    - check_point 若 I 列(row[8])空，被测值 = 框架 `result`；`re.search(expect, None)` → TypeError 崩溃。
    ⟹ check_point(I 空) 的 result 非 None ⟺ 它**之前最近的「不带 H 的步」是观测算子**(dig/show 产回显)。
      若最近的不带 H 步是配置步(result=None)、或前面的观测步都带了 H(没更新 result) → 崩溃。

    与意图无关、机械可判。捕获比较的正确三步式：dig(H=v1 捕获基线) → dig(**无 H**，设 result) →
    check_point(H=v1)；draft 漏掉中间「无 H 观测步」时本门拦下。
    """
    result_is_observe = False   # 框架 `result` 当前是否持有观测回显（非 None 可被 re.search）
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        e = str(s.get("E", "")).strip()
        h = str(s.get("H", "") or "").strip()
        i_col = str(s.get("I", "") or "").strip()
        if e == "check_point":
            # I 列非空时被测值取 I 寄存器（另一路径，此处不判）；I 空时取框架 result。
            if not i_col and not result_is_observe:
                result.add(
                    "dangling_assertion",
                    "该断言取的 result 无有效观测回显 → 框架 result=None、found(None) 抛 TypeError "
                    "**崩溃整份文件**(该 case 之后全不跑)。成因:断言紧前最近的「不带 H 步」是配置步"
                    "(cmds_config 返回 None)、或前面的观测步都带了 H(save_as 不更新 result)。"
                    "修法:断言**紧前**放一个**不带 H** 的观测步(dig/show)让其回显成为 result;"
                    "捕获比较用三步式 dig(H=v1) → dig(无H) → check_point(H=v1)。",
                    i,
                )
            # check_point 不改变 result（它消费 result，不产出新回显）
        else:
            if not h:
                # 不带 H → 框架 `result = func()`;观测步→字符串(有效),配置步→None(无效)
                result_is_observe = _is_observation_step(s)
            # 带 H → 仅存寄存器、不更新 result → result_is_observe 不变


def _check_dead_capture(steps: list, result: StructuralResult) -> None:
    """寄存器写而不读（死捕获）：观测/动作步用 H(save_as) 把回显捕获进寄存器 v，但**没有任何
    check_point 引用 v**——写了一个永不读的寄存器，是废动作/残缺断言。

    典型（GA 断错缓冲）：dig 带 H 捕获命中 IP 进 v1/v3，但 check_point 去读框架 result（紧前常是
    `show host pool` 配置回显，里面没有该 IP）→ 既没验到 dig 行为(寄存器没人读)、断言又读错缓冲。
    这正是 grade 的 `is_genuine_v_assertion` 修 H 后仍不主动报警的那类（无 mutating、IP token 空），
    需本确定性门兜底。

    与意图无关、纯数据流（写入集 − 读取集），机械可判。**天然区分合法三步式**：dig(H=v1)→dig(无H)→
    check_point(H=v1)，v1 被 check_point 的 H 读了 → 不死；残缺混合体里 v1 无人读 → 死。
    读取集保守地收 check_point 的 H(作 expect 寄存器) + **所有步**的 I(作被查文本/输入引用)——
    宁可漏报、绝不误杀（对齐本门「静态约束宁漏报不误杀」原则，见 check_structural_constraints 注）。
    """
    captured: dict[str, int] = {}   # 寄存器名 → 捕获它的步 idx（非 check_point 步带 H）
    referenced: set[str] = set()    # 被引用（消费）的寄存器名
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        e = str(s.get("E", "")).strip()
        h = str(s.get("H", "") or "").strip()
        i_col = str(s.get("I", "") or "").strip()
        if i_col:
            referenced.add(i_col)            # 任何步的 I = 从寄存器取被查文本/输入
        if e == "check_point":
            if h:
                referenced.add(h)            # check_point 带 H = expect 从寄存器取（abs_found 比较）
        elif h:
            captured[h] = i                  # 观测/动作步带 H = 把回显捕获进寄存器
    for reg, idx in captured.items():
        if reg not in referenced:
            result.add(
                "dead_capture",
                f"寄存器 '{reg}' 被 save_as 捕获但**无任何 check_point 引用**（既不作 expect 的 H、"
                f"也不作被查文本的 I）= 写了永不读的寄存器、废动作/残缺断言。典型：dig 带 H 捕获进 "
                f"'{reg}' 却用 found 读 result(紧前常是 show 配置回显→断错缓冲)，没 abs_found(H='{reg}') "
                f"消费它 → 既没验到该 dig 行为、断言又读错缓冲。修法：用 check_point abs_found 引用 "
                f"'{reg}'（三步式 dig(H={reg})→dig(无H)→check_point(H={reg})），或删掉这个没用的捕获。",
                idx,
            )


def check_structural_constraints(autoid: str, steps: list, init: str = "") -> StructuralResult:
    """v2 结构约束门入口：命令 allowlist + 断言非悬空（IP 可达由 emit 既有门做）。

    返回 StructuralResult；ok=False 时 emit 应拒绝并把 render() 反馈给 draft 让它改。

    注（为何不做「引号/参数格式门」）：实证 `sdns host persistence` 先例**逐位置且不一致**
    （域名从不加引号、掩码总加引号），且先例集**不完整**（不覆盖 query_type 的 arity-5 合法形态）。
    任何静态格式门要么漏报、要么误杀合法形态。命令的参数格式正确性靠：①照最像先例**逐字复制**
    （compile_precedent 已强调）；②查 footprint/手册；③上机 verify 用设备 `^`/show 反馈兜底回流。
    """
    result = StructuralResult()
    if not isinstance(steps, list):
        return result
    _check_command_allowlist(steps, init, result)
    _check_dangling_assertions(steps, result)
    _check_no_found_times(steps, result)
    _check_dead_capture(steps, result)
    return result


def _check_no_found_times(steps: list, result: StructuralResult) -> None:
    """拒绝 found_times 断言——框架 xlsx 分派**不支持**它,必崩整份文件(A 层机械事实,非语义判断)。

    实证(lib/test_xlsx.py 无任何 found_times/times 特殊处理):check_point 一律走 generic 2 参分派
    `func(expect, result)`,而 `check_point.found_times(expect, result, times)` 需 3 参 →
    `TypeError: found_times() missing 1 required positional argument: 'times'` → pytest 崩、
    该 case 之后全不跑(实证 yzg 10 pass 后崩、14 不执行)。
    改用 `found`(出现即可)或 `abs_found`(字面);要"恰好 N 次"语义,框架表达不了,换断言。
    注:这是**机械崩溃**判定(等同语法错),与"某 claim 可不可证伪"的语义判断(归 verifiability 工具 +
    LLM)是两码事——本门只认 F==found_times 这个必崩形态,不在这里算可证伪性。
    """
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        if str(s.get("E", "")).strip() == "check_point" and str(s.get("F", "")).strip() == "found_times":
            result.add(
                "found_times_unsupported",
                "found_times 框架 xlsx 流不支持(分派只传 2 参、缺 times)→ TypeError 崩整份文件。"
                "改用 found(出现即可)/abs_found(字面匹配);'恰好 N 次'语义本框架表达不了。",
                i,
            )


def check_no_found_times_mandatory(steps: list) -> StructuralResult:
    """found_times **无条件**拒绝门——与 strict_structural opt-in 解耦(A 层机械崩溃门)。

    found_times 保证崩框架(分派只传 2 参必 TypeError,见 _check_no_found_times);其拒绝绝不该可选。
    实证:draft agent 偶尔漏传 `strict_structural=True`(tool 默认 False 的 prompt 指令) → 整个结构门
    跳过 → found_times 漏进 excel → 上机崩、崩溃点后全 case unknown(dongkl 实测 31 unknown 根因)。
    故 emit **无条件**先跑这一条(其余启发式门仍留 strict_structural opt-in)。等同 SWE-agent 的
    linter"语法不对不让 edit 过"——机械可判、误判即真错,不误杀好制品。
    """
    result = StructuralResult()
    if isinstance(steps, list):
        _check_no_found_times(steps, result)
    return result


def check_crash_gates_mandatory(steps: list) -> StructuralResult:
    """必崩形态**无条件**拒绝门集合——与 strict_structural opt-in 解耦(A 层机械崩溃门)。

    收录标准(严进):该形态上机**保证** TypeError 崩整份 pytest 文件(该 case 之后全不跑)——
    误判即真错、不存在误杀好制品的可能。当前两条:
    - found_times:框架分派只传 2 参必崩(_check_no_found_times;dongkl 首跑 31 unknown 根因)。
    - 悬空断言:check_point(I 空)前无 result 生产步 → found(None) 必崩(_check_dangling_assertions;
      实证 dongkl 778012 重编版:配置步后直接断言,worker 漏传 strict_structural 使 opt-in 门被
      跳过而漏网 → 第三轮上机 1 pass + 33 unknown)。
    教训同源:必崩类检查躲在 opt-in 开关后面就等于没有——draft agent 会漏传参数。启发式/
    allowlist 类门仍留 strict_structural(可能误杀,须可选);必崩类一律进本门。
    """
    result = StructuralResult()
    if isinstance(steps, list):
        _check_no_found_times(steps, result)
        _check_dangling_assertions(steps, result)
    return result

