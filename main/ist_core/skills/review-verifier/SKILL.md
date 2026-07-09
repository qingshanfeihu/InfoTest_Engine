---
name: review-verifier
description: Independent adversarial verification of a test list review draft. Re-reads evidence, challenges findings, and assigns the final VERDICT (PASS/PARTIAL/FAIL) and LEVEL (P0-P7). Invoked from test-list-review Step 7; takes a structured brief as $ARGUMENTS.
context: fork
agent: review-verifier
user-invocable: false
---

# Verify the test list review draft

The main agent has finished evidence collection and drafted the review. Your task: **independently verify** the draft, find the issues the main agent missed, and issue the final VERDICT and LEVEL.

## Brief from main agent

$ARGUMENTS

## Your job

1. Independently re-read the `test_case_file` from the brief (read it in full; do not skip)
2. Check every entry in the brief's `draft_findings`: does the line number exist? does the description match? is the severity reasonable?
3. Find the issues the brief missed (see the adversarial probes in your system_prompt)
4. Challenge the brief's `draft_level`: based on the actual evidence, is the P level too loose / too tight?
5. Produce your **structured research report** (in English — the main agent composes the final user-facing review from it), ending with the VERDICT + LEVEL lines
