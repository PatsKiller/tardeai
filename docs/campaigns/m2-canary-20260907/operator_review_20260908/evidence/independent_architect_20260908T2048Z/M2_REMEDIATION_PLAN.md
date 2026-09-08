# M2 remediation plan — campaign `m2-canary-20260907`

Prepared: 2026-09-08T21:00Z  
Source of truth for failures: independent architect FAIL package in this directory  
**Status: PLAN ONLY — no production mutation until operator answers §0 questions and grants scopes**

---

## 0. Operator questions (must answer before Phase C+)

1. **Deploy pin:** promote `origin/main` (`9855e5ad…` = #921 + #924 holdings lock) **or** exact merge `2e49e50a…` only?
2. **Grants to issue (native `bin/guard`):** approve `release-write`, `service`, `cron`, `telegram`, and read-only `db-write` (or a read path) for incident re-verify? Current active grants belong to *another* chat (watch-technicals) and must **not** be reused.
3. **CANARY chat allowlist:** confirm chat IDs / classes already in process env are correct for one outbound proof + your reply.
4. **Human reply window:** will you reply in-Telegram within the activation epoch so inbound consumption can be proven (C-I-04)?
5. **Inbound apply path:** STAGE2 checklist notes `agent_consume_communications.py` defaults dry-run — authorize scheduled `--apply` for canary, or keep dry-run and accept inbound stay dark?
6. **Research non-none effect:** soak needs `effect_kind != 'none'`. If live wakes keep refusing / READ-only, authorize a **controlled canary** subject (tagged non-organic) *or* wait for organic non-none?
7. **Drive sync:** after promote, run Drive sync so operator-visible docs leave `DEGRADED_STALE_SOURCE`?
8. **Dirty maintree:** `local/m2-canary-soak-exec` has 6 dirty lines — stash/commit out-of-band before promote (promote refuses dirty)? Who owns those dirty files?
9. **Success bar:** is the goal **Stage-2 deployability proof** (S-gates + dry/canary) or full **organic Stage-3 soak seal** (≥3 cycles + all 5 organic counts)? Latter needs days + human reply.
10. **Authority to start:** reply exactly `GRANT Stage2` (or list scopes) when ready for mutations.

---

## 1. Complete defect catalog

### 1.1 Legend

| Class | Meaning |
|---|---|
| ID | Stable defect ID |
| Kind | `IDENTITY` / `GOVERNANCE` / `DEPLOY` / `RUNTIME` / `EVIDENCE` / `CODE_RISK` / `ORGANIC` |
| Fix phase | A docs · B dry · C deploy · D activate · E soak · F revalidate |
| Grant | Required guard scope(s), or `none` |

### 1.2 Identity & runtime (Stage-2 blockers)

| ID | Claim | What’s wrong (proven) | Root cause | Fix | Phase | Grant |
|---|---|---|---|---|---|---|
| DEF-IDENTITY-SERVED / C-D-04 | Release == merge | Served/API pin `54639ff5a…`; merge `2e49e50a…` | `release-write` never approved; epoch not started | `cio_phase2_exact_main_deploy.sh prepare` then `promote`; verify SOURCE_COMMIT via `--print-targets`/API | C | release-write |
| DEF-IDENTITY-MAIN / I-MAIN-EQUALS | main == merge | main `9855e5ad…` (#924 after #921); MERGE_AND_DEPLOY_STATE falsely says equal | Stale handoff after later merge | Deploy chosen pin; rewrite identity artifacts honestly | A+C | none / release-write |
| C-P-03 | Poller on CURRENT | PID 3635254 cwd `2b4188f47…` (2026-09-06 daemon) | Long-lived `--daemon` ignores CURRENT flip | Stop/restart poller **after** promote from new CURRENT | C | service (+ maybe cron) |
| C-I-01 / C-D-05 | Inbound + `_send` live | Absent on all deployed trees | Code only in merge SHA | Deploy merge/main; restart poller | C | release-write, service |
| C-P-01 | Wake scheduled on pin | Post-merge wake paused / not on merge SHA | Deliberate pause + never re-armed on new release | Cron entries resolve CURRENT (not hardcoded SHA) | D | cron |
| C-P-02 | Feed on exact release | Snapshot hardcodes `54639ff5a…` paths | Cron written to absolute old release | Repoint feed/wake to CURRENT | D | cron |
| I-DEV-TREE / S-2 | Executing tree == pin | Dev tree dirty; stage2 WT at `ad1b32a71…` | Cron/systemd often use maintree | Clean/reconcile maintree to served pin | C | maintree (if writing primary tree) |
| DEF-EPOCH / I-EPOCH | Activation epoch | `epoch_started=false` | No deploy seal | Emit `M2_CANARY_DEPLOYED.json` + epoch stamp after S-1..S-6 | C | none (after deploy) |
| DEF-DRIVE-STALE / I-DRIVE-CURRENT | Drive == Git/runtime | Drive `DEGRADED_STALE_SOURCE` @ `54639ff5a…` | Sync from stale CURRENT | Sync after promote; label historical snapshots | D | none / Drive path via existing sync |
| COMMS mode drift | Default OFF vs live CANARY | portfolio_server env `COMMS_GATEWAY_MODE=CANARY` on old pin | Partial soak config on old release | Document intended mode; set on **new** served `.env`; restart portfolio-server | C | service, config-write? |

### 1.3 Live / organic (cannot fake)

| ID | Claim | What’s wrong | Fix | Phase | Grant |
|---|---|---|---|---|---|
| C-G-05 / I-MODE-LIVE | Provider SETTLED ack | Soak gateway_delivery=0 | One CANARY outbound through gateway after deploy | D | telegram |
| C-I-04 / I-INBOUND-CORRELATE | Operator reply → receipt | inbound_consumed=0; correlation unproven | Human reply in allowlisted chat; poller on new release | D–E | telegram + human |
| I-COMMIT-CREATE / I-COMMIT-EVAL / I-MEM-CONSUME | Commitment path | organic_commitment=0; wakes refused | Wake must select actionable subject; Lane D settle later | E | cron (organic) |
| I-RES-INGEST / I-RES-MENTION / I-RECEIPT-SUPPRESS | Research loop live | consumption_evidence_count=0 | Feed + wake on new pin; non-none receipt | D–E | cron |
| I-WAKE-EVENT | Wake → CommunicationEvent | Not live-proven on merge pin | Observe after activate | E | none |
| I-SOAK-ORGANIC-TRIGGER | Organic triggers | `unknown:39` | Runner emit `provenance.trigger`; collector reject unknown | B+E | none / small code if missing |
| I-CC-TRUTH / I-CC-UNCONFLATED | CC truth | Pin stale; defect 15 may still need surface check | After deploy, hit maturity/CC; hermetic I-14 re-run | B+C | none |

### 1.4 Governance / evidence package

| ID | Claim | What’s wrong | Fix | Phase | Grant |
|---|---|---|---|---|---|
| DEF-ARTIFACT-ABSENT / I-ARTIFACT-SET | Complete Claude universe | Missing 5 artifacts | Author CAPABILITY_MATURITY_MATRIX, EDGE_INVENTORY, UNPROVEN_REGISTER, FALSIFICATION_RESULTS, GITHUB_DRIVE_SERVED_RECONCILIATION; expand COMPLETE_CLAIM_UNIVERSE with omitted I-* rows | A | none |
| C-X-01 / C-X-02 | Incident PROVEN_LIVE | Independent DB re-read missing | Read-only verify tombstones/ambiguous bytes | B | db read path |
| I-SCHEMA-V2 | @v2 migration apply+rollback | Not re-proven in this package | Disposable DB: apply `2026_09_07_agent_consumption_receipt_v2.sql` + down | B | db-write on disposable / lab DSN only |
| I-GW-MODE-CANARY | CANARY fail-closed | Hermetic only | Re-run authorize/canary negatives; live out-of-allowlist must refuse | B+D | none / telegram for live refuse |

### 1.5 CODE_RISK (not “just deploy”) — from STAGE2 checklist §7

| ID | Risk | Evidence | Plan |
|---|---|---|---|
| RISK-INBOUND-APPLY | Inbound consumer dry-run by default | STAGE2 §7 | Decide apply schedule; add dry-run proof first |
| RISK-EFFECT-NONE | Live effects mostly READ / refused | Soak refused=30, consumption=0 | Controlled canary subject **or** wait organic; never pad |
| RISK-CC-STALE-BODY | CC maturity `generated_at` ancient | STAGE2 §7 | Separate follow-up; don’t block Stage-2 if pin/truth surfaces correct |
| RISK-TRIGGER-FIELD | Wakes lack trigger provenance | Soak note | Patch runner to stamp `provenance.trigger=scheduled_cron` (small code change on main) |

---

## 2. What is NOT wrong (do not “fix”)

- Hermetic suites on `690a23b47…` (79/37/7) — keep as regression gate, not live proof.
- Telegram chokepoint ratchet = 0 undocumented bypasses.
- PR #921 merge itself and 6/6 checks on tested head.
- Incident tombstone *design* (10 preserved / 5 quarantine / 0 deletes) — only independent DB *observation* missing.
- M3/M4 aspirations (C-F-01/02) — correctly non-blocking for M2.

---

## 3. Phased execution plan

### Phase A — Governance repair (no grants) ✅ can start after Q answers on scope of docs only

1. Expand `COMPLETE_CLAIM_UNIVERSE.csv` with all I-* M2 rows + honest classifications.
2. Create missing: `CAPABILITY_MATURITY_MATRIX.csv`, `PRODUCER_CONSUMER_EDGE_INVENTORY.csv`, `UNPROVEN_AND_DARK_REGISTER.csv`, `FALSIFICATION_RESULTS.json`, `GITHUB_DRIVE_SERVED_RECONCILIATION.json`.
3. Correct `MERGE_AND_DEPLOY_STATE.json` copy in campaign evidence: `origin_main_equals_merge_sha=false`, note #924.
4. Publish this plan + question log.

### Phase B — Dry tests (no production mutation)

1. **Identity dry:** `cio_phase2_exact_main_deploy.sh` status / print-targets if available without write; API `/api/health` + maturity `_serving` snapshot (read-only).
2. **Negative controls (already green):** re-run on `origin/main` worktree after checkout:
   - reachability, gateway settlement, inbound, wake loop, dark-contract, write-barrier, canary authorize.
3. **Migration dry:** apply+rollback @v2 on disposable DB.
4. **Wake dry-run on CURRENT tree (read-only flags):**  
   `run_persistent_wake.py --dry-run --select-only` with feed env — expect candidates or honest empty, never `no --subject-guid`.
5. **Poller dry:** prove `^def _send\(` exists in **candidate** tree; prove absent in **served** tree (via process path / prior evidence).
6. **Incident dry:** read-only SQL verify tombstone set if DB readable.
7. **Rollback rehearsal dry:** document PREV_RELEASE=`54639ff5a-main-exact-phase2-20260908-084725`; `--print-targets` sequence only.

**Exit Phase B:** dry-test matrix CSV with PASS/FAIL/UNKNOWN; zero UNKNOWN on hermetic rows.

### Phase C — Deploy (mutations; requires `GRANT Stage2` + scopes)

Order (Claude’s corrected sequence):

1. Clean maintree / worktree at chosen pin (`origin/main` **recommended**).
2. `release-write`: `bash scripts/cio_phase2_exact_main_deploy.sh prepare`
3. Verify stamps (SOURCE_COMMIT, BUILD_SHA) **before** promote.
4. `promote` once.
5. Independent verify: API `source_pin` == pin; portfolio_server cwd == new release; PREV intact.
6. `service`: restart portfolio-server (pick up `.env`); **restart telegram callback poller daemon** from CURRENT (kill stale `2b4188f47` PID).
7. Emit `M2_CANARY_DEPLOYED.json` + epoch start.
8. Drive sync (optional per Q7).

**Exit Phase C:** S-1, S-2, S-4, S-6 PASS; C-D-04/C-I-01/C-D-05/C-P-03 cleared or residual documented.

### Phase D — Activate canary paths

1. `cron`: feed @:55 and wake @:00 via **CURRENT** (no hardcoded SHA).
2. Set `PERSISTENT_WAKE_*` + `COMMS_GATEWAY_MODE=CANARY` on served env; restart services.
3. Controlled canary outbound (tagged) → SETTLED (C-G-05 / I-MODE-LIVE).
4. Operator reply → inbound receipt (C-I-04).
5. Out-of-allowlist negative (must refuse).

**Exit Phase D:** canary proofs recorded as **controlled**, not organic.

### Phase E — Organic soak (Stage 3)

1. Start schema-fixed soak collector with `M2_CANARY_EXPECTED_SHA=<pin>`.
2. Collect ≥3 consecutive wakes with **known** trigger provenance.
3. Wait for organic research non-none, commitment create/eval — **do not manufacture**.
4. Daily: pin still equal; duplicate scan empty; legacy fallback reasons.

**Exit Phase E:** soak archive or honest shorter claim.

### Phase F — Independent revalidation

1. Re-run architect falsification (this agent posture) against new evidence.
2. Require PASS gates from original prompt; else FAIL with residual IDs.

---

## 4. Dry-test matrix (to execute in Phase B)

| Test ID | Command / observation | Intended pass criterion |
|---|---|---|
| DT-01 | pytest reachability+settlement+inbound+wake+dark | exit 0 |
| DT-02 | pytest write-barrier | exit 0 |
| DT-03 | chokepoint `--report` | 0 bypasses |
| DT-04 | wake `--dry-run --select-only` on pin tree | no subject-guid hard-fail |
| DT-05 | migration up+down disposable | both exit 0 |
| DT-06 | API serving pin vs git pin | match after deploy; mismatch now = expected FAIL |
| DT-07 | `ps` poller cwd | equals CURRENT after Phase C; today FAIL |
| DT-08 | authorize out-of-canary hermetic | DETECTED refuse |
| DT-09 | missing transport settlement | raises / non-SETTLED |
| DT-10 | effect_kind=none not consumption | unit assert |
| DT-11 | incident row hashes read-only | match disposition |
| DT-12 | deploy print-targets / status dry | PREV + targets coherent |

---

## 5. Mapping: 34 blocking IDs → phase that clears them

| Clears in A | Clears in B | Clears in C | Clears in D | Clears in E | May remain CODE_RISK |
|---|---|---|---|---|---|
| I-ARTIFACT-SET, DEF-ARTIFACT-ABSENT, I-MAIN-EQUALS (doc), part DEF-IDENTITY-MAIN | C-X-01/02 (if DB), I-SCHEMA-V2, I-GW-MODE-CANARY (hermetic), I-CC-* (partial) | C-D-04, C-I-01, C-D-05, C-P-03, DEF-IDENTITY-SERVED, DEF-EPOCH, I-EPOCH, I-DEV-TREE, I-CC-TRUTH | C-P-01, C-P-02, C-G-05, I-MODE-LIVE, I-DRIVE-CURRENT, DEF-DRIVE-STALE, part C-I-04 | I-COMMIT-*, I-MEM-CONSUME, I-RES-*, I-RECEIPT-SUPPRESS, I-WAKE-EVENT, I-SOAK-ORGANIC-TRIGGER, organic C-I-04 | RISK-* |

---

## 6. Explicit non-goals until asked

- No force-push, no broker/order mutations, no deleting tombstones.
- No manufacturing organic soak counts.
- No reusing other chat’s `git-push`/`maintree` grants.
- No claiming M2 PASS from hermetic green alone.

---

## 7. Immediate next action

**Stop for operator answers to §0.**  
Optionally begin **Phase A + Phase B only** if you reply: `PROCEED DRY` (docs + dry tests, zero production mutation).
