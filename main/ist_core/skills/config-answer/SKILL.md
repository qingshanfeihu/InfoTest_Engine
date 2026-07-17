---
name: config-answer
description: Any question involving APV CLI commands (lookup / generation / explanation / translation / verification) must be answered from the CLI manual, never from memory.
context: inline
user-invocable: true
when_to_use: |
  Use when the user's request requires APV CLI commands —
  configuration generation, command explanation, parameter lookup, or config translation.
  Trigger keywords: 怎么配置, CLI命令, 生成命令, 翻译成APV
  SKIP when: the request is not about APV CLI commands — pure product-spec / concept Q&A, on-device execution (device-verify), reviewing test cases (test-list-review), or IP replacement of an already-generated config (config-automation).
allowed-tools:
  - fs_read
  - invoke_skill
effort: medium
---

# Config Answer

CLI configuration expert. The CLI documentation is the only authority — never write a command from memory. **Grep the manual first, then write the command.**

## Principles

- **Grep before writing**: for every command, `fs_grep` the manual for its syntax first, then write it. Never write first and backfill the grep afterwards
- **Converge, don't spin**: if 2-3 alternative keywords still find nothing → annotate `[未在文档直接命中]` (not directly found in the docs)

## Steps

### 1. Determine the scenario

- **Generation / explanation / verification** (user asks "怎么配置", "命令对不对") → Steps 2-3 (inline fast path; the draft fork completes within ~4s)
- **Translation** (user asks to "翻译成 APV" / convert a third-party config) → Steps 2-4 (fork refinement path; complex third-party translations produce long results, so the output is saved to a file by default)

### 2. Generate (fork draft)

```
invoke_skill(skill="config-answer-draft", brief="<user requirement>")                              # generation scenario
invoke_skill(skill="config-answer-draft", brief="<translation instructions + source file path>")   # translation scenario
```

The draft fork generates every command via `build_command` — command structure is guaranteed by the manual grammar, so the generation scenario needs no second verification. Output directly.

### 3. Verify (fork verify — when applicable: translation scenario)

```
invoke_skill(skill="config-answer-verifier", brief="<candidate_path + evidence_dir>")
```

### 4. Output

- Generation scenario: output directly into the conversation — **do not save a file** (unless the user explicitly asks to "output to a file").
- Translation scenario: `Verdict: PASS` → write the result to a file.
- Either scenario: `Verdict: CUT` → fix (at most 1 retry); a second CUT → annotate `[??]` and include it in the output.
