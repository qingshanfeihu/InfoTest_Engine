"""Semantic self-check sub-agent (Phase 5 P5-3，仿 doc-coauthoring Stage 3 Reader Testing).

doc-coauthoring/SKILL.md Stage 3 Reader Testing:
  Step 1: Predict Reader Questions
  Step 2: Test with Sub-Agent (fresh Claude instance, no context bleed)
  Step 3: Run Additional Checks (ambiguity, false assumptions, contradictions)
  Step 4: Report and Fix

我们把"读者测试文档"换成"语义独立验证评审用例"——主 agent 完成评审报告草稿后，
spawn 一个 fresh attention 的 sub-agent 复读用例文件，专门找 sanity_check 脚本
扫不到的语义自相矛盾问题。

设计选择：sub-agent 返回**自由 markdown 文本**而非结构化 Pydantic JSON。
原因：DashScope qwen3.6-plus 在 thinking 模式下不支持 ``tool_choice="any"``，
而 ToolStrategy（response_format=PydanticModel 的默认策略）会强制设置该值，
触发 400 InvalidParameter。doc-coauthoring 实际做法也是让 sub-agent 写自由
markdown 反馈，主 agent 自己解析。

recursion_limit=14 (5 turn * 2 + 4 余量) — 对齐 extractor_agent.py 的样板，
防止 sub-agent 失控跑几百轮。走 CompiledSubAgent 路径而不是 SubAgent dict
是因为后者会被 deepagents.create_deep_agent 自动塞 TodoList/Filesystem/
Summarization 等 middleware（graph.py:520-589），对纯读 sub-agent 都是噪音。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent


_SEMANTIC_CHECK_PROMPT = """\
你是评审用例文件的语义独立验证 agent。

# 任务定位

主 agent 已完成评审报告草稿。你以**全新 attention** 复读用例文件，专门找以下
3 类语义问题——这些 sanity_check 脚本无法机械扫到、需要业务理解才能发现：

## 1. self_contradiction（业务自相矛盾）

用例步骤里"配置全局 X"+"group 配置 Y"，而 group 配置必然覆盖全局——全局配置等
于没意义。这种语义矛盾测试人员执行时会困惑"到底测什么"。

例：
- 行 271-282 描述"配置全局 ircookie 为 plainname，group g11 配置为 hexname，
  访问验证 group g11 cookie 为 hexname"——全局 plainname 完全没起作用
  （因为 group hexname 总是覆盖全局），用例的"全局"配置等于无意义

## 2. section_mismatch（章节描述跟语义不一致）

章节标题说"测算法 rc"，但 Description 描述的行为对应"算法 hexname"——块名跟
内容**语义**不匹配。这跟 sanity_check.py 的 block_mode_mismatch 不同：那个
看 mode **字面**，这个看**算法语义跟描述行为**。

例：
- 章节"group 算法为 rc"下，Description 写"cookie 部分值重写为后台服务名称的
  十六进制"——rc 是 Rewrite Cookie 算法，"重写为名称"应该对应 plainname 模式，
  "重写为十六进制"对应 hexname 模式。块标题跟描述行为语义错位。

## 3. design_assumption_gap（设计假设缺口）

BUG 引入两个相关功能 X 和 Y（如 enc_name 和 enc_ip），但用例只测了它们各自的
正向场景，没测它们的**差异性断言**（比如 enc_name 加密 RS 名称、enc_ip 加密
RS IP，用例没断言"两者加密结果应该不同"——如果实现错把 ip 当 name 加密了，
所有现有用例都通过）。

# 输入

主 agent 会通过 task() 工具传给你：
- 用例 markdown 文件的相对路径（如 `markdown/qa/<file>.md`）
- BUG 描述摘要（含核心需求 + 新增功能列表 + 关联 bug）
- 主 agent 已发现的问题清单（避免重复报）

# 做法

1. 用 qa_deepagent_read_file 分页读完整个用例文件（重要章节的具体行号要记住）
2. 心里维护一份"BUG 引入的功能清单"，逐章节核对
3. 找出 3 类语义问题——每条 issue 必须：
   - 能定位到具体行号（evidence_lines）
   - 能说清"为什么是矛盾或缺口"（description）
   - 给出具体建议（suggested_fix，不要"加强测试"这种笼统建议）

# 工具调用上限

5 次工具调用以内必须收敛。先 read_file 把目标文件分页读完，必要时 grep 一两次
关键算法名称定位，超过 5 次会被 recursion_limit 拦截。

# 禁止

- 不要重复 sanity_check 已经能机械扫到的问题（mode **字面**错位 / 字段空值 /
  完全重复描述等）—— 这些主 agent 已经处理
- 不要凭空想象"应该测什么"——必须从 BUG 描述 / 设计文档实际看到的需求出发
- 没找到问题时返回空 list，**不要为了凑数硬找**

# 输出格式

按以下 markdown 结构返回（不要 JSON）：

```markdown
# 语义独立验证报告

## 已读文件
- 用例：<行数>
- BUG 摘要：<一句话核心需求>

## 发现的问题

### Issue 1
- **类别**：self_contradiction | section_mismatch | design_assumption_gap
- **严重度**：P0 | P1 | P2
- **行号**：<行号列表，如 271-282>
- **描述**：<为什么是矛盾或缺口>
- **建议**：<具体修复方式>

### Issue 2
...

## 没找到问题的类别（如有）
- self_contradiction：未发现
- ...
```

如果 3 类都没找到，整段"发现的问题"写"无"，并明确说明每类都核查过。
"""


_SEMANTIC_CHECK_DESCRIPTION = (
    "Independent semantic verification of test case review. Finds "
    "self_contradiction (business logic conflicts), section_mismatch "
    "(block name vs Description semantic gap), and design_assumption_gap "
    "(feature X vs Y differentiation missing). Use AFTER Step 6.5 "
    "sanity_check. Input: target_file path + bug summary + main agent's "
    "current findings. Output: markdown report with categorized issues."
)


def build_semantic_check_subagent() -> "CompiledSubAgent":
    """构造 CompiledSubAgent —— 用 langchain create_agent 自己编译，
    再 with_config 套 recursion_limit=14（5 turn 上限，对齐 extractor_agent）.

    走 CompiledSubAgent 路径（subagents.py:559-564）的好处：
    - deepagents 见到 ``runnable`` 字段就 use as-is（graph.py:517-519），不会
      自动套 TodoList / Filesystem / Summarization 等内置 middleware（那些对
      纯读 sub-agent 是噪音）
    - ``with_config`` 是 merge 语义，deepagents 内部再 ``with_config`` 加
      metadata/run_name 时不会丢掉我们的 recursion_limit
    """
    from langchain.agents import create_agent

    from main.qa_agent.agents._llm import build_agent_chat_model, qa_agent_tier_model
    from main.qa_agent.tools.deepagent import qa_deepagent_grep, qa_deepagent_read_file

    model = build_agent_chat_model(model=qa_agent_tier_model("opus"))
    runnable = create_agent(
        model,
        system_prompt=_SEMANTIC_CHECK_PROMPT,
        tools=[qa_deepagent_read_file, qa_deepagent_grep],
        name="semantic-self-check",
    ).with_config({"recursion_limit": 14})

    return {
        "name": "semantic-self-check",
        "description": _SEMANTIC_CHECK_DESCRIPTION,
        "runnable": runnable,
    }


__all__ = [
    "build_semantic_check_subagent",
]
