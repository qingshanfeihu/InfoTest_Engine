---
name: ist_compile_draft
description: Generate a structured case.xlsx draft from one manual test case (or rework a prior draft using the device verdict and grading feedback). Checks preconditions, retrieves canonical precedents, emits the xlsx. Does NOT run on-device and does NOT self-assess — the orchestrator dispatches run/grade separately. Invoked by ist_compile_orchestrate; takes a structured brief as $ARGUMENTS.
context: fork
agent: ist-compile-draft
user-invocable: false
---

# 生成 case.xlsx 草稿

按流程把下面这条人工用例编译成结构正确、断言覆盖目标行为的 case.xlsx：
核查前置（检索先例完整 init、probe 设备、grep 手册）→ 检索先例确定测法 → qa_emit_xlsx 生成。

- 断言期望值溯源先例/手册，不用裸 IP/域名匹配充数。
- 编译轮询/会话保持等多次行为：按确定顺序逐次断言不同命中值（参照同类先例做法）。
- **不调用 qa_run_case（上机不属本子流程），不评估自身产物（评估不属本子流程）**。
- 生成后返回：xlsx 路径 + 测试思路简述（覆盖什么行为、断言什么、期望来源）。

若 brief 含"上一版草稿 + 设备真实裁决 + 评估重做意见"，则为**定向重做**：基于上一版、针对评估指出的问题修改，不丢弃已正确部分。

## Brief from orchestrator

$ARGUMENTS
