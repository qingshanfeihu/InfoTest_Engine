---
name: review-verification
description: Independent adversarial verification of a test list review draft. Re-reads evidence, challenges findings, and assigns the final VERDICT (PASS/PARTIAL/FAIL) and LEVEL (P0-P7). Invoked from test-list-review Step 7; takes a structured brief as $ARGUMENTS.
context: fork
agent: review-verifier
user-invocable: false
---

# Verify the test list review draft

主 agent 已完成证据收集和草稿撰写。你的任务是**独立验证**草稿、找出主 agent 漏掉的问题，给出最终 VERDICT 和 LEVEL。

## Brief from main agent

$ARGUMENTS

## Your job

1. 独立复读 brief 中的 `test_case_file`（完整读完，不要跳过）
2. 核对 brief 中每条 `draft_findings`：行号是否存在？描述是否匹配？severity 是否合理？
3. 找 brief 漏的问题（参考你 system_prompt 中的 adversarial probes）
4. 挑战 brief 中的 `draft_level`：基于实际证据看 P 级别给得是不是松了/紧了
5. 输出**用户可见**的中文评审报告，文末以 VERDICT + LEVEL 行结尾
