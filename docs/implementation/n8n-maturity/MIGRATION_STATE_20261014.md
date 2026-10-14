# Cron → n8n migration state — 2026-10-14

```
Status:      ACTIVE
as_of:       2026-10-14T11:39:32-04:00 (G1 inventory summary 15:39:32Z, final); matrix verdicts 2026-10-14T11:06:00-04:00
Measured at: CURRENT 8ae8a5b91-main-exact-phase2-20261013-234427 (both evidence sets); origin/main 964467594
             (#1722, #1723, #1724 merged 11:36 ET; not yet released); written on branch docs/n8n-migration-state-20261014
             (stacked on PR #1725 at 73eebc5c1; #1725 head is now 1cdcdc7e3, a chokepoint-exemption commit)
Owner:       platform (n8n maturity program); Agent Group 4 (documentation and governance) wrote it
Policy:      AGENTS.md §23. Cutover standard: operator ruling 2026-10-14 ~11:05 ET, recorded as AGENTS.md 8.0.0 §23.21
             (PROPOSED, awaiting APPROVE_AGENTS_POLICY_8_0_0)
```

Evidence tags (AGENTS.md §4): **[M]** measured by the named file's producer at its `as_of`, not re-run here ·
**[DOC]** another program document · **[I]** inferred. Nothing in this file was measured by its author: every number
is copied from the evidence files named in §8, which a reader can re-open.

This replaces no live tracker. The living scoreboard stays `~/n8n-maturity-verification/ROADMAP.md` §0; the
per-lane truth is the evidence matrix (§8). This file is the in-repo snapshot that the migration documents link to.

## 1. The standard in force

Operator ruling 2026-10-14 ~11:05 ET, verbatim: *"new standards apply when i say so fix and dry and regression
testing, yes it should run live successful to many road blocks to testing"*. A lane cuts over when:

1. **the defect that held it is fixed** (merged and served from CURRENT);
2. **its n8n dry run passes** — the latest `dry_run` fire is `RUN_DONE`, any earlier failure is followed by a clean
   fire; a forced fire counts, no natural shadow slot is needed;
3. **its lane regression tests pass** under `TRADE_AI_CI=1`;
4. **it has at least one successful `live` n8n run with the cron line still present under the shared lock** — a
   forced live relay fire counts when the lane's window allows it (market-hours lanes fire in-window).

Removed: every multi-day soak, including §23.3's three clean market days for `trade-ai-scalp-live` and the natural
shadow slot of onboarding step 8. Unchanged: §23.14 never-eligible lanes, comment-not-delete, one `cron` grant per
wave naming every lane, rollback per line. Procedure: [`RUNBOOK_CUTOVER_ROLLBACK.md`](RUNBOOK_CUTOVER_ROLLBACK.md).

**Policy state.** AGENTS.md 8.0.0 (§23.21) records the ruling and is **PROPOSED**. Until the operator gives
`APPROVE_AGENTS_POLICY_8_0_0 <pr> <sha>` and it merges, the ACTIVE text of §23.3 / §23.14 still states the
`trade-ai-scalp-live` 3-day fallback. The operator's word "apply when i say so" is the operator's decision; the
ratification token makes the policy file agree with it. Retiring the `trade-ai-scalp-live` cron line is the one step
that should wait for the token, because it is the one lane whose soak is written into ACTIVE §23.3 and §23.14.

## 2. Counts

**G1 inventory, 11:39 ET, final [M]** (`status-20261014-p1/summary.json`; every host-discovered unit):

| Measure | Value |
|---|---|
| Discovered scheduled units | **524** — cron 413, systemd timer 82, systemd service 18, n8n-native 6, cron retired by n8n cutover 5 |
| Migrated (n8n is scheduler of record) | **6** |
| Validated (≥ 1 live `RUN_DONE`) | **7** (the 6 above + `momentum-cache-reconcile`) |
| Needs refactor / needs development | **165** / **306** (237 excluding lanes that only need the canary PR) |
| Awaiting n8n validation | **366** |
| Ready for cutover now (all four criteria met) | **0** — every shadow cron lane has allowlist `live_arg` null, so a live fire needs the canary PR plus the relay live list (`config-write`) |
| Remaining | **518** (367 in migration scope) |
| Stays on cron / systemd (never eligible) | **151** |
| Remaining in migration scope | **367** |
| Blocked | **208** — never-eligible 151; registry RETIRED/superseded but line still active 49; registry ACTIVE but timer disabled 7; relay live-lane list missing 1 |
| Registry dispatch rows / allowlist entries | 78 / 94 |
| Ledger | 7,049 receipts on 104 lanes — live `RUN_DONE` 3,872, `RUN_FAILED` 1, `RUN_TIMEOUT` 8, `RUN_SKIPPED_LOCK` 3; dry_run `RUN_DONE` 3,101, `RUN_FAILED` 39, `RUN_TIMEOUT` 3, `RUN_SKIPPED_LOCK` 22 |
| Host crontab | 413 active job lines; 66 commented; 5 `RETIRED … n8n-cutover` |

**Buckets** (same file): `MIGRATED_VALIDATED` 6 · `SHADOW_AWAITING_EVIDENCE` 42 · `NEEDS_TESTING` 10 ·
`NEEDS_REFACTOR` 28 · `NEEDS_DEVELOPMENT` 4 · `NOT_ONBOARDED` 226 · `BLOCKED` 208. Cutover readiness: needs live fire
39, needs in-window live fire 3, not ready 325, never 151, cut over 6.

**Matrix verdicts, 11:06 ET [M]** (`status-20261014-1130/MIGRATION_STATUS.md`; 469 ACTIVE registry lanes + 2 in
open PRs):

| Verdict | Lanes |
|---|---|
| CUT OVER | 6 |
| CANARY-READY (needs one forced live fire with cron present) | 61 — tier A 21, tier B 40 |
| IN SHADOW, needs evidence | 18 |
| NOT ONBOARDED (eligible, no dispatch row) | 229 |
| STAYS ON CRON / SYSTEMD (justified) | 157 |

The two sets differ because they count different things: the matrix counts registry lanes, the G1 inventory counts
host-discovered scheduler units (a lane can own several lines, and 49 lines still run for registry rows marked
RETIRED). Neither number is wrong; quote the one whose denominator you mean. **[I]**

**Corrections and notes to the G1 inventory [M]:**

- **`run-protection-pipeline` is not obsolete.** G1's `duplicates_obsolete.md` calls both lines
  (`run-protection-pipeline-at-x-30-9-16`, `-at-30-20`) obsolete because `logs/protection_pipeline_cron.log` was last
  written 2026-10-02. That is the wrong log: the job writes the dev-tree `logs/protection_pipeline.log`
  (`~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/logs/protection_pipeline.log`, last written 2026-10-14 11:33 ET). It
  is live; it stays on cron as a `market_day_gate` pipeline-excluded row, not as obsolete.
- **P3: 49 live crontab lines sit under registry rows marked RETIRED** — pending the premarket C1 manifest flip and
  the five B-family installs, neither applied on the host. They are not migration debt to fix by hand; they close when
  those packets are installed under their `cron` grants.
- **16 of the 61 canary-ready lanes fail the canary lock rule** (cron line with no `flock`, `safe_flock`-only, or
  allowlist `lock_kind` `safe_flock`) and cannot take the live fire until the lock is made equal (§23.12).
- `momentum-cache-reconcile` is back in shadow (the relay refused live); 7 ACTIVE registry rows point at disabled
  timers.

## 3. Cut over (n8n is the only scheduler) — 6

| Lane | Cron line | Cut over | Live `RUN_DONE` (11:39 ET) |
|---|---|---|---|
| `n8n-pilot-dispatch` | `# RETIRED … n8n-cutover` | 2026-10-09 | 531 |
| `n8n-incident-fanin` | `# RETIRED … n8n-cutover` | 2026-10-09 | 1,597 |
| `n8n-research-intake-consumer` | `# RETIRED … n8n-cutover` | 2026-10-09 | 535 |
| `crontab-snapshot-for-health-agent` | `# RETIRED … n8n-cutover` | 2026-10-09 | 419 |
| `research-insight-extractor` | `# RETIRED 2026-10-13 n8n-cutover research-insight-extractor` (operator apply 17:56 ET) | 2026-10-13 | 7 |
| `heartbeat-watch` | none (n8n-native) | n8n-only from activation | 782 |

Registry drift: `heartbeat-watch` still reads `stage: canary` although n8n is its only scheduler — the row should be
flipped to `cutover` by registry PR. Non-DONE runs on `n8n-pilot-dispatch` and `n8n-incident-fanin` are
`executor_lost` timeouts on 10-13 and one `exit_1` at 12:40Z on 10-14; every later run is clean. **[M]**

## 4. The canary wave

**Tier A — 21 lanes in the canary PR** (≥ 5 clean dry runs, 0 failures): `job-coverage-monitor`,
`hermes-pipeline-health`, `identity-sweep-stage0`, `material-change-detector-stage1`, `document-mentions-backfill`,
`resolve-due-checkpoints`, `agent-number-grounding-slo`, `trade-ai-scalp-live`, `hermes-entity-spike-discovery`,
`data-gap-resolver-at-0-10-16`, `hermes-analyst-signal-discovery`, `news-to-catalyst`, `hermes-news-bridge`,
`aegis-social-sentiment`, `finviz-proactive-research`, `hermes-research-worker-pool`, `finviz-sector-research`,
`proposal-backtest-engine`, `hermes-scope-governor`, `hermes-score-event-feeder`, `momentum-cache-reconcile`.

Every canary-ready lane first needs the canary PR (allowlist `live_arg` set, `stage: canary`, `dispatch.mode: live`) and the relay live list; "canary-ready" means only that the dry run passes.

**Tier B — 40 lanes** whose dry run passes with fewer than 5 runs or an earlier failure since fixed; the list is in
`MIGRATION_STATUS.md` "Canary-ready".

Before each lane's live fire: (a) the cron `flock` equals the allowlist lock, (b) the lane regression tests are green
(criterion 3 — G3's run is under `status-20261014-p1/testing/evidence/`: 194 runs, 185 `rc=0`; the non-zero ones
are `test_fundamentals_freshness`, `test_hermes_governance_api` (rc 5, no tests collected), `test_hermes_outcome_feedback`,
`test_hermes_threshold_learning` and three `test_screener_arch*` files, listed in `run_index.txt`; a lane whose tests
are among them is not cutover-ready), (c) window-bound lanes fire between 09:30 and 16:00 ET on a
trading day. Window-bound: `catalyst-symbol-impact`, `watch-goods-consistency`, `watchlist-enrichment-sweep`,
`hermes-momentum-catalyst-scalp`, `trade-ai-scalp-live`, `materialize-watchlist-strategy-cards`,
`hermes-governance-api`, `data-gap-resolver-at-0-10-16`, `signal-fusion-full`, `signal-fusion-active`,
`aegis-social-sentiment`, `sync-social-to-intelligence`, `hermes-social-sentiment`, `finviz-proactive-research`,
`finviz-sector-research`, `finviz-market-movers`. `trade-ai-scalp-live`'s canary is pre-staged in PR #1726
(`flip_scalp_canary.py`), not applied. **[M]/[DOC]**

**Cutover list for 2026-10-14/15:** every tier A lane with a clean live `RUN_DONE` under the shared lock, then
tier B, each under the wave's `cron` grant naming it. G1 proposes 59 lanes for today and 29 for tomorrow
(`summary.json` `by_est_completion`; proposals, not decisions).

## 5. In shadow, needs evidence — 18

Seven are held by the 7.0.0 sender-reach baseline (PR #1725, shrink-only; fix the reach or drop from the wave):
`finviz-health-check`, `crawl-v3-dashboard`, `audit-enrichment-coverage`, `watchlist-enrichment-sweep`,
`journal-tilt-morning-hook`, `catalyst-momentum-engine-overnight`, `aegis-evening-packet`. Seven have not run clean
since the 2026-10-12 07:50–13:00Z `exit_73` incident (re-fire their dry runs): `finviz-market-movers`,
`hermes-momentum-catalyst-scalp`, `hermes-governance-api`, `signal-fusion-active`,
`materialize-watchlist-strategy-cards`, `maturity-remeasure`, `fee-efficiency-analyzer`. Four have never fired:
`agent-outcome-scorer`, `etf-analyst-enrich`, `etf-performance-enrich`, `validate-expense-ratios`. **[M]**

## 6. Never eligible — why they stay on cron or systemd

Matrix justification, 157 lanes **[M]**:

| Justification | Lanes |
|---|---|
| `KEEP_ON_CRON` review verdict (broker / stop / order / daemon class, DOF SQL, operator decision) | 66 |
| §23.14 broker / order / position / paper | 39 |
| systemd daemon, or a watchdog of n8n itself | 19 |
| `market_day_gate` pipeline-excluded rows | 13 |
| §23.14 secret / guard / release-deploy | 8 |
| event / on-demand trigger (no timer to migrate) | 5 |
| §23.14 sender | 4 |
| account read — §23.20 (7.0.0, PROPOSED in #1725) condition (a) fails (`finviz-momentum-scalp-early-lane`, `momentum-scalp-advisory-alerts`) | 2 |
| other never-eligible §23.14 | 1 |

The rule is AGENTS.md §23.14: a stolen relay bearer must not be able to place an order, render a secret or start a
second copy of a long-running process, so broker, order, secret and daemon lanes stay on the host scheduler, and n8n
only *watches* them through `heartbeat-watch`. The 8.0.0 ruling does not touch this list. Eligibility was computed with
the served `lane_dispatch.dispatch_eligible()`. The two account-read lanes return when their sizing read moves behind a
data-broker projection. G1's inventory counts 151 never-eligible host units by the same rule.

## 7. Risks and open items

1. **Executor capacity** — 3 workers; PR #1726 raises class caps (ingest 2, global 4) but the effective limit stays 3
   until the executor drop-in sets `WORKERS=4` (`config-write` grant). A 61-lane wave will queue.
2. **Window-bound lanes** need in-window live proof; a fire outside market hours proves nothing for them.
3. **`trade-ai-scalp-live`** — see §1 "Policy state"; the canary is staged in #1726, not applied.
4. **Code still encodes the old standard [M]:** `scripts/n8n_cutover_checklist.py` (read-only reporter, not called by
   `_cutover.py`) refuses a manual or forced fire as shadow/canary evidence (`DRIFT: manual/event fire cannot substitute
   for a natural schedule`, `NOT_MEASURED: distinct first-attempt natural schedule slot required`). Under §23.21 its
   verdicts for forced fires are stale; a follow-up code PR should accept a forced `dry_run` and a forced in-window
   `live` fire. Until then do not read its `NOT_MEASURED` as a cutover blocker.
5. **Registry drift** — `heartbeat-watch` at stage canary (§3); `lane-governance-packet-weekly` NEVER_SCHEDULED with one
   dry run; 49 host lines still active for registry rows marked RETIRED (G1).

## 8. Evidence

| Evidence | Path |
|---|---|
| Migration status + per-lane matrix (11:06 ET) | `~/n8n-maturity-verification/status-20261014-1130/MIGRATION_STATUS.md`, `migration_matrix.csv` (536 rows) |
| G1 inventory (11:39 ET, final) | `~/n8n-maturity-verification/status-20261014-p1/summary.json`, `inventory.csv` (524 rows), `duplicates_obsolete.md`, `doc_drift.md` |
| G3 lane regression tests | `~/n8n-maturity-verification/status-20261014-p1/testing/evidence/` (`run_index.txt`, `pytest/`, `junit/`) |
| Coordination ledger | `~/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite` (`mode=ro`) |
| Cutover receipts | `$TRADEAI_STATE_ROOT/data/runtime/n8n_cutover/` |
| Change record | `~/n8n-maturity-verification/REMEDIATION_PLAN.md` §9; scoreboard `ROADMAP.md` §0 |
| Architecture | [`N8N_RUNTIME_ARCHITECTURE.md`](N8N_RUNTIME_ARCHITECTURE.md) |

## 9. Documents corrected with this snapshot

`MIGRATION_RECONCILIATION_20261012.md` (natural-slot-only proof and "additional cutover BLOCKED"),
`cron-inventory/REMEDIATION_PLAN.md` ("operator freeze in force"), `00-MASTER-PROGRAM.md` (governing AGENTS version),
`N8N_ONBOARDING_STANDARD.md` (step 8 natural slot as the gate; steps 9, 10, 12), `03-momentum-scalp-lanes.md` §6
(3 clean market days, 2 clean RTH days), `N8N_CONFIGURATION.md` (policy line, freeze, scalp exception). Each keeps
its history and says what changed at the top.
