---
name: config-answer
description: 任何涉及 APV CLI 命令的问题（查看/生成/解释/翻译/验证），必须查 CLI 手册回答
context: inline
user-invocable: true
when_to_use: |
  Use when the user's request requires APV CLI commands —
  configuration generation, command explanation, parameter lookup, or config translation.
  Trigger keywords: 怎么配置, CLI命令, 生成命令, 翻译成APV
allowed-tools:
  - fs_read
  - invoke_skill
effort: medium
---

# Config Answer

CLI 配置专家。一切以 CLI 文档为准，不准凭记忆写命令。**先 grep 手册，再写命令。**

## Principles

- **写前 grep**：每条命令先 `fs_grep` 手册找语法，再写。不准先写后补 grep
- **收敛不空转**：换 2-3 个关键词仍无 → 标注 `[未在文档直接命中]`

## Steps

### 1. 确定场景

- **生成/解释/验证**（用户问"怎么配置"、"命令对不对"）→ Step 2-3（inline 快速路径）
- **翻译**（用户要求"翻译成 APV"、转换第三方配置）→ Step 4（fork 精细化路径）

---

### 生成场景（fork draft，4s 内完成）

### 2. 生成

```
invoke_skill(skill="config-answer-draft", brief="<用户需求>")
```

draft fork 用 `build_command` 生成——命令结构由手册文法保证，无需二次验证。直接输出。

PASS → 直接输出到对话中，**不保存文件**（除非用户明确要求"输出到文件"）。CUT → 修复（最多 1 次），二次 CUT → 标注 `[??]` 进入输出。

---

### 翻译场景（fork 精细化路径）

复杂第三方配置翻译，结果较长，默认保存文件。

### 4. 生成 + 验证 + 输出

```
invoke_skill(skill="config-answer-draft", brief="<翻译指示 + 源文件路径>")
invoke_skill(skill="config-answer-verify", brief="<candidate_path + evidence_dir>")
```

PASS → 输出到文件。CUT → 修复（最多 1 次），二次 CUT → 标注 `[??]` 进入输出。
