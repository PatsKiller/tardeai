# INC-20261014-SPCX — resting Schwab stops filled; the stop alerts were digested

```
id:            20261014-spcx           sev: SEV1        ic: operator (John)       opened: 2026-10-14 ~14:40 ET
status:        CONTAINED (not RESOLVED: operator's own stop check (1), BROKER_LIVE_ENABLED (5) and postmortem (6)
               open — §8, updated 2026-10-22; Schwab reads back in read_only since 10-16)
exit criteria: (1) every Schwab account's working orders inventoried by the operator, leftover SPCX stops
               cancelled or kept on purpose; (2) every stop-firing alert pages (P0) — done, #1732 LIVE;
               (3) Schwab paused state is loud, never silent — done, #1733 LIVE; (4) the host cannot place,
               replace or cancel without an operator unlock — done, #1734 LIVE, LOCKED; (5) BROKER_LIVE_ENABLED
               removed; (6) postmortem written (§7 of the incident runbook)
recorded:      2026-10-15T02:35Z by Agent A (read-only), in the format of docs/runbooks/INCIDENT_RESPONSE.md §3
evidence:      ~/n8n-maturity-verification/incident-spcx-20261014/ (ORDER_PATHS_AND_PROVENANCE, KILL_SWITCH_DESIGN,
               MFA_INTEGRITY, RECOVERY, SCHWAB_DEPENDENCY_*, SECURITY_REVIEW*, THREAT_MODEL);
               ~/n8n-maturity-verification/arch-review-20261014/ARCHITECTURE_REVIEW_20261014/OPS_READINESS.md §2
```

This is the first record of the incident in `docs/incidents/`. Before this file existed, the incident had no
record, owner or severity (finding WS8-01). The timeline is a backfill. Each line names its evidence.

## 1. Summary

At 14:36 and 14:38 ET on 10-14, SPCX stop orders resting at Schwab filled at about $151.5:

- about 200 shares in `schwab_taxable`;
- about 600 shares in `schwab_rollover_ira`.

The operator placed these stops by hand on 10-06 and 10-07, outside the host. The host did not place them:
`schwab_pilot_orders` has 0 SPCX rows, and no host log shows a Schwab order POST since 2026-08-28. The stops
worked as stops.

**What failed was the alerting.** From 13:50 ET, `stop_health_check` warned "about to fire" (NEAR_TRIGGER).
Every warning was routed as `Suppressed (P1_DIGEST)`: 48 stop_health alert events went unsent, and so did
"CRITICAL STOP ALERT · 2" at 14:40. The first page was the SIEM backstop at 14:45 ET, after both fills. The
operator's first question was "hacked / who sold it?". The answer came from Schwab's own records and the
stop_health payloads, not from host logs.

## 2. Timeline (ET)

| When | Event | Evidence |
|---|---|---|
| 10-06 / 10-07 | The operator enters SPCX stops at Schwab. The taxable buy and its 3 stops have consecutive order ids (a manual multi-leg ticket). The rollover IRA ends up with 5 SPCX stops, about 1,900 shares, against about 600 held | Schwab order ids; `alert_events` stop_health payloads; WS8-02 |
| 10-14 13:50, 14:00, 14:10 | NEAR_TRIGGER "about to fire" → `Suppressed (P1_DIGEST)`. `classify_alert` asked `operator_alert_policy_v2.route_event` first | WS3-03; `operator_alert_policy_v2.py:170-171` |
| 14:24–14:39 | Fills land between two position-sync runs: taxable order `#1008189857145` at 14:36:16 (~200 sh), rollover IRA order `#1008210666580` at 14:38:19 (~600 sh), both ~$151.5 | Schwab transactions; OPS_READINESS §2 |
| 14:37, 14:40, 14:52 | "resized 800->600", "CRITICAL STOP ALERT · 2" and "closed 600->0" are all suppressed | WS3-03, WS3-09 |
| ~14:40 | The operator reports 600 SPCX sold "with no stop" and halts everything | operator, in session |
| 14:45 | First page: the SIEM backstop, about 21 minutes after the first fill | WS3-25 |
| 14:54 | The operator deactivates the Schwab developer app. Holdings and cash freeze, and the monitors go stale without saying so | WS8-03 |
| 16:03 | Disarm: pilot `armed=false`, the standing unlock cleared, `api_write_enabled=false` on all 3 Schwab accounts, **global kill switch ON** (16:03:44, reason "SPCX incident 2026-10-14"), the LMT synthetic stop cancelled | `GET /api/v2/execution/kill-switches`; `GET /api/v2/broker-orders/pilot/status` |
| 16:05 | Provenance closed: the host never placed the SPCX orders | `schwab_pilot_orders` 0 SPCX rows (operator-run query) |
| afternoon | 15 Schwab cron lines paused (`# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX)`, packet `schwab-pause-cron-20261014`, `rollback.sh`) | crontab |
| 18:11 | Operator containment: a `config-write` grant script (grants `96a0ab8c`, `d3a80ca0`) edits the served release's `config/health_agent_policy.json` in place, removing the stop-supervisor `--apply` remediation | gap assessment §6.1 |
| evening | coder_dispatch autolaunch cron L558 paused (WS7-02, grant `a67b8f21`; crontab sha256 `69d544ef…`). Vite preview servers stopped. The operator declines key rotation for now | crontab line 558 |
| evening | Release 3e9dc5e14 served: #1732, #1733 and #1735 (report_only) | build-meta at the time |
| 10-15 00:24Z (20:24 ET) | **Release 5aa61048d served**: adds #1734 (trading lock, LOCKED) and #1737 (health agent: no broker remediation), plus Builds 1 and 2 | `GET /v3/build-meta.json` `git_sha 5aa61048de4a…` |

| 10-15 | 3 more Schwab lines paused under grant `0f9de907`: position sync (L501), econfirm (L784), instrument sweep (L896) | crontab prefix `# PAUSED 2026-10-15 … grant 0f9de907` |
| 10-16 18:30 | The operator reactivates the Schwab app; `config/schwab_access_mode.yaml` → `mode: read_only`. `resume_schwab_journal_cron.sh` un-pauses only the 2 ledger/journal lines (L457/L458). 13 of the 15 lines from 10-14 stay paused | served `config/schwab_access_mode.yaml`; `~/n8n-maturity-verification/resume_schwab_journal_cron.sh` |
| 10-16 → 10-22 | Holdings drift: the Schwab rows in holdings.json refresh only on a manual `broker_read_sync` run (10-16 18:02, 10-22 11:10). The positions proof ledger stops at 10-13 ("day 1 of 10"); `stops.json` keeps 7 broker-sourced entries frozen from 10-14. The lane registry says ACTIVE for every paused line | `schwab_sync_history`; `positions_proof_ledger.jsonl`; `config/lane_registry.json` (before PR "ops(incident-SPCX)") |
| 10-22 12:30 | Order read used as the stop inventory (item #27, §7): no working SPCX stop; no working stop larger than the shares held | `stop_lifecycle` snapshot 12:30 ET; `stop_health_last.json` |
| 10-22 | Operator approves the resume packet, the registry truth PR, the double-run fixes and this close-out ("yes", 4 items). Kill switch stays ON | `docs/ops/packets/incident-spcx-resume-20261022/` |

Detection took about 8 minutes on the host's internal signal. The operator was told about 21 minutes after the
first fill, and only by the backstop.

## 3. Root cause

1. **Primary: stop-firing alerts were digested.** The stop pattern was checked after the v2 router, and the
   router classified the alerts as P1_DIGEST. Fills and position changes also appear only as suppressed info
   (WS3-09, still open).
2. **Contributing: manual resting stops at Schwab that the host did not know about.** There is no inventory of
   broker orders against host intent, so "who placed this order?" cannot be answered from the host (WS8-02). The
   rollover IRA held stops for about 3× the shares held.
3. **Contributing: the containment step itself blinded the platform.** With the app off, monitors went stale
   without saying so (WS8-03). #1733 now makes this loud.
4. **Not a cause:** compromise. No host order POST, no change to MFA since 10-01. Approval has been single-factor
   since 06-15 (`REQUIRED_CHANNELS=1`), which is a finding but not this incident's cause (MFA_INTEGRITY.md).

## 4. Containment (in force at 2026-10-15 02:35Z)

| Control | State | Check |
|---|---|---|
| Schwab developer app | deactivated (operator) | Schwab dev portal |
| Schwab access mode | `forbidden` | `config/schwab_access_mode.yaml` (served) |
| Global kill switch | **ON** since 16:03:44 ET | `GET /api/v2/execution/kill-switches` → `active: [global]` |
| Pilot | disarmed: `armed: false`; `api_write_enabled` false ×3; `canary_session_date 2099-12-31` (inert while disarmed) | `GET /api/v2/broker-orders/pilot/status` |
| Read-only trading lock (#1734) | **LOCKED**; no unlock file | `trading_lock.status()` |
| Schwab cron | 15 lines paused. 3 lines that name Schwab are still active: the position sync every 15 min in market hours, the 18:35 econfirm and the Saturday instrument sweep. With `mode: forbidden` they fail loud | `crontab -l \| grep -i schwab` |
| coder_dispatch autolaunch | paused (L558) | crontab |
| Health-agent broker remediation | removed. Served by #1737 in 5aa61048d; the in-place edit is superseded | served `config/health_agent_policy.json` = origin/main |

## 5. Fixes

| Fix | PR | Status |
|---|---|---|
| Stop-firing alerts → P0, before the v2 router; ops-exempt from the daily P0 budget | #1732 | **LIVE @5aa61048d** |
| Schwab paused → fail loud (stop data UNAVAILABLE = P1, cache-not-live labels) | #1733 | **LIVE @5aa61048d** |
| Read-only trading lock (place/replace/cancel blocked without an operator unlock file) | #1734 | **LIVE @5aa61048d, LOCKED** |
| CC Tailscale identity auth; secret writes 403; 42 step-up routes refused | #1735 | **LIVE (code), report_only (runtime)**; operator packet not run |
| Health agent never remediates broker-adjacent units | #1737 | **LIVE @5aa61048d** |
| Incident runbook (severity, roles, record, containment by class) | docs-refresh branch | **BRANCH-ONLY** (`docs/runbooks/INCIDENT_RESPONSE.md`) |

## 6. Open items

| Item | Owner | Tracker row |
|---|---|---|
| Check every Schwab account for leftover SPCX stops (the rollover IRA had 5 stops for ~1,900 sh against ~600 held); cancel or keep on purpose; record the result here | operator | [`PROGRAM_TRACKER_20261015.md`](../implementation/n8n-maturity/PROGRAM_TRACKER_20261015.md) #27 |
| Remove `BROKER_LIVE_ENABLED` (still `true` in the rendered env `/run/user/1000/tradeai/env`; the DB control is false) | operator (config-write) | #28 |
| Run the CC auth packet; flip `report_only` off | operator | #22 |
| Fills and position changes page (WS3-09) | agent (PR) | gap assessment §5.2 |
| Foreign-order detector: broker orders vs host intent (WS8-02) | agent (PR, R4) | #32 |
| Schwab re-enable R0–R6 (`WS10_SCHWAB_INTEGRATION.md`) | operator gates; agent builds R1 | #32 |
| Key rotation (declined for now) | operator | #26 |
| Postmortem (detection time, what should have paged, one action per cause) within 3 days of RESOLVED | operator + agent | DRAFT: [`POSTMORTEM_20261014_SPCX.md`](POSTMORTEM_20261014_SPCX.md) |
| Resume the 13 read/report lines still paused (operator script, dry runs first) | operator | `docs/ops/packets/incident-spcx-resume-20261022/resume-operator.sh` |

## 7. Item #27 — the stop inventory, recorded 2026-10-22

*Recorded 2026-10-22 by an agent (read-only). This is the host's own read of Schwab orders, not the operator's
account check; the operator's check is still open (criterion 1).*

| Field | Value |
|---|---|
| Source | Postgres `stop_lifecycle`, the snapshot written by `scripts/stop_lifecycle_monitor.py` `scan()` from its Schwab working-order read (GET only), snapshot of **2026-10-22 12:30 ET**. The table holds only the latest scan, so the 12:30 rows are superseded by later scans |
| Measured by | the incident-pause review of 2026-10-22 ~12:00–12:35 ET (read-only; no broker call by the agent) |
| Rows | 86 stop rows. 3 in a `working` state and 1 `awaiting_stop_condition` |
| SPCX | 8 SPCX rows, **all filled, replaced or closed. No working SPCX stop in any Schwab account** |
| Over-coverage | **No working stop exceeds the held quantity** (held quantity from holdings.json, whose Schwab rows were refreshed by the `broker_read_sync` apply run at 11:10 ET, receipt `data/runtime/broker_read_sync/broker_read_sync_20261022T151024070113Z_apply.json`) |
| Corroboration | `<persistent-state>/data/runtime/stop_health_last.json` (`StopHealthRun@v1`): `status ok`, `schwab_stops: ok`, `stops 86`, `telegram_fired []`, `ok_at 2026-10-22T16:50:04Z` (12:50 ET), re-read by the agent at 12:57 ET |
| Re-run (operator) | `SELECT account, symbol, status, qty, held_qty, lifecycle FROM stop_lifecycle WHERE symbol='SPCX' OR (status ILIKE '%working%' AND qty > held_qty);` — expect 0 working SPCX rows and 0 over-covered rows |
| Caveats | `stops.json` still holds 7 broker-sourced entries frozen from 10-14 (BAH, DT, NFLX, SPCX×2, V, ZETA) until `broker_stop_reconcile` (L794) resumes; those can read as phantom protection. The original 10-07 rollover IRA over-coverage (5 stops, ~1,900 sh against ~600 held) is gone from the working set |

## 8. Exit criteria, 2026-10-22

| # | Criterion | State | Evidence / owner |
|---|---|---|---|
| (1) | Every Schwab account's working orders inventoried by the operator; leftover SPCX stops cancelled or kept on purpose | **OPEN — host evidence clean, operator check pending** | §7 above (host read). Operator: check each Schwab account in Schwab itself and record the result as a row here |
| (2) | Every stop-firing alert pages (P0) | **MET** | #1732 LIVE |
| (3) | Schwab paused state is loud | **MET** | #1733 LIVE |
| (4) | No place/replace/cancel without an operator unlock | **MET, still LOCKED** | #1734 LIVE; no unlock file (2026-10-22) |
| (5) | `BROKER_LIVE_ENABLED` removed | **UNVERIFIED — operator to confirm** | last known `true` (10-15) in the rendered env; an agent may not read the env file (§24.7). Operator: confirm removal and record it here |
| (6) | Postmortem written | **DRAFT** | [`POSTMORTEM_20261014_SPCX.md`](POSTMORTEM_20261014_SPCX.md); final within 3 days of RESOLVED |

Status stays **CONTAINED** until (1), (5) and (6) close. The global kill switch stays **ON** (operator decision
2026-10-22); clearing it belongs to the `read_only → write_bounded` transition (ADR-WS10-01 §2.3), not to RESOLVED.
