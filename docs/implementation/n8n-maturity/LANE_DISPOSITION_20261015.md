# Lane disposition, 2026-10-15

One row per active crontab job line, plus one row per ACTIVE registry lane that no crontab line schedules. Every row
has exactly one disposition. The table is `LANE_DISPOSITION_20261015.csv` (beside this file).

The builder is `scripts/n8n_lane_disposition.py`. It is read-only and re-runnable, and its inputs are committed under
`data/disposition_20261015/`:

- `crontab_20261015.txt`: `crontab -l`, read-only, sha256 `6a5c6768…de4e96`. It has 1,065 lines: 394 active job lines,
  8 env lines, and the rest comments.
- `inventory_20261014.csv`: the 524-job inventory.
- `ws2_family_decisions_20261014.csv`: 52 families.
- `overrides.json`: per-lane verdicts re-checked today, each with its evidence.

Matching uses the same substring rule as `lane_registry.find_undeclared`. **All 394 lines map to a registry row. None
is undeclared.**

The architecture review (`MIGRATION_TARGET.md` §2-§3) supplies the categories. A per-lane override, when present, wins
over the family default.

## Totals (crontab lines; they reconcile to `crontab -l`)

| Disposition | Lines | Waves |
|---|---:|---|
| RETIRE | **10** | R1 4 (this packet, tier A) · R1b 6 (same packet, tier B, operator YES per row) |
| CONSOLIDATE | **148** | C1 52 · C2 29 · C3 15 · C4 33 · C5 19 |
| STAY_HOST | **99** | broker/order/stop/protection/secret (F09 43), senders and `--send` lanes, daemons and watchdogs, deploy chain, §23.14 keep-on-cron |
| MIGRATE_N8N | **137** | M0 6 · M1 6 (PR #1761) · M2 38 · M3 16 · M4 33 · M5 16 · M6 22 |
| **Total** | **394** | = 394 active job lines in the snapshot (379 distinct lanes; 15 lanes have 2-3 lines) |

There are also 140 registry-only rows: 101 systemd units, 23 cron rows with no live line, 8 n8n rows, 5 event rows and
3 none rows. Their dispositions:

| Disposition | Rows |
|---|---:|
| RETIRE | 13 (R1-timer 1, `hermes-shadow-scorer`; R2 12) |
| CONSOLIDATE | 17 |
| STAY_HOST | 73 |
| MIGRATE_N8N | 37 |

## What changed against the 2026-10-14 status pass

- **Active lines: 413 → 394.** Today's table holds 394 active job lines.
- **The 49 "superseded" lines are still live.** 36 premarket lines and 13 B-family lines still run under RETIRED rows.
  They are classified **CONSOLIDATE / C1**, with `duplicate_of` set to the successor stage, and not RETIRE. Their
  removal is the existing flip packets, `c1-manifest-flips/premarket` and `b-families-top5`. Each packet comments the
  lines and turns the stage runner from `--dry-run` to `--apply` in one act. Commenting the lines without that flip
  would stop the work.
- **The retire-wave2 decisions stand.** Its 4 YES rows are 3 cron lines (here R1) and 1 timer (R1-timer). Its 9 NO
  rows are not retired.
- **`hermes-research-worker-pool` is not built-but-not-wired.** The claim was checked on 2026-10-15 and refuted:
  - Its log holds 421 runs (09-27 to 10-15).
  - 6 of its 9 lanes have runners and upsert 30-50 discovery candidates a day. On 10-14 it scanned 56 and upserted 40.
  - Only `tax_retirement`, `system_ops` and `custom_domain` are `no_runner`.
  - The NO_OUTPUT page comes from the receipt. An hour in which every lane is cadence-skipped writes `status: failed`,
    `error: pool_incomplete`.
  - It is classified MIGRATE_N8N / M2 with a REPAIR note: make the receipt honest, and drop the three runner-less lanes.
- **The "runs, exit 0, zero output for more than 7 days" sweep.** I checked every `data/runtime/*_last.json` written in
  the last 48 h, and every cron line whose registry `output_signal` file is older than 7 days.
  - **No lane met the pattern.** Every stale signal belonged to a weekly or monthly line that is inside its cadence.
  - **The sweep found a different defect.** `symbol-enrichment` fails on every run. Its cron argv `--limit 50` is
    rejected by the script's strict parser, which arrived in `1c733d98f` on 10-11, and the run exits 2.
  - **`indicator-engine` does no universe work.** The line only runs the module's AMD demo.
  - Both are in the retire packet.
  - **Failing lanes to repair, not retire:**
    - `build-symbol-profiles` and `build_symbol_profiles_watchlist`: `OperationalError`.
    - `watchlist_entry_planner`: `InterfaceError`.
    - `run-research-intelligence-overnight`: `ingest` exit 124.
    - `hermes-coordinator`: `completed: false`.
    - `source-litmus-vs-yahoo`: exit 1.

## Waves

### RETIRE

- **R1, this PR, `docs/ops/packets/lane-retire-wave1-20261015`, tier A, 4 lines:**
  - `agent-intelligence-cron-deep`, `-daily` and `-intraday`: CURRENT has no `.venv`, every run logs "No such file",
    and 0 steps run.
  - `symbol-enrichment`: argv rejected, exit 2 on every run.
- **R1b, same packet, tier B, 6 lines.** Each needs an operator YES per row.
  - `cleanup-stale-locks`
  - `risk-gate`: an hourly self-test that writes synthetic rows into the table the CC aggregates.
  - `backup-generated-docs`: a push from cron, which §24.5 forbids.
  - `goal-pilot-material-change`
  - `dormant-lane-consumers`
  - `indicator-engine`
- **R1-timer.** `hermes-shadow-scorer` is retired with the existing `consolidation-retire-wave2-20261014/timers.sh`,
  under a service grant.
- **R2, 12 registry rows, registry PR plus service grant:**
  - The 7 F03 phantom rows on disabled timers.
  - `coder-dispatch`, `tradeai-ops-agent-service` and `tradeai-advisory-notif-broker`: R-check first.
  - `advisory-shadow-seed` and `cio-memory-shadow-measure`: these wait on operator decision O-W3-4.

### CONSOLIDATE (host first, then one n8n process per unit)

| Wave | Lines | Unit | Status |
|---|---:|---|---|
| C1 | 52 | premarket-data-pipeline (38); B-families (14) | packets built; operator cron grant flips each |
| C2 | 29 | after-close pipeline (25, manifest exists, stages run `--dry-run`); hermes stages (4, already `--apply`) | after-close flip packet; hermes is the fabric pilot (#1746) |
| C3 | 15 | F36 health/audit plane: `config/pipelines/health_audit.json` (PR #1763, inert) takes the 4-line weekday-morning chain into stage `morning`; 11 multi-slot or fabric members are deferred and 7 STAY_HOST members excluded in the manifest | PR #1763; flip packet `consolidation-health-audit-c3-20261015` |
| C4 | 33 | 17 same-script multi-slot families (F17-F34): one lane, N slots, slot→argv | one registry PR per family |
| C5 | 19 | quote writers (7), digests/approvals (7), cache prewarmers (4), maintenance (1) | after the send-intent API and the quote service |

### MIGRATE_N8N

| Wave | Lines | What | Gate |
|---|---:|---|---|
| M0 | 6 | already canary or cutover | — |
| **M1** | **6** | **shadow wave LD-W1 (PR #1761): shadow on the fabric, dry run only** | none: inert at merge, no scheduler change |
| M2 | 38 | already shadow | each needs canary plus ≥1 live n8n run (§23.21). Cutover waits for the freeze exit: Run Lane fault matrix plus outcome callback |
| M3 | 16 | no refactor flag, but each needs a write-free dry run and a receipt audit before shadow | next shadow wave |
| M4 | 33 | refactor first: dry-run flag, receipt, or sender/broker reach | refactor shards |
| M5 | 16 | agent workflows (CIO/Hermes/Aegis/persona) | phase 5, WS9 C1-C10 |
| M6 | 22 | event subscriptions (pollers) | phase 5, producers emit `Event@v1` first |

**Why M1 has 6 lanes, not 15-25.** I applied a strict filter to every MIGRATE line:

- one script;
- no `--send`, `--telegram` or `--alert`;
- no LLM wrapper or model call;
- no send, broker module or account read anywhere in the import closure (`advisory_lane_guard.scan_entry`);
- not a lane pinned off the dispatcher by an earlier wave for a reason that still holds;
- not yet on the allowlist.

8 lanes passed; 6 are onboarded. The others were held or rerouted:

- `build-symbol-profiles-at-0-19` and `drain-discovery-backlog` passed but stay with their refactor shard 05-08
  proposals, which `tests/test_refactor_shards_05_08_locks_20261011.py` pins as held. They are M3 and M6 here.
- `agent-recommendation-normalizer` passed the filter but is held: SW4 P0, random `recommendation_id` per run.
- `symbol-enrichment` and `indicator-engine` passed the filter but go to RETIRE instead (dead line, demo line).
- `sec-filings-feed` and `sec-fundamentals-ingest` fail the filter: their import closure reaches `api_v2`.
- `defense-recommendations` is held: options and holdings advice, and its cron line sources `.env`.

The rest of the pool fails on sender reach (`strategy-weekly-review`, `premarket-watcher`), on the `schwab_transport`
import (`reconcile-*-outcomes`, `enrich-proposal-technicals`, `proposal-monitor`), or on an LLM. Moving those lanes needs
code work, which is M3/M4, not a registry row.
