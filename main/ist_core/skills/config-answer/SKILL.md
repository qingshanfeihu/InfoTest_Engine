---
name: config-answer
description: 任何涉及 APV CLI 命令的问题（查看/生成/解释/翻译/验证），必须查 CLI 手册回答
context: inline
user-invocable: true
when_to_use: |
  Use when the user's request requires APV CLI commands —
  configuration generation, command explanation, parameter lookup, or config translation.
  Trigger keywords: 怎么配置, CLI命令, 生成命令, 翻译成APV, 会话保持, 健康检查
allowed-tools:
  - fs_read
  - fs_write
  - invoke_skill
effort: medium
---

# Config Answer

编排 APV CLI 命令的生成和验证。不自己 grep 手册、不自己写命令——生成委托给 fork draft agent，验证委托给 fork verify agent。

## 硬约束

**不准凭记忆写命令。** 命令必须由 fork draft agent 从手册 grep 生成、经 fork verify agent 独立验证后输出。

## Steps

### 1. 确定场景

生成新配置 → 提供需求描述。翻译第三方配置 → 提供源文件路径和数据提取说明。

### 2. 生成（fork draft）

```
invoke_skill(skill="config-answer-draft", brief="<用户需求 / 源文件路径 + 翻译指示>")
```

fork agent 会 grep 手册、提取数据、生成命令、保存 evidence 和 candidate。

### 3. 验证（fork verify）

```
invoke_skill(skill="config-answer-verify", brief="<candidate_path>\n<evidence_dir>\n<用户需求>")
```

fork agent 独立 grep 手册做对抗校验，返回 `判定：PASS` 或 `判定：CUT`（含具体违规）。

- PASS → 进入 Step 4
- CUT → 反馈给 draft agent 修复 → 重验（最多 1 次），二次 CUT → 标注 `[??]` 进入输出

### 4. 输出

三段结构：文档依据 → 配置命令 → 验证说明。每条命令标注手册出处。输出时禁止再调工具。
