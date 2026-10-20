# Live changes — 2026-10-20

```
Status:      ACTIVE (dated record; superseded by any later measurement)
as_of:       2026-10-20T14:40:00-04:00
Measured at: origin/main 1d00a5181; served CURRENT f6f56e365-main-exact-phase2-20261020-125112
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
```

Everything merged or made live on 2026-10-20, with the status of each item and the evidence behind it. The
subsystem docs below carry the detail. This page links them.

Status words: **LIVE** = in the served release, or applied on the host and observed running.
**MERGED-NOT-SERVED** = on `main` but not yet in a promoted release. **PENDING** = an operator step that has not run yet.

## 1. Releases

| Commit | Promoted (ET) | Release dir | Status |
|---|---|---|---|
| `720fce06c` (merge of #1867, registry truth) | 08:58 | `720fce06c-main-exact-phase2-20261020-085604` | LIVE until 12:52, then superseded |
| `f6f56e365` (merge of #1866; includes #1882) | 12:52 | `f6f56e365-main-exact-phase2-20261020-125112` | **LIVE** (`portfolio-server/CURRENT` → this dir, link written 12:52:24 ET) |
| `1d00a5181` (merge of #1885; includes #1883, #1884) | — | — | **PENDING** promotion |

The relay and coordination gateway restarted with the 12:52 promote (`ActiveEnterTimestamp` 12:52:45 / 12:52:42 ET).

## 2. Merged PRs

| PR | Merged (ET) | What | Served? | Detail doc |
|---|---|---|---|---|
| #1882 | 11:15 | `scripts/pro_analyst_fetch.py` `prioritize()`: the 250/day cap goes to held → actionable → directive-watch oldest fetch first → never-fetched directive symbols in a per-day rotation → anything fetched in the last 20 h last. Cap 250 and the 06:10 schedule are unchanged. | LIVE (`f6f56e365`) | `docs/CHANGELOG.md` 2026-10-20 |
| #1866 | 11:15 | Trimmed to N1–N3. N1: the notifier says `NOTICE SETTLED`, not `RECOVERED`, unless `recovery_validator.output_recovered` proves a live output run. N2: Telegram settlements carry an explicit provider message id. N3: `GET /api/v2/communications/deliveries/summary` and the Comms hub delivery-health strip (UNAVAILABLE/STALE instead of 0). | LIVE (`f6f56e365`) | `docs/ALERT_INCIDENT_RESOLUTION.md` "Update 2026-10-20"; `docs/ops/COMMS_HUB_2026-10-07.md` "Update 2026-10-20"; `docs/ops/n8n_self_healing.md` (diagnosis cadence, updated by #1866) |
| #1883 | 13:06 | `tests/conftest.py` `pytest_assertrepr_compare`: a failing assertion with `os.environ` as an operand prints the name only, never the environment's contents. | MERGED-NOT-SERVED (test-only, no runtime effect) | `docs/CHANGELOG.md` 2026-10-20 |
| #1884 | 14:15 | Plausibility BLOCK writers: `scalp_critic_agent.validate_catalyst` clamps `catalyst_confidence` to [0, 1]; `/api/v2/indicators/batch` upsert refreshes every scalar column on conflict (incl. `stop_price`); `etf_performance_enrich` selects targets stalest `perf_updated_at` first. | MERGED-NOT-SERVED | `docs/CHANGELOG.md` 2026-10-20 |
| #1885 | 14:27 | Comms: a delivery is reserved only for an OUTBOUND event that named its channel (`AssumedChannels`, `should_reserve_delivery`); new `reap_stale_reservations()`; `comms_lifecycle.py --steps reservations` is **opt-in** and **not** in the hourly defaults. | MERGED-NOT-SERVED | `docs/ops/COMMS_HUB_2026-10-07.md` "Update 2026-10-20"; `docs/runbooks/DB_RETENTION.md` |

## 3. n8n lanes added to the relay live list

`TRADEAI_N8N_RELAY_LIVE_LANES` in `~/.config/tradeai/n8n-live-lanes.env` went from 54 to 59 lanes (names read only).
Each write left a backup named after it:

| Lane | Added (ET) | Backup written before the change | First live evidence |
|---|---|---|---|
| `disk-usage-monitor` | 09:58:37 | `n8n-live-lanes.env.bak-20261020T135837Z-disk-hygiene-n8n-live` | `data/runtime/disk-usage-monitor_last.json` run `d:disk-usage-monitor:live:20261020T1430`, `code_sha` f6f56e365, `produced_count 2` |
| `disk-hygiene` (`--plan`, deletes nothing) | 09:58:37 | same | PENDING: next slot Sun 2026-10-25 04:00 ET |
| `tmp-hygiene` (`--plan`, deletes nothing) | 09:58:37 | same | PENDING: next slot 2026-10-21 05:00 ET |
| `active-trader-motion-watchdog` | 09:58:42 | `...bak-20261020T135842Z-motion-watchdog-live` | `data/runtime/active-trader-motion-watchdog_last.json` run `d:active-trader-motion-watchdog:live:20261020T1435`, band HEALTHY |
| `registry-runtime-truth` | 10:23:28 | `...bak-20261020T142328Z-registry-truth` | PENDING: next `20 7 * * *` slot (no `registry-runtime-truth_last.json` yet) |

Packet READMEs, Status lines updated to LIVE:
`docs/ops/packets/disk-hygiene-n8n-20261018/README.md`,
`docs/ops/packets/active-trader-motion-n8n-20261019/README.md`,
`docs/ops/packets/registry-runtime-truth-20261018/README.md`.

### Active Trader motion runtime

`tradeai-active-trader-motion.service` was installed with the fixed gate line
`ConditionPathExists=/etc/tradeai/enable-active-trader-motion` (the marker is root-owned, created 2026-10-19 11:18 ET).
It was started at 10:00:33 ET under the operator's `--force-open-hours` override. The session was open, so §24.10's
closed-session rule needed the override. The packet's `proof` step reported PASS in the operator's session. Read back
at 14:35 ET:
`systemctl --user show` reports `ActiveState=active`, `SubState=running`, `ConditionResult=yes`. The watchdog state
(`ActiveTraderMotionWatchdogState@v1`) says `last_band HEALTHY` since 14:05:02Z, `marker_present true`, heartbeat age
28.8 s. The heartbeat's `cycle_count` is 209,816 (209,263 at the 2026-10-10 stop).

## 4. Operator data remediations (archive-first)

Both ran under `scripts/db_trim.py` conventions: an archive under
`~/trade-ai-releases/persistent-state/archive/db_trim/<stamp>/`, plus a record in
`archive/db_trim/TRIPWIRE.jsonl`, which `retention_tripwire` reads every night (`docs/runbooks/DB_RETENTION.md`).

| Stamp | Table | Rows | What | Tripwire record |
|---|---|---|---|---|
| `20261020T165931Z` | `analyst_data_history` | 531 | Empty-payload rows (`as_of >= 2026-10-18`, payload NULL / `null` / `{}` / `[]`) written by pre-fix dev-checkout code. Archived to `rows_analyst_data_history.jsonl.gz`. Clears the `retired_store` BLOCK. | `kind rows`, `why: retired_store BLOCK: empty rows from pre-fix dev checkout` |
| `20261020T173035Z` | `communication_deliveries` | 205 | Stuck RESERVED reservations with no owner, settled from evidence: CANCELLED 150 (INBOUND), SUPPRESSED 52, SENT 3 (twin provider ids went to `provider_coordinates` only). Pre-image archived to `rows_communication_deliveries_stuck.jsonl.gz`. | `kind rows_settled`, `by_new_status {SUPPRESSED 52, CANCELLED 150, SENT 3}` |

The 205 were settled **before** the #1885 reaper is ever enabled. Run in the other order, the reaper would have marked
the 55 outbound copies EXPIRED.

## 5. Open after today (operator)

- Promote `1d00a5181` (serves #1883, #1884, #1885).
- After that promote, run #1884's archive-first in-place correction for existing rows. Its dry run gave: scans 720 →
  1.0, stops 34 → NULL, ytd 11 NaN → NULL.
- Add `reservations` to the hourly `comms-lifecycle` steps only after the cron-inventory row for `comms-lifecycle` is
  approved (operator freeze 2026-10-09).
- AGENTS.md §24.10 item 4 still states the 2026-10-10 misspelt marker path. A PATCH draft is in
  `docs/ops/packets/active-trader-motion-n8n-20261019/AGENTS_PATCH_DRAFT.md`. Its precondition, that the fixed unit is
  installed, is now met. Applying it needs the operator's per-PR word (§20).
- Carried from #1882: `--max` around 400 to cover every directive symbol weekly (a cron change).
- Carried from #1883: rotate the Alpaca secret key that appeared in a local test log.
