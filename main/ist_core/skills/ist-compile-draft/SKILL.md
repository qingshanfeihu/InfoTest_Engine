---
name: ist-compile-draft
description: "Draft subflow — compile ONE manual test case into a structurally-correct case.xlsx draft whose assertions truly cover the target behavior. Use when ist-compile dispatches a single-case compile leg (脑图→草稿、生成断言草稿、先例检索+emit). Reads the prefetched precedent + footprint first, probes only on genuine semantic gaps. Does NOT run on-device, does NOT self-assess. Invoked by ist-compile with a structured brief as $ARGUMENTS — use whenever you need a per-case xlsx draft before grading."
context: fork
agent: ist-compile-draft
user-invocable: false
---

# 任务：编译一条人工用例 → case.xlsx 草稿

把下面 brief 里这条人工用例编译成结构正确、断言真覆盖目标行为的 case.xlsx 草稿。

**怎么编（G→E→V 三层方法、`source.kind` 取值与每层定义、期望值分诊细则（①配置可推导/②运行时单点/②b命中归属/③设备不透明单值/分布区间）、单设备红线、配置装配纪律）见你的系统提示词——此处不重复，只给任务和一条必须先做的事。**

> 契约指针：本草稿的数据契约（每断言 `source.kind` 取值、G/E/V 层映射、分诊规则）权威定义在 `agent=ist-compile-draft` 系统提示词，按此溯源；本 SKILL.md 不重述，避免双份易漂移。

**CRITICAL：先读 brief 预检索材料，再决定要不要探——别抢跑工具。** brief 末尾已为你**确定性预检索**好「先例」+「footprint 文法」，按序用：
1. **先读「预检索先例」+「预检索 footprint」**：先例的触发→断言链 + footprint 的命令文法/行为——**多数 case 这两样就够**，直接设计断言、`compile_emit`，**别重复调 `kb_footprint`/`compile_precedent` 查它们已给的东西**。
2. **仅当 brief 仍说不清要测什么行为**（会话是否保持 / 轮转命中哪个成员 / 计数是否 +1）才 `dev_probe` 观测真实行为——这是"理解行为格式"，**不是抄设备当前值当期望**（期望值仍按系统提示词的分诊规则溯源）。
3. 文法仍缺的命令才 `kb_footprint` 补。

**为什么这样排**：上一版纯靠空想测试语义、绕不出来、case 不出 xlsx——故保留"语义不清必须探"兜底；但预检索已把先例+文法摆上桌后还盲目重探，是反向的浪费。**先用现成的，缺口才探。**

产出：`compile_emit(..., strict_structural=True, provenance_json=...)`；被结构门打回按返回原因**定向修正**，不反复重试同一版本。brief 若带「上一版草稿 + grade/verify 反馈」＝定向重做：针对问题改、保留正确部分。

## Validation（产出后自检）

- emit 走 `strict_structural=True`，且未被结构门打回（被打回则定向修正后重发，不重试同一版本）。
- 每条断言都带 `source.kind`（值与 G/E/V 层定义见上方契约指针）。
- 凡能离线定值的期望值都已定死，未遗留可离线定值的 `<RUNTIME>` 占位（真运行时项才留给 `compile_runtime_fill` 回填）。

## Brief from orchestrator

$ARGUMENTS
