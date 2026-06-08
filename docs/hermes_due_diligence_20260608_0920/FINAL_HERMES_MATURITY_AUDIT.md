# Hermes News-Injection Maturity Audit — 2026-06-08 09:20 ET
Read-only due diligence. Evidence: this folder.

## Executive maturity score: **6 / 10**
End-to-end chain is scheduled, flowing, and proven with real ticker traces + monitoring exists — but held
below 7 by: a monitor recording defect (crashes 91×/day), one dead lane (topic_ingestion, 26d stale),
flat catalyst quality (all `other`/3.0), and weekday-2×/day fusion cadence leaving scalp coverage at 42%.

| Tier | Score | Basis |
|------|-------|-------|
| Scalp / day-scalp | **6** | bridge→catalyst→momentum-engine every 30m premarket; catalyst-confirmed proposals generated; BUT only 11/26 GO/WAIT have fresh fusion (42%) + flat catalyst scoring |
| Proposal / open-trade | **6** | catalyst_momentum stages catalyst-confirmed proposals (2 confirmed @09:00); 0 open proposals now; 2/3 open paper trades have fusion |
| Holdings / watchlist | **7** | held 41/42 fused (98%, excellent); watchlist 25/42 (60%) |
| Monitor / watchdog | **5** | detects + records real staleness, watchdog heartbeat OK; BUT alert insert crashes on recurring alert_uid (91×/day) + dead topic_ingestion lane unresolved |

## Primary questions
1. **Bridge on cron every 10m 04:00–11:59 ET weekdays?** YES — `*/10 4-11 * * 1-5` (+ backup 40 6,12,18). Running (log mtime 09:20).
2. **Bridging fresh ticker rows → news_articles source='hermes'?** YES — 73 total, 12 in 24h, newest today; lineage stamped (e.g. `news#8184 <- hermes#2304`, QTEX).
3. **news_to_catalyst converting → catalyst_events?** YES — source='hermes' 73, 12/24h, newest 09:20. QUALITY GAP: every catalyst is `catalyst_type=other`, `severity=low`, `impact_score=3.0` (no granular typing/scoring).
4. **signal_fusion refreshing fused_signals?** YES — 2728 rows/24h, "Fused 2728 symbols" @07:00. CADENCE GAP: runs only `0 7,13 * * 1-5` (2×/day weekday) → 59h stale by Monday 00:00 (weekend), self-resolves Mon 07:00.
5. **Scalp candidates get catalysts before proposal/alert?** PARTIAL — catalyst_momentum_engine (premarket every 30m) confirms catalysts + gates proposals; but fused_signals coverage for today's GO/WAIT scalp set is 42%.
6. **Proposals/paper/held/watchlist getting fused intel at cadence?** PARTIAL — held 98%, watchlist 60%, open paper 67%, proposals 0 open. Intraday names discovered after 07:00 wait until 13:00 for fusion.
7. **Freshness monitor watching + paging/recording stale failures?** PARTIAL — it DETECTS + records (`freshness:fused_signals` urgent, `freshness:cio_decisions` warning, `freshness:topic_ingestion`), watchdog heartbeat OK; BUT the alert INSERT is not an upsert → `UniqueViolation` on recurring alert_uid crashes the run (91 tracebacks today).
8. **Silent-failure patterns?** (a) **topic_ingestion DEAD — 630h / 26 days stale**; (b) monitor recurring-alert insert crash (green-ish job, errors mid-sweep); (c) fused_signals weekend gap labeled "silently broken" (actually weekday-only schedule); (d) flat catalyst quality (all other/3.0).
9. **Maturity:** scalp 6 / proposal 6 / holdings-watchlist 7 / monitor 5 → exec 6.

## Evidence table (row counts / newest)
| Table | total | 24h | newest |
|---|---|---|---|
| news_articles | 6497 | 49 | 2026-06-08 06:12 |
| news_articles (hermes) | 73 | 12 | 2026-06-08 00:00 |
| catalyst_events | 6626 | 343 | 2026-06-08 09:20 |
| catalyst_events (hermes) | 73 | 12 | 2026-06-08 09:20 |
| fused_signals | 13267 | 2728 | 2026-06-08 07:00 |
| hermes_research_intelligence | 2298 | 369 | 2026-06-08 09:18 |
| sentiment_observations | 3454 | 104 | 2026-06-08 06:30 |

## 5-symbol trace (Hermes-sourced)
| symbol | scalp GO/WAIT | open proposal | open paper | held | active watch | latest catalyst | latest fusion |
|---|---|---|---|---|---|---|---|
| ABTS | no | no | no | no | no | 2026-06-04 | 2026-06-08 07:00 |
| ACCL | no | no | no | no | no | 2026-06-06 | 2026-06-08 07:00 |
| AIRJ | no | no | no | no | no | 2026-06-04 | 2026-06-08 07:00 |
| ALOY | no | no | no | no | no | 2026-06-05 | 2026-06-08 07:00 |
| ANY  | no | no | no | no | no | 2026-06-04 | 2026-06-08 07:00 |
Interpretation: Hermes-discovered microcaps flow all the way to fused_signals (refreshed today) but are NOT
entering active trading sets — fusion coverage works; these particular names are low-conviction/not actioned.

## Stale / dead tables with consumer impact
- **topic_ingestion / topic_monitor — 630h (26 days) stale.** Consumer: research-topic gap detection. Dead lane; monitor alerts but cannot escalate cleanly (insert crash).
- **fused_signals — weekend staleness** (weekday 2×/day schedule). Consumer: scalp/proposal intraday freshness. Cadence design gap, not breakage.

## False assumptions corrected
- `portfolio_holdings` table does NOT exist — holdings are a JSON blob (`holdings.json` / 1-row `holdings_json_mirror`), no per-symbol rows. Held coverage computed from JSON (42 symbols).
- `watchlist_items.active` does NOT exist — status is `status` ∈ {active, removed, researched}.
- `alert_events.message` does NOT exist — text column is `raw_text`; dedup key is `alert_uid` (unique).

## "Do not fix yet" — operator approval required
1. **Make freshness-monitor alert insert an UPSERT** (ON CONFLICT (alert_uid) DO UPDATE) so recurring stale conditions update instead of crashing (kills the 91×/day UniqueViolation). [code change — needs approval]
2. **Revive or formally retire topic_ingestion** (26d dead). [decide: fix vs retire]
3. **Increase signal_fusion cadence** (e.g. hourly during market, or trigger after catalyst writes) to lift scalp GO/WAIT fusion coverage above 42%. [cron change — needs approval]
4. **Granular catalyst typing/scoring** in news_to_catalyst (stop stamping every Hermes catalyst as other/3.0). [scoring-adjacent — needs approval]

## Recommended next Claude Code prompt (maturity < 8)
"Fix the system_freshness_monitor alert_events UpSert defect (ON CONFLICT alert_uid DO UPDATE), decide
topic_ingestion revive-vs-retire, and propose a signal_fusion intraday cadence to raise scalp GO/WAIT fusion
coverage — read-only analysis + a single guarded code patch for the upsert, with operator approval gates for
the cadence and catalyst-scoring changes."
