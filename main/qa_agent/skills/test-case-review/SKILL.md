---
name: test-case-review
description: 评审测试用例文件（xlsx / markdown / Test List），独立 verifier 给最终 verdict。
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

对测试用例文件做独立、有证据的评审；最终 verdict 由 verifier subagent 给出。
主 agent 不能 self-assign verdict（仿 cc-haha constants/prompts.ts:390-395）。

## Inputs

- 测试用例文件路径（xlsx 或 markdown，位于 knowledge/data/markdown/qa/ 或 workspace/inputs/）
- 关联的 BUG / 需求 ID

## Goal

产出一份有证据支撑的评审报告，包含：
- VERDICT: PASS | PARTIAL | FAIL (by verifier)
- LEVEL: P0-P7 (by verifier)
- 每条 finding 带文件路径 + 行号 + grep 证据

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

### 1. 读缺陷 / 需求

调 web_bug_search(ticket_id) 拿完整缺陷描述。

**ONLY**: web_bug_search
**Success criteria**: 拿到 bug summary + CLI 命令变更 + severity + 影响版本。
**Artifacts**: bug_summary, cli_command, severity

### 2. 读产品设计文档

grep 产品语义。

**ONLY**: knowledge/data/markdown/product/
**Rules**: NEVER use qa/ paths for product semantics. 禁止从 qa/Test List_*.md 推导产品定义。
**Success criteria**: 找到功能在系统里的位置 + 上下游耦合 + 设计边界。

### 3. 读 CLI 手册

确认参数语义、合法值范围、依赖关系。

**ONLY**: knowledge/data/markdown/product/cli__part*.md
**Success criteria**: 完整参数表 + 默认值 + 互斥关系。

### 4. 读测试方法论

**ONLY**: knowledge/data/markdown/qa/Test Strategy*.md
**Success criteria**: 同类功能的测试维度 / 重点 / 方法。

### 5. 读同类历史用例

**ONLY**: knowledge/data/markdown/qa/Test List*.md（禁止读自己——当前评审的用例文件）
**Success criteria**: 同类测试覆盖模式作为对标参考。

### 6. 读当前用例全文

**MUST** read entire file. If > 500 lines, do paginated reads with explicit offset until full coverage. 不许跳读。

**Success criteria**: 完整覆盖功能点 / 参数组合 / 测试设计。

### 7. 草稿 + 提交 verifier

**Execution**: Task agent（review-verification）

写初步草稿（检索证据列表 + 初步 finding + 初步 P 级别建议），然后立即提交给 verifier。

**BLOCKING REQUIREMENT**: 草稿写完立即调：

```
task(subagent_type="review-verification", description="""
  test_case_file: <path>
  bug_id: <id>
  bug_summary: <oneliner>
  cli_command: <command>
  evidence_collected: [<Phase 1-6 检索到的证据列表>]
  draft_findings: [<你的初步问题列表>]
  draft_level: P0-P7

  Independently verify each finding. Try to break my draft.
  Output per-Check format with VERDICT + LEVEL.
""")
```

**Success criteria**: verifier 返回 VERDICT + LEVEL + Check 列表。
**Artifacts**: verdict, level, checks
**Rules**: 不能修改 verifier 的 VERDICT / LEVEL；只能透传。你不能 self-assign verdict。

### 8. 输出最终报告

基于 verifier verdict 综述给用户。报告头部显示：

```
VERDICT: ... (by verifier)
LEVEL: ... (by verifier)
```

**Success criteria**: 用户看到 verdict + level + check 详情 + 主 agent 草稿与 verifier 反驳的 diff（如有）。

### 9. 多 sheet xlsx 并发评审 (when applicable)

If input is .xlsx with N independent sheets/sections (>500 rows each):
1. First call qa_deepagent_read_file to peek the markdown form
2. Identify N independent chunks
3. Launch N task(subagent_type='review-verification') agents concurrently in a single message, each handling one chunk
4. Wait for all to complete; aggregate VERDICTs (worst-case: any FAIL → final FAIL; any PARTIAL → final PARTIAL)
5. Render single final report

**Execution**: Task agent (multiple concurrent)
**Success criteria**: 每个 sheet/chunk 都有独立 VERDICT；最终报告聚合。
