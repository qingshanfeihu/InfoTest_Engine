---
name: compile-worker
description: "Compile ONE manual test case into a structurally-correct case.xlsx whose assertions truly cover the target behavior — by replicating main agent's free-reasoning logic (understand the behavior, judge which layer each assertion belongs to, emit via compile_emit). Use when an orchestrator dispatches a single-case compile leg. Does NOT run on-device, does NOT self-assess (orchestrator dispatches verify separately). Invoked with a structured brief as $ARGUMENTS."
context: fork
agent: compile-worker
user-invocable: false
---

# 任务：把一条人工用例编译成 case.xlsx

紧接在下方的是 orchestrator 派发的 brief：首行机读信封，随后是数据区（历史设备证据 / 结构事实 / 归因假设 / 意图）。任务指令在 brief 之后的 `<instructions>` 里。

## Brief from orchestrator

$ARGUMENTS

<instructions>
把上面 brief 里这条人工用例编译成结构正确、断言真覆盖目标行为的 case.xlsx。

像 main agent 那样自由地做：读懂这条 case 测的是什么行为 → 判断每条断言的期望值属静态层还是运行时层 → 设计步骤（配置 / 触发 / 断言）→ `compile_emit` 落盘。怎么判层、命令文法从哪查、三个设备真相（单设备 / 装配完整 / dig 触发机），都在你的系统提示词里，按它来。

brief 首行的 JSON 信封（autoid/manifest_path/advisory_path/round/redispatch_reason）：先 `fs_read` `manifest_path` 里你这个 autoid 的 step_intents **原文**（那是需求原件，brief 里的意图摘要若与之出入以 manifest 为准），再 `fs_read` `advisory_path` 的全批守则；`redispatch_reason` 告诉你这次重派是为什么（探针提示 / emit 报错 / 用户决策 / 上机失败），对症改、别全部重来。

brief 里工具注入的设备证据 / 先例 / footprint 是**事实参考**——帮你确认命令怎么写、上一轮设备上真实发生了什么，不是要你照先例的断言抄。需要确认行为或文法时，`fs_read` / `kb_footprint` / `compile_precedent` / `dev_probe` 随你判断用，**没有非走不可的固定顺序**。

`compile_emit` 返回「已产出」就是终点——拿到路径给一句话测试思路返回。不自审自产、不读回 case.xlsx 逐项打勾：语义终判在独立的上机验证，不在你这里。

**返回的最后两行是机读尾块，逐字格式、单独成行**（orchestrator 靠它对账；正文内容随你写）。两种常见收尾的完整形态：

<examples>
<example>
（正文：测试思路一句话——覆盖什么行为、断言什么、期望来源）

状态：produced
产物：workspace/outputs/204650000000000123/case.xlsx
</example>
<example>
（正文：原样带出证伪工具的 NEEDS_USER_DECISION 整段 + 保留约束 + 待决 claim）

状态：needs_user_decision
产物：-
</example>
</examples>

failed 时正文带最后一次报错原文、尾块同格式（状态：failed / 产物：-）。别把「否/未触发/不需上报」这类否定措辞与标记词混在一句里——历史实证 46 份返回里 40 份含 NEEDS_USER_DECISION 字样、真欠定只有 6 份，机读只认上面的尾块。
</instructions>
