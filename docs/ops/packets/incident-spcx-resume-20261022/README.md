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

> **2026-10-22 operator run: steps applied but verify falsely reported FAILED (SIGPIPE under pipefail); fixed in
> PR #1965.** The verify was `crontab -l | grep -qxF -- "$line"` under `set -euo pipefail`. `grep -q` stops at the
> first match, `crontab -l` is killed by SIGPIPE writing the rest of the ~174 KB crontab (exit 141), and pipefail
> fails the whole check although the line is present. For every step the crontab ended exactly as intended.
> Both scripts now read back once into a file (`crontab -l > "$WORK/after-installed.<step>"`) and grep the file.
> The same pattern is fixed in the hermes learning/tune/feedback cutovers and the hermes-scorer canary retire step.
> `tests/test_packet_verify_sigpipe_20261022.py` runs the real verify blocks against a >200 KB fake crontab that
> dies on SIGPIPE, and lints every pipefail packet script for `crontab -l |` into an early-exit reader.

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
| sync-social-to-intelligence (L875) | 9 RUN_DONE | **yes, 9 of 9 slots** (e.g. 10-22 cron 11:30:09, n8n 11:30:18) | **this script**: comment the cron line (n8n proven) |
| materialize-watchlist-strategy-cards (L219) | 35 RUN_DONE, 67 SKIPPED_LOCK | **yes, 33 slots** | **this script**: comment |
| hermes-discovery-scorecard (L845) | 4 RUN_DONE, 3 SKIPPED_LOCK | **yes, 10-19, 10-21, 10-22** (10-18 unproven) | **this script**: comment |
| opening-intelligence-render (L804) | 1 RUN_DONE, 4 SKIPPED_LOCK | **yes, 10-22 09:15** (one duplicate jsonl row) | proposed: a staged effect key (`cron_claim`/`n8n_claim` false) in its cutover packet, then the usual arming order — see below |
| job-coverage-monitor (L391) | 1 RUN_DONE, 1 SKIPPED_LOCK | **yes, 10-21 20:30** (read-only report; a duplicate costs time, not data) | none now; comment the cron line once n8n has >= 3 live runs |
| classify-instruments (L506) | 1 RUN_DONE | no (n8n won the 10-17 lock race; cron log last 10-10) | none now (overwrite-only); same rule |
| finviz-enrichment (L144) | 0 RUN_DONE, 4 SKIPPED_LOCK | no (cron always wins the lock) | none now; n8n has never completed a live run |
| finviz-sector-research (L526) | 0 RUN_DONE, 9 SKIPPED_LOCK | no (cron always wins the lock) | none now; same |
| maturity-remeasure (L1016) | dry_run only | no (n8n never ran it live) | no crontab change: take it off the relay live list with `docs/ops/packets/maturity-remeasure-relay-live-removal-20261015/` |

```bash
bash docs/ops/packets/incident-spcx-resume-20261022/double-run-operator.sh --preview
bash docs/ops/packets/incident-spcx-resume-20261022/double-run-operator.sh            # then "type APPLY" once
```

The script re-reads the ledger and refuses a lane with fewer than 3 live `RUN_DONE` since 10-14. It prefixes each line
with `# N8N-OWNED 2026-10-22 double-run fix (n8n live RUN_DONE proven; cron side retired) `, so the line is kept.

**Why there is no effect-claim wrap in this packet (a finding against the 10-22 plan).** The plan offered "wrap the
cron line in the effect claim" for the unproven lanes. The repo's canary effect-key process rules that out here:
- `tests/test_effect_claim_20261014.py::test_committed_effect_config_changes_no_live_run_at_merge` forbids a key that
  changes a live run at merge. An armed key refuses every n8n run (`effect_no_owner`) until an owner row exists.
- `tests/test_canary_effect_keys_20261015.py` forbids keying overwrite-only or read-only lanes, which covers
  job-coverage-monitor and classify-instruments.
- The wrapper `scripts/effect_claim_cron.sh` exits 65 and runs nothing for an unkeyed lane.

So wrapping is a per-lane cutover packet: a staged key, then `set-owner --owner cron`, then `cron_claim` true plus
the wrapped line, then `n8n_claim` true. Only opening-intelligence-render needs it, because it appends.

## 3. Registry truth (in the same PR)

- **15 paused-line rows → `PAUSED`**, each with `state_since`, the exact prefix, the incident id and `review_by`
  2026-10-29. `schwab-position-sync` (L501) is flipped by PR #1927, so this PR leaves it alone to avoid a conflict.
  `options-chain-snapshot` is one row for L772 + L778.
- **The 7 disabled timers are not changed (a finding against the 10-22 plan).** db-retention, the user
  systemd-tmpfiles-clean, agent-runtime atlas, concierge, hermes and pulse, and iris-taxonomy are already recorded as
  `state ACTIVE`, `status DISABLED_UNRULED`, `operator_decision_pending true`. That is the registry's deliberate
  shape for "found disabled, not yet ruled": `tests/test_expected_services_lane_states_20261008.py` pins it, so a
  disabled timer stays a finding and never becomes "expected off" without an operator ruling.

  Measured 2026-10-22 with `systemctl --user is-enabled` / `is-active`: all 7 disabled and inactive, and the 4
  runtime timers never triggered since boot. The ruling stays with the operator:
  - RETIRED proposed for db-retention, now inside `tradeai-platform-maintenance-nightly`;
  - iris-taxonomy waits on decision O-4;
  - systemd-tmpfiles-clean is OS-owned.
- **L214 → a new `RETIRED` row `sync-docs-to-drive`**, superseded by `drive-syncs-hourly`.
- **Live-list mismatches, documented in `live_list_note`, not changed:**
  - `release-train-request-*` is intended by H.0.
  - `maturity-remeasure`: the stale side is the host live list.

Generated rows that changed state were adopted (`adopted_from_generator`), so `reconcile_lane_registry.py` cannot
reset them. The committed file is the generator's fixed point.

**Host finding, not from this PR.** `tradeai-release-train-claim.timer` is enabled but undeclared, so
`check_lane_registry.py --fail-on-new` fails on this host for origin/main as well. The release-train packet installed
it, and its registry row belongs to that packet.
