# CIO prospect shadow build — comparison vs today's surfaces, and the NAVN round trip (2026-10-22)

```
Status:      SHADOW EVIDENCE — input to the operator's §17 decisions (AGENTS.md §26); nothing here is live
as_of:       2026-10-22T20:52:10Z (16:52 ET, after the close, so expires_at = evidence_at + 26 h)
Measured at: scripts/cio_prospect_shadow_build.py --dry-run --compare --state-root ~/trade-ai-releases/persistent-state
             --captured-inputs <NAVN capture> (read-only file inputs; no DB session; no store written).
             Watch top ideas: ONE read-only GET of /api/v3/data-broker/watch-intelligence?view=top_ideas&page_size=50
             at 19:45:51Z (rank top_ideas.v2). NAVN round trip: ONE read-only GET of /api/v2/journal?symbol=NAVN
             (trade_closed srt:607228); NAVN daily closes: ONE GET of /api/v3/opportunities/NAVN (chart.bars);
             NAVN observed stop path: the coordinator's relay of the operator's read-only stop_lifecycle read.
```

Architecture: [`CIO_PROSPECT_DATA_FOUNDATION.md`](CIO_PROSPECT_DATA_FOUNDATION.md) §7 P1 and §11. Reproduce:
`.venv/bin/python scripts/cio_prospect_shadow_build.py --dry-run --compare --watch-surface-json <capture> --captured-inputs <capture> --report-md <out>`.
The NAVN inputs are also committed as the test fixture `tests/fixtures/cio_prospect/navn_20261022.json`.

**What this run did not read** (stated so nobody reads more into it): the DB inputs (decision_packets, cio_decisions,
cio_entry_states, trade_ai_scans, watchlist_items, operator_starred_symbols, schwab_round_trips, trade_transactions,
stop_lifecycle, trade_recommendation_links, ticker_prices) — the agent may not load DB credentials (§24.7); the lane
reads them with `--with-db` on a READ ONLY session. So: no prospect reached stage `actionable`, `scanner_score` is
empty, operator stars/adds are not yet protected members, and only NAVN (captured) carries a full lifecycle — the 19
other held positions show "origin n/a" because their buy fills were not read. `fused_score`, `catalyst_grade` and
`regime_fit` have no producer and are carried as missing components, never invented.

## Highlights

1. **NAVN — "it came from internal" is true, and the record now says so.** The 2026-10-19 11:01 ET buy at 25.64 links
   (learning-loop rules, `window_only`, 2.15% above the zone) to the CIO entry state **BUY_READY on 2026-10-16 13:40 ET**
   (zone 24.80–25.10, R:R 4.08, `cio_events evt-cb6ad4a5e735`). At the fill, **Home best opportunities showed it #4 at
   conviction 85.6, R:R 4.81** (assessment v26) and the Telegram conviction line read "Conviction 86/100 · #4". It was
   **#1 at 87.6 only on 10-22 at 11:30 ET** (v27, stance WATCH→ADD) — after the entry, four and a half hours before the
   exit. The "#1, conviction 88" in the brief is the exit-day value, not the entry-day one.
2. **NAVN exit: a trailing ratchet, in profit — and the stop-out reads as noise.** The observed stop moved 24.31 → 24.59
   → 24.70 → 24.97 → 25.51 → 25.61 → 26.02 (six ratchets); the last one FILLED at 26.02 on 10-22 15:59 ET. P/L
   **+$189.73 (+1.48%)**, 0.29 R on the initial stop, 0.22 R on the plan invalidation at entry (23.90). On a close
   basis the peak was 26.625 (10-21, +3.84%); the exit gave back 2.27% from it, and the exit-day close (26.03) is above
   SMA20 (23.14) and SMA50 (24.71): **noise, not a trend break** — the stop sat 2.27% under the peak. ATR and VWAP are
   not measured (no intraday high/low or VWAP in the stores read), and the record says so.
3. **NAVN re-entry advice (the desk's own classifier):** state **MISSING MARKET** — NAVN has no RSI row in the indicator
   snapshot, so the desk cannot say READY; price 26.02 is 3.7% above the zone. Conditions: conviction ≥ 70 met (86.6),
   thesis active, no wash window (a profitable exit opens none); waiting on a pullback into 24.80–25.10 with RSI 40–70
   or a close back above 26.02 on volume. Alert levels 25.853 (near), 25.10 (in zone), 26.02 (reclaim) → Watch
   "Re-entry near", one alert `reentry_near:<guid>:srt:607228` (described, not sent).
4. **Two conflicts the surfaces hide today:** the holdings file (updated 20:30Z) still lists 500 NAVN after the 19:59Z
   fill, and the curator still says `ADD` / owned at 20:30Z. Both are recorded on the prospect (`held`,
   `stance_after_exit`) — shown, never resolved — and NAVN's stage is `exit` / `exit_review` from the fill, not from the
   stale file. Home's best opportunities still list NAVN tonight.
5. **The NVDA case reproduces exactly:** held, stance `ADD`, two recorded conflicts (curator `ADD` vs thesis
   `symbol_nvda@v8` `watch`; instrument record `WATCH:NVDA` while held). In all, **23 prospects carry 28 conflicts**
   (22 stance, 3 subject_key_kind, 1 held, 1 stance-after-exit, 1 Hermes lifecycle). HOLD-vs-watch is deliberately not
   a conflict.
6. **Watch ranks something else entirely.** Of Watch's 22 top ideas (`top_ideas.v2`), only ANET, NVDA and SPCX are in
   the shadow top 50; the rest are held income/ETF names, because `top_ideas.v2` reads no CIO conviction or thesis.
   Moving Watch onto the prospect is the §17 "what is ranked onto an operator surface" decision.
7. **Identity is the gate:** 191 of 1,844 symbols have no CONFIRMED GUID and get no prospect ("identity unresolved",
   never a placeholder). **Watchlist curation (proposed, nothing written):** 205 kept, 1,192 would be proposed out
   under the proposed caps; held and exited names are protected.

## Build

- universe 1844 symbols → **1653 prospects** (one per security_guid); 191 identity unresolved (no prospect, by rule); 0 duplicate GUID aliases; 0 errors
- by stage: {"exit": 1, "held": 19, "re_entry": 43, "setup_forming": 349, "watching": 1241}
- **23 prospects carry 28 recorded conflicts** (shown, never resolved)
- held set: 23 symbols from `positions_context (holdings_accounts via lib.portfolio_positions)` (as_of 2026-10-22T20:45:13.498171+00:00); a held symbol without a CONFIRMED GUID has no prospect
- watchlist curation (proposed, nothing written): {"keep": 205, "propose_out": 1192}; by stage {"actionable": {"cap": 20, "members": 0, "over_cap": 0, "protected": 0}, "exit": {"cap": 20, "members": 1, "over_cap": 0, "protected": 1}, "held": {"cap": null, "members": 19, "over_cap": 0, "protected": 19}, "proposed": {"cap": 15, "members": 0, "over_cap": 0, "protected": 0}, "re_entry": {"cap": 25, "members": 43, "over_cap": 18, "protected": 0}, "setup_forming": {"cap": 40, "members": 349, "over_cap": 309, "protected": 0}, "watching": {"cap": 120, "members": 976, "over_cap": 856, "protected": 0}}

Sources read:

| source | status | rows | as_of |
|---|---|---|---|
| opportunity | ok | 1589 | 2026-10-22T20:30:18.765131+00:00 |
| theses | ok | 690 | 2026-10-22T17:41:22.252231+00:00 |
| spine | ok | 298 | 2026-10-22T20:51:26.149818Z |
| instrument_records | ok | 52 | 2026-10-22T20:02:12.656221+00:00 |
| reentry | ok | 93 | 2026-10-22T20:51:26.023391+00:00 |
| hermes | ok | 5646 | 2026-10-22T20:37:15.652955+00:00 |
| assessment_versions | ok | 1938 | 2026-10-22T20:30:18.546672+00:00 |
| entry_signals | ok | 229 | 2026-10-22T18:10:07.651485+00:00 |
| indicators | ok | 90 | 2026-10-22T20:50:13.965556+00:00 |
| scanner | ok | 538 | None |
| decision_packets | not_read (no read-only db_query injected) | 0 | None |
| cio_decisions | not_read (no read-only db_query injected) | 0 | None |
| entry_states | not_read (no read-only db_query injected) | 0 | None |
| scanner_db | not_read (no read-only db_query injected) | 0 | None |
| watchlist_items | not_read (no read-only db_query injected) | 0 | None |
| starred | not_read (no read-only db_query injected) | 0 | None |
| round_trips | ok | 1 | None |
| fills | ok | 0 | None |
| stop_history | ok | 1 | None |
| rec_links | ok | 0 | None |
| bars | ok | 1 | None |

## Comparison — top 50 shadow prospects + Home best opportunities + Watch top ideas

- subjects compared: 71 — **agree 55, differ 16**
- stance differences 1; conviction differences (≥10 pts) 5; subjects whose inputs disagree 13
- shadow top 50 ∩ Home (opportunity rank) top 50: 16
- Home best opportunities (preset top5): ['ASST', 'NAVN', 'BHVN', 'P', 'BRCC'] — in shadow top: ['ASST', 'NAVN', 'BHVN']
- Watch top ideas (captured watch_top_ideas.json (rank_version top_ideas.v2, generated_at 2026-10-22T19:45:51.705342+00:00, 22 top ideas)): ['ANET', 'NVDA', 'SPCX', 'V', 'PFLT', 'RTX', 'NOC', 'LDOS', 'CSWC', 'DT', 'BAH', 'BND', 'DIV', 'JEPI', 'AMANX', 'SCHD', 'SCHG', 'SRNE', 'XAR', 'XLB', 'XLI', 'ZETA'] — in shadow top: ['ANET', 'NVDA', 'SPCX']
- Telegram conviction line: scripts/lib/opportunity_alert.enrich reads the same projection; suppressed when older than 26h (projection age 0.36 h)

| symbol | shadow rank · stage · stance · conviction | Home rank · stance · conviction | Watch | Telegram line | verdict |
|---|---|---|---|---|---|
| ASST | #1 · setup_forming · WATCH · 82.9 | #2 · WATCH · 86.7 · **best** | — | Conviction 87/100 · #2 · WATCH | agree |
| PDSB | #2 · setup_forming · WATCH · 80.62 | #9 · WATCH · 82.1 | — | Conviction 82/100 · #9 · WATCH | agree |
| NAVN | #3 · exit · WATCH · 79.68 | #3 · ADD · 86.6 · **best** | — | Conviction 87/100 · #3 · ADD | stance: shadow WATCH vs home ADD; inputs disagree: held, stance_after_exit |
| BHVN | #4 · setup_forming · WATCH · 79.56 | #4 · WATCH · 85.0 · **best** | — | Conviction 85/100 · #4 · WATCH | agree |
| XRPN | #5 · setup_forming · WATCH · 77.98 | #1 · WATCH · 86.9 | — | Conviction 87/100 · #1 · WATCH | agree |
| NVDA | #6 · held · ADD · 76.72 | #82 · ADD · 77.6 | #2 | Conviction 78/100 · #82 · ADD | inputs disagree: stance, subject_key_kind |
| DHR | #7 · setup_forming · WATCH · 76.04 | #144 · WATCH · 75.6 | — | Conviction 76/100 · #144 · WATCH | agree |
| ELF | #8 · setup_forming · WATCH · 75.28 | #100 · WATCH · 76.9 | — | Conviction 77/100 · #100 · WATCH | agree |
| VST | #9 · setup_forming · WATCH · 75.08 | #32 · WATCH · 79.3 | — | Conviction 79/100 · #32 · WATCH | agree |
| HNGE | #10 · setup_forming · WATCH · 75.0 | #68 · WATCH · 77.9 | — | Conviction 78/100 · #68 · WATCH | agree |
| MCK | #11 · setup_forming · WATCH · 74.92 | #64 · WATCH · 77.9 | — | Conviction 78/100 · #64 · WATCH | agree |
| CDW | #12 · setup_forming · WATCH · 74.55 | #60 · WATCH · 78.0 | — | Conviction 78/100 · #60 · WATCH | agree |
| AJG | #13 · setup_forming · WATCH · 74.26 | #18 · WATCH · 80.2 | — | Conviction 80/100 · #18 · WATCH | agree |
| MDLN | #14 · setup_forming · WATCH · 74.12 | #189 · WATCH · 74.2 | — | Conviction 74/100 · #189 · WATCH | agree |
| HAFN | #15 · setup_forming · WATCH · 73.94 | #226 · WATCH · 73.5 | — | Conviction 74/100 · #226 · WATCH | agree |
| SYF | #16 · setup_forming · WATCH · 73.92 | #27 · WATCH · 79.5 | — | Conviction 80/100 · #27 · WATCH | agree |
| HAS | #17 · setup_forming · WATCH · 73.76 | #202 · WATCH · 74.0 | — | Conviction 74/100 · #202 · WATCH | agree |
| INDV | #18 · setup_forming · WATCH · 73.74 | #17 · WATCH · 80.2 | — | Conviction 80/100 · #17 · WATCH | agree |
| DCTH | #19 · setup_forming · WATCH · 73.52 | #115 · WATCH · 76.3 | — | Conviction 76/100 · #115 · WATCH | agree |
| TSM | #20 · setup_forming · WATCH · 73.52 | #178 · WATCH · 74.6 | — | Conviction 75/100 · #178 · WATCH | agree |
| SBET | #21 · setup_forming · WATCH · 73.26 | #336 · WATCH · 71.0 | — | Conviction 71/100 · #336 · WATCH | agree |
| SBS | #22 · setup_forming · WATCH · 73.26 | #155 · WATCH · 75.3 | — | Conviction 75/100 · #155 · WATCH | agree |
| TGS | #23 · setup_forming · WATCH · 73.26 | #85 · WATCH · 77.5 | — | Conviction 78/100 · #85 · WATCH | agree |
| DDOG | #24 · setup_forming · WATCH · 73.22 | #266 · WATCH · 72.5 | — | Conviction 72/100 · #266 · WATCH | agree |
| SPCX | #25 · held · ADD · 73.12 | #57 · ADD · 78.1 | #3 | Conviction 78/100 · #57 · ADD | inputs disagree: stance |
| ADIL | #26 · setup_forming · WATCH · 72.94 | #25 · WATCH · 79.6 | — | Conviction 80/100 · #25 · WATCH | agree |
| CCL | #27 · setup_forming · WATCH · 72.86 | #20 · WATCH · 80.0 | — | Conviction 80/100 · #20 · WATCH | agree |
| ATEC | #28 · setup_forming · WATCH · 72.84 | #29 · WATCH · 79.4 | — | Conviction 79/100 · #29 · WATCH | agree |
| ANET | #29 · re_entry · BUY_SETUP · 72.68 | #296 · RE_ENTER · 71.8 | #1 | Conviction 72/100 · #296 · RE_ENTER | inputs disagree: stance |
| SW | #30 · setup_forming · WATCH · 72.52 | #160 · WATCH · 75.2 | — | Conviction 75/100 · #160 · WATCH | agree |
| DLXY | #31 · setup_forming · WATCH · 72.46 | #67 · WATCH · 77.9 | — | Conviction 78/100 · #67 · WATCH | agree |
| J | #32 · setup_forming · WATCH · 72.42 | #52 · WATCH · 78.3 | — | Conviction 78/100 · #52 · WATCH | agree |
| MCD | #33 · re_entry · BUY_SETUP · 72.42 | #240 · RE_ENTER · 73.1 | — | Conviction 73/100 · #240 · RE_ENTER | inputs disagree: stance |
| AGI | #34 · setup_forming · WATCH · 72.32 | #367 · WATCH · 70.4 | — | Conviction 70/100 · #367 · WATCH | agree |
| PLTR | #35 · setup_forming · WATCH · 72.32 | #303 · WATCH · 71.7 | — | Conviction 72/100 · #303 · WATCH | agree |
| WMT | #36 · re_entry · BUY_SETUP · 72.28 | #165 · RE_ENTER · 75.1 | — | Conviction 75/100 · #165 · RE_ENTER | inputs disagree: stance |
| MSTR | #37 · setup_forming · WATCH · 72.22 | #7 · WATCH · 82.6 | — | Conviction 83/100 · #7 · WATCH | conviction: shadow 72.22 vs home 82.6 |
| ALLE | #38 · setup_forming · WATCH · 72.13 | #28 · WATCH · 79.5 | — | Conviction 80/100 · #28 · WATCH | agree |
| APEI | #39 · setup_forming · WATCH · 71.96 | #58 · WATCH · 78.1 | — | Conviction 78/100 · #58 · WATCH | agree |
| HITI | #40 · setup_forming · WATCH · 71.9 | #63 · WATCH · 77.9 | — | Conviction 78/100 · #63 · WATCH | agree |
| AGBK | #41 · setup_forming · WATCH · 71.86 | #54 · WATCH · 78.3 | — | Conviction 78/100 · #54 · WATCH | agree |
| MU | #42 · watching · WATCH · 71.85 | #385 · WATCH · 69.9 | — | Conviction 70/100 · #385 · WATCH | agree |
| CF | #43 · setup_forming · WATCH · 71.68 | #332 · WATCH · 71.1 | — | Conviction 71/100 · #332 · WATCH | agree |
| ASPN | #44 · setup_forming · WATCH · 71.48 | #277 · WATCH · 72.2 | — | Conviction 72/100 · #277 · WATCH | agree |
| DH | #45 · setup_forming · WATCH · 71.42 | #46 · WATCH · 78.5 | — | Conviction 78/100 · #46 · WATCH | agree |
| MH | #46 · setup_forming · WATCH · 71.42 | #81 · WATCH · 77.6 | — | Conviction 78/100 · #81 · WATCH | agree |
| AMTM | #47 · setup_forming · WATCH · 71.28 | #34 · WATCH · 79.2 | — | Conviction 79/100 · #34 · WATCH | agree |
| AEYE | #48 · setup_forming · WATCH · 71.18 | #230 · WATCH · 73.4 | — | Conviction 73/100 · #230 · WATCH | agree |
| SMMT | #49 · setup_forming · WATCH · 70.98 | #151 · WATCH · 75.4 | — | Conviction 75/100 · #151 · WATCH | agree |
| RARE | #50 · setup_forming · WATCH · 70.94 | #215 · WATCH · 73.7 | — | Conviction 74/100 · #215 · WATCH | agree |
| P | #131 · setup_forming · WATCH · 66.85 | #5 · WATCH · 84.6 · **best** | — | Conviction 85/100 · #5 · WATCH | conviction: shadow 66.85 vs home 84.6 |
| BRCC | #73 · setup_forming · WATCH · 69.82 | #6 · WATCH · 84.0 · **best** | — | Conviction 84/100 · #6 · WATCH | conviction: shadow 69.82 vs home 84.0 |
| V | #174 · held · HOLD · 66.05 | #749 · HOLD · 62.1 | #4 | Conviction 62/100 · #749 · HOLD | agree |
| PFLT | #439 · held · HOLD · 60.62 | #614 · HOLD · 65.3 | #5 | Conviction 65/100 · #614 · HOLD | agree |
| RTX | #550 · held · ADD · 58.18 | #173 · ADD · 74.8 | #6 | Conviction 75/100 · #173 · ADD | conviction: shadow 58.18 vs home 74.8; inputs disagree: stance |
| NOC | #683 · held · ADD · 55.97 | #142 · ADD · 75.6 | #7 | Conviction 76/100 · #142 · ADD | conviction: shadow 55.97 vs home 75.6; inputs disagree: stance |
| LDOS | #114 · held · ADD · 67.42 | #237 · ADD · 73.2 | #8 | Conviction 73/100 · #237 · ADD | inputs disagree: stance |
| CSWC | #544 · held · HOLD · 58.26 | #497 · HOLD · 67.7 | #9 | Conviction 68/100 · #497 · HOLD | agree |
| DT | #59 · re_entry · BUY_SETUP · 70.48 | #39 · RE_ENTER · 78.8 | #10 | Conviction 79/100 · #39 · RE_ENTER | inputs disagree: stance |
| BAH | #190 · held · ADD · 65.77 | #245 · ADD · 73.0 | #11 | Conviction 73/100 · #245 · ADD | inputs disagree: stance |
| BND | #1037 · held · HOLD · 48.66 | #1152 · HOLD · 50.5 | #12 | Conviction 50/100 · #1152 · HOLD | agree |
| DIV | #924 · held · HOLD · 51.22 | #1197 · HOLD · 49.0 | #13 | Conviction 49/100 · #1197 · HOLD | agree |
| JEPI | #618 · held · HOLD · 57.23 | #962 · HOLD · 56.5 | #14 | Conviction 56/100 · #962 · HOLD | inputs disagree: subject_key_kind |
| AMANX | #1330 · held · HOLD · 38.5 | #1225 · HOLD · 47.6 | #15 | Conviction 48/100 · #1225 · HOLD | agree |
| SCHD | #780 · held · TRIM_REVIEW · 54.2 | #1073 · TRIM · 52.9 | #16 | Conviction 53/100 · #1073 · TRIM | inputs disagree: stance |
| SCHG | #740 · held · HOLD · 55.03 | #1031 · HOLD · 54.0 | #17 | Conviction 54/100 · #1031 · HOLD | agree |
| SRNE | #321 · held · HOLD · 62.73 | #487 · HOLD · 67.9 | #18 | Conviction 68/100 · #487 · HOLD | agree |
| XAR | #1297 · held · HOLD · 40.35 | #1165 · HOLD · 50.0 | #19 | Conviction 50/100 · #1165 · HOLD | agree |
| XLB | #985 · held · HOLD · 49.97 | #1067 · HOLD · 53.1 | #20 | Conviction 53/100 · #1067 · HOLD | agree |
| XLI | #1047 · held · HOLD · 48.27 | #1061 · HOLD · 53.3 | #21 | Conviction 53/100 · #1061 · HOLD | agree |
| ZETA | #316 · re_entry · WATCH · 62.8 | #679 · WATCH · 63.7 | #22 | Conviction 64/100 · #679 · WATCH | agree |

## Positions — origin, lifecycle, post-exit review, re-entry (same record)

### NAVN — stage `exit` / `exit_review`, stance WATCH

- **Origin: internal** — From internal: cio_entry_state entry:evt-cb6ad4a5e735 (window_only); 3 surface(s) showed it before the entry fill. Link: `entry:evt-cb6ad4a5e735` (window_only, 2.151% from the plan zone [24.8, 25.1]).
- What the surfaces showed before the entry fill (2026-10-19T15:01:04+00:00 at 25.64):
  - Home · Best opportunities (preset top5): shown — rank 4, conviction 85.6, rr 4.81, stance WATCH (`data/cio/cio_opportunity_assessments.jsonl NAVN:v26`, 2026-10-16T13:00:13.526566+00:00)
  - Telegram · conviction line (opportunity_alert.enrich): shown — text Conviction 86/100 · #4 · R:R 4.81 · WATCH (`data/cio/cio_opportunity_assessments.jsonl NAVN:v26`, 2026-10-16T13:00:13.526566+00:00)
  - CIO entry state (Telegram HIGH CONVICTION ENTRY card source): shown — rr 4.08, state BUY_READY, entry_zone [24.8, 25.1], price 24.98 (`data/cio/cio_events.jsonl evt-cb6ad4a5e735`, 2026-10-16T17:40:13.617096+00:00)
- Fills: entry 25.64 at 2026-10-19T15:01:04+00:00 → exit 26.02 at 2026-10-22T19:59:21+00:00 (3 days); P/L $189.73 (1.48%); R None on the linked plan, 0.286 on the initial observed stop, 0.218 on the plan invalidation at entry (23.9).
- Observed stops: 24.31 → 24.59 → 24.7 → 24.97 → 25.51 → 25.61 → 26.02 (6 ratchets; last FILLED).
- Excursion (daily_close): MFE 3.84% (26.625 on 2026-10-21), MAE 0.12% (25.67 on 2026-10-19).
- Conviction while held: 2026-10-22T15:30:14.607566+00:00 ADD 87.6 #1.
- **Exit cause: trailing_ratchet** — exit 26.02 = observed stop 26.02 (FILLED); stop raised 6x from 24.31; exit above entry 25.64.
- **Post-exit review: noise** — close-basis giveback 2.27% from the peak close 26.625; exit-day close 26.03 >= SMA20 23.143 and SMA50 24.7126; ATR not measured (no intraday high/low in this read). Prose: not requested: no registered capability for post-exit review prose (registering one is a §12 / §23.4 decision); the facts above are the review.
- **Re-entry: MISSING MARKET** (Refresh market evidence). Conditions: conviction_floor met; thesis_valid met; wash_window met; pullback_entry not met; reclaim not met. Alert levels: near_entry 25.853, in_zone 25.1, reclaim 26.02. Lane: Watch · Re-entry near (desk NEAR ENTRY / READY TO REVIEW); one alert `reentry_near:1b1fd2bf-78cf-5755-bdea-9248cd007907:srt:607228` (not sent).
- Conflicts on the record: held: held (positions[positions_context (holdings_accounts via lib.portfolio_positions)]) vs closed (schwab_round_trips srt:607228 exit fill); stance_after_exit: ADD (cio_opportunity_projection) vs exited (schwab_round_trips srt:607228).
- Events (append-only, one per fact): 14 — conviction_change, entry_fill, excursion, exit_fill, exit_review, origin_attributed, reentry_advice, stop_change.

Held positions with a lifecycle on the record: 19 — NVDA (origin n/a), SPCX (origin n/a), LDOS (origin n/a), V (origin n/a), BAH (origin n/a), SRNE (origin n/a), PFLT (origin n/a), CSWC (origin n/a), RTX (origin n/a), JEPI (origin n/a), NOC (origin n/a), SCHG (origin n/a), SCHD (origin n/a), DIV (origin n/a), XLB (origin n/a), BND (origin n/a), XLI (origin n/a), XAR (origin n/a), AMANX (origin n/a). An open position's origin needs its buy fill (trade_transactions, read with --with-db); 'origin n/a' means the fills were not read in this run.

MBI_BEHAVIOR = 0: stance is posture and priority; reference levels are information, never orders.
