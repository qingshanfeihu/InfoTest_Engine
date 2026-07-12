---
name: ist-compile-engine
description: "V8 compile engine entry point: turns a mindmap into on-device-verified case.xlsx deliverables in one call. An event-sourced fact ledger drives the loop (bed check → author → ask on underdetermined → merge → run → reconcile → attribute → targeted recompile → final delivery verify → writeback → report); every device verdict is reconciled with an explicit outcome, so swallowed verdicts are structurally impossible. Resumable from checkpoint. Preferred whenever the user asks to 编译 / 脑图转excel / compile-and-verify."
context: inline
user-invocable: true
effort: low
when_to_use: |
  Use when the user wants manual test cases (mindmap/txt) compiled into automated case.xlsx with on-device verification and delivery.
  Examples: "编译 dongkl.txt", "把这批脑图编译并上机", "用例编译".
  Trigger keywords: 编译, 脑图转excel, 编译上机, 用例编译, 闭环编译.
  SKIP when: re-verifying an existing excel only (ist-verify); looking up a single CLI (dev_probe).
engine:
  graph: main.ist_core.compile_engine_v8.graph:graph
  phases: [prep, bed_gate, author, ask_decision, merge, run, reconcile, attribute, diagnose, ask_contradiction, closing]
  holes:
    worker: compile-worker
    attributor: compile-attributor
  tools: [compile_engine_run]
---

# V8 compile engine (fact ledger driven; LLM only inside the holes)

Call `compile_engine_run(mindmap_path, product_version)` once — the engine runs the whole loop
and may pause on any of three user-decision edges, each surfacing as an ask panel:

- **bed_gate** — device build anchor mismatch or foreign residue on the shared bed;
- **ask_decision** — underdetermined claims (ask-before-write is code-enforced);
- **ask_contradiction** — the user-adjudication edge: intent discrepancies filed by the
  attribution hole via submit_ask_panel (manual vs device, expected vs observed — the user
  confirms / corrects via free text / declares a product defect), round-cap resource grants,
  env-blocked stop-loss confirmations, alone-pass-volume-fail contradictions, and
  resume-or-keep for previously suspended cases. Unanswered questions auto-suspend the case
  (non-terminal; re-asked on the next run with the same arguments).

If the product version is missing, `ask_user` first — a wrong version invalidates the whole
batch's grammar. If the run is interrupted, re-calling with the same arguments resumes from
checkpoint; completed device rounds are not re-burned. Batch truth lives in
`workspace/outputs/<batch>/facts.jsonl` (append-only); machine contracts are documented in
`references/contracts.md`.

If the engine stops early or errors, your only recovery moves are: re-call with the same
arguments (checkpoint resume), or report the stall to the user and wait. Do NOT hand-merge
sheets with compile_emit_merged, hand-run dev_run_batch on engine artifacts, or edit
case.xlsx directly to "finish the job" — those bypass the credential/lint gates, the fact
ledger, and attribution, so the delivery loses its audit chain and the next resume
mis-reads the batch state (run13: a bypassed edit invalidated a credential and stalled the
whole batch).

Keep the user-facing summary **short**: the engine already wrote the full report to
`delivery_report.md` (path in its return). One or two sentences plus the report path is
enough; never replay the report inline. When restating device behavior, quote only from the
engine return, `engine_report.json`, or the referenced run files — never from memory.
