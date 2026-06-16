---
name: ist_compile_batch
description: "把人工测试用例（脑图 / txt / 单条用例 / 需求描述）编译或改编成断言真覆盖目标行为的自动化 excel——单条用例或整脑图批量统一走本 skill。通读用例→解析 manifest→draft 并发生成→grade 并发审批断言质量→合并打包出 excel。上机验证是独立环节（走 ist_verify），不阻塞产出。单条是 N=1 特例，同一流程无需区分。"
context: inline
user-invocable: true
source: hand
version: "2"
effort: high
when_to_use: |
  Use when 用户要把人工测试用例（脑图 / txt / 单条用例 / 需求描述）编译或改编成框架能上机执行、断言真覆盖作者目标行为的自动化 excel / case.xlsx——无论单条还是整脑图 / 多个 txt 批量。
  Examples: "把这条脑图用例编译成 excel", "把这个用例改编成自动化 case", "生成 case.xlsx 并上机跑通", "把 automatic_case 下 3 个 txt 的脑图用例转成 3 个 excel", "把 dongkl.txt 整个编译成 excel", "把这几个脑图批量转自动化", "一次把整张脑图的用例都编译了"。
  Trigger keywords: 用例编译, 编译, 改编, 脑图转excel, txt转excel, case.xlsx, 自动化用例, 断言覆盖, 单条用例, 批量编译, 多个脑图, 3个txt, 整个脑图, 一个脑图一个excel, 批量转excel, 全部用例, 并行编译。
  SKIP when: 只查 CLI 回显（用 qa_probe_show）；评审已有用例文件（用 test-list-review）。
---

# 编译编排：通读用例→解析 manifest→分阶段调度→合并打包

把人工测试用例编译成自动化 **excel**（每条断言真覆盖目标行为）——**单条用例或整脑图批量都走本流程**。你是编排器，不亲自生成命令：通读用例→解析出 case 清单（manifest）→draft 并发生成→grade 并发审批断言质量→把审批通过的 case 合并打包出 excel。上机验证是产出之后的独立环节（ist_verify），不在本流程内。

**单条用例是 N=1 特例，同一流程无需区分**：prep 产出含 1 个 case 的 manifest，draft fanout 并发度=1，run for 循环 1 次，grade fanout 1 条，merged 退化成「单 case + 哨兵」的 excel——所有阶段天然兼容，不走特殊分支。

## 为什么分阶段（不逐条从头编译）

逐条从头编译 = 每个 case 都从头解析、查证、生成，慢且重复。正确做法：先一次性解析整批用例（prep），能并行的并行（draft 各 case 同时生成、grade 同时判分）。编译产出本身不上机（上机是产出后的独立验证环节）。

## 第一原则（不可违反，高于一切）

**零硬编码、纯引导**：你和所有子流程的代码/brief 里**绝不出现任何具体设备命令**（如 sdns/slb CLI）、不按关键字分支、不逐 autoid 特殊处理。命令/参数/断言全部由 draft 子 agent **现场查手册（`*cli__part*.md`）/查先例（qa_lookup_pattern）**得出。你给子流程的 brief 只含**需求+现状+规则+指路+边界**（见下"brief 五要素"），绝不喂答案。

## 物理边界（硬约束，落在工具里，不靠自律）

| 阶段 | 工具 | 并行性 | 为什么 |
|---|---|---|---|
| 解析 | `qa_compile_prep` | 一次 | 解析脑图→manifest（只含需求，零命令） |
| 生成 draft | `qa_compile_fanout(skill="ist_compile_draft")` | **并发** | 查手册+本地 emit，不碰设备态 |
| 审批 grade | `qa_compile_fanout(skill="ist_compile_grade")` | **并发** | 纯本地判分（基于先例/手册），零设备交互 |
| 打包 | `qa_emit_xlsx_merged` | 一次 | 同脑图 grade-PASS 的 case 合并成一个 excel + 哨兵垫底 |

**编译产出与上机验证解耦**（2026-06-16）：本 skill 只负责**产出 excel**（draft 生成 → grade 审批断言质量 → 合并打包），**不上机**。上机验证是独立环节，由 `ist_verify` skill 单独对成品 excel 做（`qa_run_batch` 串行上机、采集真实裁决、回报）。原因：上机大面积失败常是**设备环境瞬态**（SSH 会话中断、dig 超时、DNS 解析失败），不该阻塞编译产出；把"上机通过"当成"进 excel"的硬前置，会让环境一坏就出不了任何 excel。grade 是断言质量门槛（弱断言/未覆盖仍 CUT），上机是产出之后的独立验证 + 回流依据。

## 编排器步数纪律（必须遵守，否则跑不完整批）

你的工具调用步数有硬上限（recursion_limit）。批量编译有几十上百个 case，**你绝不能自己逐 case grep 手册 / qa_probe_show 探设备 / qa_lookup_pattern 查先例**——那是 draft 子 agent 的活，你这么做会在解析阶段就把步数耗光，整批编译半途而废（已有前车之鉴）。

你（编排器）每个脑图**只允许这几类调用**：`qa_compile_prep`（1 次）→ 读 manifest（1-2 次）→ `qa_compile_fanout(draft)`（1 次，一把梭全部 case）→ `qa_compile_fanout(grade)`（1 次）→ 判定 → 重做 fanout（如需）→ `qa_emit_xlsx_merged`（1 次）。**探查手册/先例的活全在 fanout 内部由 draft 子 agent 完成，你看不到也不该看。上机不在本 skill 流程内——产出 excel 后由 ist_verify 单独验证。** 每个脑图主循环控制在个位数到十几次主 agent 调用，省下的步数留给重做循环。

## 流程

### 0. 校验版本（必须先做，缺版本立即 ask_user）
不同产品版本对应**不同 CLI 手册、不同命令语法**，draft 子 agent 必须 grep **对版本**的手册才能生成正确命令。所以编译前必须先确定**目标产品 + 版本**（如「APV 10.5」）。

- 从**用户请求原文**提取产品+版本（用户通常会写明，如"请基于 APV 10.5 版本编写自动化用例"）。
- **用户没写版本就立即 `qa_ask_user` 问**，不要从 config 猜默认值、不要臆测——版本是改变命令正确性的关键决策，猜错会让整批用例查错手册、生成错命令。拿不到版本不得往下走。
- 确定版本后，推出手册 glob：版本 `10.5` → 手册 `knowledge/data/markdown/product/10.5_cli__part*.md`。这个 glob 后面写进每条 brief 的"指路"，draft 据此 grep 对版本手册。

### 1. 解析：`qa_compile_prep(mindmap_path=..., out_name=<脑图名>)`
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
### 3. 派发 grade 审批（并发）
draft 出齐后，为每个 case 组 grade brief，并发 fan-out。grade 是**断言质量审批**（基于需求 + draft + 先例/手册，判断言是否真覆盖目标行为）——**不依赖上机裁决**（上机是后续 ist_verify 的独立环节）：

```
qa_compile_fanout(
  skill="ist_compile_grade",
  briefs_json='[{"key":"<autoid>","brief":"xlsx_path=...; 原始需求=<脑图step+expected>"}, ...]'
)
```

返回每个 case 的 PASS/CUT + 重做意见，回填 `compile_state.grade`。

### 4. 判定 + 重做循环（grade-PASS 即可交付）
逐 case 按编排红线判定（**这是你自主决策,绝不 qa_ask_user 问用户「合并哪些/要不要重做」——判定规则已定死,直接执行**）：
- **grade PASS（断言真覆盖目标行为）** → 该 case `status=done`，进第 5 步合并。
- **grade CUT（弱断言/未覆盖）** → 携带反馈（上一版 + grade 重做意见）重新派发 draft（把所有待重做 case 再次并发 fan-out），回第 3 步。
- 连续 N 轮（建议 3）仍 CUT 的 case → `status=escalated`，**不拿弱产物充数**，记录卡点。
- **门槛是 grade 断言质量，不是上机 pass**：grade 严格判弱断言/未覆盖（不救场），但上机通过与否不在此判定——环境瞬态失败不该挡产出。

**部分 PASS 部分 CUT 是常态,不是要问用户的决策点**：grade 后通常有些 PASS 有些 CUT（如 10 PASS / 16 CUT）。**默认动作固定**：① 先把 PASS 的合并出 excel（第 5 步,先交付能交付的）；② CUT 的按上面规则重做/escalate。**绝不因为「有 CUT」就停下 qa_ask_user 问「合并 PASS 还是重做 CUT」——两件都做：PASS 先合并,CUT 另行重做。** 非交互模式下尤其不能卡在这里空转（已有前车之鉴：撞 ask_user error 后反复 ls/ask 转圈被 loop guard 拦截）。

### 5. 合并打包：`qa_emit_xlsx_merged`
把该脑图所有 `status=done`（grade PASS）的 case 合并成**一个 excel**。每个 case 自带它自己的 init（从 draft 回填的自包含前置），传给 merged 工具：

```
qa_emit_xlsx_merged(
  cases_json='[{"autoid":"...","title":"...","init":"<该case自包含前置>","steps":[...]}, ...]',
  out_name="<脑图名>"
)
```

工具自动垫哨兵、round-trip 对账。**到此编译产出完成**——脑图级 excel 已落 `workspace/outputs/<脑图名>/case.xlsx`。

### 6. 收尾：报告产出 + 询问是否上机验证（闭环）
编译产出 excel 后，**上机验证是独立环节，不在本 skill 内做**（不要在本 skill 里 qa_run_batch / qa_invoke_skill(ist_compile_run)——上机已从编译链解耦）。按以下方式收尾,把编译与验证在交互层串成闭环：

1. **报告编译产出**：列出每个脑图产出的 excel 路径（`workspace/outputs/<脑图名>/case.xlsx`）、各含多少 case（grade PASS 数 / escalated 数）。
2. **询问是否上机验证**：`qa_ask_user`「excel 已生成。是否现在上机验证（到跳转机框架跑一遍、采集设备真实裁决）？」
   - 用户选**是** → `qa_invoke_skill(skill="ist_verify", brief="验证 workspace/outputs/<脑图名>/case.xlsx,build=<版本>")`,把上机验证交给 ist_verify。
   - 用户选**否** → 到此结束,excel 已交付。
3. ist_verify 跑完会输出验证 summary + 具体报错,并自行询问是否修复——若用户选修复,ist_verify 会把真实断言失败的 case 回流调本 skill 重编译。**回流闭环由 ask_user 在交互层驱动,不在编译链里强耦合上机。**

> 非交互模式（`infotest -p`,无人应答 ask_user）：编译产出 excel 后直接报告完成,不阻塞等待——验证作为独立步骤由调用方另行发起。

### 7. 多脑图
用户给多个脑图（N 个 txt → N 个 excel）：对每个脑图跑 1-5。draft/grade 可跨脑图一起 fan-out 提速。每个脑图产一个独立 excel。上机验证（ist_verify）也对每个成品 excel 独立做。

## brief 五要素（派发 draft 时，逐项过滤"答案"）

每个 case 的 brief 只含这些**框架性信息**，绝不含具体命令/期望值：

1. **需求（objective）**：要编译的 case 是什么——autoid、标题、脑图原文步骤 + 期望（manifest 的 step_intents）。
2. **现状（state）**：目标模块（从 manifest 分组判断，如 sdns）、**目标产品+版本（从用户请求提取，如 APV 10.5——见第 0 步，缺则已 ask_user）**、这条属哪个分组、组级共享基线需求（若有）。
3. **规则（rules）**：断言期望值必须溯源先例/手册/作者意图，**不许 observe-then-assert**（看这次设备输出啥就抄成期望）；轮询/会话保持类按确定顺序逐次断言；每个 case 自包含（框架每 case 前清配置，基线必须在 case 内）。
4. **指路（tools/sources）**：CLI 语法去 grep **对版本**手册 `knowledge/data/markdown/product/{版本}_cli__part*.md`（如 10.5 → `10.5_cli__part*.md`，**不要用通配 `*cli__part*` 以免命中别的版本**）；先例用 qa_lookup_pattern 按配置结构相似度召回；拿不准命令用 qa_probe_show 探。
5. **边界（boundaries）**：你只生成 draft（不上机、不自评）；重做时基于上一版改、保留正确部分。

**自检三问**（每条 brief 过一遍）：① 这句是"需求/现状/规则/指路"还是"命令/期望值/映射"？后者删。② 删掉后子 agent 是"查不到"还是"想不到"？查不到补"去哪查"，不补答案。③ 这句换个 build/设备还成立吗？不成立=领域写死了。

## 约束（编排红线）
- **编排器不亲自生成/审批**：emit/grade 全派发子流程；你只做解析、调度、判定、重做、合并、上报。
- **交付门槛是 grade 断言质量**：grade 判断言是否真覆盖目标行为（弱断言/未覆盖 CUT，不救场）。**上机不是交付门槛**——上机验证由 ist_verify 在产出后独立做，环境瞬态失败不挡 excel 产出。
- **上机已从编译链解耦**：本 skill 流程内**不调** qa_run_batch / ist_compile_run。上机走独立的 ist_verify skill。
- **autoid 是主键，标题重名不去重**：合并按 autoid，同名 case 各自独立。
- **零命令进 brief/manifest**：命令全由 draft 现场查证产出。违反即滑回被推翻的硬编码老路。
- **失败如实上报**：N 轮 CUT 标 escalated，不充数、不把弱断言写进记忆当"经验"。
