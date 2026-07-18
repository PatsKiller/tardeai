# Defense Desk v2 — Phase 0 Diagnosis (2026-07-18)

## Capability matrix (v2 additions over v1 diagnosis)
| Capability | Verdict | Evidence |
|---|---|---|
| v1 "—" cells root cause | **NAME MISMATCH, not thin coverage** | trade_ai_scans/finviz use "Financial Services"/"Consumer Cyclical"/"Basic Materials"/"Consumer Defensive"/"Communication Services" while the engine queried ETF-label names ("Financials"…). Membership is actually 80–480 symbols/sector. Fixed via `sector_aliases` in config/sector_momentum.json + `_aliases()` → `t.sector = ANY(%s)` in breadth/hermes/news queries. Post-fix: all 11 sectors show breadth (22–78%, n=41–60) and Hermes pulse (48.2–55.5). Zero "—" cells. |
| Whole-market price depth | **SUFFICIENT** | SPY/QQQ/IWM 1,259–1,260 closes (5y); RSP/DIA ~257–258 closes (added later to universe) — enough for RS 5/20/60 + slope5, no warm-up needed |
| Market internals (NH/NL) | **AVAILABLE — reuse** | market_movers_latest.json already captures new_high/new_low signal lists (top-15 caps per signal; counts labeled as capped, not exchange-wide) |
| Style pairs | **LIVE** | VUG/VTV/IWM/SPY/RSP/SPY all priced daily; spreads persisted as `STYLE:<key>` rows in sector_momentum_state — same debounce/transition machinery as sectors |
| Finviz industry groups export | **WORKS** | `https://elite.finviz.com/grp_export.ashx?g=industry&v=141` through existing cookie+throttle → 144 industries × Perf Week/Month/Quarter/Half/Year/YTD + Change + Volume. v=152 lacks multi-period perf; **v=141 is the B2 view** |
| Options-module reuse (for E2/WS-B) | **INVENTORY** | `schwab_transport.get_option_chain` + `normalize_option_chain` (verified v1); options_engine.py has starred-lane pattern via db_adapter._execute; options_desk_enterprise.py owns queue/gates. OI-delta inference = snapshot chain → diff vs prior snapshot (no new Schwab surface) |

## Engine gotchas found during A2/C2
- **Held-ETF extra rows**: ETFs also held in the book get intraday repricer rows in ticker_prices → naive `ORDER BY date DESC LIMIT n` misaligns vs SPY. Fix: date-intersection alignment before RS math (this was the false "warming up" on XLI/XLB).
- **InFailedSqlTransaction cascade**: fail-soft except blocks must `conn.rollback()` or every later query in the loop dies silently.
- **Hermes table name**: `hermes_score_history`, NOT hermes_composite_scores.

## Live A2 verification (2026-07-18 first run)
STATE LINE: `Market: SPY -1.4% wk · equal-weight leading cap-weight (+3.0% 20d) · small caps leading · NH/NL 15/15 — mixed tape · 4/11 sectors lagging`
Cross-check coherent: QQQ rs20 −5.55 (tech-led weakness at index level) vs DIA +2.31; RSP−SPY s20 +3.01 LEADING (megacap-concentrated selling); VUG−VTV −0.1 slope +2.05 IMPROVING.

## Scope
A2+C2 shipped this pass (tests: scripts/test_sector_momentum_debounce.py v1+v2 all pass).
B2 (industries, v=141) and D2 (DefenseHub rebuild) next; E2 = v1 engines as capacity allows —
cut line per prompt: A2/B2/C2/D2 ship first.
