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

## Retrieval order (worker grounding; §5.5:217 replacement — detail lives here, prompt keeps only the pointer)

Grounding an expected value or a command consults these in order — each is a distinct authority,
higher listed = same-intent-closer:

1. `compile_precedent` — same-intent verified forms (config **form**, never assertion direction).
2. `kb_footprint` — verified grammar/behavior; uncertain observations are context-tagged — judge
   them against your own config form, and arbitrate by device experiment when they conflict.
3. manual under `knowledge/data/markdown/product/manual_<version>/`.
4. `dev_probe` / `dev_help` — live syntax and echo shape; their docstrings state their scope.

## SSL dispatch (cert-family / execute / server grounding + silent-failure faces)

The cert-method inventory, arg-signatures, and the two file branches are DATA — `fs_read` them
from the mirror, never hardcode method names:

- dispatch skeleton (E/F/G/H/I → `getattr(E_obj, F)(*pos, **kw)`): `mirror/lib/apv/test_xlsx.py:280-336`.
- cert-family methods (csr / importKey / importCert / importSni* / RootCA / InterCA / CRLCA /
  sm2* / activeCert) + signatures + the local-file-vs-TFTP branch: `mirror/lib/apv/ssl_comm.py`
  (importKey :89, importCert :124, sm2ImportKey :572). RSA import is `<vhost>, <path>` (2 args);
  **sm2 import is 3 args `<keyType>, <vhost>, <keyFile>`** (SM2 dual-certificate, signkey/enckey) —
  a wrong arg count crashes the sheet (checked against 8 golden rows, #50 CC2). CSR subject is
  hardcoded (US/CA/San Jose/…), not parameterisable.
- execute action registry (Chinese action-name → func_N): `dic_operation.py:57` (live; NOT the
  commented-out `ssh_server.py:151`) + `apv_action.py:11-44` / `client_action.py`.
- server-trigger hosts (server213/231/232): `env.py:66-82` (SSH to a config `env` host; IP-restore
  side-effect `ssh_server.py:95-118`, same restore contract as bed writes).

Silent-failure faces — a fail here masquerades as a V-layer assertion-wrong; attribution must
tell a harness-silent-failure apart from real device behaviour:

| face | mechanism | source |
|---|---|---|
| S1 | cert/key file missing → print + return, import never happened, no error raised | `ssl_comm:102-104` |
| S2 | execute action-name miss / fuzzy-match ≥0.8 mis-dispatch → None | `dic_operation:72/:79-80` |
| S3 | server / read_until timeout → partial output, not an exception | `ssh_server:91` |
| S4 | TFTP source `172.16.35.215` unreachable / file absent | `ssl_comm *_tftp` |
| S5 | H stores None (most SSL imports do not return) → a downstream `H` reference is meaningless | `test_xlsx:332-336` |

Golden SSL cases all take the local-file branch (`cert/epolicy_ssl/*.key|.crt`), never TFTP (#50 CC3)
— bed readiness needs the local cert tree, not the `.215` server. The `ssl activate certificate <h>`
→ `ssl host virtual <h>` structural dependency is grammar-checked (`ssl_cert_activate_needs_host_define`).
