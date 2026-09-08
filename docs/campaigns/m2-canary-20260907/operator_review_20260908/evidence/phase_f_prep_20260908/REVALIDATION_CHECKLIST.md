# Phase F revalidation checklist — m2-canary-20260907

Prepared: 2026-09-08 (Phase F **prep only** — scaffolding, not executed PASS)  
Campaign: `m2-canary-20260907`  
Expected served pin: `aaa9115cbc2745b34a6d0a48cbdbd012c0ac6816`  
Expected release: `aaa9115cb-main-exact-phase2-20260908-171709`  
Prior FAIL package: `evidence/independent_architect_20260908T2048Z/`  
Remediation claim universe: `evidence/claim_universe_remediation_20260908/`  
Activated seal: `evidence/M2_CANARY_ACTIVATED.json` (`research_policy=ORGANIC_ONLY`)

**Hard constraints for this prep:** read-only scaffolding. Do **not** deploy, mutate production, send Telegram, invent organic evidence, claim M2 PASS, or seal Stage-3 (soak not sealed).

Phase F (from `M2_REMEDIATION_PLAN.md` §3): re-run independent architect falsification against new evidence; require PASS gates from original FAIL package structure; else FAIL with residual IDs.

Companion machine table: `BLOCKING_IDS_STATUS.csv` (34 prior blocking IDs).

---

## Summary counts (prep mapping — not a verdict)

| Bucket | Count | IDs |
|---|---|---|
| Needs Phase E organic evidence | **8** | I-COMMIT-CREATE, I-COMMIT-EVAL, I-MEM-CONSUME, I-RES-INGEST, I-RES-MENTION, I-RECEIPT-SUPPRESS, I-WAKE-EVENT, I-SOAK-ORGANIC-TRIGGER |
| Clearable from A–D artifacts (intent) | **25** | All other blocking IDs except I-SCHEMA-V2 |
| Residual non-organic (B incomplete) | **1** | I-SCHEMA-V2 (`DT-09 PENDING`) |

Operator success bar (`OPERATOR_DECISIONS.md` Q9): **Stage-3 organic soak seal** — therefore Phase F PASS cannot close until the 8 organic IDs have real soak evidence.

---

## Per-ID checklist

For each row: map prior blocking defect → phase that clears it → evidence hint → high-level probe → expected_for_PASS. Status cells left for Phase F execution (do not fill PASS here).

### Cleared in A (governance / honest identity docs)

| ID | cleared_in_phase | evidence_path_hint | probe_command_hint | expected_for_PASS | F status |
|---|---|---|---|---|---|
| DEF-ARTIFACT-ABSENT | A | `claim_universe_remediation_20260908/` (7 companions) | List required artifact filenames; match `ARCHITECT_HANDOFF.json` | All required companions present | _pending F_ |
| I-ARTIFACT-SET | A | same + `COMPLETE_CLAIM_UNIVERSE.csv` | Count I-* M2 rows; no ABSENT required set | Universe + companions complete | _pending F_ |
| I-MAIN-EQUALS | A | `independent_architect_20260908T2048Z/MERGE_AND_DEPLOY_STATE_CORRECTED.json` | Confirm `origin_main_equals_merge_sha=false` and honest note | No false main==merge claim | _pending F_ |
| DEF-IDENTITY-MAIN (doc half) | A (+C runtime) | corrected merge-state + deploy seal | Doc honesty + pin policy `origin/main_at_prepare` | Honest identity narrative | _pending F_ |

### Cleared in B (dry / hermetic / DB read)

| ID | cleared_in_phase | evidence_path_hint | probe_command_hint | expected_for_PASS | F status |
|---|---|---|---|---|---|
| C-X-01 | B | dry matrix DT-10; incident verify output | Read-only tombstone/hash verify (no DB mutate) | Independent observation matches disposition | _pending F_ |
| C-X-02 | B | same as C-X-01 | Same | Same | _pending F_ |
| I-CC-UNCONFLATED | B | hermetic suite logs / DT-01 | Re-run CC unconflation / I-14-class tests on pin tree | Hermetic green on pin | _pending F_ |
| I-GW-MODE-CANARY (hermetic) | B (+D live refuse) | DT-03 canary negatives | Re-run authorize/canary fail-closed fixtures | Refuse/allowlist negatives PASS | _pending F_ |
| I-SCHEMA-V2 | **cleared_B** | DT-09 PASS (apply+rollback exit 0) | Disposable DB: apply + rollback `@v2` migration only | Both apply and rollback exit 0 | **CLEARED** — `phase_f_prep_20260908/DT09_MIGRATION_V2.json` |

### Cleared in C (deploy / identity / process)

| ID | cleared_in_phase | evidence_path_hint | probe_command_hint | expected_for_PASS | F status |
|---|---|---|---|---|---|
| C-D-04 | C | `M2_CANARY_DEPLOYED.json` | API `_serving.source_pin` == `aaa9115cbc…` | Served pin matches seal | _pending F_ |
| DEF-IDENTITY-SERVED | C | same + CURRENT `SOURCE_COMMIT` | Compare API / CURRENT / seal | Triple agreement on pin | _pending F_ |
| C-I-01 | C | deploy seal `poller_cwd_verified` | `/proc/<pid>/cwd` under CURRENT release | Inbound path live on pin | _pending F_ |
| C-D-05 | C | seal `poller_def_send_present` | `rg`/`grep` for `def _send` on served poller script | `_send` present on served tree | _pending F_ |
| C-P-03 | C | seal poller_pid / cwd | Process cwd == `aaa9115cb-main-exact-phase2-20260908-171709` | No stale `2b4188f47` daemon | _pending F_ |
| DEF-EPOCH / I-EPOCH | C | `M2_CANARY_DEPLOYED.json` `epoch_started` | Read seal fields only | `epoch_started=true` | _pending F_ |
| I-DEV-TREE | C | deploy `s_gates.S-2_dev_tree` | Porcelain / HEAD vs pin | PASS or documented PARTIAL residual | _pending F_ (note PARTIAL) |
| I-CC-TRUTH | C | maturity/CC serving after promote | Read-only maturity/`_serving` pin check | Surfaces report aaa9115cb | _pending F_ |

### Cleared in D (activate / controlled canary — not organic)

| ID | cleared_in_phase | evidence_path_hint | probe_command_hint | expected_for_PASS | F status |
|---|---|---|---|---|---|
| C-P-01 | D | `M2_CANARY_ACTIVATED.json`; DT-16 | Confirm wake cron resolves CURRENT | Wake scheduled on pin | _pending F_ |
| C-P-02 | D | ACTIVATED + `POST_PROMOTE_FEED_AND_SELECT.json` | Confirm feed @:55 CURRENT; feed counts coherent | Feed on exact release | _pending F_ |
| C-G-05 | D | `INBOUND_OK_PROVEN.json` → `gateway_outbound_proof` (SETTLED pmid 50986); ACTIVATED `canary_gateway_settled` | Independent ledger/API re-read of SETTLED delivery; **re-adjudicate** if `M2_CANARY_GATEWAY_OUTBOUND_PROOF.json` shows later FAILED overwrite | Controlled SETTLED gateway ack proven | _pending F_ |
| I-MODE-LIVE | D | same as C-G-05 | `delivery_owner=gateway` + SETTLED | Live ownership path for canary | _pending F_ |
| C-I-04 | D | `INBOUND_OK_PROVEN.json` | Correlate operator `ok` → events → consumption receipts | Controlled inbound proven | _pending F_ |
| I-INBOUND-CORRELATE | D | same | Outbound pmid/correlation → inbound → receipt | Correlation chain intact | _pending F_ |
| DEF-DRIVE-STALE / I-DRIVE-CURRENT | D | `DRIVE_SYNC_POST_PROMOTE.json` (+ refresh reconciliation at F) | Drive sync exit 0; source_commit vs pin | Not `DEGRADED_STALE_SOURCE` on current pin | _pending F_ |
| I-GW-MODE-CANARY (live refuse) | D | Phase D exit criteria | Observe out-of-allowlist refuse if claimed | Refuse outside allowlist | _pending F_ |

### Needs E (organic soak — do not invent)

| ID | cleared_in_phase | evidence_path_hint | probe_command_hint | expected_for_PASS | F status |
|---|---|---|---|---|---|
| I-SOAK-ORGANIC-TRIGGER | E (B stamps) | future soak archive / `soak-collector/` when READY | Counts: ≥3 consecutive wakes; `trigger_classification` known (not `unknown:*`); `M2_CANARY_EXPECTED_SHA=aaa9115cbc…` | Known-trigger organic wakes | **needs E** — `ORGANIC_TRACES.json` currently empty |
| I-WAKE-EVENT | E | soak organic traces / event ledger on pin | Wake → CommunicationEvent path under ORGANIC_ONLY | Organic wake→event proven | **needs E** |
| I-RES-INGEST | E | soak research ingest metrics | Organic ingest/store advancement post-epoch | Non-padded research ingest | **needs E** |
| I-RES-MENTION | E | soak mention/subject edges | research→stored→mention | Organic mention edge | **needs E** |
| I-RECEIPT-SUPPRESS | E | soak consumption with `effect_kind != none` | Receipt linkage for non-none effect | Organic non-none receipt | **needs E** |
| I-COMMIT-CREATE | E | soak `organic_commitment` create | Commitment create on pin | organic_commitment > 0 (real) | **needs E** |
| I-COMMIT-EVAL | E | soak commitment eval | Commitment eval on pin | Eval observed organically | **needs E** |
| I-MEM-CONSUME | E | soak memory consumer edge | Consumer edge live organically | Memory consume proven | **needs E** |

---

## Phase F execution gates (when soak sealed — not now)

1. Recompute identity: API pin, CURRENT, poller cwd, Drive source_commit all `aaa9115cbc2745b34a6d0a48cbdbd012c0ac6816` / release `aaa9115cb-main-exact-phase2-20260908-171709`.
2. Re-run hermetic negative controls on pin tree; chokepoint bypasses remain 0.
3. Adjudicate controlled Stage-2 proofs (A–D) vs organic Stage-3 counts (E) separately — controlled canary must not pad organic.
4. Fill `VERDICT_TEMPLATE.md` only after evidence exists; use exact verdict line formats below.
5. If any of the 8 E-IDs or I-SCHEMA-V2 remain unproven → **FAIL** with residual IDs (do not claim PASS).

---

## Explicit non-claims (prep)

- No M2 PASS.
- No Stage-3 soak seal.
- No assertion that organic counts are >0 (`ORGANIC_TRACES.json` is empty `{}` at prep time).
- No Telegram / deploy / production mutation from this package.
