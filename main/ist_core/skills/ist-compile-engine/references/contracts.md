# V8 machine contracts (mechanism only; data lives in the referenced files)

## Fact stream (`workspace/outputs/<batch>/facts.jsonl`, append-only, single writer = engine)

| ev | identity (idempotency key) | carries |
|---|---|---|
| `authored` | (aid, round) | artifact fingerprint of the produced sheet |
| `needs_decision` / `decision` | (aid, question_id) | underdetermined claim ↔ user answer |
| `verdict` | (aid, run_id) | ctx (delivery/subset), result, signatures, **artifact**, **volume**, bed, build, evidence_ref |
| `attribution` | (aid, round) | layer, disposition, fix_direction, evidence |
| `merged` | content | volume fingerprint, composition, moved_tail, coexist_violations |
| `writeback` / `rollback` | (aid, voucher_run/of) | provisional flag / reason |
| `escalated` / `bed_checked` | content | reason / anchor+findings |

Rules: facts only append; unknown `ev` types are skipped by the fold (forward compatible);
derived views are pure functions (`views.py`) — state labels are computed, never stored.

## Fingerprints (verdict-to-artifact binding)

- artifact = `<aid>:<emit-credential xlsx_mtime>`; volume = sha1 of sorted (aid, artifact) pairs.
- `deliverable(aid)` requires the latest delivery-ctx verdict to be pass **and** match both the
  current artifact and the current volume composition — an old sheet's pass never certifies a
  new sheet.

## Worker/attributor tail blocks (parsed by the engine)

```
STATUS: produced | needs_user_decision | failed
ARTIFACT: workspace/outputs/<autoid>/case.xlsx
VERDICT: <layer>/<disposition>
```

dispositions: reflow / frozen / rerun_isolated / env_blocked / defect_candidate / fixed.

## Ask edges (all three are user holes; interrupt + Command(resume))

`bed_gate` (anchor mismatch / foreign residue) · `ask_decision` (underdetermined claims) ·
`ask_contradiction` (passed-alone/failed-in-volume, every occurrence from the second onwards).

## Persistence channels & bed probes

Data-driven from `knowledge/data/compile_ref/domain_grammar.json`
(`persistence_channels`, `bed_probes`) — adding a channel or probe is a JSON edit, zero code.
Bed ledger: `runtime/bed_ledger/<host>.jsonl` (created/restored pairs; auto-cleanup only for
our own unrestored artifacts).

## Derived-remedy queue & ask precondition (2026-07-10, §11.7)

- Fact types added: `run_done` (device-run idempotency marker), `cap_reached` (round budget
  hit; a resource question, not a terminal), `suspended` (user chose to suspend; batch-settled,
  resumable next run). `authored` may carry `remedy` (the remedy_key it implements).
- `attribution` facts carry `user_note` (Chinese, report-facing), `doc_quote`/`doc_source`/
  `device_quote` (doc-vs-device pair; device_quote substring-gated), `channel` (mechanical).
- `remedies.derive_queue(facts, aid, case_rows)` — pure function; ask edges require the queue
  to be EMPTY (`remedies.queue_empty`). Queue actions: self_cleanup (per persistence channel
  `case_mitigation` data) → recompile_directed (keyed per attribution round) → rerun_isolated
  → vary_form.
- Rendering (`render.py`) is a pure projection of facts; `render.leak_scan` gates internal
  enum/hash leakage out of user-facing reports.

