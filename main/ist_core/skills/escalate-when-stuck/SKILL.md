---
name: escalate-when-stuck
description: "Honest escalation exit for a genuinely stuck compile task. Use after all legitimate means are exhausted (manual lookup, precedent search, device probing, converting dynamic behavior into assertable show output) and no case.xlsx with framework-executed, non-vacuous check_points can be produced — instead of forcing weak assertions or a fake-pass artifact. Trigger scenarios: 卡住, 表达不了, 做不出, 只能弱断言, stuck."
context: inline
user-invocable: true
when_to_use: |
  Use when all legitimate paths (manual / precedents / device probing / form conversion) are exhausted and no framework-executed, non-vacuous case.xlsx can be produced — honest escalation is required instead of forcing weak assertions.
  Trigger keywords: 卡住, 表达不了, 做不出, 只能弱断言, stuck.
  SKIP when: there are untried legitimate means; or it is a single tool error (retry per the error guidance / switch channel first).
effort: medium
---

# Stuck: report honestly, never fudge

Reaching this point means the case likely **cannot be expressed** with the current xlsx DSL capabilities plus device-observable means — typically "cross-step numeric comparison of runtime dynamic values" (e.g. which IP the first dig returned, then comparing later responses against it) when the device has no show command that turns that behavior into stable text.

## Red line: never fudge for the sake of "completion"

Both of the following are worse than honestly saying "cannot be done", and are **forbidden**:
- Falling back to a **weak assertion** (only verifying the response is within some set, or that the command echoes the domain) while pretending the target behavior is covered;
- Hand-crafting an artifact that runs but is **vacuous** (zero real check_points; the framework only runs init and passes) to fill the quota.

An honest "cannot be done + why + what next" is worth far more than a fake pass.

## Honest exit (do in order)

1. **Confirm once more there is truly no way out**: have you actually used `dev_probe` to check whether the device has a show command that observes this behavior? (Session persistence → persistence state table; distribution → statistics counters; state change → status table entries.) Many "hard-to-assert dynamic behaviors" have a show command that converts them into stable, text-searchable output. If one exists, go back and use it — do not escalate yet.

2. **Write a structured blocker report** (into your final reply):
   - What behavior the case intends to test (author's original intent);
   - Which paths you tried (which manual sections were read / which show commands were probed and their actual output / which assertion forms were attempted and their on-device results);
   - Why it cannot be expressed (specific missing capability: e.g. the xlsx DSL cannot extract an output field for numeric comparison, and the device has no corresponding show command);
   - Your 2-3 candidate ways forward (e.g. framework DSL needs a specific capability / a human must confirm whether the device has a certain command / a degraded verification is possible but loses X).

3. **Record it truthfully**: call `remember` with the body starting with `[未解决/needs-human]`, containing the blocker and the missing capability — kept distinct from "verified lessons", for the next same-type case and for maintainers.

4. **Ask for a decision (if possible)**: if the `ask_user` tool is available, use it to hand over "which way forward / is the degraded option acceptable". Without that tool (autonomous mode), deliver the blocker report above as the final output for humans to review — **do not fudge a fake pass because nobody answered**.

> Whether you are "truly stuck" is your call: if you have not actually read the manual / probed the device / tried show-based observation, you are not stuck — go back and continue. Only after all of that fails does this exit apply.
