---
name: config-answer-draft
description: Generate APV CLI configuration commands from user requirements or source config translation. Greps CLI manual, extracts source data, produces candidate commands with evidence.
context: fork
agent: config-answer-draft
user-invocable: false
---

# Generate APV CLI configuration commands

## Brief from orchestrator

$ARGUMENTS

<instructions>
The main agent has placed the requirement or the source-config file information in the brief above. Your task: follow the flow in your subagent prompt — grep the manual, extract the data, generate the commands, and save the evidence and candidate files.
</instructions>
