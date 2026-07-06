"""agent_define:main 按 B2 骨架自主生成 fork agent(D 阶段,2026-07-05)。

设计(docs/AUDIT_skill_standard_alignment.md D 节):不让 LLM 徒手写 md 文件——
本工具收原生结构化参数,工具内拼装+校验+落盘,与 compile_emit 的组合子同一哲学
(correct-by-construction):坏名字/未注册工具/结构标签注入/frontmatter 破坏这些
形态在本入口下写不出来。产物落 runtime/(文件工具沙箱黑名单)——创建/覆盖只有
这一条有闸的路。

生成物 = 一对标准文件:
- runtime/dyn_agents/dyn-<name>.md    —— B2 骨架(<role>/<task>/<rules>),
  inherit-parent-prompt 强制 true(证据纪律/忠实汇报等共享硬约束不可剥离)
- runtime/dyn_skills/dyn-<name>/SKILL.md —— context: fork 的派发壳(body=$ARGUMENTS)

派发即现有机制:invoke_skill(skill="dyn-<name>", brief=…) 单发;
compile_fanout(skill="dyn-<name>", briefs_path=…) 批量并发(载荷走文件通道)。
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,49}")
_MODELS = ("haiku", "sonnet", "opus")
# 结构标签注入拦截:role/task/rules 正文里出现骨架标签会破坏三段结构
_TAG_INJECT_RE = re.compile(r"</?(role|task|rules)>", re.IGNORECASE)
# 动态 agent 不授上机执行权(2026-07-05 红线评审观察项机械化):上机独占设备床,
# 进程内互斥/设备残留探测/run-identity 基线全挂在 ist-verify 编排链上——dyn agent
# 直接拿 run 权就绕过了整套护栏(曾实证并发上机互踩配置三轮结果报废)。
_ON_DEVICE_BLOCKED = frozenset({
    "dev_run_batch", "dev_run_batch_digest", "dev_run_case", "dev_init_device",
})


def _err(msg: str) -> str:
    return f"error: {msg}"


@tool(parse_docstring=True)
def agent_define(name: str, description: str, role: str, task: str, rules: str,
                 tools: list | str, model: str = "haiku", overwrite: bool = False) -> str:
    """定义一个可派发的临时子 agent(fork),用于当前任务需要而现有 skill 不覆盖的子流程。

    你只提供语义(角色/任务/规则/工具白名单),文件骨架、frontmatter、共享硬约束
    (证据纪律/忠实汇报/反空转,自动预挂)由工具拼装——不要自己 fs_write agent 文件。
    生成后用 invoke_skill(skill="<返回的名字>", brief=…) 单发,或
    compile_fanout(skill="<名字>", briefs_path=…) 批量并发派发。

    Args:
        name: 短名(小写字母/数字/连字符,≤50)。自动加 "dyn-" 前缀与静态 agent 区隔。
        description: 一句话:它做什么+何时用(第三人称,≤1024,禁 XML 标签)。
        role: <role> 段——它是谁、对什么负责、不对什么负责(职责边界)。
        task: <task> 段——工作流:按什么顺序做什么、产出什么、返回格式。
        rules: <rules> 段——硬约束(只读边界/禁止事项/机读输出契约等),收尾紧邻 brief。
        tools: 工具白名单(原生数组首选,逗号分隔字符串兼容)。每个必须是已注册工具名,
            未注册的直接拒绝——宁可现在报错,不要运行时静默丢工具。
        model: haiku(默认,快而省)/ sonnet / opus(复杂推理才用)。
        overwrite: 同名已存在时默认拒绝;确认要替换旧定义传 True(会清 runnable 缓存)。

    Returns:
        成功:规范名 + 两个产物路径 + 派发用法。失败:error: 开头的具体原因。
    """
    from main.ist_core.skills.loader import (
        _DYN_AGENTS_DIR, _DYN_SKILLS_DIR, _get_tool_registry,
        clear_subagent_cache, load_subagent,
    )

    # --- 名字 ---
    n = (name or "").strip().lower()
    n = n[4:] if n.startswith("dyn-") else n
    if not _NAME_RE.fullmatch(n):
        return _err(f"name {name!r} 不合规——小写字母/数字/连字符,≤50 字符,字母数字开头")
    full = f"dyn-{n}"

    # --- description(进 frontmatter,须 YAML/解析双安全)---
    desc = (description or "").strip()
    if not desc:
        return _err("description 必填(它做什么+何时用)")
    if len(desc) > 1024:
        return _err(f"description {len(desc)} 字符超限(≤1024)")
    if re.search(r"<[a-zA-Z][^>]*>", desc):
        return _err("description 不得含 XML 标签")
    if "---" in desc or "\n" in desc:
        return _err("description 须单行且不含 '---'(frontmatter 解析安全)")

    # --- 三段正文 ---
    sections = {"role": (role or "").strip(), "task": (task or "").strip(),
                "rules": (rules or "").strip()}
    for key, val in sections.items():
        if not val:
            return _err(f"{key} 必填——骨架三段(role/task/rules)一个都不能空")
        if _TAG_INJECT_RE.search(val):
            return _err(f"{key} 正文含骨架标签(<role>/<task>/<rules>)——正文写内容,标签由工具拼")

    # --- 工具白名单(严格:未注册即拒)---
    if isinstance(tools, str):
        tool_names = [t.strip() for t in tools.replace(",", " ").split() if t.strip()]
    elif isinstance(tools, list):
        tool_names = [str(t).strip() for t in tools if str(t).strip()]
    else:
        return _err("tools 须为工具名数组或逗号分隔字符串")
    if not tool_names:
        return _err("tools 至少一个(子 agent 无工具做不了事)")
    registry = _get_tool_registry()
    unknown = [t for t in tool_names if t not in registry]
    if unknown:
        return _err(f"未注册工具: {', '.join(unknown)}。可用: {', '.join(sorted(registry))}")
    blocked = [t for t in tool_names if t in _ON_DEVICE_BLOCKED]
    if blocked:
        return _err(f"动态 agent 不授予上机执行权: {', '.join(blocked)}——"
                    "上机独占设备床,互斥/残留探测/run-identity 护栏全在 ist-verify 编排链上,"
                    "dyn agent 直跑会绕过它们。需要上机结果就正常走 ist-verify。")

    # --- model ---
    m = (model or "haiku").strip().lower()
    if m not in _MODELS:
        return _err(f"model 须为 {_MODELS} 之一,收到 {model!r}")

    # --- 落盘(仅本工具可达 runtime/;同名保护)---
    agent_md = Path(_DYN_AGENTS_DIR) / f"{full}.md"
    skill_md = Path(_DYN_SKILLS_DIR) / full / "SKILL.md"
    if (agent_md.exists() or skill_md.exists()) and not overwrite:
        return _err(f"{full} 已存在。要替换旧定义传 overwrite=True;或换个名字")

    agent_text = (
        "---\n"
        f"name: {full}\n"
        f"description: \"{desc}\"\n"
        f"tools: {', '.join(tool_names)}\n"
        f"model: {m}\n"
        "inherit-parent-prompt: true\n"
        "---\n\n"
        f"<role>\n{sections['role']}\n</role>\n\n"
        f"<task>\n{sections['task']}\n</task>\n\n"
        f"<rules>\n{sections['rules']}\n</rules>\n"
    )
    skill_text = (
        "---\n"
        f"name: {full}\n"
        f"description: \"{desc}\"\n"
        "context: fork\n"
        f"agent: {full}\n"
        "user-invocable: false\n"
        "---\n\n"
        "$ARGUMENTS\n"
    )
    try:
        agent_md.parent.mkdir(parents=True, exist_ok=True)
        skill_md.parent.mkdir(parents=True, exist_ok=True)
        agent_md.write_text(agent_text, encoding="utf-8")
        skill_md.write_text(skill_text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return _err(f"落盘失败: {exc}")

    clear_subagent_cache()   # 覆盖旧定义时旧 runnable 必须失效

    # --- 出厂自检(写完立刻按加载路径读回,坏定义当场报、不留到派发时)---
    spec = load_subagent(full)
    if spec is None:
        return _err(f"自检失败:{agent_md} 写入后无法加载(已写文件请检查)")

    return (
        f"已创建子 agent {full}(model={m},tools={len(tool_names)} 个,共享硬约束已自动预挂)。\n"
        f"- 定义: {agent_md}\n- 派发壳: {skill_md}\n"
        f"派发:invoke_skill(skill=\"{full}\", brief=\"<零上下文交底:目标/已知/边界/产出>\") 单发;"
        f"compile_fanout(skill=\"{full}\", briefs_path=\"workspace/…briefs.json\") 批量并发。\n"
        f"注意:它不进 skill listing(临时件,你自己记得名字);同会话重定义传 overwrite=True。"
    )
