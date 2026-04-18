# Trade AI v11 — Operator Runbook

## Daily workflow

| Time ET | Run | Command | Focus |
|---|---|---|---|
| 4:00 AM | 0400 | `--run-label 0400` | Overnight movers, early catalyst hits |
| 7:00 AM | 0700 | `--run-label 0700` | **Primary watchlist build** — main decision window |
| 9:00 AM | 0900 | `--run-label 0900` | Finalize top 2–3 targets before open |
| 10:00 AM | 1000 | `--run-label 1000` | Late-morning setups, VWAP reclaims, continuations |

**Recommended morning flow:**
1. Open HTML dashboard from 0700 run — review sector heatmap first
2. Check breadth badge (top-right): Bullish = more aggressive, Bearish = tighten criteria
3. Look at VIX direction: rising = avoid small floats with low catalysts
4. Review GO-tier cards top-to-bottom (sorted by score)
5. Cross-check against options flow panel for confirmation
6. Import `.tst` file to TOS watchlist

---

## Reading the HTML dashboard

**Sector heatmap tiles:**
- Dark green = strong sector leader (+2%+) — tickers in this sector get +5 sector momentum pts
- Light green = leading (+0.5% to +2%) — +3 pts
- Gray = flat — +1 pt
- Red = lagging — 0 pts
- Dark red = strong laggard (-2%+) — consider avoiding setups in this sector

**Trend arrows on ticker cards:**
- ⬆ on score = setup is improving since last run — building momentum
- 🚀 on RVOL = volume is accelerating fast — high conviction signal
- 🆕 = brand new ticker this run — watch for first-run false positives

**Breadth badge:**
- 🟢 Bullish: >60% of sectors advancing. More setups likely to follow through.
- 🟡 Neutral: Mixed market. Cherry-pick only A+ setups.
- 🔴 Bearish: >60% of sectors declining. Only trade high-conviction GO with fresh catalyst.

---

## Score interpretation (v11 — max 55)

| Score | Grade | Decision | Guidance |
|---|---|---|---|
| 48–55 | A+ | GO | Elite setup — all 6 pillars aligned, sector tailwind |
| 40–47 | A | GO | Strong setup — enter on confirmation |
| 30–39 | B | WAIT | Keep watching — needs RVOL boost or fresh catalyst |
| 20–29 | C | AVOID | Weak — skip unless something changes dramatically |
| 0–19 | D | AVOID | No edge |

**Escalation:** A+ and A grades get a Claude Sonnet narrative. Always read it before trading.

---

## Catalyst tiers

| Tier | Examples | Pillar pts |
|---|---|---|
| High impact | FDA approval/PDUFA, earnings beat, M&A, material 8-K | 12–15 |
| Medium impact | Analyst upgrade, partnership, licensing | 8 |
| Low impact | General news, product mention | 4 |
| Noise | Marketing, generic wire | 0 |

Recency bonus: articles < 2h old get ×1.5 multiplier.

---

## Options flow panel

The options panel shows unusual activity — high volume relative to open interest, or
large premium ($50K+). Use it for **confirmation**, not as primary signal.

- **SWEEP**: order filled across multiple exchanges simultaneously — institutional urgency
- **Bullish CALL sweep**: large player betting stock goes up — confirms long thesis
- **Bearish PUT sweep**: large player hedging or betting down — be cautious on that ticker
- **High premium**: $500K+ = whale-level conviction — strong confirmation

---

## Delta events to act on immediately

| Event | Urgency | Action |
|---|---|---|
| `NEW_CATALYST` on a WAIT ticker | High | Re-score mentally — may now be GO |
| `RVOL_THRESHOLD_CROSS` above 5x | High | Volume confirming — check catalyst |
| `GRADE_UP` +10 or more | Medium | Momentum building — add to shortlist |
| `NEW_TICKER` with score ≥ 40 | High | Fresh GO setup — review immediately |
| `TICKER_FADED` | Low | Remove from mental watchlist |

---

## Economic calendar integration

High-impact events (🔴 HIGH) shown in the calendar panel:

- **Fed rate decision / FOMC**: extreme VIX move likely — tighten or avoid small floats
- **CPI / PPI**: market direction unclear until print — wait for dust to settle (5–10 min post-print)
- **NFP (Non-Farm Payrolls)**: Friday morning — can reset market sentiment entirely
- **Earnings for watchlist tickers**: ⚠ badge appears on ticker card — confirm earnings date before entry

---

## Troubleshooting

**HTML dashboard not auto-refreshing:**
- Confirm the file opens in a modern browser (Chrome/Edge/Firefox)
- The `<meta http-equiv="refresh" content="60">` tag handles this — no server needed
- To get live data: re-run the pipeline manually or wait for next Task Scheduler trigger

**Sector data showing zeros:**
- Check Polygon key in `.env` (primary source)
- Run `python scripts/market_context.py` standalone to debug
- Yahoo Finance fallback requires no key but may be rate-limited

**Options flow empty:**
- Polygon key required for options data
- Run `--skip-market-check` outside hours to test — options data may be unavailable pre-market
- This is display-only; empty options data doesn't block any other output

**Finviz cookie expired:**
- Re-login to elite.finviz.com and copy the new cookie string from browser DevTools (Network tab → any request → Cookie header)
- Update `FINVIZ_COOKIE=` in `.env`

**LLM errors (Haiku/Sonnet):**
- Verify `ANTHROPIC_API_KEY` in `.env`
- Run with `--no-llm` for keyword-only scoring — all outputs still generate

**WhatsApp not arriving:**
- Check `TWILIO_SID`, `TWILIO_AUTH_TOKEN` in `.env`
- Verify `TWILIO_WHATSAPP_TO` format: must be `whatsapp:+1XXXXXXXXXX`
- Check Twilio console for sandbox sandbox join status

---

## Weekly maintenance (auto Mondays)

First run each Monday auto-archives:
- Prior-week raw CSVs → `archive/weekly/{date}/`
- Prior-week merged CSVs
- Prior-week reports
- Logs preserved

---

## Tuning weights.yaml

Key levers for v11:

- **Sector momentum max**: reduce from 5 to 3 if you prefer sectors to play a smaller role
- **Catalyst recency multipliers**: reduce `under_2h: 1.5` if very fresh news causes false GO signals
- **RVOL tiers**: tighten `rvol_3_to_4_99` if you want only 5x+ to score meaningfully
- **Grade band floor**: raise `GO min_score` from 40 to 42 if too many borderline GO signals

After any change: `python scripts/trade_ai_orchestrator.py --run-label 0700 --skip-market-check --no-llm --no-alerts --date 2025-01-15` to see score shifts on a historical date.
