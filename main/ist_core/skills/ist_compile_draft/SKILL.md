---
name: ist_compile_draft
description: "Draft subflow — compile ONE manual test case into a structurally-correct case.xlsx via G→E→V three-layer generation, with per-step Provenance IR. The full method and source.kind data contract live in the subagent system prompt; this task message only frames the case and enforces investigate-before-assert ordering. Does NOT run on-device, does NOT self-assess. Invoked by ist_compile with a structured brief as $ARGUMENTS."
context: fork
agent: ist-compile-draft
user-invocable: false
---

# 任务：编译一条人工用例 → case.xlsx 草稿

把下面 brief 里这条人工用例编译成结构正确、断言真覆盖目标行为的 case.xlsx 草稿。

**怎么编（G→E→V 三层方法、source.kind 契约、V_K/V_R/V_D 期望值分诊、单设备红线、配置装配纪律）见你的系统提示词——此处不重复，只给任务和一条必须先做的事。**

**CRITICAL：先探明，再设计断言。** 在用先例 / `dev_probe` 把"这条用例到底要测什么行为、设备真实回显长什么样"看清楚之前，不要跳去写断言。测试语义不清时（如会话是否保持 / 轮转命中哪个成员 / 计数是否 +1），先 `dev_probe` 观测真实行为再设计——这是"理解行为"，不是"抄设备当前值当期望"（期望值仍按系统提示词的三分诊溯源）。**为什么强制先探**：上一版抢跑、纯靠 footprint 空想测试语义、绕不出来、整条 case 不出 xlsx——别重蹈。

产出：`compile_emit(..., strict_structural=True, provenance_json=...)`；被结构门打回按返回原因**定向修正**，不反复重试同一版本。brief 若带「上一版草稿 + grade/verify 反馈」＝定向重做：针对问题改、保留正确部分。

## Brief from orchestrator

$ARGUMENTS
