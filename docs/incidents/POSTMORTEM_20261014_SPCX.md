# Postmortem — INC-20261014-SPCX: resting Schwab stops filled; the stop alerts were digested

```
Status:      DRAFT (agent draft for operator review; becomes ACTIVE when the operator signs it off at RESOLVED)
as_of:       2026-10-22T13:00-04:00
Measured at: e8ce6e913 (origin/main) / served CURRENT 82180caba-main-exact-phase2-20261022-110850; host reads 2026-10-22
Incident:    docs/incidents/INCIDENT_20261014_SPCX_RESTING_STOPS.md (the record; this file adds no new facts about
             10-14 and cites it for every one)
Format:      docs/runbooks/INCIDENT_RESPONSE.md §7 (timeline, detection time, containment time, root causes, what
             alerted and what should have, one tracked action per cause)
```

Blameless. The stops did what stops do. Most of what went wrong after the fills was the platform's own doing:
the alert routing, then how containment was left in place.

## 1. Impact

- About 800 SPCX shares were sold at about $151.5 by stops the operator had placed at Schwab on 10-06/10-07:
  - about 200 shares in `schwab_taxable` at 14:36:16 ET;
  - about 600 shares in `schwab_rollover_ira` at 14:38:19 ET.
  `[VERIFIED]` incident record §1–2 (Schwab order ids, stop_health payloads).
- The operator learned of it from a SIEM backstop page at 14:45, 9 minutes after the first fill order (14:36) and
  about 21 minutes after the start of the fill window the record uses (14:24). He asked "hacked / who sold it?". The host could not answer from its own logs. `[VERIFIED]` record §2 (14:45).
- Read-side damage from containment: for **8 days** (10-14 to 10-22) 13 read/report cron lines stayed paused after the
  Schwab app was reactivated on 10-16. Holdings drifted and the positions proof stalled (§4). `[VERIFIED]` crontab
  `# PAUSED` prefixes; `schwab_sync_history`; `positions_proof_ledger.jsonl`.
- No order was placed, replaced or cancelled by the host. No compromise was found. `[VERIFIED]` record §2 16:05 and §3.4.

## 2. Timeline (ET)

Condensed from the record §2. Each line carries its evidence there.

| When | Event |
|---|---|
| 10-06 / 10-07 | The operator places SPCX stops at Schwab by hand. The rollover IRA ends up with 5 stops for about 1,900 sh against about 600 held |
| 10-14 13:50 | **First host signal**: `stop_health_check` NEAR_TRIGGER, routed `Suppressed (P1_DIGEST)` |
| 14:36 / 14:38 | The two fills |
| 14:40 | "CRITICAL STOP ALERT · 2" suppressed. The operator notices on his own and halts everything |
| 14:45 | **First page** (SIEM backstop) |
| 14:54 | The operator deactivates the Schwab app. The monitors go stale without saying so |
| 16:03 | **Contained**: pilot disarmed, `api_write_enabled=false` ×3, global kill switch ON |
| 16:05 | Provenance closed: the host never placed the SPCX orders |
| afternoon / 10-15 | 15 + 3 Schwab cron lines paused, coder_dispatch paused |
| 10-15 00:24Z | Release 5aa61048d: #1732 (stop alerts page P0), #1733 (paused = loud), #1734 (trading lock), #1737 |
| 10-16 18:30 | Schwab app back on, `mode: read_only`. Only the 2 journal lines are resumed |
| 10-16 → 10-22 | Every other paused read line stays off. The registry says ACTIVE for all of them |
| 10-22 12:30 | The host's order read records no working SPCX stop and no over-covered stop (record §7, item #27) |
| 10-22 | The operator approves the resume packet, registry truth, double-run fixes and this draft |

## 3. Detection and containment times

| Measure | Value | Basis |
|---|---|---|
| First host signal → first fill | 46 min (13:50 → 14:36) | record §2 |
| First fill → host's internal alert | about 4 min (14:36 → 14:40, suppressed) | record §2 |
| First fill → operator told by a page | **9 min** from the 14:36 fill order; **about 21 min** from 14:24, the start of the fill window the record uses | record §2 |
| First fill → contained | about 1 h 27 min (14:36 → 16:03) | record §2 |
| Containment → reads restored by schedule | **not yet**; 8 days and counting on 10-22 | crontab, this review |

## 4. Root causes

1. **Primary: stop-firing alerts were digested.** Stop patterns were checked after the v2 router, which classed them
   P1_DIGEST. 48 stop_health events went unsent. `[VERIFIED]` record §3.1 (WS3-03, `operator_alert_policy_v2.py:170-171`).
2. **Contributing: resting stops the host did not know about.** There is no inventory of broker orders against host
   intent (WS8-02), and the rollover IRA held stops for about 3× its shares. `[VERIFIED]` record §3.2.
3. **Contributing: containment blinded the platform.** With the app off, monitors went stale silently (WS8-03).
   `[VERIFIED]` record §3.3. Fixed by #1733.
4. **Contributing, after the fact: containment had no exit.** The 10-14 pause packet recorded how to pause and roll
   back, but no condition for resuming and no owner. When the app came back read-only on 10-16, only the 2 journal
   lines were resumed. The other 13 read lines stayed off for 8 days. Nothing reported it, because the lane registry
   still said ACTIVE for every paused line and no checker compared a declared-ACTIVE cron row with a commented line.
   `[VERIFIED]` crontab; registry before this PR; `check_registry_runtime_truth.py` codes on main (no such rule) —
   the rule is added by PR #1927 (`ACTIVE_CRON_LINE_ABSENT`).
5. **Not a cause:** compromise (no host order POST; MFA unchanged since 10-01). `[VERIFIED]` record §3.4.

## 5. What worked

- **The stops.** They protected the position as the operator designed them to.
- **The SIEM backstop paged**, if late. It was the only signal that reached the operator.
- **Provenance** was established within about 90 minutes, from `schwab_pilot_orders` and Schwab's own records.
- **Write-side containment held.** Trading lock LOCKED (#1734), kill switch ON, pilot disarmed. No write path was
  exercised in 8 days, and the 2026-10-22 review re-confirmed the lock.
- **The fixes shipped fast.** #1732, #1733, #1734 and #1737 were served within about 10 hours (5aa61048d).
- **Read-only recovery had a governed path.** The §24.11 `broker-read` grant let `broker_read_sync.sh` refresh
  positions by hand (10-16 18:02, 10-22 11:10) without touching any write path.

## 6. What did not work

- **Alert routing let the router decide a stop fill was digest material** (cause 1).
- **The host had no answer to "who placed this order?"** (cause 2).
- **The paused jobs were left off for 8 days.** This caused the holdings drift:
  - **Positions.** `schwab_position_sync` (L501) did not run on its 15-minute cadence after 10-14 14:52. Schwab
    rows in holdings.json changed only on two manual runs (10-16 18:02, 10-22 11:10). Every desk that reads
    holdings saw positions up to 6 days old.
  - **Basis.** The basis self-heal and basis-drift alarm (L468/L469) were off, so the repricer's known reversion
    went unchecked.
  - **Positions proof.** The 10-day proof (L1036/L1038) stopped at "day 1 of 10" on 10-13. Positions phase 2 → 3
    stalled for 7 trading days and restarts at day 1.
  - **Stops.** `broker_stop_reconcile` (L794) was off, so `stops.json` kept 7 broker entries frozen from 10-14,
    two of them SPCX stops that no longer exist (possible phantom protection on the surfaces that read it).
  - **Fill confirmations.** `econfirm` (L784) was off. The 10-14 SPCX confirms now fall outside its 7-day window and
    need a 10-day backfill check.
- **The registry hid the outage.** 16 rows said ACTIVE while their lines were commented (§3 of the 2026-10-22
  review). The review also counted 7 disabled timers as stale rows. That was a misreading, corrected here: those rows
  already carry `status DISABLED_UNRULED, operator_decision_pending`, the registry's deliberate "found off, not yet
  ruled" shape.
- **Double runs went unnoticed.** Eight lanes on both cron and the n8n live list had no effect-claim wrapper.
  Five of them really ran twice in one slot (sync_social_to_intelligence 9 slots, materialize cards 33 slots,
  hermes_discovery_scorecard 3 days, opening_intelligence 10-22 with a duplicate jsonl row, job_coverage_monitor
  10-21 20:30). Not caused by the incident; found by the same review.
- **The record went stale.** The incident file was not edited from 10-15 to 10-22. Item #27 and exit criteria (1)
  and (5) had no recorded state.

## 7. Action items (one per cause; owner; tracker)

| # | Cause | Action | Owner | Tracker / state |
|---|---|---|---|---|
| A1 | 1 | Stop-firing alerts → P0 before the router, ops-exempt from the P0 budget | agent | #1732 **LIVE** |
| A2 | 1 | Fills and position changes page (WS3-09) | agent (PR) | gap assessment §5.2; **open** |
| A3 | 2 | Foreign-order detector: broker orders vs host intent (WS8-02) | agent (PR, R4) | tracker #32; **open** |
| A4 | 2 | Operator's own check of every Schwab account for leftover SPCX stops; record in the incident §8 | operator | criterion (1); **open** (host read clean, §7) |
| A5 | 3 | Paused/stale broker data is loud | agent | #1733 **LIVE** |
| A6 | 3 | Remove `BROKER_LIVE_ENABLED` from the rendered env; confirm in the incident §8 | operator (config-write) | tracker #28; **unverified** |
| A7 | 4 | Resume the 13 read/report lines in order, each after its own dry run | operator | `docs/ops/packets/incident-spcx-resume-20261022/resume-operator.sh`; **ready, not run** |
| A8 | 4 | Registry says PAUSED for every paused line; flip back to ACTIVE as lines resume. The 7 disabled timers stay DISABLED_UNRULED pending the operator ruling | agent | PR "ops(incident-SPCX): resume packet, registry truth, double-run fixes, postmortem draft"; **in review** |
| A9 | 4 | A checker that flags ACTIVE cron rows whose line is commented, and off rows whose line runs | agent | PR #1927 (`ACTIVE_CRON_LINE_ABSENT`, `DECLARED_OFF_CRON_LINE_ACTIVE`); **in review** |
| A10 | 4 | Every future pause packet names its resume condition, owner and review date (pause = PAUSED row with `review_by`) | agent → AGENTS.md amendment | proposed (§20); **open** |
| A11 | double runs | Comment the 3 cron lines where n8n is proven (sync_social, materialize cards, hermes scorecard); maturity-remeasure off the live list; opening_intelligence gets a staged effect key in its cutover packet (it appends) | operator (crontab, live list) + agent (key PR) | `double-run-operator.sh`; maturity packet `maturity-remeasure-relay-live-removal-20261015`; opening_intelligence key **open** |
| A12 | 4 | Grok stop review registered with the LLM spend gate before it resumes | agent | same PR (`grok_stop_review` process, 12/run, 30/day); **in review** |
| A13 | — | Kill switch: stays ON until the `write_bounded` ADR gates exist (DB role split, per-order WebAuthn, cancel via kill switch, bounded arming, one-order canary) | operator | ADR-WS10-01 §2.3; **decision: keep ON** |
| A14 | — | Postmortem signed off and the incident moved to RESOLVED, then CLOSED | operator + agent | this file; **draft** |

## 8. Corrections and unknowns

- The record's 21-minute figure measures from 14:24, the start of the fill window, not from the first fill at
  14:36. Both are kept; §3 says which.
- The disable dates of the 4 agent-runtime timers are UNKNOWN (cron inventory: "date UNKNOWN"; never triggered since
  boot). They stay DISABLED_UNRULED; no reason is invented.
- The 10-22 plan said "wrap the unproven double-run lanes in the effect claim". The repo's effect-key process forbids
  arming a key at merge and keying overwrite-only lanes, so only the 3 proven lanes are fixed now (A11).
- The 12:30 ET order inventory is the host's read, not the operator's (criterion 1 stays open).
- `BROKER_LIVE_ENABLED` was not re-checked: an agent may not read the env file (§24.7).
