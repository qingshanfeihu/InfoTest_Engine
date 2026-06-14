---
name: test-list-review
description: 评审测试用例文件（xlsx / markdown / Test List），独立交叉验证给出评审结论。
when_to_use: |
  Use when the user wants to review test cases (评审 / Test List / 用例评审).
  Examples: "评审 BUG-121100 的测试用例", "review test cases for cookie encryption",
  "看一下 121100 用例怎么样", "按之前评审要求", "xlsx 评审".
  Trigger phrases: 评审, review, Test List, BUG-XXXXX, 测试用例评审.
  SKIP when: 用户只问 CLI 用法、产品规格说明、缺陷详情查询，或要求生成新用例。
allowed-tools: qa_deepagent_read_file, qa_deepagent_grep, qa_deepagent_ls, qa_exec, qa_bash, web_bug_search, qa_footprint_lookup, qa_invoke_skill
effort: high
---

# Test List Review

对测试用例做独立、有证据的评审。最终 VERDICT/LEVEL 由 review-verification fork skill 给出（你不能 self-assign 结论）。


## Inputs

- 测试用例文件路径（xlsx 或 markdown，位于 knowledge/data/markdown/qa/ 或 workspace/inputs/）
- 关联的 BUG / 需求 ID

## Goal

产出一份有证据支撑的评审报告（由交叉验证 task 结果块交付用户），含 VERDICT、LEVEL、改进建议。

## Principles

- 评审质量来自"读懂产品 + 读懂测试"，不是"套规则字典"
- 关注研发修改内容和具体产品实现——不要把修复细节当背景一扫而过，逐项理解改了什么参数、行为、选项
- 参考以往测试用例和测试策略——评审前了解历史覆盖维度，看类似功能历史上关注过什么，不要跑偏

## P 级别定义

- P0: 覆盖所有功能细节 + 非常丰富的兼容性/负面/压力/corner case 和极端场景
- P1: 覆盖所有功能细节 + 丰富的兼容性/负面/压力
- P2: 覆盖所有功能细节 + 比较丰富的兼容性/负面/压力
- P3: 覆盖所有功能细节 + 一定的兼容性/负面/压力
- P4: 覆盖所有功能细节 + 一定的负面/压力（兼容性不足）
- P5: 覆盖所有功能 + 一定的负面/压力（缺少功能细节深度）
- P6: 覆盖基本功能，包含负面和压力测试类型（功能细节覆盖不全）
- P7: 无法覆盖基本功能，不包含负面和压力测试类型

## Steps

### 0. 拆 todo（必做）

**Execution**: Direct（用 ``write_todos``）

接到评审任务后**第一件事**：调 ``write_todos``。文案必须是**用户友好的中文**（Plan 面板会直接展示）。

**禁止**在 todo 中出现：verifier、fork、subagent、gate、brief、review-verification、VERDICT 等内部词。

示例：

```text
- 读取需求文档
- 查询产品知识
- 分析产品设计
- 确认参数规格
- 参考测试方法
- 对标历史用例
- 逐行审阅用例
- 交叉验证
- 完成评审
```

**Rules**: 同时只能有一条 ``in_progress``。

### 1. 读缺陷 / 需求

调 ``web_bug_search(ticket_id)``。``ticket_id`` 可用 ``BUG-121100`` 或纯数字 ``121100``——工具在 **bugzilla / 禅道缺陷 / 禅道需求** 三端分别查询，不按前缀猜平台。重点理解研发修复了什么问题、改了哪些参数/枚举值/行为。

- 仅一端命中：用 ``title`` / ``description`` / ``metadata`` 写后续 ``bug_summary``
- ``hits_count`` > 1：对比 ``results`` 里各 ``probe_backend``，选定与评审相关的一条（其余勿丢）

**ONLY**: web_bug_search
**Success criteria**: 能回答"研发具体改了什么、影响哪些命令和版本"
**Artifacts**: bug_summary, fix_approach, affected_params, affected_versions, cli_command, severity

### 2. 读产品设计文档

**ONLY**: knowledge/data/markdown/product/
**Rules**: NEVER use qa/ paths for product semantics.
**Success criteria**: 能回答"该功能在系统中的位置、上下游耦合、设计边界（核心/边缘/兼容选项）"
**Artifacts**: feature_position, module_hierarchy, coupling_relations, design_boundaries

### 3. 读 CLI 手册

grep `knowledge/data/markdown/product/*cli__part*.md`，找到相关命令的完整参数表，确认参数间依赖关系（互斥/包含）、合法值范围和默认值。同时查找该命令在其他位置的引用，确认兼容关系。

**ONLY**: knowledge/data/markdown/product/*cli__part*.md
**Success criteria**: 能列出命令完整参数表 + 使用方法 + 配置示例 + 参数间依赖关系
**Artifacts**: param_table, legal_values, defaults, param_dependencies, usage_examples

### 4. 读测试方法论

grep `knowledge/data/markdown/qa/Test Strategy*.md` 找测试用例中包含的功能在历史上的测试策略，关注历史上类似功能的测试维度（HTTP版本/IPv6/性能/安全等）和方法论（边界值分析/等价类划分/错误推测法等）。

**ONLY**: knowledge/data/markdown/qa/Test Strategy*.md
**Success criteria**: 能回答"类似功能历史上关注哪些维度、用了什么测试方法"
**Artifacts**: test_dimensions, test_focus_areas, test_methods

### 5. 读同类历史用例

grep 测试用例中包含的相关功能历史的Test List，重点关注：覆盖维度（功能点/参数组合/网络环境）、设计思路（正向/负向/边界）、质量水平（描述清晰度/预期结果明确度）、模块划分。

**ONLY**: knowledge/data/markdown/qa/Test List*.md（禁止读当前正在评审的用例文件）
**Success criteria**: 能对标"同类功能历史上覆盖了什么、怎么分模块、质量如何"
**Artifacts**: historical_coverage_pattern, test_design_approach, module_partition

### 6. 读当前用例全文 + 产品知识补充

**MUST** read entire test case file. If > 500 lines, paginated reads until full coverage.

在 Step 7 之前，对 ``cli_command`` 调 ``qa_footprint_lookup``，把测试用例中已确认的产品测试事实写入后续 brief 的 ``evidence_collected``（禁止留到交叉验证之后再补查）。

**ONLY**: 用例文件 + qa_footprint_lookup
**Success criteria**: 全文覆盖 + footprint 要点已记录 + 用例中所有命令/模块均已确认语义
**Artifacts**: footprint_facts, test_coverage_dimensions, test_design_approach, module_partition
**Rules**: 用例中出现未知命令/模块时，必须 grep product/ 确认语义后再评审；禁止凭名字推断功能行为

### 7. 草稿 + 交叉验证 (when applicable: 多 sheet)

**多 sheet xlsx（when applicable）**：若 xlsx 有 N 个独立 sheet/section（各 >500 行），先 peek 结构，再**同一条消息**并发 N 个 ``qa_invoke_skill(skill="review-verification", brief=...)``，每块一份 brief；全部返回后按 worst-case 聚合（任一 FAIL → FAIL；否则任一 PARTIAL → PARTIAL）。

**Execution**: Fork skill — 必须调 ``qa_invoke_skill(skill="review-verification", brief=<完整草稿>)``

⚠️ **关键约束**：
- skill 名必须是 ``review-verification``（fork skill），**不是** ``test-list-review``（你已加载的 inline skill）
- 再调 ``test-list-review`` 只会重新返回这份 SKILL.md（inline skill 行为），**不会触发独立验证**
- ``review-verification`` 是 fork skill，会在独立 subagent (review-verifier) 中执行验证，返回结构化研究报告

先在对话里写完整草稿（证据列表 + draft_findings + draft_level），再调 ``qa_invoke_skill(skill="review-verification", ...)``。Brief 必须完整——fork skill 从零上下文开始，看不到你之前的对话。

``brief`` 建议结构：

```text
test_case_file: <路径>
bug_id: <BUG-XXXXX>
bug_summary: <一句话>
cli_command: <CLI>
evidence_collected:
  - Phase 1: <研发修改方案 + 影响参数>
  - Phase 2: <功能位置 + 设计边界>
  - Phase 3: <参数表 + 依赖关系>
  - Phase 4: <历史测试维度 + 方法论>
  - Phase 5: <同类覆盖模式>
  - Phase 6 footprint: <qa_footprint_lookup 要点>
  - Phase 6 用例结构: <覆盖维度 + 模块划分>
evidence_gaps:
  - <知识库中未找到但可能影响判断的信息>
draft_findings:
  critical (P6-P7 级):
    - <行号> <描述>
  major (P3-P5 级):
    - <行号> <描述>
  minor (P0-P2 级):
    - <行号> <描述>
draft_level: P0-P7

Independently verify each finding (you will grep/read internally).
Try to break my draft. User-facing report: 中文「发现项」+ 证据摘录（勿写 qa_deepagent_* 工具行）+ VERDICT + LEVEL.
```

**Success criteria**: task 返回含 ``VERDICT:`` + ``LEVEL:`` 的报告

**Rules**:

- 不得修改交叉验证给出的 VERDICT/LEVEL（Faithful Reporting）
- 交叉验证返回后**禁止**再调任何工具或写补充 finding

### 8. 撰写最终报告（对齐 Anthropic 官方做法）

fork verifier 已返回**结构化研究报告**作为 ToolResult（含 Summary / Verified Findings / New Findings / Level Challenge / Verdict）。这是研究材料，**不是直接给用户的成品**。

你的任务：基于 verifier 的研究材料 + Phase 1-6 的证据，**用你自己的话**写最终用户可见的评审报告。

**必须遵守**：
- VERDICT 和 LEVEL 直接采用 verifier 的判定，**不得修改**（Faithful Reporting）
- 所有 verifier 列出的 findings（Verified + New）都要在最终报告中体现
- 改进建议来自 verifier 的 Improvement Suggestions
- 用中文 markdown，结构清晰

**禁止**：
- 直接 copy-paste verifier 的输出（重复显示、用户看到两遍）
- 篡改 verifier 的 VERDICT/LEVEL
- 加 verifier 没列的发现（verifier 已是最终评审者）
- 输出后再调任何工具

**Success criteria**: 最终 AIMessage 包含完整中文评审报告（findings + 改进建议 + VERDICT + LEVEL），用主 agent 自己的语言组织，不是 verifier 输出的逐字复制
