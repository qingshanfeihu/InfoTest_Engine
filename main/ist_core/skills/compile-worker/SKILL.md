---
name: compile-worker
description: "Compile ONE manual test case into a structurally-correct case.xlsx whose assertions truly cover the target behavior — by replicating main agent's free-reasoning logic (understand the behavior, judge which layer each assertion belongs to, emit via compile_emit). Use when an orchestrator dispatches a single-case compile leg. Does NOT run on-device, does NOT self-assess (orchestrator dispatches grade/verify separately). Invoked with a structured brief as $ARGUMENTS."
context: fork
agent: compile-worker
user-invocable: false
---

# 任务：把一条人工用例编译成 case.xlsx

把下面 brief 里这条人工用例编译成结构正确、断言真覆盖目标行为的 case.xlsx。

像 main agent 那样自由地做：读懂这条 case 测的是什么行为 → 判断每条断言的期望值属静态层还是运行时层 → 设计步骤（配置 / 触发 / 断言）→ `compile_emit` 落盘。怎么判层、命令文法从哪查、三个设备真相（单设备 / 装配完整 / dig 触发机），都在你的系统提示词里，按它来。

brief 开头若带 JSON 信封（autoid/manifest_path/advisory_path/round/redispatch_reason）：先 `fs_read` `manifest_path` 里你这个 autoid 的 step_intents **原文**（那是需求原件，brief 正文若与之出入以 manifest 为准），再 `fs_read` `advisory_path` 的全批守则；`redispatch_reason` 告诉你这次重派是为什么（grade 重做意见 / emit 报错 / 用户决策），对症改、别全部重来。

brief 末尾内联了预检索的先例和 footprint——那是**命令文法的参考**（帮你确认命令怎么写），不是要你照先例的断言抄。需要确认行为或文法时，`fs_read` / `kb_footprint` / `compile_precedent` / `dev_probe` 随你判断用，**没有非走不可的固定顺序**。

`compile_emit` 返回「已产出」就是终点——拿到路径给一句话测试思路返回。不自审自产、不读回 case.xlsx 逐项打勾：语义覆盖归 orchestrator 另派的 grade、落点归 verify 上机。

**返回的最后两行是机读尾块，逐字格式、单独成行**（orchestrator 靠它对账；正文内容随你写）：

```
状态：produced | needs_user_decision | failed   （三选一，只留一个）
产物：workspace/outputs/<autoid>/case.xlsx      （produced 给路径；其余写 -）
```

needs_user_decision 时正文把证伪工具返回的欠定 claim、保留约束与候选改法原样带出；failed 时正文带最后一次报错原文。别把「否/未触发/不需上报」这类否定措辞与标记词混在一句里——历史实证 46 份返回里 40 份含 NEEDS_USER_DECISION 字样、真欠定只有 6 份，机读只认上面的尾块。

## Brief from orchestrator

$ARGUMENTS
