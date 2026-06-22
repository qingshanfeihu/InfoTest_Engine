---
name: ist_draft_v2
description: v2 draft subflow — compile one manual test case into a structured case.xlsx via the paper's G→E→V three-layer generation. G-grammar from footprint (no manual grep when hit), G-skeleton + intent-axis precedents (LLM selects), E from env_facts directly, V LLM-filled with provenance, emitted through the correct-by-construction structural gate. Does NOT run on-device, does NOT self-assess. Invoked by ist_compile_v2; takes a structured brief as $ARGUMENTS.
context: fork
agent: ist-draft-v2
user-invocable: false
---

# v2 生成 case.xlsx 草稿（G→E→V 三层）

按论文 G⊔E⊔V 三层分解把下面这条人工用例编译成结构正确、断言覆盖目标行为的 case.xlsx：

- **G-文法**：先 `qa_footprint_lookup` 拿命令参数文法（命中即得不啃手册）；未命中才 grep 对版本手册。
- **G-骨架**：`qa_lookup_pattern(my_config, intent=需求原文)` 拿骨架候选（**带 intent 意图轴**），骨架选择由你做。
- **E**：直接用 `qa_lookup_pattern` 返回末尾的"本测试床网络事实源"拿可达 IP（独立于先例命中）；不可达 IP 当场换。
- **V**：LLM 填业务值，期望值溯源先例/手册/作者意图，不 observe-then-assert。
- **生成**：`qa_emit_xlsx(..., strict_structural=True)` 走结构约束门；被打回按结构原因定向修正。

brief 会给定目标产品+版本和对版本手册 glob。grep CLI 语法只查该版本手册，不用 `*cli__part*` 通配。brief 没给版本就如实报错。

**不调 qa_run_case（上机不属本子流程），不评估自身产物（评估不属本子流程）。**
生成后返回：xlsx 路径 + 测试思路简述（G/E/V 各层依据）。

若 brief 含"上一版草稿 + grade 重做意见 / 结构门反馈"，则为**定向重做**：基于上一版针对问题改，不丢正确部分。

## Brief from orchestrator

$ARGUMENTS
