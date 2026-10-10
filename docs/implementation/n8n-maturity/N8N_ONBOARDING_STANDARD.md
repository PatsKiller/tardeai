# N8N onboarding standard — the mandatory procedure for adding anything to n8n

```
Status:      ACTIVE
as_of:       2026-10-10T17:30:00-04:00
Measured at: origin/main 2aa2cc37d (#1664) / live af292381c-main-exact-phase2-20261010-113824; host ms01-openclaw
Owner:       platform (n8n maturity program, Agent A supervises)
Policy:      AGENTS.md 4.4.1 §9.3, §17, §23 (this file restates; where it differs, AGENTS.md wins). AGENTS.md 4.5.0
             §23.19 (PROPOSED, awaiting APPROVE_AGENTS_POLICY_4_5_0) makes this procedure mandatory.
Companion:   docs/implementation/n8n-maturity/N8N_MONITORING_AND_REMEDIATION_STANDARD.md (monitoring, SIEM,
             Telegram, LLM remediation, workflow health contracts)
Entry point: docs/implementation/n8n-maturity/N8N_CONFIGURATION.md (how n8n is configured on this host)
```

Operator ask, 2026-10-10 ~16:35 ET: *"Make sure you totally update the documentation on this and the agents.md or any
other files that need to know these baseline configurations that's being done. So when new stuff is added to N8N, it
follows the procedures."*

This is the procedure for adding **any** job, lane, workflow or relay path to n8n: a dispatcher lane, a shadow /
canary / cutover row, a generic workflow change, a relay route, a gateway lane or an executor setting. Every step
names the gate or test that enforces it and the grant it needs. A step without its evidence did not happen
(AGENTS.md §0 rails 7–8). It records the baseline as configured on 2026-10-10; §12 lists what is live, and §13 maps
each rule to the incident that produced it.

Grant vocabulary (AGENTS.md §2, §17, §23.2): **`cron`** covers crontab edits and every n8n import, publish,
unpublish, edit, archive and cutover; **`config-write`** covers host unit drop-ins and on-disk config;
**`service`** covers `daemon-reload` and restarts; **`db-write`** covers a database row change. A registry-row PR
needs no grant: its merge is the operator's decision (§23.11), by the operator or under the §23.13 standing merge
approval (`Expires-At: 2026-10-11T17:30:03-04:00`; AGENTS.md changes keep the operator's per-PR word).

---

## 1. The checklist

Do the steps in order. Each row: what to do, what proves it, and what authority it needs.

| # | Step | Enforced / proved by | Authority |
|---|---|---|---|
| 1 | **Inventory row first.** The job has a row in `docs/implementation/n8n-maturity/cron-inventory/` (classification, notes, `approval_status`). No job is migrated, modified, disabled, consolidated or retired until its row is Approved. | cron-inventory `README.md` (operator mandate 2026-10-09 ~21:50 ET, "cron freeze"); the change-log row lands in the same PR train | operator row approval |
| 2 | **Classify.** Never eligible: broker, order, stop, position, paper execution, secret render, guard write, release deploy, daemon (`--daemon/--loop/--forever/--watch/--serve`, systemd services) and every sender. Eligible: `monitor`, `report`, `hygiene`, `pipeline`, `heavy`, and the R1 classes `ingest`, `llm`, `learn` (4.3.0). `send` stays refused (R2). The only live exception is `trade-ai-scalp-live` on its 4.0.0 terms, and it is excluded from LLM diagnosis. | `scripts/lib/lane_dispatch.py` `dispatch_eligible` (:611, whole-word matcher, #1643) and `r1_class_admission` (:703); `tests/test_agents_policy_4_1_0_amendment.py`, `tests/test_agents_policy_4_3_0_r1_classes.py` | none (code) |
| 3 | **Write the workflow health contract** (purpose, connects_to, healthy / degraded / failed, baseline, alerting, remediation link, owner, evidence, review_by) in `config/n8n_health_contracts.json`, and have the owner mark it `REVIEWED`. Start from `python3 scripts/build_n8n_health_contracts.py --dry-run`. | `scripts/check_n8n_health_contracts.py` (MISSING_CONTRACT, DRAFT_NOT_GRANDFATHERED, DRAFT_AT_LIVE_STAGE); `tests/test_n8n_health_contracts_20261010.py`; companion standard §3 | owner review |
| 4 | **Refactor to the lane contract** (§2 below): write-free `--dry-run`, honest exit codes, `LaneRunReceipt@v1` `ok_at`, lock equal to the cron line, no checkout-relative path, no whole-`.env` load, no direct Telegram or email. | per-lane tests in the `refactor_w*` GATES entries; dry-run before/after snapshots under `~/n8n-maturity-verification/refactor-evidence/` | agent PR |
| 5 | **Allowlist entry** in `config/n8n_run_allowlist.json`: exact cron argv, `lock` + `lock_kind`, `timeout_s`, non-empty `dry_run_arg`, `live_arg` (null at shadow), `output_signal` = the LaneRunReceipt path, `env_names`, `llm_route` for an `llm` lane. | `r1_class_admission` (d)/(e); gateway `FORBIDDEN_ROUTE_TOKENS`; `tests/test_n8n_run_allowlist_20261008.py` | same PR as step 6 |
| 6 | **Registry row for the stage** (§3 below), with `dispatch.retry_policy` for the class and `adopted_from_generator` if the row was generated. One registry PR at a time. | `scripts/check_lane_registry.py --fail-on-new --state-drift --no-exemptions` (and `--n8n-live` on the host); `validate_dispatch_block` (:880); `scripts/reconcile_lane_registry.py --snapshot-in --write` must be a no-op | merged reviewed PR = operator decision (§23.11) |
| 7 | **Remediation catalogue**: regenerate `config/n8n_remediation_catalogue.json` after the allowlist PR so the diagnoser knows the lane (or record why it is excluded). | `python3 scripts/build_remediation_catalogue.py --check`; companion standard §5 | agent PR; operator reviews the catalogue (decision 4) |
| 8 | **Prove the shadow fire** on the natural schedule: `RUN_DONE` in mode `dry_run` in the coordination ledger, receipt and output_signal unchanged. | ledger `runs` rows + `RunReceipt@v2` `output_signal_mtime_before == after`; `scripts/lib/n8n_due.py` `compute_due` week sweep emits the lane `dry_run` only | none |
| 9 | **Canary** (4.4.0): `dispatch.mode live`, `live_arg` set, allowlist lock equal to every `flock` lock in `scheduler.command_text`. One live fire with the cron line still present; the lock proves no double run. | `r1_canary_lock_matches` (:825); §23.12 | registry PR |
| 10 | **Cutover** per wave: `_cutover.py --lane <id>` comments the exact line `# RETIRED <date> n8n-cutover <lane_id>`, flips the row to `kind: n8n`, `expression: "dispatcher"`, `stage: cutover`, writes `CutoverReceipt@v1`. | `scripts/pipelines/cutover/_cutover.py`; `CRON_PRESENT_WHILE_SCHEDULER_N8N` in `check_lane_registry` | one `cron` grant per wave naming every lane id |
| 11 | **Monitoring proof**: SIEM row on a controlled failure, diagnosis within cap or a recorded exclusion, notifier would send. | companion standard §6 (R6 per lane) | dry run first; live injection needs the selftest lane |
| 12 | **Natural-schedule evidence after cutover** (2 cadences clean; weekly/monthly lanes on their natural fire). A wave fire is not natural evidence. | output_signal on the natural slot; §23.12 last bullet | none |
| 13 | **Inventory change-log row** for any retire / consolidate / cutover / install. | `cron-inventory/README.md` change log | in the same PR train |

Rollback for every step is in §9. Nothing is ever deleted (§0 rail 6).

---

## 2. The refactor contract (a lane must satisfy all of it before any fire)

Source: refactor waves 1–3 (#1641, #1646, #1658) and AGENTS.md §23.18 (e).

1. **`--dry-run` is write-free, and that is proven by a before/after snapshot.** No DB write (a psycopg2 session
   is put in READ ONLY by `scripts/lib/lane_last_receipt.py` `enforce_readonly` :236), no file, no receipt, no
   send, no model call, no paid provider, no claim of queued work. Wave 3 found five dry runs that wrote
   (`etf_performance_enrich --no-fetch` ran ALTER TABLE; `agent_outcome_scorer` parsed no args so `--dry-run` ran
   live; `llm_intelligence_enrichment --dry-run` ran CREATE TABLE; two `--apply --dry-run` combinations applied).
   Proof: files, receipts and DB counts/max/md5 through a read-only session, before and after
   (`refactor-evidence/W5/`, `dispatch-shadow-wave*/before.json`/`after.json`).
2. **Honest exit codes.** 0 only when the work landed; 1 when a source was unavailable or a write failed; 2 for
   usage. No `|| true`, no exit 0 on an abort or a cost cap (REMEDIATION_PLAN §3 P2 #17, #21).
3. **`LaneRunReceipt@v1`** at `data/runtime/<lane>_last.json` through `write_lane_receipt` (:153): `ok_at` advances
   only on a successful run, a failed run carries the previous `ok_at` forward, the dry run calls only
   `dry_run_report` (:213). The registry and allowlist `output_signal` name the same file (`json_key` `ok_at`).
   A log-file mtime proves only that cron opened a file.
4. **Lock = the cron line's lock.** The allowlist `lock` equals the `flock -n` / `safe_flock.sh` lock in the
   crontab line, or the canary cannot prove no double run (§23.12). Lanes without one need a crontab edit first
   (2026-10-10: `wave23-flock` added `flock -n` to L318, L314, L427 at 16:20 ET under cron grant 08c0bb77ec898136).
5. **No checkout-relative paths.** Resolve stores through `TRADEAI_STATE_ROOT` / `persistent_state_root`, and run
   from the pinned release, never `CURRENT` for a dry run and never the dev tree (§9.3, §9.4). Root causes on
   2026-10-10: L227 called `.venv/bin/python` relative to the release (alerts dead since 10-06); several lanes
   still use checkout-relative paths (REMEDIATION_PLAN §8, open finding).
6. **No whole-`.env` loading.** Declare `env_names` in the allowlist. `env_allowlist_mode: report` is allowed only
   with a written `env_report_reason` (today: `db_adapter` → `env_bootstrap.load_env` re-reads the whole rendered
   env). An admitted R1 lane may not name a broker credential (`SCHWAB`, `ALPACA`, `SNAPTRADE`, `MOOMOO`, `IBKR`).
   Open finding: several lanes still load the whole `.env` (ALPACA_* names; the incident-notifier line L1052 sources
   `./.env`).
7. **No direct Telegram, email or Slack.** A lane writes `alert_events` or a receipt; the host chokepoints
   (`send_telegram`, the incident notifier on the SYSTEM family) send. A lane that sends is class `send` and is not
   eligible (L205/L213 were dropped from wave 3 for this).
8. **Governed LLM only.** An `llm` lane declares `llm_route: {"via": "cio-governed-bridge", "process_id": <id>}`
   with a registered process; no argv picks a provider or model (§23.18). Open finding: the R1 gate trusts the
   declared route; a code-level check is still needed.

---

## 3. Registry row shapes per stage (4.4.0)

The schedule lives in `config/lane_registry.json`, never in a workflow. Check every shape with
`check_lane_registry --fail-on-new --state-drift --no-exemptions`.

| Stage | `scheduler` | `dispatch` | allowlist | Example |
|---|---|---|---|---|
| **shadow** (cron row) | `kind: "cron"`, live expression, `match`, `stage: "shadow"`, `wave` | `mode: "dry_run"`, `cron` = the live line's schedule, `tz: "America/New_York"`, `class`, `priority`, `retry_policy` | `live_arg: null` | 36 rows on main (#1656, #1661): `fee-efficiency-analyzer` |
| **staged R1** | cron row + an `r1_pending` block holding the shadow `scheduler`, `output_signal`, `dispatch`; **no** `dispatch` key | none until activation | `live_arg: null` | 19 rows (#1661); activated by #1665 (OPEN) |
| **canary** (cron row) | as shadow, `stage: "canary"`, `command_text` carrying the cron line's `flock` lock | `mode: "live"` | `live_arg` set, `lock_kind: flock`, `lock` = every `flock` lock in `command_text` | none yet |
| **cutover** (dispatcher row) | `kind: "n8n"`, `expression: "dispatcher"`, `cadence`, `match` (the retired line), `wave`, `stage: "cutover"` | `mode: "live"` | as canary | none yet |

Rules:

- **`expression` is `dispatcher`, never `tradeai-dispatcher`.** `tradeai-dispatcher` is the workflow id; the gate
  refuses it as an expression (`workflow_id_as_expression`, `lane_dispatch.py` :749), the stage clamp
  (`scripts/lib/lane_stage_clamp.py` `clamp_mode` :70) runs such a row `dry_run`, and `_cutover.py --workflow-id
  tradeai-dispatcher` is refused (#1659, AGENTS.md §23.11).
- **The stage clamps the mode.** A `shadow` row runs `dry_run` whatever was requested, in the gateway and the
  executor (§23.11).
- **A `kind: n8n` row whose cron line is live fails** `CRON_PRESENT_WHILE_SCHEDULER_N8N`; that is why shadow and
  canary stay cron rows (4.4.0).
- **`adopted_from_generator`.** A generated row (`generated_by: "reconcile_lane_registry@v1"`) that gains a reviewed
  `dispatch` or `r1_pending` block drops `generated_by` and carries `adopted_from_generator:
  "reconcile_lane_registry@v1"`, `adopted_on`, `adopted_reason`; otherwise the next reconcile drops the block
  (`tests/test_n8n_maturity_registry_reconcile_20261009.py`, 17 rows in wave 1, 7 in wave 2, 19 in wave 3).
- **One registry PR at a time** (§23.11): the next PR touching `config/lane_registry.json` waits for the previous
  merge. 2026-10-10 ran four in order (#1654, #1656, #1657, #1661) plus #1665.
- **`retry_policy` per class** (`config/n8n_retry_policies.json`): `none` for `send` and `learn` (and the R1
  `ingest` rows on 2026-10-10); `transient-2` (default, 3 attempts) for `monitor`, `report`, `hygiene`, `pipeline`;
  `transient-1-slow` for `heavy`; `llm-transient` for `llm` (COST_CAP, PEAK_SKIP and 4xx are terminal). The
  breaker opens after 3 failures. CI: `n8n_maturity_b5_followups_20261009` (dispatch class vs retry_policy).
- **Host monitors with no line yet** are declared `state: PAUSED` with an `install_line` that is byte-identical to
  the packet line (incident-notifier, n8n-siem-bridge, n8n-failure-diagnosis); they flip to ACTIVE by a later
  registry PR after the natural-slot verification.

---

## 4. Generic workflows (the six) and relay paths

The six are generated, never hand-edited: `python3 scripts/n8n_workflow_templates.py build-generic` into
`docs/implementation/n8n-maturity/workflows/` (`--check` verifies the committed files and `INDEX.json`). They are
declared to the registry gate by their INDEX (#1650). Rules, each enforced before an import:

1. **`lane=` filters name registry rows only.** The gateway answers 403 `bad_lane_filter` otherwise (W0 cause (a):
   `incident-fanin`, `incident-notify`, `approval-escalate`, `heartbeat-watch`). Today the incident router filters
   on `n8n-incident-fanin,incident-notifier`. The heartbeat watcher and approval router stay out of W0 until
   their host lanes have registry rows.
2. **Every relay path the workflows call must be served.** The relay table is `scripts/n8n_run_relay.py` `ROUTES`
   (:83): `GET /status`, `GET /due`, `GET /runs/<lane_id>/last`, `POST /run`, `POST /event` (`--routes` prints it).
   W0 cause (b): `POST /event` returned 404 because the route in design 02 §8 was never built (#1663 built it).
   **Run `scripts/check_n8n_relay_contract.py` before any import**: it starts a scratch relay from `--relay-root`
   on a free loopback port and refuses `unsupported_route`, `lane_filter_unknown`, `http_timeout_missing`,
   `http_timeout_exceeds_execution`, `execution_timeout_missing`, `save_manual_executions_true`. Exit 0 = PASS,
   1 = REFUSED, 2 = could not check.
3. **HTTP timeouts sit inside `executionTimeout`**, and every workflow sets `executionTimeout` (same checker).
4. **`saveManualExecutions: false`** in every workflow (`n8n_workflow_templates.py` :1823; closes F4).
5. **`errorWorkflow = tradeai-incident-router`** for the other five (:1826). The incident router's Error Trigger
   posts `{lane_id: "n8n-workflow-error", workflow_id, execution_id, node, message}` to relay `POST /event`, which
   forwards one read-scope `accept_event` (the fan-in has no reader for these events yet — companion §4.4); the
   gateway accepts it only because `n8n-workflow-error` is in
   `TRADEAI_N8N_GATEWAY_EXTRA_LANES` (#1664; installed drop-in `20-workflow-error-lane.conf`, 16:27 ET, config-write
   grant 8c235faa82733127, service grant 7752d1c23506de55).
6. **The relay URL is the bridge IP** `http://172.19.0.1:18092` set once in a `Relay` Set node; credential
   `tradeai-run-relay` only. No `RELAY_HOST` placeholder (`scripts/check_n8n_import_ready.py`,
   `tests/test_n8n_import_guard_20261010.py`).
7. **A new relay route** is a relay PR (with `ROUTES` updated, so the contract check sees it) plus, if it forwards
   a new lane, a gateway unit change under `config-write` + `service` grants. n8n never gets a new credential,
   port or socket (§23.3, §23.5).

---

## 5. W0 / import procedure (any n8n import, publish or unpublish)

Packet: `~/n8n-maturity-verification/packets/w0-import-six/` (`README.md`, `import-six.sh`, `rollback.sh`).

1. **Dry run, and quote it.** `bash import-six.sh` (default dry run): JSON parses, id/file/sha256 match
   `INDEX.json`, `active=false`, relay-only URLs, no `RELAY_HOST`, `errorWorkflow` set, then **step 1b**
   `check_n8n_relay_contract.py` against a scratch relay from the served CURRENT (receipts:
   `dryrun-relay-contract-served-20261010.txt` REFUSED the served six; `...-fixed4-...` PASS for the fixed four).
2. **One `cron` grant naming every workflow id** (§23.11). A grant that lists fewer activates only those. Request
   it with `bin/guard request cron --for <≤12h> --reason "<ids, PR, sha, packet>"`.
3. **Import inactive**: `TRADEAI_W0_GRANT=<id> bash import-six.sh --apply` (expects `imported_inactive=N`).
   Re-import over inactive rows with `W0_REIMPORT=1` (refuses if any row is active, published or foreign).
4. **Publish** each id (`docker exec m8m-n8n n8n publish:workflow --id=<id>`), then **restart** n8n — a CLI publish
   loads only at start.
5. **Verify with durable evidence, never the n8n status.** Successful executions are soft-deleted
   (`EXECUTIONS_DATA_SAVE_ON_SUCCESS=none`) and keep `status = 'running'`. Read:
   - `SELECT id, active FROM workflow_entity WHERE id LIKE 'tradeai-%'`;
   - `SELECT "workflowId", status, count(*) FROM execution_entity WHERE "deletedAt" IS NULL GROUP BY 1, 2` (errors
     only appear here);
   - relay `data/runtime/n8n_relay/relay_log.jsonl` `op: due` lines every minute, `op: event` lines;
   - coordination ledger `runs` rows (`RunReceipt@v2`, `state`, `mode`);
   - `python3 scripts/check_n8n_activation_grants.py` (every activation reconciled against `guard log`) and
     `check_lane_registry --n8n-live --fail-on-new`.
6. **Rollback** = `rollback.sh --apply [id ...]`: unpublish, restart, then archive through n8n's own archive
   endpoint. Never delete. On 2026-10-10 the six were imported inactive and published at 15:53 ET and unpublished
   at 15:58 ET (grant f9c459a230d3bc58; `apply-20261010.txt`, `rollback-unpublish-20261010.txt`). The re-run waits
   for the release carrying #1663/#1664 and imports the four whose filters are served.

---

## 6. Executor v2 (live since 2026-10-10 13:07 ET)

- **Setting:** drop-in `~/.config/systemd/user/tradeai-n8n-run-executor.service.d/10-executor-v2.conf`,
  `Environment=TRADEAI_N8N_EXECUTOR_WORKERS=3` (operator "go executor v2", service grant eebd4ca0a6b31bd2). The
  repo unit sets no value, and a promote restarts the unit with the drop-in in place, so v2 survives promotes.
- **Caps** (`config/n8n_retry_policies.json#class_caps`): global 3, `heavy` 1, `llm` 1, `ingest` 1, `send` 1,
  `pipeline` 2, `learn` 1; the last free worker takes only priority ≤ 1 (`reserved_priority_max: 1`), so 3 workers
  are 2 general + 1 reserved. Per-lane exclusivity: `claim_next_v2` never claims a lane with a RUNNING row.
- **Reaper:** a RUNNING row past `started + timeout_s + 120 s`, or whose dead owner's heartbeat is stale beyond
  90 s, ends `RUN_TIMEOUT / executor_lost` (closed the 14 h orphan `-1552` class, RC2).
- **Verify:** `data/runtime/n8n_run_executor_last.json` is `ExecutorStatus@v1` with `workers: 3`; ledger rows carry
  `RunReceipt@v2` and a `worker_id`; overlapping `started_at`/`finished_at` pairs prove concurrency
  (`packets/executor-v2-evidence/enable-20261010.log`: 2 overlapping pairs at 17:15Z).
- **Rollback:** set the drop-in value to `1` (the tested v1 flag) and restart under a `service` grant; never delete
  the drop-in (`docs/ops/ROLLBACK_COMMANDS.md`).
- **Before adding a heavy or slow lane**, check the caps: one 300 s lane on one worker delayed three live lanes by
  4 m 42 s on 2026-10-10 13:11Z (V8 W1).

---

## 7. Monitoring, SIEM, Telegram and LLM remediation — summary

Full procedure, per lane, in the companion `N8N_MONITORING_AND_REMEDIATION_STANDARD.md`. In short:

- **SIEM:** `scripts/n8n_siem_bridge.py` is the single writer of `system_health_events` rows with component
  `n8n:<lane>` (one active row per lane + kind, self-resolving). Severity comes from the registry row `severity`,
  else the fan-in priority; only 2 of 619 registry rows carry one, so RUN_* failures land WARN today (L6 gap).
- **Diagnoser:** `scripts/n8n_failure_diagnosis.py` diagnoses catalogue lanes through the governed bridge
  (grok OAuth → chatgpt OAuth → deepseek FAST; $0.05/call, $0.10/day, 40/day, ≤ 3 per lane per day), runs only an
  auto catalogue action (`rerun_dry_run`, `reap_orphan_run`), excludes `trade-ai-scalp-live`, and runs behind
  `run_with_deepseek_offpeak.sh --scheduled --defer-in-process` (#1652) so it writes a deferred receipt off-peak.
- **Telegram:** only `scripts/incident_notifier.py` (cron L1052, live since 2026-10-09 23:34 ET) on the SYSTEM ops
  family: P1 at once and never capped, P2 batched every 30 min and held 22:00–07:00 ET, 24 messages/day cap for
  everything but P1, P3 never sends. No lane and no n8n node sends.
- **State 2026-10-10:** bridge and diagnoser rows merged PAUSED (#1657); install staged by the operator ruling
  (bridge first, diagnoser ~2 h later), not yet installed.

---

## 8. LLM configuration — the source of truth

- **`config/llm_process_registry.json` is the source of truth** for every process (allowed lanes, caps, schema).
  Enforcement already reads it (`get_process_config`, `check_cost_cap`).
- **The DB table `llm_process_config` is seeded from it** by `scripts/lib/llm_consumption.py` `_seed_registry`
  (:146): a new row gets the registry lanes and cap; an existing row gets a NULL cap filled; a non-NULL cap is never
  overwritten (the operator's `/caps` path stays authoritative); existing lanes are never rewritten (#1651, RC3).
  A divergent existing row is corrected only by a reviewed, compare-and-set packet under `db-write` with operator
  intent (`packets/llm-seed-sync/`, applied 2026-10-10 16:27 ET for `n8n_lane_failure_diagnosis`); the other
  divergent rows are listed in `divergence-20261010.txt` and left for the operator.
- **Scheduled paid work is deferred off-peak, not dropped.** The crontab header sets `LLM_DEFER_OFFPEAK=1` for every
  cron line (crontab line 9, "ARMED globally for cron 2026-09-20 (operator)"), and systemd units set it per unit
  (drop-ins on portfolio-server, cio-reactive, nightly-reflection; `Environment=` in the executor and health-tick
  units; the Hermes CIO worker sets `0`). A lane that wraps itself in `run_with_deepseek_offpeak.sh` without
  `--defer-in-process` still PEAK_SKIPs and exits 0 with no receipt. Two copies of the wrapper exist: 17 active
  crontab lines call `~/.config/tradeai/bin/run_with_deepseek_offpeak.sh` (2026-08-21, no `--defer-in-process`),
  2 call `$PROJ/scripts/run_with_deepseek_offpeak.sh` (measured 2026-10-10; open finding). A new lane uses the repo
  copy.

---

## 9. Testing rules

1. **Always `TRADE_AI_CI=1`.** A `@needs_db` test run without it wrote `hdi2test` rows to five live tables on
   2026-10-10 (RC7). Tests use fake connections, `tmp_path` stores and scratch ledgers; none touches the live DB,
   Telegram, n8n, the live relay, gateway or ledger.
2. **Stand-in drivers only when the real one is absent** (`try: import psycopg2 except ModuleNotFoundError:` install
   a minimal stand-in), so the test still runs in CI instead of being skipped, and never shadows the real driver
   on the host (pattern: `tests/test_refactor_w1_materializers_20261010.py`).
3. **Prove the test with heavy deps blocked** (psycopg2, pandas, numpy, yfinance) as well as normally; a test that
   only passes with them installed will fail in required CI.
4. **A module imported under two names is two modules.** `lib.x` and `scripts.lib.x` have separate caches;
   refresh, patch or reset both aliases (commit 744290618, RC5; the same duplicate-cache bug is open in the
   production tagger).
5. **Every new test file is in `scripts/run_cio_hardening_ci.py` GATES** with an anchor comment, or
   `scripts/check_test_coverage.py --fail-on-new` fails.
6. **No real identifiers in tests.** The pre-push hardcoded-values scan blocked a push on the operator's real
   Telegram chat id that came from another session's commit (RC6, #1658).
7. **A test may not reach a mutation** — dry-run tests assert the write path is not called, not only that the exit
   code is 0.

---

## 10. Release, grants and approvals

1. Commit locally; push only with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` and operator intent (`AI_WORK_POLICY.md`);
   `n8nmat/*` branches have 4 pushes per tranche until 2026-10-12T23:59:59-04:00 (pre-push hook).
2. PR → Agent A review verdict on the program board → required checks green on the exact head → merge.
3. **Promote is the operator's**, only after main CI is green on the exact merged SHA. Merge is not deploy.
4. **Then** request the grant for the host step the PR needs (install, import, restart).
5. **Grants:** one per scope; the guard ledger holds one grant per tier (`.cursor/hooks/guard-lib.sh` :127–133,
   `.grants[$tier]`), and a new request for a scope supersedes the pending one (`scripts/lib/guard_remote_approval.py`
   :219–224). Ask for one scope at a time, for ≤ 12 h (`MAX_GRANT_SECONDS`, :92), naming the PR, the sha and the
   packet. **If the request is not visible in Telegram, re-send it** — on 2026-10-10 a tap never reached Telegram,
   and the re-sent request landed in seconds (RC10). Never route around a denial.
6. Every host change writes a receipt in its packet (`*-evidence/*.log`) and a change-log row in the cron
   inventory README.

---

## 11. Rollback per step (comment or flip, never delete)

| Step | Rollback |
|---|---|
| Registry stage / dispatch row | Registry PR back to the previous stage or `mode: off`; `_cutover.py rollback --lane <id>` re-enables the exact line and restores `scheduler_before` in one write |
| Allowlist entry | PR removing `live_arg` (back to shadow) or the entry; the gateway reloads on promote |
| Crontab line | Packet `rollback.sh` comments the line `# RETIRED <date> lane=… reason=… owner=… review_by=…`, or restores the pre-install snapshot by `cmp`-checked install under a `cron` grant |
| n8n workflow | Unpublish + restart, then archive (`packets/w0-import-six/rollback.sh`) under a `cron` grant |
| Executor v2 | Drop-in value `1` + restart (`service` grant) |
| Gateway lane | Remove `n8n-workflow-error` from the drop-in value + restart (`config-write` + `service`) |
| DB row (seed sync) | Restore the values printed by the packet's dry run, compare-and-set (`db-write`) |
| Ledger row | Backup copy beside it (`packets/ledger-1552/n8n_coordination_ledger.before-1552-close.*.sqlite`) |

---

## 12. The baseline as configured on 2026-10-10 (live facts)

| Fact | Value | Evidence |
|---|---|---|
| Policy | AGENTS.md 4.4.0 ACTIVE (ratified #1660 comment 20:04:37Z, ratification edit #1662) | `R1_STATUS`, `R1_SHADOW_SHAPE_STATUS` = ACTIVE in `lane_dispatch.py` :76, :100 |
| n8n execution data | `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none` — successes soft-deleted, status stays `running` | AGENTS.md §23.5; W0 README |
| Executor | v2, 3 workers, since 13:07 ET | drop-in `10-executor-v2.conf`, grant eebd4ca0a6b31bd2 |
| Gateway extra lanes | `incident-fanin research-intake n8n-workflow-error` since 16:27 ET | drop-in `20-workflow-error-lane.conf` |
| Relay routes | `/status`, `/due`, `/runs/<lane_id>/last`, `/run`, `/event` (POST /event on main via #1663, needs a promote) | `n8n_run_relay.py` `ROUTES` |
| Generic workflows | imported inactive; published 15:53, unpublished 15:58 ET (W0 rollback) | `packets/w0-import-six/` |
| Live per-lane n8n workflows | 4: `n8n-incident-fanin` (722fac0e043ea5c4), `n8n-pilot-dispatch` (078e8fcbea0c5020), `n8n-research-intake-consumer` (21fd15d5f8a4c4da), `crontab-snapshot-for-health-agent` (c0d4c7845e5c4fcc) | registry `kind: n8n` ACTIVE rows |
| Shadow rows | 36 on main (wave 1: 22, #1656; wave 2: 14, #1661); 19 R1 rows staged, activated by #1665 (OPEN) → 55 | registry `stage: shadow` |
| Flock for R1 learn lanes | L318, L314, L427 `flock -n` installed 16:20 ET (cron grant 08c0bb77ec898136; backup `~/.local/state/tradeai/backups/crontab-20261010T202023Z-pre-wave23-flock.txt`) | `packets/wave23-flock/` |
| Incident notifier | cron L1052, ACTIVE since 2026-10-09 23:34 ET | registry `incident-notifier` (#1654) |
| SIEM bridge, diagnoser | registry rows PAUSED (#1657), not installed | `packets/siem-diagnoser-schedule/` |
| Retry policies / caps | `config/n8n_retry_policies.json` | §3, §6 |
| Health contracts | 68 DRAFT (59 lanes, 6 generic, 3 host monitors) | `config/n8n_health_contracts.json` |

---

## 13. Lessons from 2026-10-10

| # | What happened | Rule it produced here |
|---|---|---|
| RC1 | A future `last_request` (2026-12-25) in `finviz_throttle.json` stalled every Finviz caller 300 s; the old `--dry-run` still fetched (#1648) | §2.1 dry run is write-free and fetch-free; state written by a wrong clock is discarded, not obeyed |
| RC2 | v1 executor stopped 3 s after start left run −1552 RUNNING 14 h; v1 has no reaper | §6 executor v2 with reaper is the baseline; never restart the executor while a lane runs |
| RC3 | Diagnoser DB row had table-default lanes and a NULL cap (#1651) | §8 registry is the source of truth; seed never overwrites an operator cap |
| RC4 | Off-peak wrapper PEAK_SKIP exits 0 with no receipt → false P1 nightly (#1652) | §8, companion §5: LLM lanes use `--scheduled --defer-in-process` |
| RC5 | `company_name_index` imported as `lib.` and `scripts.lib.` → two caches; CI-only failure | §9.4 refresh both aliases |
| RC6 | Operator's real Telegram chat id in a test from another session | §9.6 no real identifiers |
| RC7 | `@needs_db` test without `TRADE_AI_CI=1` wrote to the live DB | §9.1 always `TRADE_AI_CI=1` |
| RC8 | W0: `bad_lane_filter` 403 and `POST /event` 404 within 4 minutes; rows "running" were soft-deleted successes | §4.1–4.2, §5.5 registry lane names, served routes, verify with `deletedAt IS NULL` |
| RC9 | W0 dry run checked URLs, not served paths/lanes | §5.1 relay contract check is step 1b of every import |
| RC10 | A Telegram approval tap never arrived | §10.5 re-send a request that is not visible |

Other open findings carried here: crontab-wide `LLM_DEFER_OFFPEAK=1` (now stated in AGENTS.md §12); the older
wrapper copy in `~/.config/tradeai/bin`; inotify watch exhaustion on executor restarts; R1 admission trusts a
declared `llm_route`; lanes that load the whole `.env`; checkout-relative paths; the remediation catalogue is stale
against the host inventory (REMEDIATION_PLAN §8).
