Status: PROPOSED (for operator/coordinator review — no detector is implemented here)
as_of: 2026-10-29T21:20:00Z
Measured at: monitor inventory of the served release `1e62905f8` + source reads of existing monitors
Canonical repo path: docs/ops/CIO_GO_LIVE_MONITORING_PROPOSAL_2026-10-29.md
Authority: read-only; proposals only, nothing implemented (`[CODE]` / `[VERIFIED]` where noted)
Supersedes: none
See also: docs/ops/CIO_GO_LIVE_RUNTIME_VERIFY_2026-10-29.md, docs/ops/CIO_GO_LIVE_OPERATOR_APPROVALS_2026-10-28.md (branch `wt/ops-watchdogs-20261028`)

# CIO go-live — monitoring proposal (2026-10-29)

For each of the five go-live items: what monitor (if any) already covers it, what **GAP** remains, and a
concrete minimal read-only detector that could slot into an existing monitor. **Nothing here is implemented** —
this is a proposal for operator/coordinator review, and any new detector lands as its own reviewed PR
(§17 for anything touching a scheduler/operator surface; §24 for a new lane row).

## The monitor inventory (existing, served release)

| monitor | what it is | receipt / output |
|---|---|---|
| `health-tick` | systemd timer `tradeai-health-tick.timer` (*:0/5) → `scripts/health_tick.py`; steps from `config/health_tick_steps.json` | `data/runtime/health_tick_last.json` (`HealthTickReceipt@v1`) |
| `cron_outage_watchdog` | `scripts/cron_outage_watchdog.py` — missed-runs over the lane registry + run ledger | `data/runtime/cron_outage_watchdog_latest.json`; feeds `jobs_health` |
| `pipeline_freshness_slo` | `scripts/pipeline_freshness_slo.py` — write-volume vs trailing baseline (also a `health-tick` step `pipeline-freshness-slo`) | stdout/Telegram; no durable per-check receipt today |
| `incident-supervisor` | `scripts/incident_supervisor.py` — LLM triage/fix over `IncidentRecord@v1` rows (reacts, does not detect) | `data/runtime/...` incident receipts |
| `supervisor-breach-detector` | `scripts/supervisor_breach_detector.py` (lane `supervisor-breach-detector`) | `data/runtime/supervisor_breach_detector_latest.json` |
| `jobs-health` `_watchers` | the stoplight strip (item 5) — **not on the served release** | `GET /api/v2/ops/jobs` `.watchers` |

---

## Item 1 — `cio_prospect` dual-write

**Covered today:** only by the writer's own receipt (`data/runtime/cio_prospect_writer_<caller>_last.json`), which
truthfully reports `pg.mode` / `pg.live` / `pg_upserted` / `pg_errors`. `jobs_health` lists the `cio-opportunity-curator`
and `cio-entry-state` **lanes** (missed runs), but nothing reads the receipt's `pg` block.

**GAP — the dual-write can fail open silently.** If `TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1` is dropped, the table is
dropped, or `pg_errors` climbs, the writer keeps writing jsonl and the receipt simply shows `pg.mode: "inert"` /
`"off"` (or a circuit-open) — **no alert fires**. Likewise no monitor reconciles that PG is actually receiving rows
(count), so a dual-write that is `live` but writing zero rows (e.g. the curator full pass never runs again) would
read healthy. The observed state underlines the first half: the curator receipt is stale and pre-flag
(`as_of 2026-10-28`, `flag:false`), yet nothing surfaced that.

**Proposed detector (read-only, slot into `health-tick` as a new step or into `cron_outage_watchdog` output):**
a `cio_prospect_dual_write_guard.py` that (1) reads the newest of the two writer receipts, (2) asserts
`as_of` within the lane's cadence window (entry-state ≤ 20 min on a market day, curator ≤ 2 h on a market day),
(3) asserts `pg.live == true` and `pg.mode == "dual_write"`, (4) asserts `pg_errors == 0` and no
`pg.circuit` open, and (5) emits one finding (`OK` / `INERT` / `STALE` / `PG_ERRORS`) instead of the dual-write
failing open. The row-count reconciliation (jsonl count vs `SELECT count(*) FROM cio_prospect`) is a **separate,
operator-only** DB read and should be an operator-run check, not an agent monitor (DB access is off-limits to agents).

---

## Item 2 — conflict engine

**Covered today:** nothing. The rulebook is `PROPOSED` / `live_enabled: false` on the served release; the shadow
lane was deferred; there is no `conflict-resolver_last.json` and no ledger. Once it lands, `jobs_health` would list
the `conflict-resolver` lane only if a registry row exists — which it does not yet.

**GAP — three silent failure modes:** (a) the rulebook is reverted to `PROPOSED`/`live_enabled:false` (a full revert
fails silently; only a *half*-flip raises in `load_rulebook`); (b) the shadow lane runs but writes no events (a
resolver that always finds "no conflicts" is indistinguishable from one that never collected inputs); (c) the lane is
never admitted/scheduled.

**Proposed detector (read-only):**
- A `conflict_rulebook_guard` that asserts `config/conflict_rulebook.json` `status == "APPROVED"` and
  `live_enabled == true` and `approval.approved_by == "operator"` — cheap, and catches a revert the engine itself
  will not raise on.
- A shadow-run check that reads `data/runtime/conflict-resolver_last.json` (fresh within the lane cadence,
  `status: "ok"`, `produced_count ≥ 0` but `findings_count`/`events_written` recorded) **and** compares
  `data/conflicts/conflict_events.jsonl` line count across runs — a non-growing ledger across N consecutive fresh
  receipts is a finding. Slot into `health-tick` or `supervisor-breach-detector`.

---

## Item 3 — pipeline-freshness SLO `hermes_score_snapshots_2h`

**Covered today:** the SLO is itself a `health-tick` step (`pipeline-freshness-slo`) plus its own cron line
(`15 7-17/2 * * 1-5`), so a step **crash** shows in `health_tick_last.json` `status: "unhealthy"`. The scorer lane
is listed in `jobs_health`.

**GAP — the SLO's own verdict is not durable.** The per-check OK/WARN/CRITICAL is only in the Telegram send and
stdout; there is no receipt a monitor can assert "the hermes check evaluated and returned OK (not WARN)" — so a
**baseline regression that reintroduces pre-market false-WARNs** (or that neutralizes the check entirely) is silent
unless someone reads the Telegram message. A check that silently stops evaluating (removed from `CHECKS`, or its
baseline rewritten back to `daily_median/12`) also passes green.

**Proposed detector (read-only):** extend `pipeline_freshness_slo.py` to persist its per-check verdicts to
`data/runtime/pipeline_freshness_slo_last.json` (`{check, verdict, value, baseline, as_of}`), and add a thin
`health-tick` step (or fold into the existing step) asserting the `hermes_score_snapshots_2h` verdict is present,
is not `ERROR`/`UNRUNNABLE`, and is `OK` during the pre-market windows where the old baseline false-fired. This is a
small, additive change to an existing script, not a new scheduler entry.

---

## Item 4 — Deploy console in-flight board

**Covered today:** none. The endpoint fails closed to `UNAVAILABLE` on gh failure (correct), but nothing asserts the
board is actually reachable and returning rows.

**GAP — silent UNAVAILABLE.** If the `gh` token expires or the subprocess path breaks, the board shows UNAVAILABLE
forever with no alert; it is a read-only surface, so no write-side monitor notices.

**Proposed detector (read-only):** a `health-tick` step (or the existing `system-health-agent`) that calls
`deploy_in_flight.build()` (or `curl /api/v2/ops/in-flight`) and asserts `status == "OK"`, `freshness == "OK"`, and
`count is not None` within the 60 s cache TTL; a finding when `UNAVAILABLE` persists across two consecutive checks.
No GitHub write, no new schedule.

---

## Item 5 — Watchers & alerts stoplight

**Covered today:** the strip *is* a monitor (of watcher lanes), but it is not on the served release, and its
`WATCHER_LANES` map is hardcoded to three lanes (`self-heal-fixer`, `pr-merge-telegram-notify`,
`delivery-failure-alerts`) plus `missed-run-watchdog`.

**GAP — the strip does not cover the go-live items.** Items 1/2/4 above have no watcher light, and the strip itself
isn't live yet.

**Proposed change (proposal only):** when the strip lands, extend `WATCHER_LANES` (or the equivalent table) with
`conflict-resolver` (shadow) and the new `cio_prospect_dual_write_guard` from item 1, so the stoplight carries a
green/amber/red for each go-live item. This keeps the "one strip, one place" property instead of scattering new
alarms.

---

## Cross-cutting note for the operator

- Every detector above is **read-only** and slots into an existing monitor (`health-tick`,
  `cron_outage_watchdog`, or the `jobs-health` strip) — none adds a scheduler entry on its own, so none is
  §17-scheduler-gated by itself. The one thing an agent **cannot** build is the row-count reconciliation
  (jsonl ↔ `cio_prospect`), because it needs the Postgres credential — that stays an operator-run check.
- Two of the five items (2 and 5) are not yet merged; their monitors cannot be built against the served release
  until `wt/ops-watchdogs-20261028` merges + deploys. Sequencing: merge those first, then land the detectors.
