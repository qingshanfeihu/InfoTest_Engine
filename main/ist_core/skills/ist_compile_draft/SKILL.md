---
name: ist_compile_draft
description: Draft subflow — compile one manual test case into a structured case.xlsx via the paper's G→E→V three-layer generation, AND emit a three-layer Provenance IR (per-step layer + source) alongside it. G-grammar from footprint, G-skeleton + intent-axis precedents (LLM selects), E from env_facts directly, V LLM-filled with provenance, emitted through the correct-by-construction structural gate with provenance_json. Compiles each case directly (no family-skeleton reuse — measured net-negative, removed). Does NOT run on-device, does NOT self-assess. Invoked by ist_compile; takes a structured brief as $ARGUMENTS.
context: fork
agent: ist-compile-draft
user-invocable: false
---

# 生成 case.xlsx 草稿（G→E→V 三层 + Provenance IR）

按论文 G⊔E⊔V 三层把下面这条人工用例编译成结构正确、断言覆盖目标行为的 case.xlsx，同时旁挂带来源的三层 provenance。

**brief 末尾已为你预检索好「预检索先例」（含完整配置基线 + 触发→断言链 + 网络事实源）——优先照它改写，少跑检索轮次。** 只有先例缺的命令/语法才另查 footprint/手册（轨迹缩减，省往返）：

- **G-骨架（先用预检索先例）**：直接采用 brief 里「预检索先例」的骨架（记 `kind=precedent`），逐 case 改写，不复用族骨架。**照先例完整配置基线写，别截断**——启用/激活步（如 `sdns on`）、数据中心/池法/监听器等基线步一个不能漏；漏了服务不起、dig 零解析、断言全 fail。能跑通的 case = 完整基线 + 触发 + 断言，三者配套照抄。预检索为空（分布外）才 `compile_precedent` 自查。
- **G-文法（先例缺才查）**：先例里已用到的命令直接照搬。**只有先例没覆盖的命令**才 `kb_footprint`（命中采信签名，记 `kind=footprint`）。**你没有手册全文 grep 工具**（有意为之——上一版 grep 大手册 20+ 次空转）：footprint 也没有的命令，用 `dev_probe` 探设备真实回显确认，或按最接近语法推断 + 标 `kind=manual`，绝不空转找全文。
- **E**：用 brief 里「本测试床网络事实源」的可达 IP（在预检索先例块末尾），不可达当场换（记 `kind=env_facts`）。绝不照抄示例 IP（1.1.1.1 等）。
- **V**：填业务断言，期望值溯源先例 / 手册 / 作者意图，不 observe-then-assert（记 `kind=manual/precedent/intent`）。
- **V-不可知值（写不准就留空，绝不编）**：若某断言的期望值**离线根本无法定**（先例/手册都没有、是运行时才产生的落点——dig 轮转解析出的具体 IP、Hit/统计计数、会话/连接保持的具体值、哈希、脚本运行时生成值），**不许凭空编一个值**。这类期望值：
  - **优先写部分模式**：把能溯源的**结构**写实（前缀来自手册/先例），只把那个不可知的值槽位留成 `<RUNTIME>`——例如断言"命中统计行存在但具体数不可知"写 `...Hits:\s*<RUNTIME>`（前缀 `Hits:` 溯源手册，数留空）。这样既测真行为又不编数。
  - **整值不可知**：连结构都无从溯源时，G 整个填 `<RUNTIME>`。
  - 这类步骤一律标 `source.kind=device_runtime`（`<RUNTIME>` ⟺ `device_runtime` 双向自洽，emit 结构门会强制；填了占位却标别的来源、或标了 device_runtime 却填具体值，都会被打回）。
  - `<RUNTIME>` 的真实值由后续 `ist_verify` 上机回填并锁死——你这步**只负责诚实留空**，不要为了让它上机过而编一个值。
- **生成**：`compile_emit(..., strict_structural=True, provenance_json=<CaseProvenance JSON>)`。provenance 的 steps E/F/G 必须与 steps_json 逐字一致。被结构门打回就按返回原因定向修正，不反复重试同一版本。

brief 会给定目标产品 + 版本和对版本手册 glob。grep 只查该版本手册。brief 没给版本就如实报错。

不调 dev_run_case，不评估自身产物。返回：xlsx 路径 + 一句话测试思路（G/E/V 各层依据）+ provenance 旁挂确认。

若 brief 含"上一版草稿 + grade/verify 反馈"，则为定向重做：基于上一版针对问题改，不丢正确部分。

## Brief from orchestrator

$ARGUMENTS
