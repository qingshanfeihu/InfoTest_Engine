---
name: ist-verify
description: "Runs an already-compiled case.xlsx on the device once: collects the framework's real verdicts, backfills empty RUNTIME assertions, attributes each failure across four layers (G/E/V/transient), dispatches compile-worker for targeted recompiles by layer, and writes true-PASS results back to footprint. Verifies existing excel only — never generates new cases. Use when the user says 上机验证 / 上机复验 / verify this case.xlsx / run it on-device and check / 验证用例, or wants an already-compiled excel confirmed on the real device."
context: inline
user-invocable: true
effort: medium
when_to_use: |
  Use when the user wants an already-compiled excel / case.xlsx verified on-device: first run, re-verify, "run it and see", confirm it passes on the device; includes four-layer attribution / runtime backfill / closed-loop writeback.
  Examples: "把这个 excel 上机验证", "上机复验编译好的用例", "上机跑一遍看结果", "验证并按 G/E/V/瞬态归因", "上机 PASS 的写回 footprint".
  Trigger keywords: 上机验证, 上机复验, 上机跑, 验证excel, 验证用例, 跑一遍, 复验, 设备验证, 四层归因, 闭环写回.
  SKIP when: compiling/generating new cases (ist-compile-engine); looking up a single CLI echo (dev_probe); reviewing case file quality without device runs (test-list-review).
---

# On-device verification: serial run + four-layer attribution + reflow handoff

Run the **already-compiled** excel on-device once, collect the framework's real verdicts, backfill `<RUNTIME>`, attribute every fail across four layers, dispatch `compile-worker` reflows by layer, and dual-writeback true PASSes. **One verification pass + handoff** — this skill never edits cases itself (that belongs to `compile-worker`) and never loops "verify until all pass" on its own (iteration is driven by the caller: user / goal loop; this skill runs once and returns). The flow is Steps 1-8 below; tool parameters and return shapes follow each tool's own doc — not restated here.

Attribution filing discipline applies throughout: for every fail with a conclusion, call `submit_attribution`; evidence must be a **verbatim substring** of device_context/causality (copy, never paraphrase) — unfiled conclusions are invisible to next round's "transient-recurrence = mis-attribution" and "freeze same-method" guards.

## Inputs

- Excel path or mindmap name (→ `workspace/outputs/<mindmap>/case.xlsx`) + autoid list.
- **Do not determine build/module yourself, and do not ask the user for them** — when not passed, `dev_run_batch` falls back to `get_config()` dataclass defaults (module=`sdns`, build=current product version). Pass a build string only when the user **volunteered** one. A missing local `compiler_config.json` is normal, not an error.
- Each case's `case.provenance.json` (side-mounted since draft v3; if missing, attribution degrades to verdict-detail-only and no writeback).

## Principles

- **Verdicts come from the framework's per-check_point detail, never the verdict string** — the string can record an environment failure as fail and mask the real cause.
- **Every failure requires reading `device_context`**: `dev_run_batch` returns it for non-pass cases — containing ① framework step-by-step execution + assertion detail + in-case exceptions ② the device config session verbatim (each command + real device response, incl. `^` syntax rejections / `Failed to execute X because Y` → which command was rejected and why) ③ trigger-side RouterA/RouterB/clientc dig output (ANSWER SECTION / actual resolved IPs). `unknown` cases also carry `framework_traceback` (**file-level crash** root cause: one case crashed the whole pytest and everything after it never ran → fix the case the traceback names, do not misjudge the subsequent cases). **Config changes / value fills / reflow briefs are all based on it — never on guesses.**
- **When unsure about framework assertion behavior, read the framework source** (mirror on disk, read-only): assertion semantics in `knowledge/framework/mirror/lib/check_point.py`, row dispatch/variable mechanics in `lib/test_xlsx.py` — why an assertion matched/missed/crashed is decided **by the source** (column-semantics quick reference in `knowledge/data/compile_ref/EXCEL_FUNCTIONS.md`).
- **Attribute honestly, never rescue**: do not dress an environment failure as a pass, and do not blame an assertion failure on the environment.
- **Diagnosis gives facts, not verdicts**: the primary material is the raw `device_context` in `last_run.json`; judge from it. Mechanical pre-judgement only asserts protocol-level facts (G(^) syntax rejection / file-level crash signatures — more reliable than you, accept directly); everything else is undetermined and **you** attribute from the raw text. Semantic judgement is always yours (operational rules in Step 5).
- **Three-layer boundary (whose bug, how to fix)**: **mechanical crashes** (`found_times` always-crash, `found(None)` crash) = emit structural gate's jurisdiction; their appearance means a **compile defect**, goes to recompile, **not** a framework bug. **Falsifiability** (whether an assertion can be falsified for the algorithm class, e.g. "hit exactly N times" is unverifiable under rr/wrr random start) is judged by `compile_check_verifiability`; underdetermined → change the expectation (redirect to membership anchoring / distribution interval). **Semantic sufficiency** (does the assertion truly cover the behavior the mindmap cares about) is your judgement. Never flatten these three into one.
- **Serial within one environment**: the framework holds a global lock per device bed; one `dev_run_batch` at a time per environment (collisions return `device_busy`).
- **Multiple excels in parallel across environments** (when the pool is enabled, `IST_ENV_POOL_ENABLED=1`): issue several `dev_run_batch` calls in one round (one excel each); the pool auto-assigns them to distinct idle environments (independent device beds, no lock contention) → N machines, N lanes; total time ≈ slowest one, not the sum. Excess concurrency queues automatically. **Pool disabled (single environment) stays serial**: one after another, never concurrent (`device_busy`).

## Steps

### 1. Locate excel + provenance

**Execution**: Direct

Determine the excel path and autoid list; note each case's `provenance.json` path (missing → attribution degrades, no writeback). **Do not dig for build/module, do not ask the user** — omitted means `get_config()` defaults (see Inputs).

**Success criteria**: path + autoids ready (build/module on defaults, non-blocking)
**Artifacts**: xlsx_path, autoids, provenance_paths

### 2. First on-device run

**Execution**: Direct

`dev_run_batch_digest(xlsx_path=..., autoids_json='[...]')` — one serial run of the whole sheet, large results digested in-process, returns a **concise summary** (per-case verdict + attribution layer + `found_times` file-level crash culprit named), full detail (`device_context`/`causality`/`framework_traceback`) lands in `workspace/outputs/<mindmap>/last_run.json`. To dig into a fail: `fs_grep <autoid> last_run.json` or `run_python` over it. Omit build/module for `get_config()` defaults (see Inputs); never ask the user for them.

**Rules**: cases containing `<RUNTIME>` must fail the first run (the framework greps the literal "<RUNTIME>") — that is the expected "awaiting backfill", **do not attribute yet**. If the summary flags a `found_times` file-level crash (culprit named) → that is a **compile defect** (framework always crashes), go straight to Step 6 recompile; do not investigate subsequent cases individually.
**Success criteria**: per-case real verdict summary + `last_run.json` full detail
**Artifacts**: digest_summary, last_run.json

### 3. Backfill `<RUNTIME>` (fill-once, locked)

**Execution**: Direct

`compile_runtime_slots(xlsx_path)` lists pending slots + each slot's `observe_cmd`; extract the real value from that command's output in the first run → `compile_runtime_fill(xlsx_path, fills_json=..., run_meta=...)`.

**Rules**: backfill values **only from real device output**; if not extractable, leave empty — never guess. Touch only cells still containing `<RUNTIME>`; once filled they are locked (one fill per slot; even a wrong fill is not silently rewritten).
**Success criteria**: fillable slots filled and locked; unfillable ones honestly recorded as "awaiting manual value"
**Artifacts**: fills (filled / left empty)

### 4. Re-verify (when applicable: Step 3 filled something)

**Execution**: Direct

Run `dev_run_batch_digest` again after backfill. Backfilled assertions should now **pass** (device value = device value); still-failing ones are **real assertion failures** → attribution. Slots still empty do not count as failures and are not attributed.

**Re-verify the subset, deliver on the full sheet**: repair rounds merge only the failing cases before running (the framework clears device config before each case; cases are independent — subset behavior equals full-sheet behavior per case; when fails are the minority the digest summary prints a throttling hint with the exact autoid list — follow it). After everything turns green, **run the full sheet once** as delivery confirmation.

**Success criteria**: separated into true PASS / real fail / awaiting value
**Artifacts**: rerun_results

### 5. Four-layer attribution

**Execution**: Direct

For check_points still failing after re-verify (excluding empty `<RUNTIME>`): first read that case's `device_context` / `framework_traceback` from `last_run.json` (`fs_grep <autoid> last_run.json`), take the step's `layer` from provenance, then `compile_attribute(verdict_detail=<error detail>, failing_assertion_layer=<layer>)` → mechanical pre-judgement. True PASSes skip attribution and go to Step 7.

**Rules**: attribution must rest on `last_run.json`'s device_context/traceback, never on impressions. **Mechanical pre-judgement asserts exactly two certainties**: ① `compile_attribute` returns **G(^)** = device syntax-rejection marker (protocol-level fact, accept directly; it is the upstream root cause — the same case's later dig misses, assertion misses and timeouts are mostly downstream consequences; fix G first); ② file-level crash signatures like `found_times` = compile defect (no per-case attribution). **Everything else returns undetermined — the tool does not guess; you attribute from the raw device_context**: E (reachability/environment), V (assertion expectation), transient (criterion = disappears on a later re-run; anything the digest flags as "same-signature fail two rounds running" is never transient), or suspected product defect (logic right ∧ docs right ∧ environment normal, still reproduces → compare via `kb_bug_search`, record a defect candidate).
**Success criteria**: every real fail has a four-layer conclusion (G / E / V / transient)
**Artifacts**: attributions

### 6. Reflow handoff (repairs go through this path only)

**Execution**: Direct (delegated fork)

When several failed cases need recompiling, **fan out once concurrently — never one-by-one**: build one brief per fail case (autoid + target_layer + fix direction + "targeted redo: fix the problem, keep what is correct"; let the tool inject raw device_context via the `evidence_from_xlsx` parameter — do not hand-copy paraphrases), then call `compile_fanout(skill="compile-worker", briefs_json=[native array])` **once** — N workers run truly in parallel and return per-case artifacts together. After fan-out returns, each case's new `case.xlsx` is under `outputs/<autoid>/`; go back to Step 2 to verify (the device run is the real gate).

**Rules**:
- **The only sanctioned recompile path**: `compile_fanout(skill="compile-worker", briefs)` (concurrent targeted recompiles, backstopped by on-device re-verify). **Never** ad-hoc churn `compile_emit`/`compile_precedent`/`compile_prep` case by case — single-step ad-hoc loops do not converge and slam the per-turn tool_call recursion cap (300), crashing the whole turn (observed: 4 churn rounds, zero excel change). `compile_fanout` is a **batch dispatcher** (not a churnable single step): dispatch once, no loop.
- **Never `fs_edit` case.xlsx** — binary; text editing cannot change it. Case changes go through the reflow path only.
- **Transients do not reflow** — label "environment check / re-run later"; they are unrelated to compile quality.
- **Convergence stop-loss (digest's cross-round comparison is hard fact)**: cases flagged "same-signature fail two rounds running" → last round's fix is falsified; **exclude them from this round's reflow briefs** (a third same-method round almost certainly fails again — observed: zero conversions across two consecutive recompiles). Instead: ① verify environment facts first (dev_probe/dev_ssh the real state of that IP/config on the device — topology and reality can diverge); ② environment confirmed normal yet still reproducing → suspected **product defect**: compare against the defect library via `kb_bug_search`; if known, link it; if new, record a defect candidate in the final report's "suspected product defects" section (repro steps = case steps, expectation + doc source, actual = device_context evidence, version). Cases flagged "last round transient, reproduced this round" → not transient; re-attribute. **Either way, run the flow to completion and produce the full report (true-PASS list + blocked list with evidence); never stall mid-way waiting for a human.**
- Non-interactive (`infotest -p`): output attributions + reflow briefs directly; reflow is initiated by the caller as a separate step.
- **This skill returns here**: whether to verify the recompiled excel again is the **caller's** decision (user / goal loop) — verify never loops itself.

**Success criteria**: G/E/V errors needing recompile dispatched in **one** `compile_fanout(compile-worker)`; same-signature two-round fails excluded from recompile (environment-check / product-defect exit); transients listed separately
**Artifacts**: reflow_brief (fan-out briefs; for >6 cases write the briefs array to a workspace file first and pass `briefs_path` — inline large arrays get truncated by serialization)

### 7. Closed-loop writeback to the precedent store

**Execution**: Direct

For every **true PASS**, perform both complementary writebacks (each has a tool with its own mechanical gate — never hand-assemble files):

1. `compile_writeback(autoid=..., last_run_path="<this run's last_run.json>")` — writes the sheet back to the **precedent store** (mirror + intent index). Two mechanical gates inside: the autoid must be verdict=pass in last_run (on-device oracle, no paraphrase trusted), and the sheet credential must be fresh (what is written back is exactly what ran). Once written, `compile_precedent` in the same run can retrieve it immediately: the fuller the precedent store, the less from-scratch derivation for later same-type compiles.
2. `compile_footprint_writeback(autoid=..., provenance_path="<the case's case.provenance.json>", on_device_passed=True)` — writes the true-PASS **G-layer command grammar** into the footprint tree (evidence gate rejects sourceless facts; G layer only — V assertions / concrete E IPs / runtime values are never written). Provenance exists on every sheet since the emit mandatory gate; the tool auto-skips rare legacy sheets without it.

**Rules**: write back via the tools only — no manual file copying / index editing / hand-built footprint JSON; fail/unknown sheets get **neither** writeback (knowledge-asset poisoning).
**Success criteria**: true PASSes dual-written one by one; report precedent count + footprint written/skipped counts
**Artifacts**: precedent_writeback + footprint G-layer entries

### 8. Output the report

**Execution**: Direct (no tool calls while emitting output)

Use this structure (report content is user-facing, keep it in Chinese):

```
### 上机验证 summary
- excel：<path> | build：<build> | 总 case：N
- 真通过 P / 真实 fail F（G错 a / E错 b / V错 c）/ 瞬态 t / 待补值 r
- 回填：填了 x 个 <RUNTIME>，留空 y 个（待人工补值）

### 逐 case
| autoid | verdict | 归因层 | reflow→层 | 关键裁决明细 |
|---|---|---|---|---|
| <id> | fail | V | →V | fail to find ... |

### footprint 写回
- 写回 N 条 G 段（autoid + feature_id）

### reflow brief（如有 G/E/V 错）
<逐 autoid + target_layer + device_context 摘要 + 应改方向>
```

**Rules**: paste errors verbatim, no hedging; no tool calls during final output.
**Success criteria**: report contains the four sections (summary / per-case table / footprint writeback / reflow brief); anomalies carry root causes
