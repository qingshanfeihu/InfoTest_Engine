---
name: ist-compile-engine
description: "V6 compile engine entry point: turns a mindmap into on-device-verified case.xlsx deliverables in one call — a deterministic state machine drives the whole closed loop (write → ask user on underdetermined → merge → on-device run → attribution → targeted recompile → iterate to fixpoint → writeback → report), resumable from checkpoint. Preferred whenever the user asks to 编译 / 脑图转excel / compile-and-verify."
context: inline
user-invocable: true
effort: low
when_to_use: |
  Use when the user wants manual test cases (mindmap/txt) compiled into automated case.xlsx with on-device verification and delivery.
  Examples: "编译 dongkl.txt", "把这批脑图编译并上机", "用例编译".
  Trigger keywords: 编译, 脑图转excel, 编译上机, 用例编译, 闭环编译.
  SKIP when: re-verifying an existing excel only (ist-verify); looking up a single CLI (dev_probe).
engine:
  graph: main.ist_core.compile_engine.graph:graph
  phases: [prep, worker_fanout, ask_decision, merge, run_digest, attribute, writeback, report]
  holes:
    worker: compile-worker
    attributor: compile-attributor
  tools: [compile_engine_run]
---

# V6 compile engine (state-machine driven; LLM only inside the holes)

Call `compile_engine_run(mindmap_path, product_version)` once — the deterministic state machine runs the whole loop:
dispatch a worker per case (mechanical gates + probe self-check) → underdetermined cases pop a user panel (decision lands only after the answer; ask-before-write is code-enforced) → merge (credential gate + pass sheet lock) → on-device run → attribution (known-defect short-circuit / mechanical pre-judgement / LLM fills only the undetermined) → recompile the fail subset only → iterate to fixpoint (all pass / all labeled / round cap) → true-PASS dual writeback → delivery report.

- If the product version is missing, `ask_user` first — a wrong version invalidates the grammar of the whole batch.
- If the engine is interrupted (process death / device busy), **re-calling with the same arguments resumes from checkpoint**; completed device rounds are not re-burned.
- Keep the user-facing summary **short**: the engine has already written the full delivery report to the `delivery_report.md` path given in its return (batch pass/fail summary + deliverable paths + evidence for cases needing disposition). The report lives on disk — do not retell it. One or two sentences of results plus "完整报告见 `<delivery_report.md path>`" is enough. **Never replay the whole report inline** (long responses under deepseek streaming get self-truncated mid-sentence; observed in practice). Machine-readable full data is in `engine_report.json`.
- When the return contains "escalated to human" entries, the engine has exhausted its mechanical paths for those cases (rounds exhausted / attribution missing). Deciding on the user's behalf hides failures inside a report — **full evidence is already in `delivery_report.md`/`unsuccessful_cases.md`; list only autoid + one-line reason and point to the report** (do not replay device echoes at length — that is exactly the streaming-truncation trigger), then `ask_user` for disposition. Disposition is an **open, per-case semantic judgement** (rewrite the case description, mark abandoned, file a product defect, give a fix direction and retry, … depending on why it failed) — **do not present a fixed option list**; lay out the facts and let the user (or yourself, case by case) judge.
- When restating device behavior, quote only: echo excerpts in the return, each case's `fail_evidence` in engine_report, or the `device_context` raw text via `fs_read` of that batch's `last_run.json`. If it cannot be quoted, read first, then quote; if unreadable, write "未取到回显". "Echoes" reconstructed from conversational memory are fabricated evidence — one instance retold "device unsupported" as "executed successfully" and rendered a config session that never happened (trace-verified).
