# Lane disposition, 2026-10-15

**Operator directive 2026-10-15 (decision D11) — applied to this table.** Verbatim, authoritative wording:

> **Agent Instruction: N8N Cutover Decision**
>
> I reviewed the entire assessment and disagree with the conclusions for every category except F07 (Long-Running
> Daemons and @reboot).
>
> **Decision**
>
> F07 remains outside of N8N for this iteration. Long-running services, daemons, watchdog-dependent processes, OAuth
> proxy services, and other continuously running infrastructure are not cutover candidates at this time.
>
> All other categories listed below are approved for cutover to N8N.
>
> registry_systemd files are to remain on the server for this iteration. They are not to be migrated, refactored, or
> reclassified as part of the current cutover effort. Once the broader N8N migration is complete and operating
> successfully, we will evaluate these assets during the next iteration and determine whether any additional
> consolidation into N8N is appropriate.
>
> The rationale that these workflows should remain host-side, cron-based, or external due to maturity, reliability,
> operational risk, monitoring requirements, or similar concerns is not accepted as a blocker. Our target architecture
> requires these capabilities to be implemented as: Matured within N8N; Automated end-to-end; Self-healing and
> self-fixing where applicable; Operationally resilient without requiring manual intervention; Fully documented,
> monitored, and auditable.
>
> If any existing documentation, standards, inventory notes, exception records, or implementation guidance state
> otherwise, consider that guidance superseded. I will either: Approve an exception directly, or Require the language,
> classification, architecture, and documentation to be updated to align with this directive.
>
> This is not a discussion item, not a recommendation, and not a request for further analysis. It is a direct
> architectural decision and implementation directive.
>
> Approved for N8N Cutover: F09 Broker / Order / Stop / Protection / Secret; F36 Health / Audit / Monitor Plane; F41
> Retention, Backup, Hygiene Timers; F06 Other Applications and OS Units; F40 LLM-Judgment Agents on Clocks (CIO /
> Hermes / Aegis); F10 Operator Senders (P1 Paths); F07w Host Watchdogs and Guards (provided monitoring independence is
> preserved through architecture and implementation); F37 Digests and Reminders; F49 Already on N8N (Platform Lanes);
> F08 Automation-Fabric Infrastructure; F23 News Ingestion; F33 Deploy Chain; F22 LLM Spend Reports.
>
> Deferred for This Iteration: F07 Long-Running Daemons and @reboot Services; registry_systemd files and associated
> service definitions.
>
> Implementation Guidance: Proceed under the assumption that all approved categories are expected to be migrated,
> engineered, tested, documented, and operationalized within N8N unless I explicitly authorize an exception. Do not
> spend additional cycles defending legacy placement decisions. Instead, focus on designing the required controls,
> redundancy, monitoring, recovery, alerting, and self-healing capabilities necessary to make these workflows
> production-grade within N8N. For the current phase, keep the registry_systemd assets on the server unchanged.
> Complete the N8N cutover first, stabilize operations, validate production readiness, and revisit the
> registry_systemd strategy during the next architecture review cycle. The default assumption should be that they
> remain in place until a future review explicitly determines otherwise.

The builder applies it after the 2026-10-14 rules (`apply_cutover_directive`):

- every STAY_HOST row with `family_id != F07` and `source != registry_systemd` is now **MIGRATE_N8N**, with the
  directive cited in `evidence` (`was: <old reason>` kept);
- F07 STAY_HOST rows stay **STAY_HOST**, wave **`DEFERRED-I2`**;
- **every `registry_systemd` row** (101), whatever its 2026-10-14 disposition, is **STAY_HOST / `DEFERRED-I2`** with
  evidence `operator directive 2026-10-15: registry_systemd deferred this iteration (was: <disposition>/<wave>; …)`.
  That includes 25 rows that were MIGRATE_N8N, 12 CONSOLIDATE and 12 RETIRE (the R1-timer `hermes-shadow-scorer` and
  11 of the 12 R2 rows below are therefore deferred, not retired, this iteration).
- **F41 and F08 have nothing to move this iteration.** Every F41 and F08 row is `registry_systemd`, so although both
  families are approved, all their rows are deferred by the same directive.

The old totals below are struck, not deleted.

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
| STAY_HOST | **1** (~~100~~; ~~99~~ before train d) | F07 daemon/`@reboot` line only, wave `DEFERRED-I2` (operator directive 2026-10-15). ~~broker/order/stop/protection/secret (F09 43), senders and `--send` lanes (incl. hermes-coordinator, L376: moved from M5 by lane repair #1772, train 2026-10-15 d), daemons and watchdogs, deploy chain, §23.14 keep-on-cron~~ — superseded |
| MIGRATE_N8N | **235** (~~136~~) | M0 6 · M1 6 (PR #1761) · M2 38 · M3 16 · M4 33 · M5 15 · M6 22 · **directive waves: CD1 5 · CD2 18 · CD3 19 · CD4 10 · CD5 2 · CD6 45** (CD4 includes hermes-coordinator L376, STAY_HOST via #1772, moved by the directive) |
| **Total** | **394** | = 394 active job lines in the snapshot (379 distinct lanes; 15 lanes have 2-3 lines) |

There are also 140 registry-only rows: 101 systemd units, 23 cron rows with no live line, 8 n8n rows, 5 event rows and
3 none rows. Their dispositions:

| Disposition | Rows |
|---|---:|
| RETIRE | **1** (~~13~~ R1-timer 1, `hermes-shadow-scorer`; R2 12 — 12 of them are `registry_systemd`, now deferred) |
| CONSOLIDATE | **5** (~~17~~): C1 4 · C5 1 |
| STAY_HOST | **102** (~~73~~): all 101 `registry_systemd` rows + 1 F07 cron row with no line, all wave `DEFERRED-I2` |
| MIGRATE_N8N | **32** (~~37~~): M0 1 · M3 5 · M5 3 · M6 3 · CD1 5 · CD2 1 · CD3 1 · CD6 13 (F09 cron rows with no live line) |

## Directive cutover waves (CD1-CD6), in order

Order set with the directive: read-only first, broker last. Each wave still follows the n8n cutover standard (fix +
dry run + regression + at least one live n8n run) and the existing grant/packet process; the directive is a direction,
not an activation grant.

| Wave | Crontab lines | Registry-only rows | Families | Shape |
|---|---:|---:|---|---|
| CD1 read-only | 5 | 5 | F36 (non-sending health/audit), F49 (already-n8n platform lanes) | fabric Run Lane leaf |
| CD2 appenders | 18 | 1 | F06, F12, F23, F33, F39, F45, F46, F52, 2 unfamilied KEEP_ON_CRON lines | fabric Run Lane leaf |
| CD3 senders | 19 | 1 | F10 (8), F37 (5), F22 (3), sender-blocked F36 (2) and F04 (1); 1 unfamilied event row | n8n orchestrates; send stays the host chokepoint (send-intent). F10 = "independent host P1 backstop + n8n-orchestrated primary" |
| CD4 LLM agents | 10 | 0 | F40 (incl. hermes-coordinator L376), F29 | agent workflow via the governed bridge |
| CD5 watchdogs | 2 | 0 | F07w (crontab only; F07w systemd units are deferred) | n8n-orchestrated; independence from the outside dead-man (DD12) |
| CD6 broker | 45 | 13 | F09 | n8n **schedules** the host lane; the host executes under the trading lock; n8n holds no broker credential and calls no order route |
| DEFERRED-I2 | 1 | 102 | F07 STAY_HOST rows (any source) and every `registry_systemd` row (F36 18, F41 15, F07 12, F40 12, F03 7, F06 7, F51 5, F07w 5, F08 4, F38 4, F39 4, F04 2, F05 2, F02 1, F09 1, F15 1, unfamilied 1) | stays on the server unchanged; next architecture review |

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

*Operator directive 2026-10-15: R1-timer and the 11 `registry_systemd` R2 rows are deferred (STAY_HOST /
`DEFERRED-I2`), not retired, this iteration; the crontab R1/R1b lines are unaffected.*

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

*The M-waves below are the 2026-10-14 MIGRATE set (137 lines; 136 after #1772). The 99 lines moved by the operator directive are in
waves CD1-CD6 above (M5 shows 15: hermes-coordinator went to STAY_HOST in #1772, then to CD4).*

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
