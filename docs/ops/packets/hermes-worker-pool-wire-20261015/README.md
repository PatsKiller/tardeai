# hermes-research-worker-pool — real lane runners + fail closed on zero output (2026-10-15)

Operator, verbatim: "That is the type of thing that having the workflows in N8N will catch. Wire it up correctly."

## What was wrong (measured, read-only)

`5 * * * * ... hermes_research_worker_pool.py --run --json` has run hourly since 2026-07-05. The pool log
(`persistent-state/logs/hermes_worker_pool.log`, 421 reports 2026-09-27T15:05Z .. 2026-10-15T11:05Z) shows:

| lane | runs that did work | payloads upserted | other outcomes |
|---|---|---|---|
| holdings | 89 | 224 | 332 cadence skips |
| watchlist | 88 | 117 | 333 cadence |
| white_space | 33 | 183 | 388 cadence |
| strategy | 17 | 66 | 404 cadence |
| private_proxy | 18 | 90 | 403 cadence |
| legal_domain | 17 (5 empty) | 21 | 404 cadence |
| **tax_retirement** | **0** | **0** | **421 `no_runner`** |
| **system_ops** | **0** | **0** | **421 `no_runner`** |
| **custom_domain** | **0** | **0** | **421 `no_runner`** |

So six lanes worked; three were declared and enabled but no module ever registered a runner. The pool exited 0
every hour. The lane receipt was `failed` (`pool_incomplete`) on most hours anyway, because every lane-cadence-only
hour counted as "entirely skipped", so the one red signal was noise that hid the real gap. The n8n dispatcher has
fired this lane as a shadow dry run since 2026-10-11: 89 `RUN_DONE` rows, each 0.105 s, because the preview printed
one line and returned. n8n was green while three lanes did nothing.

## What this branch changes

* **Runners for the three lanes**, all reusing existing producers (no new table, no new external host, no LLM call):
  * `tax_retirement` -> `coverage.taxes_findings` + `coverage.retirement_findings` (term recurrence over
    `news_articles` + `hermes_research_intelligence`), evidence kept only when it has a source URL.
  * `system_ops` -> `coverage.system_ops_findings` (latest failing/stale `system_health_checks` components), behind
    a probe that raises if the table is empty, unreadable or not written for 48 h. Zero payloads is a healthy
    result here (`expected_output_hours: 0` + `zero_output_reason`).
  * `custom_domain` -> the operator's custom domains (`config/hermes_custom_research_domains.yaml`) the lane admits:
    their `classification_keywords` drive the same scan; `denylist_terms` and `blocked_source_types` filter rows.
  * Module: `scripts/lib/hermes_discovery/coverage_lanes.py`, listed in `worker_pool.RUNNER_MODULES` (the CLI no
    longer keeps its own list).
* **Expected-output rule** (`config/hermes_research_worker_lanes.yaml`): every enabled lane declares
  `expected_output_hours` (no default). A disabled lane must carry `disabled_reason`. Load fails closed otherwise.
* **Per-lane outcome + fail closed** (`worker_pool.lane_outcome`, `run_pool` -> `lane_outcomes`, `failures`, `ok`):
  `no_runner`, `runner_error`, `output_overdue` are failures. The CLI exits **3** on any failure (1 stays the
  pool-level error), and the receipt is `failed` with `summary.failures`. Exit 0 with every lane `no_runner` is now
  impossible. The output clock is durable: `last_output_at` (advanced only by a live run that returned payloads) and
  `tracking_since` in `data/runtime/hermes_worker_pool_state.json`. So a cadence-skipped hour still sees an overdue lane.
* **Receipt semantics:** `ok_at` advances when every selected lane is healthy, including an hour where every lane is
  only `not_due`. That counts as healthy because each enabled lane's output clock was checked inside its window.
  This replaces the "entirely skipped pool = failed" rule, which fired on most hours as noise. It is restated in
  the contract's `cron_receipt_failed` text and flagged for your review.
* **Dry run** (`--dry-run`, the argv n8n runs): an offline plan. It imports the lane config and runner modules (pure
  imports, no DB), reads the state file, writes nothing and makes no model call. It ends with one compact
  `DRY-RUN-SUMMARY {...}` line, which is what the executor's 800-char `stdout_tail` keeps. It exits **3** on
  `no_runner` or an overdue clock, so the shadow fire becomes `RUN_FAILED` and n8n catches zero output.
* **Fabric** (AGENTS.md §23.21/§23.23). The lane was already a dispatcher shadow lane:
  * allowlist: dry run only, `live_arg` null, unchanged;
  * `lane_registry`: stage shadow, dispatch `dry_run` W4, unchanged;
  * effect key: `append`, `cron_claim` false, unchanged.

  The REVIEWED health contract gains `lane_outcomes_ok`, `dry_run_plan_clean` and `lane_zero_output` (the
  expected-output rule). Its inventory free text is replaced by concrete config/store edges, and
  `review.amendments` records the change. The amendment is agent-reviewed; **your REVIEW pass of the amendment is
  owed**.

## Expectation windows (set from the log above, about 3-4x the longest observed gap, never below one cadence)

holdings 48 h, watchlist 48 h, white_space 72 h, strategy 96 h, private_proxy 96 h, legal_domain 336 h (niche pack:
observed 149 h gap), tax_retirement 72 h, custom_domain 336 h, system_ops 0 (zero is healthy; the source probe guards it).

## Evidence gathered on this branch (all read-only)

* The three runners were called directly against production with `PGOPTIONS=-c default_transaction_read_only=on`,
  outside the pool, so nothing was written:
  * tax_retirement: 5 payloads (roth conversion, medicare, irs, retirement, capital gains), all with URL evidence;
  * system_ops: 8 (e.g. `schwab_journal_ingest STALE`, `alex_daily MISSING`);
  * custom_domain: 5 (health_general treatment / therapy / clinical trial, legal_general liability,
    technology_general operating system).
* `--dry-run` of this branch against the production state file (sha256 `665ce22d…` identical before and after):
  exit 0, `DRY-RUN-SUMMARY {"ok": true, "failures": [], ...}`, 9/9 runners registered. The clocks read
  `untracked` until the first live run.
* Executor dry_run path (`n8n_run_executor.execute`, throwaway state root): `RUN_DONE`, exit 0, output_signal
  mtime unchanged. The same path with a lane that has no runner gives `RUN_FAILED`, exit 3 (tests).

## Order

1. Review and merge the PR. Promote as usual (release grant). Nothing else is required: no crontab, unit, n8n or
   relay change.
2. `bash 01_dry_run.sh` from the served release (expect exit 0). `bash 01_dry_run.sh --executor` for the executor path.
3. `bash 02_live_n8n_run.sh`: waits for the next :05 dispatcher fire. That is the live n8n run of the new code
   (stage clamp: dry_run). It shows the ledger row (expect `RUN_DONE`, `DRY-RUN-SUMMARY ok true`), the cron twin
   receipt (expect `status ok`, nine `lane_outcomes`, none `no_runner`) and the worker state clocks.
4. After 24 hourly slots: `python3 03_parity.py --since <promote time>` (expect PASS: paired slots agree on runner
   registration and overdue lanes).
5. The first daily runs of tax_retirement / custom_domain write operator-gated candidates (status NEW, promotion
   impossible) to the Discovery Inbox. Review them there.
6. Rollback: `09_rollback.sh` (prints the release re-point; nothing else to undo).
