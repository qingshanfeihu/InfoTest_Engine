---
name: compile-worker
description: "Compiles ONE manual test case into a structurally-correct case.xlsx whose assertions truly cover the target behavior — by replicating the main agent's free-reasoning logic (understand the behavior, judge which layer each assertion belongs to, emit via compile_emit). Used when an orchestrator dispatches a single-case compile leg. Does NOT run on-device, does NOT self-assess (the orchestrator dispatches verify separately). Invoked with a structured brief as $ARGUMENTS."
context: fork
agent: compile-worker
user-invocable: false
---

# Task: compile one manual case into case.xlsx

Immediately below is the orchestrator's brief: a machine-readable envelope on line 1, then the data zone (historical device evidence / structural facts / attribution hypothesis / intent). Task instructions follow the brief inside `<instructions>`.

## Brief from orchestrator

$ARGUMENTS

<instructions>
Compile the manual case in the brief above into a structurally-correct case.xlsx whose assertions truly cover the target behavior.

Work the way the main agent does — freely: understand what behavior this case tests → judge whether each assertion's expected value is static-layer or runtime-layer → design the steps (config / trigger / assert) → land with `compile_emit`. How to judge layers, where command grammar is looked up, and the three device truths (single device / complete assembly / dig trigger hosts) are all in your system prompt — follow it.

The JSON envelope on the brief's first line (autoid/manifest_path/advisory_path/round/redispatch_reason): first `fs_read` the **original** step_intents for your autoid inside `manifest_path` (that is the source requirement; where the brief's intent summary disagrees, the manifest wins), then `fs_read` the batch-wide advisory at `advisory_path`; `redispatch_reason` tells you why this redispatch happened (probe hint / emit error / user decision / on-device failure) — fix what it names, do not start over.

Tool-injected device evidence / precedents / footprint in the brief are **factual references** — they confirm how commands are written and what actually happened on the device last round; they are not assertions to copy. When you need behavior or grammar confirmed, use `fs_read` / `kb_footprint` / `compile_precedent` / `dev_probe` at your own judgement — **there is no mandatory fixed order**.

When `compile_emit` returns "produced structurally-correct", that is the finish line — take the path and return with a one-line test rationale. No self-review of self-production, no reading the xlsx back to tick boxes: the semantic verdict lives in the independent on-device verification, not here.

**The last two lines of your return are the machine-readable tail block — exact format, each on its own line** (the orchestrator reconciles on it; the body above is free-form). The two common endings in full:

<examples>
<example>
(body: one-line test rationale — behavior covered, what is asserted, expectation source)

STATUS: produced
ARTIFACT: workspace/outputs/<autoid>/case.xlsx
</example>
<example>
(body: the verifiability tool's NEEDS_USER_DECISION block verbatim + preserved constraints + pending claim)

STATUS: needs_user_decision
ARTIFACT: -
</example>
</examples>

On failure, the body carries the final error verbatim and the tail keeps the same format (STATUS: failed / ARTIFACT: -). Never mix negation phrasing ("no / not triggered / no need to report") into the same sentence as a marker token — measured: 40 of 46 historical returns contained the string NEEDS_USER_DECISION while only 6 were genuinely underdetermined; the machine reads only the tail block above.
</instructions>
