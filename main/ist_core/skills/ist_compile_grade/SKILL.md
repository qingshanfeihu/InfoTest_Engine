---
name: ist_compile_grade
description: "Grade subflow — judge ONLY whether a case.xlsx's V-segment assertions cover the requirement's target behavior, by verifying the draft's Provenance IR instead of re-grepping the manual. The judgment rules live in the subagent system prompt; this task message only frames the case and enforces verify-sources-before-judging ordering. Read-only. Emits a machine-readable verdict line. Invoked by ist_compile with a structured brief as $ARGUMENTS."
context: fork
agent: ist-compile-grade
user-invocable: false
---

# 任务：审批一份 case.xlsx 的 V 段断言覆盖度

判断下面 brief 里这份 case.xlsx 的 V 段断言是否真覆盖需求要测的行为。

**怎么判（验 provenance 来源、两类"非弱断言"的判别细则、compile_score、对抗性核对）见你的系统提示词——此处只给任务和一条必须先做的事。**

**CRITICAL：先验来源，再判覆盖。** 在核对完 draft 记在 `case.provenance.json` 的来源之前，不要从零 grep 手册下判定。**为什么**：来源已由 draft 记在 provenance，你的活是**核它**、不是重查（曾出现 grade 去 grep 仓库根目录空转）。

两类**看着像弱断言、实为正确形态**的，不当弱断言砍（判别细则见系统提示词）：`<RUNTIME>`（`device_runtime`）诚实弃权、`found/not_found(寄存器)` 捕获关系。

**输出的最后一行必须是机读裁定、单独成行**：`判定：PASS` 或 `判定：CUT`（重做意见写在此行之前，编排器靠这行判定）。

## Brief from orchestrator

$ARGUMENTS
