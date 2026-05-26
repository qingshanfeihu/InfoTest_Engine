# InfoTest_Engine SKILL 编写标准

## 来源

完全对齐 Claude Code 官方 SKILL.md 模板（cc-haha `bundled/skillify.ts:96-145`）。
所有新 skill 都必须按此标准；已有 skill 在重构时迁移到此标准。

## Frontmatter 字段（YAML）

```yaml
---
name: kebab-case-skill-name
description: 一行描述（中英文皆可）
allowed-tools:
  - tool_name(path/pattern/*)
  - tool_name
when_to_use: |
  Use when... + trigger phrases + example user messages.
  SKIP when: ...
argument-hint: "optional hint showing argument placeholders"
arguments:
  - arg_name_1
  - arg_name_2
context: inline | fork
---
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| name | YES | kebab-case，全局唯一 |
| description | YES | 一行，含 TRIGGER / SKIP 条件 |
| allowed-tools | YES | 工具模式列表（带 path 限定） |
| when_to_use | YES | 详细触发条件 + 示例 |
| context | NO | `inline`（默认）或 `fork` |
| arguments | NO | 参数列表 |
| argument-hint | NO | 占位符提示 |

## 正文结构

```markdown
# Skill Title

一句话 goal。

## Inputs

- `$arg_name`: 描述

## Goal

Clearly stated goal for this workflow.

## P 级别定义（评审类 skill 专用）

...

## Steps

### 1. Step Name

What to do in this step. Be specific and actionable.

**ONLY**: path/pattern（限定工具访问范围）
**Success criteria**: ALWAYS include this!
**Execution**: Direct | Task agent | Teammate | [human]
**Artifacts**: data later steps depend on
**Human checkpoint**: when to pause for user
**Rules**: hard rules (NON-NEGOTIABLE constraints)
```

## 强制约束

- **Success criteria**: REQUIRED on every step（cc-haha skillify.ts:131）
- **并发步骤**: 用子编号 3a / 3b
- **Human action**: `[human]` 标在标题
- **allowed-tools 用模式**: `qa_deepagent_grep(qa/*)` 不是 `qa_deepagent_grep`
- **when_to_use CRITICAL**: 决定 LLM 何时自动调用此 skill
- **context: fork**: 自包含任务用 fork（独立上下文）
- **BLOCKING REQUIREMENT**: 必须调的工具/步骤用此标记

## 桶隔离规则（评审类 skill）

评审类 skill 必须在每个 Step 限定 path 范围：

- `product/` 是产品定义（CLI / spec）
- `qa/` 是测试资产（Test List / Strategy）
- **NEVER** use qa/ paths for product semantics
- 每个 Step 的 `**ONLY**` 字段限定该步骤可访问的路径前缀

## Verifier 集成（评审类 skill）

评审类 skill 必须在最后一个实质步骤调用 verifier subagent：

```
task(subagent_type="review-verification", description="""
  test_case_file: <path>
  bug_id: <id>
  ...
  draft_findings: [<list>]
  draft_level: P0-P7
""")
```

主 agent **不能 self-assign** verdict / level。
