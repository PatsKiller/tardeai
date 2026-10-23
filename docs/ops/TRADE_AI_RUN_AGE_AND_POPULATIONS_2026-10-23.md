# Trade AI: the run's age and its two populations (2026-10-23)

Operator, 2026-10-23 08:54 ET, with screenshots of `/v3/trading`:

- **Header and tiles disagreed.** The header read `SETUPS · LATEST RUN: 0 GO · 0 WAIT · 7 NOGO · 17 scanned · 10 manual review`. The page tiles read `0 GO · 19 WAIT · 71 MANUAL REVIEW`.
- **"7:00 AM scan" read as two hours stale.** In a micro-scalp window, that is too long.

## What the numbers actually were

| Surface | Population | Source |
|---|---|---|
| Header `SETUPS · LATEST RUN` | The **latest run** only: 17 scanned, 0 GO / 0 WAIT / 6–7 NOGO / 10–11 review | `setup_run_summary` (SetupRunSummary@v1, `trade_ai_orchestrator:run_summary`) |
| Trade AI tiles (GO / WAIT / Manual review) | **Today's universe**: every row any run surfaced today, at its latest decision (110 rows: 65 MANUAL_REVIEW, 26 AVOID, 19 WAIT) | `/api/v2/trade-ai/scanner` → `tickers[]` |

Both were correct, but neither said which population it counted.

Slot `0700` is **re-run** through the morning. `run_history` shows attempts finishing at 08:02, 08:21, 08:35 and 08:52 ET, all labelled `0700`. The page was showing the 08:52 attempt, about four minutes old, under a "7:00 AM" label. The slot names the schedule, not the data.

## Changes

- **New pure helper:** `apps/command-center-v3/src/lib/scanRunAge.ts`, with its test `scanRunAge.test.ts` in `npm run build`.
  - It returns the finished time in ET, the age in whole minutes, and the slot label with a ` · re-run` mark when the run finished more than 30 minutes after its slot.
  - Tone: Mon–Fri 06:00–12:00 ET, **amber over 5 min, red over 10 min**. Outside the window the age is neutral.
  - A stamp with no timezone gives "age unknown" in amber. It is never assumed to be UTC or ET.
- **Trading → Trade AI run line** now leads with `Latest run finished 08:52 ET · 4 min ago`.
  - The line is `data-testid="ta-run-age"` and carries `data-run-age-min` and `data-run-age-tone`. It shows `▲` and red when stale.
  - A second line names both populations: `latest run: 17 scanned · 0 GO / 0 WAIT / 6 NOGO / 11 review · universe: 110 rows today (all runs) — the tiles below count this`.
- **Page tiles:** the GO, WAIT and Manual review hints read `today's universe · N rows`. Their tooltip explains that the header counts the latest run only.
- **Header SETUPS tile:** an aged run leads the meta line and drives the tile tone. The face shows `finished HH:MM ET · N min ago` and `slot 0700 · re-run`. The tooltip opens with "Latest run only — the Trade AI tiles count today's whole universe". The drill rows carry `run_finished_et`, `run_age_min`, `run_age_tone` and `run_slot_rerun`.
- **e2e:** `trade-ai-opportunities.spec.ts` asserts both population labels and the age chip. It checks red (`bad`) at 17 minutes on the page and in the header, and `ok` at 3 minutes. The spec is now gated in `cc-surface-agreement-ci.yml`. The `run_health_agreement` data attributes are unchanged.

## Not in this change

- **Cadence.** The 0700 slot re-runs roughly every 15–20 minutes, not every 5. Wiring the 5-minute scalp lanes into this page is owned by the cadence work item. This change only makes the age visible and loud.

Authority: READ_ONLY_ADVISORY presentation change. No API, broker, Telegram or DB effect.

## Follow-up: the served scan clock wins (stacked on this PR, pairs with cadence PR #1992)

The page's rows come from the continuous runner's scan cycles (`trade_ai_scans`). They do not come from the hourly
run summary, which those cycles never rewrite. The extra 08:18, 08:32 and 08:50 "0700" attempts were health-agent
re-runs.

When the API serves `scan_freshness` / `latest_scan_at` (#1992), `payloadRunAge` in `src/lib/scanRunAge.ts`
takes the age from the newest scanned row and labels it "Data: latest scan HH:MM ET · N min ago". The server's
`STALE` status (over 10 minutes inside 06:00–12:00 ET) forces red. Without that field it falls back to
`latest_run_timestamp`, which is this PR's behaviour.
