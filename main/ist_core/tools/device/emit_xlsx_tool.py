"""qa_emit_xlsx: 从简单步骤列表产出**结构正确**的 case.xlsx(克隆框架原生模板)。

为什么要它:agent 用 qa_exec 手搓 openpyxl 总在模板结构/列对齐上出错(E/F/G 错位、缺
27 行说明区、缺 C=0/C=1)→ 框架找不到 case 行 → 零 check_point → 空真 pass。
本工具复用 case_compiler.xlsx_emit.emit_xlsx——它克隆真实跑通的 sdns_listener.xlsx 模板,
只重写数据区,保留全部说明区/字典区/格式/列对齐。**结构由工具保证,内容由 agent 决定。**

agent 只需给:文件级前置命令(init) + 步骤列表(每步 actor/action/data)。列语义:
  E=操作对象(APV_0/check_point/test_env/time)  F=方法(cmd_config/cmds_config/found/
  not_found/found_times/routera/clientc/sleep...)  G=数据(命令/期望文本)
  H=save_as(存变量,可选)  I=input_var(引用变量,可选)
工具自动放进正确的行/列,agent 不碰模板结构。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 框架执行契约(死知识):test_xlsx.py 是**延迟执行模型**——最后一个 case 走 `if last_case`
# 收尾分支,只 parser_case_id 记录、**不执行步骤**。所以 xlsx 末尾必须垫一个哨兵 case,
# 让真实 case 都不是最后一个、走正常执行路径。哨兵自己当 last_case 不执行,无副作用。
# 这对单 case 和多 case 合并是同一条契约:cases=[真case..., _sentinel]。
_SENTINEL_AUTOID = "999999999999999"


def _build_sentinel():
    """构造垫底哨兵 case(框架延迟执行契约,见上)。show version=最通用无副作用只读占位。"""
    from main.case_compiler.case_ir import CaseIR, Row, Step
    return CaseIR(
        autoid=_SENTINEL_AUTOID, priority="P9", title="sentinel-do-not-execute",
        steps=[Step(stmt_type=2, description="sentinel",
                    rows=[Row(test_object="APV_0", method="cmd_config", data="show version")])],
    )


def _steps_to_caseir(autoid: str, steps: list, *, title: str = ""):
    """把 [{E,F,G,H?,I?,desc?}, ...] 步骤列表转成一个 CaseIR。

    返回 (CaseIR, has_check_point) 或 (None, 错误字符串)。单 case 和合并多 case 共用,
    保证 stmt_type 递增/列语义/check_point 校验完全一致。
    """
    from main.case_compiler.case_ir import CaseIR, Row, Step

    ist_steps = []
    has_cp = False
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            return None, f"step[{i}] 不是 dict"
        e = str(s.get("E", "")).strip()
        f = str(s.get("F", "")).strip()
        if not e or not f:
            return None, f"step[{i}] 缺 E 或 F"
        if e == "check_point":
            has_cp = True
        row = Row(test_object=e, method=f, data=str(s.get("G", "") or ""),
                  save_as=(s.get("H") or None),
                  input_var=(str(s.get("I")) if s.get("I") is not None else None))
        ist_steps.append(Step(stmt_type=2 + i, description=str(s.get("desc", "") or ""),
                              rows=[row]))
    if not has_cp:
        return None, (f"case {autoid} 没有任何 check_point 步骤——上机必 fail"
                      f"(pass 需 success>0)。加一个 found 断言。")
    case = CaseIR(autoid=autoid, priority="P1",
                  title=(title or f"agent_{autoid}"), steps=ist_steps)
    return case, has_cp


def _gate_unreachable_ips(autoid: str, steps: list, init: str = "") -> str | None:
    """可达性校验门(事实源白名单投影):配置类步骤的 G 列 + init 里的 IP 必须落在拓扑可达集。

    病根:draft 凭空写 1.1.1.1/2.2.2.2 等示例 IP 当 service IP→设备不可达→dig 失败→断言全 fail。
    这里在 emit 出口兜底:发现不可达 IP 直接打回,并把"可达集合是什么"原样告诉 draft 让它重写
    (供给+校验,不做事后猜测映射——契约,非死字典)。

    只校验**配置类**(APV_0 的 cmd_config/cmds_config)与 init 的 G;check_point 的期望文本里
    可能有正则/IP 片段不在此列(那是断言匹配目标,不是要连接的设备),不拦。
    """
    from main.ist_core.tools._shared.env_facts import get_env_facts

    facts = get_env_facts()
    if not facts.devices:  # JSON 缺失 → 宽松降级,不拦(与 ssh.py 一致)
        return None

    bad: list[str] = []
    texts: list[str] = []
    if init:
        texts.append(init)
    for s in steps:
        if not isinstance(s, dict):
            continue
        e = str(s.get("E", "")).strip()
        f = str(s.get("F", "")).strip()
        # 只校验被测设备的配置步骤(要真连/真生效的);test_env 触发(dig 目标)同样需可达
        if e.startswith("APV") and f in ("cmd_config", "cmds_config"):
            texts.append(str(s.get("G", "") or ""))
        elif e == "test_env":
            texts.append(str(s.get("G", "") or ""))
    for t in texts:
        for ip in facts.unreachable_ipv4s(t):
            if ip not in bad:
                bad.append(ip)
    if not bad:
        return None
    return (f"case {autoid} 用了 {len(bad)} 个**环境不可达 IP**: {', '.join(bad)}\n"
            f"这些 IP 不在本测试床任何子网内,上机 dig/连接必失败(Hit=0、断言全 fail)。\n"
            f"改用真实可达 IP 重写——后端 service/pool 用真实服务器 IP,VIP/listener 用段内未占用 IP:\n\n"
            f"{facts.summary_for_agent()}")



@tool(parse_docstring=True)
def qa_emit_xlsx(autoid: str, steps_json: str, init_commands: str = "",
                 out_name: str = "") -> str:
    """从步骤列表产出结构正确的 case.xlsx(克隆框架原生模板,你不用管模板结构/列对齐)。

    **用这个,别用 qa_exec 手搓 openpyxl**——手搓总在 27 行说明区/C=0/C=1/E-F-G 列对齐上
    出错,导致框架跳过你的 case 行(零 check_point、空真 pass)。本工具保证结构 100% 合法。

    你只决定**内容**:文件级前置命令 + 每个步骤的 操作对象/方法/数据。

    列语义(每个 step 一个 dict):
    - ``E`` 操作对象: APV_0(被测设备) / check_point(断言) / test_env(测试机) / time(等待)
    - ``F`` 方法: APV_0→cmd_config(单条)|cmds_config(多条\\n分隔);
      check_point→found(正则DOTALL)|not_found|abs_found(字面)|found_times(需I列次数);
      test_env→routera|clientc 等主机名; time→sleep
    - ``G`` 数据(**数据类型=字面文本/正则字符串,不是变量、不是 Python 表达式、不是数值**):
      配置步骤=CLI命令原文;check_point=要在上一步输出里**文本查找**的期望文本/正则。
      框架拿 G **原样**匹配——写一个变量名(如 init_ip)它就去找字面 "init_ip" 这几个字符,永远找不到。
    - ``H`` save_as(可选)/``I`` input_var(可选): 跨步骤传值。但 H 存的是**整段命令输出文本**,
      **不能提取其中某字段(如某个IP)再做数值相等比对**——xlsx DSL 没有 re.findall/算术。
      所以"第一次dig返回哪个IP、后续跟它比"这类**运行时动态值比对,xlsx 表达不了**;遇到这种,
      改用"设备 show 命令把该行为转成稳定可查找的输出"再 found(先用 qa_probe_show 探有没有这种命令)。
    - ``desc``(可选): 步骤描述

    check_point 自动校验**上一个非 check_point 步骤的输出**,所以断言前要先有产出输出的步骤
    (show/dig)。每个 case 至少一个会通过的 check_point(否则上机必 fail)。

    Args:
        autoid: case autoid for the first case row column A.
        steps_json: JSON array string; each element a dict with keys E/F/G and optional H/I/desc.
        init_commands: file-level preconfig (C=1) commands, newline separated; empty uses sdns default.
        out_name: output subdir under workspace/outputs; empty uses autoid.

    Returns:
        产出路径 + round-trip 行数统计。拿到路径后用 qa_run_case 上机验证。
    """
    autoid = (autoid or "").strip()
    if not autoid:
        return "error: 必须指定 autoid"
    try:
        steps = json.loads(steps_json) if isinstance(steps_json, str) else steps_json
        if not isinstance(steps, list) or not steps:
            return "error: steps_json 必须是非空列表"
    except Exception as e:  # noqa: BLE001
        return f"error: steps_json 解析失败: {e}"

    try:
        from main.case_compiler.case_ir import FileIR, Row
        from main.case_compiler.xlsx_emit import emit_xlsx
        from main.case_compiler.config import get_config
    except Exception as e:  # noqa: BLE001
        return f"error: 加载编译器模块失败: {e}"

    # 文件级前置
    init_g = init_commands.strip() if init_commands.strip() else get_config().default_init_g()
    init_rows = [Row(test_object="APV_0", method="cmds_config", data=init_g)]

    # 可达性校验门:配置/触发用的 IP 必须在拓扑可达集(挡住 1.1.1.1 等不可达示例 IP)
    gate = _gate_unreachable_ips(autoid, steps, init=init_g)
    if gate:
        return f"error: {gate}"

    # 步骤 → CaseIR(与合并工具共用同一构造,保证列语义一致)
    case, info = _steps_to_caseir(autoid, steps)
    if case is None:
        return f"error: {info}"

    # 末尾垫哨兵(框架延迟执行契约,见 _build_sentinel)
    sub = (out_name or autoid).strip().replace("/", "_")
    fir = FileIR(feature=sub, author="IST-Core-agent", init_rows=init_rows,
                 cases=[case, _build_sentinel()], module="ist_smoke")
    root = Path(__file__).resolve().parents[4]
    out = root / "workspace" / "outputs" / sub / "case.xlsx"
    try:
        stats = emit_xlsx(fir, out)
    except Exception as e:  # noqa: BLE001
        return f"error: emit 失败: {e}"

    return (f"=== qa_emit_xlsx ===\n"
            f"已产出结构正确的 xlsx(克隆框架模板): {out}\n"
            f"case={autoid}  steps={len(case.steps)}  check_points=有\n"
            f"round-trip 统计: {stats}\n"
            f"下一步:qa_run_case(xlsx_path='{out}', autoid='{autoid}') 上机验证。")


@tool(parse_docstring=True)
def qa_emit_xlsx_merged(cases_json: str, shared_init: str = "", out_name: str = "") -> str:
    """把**多个 case 合并成一个 xlsx**(每脑图一个 excel 的打包工具)。

    用于批量编译收尾:把同一脑图里已逐个生成好的 N 个 case 合并进一个 case.xlsx,
    末尾自动垫一个哨兵 case(框架延迟执行契约)——这样前 N 个真 case 全部正常执行。
    合并不是简单拼接:它保证 case 顺序、列对齐、哨兵垫底,结构 100% 合法。

    **每个 case 自带它自己的前置配置**(``init``):框架每跑一个 case 前会清设备配置,
    所以每个 case 必须自包含。把这个 case 的完整基线配置放进它自己的 ``init``
    (会被 emit 成该 case 的首个 APV_0 配置步骤),test 动作 + 断言放进 ``steps``。
    不同 case 基线不同时(如各自不同的 pool/算法),各写各的 init——绝不能共用一份。

    ``shared_init`` 只用于**所有 case 真正共享、且每 case 前都要重跑**的文件级前置
    (C=1)。多数情况留空,基线走每个 case 自己的 ``init``。

    零硬编码:本工具不产任何命令,init/steps 全部由你(查过手册/先例的子 agent)提供。

    Args:
        cases_json: JSON 数组字符串。每项是一个 case dict,含键:autoid(主键,标题可重名故不去重)、
            steps(步骤列表,每步 {E,F,G,H?,I?,desc?},至少含一个 check_point)、
            init(本 case 自包含前置命令,换行分隔,可空——会 emit 成该 case 的首个 APV_0 配置步骤)、
            title(可选标题)。不同 case 基线不同时各写各的 init,绝不共用。
        shared_init: 所有 case 共享的文件级前置(C=1),换行分隔;通常留空。
        out_name: 输出子目录名(workspace/outputs/<out_name>/case.xlsx);如脑图名 dongkl。

    Returns:
        产出路径 + round-trip 对账(case 数应=输入数+1哨兵)。下一步用 qa_run_batch
        把这些 autoid 顺序上机验证。
    """
    try:
        cases = json.loads(cases_json)
        if not isinstance(cases, list) or not cases:
            return "error: cases_json 必须是非空 JSON 数组"
    except Exception as e:  # noqa: BLE001
        return f"error: cases_json 解析失败: {e}"

    try:
        from main.case_compiler.case_ir import FileIR, Row
        from main.case_compiler.xlsx_emit import emit_xlsx
        from main.case_compiler.config import get_config
    except Exception as e:  # noqa: BLE001
        return f"error: 加载编译器模块失败: {e}"

    case_irs = []
    seen_autoids = set()
    for idx, c in enumerate(cases):
        if not isinstance(c, dict):
            return f"error: cases[{idx}] 不是 dict"
        autoid = str(c.get("autoid", "")).strip()
        if not autoid:
            return f"error: cases[{idx}] 缺 autoid"
        if autoid in seen_autoids:
            return f"error: autoid {autoid} 重复(autoid 是主键,不可重复;标题可重名)"
        seen_autoids.add(autoid)
        steps = c.get("steps")
        if not isinstance(steps, list) or not steps:
            return f"error: cases[{idx}] (autoid={autoid}) steps 必须是非空列表"

        # 每个 case 的自包含前置 → 该 case 的首个 APV_0 配置步骤(不是文件级 C=1)。
        # 框架每 case 前清配置,故基线必须在 case 内,且不同 case 各写各的。
        case_init = str(c.get("init", "") or "").strip()

        # 可达性校验门(逐 case):init + 步骤里的 IP 必须可达,挡住 1.1.1.1 等不可达示例 IP
        gate = _gate_unreachable_ips(autoid, steps, init=case_init)
        if gate:
            return f"error: cases[{idx}] {gate}"

        full_steps = list(steps)
        if case_init:
            full_steps = [{"E": "APV_0", "F": "cmds_config", "G": case_init,
                           "desc": "case 自包含前置配置"}] + full_steps

        case, info = _steps_to_caseir(autoid, full_steps, title=str(c.get("title", "") or ""))
        if case is None:
            return f"error: cases[{idx}] (autoid={autoid}): {info}"
        case_irs.append(case)

    # 文件级共享前置(通常空)
    shared = shared_init.strip()
    init_rows = ([Row(test_object="APV_0", method="cmds_config", data=shared)]
                 if shared else [])

    # 末尾垫哨兵(框架延迟执行契约)——前 N 个真 case 全执行
    sub = (out_name or case_irs[0].autoid).strip().replace("/", "_")
    fir = FileIR(feature=sub, author="IST-Core-agent", init_rows=init_rows,
                 cases=[*case_irs, _build_sentinel()], module="ist_smoke")
    root = Path(__file__).resolve().parents[4]
    out = root / "workspace" / "outputs" / sub / "case.xlsx"
    try:
        stats = emit_xlsx(fir, out)
    except Exception as e:  # noqa: BLE001
        return f"error: emit 失败: {e}"

    autoids = [c.autoid for c in case_irs]
    return (f"=== qa_emit_xlsx_merged ===\n"
            f"已合并 {len(case_irs)} 个真 case + 1 哨兵 → {out}\n"
            f"autoids: {autoids}\n"
            f"round-trip 统计: {stats}\n"
            f"(case_count 应={len(case_irs)}+1哨兵={len(case_irs)+1})\n"
            f"下一步:qa_run_batch(xlsx_path='{out}', autoids_json={json.dumps(autoids)}) 顺序上机。")
