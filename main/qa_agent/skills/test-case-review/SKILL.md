---
name: test-case-review
description: 评审测试用例文件（xlsx / markdown / Test List），独立交叉验证给出评审结论。
user-invocable: true
effort: high
allowed-tools:
  - qa_deepagent_read_file
  - qa_deepagent_grep(knowledge/data/markdown/product/*)
  - qa_deepagent_grep(knowledge/data/markdown/qa/*)
  - qa_deepagent_ls
  - qa_exec
  - qa_bash
  - web_bug_search
  - qa_footprint_lookup
  - task(review-verification)
when_to_use: |
  Use when the user wants to review test cases (评审 / Test List / 用例评审).
  Examples: "评审 BUG-121100 的测试用例", "review test cases for cookie encryption",
  "看一下 121100 用例怎么样", "按之前评审要求", "xlsx 评审".
  Trigger phrases: 评审, review, Test List, BUG-XXXXX, 测试用例评审.
  SKIP when: 用户只问 CLI 用法、产品规格说明、缺陷详情查询，或要求生成新用例。
context: inline
---

# Test Case Review

对测试用例做独立、有证据的评审。最终结论由交叉验证子任务给出；遵守 system prompt 的 Verification Contract（你不能 self-assign VERDICT/LEVEL）。

## Inputs

- 测试用例文件路径（xlsx 或 markdown，位于 knowledge/data/markdown/qa/ 或 workspace/inputs/）
- 关联的 BUG / 需求 ID

## Goal

产出一份有证据支撑的评审报告（由交叉验证 task 结果块交付用户），含 VERDICT、LEVEL、改进建议。

## P 级别定义

- P0: 覆盖所有功能细节 + 非常丰富的兼容性/负面/压力/corner case
- P1: 覆盖所有功能细节 + 丰富的兼容性/负面/压力
- P2: 覆盖所有功能细节 + 比较丰富的兼容性/负面/压力
- P3: 覆盖所有功能细节 + 一定的兼容性/负面/压力
- P4: 覆盖所有功能细节 + 一定的负面/压力
- P5: 覆盖所有功能细节但缺少负面/压力
- P6: 覆盖大部分功能细节
- P7: 覆盖少部分功能细节或存在重大缺口

## Steps

### 0. 拆 todo（必做）

**Execution**: Direct（用 ``write_todos``）

接到评审任务后**第一件事**：调 ``write_todos``。文案必须是**用户友好的中文**（Plan 面板会直接展示）。

**禁止**在 todo 中出现：verifier、fork、subagent、gate、brief、review-verification、VERDICT 等内部词。

示例：
```
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

调 web_bug_search(ticket_id)。

**ONLY**: web_bug_search
**Success criteria**: bug_summary + cli_command + severity
**Artifacts**: bug_summary, cli_command, severity

### 2. 读产品设计文档

**ONLY**: knowledge/data/markdown/product/
**Rules**: NEVER use qa/ paths for product semantics.
**Success criteria**: 功能位置 + 设计边界

### 3. 读 CLI 手册

**ONLY**: knowledge/data/markdown/product/cli__part*.md
**Success criteria**: 参数表 + 默认值 + 互斥关系

### 4. 读测试方法论

**ONLY**: knowledge/data/markdown/qa/Test Strategy*.md
**Success criteria**: 测试维度 / 重点 / 方法

### 5. 读同类历史用例

**ONLY**: knowledge/data/markdown/qa/Test List*.md（禁止读当前正在评审的用例文件）
**Success criteria**: 同类覆盖模式对标

### 6. 读当前用例全文 + 产品知识补充

**MUST** read entire test case file. If > 500 lines, paginated reads until full coverage.

在 Step 7 之前，对 ``cli_command`` 调 ``qa_footprint_lookup``，把 smode/sdata 等产品事实写入后续 brief 的 ``evidence_collected``（禁止留到交叉验证之后再补查）。

**ONLY**: 用例文件 + qa_footprint_lookup
**Success criteria**: 全文覆盖 + footprint 要点已记录
**Artifacts**: footprint_facts

### 7. 草稿 + 交叉验证 (when applicable: 多 sheet)

**多 sheet xlsx（when applicable）**：若 xlsx 有 N 个独立 sheet/section（各 >500 行），先 peek 结构，再**同一条消息**并发 N 个 ``task(subagent_type='review-verification')``，每块一份 brief；全部返回后按 worst-case 聚合（任一 FAIL → FAIL；否则任一 PARTIAL → PARTIAL）。

**Execution**: Task agent（review-verification）

先在对话里写完整草稿（证据列表 + draft_findings + draft_level），再调 ``task``。遵守 system prompt **Writing the prompt for task calls**——完整 brief，禁止 ``description="评审 121100"`` 这种短命令。

``description`` 建议结构：

```
test_case_file: <路径>
bug_id: <BUG-XXXXX>
bug_summary: <一句话>
cli_command: <CLI>
evidence_collected:
  - Phase 1: ...
  - Phase 2-5: ...
  - Phase 6 footprint: <qa_footprint_lookup 要点>
  - Phase 6 用例结构: ...
draft_findings:
  - <行号> <描述> (P?)
draft_level: P0-P7

Independently verify each finding (you will grep/read internally).
Try to break my draft. User-facing report: 中文「发现项」+ 证据摘录（勿写 qa_deepagent_* 工具行）+ VERDICT + LEVEL.
```

**Success criteria**: task 返回含 ``VERDICT:`` + ``LEVEL:`` 的报告
**Rules**:
- 不得修改交叉验证给出的 VERDICT/LEVEL（Faithful Reporting）
- 交叉验证返回后**禁止**再调任何工具或写补充 finding

### 8. 收尾

交叉验证报告已作为 ``task`` 的 tool_result 展示给用户。**你只输出一句**：「评审完成。」

**禁止**：复述报告、补充建议、再调工具、超过一句话。

**Success criteria**: 最终 AIMessage 仅「评审完成。」且无后续 tool_call
