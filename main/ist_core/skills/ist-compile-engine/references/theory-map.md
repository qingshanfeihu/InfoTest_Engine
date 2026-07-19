# V8 node → theory construct map (reviewers/maintainers; theory at docs/THEORY_k_state_machine.md)

| Node/mechanism | Theory construct | Evidence anchor |
|---|---|---|
| fact stream + fold views | oracle residual axiom (F16) — verdicts cannot be swallowed | delivery-fail swallow measured 3/3 in v6 |
| reconcile (surjective, per dom(V)) | reconciliation direction (F17) | v6 read L⁻¹(failed): final-verify verdicts never read |
| verdict artifact+volume binding | Pass(c, ctx) quantifier discipline (F15) | subset-pass ≠ delivery-pass (save-family measured) |
| authority order in fold | auditor outranks assumption (F18) | pass-lock suppressed the final verify in v6 |
| bed_gate + bed ledger | anchor-difference monitoring Δ over bed vector (F7; ctx=(π,B)) | swapped-build batch burned 2 rounds before human caught it |
| version-distance policy | anchor family, not point equality | 568-precedent vs 585-device is same-family |
| merge ordering + coexist check | persistence channels ①/④ (grammar data) | save-family volume interference; official HA×config-reload warning |
| author first-fail max effort + full history | K-health central thesis (§4) | R2 escalations under old late-escalation policy |
| attribute version-layer first + cross-case duty | layered decidability (§3.2) | mech-evidence 2/2 vs 0/17 natural experiment |
| contradiction ask edge (2nd+ every time) | ask symmetry: uncertainty asks before landing; contradiction asks after locking | user decree 2026-07-10 |
| provisional writeback + rollback | K poisoning prevention (§5) | 3 half-poisoned precedents written back in v6 |
| monotonicity gate (emit, unchanged tool) | conservation ΔI_V ≥ 0 (F13) | AAAA deletion under frozen-override pressure |

Every prompt rule in `agents/compile-worker.md` / `compile-attributor.md` must trace to one of:
① target-system grammar fact (by reference) · ② a theory construct above · ③ a failure mode
measured under the current regime (thinking models + gates + healthy K). Rules deleted from v6
are listed in `removed-rules.md`; a rule returns only with fresh ③-evidence.

## Rule attribution (⑥C, existence-coverage; machine-checked: set(md rule-ID) == set(this table's Rule))

Each `[Wn]`/`[An]` marker in the agent md is one rule; every marker has one row here.
Kind ∈ {theory, grammar, failmode}; a `theory` Ref is a construct-closed-set id (`F\d+` / `§[\d.]+`
above); `grammar`/`failmode` Ref is a free non-empty anchor.

**Numbering is intentionally non-contiguous** (worker skips W16–W19; attributor skips A19): the
machine check only needs `set(md id) == set(table id)` (set equality, not contiguity), so unused
numbers are harmless. **Ids are never reused** — a new rule takes the next free number; a deleted
rule's id (logged in `removed-rules.md`) is retired, not recycled — so the id space stays a stable
audit trail (a gap is either an authoring skip or a retired id, never a silently-renumbered rule).

**`[Wn]` marker form** (Py-Eng strip-test 2026-07-19): the subagent loader does not strip comments,
so an HTML comment `<!--Wn-->` would ship into the model's context — the visible `[Wn]` (~4 chars
per rule) is the deliberate minimum-pollution choice, not a default. Attribution detail lives here
(the review plane); the prompt carries only the id.

**150 line-tripwire baseline** (§5.5:216, 2026-07-19 ⑥C attribution baseline): worker / attributor
sit over 150 with every rule attributed — the per-file threshold is bumped to the post-attribution
actual line count, not a hard cap; from this baseline **any net-line increase must be preceded by a
replacement** (delete an un-attributed / obsolete rule into `removed-rules.md`). First replacement
on record: retrieval-order detail moved worker prompt → `contracts.md` (§5.5:217), so the prompt
keeps only the pointer.

| Rule | Kind:Ref | Evidence |
|---|---|---|
| W1 | theory:§3.2 | claim + falsifying-observation is the decidability basis; every step serves it |
| W2 | failmode:forbidden-mechanism-emitted | clear-config-all family killed 93/105 on two beds |
| W3 | grammar:compile_report_underdetermined | structured triple (test_point/sources/obstacle/equivalent) → user panel verbatim |
| W4 | failmode:extra-object-changes-behavior | batch theme as config justification changes the behavior under test |
| W5 | failmode:observe-then-assert | precedent polarity copy = fake PASS (project red line) |
| W6 | grammar:retrieval-order | precedent → footprint → manual → probe (docstrings state scope) |
| W7 | failmode:distribution-sampling-flaky | 593516/778072 hit-set⊆members + cumulative-share; GA-CUT fixed-count misflag |
| W8 | failmode:presence-by-sampling-luck | dig presence passes whether rotation correct or stuck |
| W9 | failmode:persistence-door-abs-position | zhaiyq live batch: specific-pool after expiry reintroduced absolute-position trap |
| W10 | failmode:layout-range-regex-mismatch | 667986 `show sdns listener` IP-then-port assumption missed |
| W11 | grammar:E/F-column-objects | `case_ir.py` VALID_TEST_OBJECTS vs VALID_TEST_ENV_HOSTS; wrong-door symptom |
| W12 | grammar:compile_check_verifiability | preserve_constraints vs rewritable_claims; NEEDS_USER_DECISION verbatim |
| W13 | failmode:verification-path-absent | no equivalent variant → underdetermined, not hard-code-around |
| W14 | grammar:persistence-families | `domain_grammar.json`; save-family isolation-pass volume-fail |
| W15 | grammar:desc-column | plain Chinese one line/step; regex in column G |
| W20 | failmode:handrolled-xlsx-bypass | run13 bypassed edit invalidated credential; blocks+provenance mandatory |
| W21 | theory:§4 | K data-face discipline: zero hardcoded commands, retrieved this round |
| W22 | theory:F13 | conservation ΔI_V ≥ 0 (monotonicity gate); AAAA deletion under frozen-override |
| W23 | failmode:observe-then-assert | bending assertions to current echo = fake PASS + coverage hole |
| A1 | failmode:retold-echo-dropped-^ | paraphrase fails verbatim-substring gate → mis-attribution |
| A2 | theory:§3.2 | version-layer first; mech-evidence 2/2 vs 0/17 |
| A3 | theory:§3.2 | config-realized-intent; dead feature rode 3 rounds of syntax-polishing |
| A4 | theory:§3.2 | cross-case duty; 3 config-existence passes refuted systemic; interface move 9 downstream |
| A5 | theory:§3.2 | layer definitions G/E/V/transient/product_defect |
| A6 | failmode:env_blocked-one-member-counter | one member's counter while another passed same run ≠ env down |
| A7 | failmode:wrong-door-shell-prompt | shell prompt where device response expected = channel/dispatch, not env |
| A8 | theory:§3.2 | same-case self-check sharpens the verdict (engine does not auto-downgrade) |
| A9 | failmode:defect-reran-historical-PASS | two "defects" re-ran historical PASS forms = form problems |
| A10 | failmode:unchecked-repeat-to-frozen | repeat prescription dragged case to frozen; contradiction → rerun_isolated |
| A11 | failmode:preset-panel-intent-conflict | picking a side rewrites someone's intent; kb_intent_search first |
| A12 | theory:§5 | K-poisoning: engine-generated round is not independent corroboration of polarity |
| A13 | grammar:submit_ask_panel | both sides quoted + retrieval_receipt + neutral hypothesis; tool rejects without panel |
| A14 | failmode:panel-when-derivable | panel only for genuine ought-conflict, not insufficient evidence (that is reflow) |
| A15 | grammar:RUNTIME-slots | `<RUNTIME>` backfill via compile_runtime_fill (device original) |
| A16 | failmode:unanchored-fact-evaporated | 035644/035453 behavior facts gate-rejected, never retried, lost |
| A17 | theory:F16 | attribution counts only once filed; digest guards read landed fields |
| A18 | failmode:english-panel-prose | 545249 users read 3 rounds' detail; English prose left them unable to judge |
| A20 | theory:F16 | engine reads only filed fields; prose conclusions do not count |
| A21 | grammar:verbatim-substring | evidence is a gate-checked verbatim substring of device original |
| A22 | theory:§3.2 | insufficient evidence → reflow with named observation, not a forced layer |
| A23 | failmode:attribution-language-drift | reason/fix_direction English, user_note Chinese — no per-field drift |
