---
name: config-answer-draft
description: Generate APV CLI configuration commands from user requirements or source config translation. Greps CLI manual, extracts source data, produces candidate commands with evidence.
context: fork
agent: config-answer-draft
user-invocable: false
---

# 生成 APV CLI 配置命令

## Brief from orchestrator

$ARGUMENTS

<instructions>
主 agent 已把需求或源配置文件信息放在上面 brief 中。你的任务：按 subagent prompt 的流程 grep 手册、提取数据、生成命令、保存 evidence 和 candidate。
</instructions>
