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
        from main.case_compiler.case_ir import CaseIR, FileIR, Row, Step
        from main.case_compiler.xlsx_emit import emit_xlsx
        from main.case_compiler.config import get_config
    except Exception as e:  # noqa: BLE001
        return f"error: 加载编译器模块失败: {e}"

    # 文件级前置
    init_g = init_commands.strip() if init_commands.strip() else get_config().default_init_g()
    init_rows = [Row(test_object="APV_0", method="cmds_config", data=init_g)]

    # 步骤 → Step/Row(每步独立 Step,stmt_type 从 2 递增)
    ist_steps = []
    has_cp = False
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            return f"error: step[{i}] 不是 dict"
        e = str(s.get("E", "")).strip()
        f = str(s.get("F", "")).strip()
        if not e or not f:
            return f"error: step[{i}] 缺 E 或 F"
        if e == "check_point":
            has_cp = True
        row = Row(test_object=e, method=f, data=str(s.get("G", "") or ""),
                  save_as=(s.get("H") or None),
                  input_var=(str(s.get("I")) if s.get("I") is not None else None))
        ist_steps.append(Step(stmt_type=2 + i, description=str(s.get("desc", "") or ""),
                              rows=[row]))
    if not has_cp:
        return "error: 没有任何 check_point 步骤——上机必 fail(pass 需 success>0)。加一个 found 断言。"

    case = CaseIR(autoid=autoid, priority="P1", title=f"agent_{autoid}", steps=ist_steps)

    # 框架执行契约(死知识):test_xlsx.py 是**延迟执行模型**——最后一个 case 走 `if last_case`
    # 收尾分支,只 parser_case_id 记录、**不执行步骤**。单 case xlsx 的唯一 case 就是 last_case,
    # 永不执行 → 零 check_point → 默认 result=pass(空真!)。故必须在真实 case 后补一个**哨兵 case**,
    # 让真实 case 不是最后一个、走正常执行路径。哨兵自己是 last_case 不执行,无副作用。
    _sentinel = CaseIR(
        autoid="999999999999999", priority="P9", title="sentinel-do-not-execute",
        steps=[Step(stmt_type=2, description="sentinel",
                    rows=[Row(test_object="APV_0", method="cmd_config", data="show version")])],
    )
    sub = (out_name or autoid).strip().replace("/", "_")
    fir = FileIR(feature=sub, author="IST-Core-agent", init_rows=init_rows,
                 cases=[case, _sentinel], module="ist_smoke")
    root = Path(__file__).resolve().parents[4]
    out = root / "workspace" / "outputs" / sub / "case.xlsx"
    try:
        stats = emit_xlsx(fir, out)
    except Exception as e:  # noqa: BLE001
        return f"error: emit 失败: {e}"

    return (f"=== qa_emit_xlsx ===\n"
            f"已产出结构正确的 xlsx(克隆框架模板): {out}\n"
            f"case={autoid}  steps={len(ist_steps)}  check_points={'有' if has_cp else '无'}\n"
            f"round-trip 统计: {stats}\n"
            f"下一步:qa_run_case(xlsx_path='{out}', autoid='{autoid}') 上机验证。")
