---
name: test-list-review
description: "Reviews APV load-balancer (SLB / SDNS / HTTP / IPv6) test cases / test strategy and delivers an independently cross-verified conclusion (VERDICT / P level / improvement suggestions). Use when the user wants to review (评审) a Test List, a test-case or test-strategy file (xlsx / markdown / case list), asks for a case review against a defect ticket (e.g. BUG-121100), wants case coverage assessed, or asks to re-check against previous review requirements. Trigger keywords: 评审, review, 测试用例评审, Test List, 用例审查, 用例覆盖评审, 缺陷用例评审. Any request to review / assess / re-check the quality of existing test cases or test strategy enters here."
context: inline
user-invocable: true
when_to_use: |
  Use when the user wants to review test cases (评审 / Test List / 用例评审).
  Examples: "评审 BUG-121100 的测试用例", "review test cases for cookie encryption",
  "看一下 121100 用例怎么样", "按之前评审要求", "xlsx 评审".
  Trigger keywords: 评审, review, Test List, BUG-XXXXX, 测试用例评审.
  SKIP when: the user only asks about CLI usage, product specifications, or defect details, or asks to generate new test cases.
allowed-tools: [fs_read, fs_grep, fs_ls, run_python, run_shell, kb_bug_search, kb_footprint, invoke_skill]
effort: high
---

# Test List Review

Independent, evidence-backed review of test cases. The final VERDICT/LEVEL is issued by the review-verifier fork skill (you cannot self-assign the conclusion).


## Inputs

- Test case file path (xlsx or markdown, under knowledge/data/markdown/qa/ or workspace/inputs/)
- Associated BUG / requirement ID

## Goal

Produce an evidence-backed review report (delivered to the user from the cross-verification task result block), containing VERDICT, LEVEL, and improvement suggestions.

## Principles

- Review quality comes from "understanding the product + understanding the tests", not from applying a rule dictionary
- Focus on what development changed and on the concrete product implementation — do not skim the fix details as mere background; understand item by item which parameters, behaviors, options changed
- Consult past test cases and test strategies — before reviewing, learn the historical coverage dimensions and what similar features focused on historically, so the review does not drift

## P level definitions

- P0: covers all functional details + very rich compatibility/negative/stress/corner cases and extreme scenarios
- P1: covers all functional details + rich compatibility/negative/stress
- P2: covers all functional details + fairly rich compatibility/negative/stress
- P3: covers all functional details + some compatibility/negative/stress
- P4: covers all functional details + some negative/stress (insufficient compatibility)
- P5: covers all functions + some negative/stress (lacking functional-detail depth)
- P6: covers basic functions, includes negative and stress test types (functional-detail coverage incomplete)
- P7: fails to cover basic functions, contains no negative or stress test types

## Steps

### 0. Break the task into todos (mandatory)

**Execution**: Direct (via ``write_todos``)

The **first thing** after receiving a review task: call ``write_todos``. The wording must be **user-friendly Chinese** (the Plan panel displays it verbatim).

**Forbidden** in todos: internal words such as verifier, fork, subagent, gate, brief, review-verifier, VERDICT.

Example:

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

**Rules**: only one todo may be ``in_progress`` at a time.

### 1. Read the defect / requirement

Call ``kb_bug_search(ticket_id)``. ``ticket_id`` accepts ``BUG-121100`` or the bare number ``121100`` — the tool queries **bugzilla / ZenTao defects / ZenTao requirements** separately; it does not guess the platform from the prefix. Focus on understanding what problem development fixed and which parameters / enum values / behaviors changed.

- Exactly one backend hits: use its ``title`` / ``description`` / ``metadata`` to write the ``bug_summary`` used later
- ``hits_count`` > 1: compare each ``probe_backend`` in ``results`` and select the one relevant to this review (do not discard the others)

**ONLY**: kb_bug_search
**Success criteria**: can answer "what exactly did development change, and which commands and versions are affected"
**Artifacts**: bug_summary, fix_approach, affected_params, affected_versions, cli_command, severity

### 2. Read the product design docs

**ONLY**: knowledge/data/markdown/product/
**Rules**: NEVER use qa/ paths for product semantics.
**Success criteria**: can answer "where the feature sits in the system, its upstream/downstream coupling, and its design boundaries (core / edge / compatibility options)"
**Artifacts**: feature_position, module_hierarchy, coupling_relations, design_boundaries

### 3. Read the CLI manual

Grep `knowledge/data/markdown/product/cli_*_Chapter*.md` + `cli_*_Appendix*.md` to find the complete parameter table of the relevant commands, and confirm inter-parameter dependencies (mutual exclusion / inclusion), legal value ranges, and defaults. Also search for other references to the command elsewhere to confirm compatibility relations.

**ONLY**: knowledge/data/markdown/product/cli_*_Chapter*.md + cli_*_Appendix*.md
**Success criteria**: can list the command's complete parameter table + usage + configuration examples + inter-parameter dependencies
**Artifacts**: param_table, legal_values, defaults, param_dependencies, usage_examples

### 4. Read the test methodology

Grep `knowledge/data/markdown/qa/Test Strategy*.md` for the historical test strategy of the features covered by the test cases, focusing on the dimensions historically applied to similar features (HTTP version / IPv6 / performance / security etc.) and the methodology (boundary value analysis / equivalence partitioning / error guessing etc.).

**ONLY**: knowledge/data/markdown/qa/Test Strategy*.md
**Success criteria**: can answer "which dimensions similar features focused on historically, and which test methods were used"
**Artifacts**: test_dimensions, test_focus_areas, test_methods

### 5. Read historical cases of the same kind

Grep the historical Test Lists for the features covered by the test cases, focusing on: coverage dimensions (feature points / parameter combinations / network environments), design approach (positive / negative / boundary), quality level (description clarity / expected-result explicitness), and module partitioning.

**ONLY**: knowledge/data/markdown/qa/Test List*.md (never read the case file currently under review)
**Success criteria**: can benchmark "what similar features covered historically, how modules were partitioned, and at what quality"
**Artifacts**: historical_coverage_pattern, test_design_approach, module_partition

### 6. Read the current case file in full + supplementary product knowledge

**MUST** read entire test case file. If > 500 lines, paginated reads until full coverage.

Before Step 7, call ``kb_footprint`` on ``cli_command`` and write the already-verified product test facts into the ``evidence_collected`` of the later brief (never defer this lookup until after cross-verification).

**ONLY**: the case file + kb_footprint
**Success criteria**: full-text coverage + footprint highlights recorded + semantics of every command/module in the cases confirmed
**Artifacts**: footprint_facts, test_coverage_dimensions, test_design_approach, module_partition
**Rules**: when an unknown command/module appears in the cases, grep product/ to confirm its semantics before reviewing; never infer feature behavior from a name

### 7. Draft + cross-verification

**Multi-sheet xlsx (when applicable)**: if the xlsx has N independent sheets/sections (each > 500 lines), peek the structure first, then issue N concurrent ``invoke_skill(skill="review-verifier", brief=...)`` calls **in the same message**, one brief per block; after all return, aggregate worst-case (any FAIL → FAIL; otherwise any PARTIAL → PARTIAL).

**Execution**: Fork skill — must call ``invoke_skill(skill="review-verifier", brief=<complete draft>)``

⚠️ **Key constraints**:
- The skill name must be ``review-verifier`` (the fork skill), **not** ``test-list-review`` (the inline skill you already loaded)
- Calling ``test-list-review`` again only returns this SKILL.md once more (inline skill behavior) and **does not trigger independent verification**
- ``review-verifier`` is a fork skill: it runs verification in an independent subagent (review-verifier) and returns a structured research report

First write the complete draft in the conversation (evidence list + draft_findings + draft_level), then call ``invoke_skill(skill="review-verifier", ...)``. The brief must be self-contained — the fork skill starts from zero context and cannot see your earlier conversation.

Suggested ``brief`` structure:

```text
test_case_file: <path>
bug_id: <BUG-XXXXX>
bug_summary: <one sentence>
cli_command: <CLI>
evidence_collected:
  - Step 1: <dev fix approach + affected parameters>
  - Step 2: <feature position + design boundaries>
  - Step 3: <parameter table + dependencies>
  - Step 4: <historical test dimensions + methodology>
  - Step 5: <coverage patterns of similar features>
  - Step 6 footprint: <kb_footprint highlights>
  - Step 6 case structure: <coverage dimensions + module partition>
evidence_gaps:
  - <information not found in the knowledge base that may affect judgment>
draft_findings:
  critical (P6-P7 severity):
    - <line number> <description>
  major (P3-P5 severity):
    - <line number> <description>
  minor (P0-P2 severity):
    - <line number> <description>
draft_level: P0-P7

Independently verify each finding (you will grep/read internally).
Try to break my draft. Return your research report in English: findings + evidence excerpts (no fs_* tool lines) + VERDICT + LEVEL.
```

**Success criteria**: the task returns a report containing ``VERDICT:`` + ``LEVEL:``

**Rules**:

- Never modify the VERDICT/LEVEL issued by cross-verification (Faithful Reporting)
- After cross-verification returns, **never** call another tool or write supplementary findings

### 8. Compose the final report (aligned with Anthropic's official practice)

The fork verifier has returned a **structured research report** as a ToolResult (Summary / Verified Findings / New Findings / Level Challenge / Verdict). This is research material, **not a deliverable to hand to the user directly**.

Your task: based on the verifier's research material + the evidence from Steps 1-6, write the final user-visible review report **in your own words**.

**Must**:
- Adopt the verifier's VERDICT and LEVEL as-is; **never modify them** (Faithful Reporting)
- Every finding the verifier lists (Verified + New) must appear in the final report
- Improvement suggestions come from the verifier's Improvement Suggestions
- Write the final report in Chinese markdown (the user reads it in Chinese), clearly structured

**Forbidden**:
- Copy-pasting the verifier's output verbatim (it would be shown to the user twice)
- Tampering with the verifier's VERDICT/LEVEL
- Adding findings the verifier did not list (the verifier is the final reviewer)
- Calling any tool after the output starts

**Success criteria**: the final AIMessage contains the complete Chinese review report (findings + improvement suggestions + VERDICT + LEVEL), organized in the main agent's own words, not a verbatim copy of the verifier output
