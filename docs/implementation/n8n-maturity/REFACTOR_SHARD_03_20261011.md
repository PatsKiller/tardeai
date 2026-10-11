# Refactor shard 03 — source preparation, 2026-10-11

Status: SOURCE_ONLY / NOT LIVE
Owner: refactor agent shard 03; operator retains review and scheduling authority
As-of: 2026-10-11
Base: `7b36c98c32382b86c04bd5792927fc7c2bd1c729`
Branch: `n8nmat/refactor-shard-03`

Eight cron lane rows are prepared at shadow with dry-run-only argv and null live argv.
No workflow, timer, crontab or deployment changed. All eight new health contracts remain DRAFT;
no reviewer was written. A merged source row is not natural fire or consumer acceptance proof.

The eight lanes are Aegis social sentiment, ETF performance enrichment, Hermes social sentiment,
investment costs, both opening intelligence schedules, analyst source registration and the
closed-trade backtest engine. CLI previews are offline plans that cannot open the live DB,
read credential files or call providers. They do not invent target counts when data was not read.
The older library preview functions remain available for callers; their DB/provider previews are
not the dispatcher CLI contract. Legacy live business calls and stdout are checked against old
entry-point source with identical fakes. Real runs write LaneRunReceipt@v1; failure retains the
prior ok_at and exit semantics. The backtest receipt now uses the lane identity's hyphenated name.

Two additional source preparations remain blocked: ask-alerts gains a strict dry-run/receipt,
but the exact cron comment includes Telegram and the existing admission matcher refuses it;
Hermes discovery yield gains an offline preview/receipt, but is already absorbed into C1 and
has no current cron line. Neither gets another scheduler row or an allowlist entry.

Exact cron text comes from the operator-approved, read-only snapshot collected by the parent,
`authorized_cron_snapshot_01_04.json`; rows matched by script and mode, never by historical line number.
A prior crontab subprocess returned exit 1 before stderr was printed; it was not retried here.
The native-approved parent read resolved that measurement boundary. Ancillary successful-shell
stream-fd warnings are recorded under playbook §1A and were not treated as refusals.

scheduler.wave is R2-03 (shard provenance). dispatch.wave is W4 because the current shared enum
only admits W0–W5; no enum or gate was relaxed. Retry policy is the existing none
policy, which admits ingest/learn without repeating a writer. Class-default cadence/timeout baselines are
provisional and say NOT_MEASURED for live-ledger history. Contracts do not claim production enforcement.

Three cron rows lack flock: Aegis social, Hermes social and analyst source registration.
Their proposed locks are listed in CRON_FLOCK_NEEDED.tsv; they cannot take a canary before an
operator packet puts the same lock into live cron. Existing ETF, investment-cost, opening and
backtest locks are reused. Both opening schedules deliberately share one lock and one business
output file, with separate run receipts; this retains the existing serial writer contract.

Direct whole-environment loaders were narrowed and moved behind live branches. Most entries
remain env_allowlist_mode=report because db_adapter/env_bootstrap and research/provider import
closures still need the integrator's shared change. Opening intelligence uses enforce: no
credential loader and one directly read lane variable. Live admission, contract review, shared
closure validation, release and runtime acceptance are separate gates and remain owed.

The inventory overlay records all 37 lanes, including skips and blockers, instead of labeling
untouched lanes shadow-ready. Workbook/Drive rebuilding is left to the integrator.

## Per-lane dispositions

| Lane | Result | Notes |
|---|---|---|
| wake-selection-feed | BLOCKED | External campaign ops script is outside this repo; no owned script available for patch/test. |
| ops-weekly-learning-report | SKIP_SENDER | External OpenClaw script; registry declares Telegram sending. External source unchanged. |
| cio-reactive-cycle | BLOCKED | Systemd inventory supplies no owned script/exact cron line; §3.7 cron shadow recipe cannot safely represent this timer. Retain scheduler unchanged. |
| cio-desk-memo-regen | BLOCKED | Systemd inventory supplies no owned script/exact cron line; §3.7 cron shadow recipe cannot safely represent this timer. Retain scheduler unchanged. |
| source-litmus-vs-yahoo | BLOCKED | Systemd inventory supplies no owned script/exact cron line; §3.7 cron shadow recipe cannot safely represent this timer. Retain scheduler unchanged. |
| advisory-outcome-scorer | BLOCKED | Systemd inventory supplies no owned script/exact cron line; §3.7 cron shadow recipe cannot safely represent this timer. Retain scheduler unchanged. |
| supervisor-breach-detector | BLOCKED | Systemd inventory supplies no owned script/exact cron line; §3.7 cron shadow recipe cannot safely represent this timer. Retain scheduler unchanged. |
| db-retention-timer | BLOCKED | Systemd inventory supplies no owned script/exact cron line; §3.7 cron shadow recipe cannot safely represent this timer. Retain scheduler unchanged. |
| tradeai-agent-runtime-alex | BLOCKED | Systemd inventory supplies no owned script/exact cron line; §3.7 cron shadow recipe cannot safely represent this timer. Retain scheduler unchanged. |
| tradeai-maturity-feeds | BLOCKED | Systemd inventory supplies no owned script/exact cron line; §3.7 cron shadow recipe cannot safely represent this timer. Retain scheduler unchanged. |
| goal-gate-bridge | SKIP_CLASS | Measurement/governance monitor; outside the recipe ingest/llm/learn classes. |
| plan-drift-revalidator | SKIP_SENDER | Invokes watchlist_entry_planner without --no-alert; child has a send path. |
| run-pullback-macd-monitor | SKIP_BROKER | Paper proposal lifecycle monitor behind market-day gate; excluded paper/safety path. |
| aegis-social-sentiment | SHADOW_READY | SOURCE_ONLY; exact approved cron line; dry_run only; null live_arg; DRAFT contract; operator review/runtime proof still owed. |
| agent-router-cron-light | SKIP_BROKER | Shared context refresher launches portfolio producer family; hidden dev-tree root and outside-shard dependency. |
| agent-router-cron-full | SKIP_BROKER | Context refresher runs portfolio_risk/stops.json producers; excluded risk/stop path. |
| agent-router-cron-deep | SKIP_BROKER | Context refresher runs portfolio_risk/stops.json producers; excluded risk/stop path. |
| agent-watchlist-engine | SKIP_SENDER | Whole script contains Telegram branches; cron currently runs --status only. Separate read-only entry needed. |
| ask-alerts | BLOCKED | Source dry-run/receipt added, but exact approved cron comment contains Telegram: forbidden_token:telegram@scheduler.command_text. No shadow admission. |
| cleanup-stale-locks | SKIP_CLASS | Independent lock maintenance/recovery; not an ingest/llm/learn class. Retain with reason. |
| etf-performance-enrich | SHADOW_READY | SOURCE_ONLY; exact approved cron line; dry_run only; null live_arg; DRAFT contract; operator review/runtime proof still owed. |
| hermes-discovery-yield-builder | BLOCKED | No active exact cron line in approved current snapshot; now part of C1 learning stage. Source dry-run/receipt improved; no shadow row. |
| hermes-social-sentiment | SHADOW_READY | SOURCE_ONLY; exact approved cron line; dry_run only; null live_arg; DRAFT contract; operator review/runtime proof still owed. |
| hermes-tag-lift-discovery | BLOCKED | No active exact cron line in approved current snapshot; C1 learning stage already owns scheduling. No duplicate scheduler proposed. |
| investment-costs | SHADOW_READY | SOURCE_ONLY; exact approved cron line; dry_run only; null live_arg; DRAFT contract; operator review/runtime proof still owed. |
| opening-intelligence | SHADOW_READY | SOURCE_ONLY; exact approved cron line; dry_run only; null live_arg; DRAFT contract; operator review/runtime proof still owed. |
| opening-intelligence-render | SHADOW_READY | SOURCE_ONLY; exact approved cron line; dry_run only; null live_arg; DRAFT contract; operator review/runtime proof still owed. |
| pro-analyst-fetch | SKIP_SENDER | Exact cron line is a three-step chain ending pro_analyst_monitor.py --send; do not admit just its first step. |
| register-analyst-sources | SHADOW_READY | SOURCE_ONLY; exact approved cron line; dry_run only; null live_arg; DRAFT contract; operator review/runtime proof still owed. |
| run-scheduled-stale-proposal-sweeper-at-25-8 | SKIP_BROKER | PAPER ONLY wrapper reads safety flags and paper holdings guard; excluded paper/safety path. |
| trade-backtest-engine | SHADOW_READY | SOURCE_ONLY; exact approved cron line; dry_run only; null live_arg; DRAFT contract; operator review/runtime proof still owed. |
| watch-directive-hygiene | SKIP_SENDER | Explicit send_telegram summary path. |
| watchlist-entry-planner-limit | SKIP_SENDER | Default planner alerts are enabled; cron omits --no-alert. Separate notification-intent migration. |
| watchlist-entry-planner-scope | SKIP_SENDER | Default planner alerts are enabled; cron omits --no-alert. Separate notification-intent migration. |
| watchlist-hygiene | SKIP_SENDER | Cron explicitly includes --telegram. |
| youtube-transcript-ingest | SKIP_SENDER | --all-channels failure path directly calls send_telegram. |
| warm-caches | SKIP_BROKER | Rotation warm step writes stop-related cache and invokes an autopilot with proposal/Telegram side effects; leave untouched. |

## Validation and rollback

Required §4 gate outputs and scratch dry-run evidence are in untracked REFACTOR_EVIDENCE_03.md.
The new test family is registered in run_cio_hardening_ci.py. Tests use scratch state and fake
business functions, with no actual provider, DB or broker operation. DRAFT review refusals and
any other gate failure remain explicit in the final handoff; no gate was weakened.

The final combined regression completed 226 tests under M2_SKIP_DOCKER=1, a minimal environment,
scratch roots and pre-import DB/network/production-write traps, with zero capability attempts.
Initial runs passed 221 tests and then 37 shard tests, but did not explicitly disable the
conftest maintenance DB probe; their production impact is NOT_MEASURED. The first guarded
rerun intercepted six DB attempts from three existing Hermes library preview tests. Those
tests now fake the separate coverage query boundary and retain all writer/upsert traps.
After correcting the retry policy and
an offline plan phrase that falsely looked like a second SQL writer, the affected registry and
data-authority gates pass. The expanded shard-only negative suite passes all 37 tests, and Ruff
passes. Coverage, host-path, dark-contract and docs-index checks passed. Health-contract check
remains exit 1 with exactly eight DRAFT_NOT_GRANDFATHERED refusals; operator review is required.
This branch is not ready for remote synchronization while that gate remains red.

Rollback before merge: leave this local branch unintegrated. After a future merge, revert this
shard's source commit before a release; no host rollback is needed for this source work. Any
future scheduler change requires its own reviewed packet and operator grant. No natural fire,
canary, cutover, SLO completion or production convergence is asserted here.
