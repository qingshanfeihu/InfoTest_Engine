---
name: ist_compile_v2
description: "v2 用例编译编排（论文 G⊔E⊔V 三层 + correct-by-construction 结构门 + 意图检索轴）。与 v1（ist_compile_batch）同流程骨架——通读用例→解析 manifest→draft 并发→grade 并发→合并打包——但 draft 走 ist_draft_v2：G 层先查 footprint 文法（命中不啃手册）、骨架检索带意图轴、emit 走结构约束门（命令∈allowlist + 断言非悬空，确定性强制）。默认关闭（实验链路），用户显式要 v2 / 三层编译 / 结构门时启用。"
context: inline
user-invocable: true
source: hand
version: "1"
effort: high
when_to_use: |
  Use when 用户显式要求 v2 编译链 / 三层（G⊔E⊔V）生成 / correct-by-construction 结构门 / 意图轴检索编译。
  Examples: "用 v2 编译链把这条脑图编译成 excel", "走三层生成 + 结构门编译", "用意图轴检索 + footprint 文法编译这批用例"。
  Trigger keywords: v2编译, 三层编译, GEV, correct-by-construction, 结构约束门, 意图轴编译, footprint文法编译。
  SKIP when: 默认生产编译走 ist_compile_batch（v1）；只查 CLI 回显用 qa_probe_show；评审已有用例用 test-list-review。
---

# v2 编译编排：G⊔E⊔V 三层 + 结构门 + 意图轴

把人工测试用例编译成自动化 **excel**，流程骨架与 v1（ist_compile_batch）一致——你是编排器，不亲自生成命令：通读用例→解析 manifest→draft 并发生成→grade 并发审批→合并打包。**v2 的差异全在 draft 子流程内部**，编排层调度方式不变。

## v2 相对 v1 的三个差异（你只需知道，调度照旧）

1. **G 层先查表**：draft 用 `ist_draft_v2`，命令文法先 `qa_footprint_lookup` 命中即得（不啃手册，提速核心）；未命中才 grep 对版本手册。
2. **骨架检索带意图轴**：draft 调 `qa_lookup_pattern(my_config, intent=需求原文)`——分布外 case（还没想好配什么命令）也能凭意图检索到骨架先例。
3. **emit 走结构约束门**：draft 的 `qa_emit_xlsx(strict_structural=True)` 强制 correct-by-construction（命令∈手册 allowlist + 断言非悬空），与 grade 的语义审批**独立**。结构错误在 emit 当场打回，不进 grade。

## 第一原则（与 v1 同，不可违反）

**零硬编码、纯引导**：你和子流程的 brief 里绝不出现具体设备命令、不按关键字分支、不逐 autoid 特殊处理。命令/参数/断言全由 draft 现场查 footprint/手册/先例得出。结构约束（命令合法性/断言非悬空/IP 可达）由 emit 门确定性强制；骨架选择（测什么/命令序列/断言形态）是 draft 的 LLM 语义决策——二者分明，互不越界。

## 物理边界（落在工具里）

| 阶段 | 工具 | 并行性 | v2 说明 |
|---|---|---|---|
| 解析 | `qa_compile_prep` | 一次 | 解析脑图→manifest（只含需求，零命令） |
| 生成 draft | `qa_compile_fanout(skill="ist_draft_v2")` | **并发** | G⊔E⊔V 三层 + 结构门，查 footprint/手册/先例 |
| 审批 grade | `qa_compile_fanout(skill="ist_grade_v2")` | **并发** | 只判 V 段语义（断言是否覆盖目标行为），结构合法性归结构门 |
| 打包 | `qa_emit_xlsx_merged` | 一次 | 同脑图 grade-PASS 合并成一个 excel + 哨兵 |

**编译与上机解耦**（同 v1）：本 skill 只产出 excel，不上机。上机由 ist_verify 独立做。

## 编排器步数纪律（同 v1，必须遵守）

你每个脑图只允许这几类调用：`qa_compile_prep`（1）→ 读 manifest（1-2）→ `qa_compile_fanout(ist_draft_v2)`（1，一把梭）→ `qa_compile_fanout(ist_compile_grade)`（1）→ 判定 → 重做 fanout（如需）→ `qa_emit_xlsx_merged`（1）。**查 footprint/手册/先例的活全在 fanout 内由 draft 子 agent 做，你不碰。**

## 流程

### 0. 校验版本（必须先做，缺版本立即 qa_ask_user）
不同版本对应不同手册/命令语法。从用户请求原文提取产品+版本（如 APV 10.5）；没写就 `qa_ask_user` 问，不猜。确定后推手册 glob（`10.5` → `10.5_cli__part*.md`），写进每条 brief 的"指路"。

### 1. 解析：`qa_compile_prep(mindmap_path=..., out_name=<脑图名>)`
产出 manifest.json（autoid 主键，命令/步骤为 null——由 draft 回填）。注意 `groups`：组级共享基线需求要写进每个 case 的 brief（只传需求，不传命令）。

### 2. 派发 draft（并发）— skill="ist_draft_v2"
为每个 case 组五要素 brief（见下），一次性 fan-out：
```
qa_compile_fanout(skill="ist_draft_v2", briefs_json='[{"key":"<autoid>","brief":"<五要素brief>"}, ...]')
```
返回每个 key 的 draft 产物（xlsx 路径 + 测试思路）。失败（ok=false）记下稍后重做，成功的回填 manifest 的 `compile_state.draft_xlsx`。

### 3. 派发 grade 审批（并发）— skill="ist_grade_v2"
draft 出齐后并发 grade。v2 grade **只判 V 段语义**（断言是否真覆盖目标行为）——结构合法性（命令 allowlist / 断言悬空 / IP 可达）已由 emit 结构门确定性强制，不归 grade，不依赖上机：
```
qa_compile_fanout(skill="ist_grade_v2", briefs_json='[{"key":"<autoid>","brief":"xlsx_path=...; 原始需求=<脑图step+expected>"}, ...]')
```
回填 `compile_state.grade`。

### 4. 判定 + 重做循环（grade-PASS 即交付）
**自主决策，绝不 qa_ask_user 问"合并哪些/要不要重做"**：
- grade PASS → `status=done`，进第 5 步。
- grade CUT → 携带反馈（上一版 + grade 意见）重新 fan-out `ist_draft_v2`，回第 3 步。
- 连续 N 轮（建议 3）仍 CUT → `status=escalated`，不拿弱产物充数，记卡点。
- 部分 PASS 部分 CUT 是常态：PASS 先合并交付，CUT 另行重做，两件都做，不停下问用户。

### 5. 合并打包：`qa_emit_xlsx_merged`
把所有 `status=done` 的 case 合并成一个 excel（每 case 自带 draft 回填的自包含 init）：
```
qa_emit_xlsx_merged(cases_json='[{"autoid":"...","title":"...","init":"<自包含前置>","steps":[...]}, ...]', out_name="<脑图名>")
```
落 `workspace/outputs/<脑图名>/case.xlsx`。

### 6. 收尾：报告产出 + 询问是否上机验证
报告每个脑图的 excel 路径 + case 数（PASS / escalated）。`qa_ask_user`「excel 已生成，是否现在上机验证（ist_verify）？」用户选是 → `qa_invoke_skill(skill="ist_verify", brief="验证 workspace/outputs/<脑图名>/case.xlsx,build=<版本>")`；选否 → 结束。非交互模式（`infotest -p`）直接报告完成，不阻塞。

### 7. 多脑图
对每个脑图跑 1-5，draft/grade 可跨脑图一起 fan-out。每脑图产一个独立 excel。

## brief 五要素（派发 draft 时，逐项过滤"答案"）

1. **需求（objective）**：autoid、标题、脑图原文步骤 + 期望。
2. **现状（state）**：目标模块、目标产品+版本（缺则已 ask_user）、所属分组、组级共享基线需求。
3. **规则（rules）**：期望值溯源先例/手册/作者意图，不许 observe-then-assert；轮询/会话保持按确定顺序逐次断言；每个 case 自包含（init 自建全部前置）。
4. **指路（tools/sources）**：先 `qa_footprint_lookup` 查命令文法（命中不啃手册）；未命中 grep 对版本手册 `{版本}_cli__part*.md`（不用 `*cli__part*` 通配）；骨架用 `qa_lookup_pattern(my_config, intent=需求原文)` 带意图轴召回；IP 取返回末尾"本测试床网络事实源"的可达值；拿不准命令用 qa_probe_show 探。
5. **边界（boundaries）**：你只生成 draft（emit 必须 `strict_structural=True`，不上机、不自评）；重做时基于上一版改、保留正确部分。

**自检三问**：① 这句是"需求/现状/规则/指路"还是"命令/期望值/映射"？后者删。② 删掉后子 agent 是"查不到"还是"想不到"？查不到补"去哪查"，不补答案。③ 换个 build/设备还成立吗？不成立=领域写死了。

## 约束（编排红线）
- **编排器不亲自生成/审批**：draft/grade 全派发；你只解析、调度、判定、重做、合并、上报。
- **结构约束 vs 语义审批分明**：结构门（emit，确定性）管命令合法性/断言非悬空/IP 可达；grade（LLM）管断言是否覆盖目标行为。交付门槛 = grade 通过（结构门是 draft 内部的产出前置，结构不合格根本 emit 不出来）。
- **上机已解耦**：本 skill 内不调 qa_run_batch / run。上机走 ist_verify。
- **零命令进 brief/manifest**：命令全由 draft 现场查证。
- **失败如实上报**：N 轮 CUT 标 escalated，不充数。
