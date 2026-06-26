---
name: config-answer-verify
description: Independent adversarial verification of APV CLI commands against the CLI manual. Re-reads generated candidate commands and grep evidence, independently re-greps the manual for each command, and returns PASS or CUT with specific violations. Called by config-answer Step 3.5.
context: fork
agent: config-answer-verifier
user-invocable: false
---

# 验证生成的 APV CLI 命令是否正确

主 agent 已经 grep 过手册并生成了候选配置命令。你的任务：**独立验证**这些命令——找出语法错误、编造命令、参数值越界。

## Brief from main agent

$ARGUMENTS

## 你的步骤

根据 brief 中的 `candidate_path` 读取候选命令文件。独立 `fs_grep` 手册逐一验证。如有 evidence 文件也读之——它们能帮你看出主 agent 查了什么、漏了什么。

输出结论时，文末以单独的 `判定：PASS` 或 `判定：CUT` 行结尾。CUT 时必须附具体违规说明。
