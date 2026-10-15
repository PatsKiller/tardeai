# Lane disposition, 2026-10-15

> **Operator directive 2026-10-15 "N8N Cutover Decision" (decision D11) — applied to this table.** All lane families
> are approved for n8n cutover except F07 (long-running daemons and `@reboot` services) and all `registry_systemd`
> assets, which stay on the server unchanged (revisit at the next architecture review). Approved list as given: F09,
> F36, F41, F06, F40, F10, F07w (monitoring independence preserved through architecture), F37, F49, F08, F23, F33, F22
> — and every other non-F07 family. Verbatim: "The rationale that these workflows should remain host-side, cron-based,
> or external due to maturity, reliability, operational risk, monitoring requirements, or similar concerns is not
> accepted as a blocker." "If any existing documentation, standards, inventory notes, exception records, or
> implementation guidance state otherwise, consider that guidance superseded."
>
> The builder applies it after the 2026-10-14 rules (`apply_cutover_directive`): every STAY_HOST row with
> `family_id != F07` and `source != registry_systemd` is now **MIGRATE_N8N**, with the directive cited in `evidence`
> (`was: <old reason>` kept). F07 and `registry_systemd` rows stay **STAY_HOST**, wave **`DEFERRED-I2`** (deferred this
> iteration). The old totals below are struck, not deleted.

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
| STAY_HOST | **1** (~~99~~) | F07 daemon/`@reboot` line only, wave `DEFERRED-I2` (operator directive 2026-10-15). ~~broker/order/stop/protection/secret (F09 43), senders and `--send` lanes, daemons and watchdogs, deploy chain, §23.14 keep-on-cron~~ — superseded |
| MIGRATE_N8N | **235** (~~137~~) | M0 6 · M1 6 (PR #1761) · M2 38 · M3 16 · M4 33 · M5 16 · M6 22 · **directive waves: CD1 5 · CD2 18 · CD3 19 · CD4 9 · CD5 2 · CD6 45** |
| **Total** | **394** | = 394 active job lines in the snapshot (379 distinct lanes; 15 lanes have 2-3 lines) |

There are also 140 registry-only rows: 101 systemd units, 23 cron rows with no live line, 8 n8n rows, 5 event rows and
3 none rows. Their dispositions:

| Disposition | Rows |
|---|---:|
| RETIRE | 13 (R1-timer 1, `hermes-shadow-scorer`; R2 12) |
| CONSOLIDATE | 17 |
| STAY_HOST | **53** (~~73~~): 52 `registry_systemd` + 1 F07 cron row with no line, all wave `DEFERRED-I2` |
| MIGRATE_N8N | **57** (~~37~~): +20 by the directive — CD1 5 · CD2 1 · CD3 1 · CD6 13 (F09 cron rows with no live line) |

Note: 25 `registry_systemd` rows were already MIGRATE_N8N (and 12 CONSOLIDATE, 12 RETIRE) under the 2026-10-14 rules;
this PR changes only STAY_HOST rows. Whether the directive's "all `registry_systemd` assets stay on the server
unchanged" also defers those 25 is an open question for the operator / Agent A.

## Directive cutover waves (CD1-CD6), in order

Order set with the directive: read-only first, broker last. Each wave still follows the n8n cutover standard (fix +
dry run + regression + at least one live n8n run) and the existing grant/packet process; the directive is a direction,
not an activation grant.

| Wave | Crontab lines | Registry-only rows | Families | Shape |
|---|---:|---:|---|---|
| CD1 read-only | 5 | 5 | F36 (non-sending health/audit), F49 (already-n8n platform lanes) | fabric Run Lane leaf |
| CD2 appenders | 18 | 1 | F06, F12, F23, F33, F39, F45, F46, F52, 2 unfamilied KEEP_ON_CRON lines | fabric Run Lane leaf |
| CD3 senders | 19 | 1 | F10 (8), F37 (5), F22 (3), sender-blocked F36 (2) and F04 (1); 1 unfamilied event row | n8n orchestrates; send stays the host chokepoint (send-intent). F10 = "independent host P1 backstop + n8n-orchestrated primary" |
| CD4 LLM agents | 9 | 0 | F40, F29 | agent workflow via the governed bridge |
| CD5 watchdogs | 2 | 0 | F07w (crontab only; F07w systemd units are deferred) | n8n-orchestrated; independence from the outside dead-man (DD12) |
| CD6 broker | 45 | 13 | F09 | n8n **schedules** the host lane; the host executes under the trading lock; n8n holds no broker credential and calls no order route |
| DEFERRED-I2 | 1 | 53 | F07 (any source), every STAY_HOST `registry_systemd` row (F41, F36, F06, F07, F07w, F08, F09, F40) | stays on the server unchanged; next architecture review |

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

*The M-waves below are the 2026-10-14 MIGRATE set (137 lines). The 98 lines moved by the operator directive are in
waves CD1-CD6 above.*

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
