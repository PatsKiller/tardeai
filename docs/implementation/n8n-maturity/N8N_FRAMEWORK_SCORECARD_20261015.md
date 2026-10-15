# n8n workflow framework scorecard — measured by `scripts/check_n8n_workflow_framework.py` (2026-10-15)

```
Status:      ACTIVE (dated measurement; re-run the checker after each remediation PR)
as_of:       2026-10-15
Measured at: origin/main 94601ff69 + this branch (offline: committed workflow JSON, configs, contracts)
Scope:       the 18 active workflows of docs/implementation/n8n-maturity/data/n8n_active_workflows_20261015.json
             (the gap assessment's 2026-10-15 02:35Z live list; not re-queried: a live n8n read was refused to the
             authoring agent, so refresh that file from a host read-only query before the next scorecard)
Policy:      AGENTS.md §23.24 (11.0.0) — activation bar + 30-day remediation clock from ratification
Checker:     python3 scripts/check_n8n_workflow_framework.py [--json] [--strict]
Catalogue:   docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md §12 (element ids FW-*)
Owner:       platform (n8n maturity program)
```

## 1. Result

**0 of 18 active workflows are fully compliant. Fleet 222.5/472 = 47.1%** (pass 1, partial 0.5, n/a excluded;
platform elements reported separately). The reference mature workflow
(`docs/implementation/n8n-parallel/workflows/reference/tradeai-reference-mature-workflow.json`) scores 27/27 = 100%
on the same checker. Every committed workflow file (`--all`, 163 files including pending per-lane shadows and
probes): 1 fully compliant (the reference), 35.4%.

This score is not comparable with the gap assessment's 40%: that was a hand score over six areas (Y/P/N per area);
this is an element score over 27–28 elements, and it adds FW-M6 (expected output), which **every** active workflow
fails.

| Workflow | Class | Scope | Mon | Alert | Log | Recov | Sec | AI | Score | Failing elements |
|---|---|---|---|---|---|---|---|---|---:|---|
| `tradeai-dispatcher` | business-critical | N | P | P | P | P | Y | n/a | 14/26 (53.8%) | FW-C1, FW-C2, FW-C3, FW-M6, FW-A3, FW-A4, FW-A6, FW-L1, FW-R3, FW-R5 |
| `tradeai-event-router` | business-critical | N | P | P | P | P | Y | n/a | 14/26 (53.8%) | FW-C1, FW-C2, FW-C3, FW-M6, FW-A3, FW-A4, FW-A6, FW-L1, FW-R3, FW-R5 |
| `tradeai-digest-scheduler` | business-critical | N | P | P | P | P | Y | n/a | 14/26 (53.8%) | FW-C1, FW-C2, FW-C3, FW-M6, FW-A3, FW-A4, FW-A6, FW-L1, FW-R3, FW-R5 |
| `tradeai-heartbeat-watcher` | resilience | P | P | P | P | P | Y | n/a | 14.5/26 (55.8%) | FW-C1, FW-C2, FW-M6, FW-A3, FW-A4, FW-A6, FW-L1, FW-R3, FW-R5 |
| `tradeai-incident-router` | resilience | P | P | P | P | P | Y | n/a | 12.5/26 (48.1%) | FW-C1, FW-C2, FW-M2, FW-M6, FW-A1, FW-A3, FW-A4, FW-A6, FW-L1, FW-R3, FW-R5 |
| `tradeai-momentum-lifecycle-candidate` | monitoring-compliance | P | P | P | P | P | P | n/a | 12.5/23 (54.3%) | FW-C1, FW-C2, FW-M1, FW-M6, FW-A3, FW-A6, FW-L1, FW-L5, FW-R3, FW-R5 |
| `n8n-incident-fanin` | resilience | P | P | P | P | P | Y | n/a | 12.5/27 (46.3%) | FW-C1, FW-C2, FW-M2, FW-M3, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5 |
| `n8n-pilot-dispatch` | monitoring-compliance | P | P | P | P | P | Y | n/a | 12.5/27 (46.3%) | FW-C1, FW-C2, FW-M2, FW-M3, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5 |
| `n8n-research-intake-consumer` | business-critical | N | P | P | P | P | Y | n/a | 12/27 (44.4%) | FW-C1, FW-C2, FW-C3, FW-M2, FW-M3, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5 |
| `crontab-snapshot-for-health-agent` | resilience | P | P | P | P | P | Y | n/a | 11.5/27 (42.6%) | FW-C1, FW-C2, FW-M2, FW-M3, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5, FW-R6 |
| `catalyst-calibration-monitor-shadow` | monitoring-compliance | P | P | P | P | P | P | n/a | 12.5/27 (46.3%) | FW-C1, FW-C2, FW-M2, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5, FW-S2 |
| `watch-directives-monitor-shadow` | monitoring-compliance | P | P | P | P | P | P | n/a | 12.5/27 (46.3%) | FW-C1, FW-C2, FW-M2, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5, FW-S2 |
| `source-attribution-monitor-shadow` | monitoring-compliance | P | P | P | P | P | Y | n/a | 13.5/27 (50.0%) | FW-C1, FW-C2, FW-M2, FW-M6, FW-A1, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5 |
| `finviz-view-contracts-shadow` | monitoring-compliance | N | P | N | P | P | Y | n/a | 9/27 (33.3%) | FW-C1, FW-C2, FW-C3, FW-M2, FW-M3, FW-M4, FW-M5, FW-M6, FW-A1, FW-A2, FW-A3, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5 |
| `generate-analyst-daily-digest-shadow` | business-critical | N | P | N | P | P | Y | n/a | 9/27 (33.3%) | FW-C1, FW-C2, FW-C3, FW-M2, FW-M3, FW-M4, FW-M5, FW-M6, FW-A1, FW-A2, FW-A3, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5 |
| `lane-governance-packet-weekly-shadow` | monitoring-compliance | N | P | N | P | P | Y | n/a | 9/27 (33.3%) | FW-C1, FW-C2, FW-C3, FW-M2, FW-M3, FW-M4, FW-M5, FW-M6, FW-A1, FW-A2, FW-A3, FW-A4, FW-A6, FW-L1, FW-R1, FW-R3, FW-R5 |
| `tradeai-fabric-run-lane` | resilience | N | P | P | Y | P | Y | n/a | 14.5/26 (55.8%) | FW-C1, FW-C2, FW-C3, FW-M4, FW-M5, FW-M6, FW-A2, FW-A3, FW-A6, FW-R3, FW-R5 |
| `tradeai-fabric-error` | resilience | N | P | P | Y | P | Y | n/a | 12.5/23 (54.3%) | FW-C1, FW-C2, FW-C3, FW-M5, FW-M6, FW-A1, FW-A2, FW-A3, FW-R3 |

**Fleet:** 18 workflows, 0 fully compliant, 222.5/472 = 47.1%; 216 failing elements.

### Platform elements (instance-wide; not in any workflow's score)

| Element | Status | Evidence |
|---|---|---|
| FW-P1 instance saves successful executions | fail | `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none` (GAP §2) |
| FW-P2 n8n DB role not superuser | fail | `pg_roles.rolsuper = t` (WS1b-12) |
| FW-P3 drift check scheduled, P1 on drift | fail | no receipt, no timer (PROGRAM_TRACKER row 40) |
| FW-P4 relay bridge bind firewalled | fail | ufw for `172.19.0.1:18092` not verified |
| FW-P5 image pinned, env access blocked, community packages off | pass | `n8nio/n8n:2.43.0` (tag, not digest) |
| FW-P6 dead-man outside n8n | fail | heartbeat-watch runs in n8n (WS1-15) |

## 2. Gap list per workflow (what each failing element means here)

Common to **all 18**: FW-C1/FW-C2 (no `meta.framework` class/owner in generator output), FW-M6 (no contract declares
`expected_output` — an exit-0 run that produced nothing reads as success), FW-R3 (no declared fallback in metadata).
Common to the 16 legacy: FW-L1 (successes not saved), FW-A6/FW-R5 (no runbook id or path).

| Workflow | Specific gaps (beyond the common set) |
|---|---|
| dispatcher, event-router, digest-scheduler | C3 business-critical past shadow with a DRAFT contract; A4 direct `POST /run` + Stop-and-Error on refusal (599 refusals/day as errors, WS1b-07); A3/M3 contract has no duration bound or `slow` check; M4 class `generic_workflow` has no cap row; R1 legacy `retryOnFail`, not Run Lane |
| heartbeat-watcher | as above (contract DRAFT is partial for resilience); it is also the watcher inside n8n (FW-P6) |
| incident-router | M2/A1 no error workflow for the error router; A4, A3, M3, M4, R1 as above |
| momentum-lifecycle-candidate | S2 PASS since the 2026-10-15 audit DD14 fix (`GET /momentum-lifecycle` added to relay `ROUTES`; the handler now dispatches only through `ROUTE_HANDLERS`); L5 the workflow JSON is not listed by any generator manifest; M1 successes not saved and no run_id join |
| n8n-incident-fanin, n8n-pilot-dispatch | per-lane 2.0.0 shape: M2/A1 no error workflow, M3 no executionTimeout, R1 no retry, A4 direct `POST /run`; M4 class `report` uncapped |
| n8n-research-intake-consumer | as fan-in, plus C3 business-critical live with a DRAFT contract |
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
| 3 | 2026-11-07 | Route legacy run requests through Run Lane: dispatcher / event-router / digest / heartbeat call Run Lane per due item; the four live per-lane workflows fold into dispatcher rows or process workflows (§23.23 "consolidate before migrating"); effect key for `crontab-snapshot-for-health-agent`; add `GET /momentum-lifecycle` to relay `ROUTES` and the momentum candidate to a generator manifest | A4, R1 on 14; R6; S2, L5 on the candidate | agent PRs; import packet + `cron` grant; effect-key owner rows via `effect_claim.py set-owner` (operator) |
| 4 | 2026-11-14 | Platform: instance `EXECUTIONS_DATA_SAVE_ON_SUCCESS` with retention + redaction; n8n DB role non-superuser (`n8n_app`); drift check on a host timer with P1; ufw rule for the relay bind; host dead-man outside n8n. Host side of FW-M6: `LaneRunReceipt@v2` output fields + executor `output_verdict` (`RunReceipt@v3`) so an empty success fails the run, not just the review | FW-P1..P4, FW-P6; runtime enforcement of FW-M6 | operator (compose, DB role, timers, firewall); agent PRs for receipt/executor |
| — | 2026-11-14 | Anything still failing an element with no operator-accepted exception: archive (never delete, §0 rule 6) | — | operator |

## 4. Reproduce

```bash
python3 scripts/check_n8n_workflow_framework.py                 # this table
python3 scripts/check_n8n_workflow_framework.py --json --out /tmp/framework.json
python3 scripts/check_n8n_workflow_framework.py --workflow docs/implementation/n8n-parallel/workflows/reference/tradeai-reference-mature-workflow.json
python3 scripts/check_n8n_workflow_framework.py --all           # every committed workflow file
```

`tests/test_check_n8n_workflow_framework.py::test_scorecard_matches_the_checker` fails when this file and the
checker disagree on the fleet score or the workflow list.
