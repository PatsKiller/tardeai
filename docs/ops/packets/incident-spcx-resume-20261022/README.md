# Incident SPCX resume packet and double-run fix (2026-10-22)

```
Status:      ACTIVE (operator packet, NOT RUN — an agent prepared it; the operator runs it)
as_of:       2026-10-22T13:00-04:00
Measured at: e8ce6e913 (origin/main) / served CURRENT 82180caba-main-exact-phase2-20261022-110850; crontab -l 2026-10-22
Approval:    operator 2026-10-22, "yes" to the 4-item proposal (resume packet, registry cleanup, double-run fix,
             incident close-out); Grok stop review: "switch on after your fix"
Incident:    docs/incidents/INCIDENT_20261014_SPCX_RESTING_STOPS.md; postmortem draft docs/incidents/POSTMORTEM_20261014_SPCX.md
```

Two scripts. Both are previews until you type the confirmation word, both take one crontab backup at start
(`~/.cache/crontab.bak-<UTC>`, never deleted), match every crontab line by its **exact text** (never by line number),
read the result back byte for byte, and stop at the first failure with the rollback command printed.

## 1. `resume-operator.sh` — resume the paused read/report lines

```bash
bash docs/ops/packets/incident-spcx-resume-20261022/resume-operator.sh --preview   # dry runs + diff, changes nothing
bash docs/ops/packets/incident-spcx-resume-20261022/resume-operator.sh             # same, then "type RESUME" once
bash docs/ops/packets/incident-spcx-resume-20261022/resume-operator.sh --only h    # one step later (Grok)
```

**Preconditions (refuses otherwise):** host `ms01-openclaw`, user `johnclaw`, `config/schwab_access_mode.yaml`
`mode: read_only` and `schwab_access_mode.mode()` = `read_only`, `trading_lock.lock_state(broker="schwab")` locked.
The global kill switch stays ON (operator decision); it blocks trading automation only, not these reads.

| Step | Lines | Dry run the script shows first (the script's own mode) | Note |
|---|---|---|---|
| a | L501 `schwab_position_sync`, L1036 `positions_sync --diff`, L1038 `positions_proof_daily` | `schwab_position_sync.py` (no `--apply`); `positions_sync.py --check-fresh` (rc 2 = stale, expected) | Proof has no dry-run mode; it restarts at day 1 |
| b | L468 `sync_basis_from_broker`, L469 `audit_position_basis` | no `--apply`; `--json` without `--alert` | |
| c | L794 `broker_stop_reconcile` | `--json` without `--apply` (report only) | Clears the 7 frozen broker entries in stops.json |
| d | L652 `stop_drift_alert` | no `--send` | |
| e | L784 `schwab_econfirm_reconcile` | `--days 10 --dry-run` (backfill check) | Prints the one-off `--days 10` command if 10-14/10-15 confirms are missing |
| f | L772 + L778 `options_chain_snapshot` | `--dry-run --limit 3` | |
| g | L896 `sweep_schwab_instruments` | `--limit 5 --json` (no `--apply`) | Weekly, Saturday 03:30 |
| h | L497 `grok_stop_review` | `--plan` (no model call, no write) | **Resumed by default only when the served release contains the spend-gate fix** (`PROCESS_ID = "grok_stop_review"` in `CURRENT/scripts/grok_stop_review.py`). Otherwise skipped, with `--only h` printed for later |
| i | L462 `schwab_stream_daemon` | none (any run streams and writes) | Last. Takes effect today only if resumed before 09:31 ET |
| retire214 | L214 `sync-docs-to-drive.py` | — | Stays commented; `# RETIRED 2026-10-22 superseded-by drive-syncs-hourly …` put in front (archive note) |

**Kept paused, asserted untouched:** L774 defense fills, L781/L782 options lifecycle, L558 coder_dispatch.

Every Schwab-reading dry run reads Schwab (GET only) from the served release with `.env` sourced inside its own
shell, as the cron line does. Under AGENTS.md §24.11 an agent may not run these; the operator does.

**After it runs:** an agent PR flips each resumed row in `config/lane_registry.json` back to ACTIVE with that day's
`state_since` (PR #1927's `DECLARED_OFF_CRON_LINE_ACTIVE` reports them until then). If Grok was resumed:
`python3 scripts/sync_cio_process_caps.py` and a `cio-governed-bridge` restart (§9.2).

## 2. `double-run-operator.sh` — stop cron and n8n both running one slot

Measured 2026-10-22 (read-only: coordination ledger `mode=ro` + `PRAGMA query_only`, `data/runtime/<lane>_last.json`
receipts, cron log mtimes). The shared `flock -n` lock serialises cron and n8n; it does not dedupe them, so when
cron finishes first n8n runs the slot again a few seconds later.

| Lane (crontab line) | n8n live since 10-14 | Ran twice? | Fix |
|---|---|---|---|
| sync-social-to-intelligence (L875) | 9 RUN_DONE | **yes, 9 of 9 slots** (e.g. 10-22 cron 11:30:09, n8n 11:30:18) | Part A: comment the cron line (n8n proven) |
| materialize-watchlist-strategy-cards (L219) | 35 RUN_DONE, 67 SKIPPED_LOCK | **yes, 33 slots** | Part A: comment |
| hermes-discovery-scorecard (L845) | 4 RUN_DONE, 3 SKIPPED_LOCK | **yes, 10-19, 10-21, 10-22** (10-18 unproven) | Part A: comment |
| opening-intelligence-render (L804) | 1 RUN_DONE, 4 SKIPPED_LOCK | **yes, 10-22 09:15** (duplicate jsonl row) | Part B: wrap, owner cron |
| job-coverage-monitor (L391) | 1 RUN_DONE, 1 SKIPPED_LOCK | **yes, 10-21 20:30** | Part B: wrap, owner cron |
| classify-instruments (L506) | 1 RUN_DONE | no (n8n won the 10-17 lock race; cron log last 10-10) | Part B: wrap, owner cron |
| finviz-enrichment (L144) | 0 RUN_DONE, 4 SKIPPED_LOCK | no (cron always wins) | Part B: wrap, owner cron |
| finviz-sector-research (L526) | 0 RUN_DONE, 9 SKIPPED_LOCK | no (cron always wins) | Part B: wrap, owner cron |
| maturity-remeasure (L1016) | dry_run only | no (n8n never ran it live) | no crontab change: take it off the relay live list with `docs/ops/packets/maturity-remeasure-relay-live-removal-20261015/` |

```bash
bash docs/ops/packets/incident-spcx-resume-20261022/double-run-operator.sh --preview
bash docs/ops/packets/incident-spcx-resume-20261022/double-run-operator.sh --part A   # any time
bash docs/ops/packets/incident-spcx-resume-20261022/double-run-operator.sh --part B   # only after the release with the 5 keys is served
```

- **Part A** refuses a lane with fewer than 3 live `RUN_DONE` since 10-14, and prefixes the line with
  `# N8N-OWNED 2026-10-22 double-run fix (n8n live RUN_DONE proven; cron side retired) `.
- **Part B** refuses unless the **served** `config/n8n_effect_keys.json` has the lane armed (`cron_claim` and
  `n8n_claim` true). Before that release, a wrapped line exits 65 and runs nothing. For each lane it runs
  `effect_claim.py set-owner --process <lane> --owner cron`, checks the owner row, and only then wraps the line with
  `env TRADEAI_EFFECT_CLAIM=<lane> bash scripts/effect_claim_cron.sh <lane>`. From then on cron claims
  `fx:<lane>:<slot>:v1` and n8n skips the slot.
- **Window to know about.** From the moment the keys are served until `set-owner` runs, n8n live runs of the five
  lanes are refused (`effect_no_owner`, fail closed). The unwrapped cron lines keep running, so nothing is lost; only
  the duplicate stops.

## 3. Registry truth (in the same PR)

- **15 paused-line rows → `PAUSED`**, each with `state_since`, the exact prefix, the incident id and `review_by`
  2026-10-29. `schwab-position-sync` (L501) is flipped by PR #1927, so this PR leaves it alone to avoid a conflict.
  `options-chain-snapshot` is one row for L772 + L778.
- **7 disabled timers → `PAUSED`:** db-retention, user systemd-tmpfiles-clean, agent-runtime atlas, concierge,
  hermes and pulse, iris-taxonomy. Each was measured with `systemctl --user is-enabled/is-active` on 2026-10-22, and
  RETIRED is proposed for operator decision.
- **L214 → a new `RETIRED` row `sync-docs-to-drive`**, superseded by `drive-syncs-hourly`.
- **Live-list mismatches, documented in `live_list_note`, not changed:**
  - `release-train-request-*` is intended by H.0.
  - `maturity-remeasure`: the stale side is the host live list.

Generated rows that changed state were adopted (`adopted_from_generator`), so `reconcile_lane_registry.py` cannot
reset them. The committed file is the generator's fixed point.
