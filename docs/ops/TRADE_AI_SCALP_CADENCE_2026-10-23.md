# Trade AI scalp cadence: 5 minutes from 06:00 to 12:00 ET (2026-10-23)

**Operator, 2026-10-23 (P1):** "So these are supposed to be running like every 5 minutes. Or so we can't
have that long of a period on micro scalps."

At 08:54 ET the Trade AI Opportunities page said "Run 2026-10-23 · 7:00 AM slot". The operator read
that as a scan nearly two hours old.

## What feeds the page (traced 2026-10-23, read-only)

```
continuous_runner.py   (system unit tradeai-continuous.service, timer 04:00 Mon-Fri,
                        runs the canonical checkout's linux_launchers/run_continuous.sh)
  ├─ LIVE cycle  → finviz_ingestion.download_screener_csvs (prime_setups, watchlist_setups)
  │               → score_all → trade_ai_scans rows (run_label = slot: 0400/0700/0900/1000)
  └─ FULL cycle (hourly anchors) → trade_ai_orchestrator.py → reports/<date>/<slot>/run_summary.json
warm_caches.py (cron */8) → api_v2.trade_ai(force=True) → data/runtime/trade_ai_cache.json
/api/v2/trade-ai/scanner and /api/v2/trade-ai/summary → the Trade AI page and the header SETUPS tile
```

- **The rows** come from `trade_ai_scans`. The query takes `DISTINCT ON (symbol)` with the latest
  `scanned_at` over today and yesterday. The scalp-live `scalp` label is included.
- **The run line**, made of `run_label`, `latest_run_timestamp` and `run_history`, comes from
  `run_summary.json`. Only FULL cycles write that file, plus the health agent's
  `rerun_trade_ai_orchestrator` remediation.
- On 10-23 the run-history attempts at 08:18, 08:32 and 08:50 ET, all labelled `0700`, were
  health-agent re-runs (`health_agent_remediation.jsonl`, strategy `rerun_trade_ai_orchestrator`,
  outcome INEFFECTIVE). They were not a schedule.
- "0700" is the **slot label** that `_best_run_label` gives to every cycle between 07:00 and 08:59.
  It does not mean the scan ran at 07:00.

### Why the page was 15–25 minutes behind

| Stage | Before | Worst-case added age |
|---|---|---|
| continuous_runner interval | 06–09 **15 min**, 09–10 10 min, 10–11 15 min, **hard stop 11:30** | 15 min (nothing after 11:30) |
| LIVE cycle duration | ~105 s (10-23 08:10: sleep 795 s of 900 s) | ~2 min |
| warm_caches `*/8` | cache recomputed every 8 min | 8 min |

The scalp lanes do refresh their Finviz CSVs every 2 to 5 minutes. But the page re-scores those
CSVs only when continuous_runner runs a cycle.

## Lanes checked (10-23, today's logs)

| Lane | Schedule | Runner | Ran today | Writes | Feeds the page? |
|---|---|---|---|---|---|
| finviz-momentum-scalp-early-lane | `*/5 6-11` | cron | yes (09:00:02 PASS) | Finviz screener CSVs (skips the refresh while the hot list owns it), strategy_signal_sync, proposals | Indirectly: the next runner cycle reads its CSVs |
| scalp-hot-list | `*/2 6-9` | cron | yes (08:58, 09:00) | Finviz scalp screener CSVs x4 | Indirectly, same as above |
| trade-ai-scalp-live | `*/5 9-15` | **cron** (lane_registry stage `canary`; n8n does not execute it) | cron fired at 09:00 and exited "outside RTH". Its own window is 09:30–16:00 | `trade_ai_scans` rows labelled `scalp` | Rows yes (DISTINCT ON). Run line no: it writes no run_summary |
| active-trader premarket-watch | `*/5 6-9` | cron | yes (09:00 as_of, 14 evaluated, 0 alerts) | `momentum_alerts` / AT premarket decisions | No: it feeds the AT alert feed and the L2 chips only |
| continuous_runner | timer 04:00, loop | system unit | yes, since 04:00 | `trade_ai_scans` (LIVE), run_summary (FULL) | **Yes: the producer** |

## Fix (this PR)

1. **continuous_runner:** 5-minute cycles across 06:00–12:00 ET (`SCALP_WINDOW`,
   `SCALP_CADENCE_MIN`). The hard cutoff moves from 11:30 to 12:00. FULL anchors stay hourly.
2. **Rewarm after each cycle:** inside the scalp window the runner starts
   `flock -n /tmp/warm_caches.lock warm_caches.py --only trade_ai` without waiting for it. That is
   the same lock as the `*/8` warm, so if that warm is already running this call skips.
   `--only trade_ai` recomputes only the scanner cache and writes its own `trade-ai-rewarm`
   receipt. It never writes the three-step `warm-caches` receipt.
3. **The scan's age is now published.** `latest_scan_at` is the newest `scanned_at` among the served
   rows. `scan_freshness` (contract `ScanFreshness@v1`) is recomputed on every serve and carries
   `age_sec`, `scalp_window`, and a `status`:
   - `FRESH`, or `STALE` when the scan is more than 10 minutes old inside the window;
   - `OFF_WINDOW` outside the window;
   - `UNKNOWN` when there is no timestamp.

   Both fields are on `/api/v2/trade-ai/scanner` and `/api/v2/trade-ai/summary`, for the page and
   the header to render as the run age, red when `STALE`.

**Worst-case age after this PR:** about 5 min of cycle plus about 2 min of cycle time plus about
0.5 min of rewarm, so roughly 7 to 8 minutes. That is under the 10-minute STALE line.

**Finviz load:** each LIVE cycle downloads 2 screeners through `finviz_throttle.acquire`. Going
from 15 to 5 minutes adds about 16 exports an hour in the morning. The scalp hot list already
makes about 120 an hour, so this is about 10% more under the same global throttle.

## Taking effect and operator steps

- **Crontab and n8n:** no change needed. Nothing in this PR edits a schedule or a live list.
- **When it takes effect:** the runner keeps its code in memory for the whole session. It runs the
  canonical checkout's launcher through `/etc/systemd/system/tradeai-continuous.service`, timer
  04:00 Mon–Fri. The change applies at the **first 04:00 start after the canonical checkout
  contains this PR** (the release source).
- **Applying it the same day** would need a restart of `tradeai-continuous.service`. That is an
  operator decision and is not recommended during market hours. The scan loop is advisory-only:
  it has no broker path and no order path.
- **Verification on the first morning:**
  - `grep -c "interval=5min" logs/continuous_$(date +%Y%m%d).log` is 12 or more per hour between
    06:00 and 12:00.
  - `data/runtime/trade-ai-rewarm_last.json` shows `status: ok` with a timestamp within the last
    5 minutes.
  - `curl -s 127.0.0.1:7777/api/v2/trade-ai/summary | jq .data.scan_freshness.status` returns
    `FRESH`.
- **Rollback:** revert this PR. The old values were 15/10/15 minutes and the 11:30 cutoff.

## Separate finding: page rows include yesterday's scans

`_compute_trade_ai` selects `run_date >= CURRENT_DATE - 1 day`, so the "universe" count includes
yesterday's `scalp` rows. That is part of why the tiles show 110 rows while the run shows 17. It is
reported to the alignment work and not changed here.
