---
name: ist_compile_batch
description: "把整个脑图文件（含几十条用例）批量编译成一个 excel——通读脑图→备料 manifest→按阶段批量并行调度（draft 并发、run 串行、grade 并发）→合并打包。面向『把 N 个 txt 转成 N 个 excel』『把整个脑图转自动化』这类批量请求；单条用例编译仍用 ist_compile_orchestrate。"
context: inline
user-invocable: true
source: hand
version: "1"
effort: high
when_to_use: |
  Use when 用户要把**整个脑图文件 / 多个 txt** 批量编译成 excel（一个脑图一个 excel，含该脑图全部用例）。
  Examples: "把 automatic_case 下 3 个 txt 的脑图用例转成 3 个 excel", "把 dongkl.txt 整个编译成 excel", "把这几个脑图批量转自动化", "一次把整张脑图的用例都编译了"。
  Trigger keywords: 批量编译, 多个脑图, 3个txt, 整个脑图, 一个脑图一个excel, 批量转excel, 全部用例, 并行编译。
  SKIP when: 只编译**单条**用例（用 ist_compile_orchestrate）；只查 CLI 回显（qa_probe_show）；评审已有用例（test-list-review）。
---

# 批量编译总厨：通读脑图→备料→分阶段并行调度→合并打包

把**一个脑图文件**编译成**一个 excel**（含该脑图全部用例，每条都上机跑通且断言真覆盖）。你是总厨，不亲自炒菜：通读整桌点单（脑图）→列备料清单（manifest）→按阶段把活铺开给子流程（draft/run/grade），最后把通过的菜合并装盘。

## 餐厅比喻（为什么分阶段，不逐条从头炒）

逐条 orchestrate = 每道菜从头备料炒，慢且重复。正确做法：先看整桌点了什么（prep），能并行的并行（draft 各菜同时下锅、grade 同时品控），只有抢同一口锅的串行（run 上机受框架全局锁，必须排队）。

## 第一原则（不可违反，高于一切）

**零硬编码、纯引导**：你和所有子流程的代码/brief 里**绝不出现任何具体设备命令**（如 sdns/slb CLI）、不按关键字分支、不逐 autoid 特殊处理。命令/参数/断言全部由 draft 子 agent **现场查手册（`*cli__part*.md`）/查先例（qa_lookup_pattern）**得出。你给子流程的 brief 只含**需求+现状+规则+指路+边界**（见下"brief 五要素"），绝不喂答案。

## 物理边界（硬约束，落在工具里，不靠自律）

| 阶段 | 工具 | 并行性 | 为什么 |
|---|---|---|---|
| 备料 | `qa_compile_prep` | 一次 | 解析脑图→manifest（只含需求，零命令） |
| 生成 draft | `qa_compile_fanout(skill="ist_compile_draft")` | **并发** | 查手册+本地 emit，不碰设备态 |
| 上机 run | `qa_run_batch` | **串行**（工具内部 for 循环） | 框架全局锁 + 设备共享态，并发必互相污染 |
| 评估 grade | `qa_compile_fanout(skill="ist_compile_grade")` | **并发** | 纯本地判分，零设备交互 |
| 打包 | `qa_emit_xlsx_merged` | 一次 | 同脑图通过的 case 合并成一个 excel + 哨兵垫底 |

## 总厨步数纪律（必须遵守，否则跑不完整批）

你的工具调用步数有硬上限（recursion_limit）。批量编译有几十上百个 case，**你绝不能自己逐 case grep 手册 / qa_probe_show 探设备 / qa_lookup_pattern 查先例**——那是 draft 子 agent 的活，你这么做会在备料阶段就把步数耗光，整批编译半途而废（已有前车之鉴）。

你（总厨）每个脑图**只允许这几类调用**：`qa_compile_prep`（1 次）→ 读 manifest（1-2 次）→ `qa_compile_fanout(draft)`（1 次，一把梭全部 case）→ `qa_run_batch` 或逐条 run（按串行约束）→ `qa_compile_fanout(grade)`（1 次）→ 判定 → 重做 fanout（如需）→ `qa_emit_xlsx_merged`（1 次）。**探查手册/先例/设备的活全在 fanout 内部由 draft 子 agent 完成，你看不到也不该看。** 每个脑图主循环控制在个位数到十几次主 agent 调用，省下的步数留给重做循环。

## 流程

### 0. 校验版本（必须先做，缺版本立即 ask_user）
不同产品版本对应**不同 CLI 手册、不同命令语法**，draft 子 agent 必须 grep **对版本**的手册才能生成正确命令。所以编译前必须先确定**目标产品 + 版本**（如「APV 10.5」）。

- 从**用户请求原文**提取产品+版本（用户通常会写明，如"请基于 APV 10.5 版本编写自动化用例"）。
- **用户没写版本就立即 `qa_ask_user` 问**，不要从 config 猜默认值、不要臆测——版本是改变命令正确性的关键决策，猜错会让整批用例查错手册、生成错命令。拿不到版本不得往下走。
- 确定版本后，推出手册 glob：版本 `10.5` → 手册 `knowledge/data/markdown/product/10.5_cli__part*.md`。这个 glob 后面写进每条 brief 的"指路"，draft 据此 grep 对版本手册。

### 1. 备料：`qa_compile_prep(mindmap_path=..., out_name=<脑图名>)`
产出 `manifest.json`：该脑图全部 case（autoid 主键，标题重名不去重）的标题/分组/步骤需求/期望，以及 `groups`（分组链）。**manifest 里 case 的 init_commands/steps 都是 null**——这是对的，命令由 draft 回填。


读 manifest，注意 `groups`：若某分组下多个 case 共享一个"组外前置基线"（脑图把基线抽到组级、组内 case 不重述，如会话保持类脑图），要在派发 draft 时把该组的共享基线需求一并写进每个 case 的 brief（讲清"这个 case 属于 X 组，组级前置需求是 …，你要把它纳入本 case 的自包含 init"）——**只传需求描述，不传命令**。

### 2. 派发 draft（并发）
为 manifest 里每个 case 组一个 **brief**（五要素，见下），打包成 JSON 数组，一次性 fan-out：

```
qa_compile_fanout(
  skill="ist_compile_draft",
  briefs_json='[{"key":"<autoid>","brief":"<五要素brief>"}, ...]'
)
```

返回每个 key 的 draft 产物（xlsx 路径 + 测试思路）。某条失败（ok=false）记下，稍后重做。把每条产出的 xlsx 路径回填进 manifest 的 `compile_state.draft_xlsx`。

> 注意：本阶段每个 case 先各自出**单 case xlsx**（draft 子流程内部用 qa_emit_xlsx）。合并成脑图级 excel 在第 5 步做。

### 3. 上机 run（串行）
draft 出齐后，把这批 case 顺序上机。draft 产的是单 case xlsx，逐个上机用 `qa_run_batch` 不便（它读一个合并 xlsx）——本阶段对每个 draft xlsx 调 `qa_invoke_skill(skill="ist_compile_run", brief="xlsx_path=...; autoid=...")`，**一条接一条**（run 不可并发）。采集每个 case 的设备真实裁决（逐 check_point Success/Fail Num、命中计数、超时/弱覆盖迹象），回填 `compile_state.verdict` + `device_truth`。

### 4. 派发 grade（并发）
上机裁决出齐后，为每个 case 组 grade brief（xlsx 路径 + 原始需求 + 设备真实裁决），并发 fan-out：

```
qa_compile_fanout(
  skill="ist_compile_grade",
  briefs_json='[{"key":"<autoid>","brief":"xlsx_path=...; 原始需求=<脑图step+expected>; 设备真实裁决=<run返回>"}, ...]'
)
```

返回每个 case 的 PASS/CUT + 重做意见，回填 `compile_state.grade`。

### 5. 判定 + 重做循环（双绿才交付）
逐 case 按编排红线判定（与 ist_compile_orchestrate 同）：
- **上机真通过（无弱覆盖）且 grade PASS** → 该 case `status=done`。
- **任一不过**（fail/超时/弱覆盖，或 grade CUT）→ 携带反馈（上一版 + 设备裁决 + grade 重做意见）重新派发 draft（可把所有待重做 case 再次并发 fan-out），回第 3 步。
- 连续 N 轮（建议 3）仍不过的 case → `status=escalated`，**不拿弱产物充数**，记录卡点。

### 6. 合并打包：`qa_emit_xlsx_merged`
把该脑图所有 `status=done` 的 case 合并成**一个 excel**。每个 case 自带它自己的 init（从 draft 回填的自包含前置），传给 merged 工具：

```
qa_emit_xlsx_merged(
  cases_json='[{"autoid":"...","title":"...","init":"<该case自包含前置>","steps":[...]}, ...]',
  out_name="<脑图名>"
)
```

工具自动垫哨兵、round-trip 对账。最后可选 `qa_run_batch` 把合并 excel 整体顺序上机复验一遍。

### 7. 多脑图
用户给多个脑图（N 个 txt → N 个 excel）：对每个脑图跑 1-6。draft/grade 可跨脑图一起 fan-out 提速；**run 始终全局串行**（所有脑图的上机排一个队）。每个脑图产一个独立 excel。

## brief 五要素（派发 draft 时，逐项过滤"答案"）

每个 case 的 brief 只含这些**框架性信息**，绝不含具体命令/期望值：

1. **需求（objective）**：要编译的 case 是什么——autoid、标题、脑图原文步骤 + 期望（manifest 的 step_intents）。
2. **现状（state）**：目标模块（从 manifest 分组判断，如 sdns）、**目标产品+版本（从用户请求提取，如 APV 10.5——见第 0 步，缺则已 ask_user）**、这条属哪个分组、组级共享基线需求（若有）。
3. **规则（rules）**：断言期望值必须溯源先例/手册/作者意图，**不许 observe-then-assert**（看这次设备输出啥就抄成期望）；轮询/会话保持类按确定顺序逐次断言；每个 case 自包含（框架每 case 前清配置，基线必须在 case 内）。
4. **指路（tools/sources）**：CLI 语法去 grep **对版本**手册 `knowledge/data/markdown/product/{版本}_cli__part*.md`（如 10.5 → `10.5_cli__part*.md`，**不要用通配 `*cli__part*` 以免命中别的版本**）；先例用 qa_lookup_pattern 按配置结构相似度召回；拿不准命令用 qa_probe_show 探。
5. **边界（boundaries）**：你只生成 draft（不上机、不自评）；重做时基于上一版改、保留正确部分。

**自检三问**（每条 brief 过一遍）：① 这句是"需求/现状/规则/指路"还是"命令/期望值/映射"？后者删。② 删掉后子 agent 是"查不到"还是"想不到"？查不到补"去哪查"，不补答案。③ 这句换个 build/设备还成立吗？不成立=领域写死了。

## 约束（与 ist_compile_orchestrate 一致 + 批量特有）
- **总厨不亲自生成/上机/评分**：emit/run/grade 全派发子流程；你只做备料、调度、判定、重做、合并、上报。
- **交付需双绿**：设备裁决（行为已覆盖）+ grade（断言覆盖目标行为），缺一不可。verdict=pass 不足够。
- **run 绝不并发**：上机只走 qa_run_batch（串行）或逐条 ist_compile_run，绝不放进 qa_compile_fanout。
- **autoid 是主键，标题重名不去重**：合并按 autoid，同名 case 各自独立。
- **零命令进 brief/manifest**：命令全由 draft 现场查证产出。违反即滑回被推翻的硬编码老路。
- **失败如实上报**：N 轮不过标 escalated，不充数、不把弱断言写进记忆当"经验"。
