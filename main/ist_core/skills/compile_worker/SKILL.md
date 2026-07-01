---
name: compile_worker
description: "Compile ONE manual test case into a structurally-correct case.xlsx whose assertions truly cover the target behavior — by replicating main agent's free-reasoning logic (understand the behavior, judge which layer each assertion belongs to, emit via compile_emit). Use when an orchestrator dispatches a single-case compile leg. Does NOT run on-device, does NOT self-assess (orchestrator dispatches grade/verify separately). Invoked with a structured brief as $ARGUMENTS."
context: fork
agent: compile-worker
user-invocable: false
---

# 任务：把一条人工用例编译成 case.xlsx

把下面 brief 里这条人工用例编译成结构正确、断言真覆盖目标行为的 case.xlsx。

像 main agent 那样自由地做：读懂这条 case 测的是什么行为 → 判断每条断言的期望值属静态层还是运行时层 → 设计步骤（配置 / 触发 / 断言）→ `compile_emit` 落盘。怎么判层、命令文法从哪查、三个设备真相（单设备 / 装配完整 / dig 触发机），都在你的系统提示词里，按它来。

brief 末尾内联了预检索的先例和 footprint——那是**命令文法的参考**（帮你确认命令怎么写），不是要你照先例的断言抄。需要确认行为或文法时，`fs_read` / `kb_footprint` / `compile_precedent` / `dev_probe` 随你判断用，**没有非走不可的固定顺序**。

`compile_emit` 返回「已产出」就是终点——拿到路径给一句话测试思路返回。不自审自产、不读回 case.xlsx 逐项打勾：语义覆盖归 orchestrator 另派的 grade、落点归 verify 上机。

## Brief from orchestrator

$ARGUMENTS
