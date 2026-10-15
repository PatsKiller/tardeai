# n8n workflow framework scorecard — STATIC CONFORMANCE measured by `scripts/check_n8n_workflow_framework.py` (2026-10-15)

```
Status:      ACTIVE (dated measurement; re-run the checker after each remediation PR)
as_of:       2026-10-15 (re-measured after the third-party audit fix; first measurement 221.5/472 = 46.9% on the v1 checker)
Measured at: train/merge-20261015-b 602863095 + the audit-fix branch (offline: committed workflow JSON, configs, contracts)
Scope:       the 18 active workflows of docs/implementation/n8n-maturity/data/n8n_active_workflows_20261015.json
             (the gap assessment's 2026-10-15 02:35Z live list; not re-queried: a live n8n read was refused to the
             authoring agent, so refresh that file from a host read-only query before the next scorecard)
Policy:      AGENTS.md §23.24 (11.0.0) — activation bar + 30-day remediation clock from ratification
Checker:     python3 scripts/check_n8n_workflow_framework.py [--json] [--strict] [--gate activation]
Catalogue:   docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md §12 (element ids FW-*, §23.24 crosswalk 23.24-*)
Owner:       platform (n8n maturity program)
```

## 0. What these numbers are — and are not

The percentage is **static conformance**: the share of the checker's offline predicates that the committed
artifact satisfies (pass 1, partial 0.5, n/a excluded). It is **not operational maturity**. It does not prove that a
run succeeded, that an effect was safe, that recovery works, or that the deployed copy equals the committed one
(third-party audit 2026-10-15: "46.9% measures selected checker predicates, not operational maturity"; "the
reference's 100% score does not prove successful execution, safe effects or recovery"). The checker now reports five
separate fields per workflow — artifact integrity, design coverage (this score), deployed parity, runtime outcome,
activation eligibility — and maps every §23.24 obligation (68 rows: 36 static, 6 platform, 26
`not_checkable_offline`) in N8N_CONTRACTS_DESIGN.md §12.2. **Every runtime obligation is UNPROVEN for every
workflow**: no runtime evidence file exists yet. **No workflow is activation-eligible** (`--gate activation` exits 1
for all 18 and for the reference).

## 1. Result

**0 of 18 active workflows statically conformant; 0 of 18 activation-eligible. Static conformance 274/531 = 51.6%**
(up to 31 elements per workflow, n/a excluded; platform elements reported separately and gated). 220 failing elements.

Why the number moved from 46.9% and why the two are not comparable: the audit fix added four structural elements
(FW-W1..W4: connections valid, reachability, required nodes on a trigger path, metadata = graph) that the legacy
graphs all pass or are n/a (+59 points on +59 elements), and strengthened existing predicates, which removed 7.5
points on the original elements (214/472 = 45.3% on those, down from 221.5/472 = 46.9%; element-by-element diff
against the auditor's `fleet_report.json`): FW-R6 now requires an ARMED effect key (`n8n_claim: true`) for live
lanes — `n8n-incident-fanin`, `n8n-pilot-dispatch`, `n8n-research-intake-consumer` go pass → fail (staged keys, both
claim flags false; `crontab-snapshot-for-health-agent` already failed, no key); FW-M5 requires `connects_to` to name
every graph dependency — 9 go pass → partial. A higher total is not a better fleet; the structural elements are
there so a broken graph cannot score green, not to reward the legacy ones.

The reference mature workflow
(`docs/implementation/n8n-parallel/workflows/reference/tradeai-reference-mature-workflow.json`) scores 31/31 static
conformance and is **not activation-eligible** (24 blocking reasons: 6 platform elements not PASS, 18 runtime
obligations UNPROVEN). Every committed workflow file (`--all`, 163 files including pending per-lane shadows and
probes): 1 statically conformant (the reference), 2030/4877 = 41.6%, 0 activation-eligible.

| Workflow | Class | Graph | Scope | Mon | Alert | Log | Recov | Sec | AI | Static conformance | Runtime | Eligible | Failing elements |
|---|---|---|---|---|---|---|---|---|---|---:|---|---|---|
| `tradeai-dispatcher` | business-critical | Y | N | P | P | P | P | Y | n/a | 18/30 (60.0%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-C3, FW-M6, FW-A3, FW-A4, FW-A6, FW-L1, FW-R3, FW-R5 |
| `tradeai-event-router` | business-critical | Y | N | P | P | P | P | Y | n/a | 18/30 (60.0%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-C3, FW-M6, FW-A3, FW-A4, FW-A6, FW-L1, FW-R3, FW-R5 |
| `tradeai-digest-scheduler` | business-critical | Y | N | P | P | P | P | Y | n/a | 18/30 (60.0%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-C3, FW-M6, FW-A3, FW-A4, FW-A6, FW-L1, FW-R3, FW-R5 |
| `tradeai-heartbeat-watcher` | resilience | Y | P | P | P | P | P | Y | n/a | 18/30 (60.0%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-M6, FW-A3, FW-A4, FW-A6, FW-L1, FW-R3, FW-R5 |
| `tradeai-incident-router` | resilience | Y | P | P | P | P | P | Y | n/a | 16.5/30 (55.0%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-M2, FW-M6, FW-A1, FW-A3, FW-A4, FW-A6, FW-L1, FW-R3, FW-R5 |
| `tradeai-momentum-lifecycle-candidate` | monitoring-compliance | Y | P | P | P | P | P | P | n/a | 14/25 (56.0%) | UNPROVEN (9) | no | FW-C1, FW-C2, FW-M1, FW-M6, FW-A3, FW-A6, FW-L1, FW-L5, FW-R3, FW-R5, FW-S2 |
| `n8n-incident-fanin` | resilience | Y | P | P | P | P | P | Y | n/a | 14/30 (46.7%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-M2, FW-M3, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5, FW-R6 |
| `n8n-pilot-dispatch` | monitoring-compliance | Y | P | P | P | P | P | Y | n/a | 14/30 (46.7%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-M2, FW-M3, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5, FW-R6 |
| `n8n-research-intake-consumer` | business-critical | Y | N | P | P | P | P | Y | n/a | 13.5/30 (45.0%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-C3, FW-M2, FW-M3, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5, FW-R6 |
| `crontab-snapshot-for-health-agent` | resilience | Y | P | P | P | P | P | Y | n/a | 14/30 (46.7%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-M2, FW-M3, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5, FW-R6 |
| `catalyst-calibration-monitor-shadow` | monitoring-compliance | Y | P | P | P | P | P | P | n/a | 15/30 (50.0%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-M2, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5, FW-S2 |
| `watch-directives-monitor-shadow` | monitoring-compliance | Y | P | P | P | P | P | P | n/a | 15/30 (50.0%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-M2, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5, FW-S2 |
| `source-attribution-monitor-shadow` | monitoring-compliance | Y | P | P | P | P | P | Y | n/a | 16/30 (53.3%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-M2, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5 |
| `finviz-view-contracts-shadow` | monitoring-compliance | Y | N | P | N | P | P | Y | n/a | 12/30 (40.0%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-C3, FW-M2, FW-M3, FW-M4, FW-M5, FW-M6, FW-A1, FW-A2, FW-A3, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5 |
| `generate-analyst-daily-digest-shadow` | business-critical | Y | N | P | N | P | P | Y | n/a | 12/30 (40.0%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-C3, FW-M2, FW-M3, FW-M4, FW-M5, FW-M6, FW-A1, FW-A2, FW-A3, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5 |
| `lane-governance-packet-weekly-shadow` | monitoring-compliance | Y | N | P | N | P | P | Y | n/a | 12/30 (40.0%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-C3, FW-M2, FW-M3, FW-M4, FW-M5, FW-M6, FW-A1, FW-A2, FW-A3, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5 |
| `tradeai-fabric-run-lane` | resilience | Y | N | P | P | Y | P | Y | n/a | 18.5/30 (61.7%) | UNPROVEN (18) | no | FW-C1, FW-C2, FW-C3, FW-M4, FW-M5, FW-M6, FW-A2, FW-A3, FW-A6, FW-R3, FW-R5 |
| `tradeai-fabric-error` | resilience | Y | N | P | P | Y | P | Y | n/a | 15.5/26 (59.6%) | UNPROVEN (9) | no | FW-C1, FW-C2, FW-C3, FW-M5, FW-M6, FW-A1, FW-A2, FW-A3, FW-R3 |

**Fleet:** 18 workflows, 0 statically conformant, 0 activation-eligible; static conformance 274/531 = 51.6%; 219 failing elements (train 3: +1 FW-S2 for momentum-lifecycle-candidate after the relay route fix, audit DD14).

"Runtime" = the runtime obligations that apply to the workflow (§23.24 crosswalk rows marked
`not_checkable_offline`), all UNPROVEN: 18 for a workflow that requests lane runs, 9 for one that does not.

### Platform elements (instance-wide; not in any workflow's score; every one blocks `--gate activation`)

| Element | Status | Evidence |
|---|---|---|
| FW-P1 instance saves successful executions | fail | `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none` (GAP §2) |
| FW-P2 n8n DB role not superuser | fail | `pg_roles.rolsuper = t` (WS1b-12) |
| FW-P3 drift check scheduled, P1 on drift | fail | no receipt, no timer (PROGRAM_TRACKER row 40) |
| FW-P4 relay bridge bind firewalled | fail | ufw for `172.19.0.1:18092` not verified |
| FW-P5 image pinned by digest, env access blocked, community packages off | partial | `n8nio/n8n:2.43.0` is a tag pin, not a digest (was scored pass on the v1 checker) |
| FW-P6 dead-man outside n8n | fail | heartbeat-watch runs in n8n (WS1-15) |

### Audit counterexamples (regression fixtures, `tests/test_check_n8n_workflow_framework_adversarial.py`)

Each was scored with its manifest row (and, except the hash case, `meta.graph_sha256`) re-stamped to match, so no
hash or generator check can carry the verdict. v1 = the checker at e355be188; v2 = this one.

| Fixture | v1 | v2 (failing elements) |
|---|---|---|
| all connections removed (audit) | 27/27 | 22.5/29 — W2, W3, W4, A4, L5, R2 |
| Run Lane node disabled (audit) | 27/27 | 23.5/29 — W2, W3, A4, L5, R2 |
| Run Lane does not wait (audit) | 27/27 | 29/31 — W3, L5 |
| every Switch output → success (audit) | 27/27 | 28/31 — W2, W3, L5 |
| zeroed graph + policy hash (audit) | 27/27 | 29/31 — W4, L5 |
| success node returns `status: 'success'`, produced 0 (audit) | 27/27 | 29/31 — W3, L5 |
| HTTP `authentication: none` with stored credential (audit) | 27/27 | 26.5/31 — W2, L4, L5, S1 |
| webhook `authentication: none` with credential object (audit) | 27/27 | 29/31 — L5, S1 |
| `https://attacker.invalid/TRADEAI_N8N_RUN_URL/{{…}}/status` (audit) | 27/27 | 26/31 — W2, L4, L5, S1, S2 |
| Run Lane call unreachable | 27/27 | 24/29 — W2, W3, A4, L5, R2 |
| triggers not connected | 27/27 | 22.5/29 — W2, W3, W4, A4, L5, R2 |
| connection to a missing node | 27/27 | 29/31 — W1, L5 |
| refusal outputs routed to the throwing node | 27/27 | 28/31 — W2, A4, L5 |
| relay credential name with a foreign credential id | 27/27 | 26.5/31 — L4, L5, S1, S3 |
| relay variable concatenated after an attacker host | 27/27 | 27/31 — W4, L4, L5, S2 |
| canary with the staged (both flags false) effect key (audit) | 27/27 | 29/31 — L5, R6 |
| `effect_process` naming no effect-key process | 27/27 | 28/31 — W4, L5, R6 |
| AI metadata for a nonexistent `Judge` node (audit) | 35/35 | 29/39 — W4, A5, L5, G1..G7 |
| AI step on a non-LLM node, template of another process, free-text branch | 35/35 | 29/39 — W4, A5, L5, G1..G7 |
| `runbook_id` with no runbook, `runbook_path` an unrelated file | 27/27 | 28/31 — A6, L5, R5 |
| `health_contract_id` that does not exist (fell through to the dispatcher's lane contract) | 26/27 (C3 pass) | 24.5/31 — C3, M4, M6, A2, A3, L5 |
| reference `meta` copied onto a schedule → no-op graph | 20.5/21 | 17/25 — W3, W4, C3, M6, A2, A3, L5 |
| malformed `expected_output` (numeric field/unit, `evidence: [{}]`, no empty reason) (audit) | 27/27 | 30/31 — M6 |
| `expected_output` with boolean count and infinite window | 27/27 | 30/31 — M6 |
| `run_id` custom data only inside a JS comment | 27/27 | 29.5/31 — M1 partial, L5 |
| `retryOnFail` on the Run Lane call (two retry owners) | 27/27 | 29/31 — R1, L5 |
| reference under `--strict` with platform FAILs (audit) | exit 0 | `--strict` exit 0 (a lint); `--gate activation` exit 1, 24 blocking |

## 2. Gap list per workflow (what each failing element means here)

Common to **all 18**: FW-C1/FW-C2 (no `meta.framework` class/owner in generator output), FW-M6 (no contract declares
`expected_output` — an exit-0 run that produced nothing reads as success), FW-R3 (no declared fallback in metadata).
Common to the 16 legacy: FW-L1 (successes not saved), FW-A6/FW-R5 (no runbook id or path).

| Workflow | Specific gaps (beyond the common set) |
|---|---|
| dispatcher, event-router, digest-scheduler | C3 business-critical past shadow with a DRAFT contract; A4 direct `POST /run` + Stop-and-Error on refusal (599 refusals/day as errors, WS1b-07); A3/M3 contract has no duration bound or `slow` check; M4 class `generic_workflow` has no cap row; R1 legacy `retryOnFail`, not Run Lane |
| heartbeat-watcher | as above (contract DRAFT is partial for resilience); it is also the watcher inside n8n (FW-P6) |
| incident-router | M2/A1 no error workflow for the error router; A4, A3, M3, M4, R1 as above |
| momentum-lifecycle-candidate | S2 calls `GET /momentum-lifecycle`, which the relay handler serves but its `ROUTES` table (and so `--routes` and the relay contract check) omits; L5 the workflow JSON is not listed by any generator manifest; M1 successes not saved and no run_id join |
| n8n-incident-fanin, n8n-pilot-dispatch | per-lane 2.0.0 shape: M2/A1 no error workflow, M3 no executionTimeout, R1 no retry, A4 direct `POST /run`; M4 class `report` uncapped; R6 (new, v2): the live lane's effect key is staged (`n8n_claim: false`, `cron_claim: false`), not armed; M5 `connects_to` omits the lane |
| n8n-research-intake-consumer | as fan-in (incl. R6 staged key), plus C3 business-critical live with a DRAFT contract |
| crontab-snapshot-for-health-agent | as fan-in, plus R6: live lane not in `config/n8n_effect_keys.json` |
| catalyst-calibration-monitor-shadow, watch-directives-monitor-shadow | S2 lane not in the run allowlist (fails every fire); archive approved 2026-10-10, not applied |
| source-attribution-monitor-shadow | per-lane shape gaps; archive approved (superseded by a dispatcher row) |
| finviz-view-contracts-shadow, generate-analyst-daily-digest-shadow, lane-governance-packet-weekly-shadow | no health contract at all (C3, M4, M5, A2, A3 fail) plus the per-lane shape gaps; the analyst digest is business-critical |
| tradeai-fabric-run-lane | no health contract (C3, M4, M5, A2, A3); no runbook |
| tradeai-fabric-error | no health contract; A1 self-referencing (its own failure must be caught host-side); runbook ids only through the intent route table (A6/R5 partial) |

## 3. Remediation order (30-day clock from 2026-10-15; due 2026-11-14)

Ordered by (failing elements removed) ÷ (grants needed). Each wave is one or more reviewed PRs; every import is a
packet under a `cron` grant naming the workflow ids (§23.2); nothing here is applied by an agent.

| Wave | By | Work | Elements closed | Owner / gate |
|---|---|---|---|---|
| 0 | 2026-10-17 | Archive (never delete) `catalyst-calibration-monitor-shadow`, `watch-directives-monitor-shadow`, `source-attribution-monitor-shadow` — approved 2026-10-10 | 3 rows leave the active set (2 fail every fire) | operator `cron` grant (PROGRAM_TRACKER row 39) |
| 1 | 2026-10-22 | Generator PR: emit `meta.framework` (class, owner, stage, connects_to, runbook_id/path, health_contract_id, rollback) from a spec for the generic, per-lane and fabric generators; set `errorWorkflow: tradeai-fabric-error`, `executionTimeout`, `saveDataSuccessExecution: all` on generic and per-lane shapes; one runbook per workflow (copy the reference runbook) | C1, C2, R3, A6, R5 on all; M2, A1, M3, L1, L2 on the legacy 16 | agent PR; import packet + operator `cron` grant |
| 2 | 2026-10-29 | Contract PR: `expected_output` rule on every active workflow's contract (owners declare the unit, rule and fatal skip reasons — the hermes worker-pool case is the template); duration bound + `slow` check on the 7 generic contracts; new contracts for run-lane, fabric-error, finviz-view-contracts, analyst digest, lane-governance; REVIEWED for the 5 business-critical; `class_caps` rows for `report`, `monitor`, `generic_workflow` | M6 on all; C3, M3, M4, M5, A2, A3 | contract owners review; operator for REVIEWED of business-critical |
| 3 | 2026-11-07 | Route legacy run requests through Run Lane: dispatcher / event-router / digest / heartbeat call Run Lane per due item; the four live per-lane workflows fold into dispatcher rows or process workflows (§23.23 "consolidate before migrating"); effect key for `crontab-snapshot-for-health-agent` and ARM the staged keys of the live per-lane workflows (`n8n_claim: true`, plus `cron_claim: true` while a cron line can fire); add `GET /momentum-lifecycle` to relay `ROUTES` and the momentum candidate to a generator manifest | A4, R1 on 14; R6; S2, L5 on the candidate | agent PRs; import packet + `cron` grant; effect-key owner rows via `effect_claim.py set-owner` (operator) |
| 4 | 2026-11-14 | Platform: instance `EXECUTIONS_DATA_SAVE_ON_SUCCESS` with retention + redaction; n8n DB role non-superuser (`n8n_app`); drift check on a host timer with P1; ufw rule for the relay bind; host dead-man outside n8n. Host side of FW-M6: `LaneRunReceipt@v2` output fields + executor `output_verdict` (`RunReceipt@v3`) so an empty success fails the run, not just the review | FW-P1..P4, FW-P6; runtime enforcement of FW-M6 | operator (compose, DB role, timers, firewall); agent PRs for receipt/executor |
| — | 2026-11-14 | Anything still failing an element with no operator-accepted exception: archive (never delete, §0 rule 6) | — | operator |

## 4. Reproduce

```bash
python3 scripts/check_n8n_workflow_framework.py                 # this table
python3 scripts/check_n8n_workflow_framework.py --json --out /tmp/framework.json
python3 scripts/check_n8n_workflow_framework.py --workflow docs/implementation/n8n-parallel/workflows/reference/tradeai-reference-mature-workflow.json
python3 scripts/check_n8n_workflow_framework.py --all           # every committed workflow file
python3 scripts/check_n8n_workflow_framework.py --gate activation   # fail-closed promotion gate (exit 1 today for all)
python3 -m pytest tests/test_check_n8n_workflow_framework_adversarial.py   # the audit counterexamples
```

`tests/test_check_n8n_workflow_framework.py::test_scorecard_matches_the_checker` fails when this file and the
checker disagree on the fleet score or the workflow list.
