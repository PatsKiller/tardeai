# Trade AI v10 — Operator Runbook

## Daily workflow

### Pre-market (4:00 AM ET)
- Task Scheduler fires `--run-label 0400`
- Ingests: pre_market_movers, low_float_rockets, gap_and_go, elite_aplus_setups, catalyst_seed, hot_sectors_seed
- WhatsApp arrives with overnight movers and early catalyst hits
- Review: check for high-impact catalysts that appeared overnight

### Pre-market update (7:00 AM ET)
- Task Scheduler fires `--run-label 0700`
- Adds: perfect_scalp_seed, rvol_5x_plus, ten_percent_move, opening_drive
- WhatsApp shows GO-tier candidates with updated scores
- Primary decision window — this is your main watchlist build

### Open prep (9:00 AM ET)
- Task Scheduler fires `--run-label 0900`
- Focus shifts to: gap_and_go, opening_drive, momentum_breakout, at_hod_seed, continuation_seed
- Delta section shows what upgraded or faded since 7:00 AM
- Finalize your 2–3 primary targets before open

### First-hour read (10:00 AM ET)
- Task Scheduler fires `--run-label 1000`
- Includes: hod_momentum, run_seed, vwap_reclaim_seed, red_to_green_seed, halts_seed, abcd_seed
- Watchlist refresh via union of continuation seeds
- Identifies late-morning setups if morning plays have stalled

---

## Score interpretation

| Score | Grade | Decision | Action |
|-------|-------|----------|--------|
| 45–50 | A+    | GO       | Top priority — all 5 pillars aligned |
| 40–44 | A     | GO       | Strong setup — enter on confirmation |
| 30–39 | B     | WAIT     | Keep on watchlist — needs one more catalyst or RVOL |
| 20–29 | C     | AVOID    | Weak setup — skip unless something changes |
| 0–19  | D     | AVOID    | No edge |

**Escalation**: A+ and A grades get a Claude Sonnet narrative. Read it before trading.

---

## Catalyst tiers

| Tier          | Examples | Weight |
|---------------|----------|--------|
| High impact   | FDA approval, PDUFA, earnings beat, M&A, material 8-K | 12–15 pts |
| Medium impact | Analyst upgrade, partnership, licensing deal | 8 pts |
| Low impact    | General news, product mention | 4 pts |
| Noise         | Marketing, generic wire, unverifiable | 0 pts |

Recency bonus: articles < 2 hours old get ×1.5 multiplier on catalyst score.

---

## Delta events to act on immediately

- `NEW_CATALYST` on a WAIT ticker → re-evaluate, may now be GO
- `RVOL_THRESHOLD_CROSS` above 5x → high-conviction volume confirmation
- `GRADE_UP` of 10+ points → strong momentum acceleration

---

## Troubleshooting

**Finviz returning empty data:**
- Check `FINVIZ_COOKIE` in `.env` — Elite cookies expire periodically
- Re-login to elite.finviz.com and copy the updated cookie

**Catalyst APIs returning nothing:**
- Verify each API key in `.env`
- Run with `--no-llm` flag to confirm scoring works without API calls
- Check `data/logs/ingestion_summary_*.json` for per-screener counts

**LLM errors:**
- Verify `ANTHROPIC_API_KEY` is valid
- Run with `--no-llm` for keyword-only scoring while you fix keys

**WhatsApp not sending:**
- Confirm `TWILIO_SID`, `TWILIO_AUTH_TOKEN` are set
- Verify `TWILIO_WHATSAPP_TO` format is `whatsapp:+1XXXXXXXXXX`
- Check your Twilio console for the sandbox join confirmation

**No output files generated:**
- Check write permissions on `reports/` directory
- Look for errors in the stage-by-stage console output
- Run with `--no-alerts` to isolate pipeline vs. alerting issues

---

## Weekly maintenance (automatic on Mondays)

`weekly_hygiene.py` runs automatically on the first run of each Monday and:
- Archives all prior-week raw CSVs to `archive/weekly/{date}/`
- Archives all prior-week merged CSVs
- Archives all prior-week reports
- Preserves logs

Manual trigger:
```bash
python scripts/weekly_hygiene.py --date 2025-01-20 --project-root .
```

---

## Adding or modifying screeners

Edit `assets/screeners.yaml`. Each screener entry needs:

```yaml
my_new_screener:
  display_name: "My Screener"
  group: "catalyst_scalp"
  status: "user_seed"
  strategy_class: "day_scalp"
  finviz_url: "https://elite.finviz.com/screener.ashx?..."
```

Then add it to the appropriate `run_windows` list.

For a union screener (merges existing ones, no direct URL):
```yaml
my_union:
  display_name: "My Union Screener"
  group: "dashboard_support"
  status: "derived_union"
  strategy_class: "day_scalp"
  union_of:
    - screener_a
    - screener_b
```

---

## Tuning weights.yaml

The expert-recommended baseline is in `assets/weights.yaml`.
If you find certain setups are being over- or under-scored, adjust the tier point values in `pillar_scoring`.

Key levers:
- **Reduce catalyst max**: lower `high_impact_single_source` if too many false GO signals
- **Increase RVOL weight**: increase `rvol_5_to_7_99` if RVOL is your primary trigger
- **Tighten float**: lower `m20_to_50m` if you prefer tighter floats exclusively
- **Recency multiplier**: reduce `under_2h: 1.5` if very fresh news leads to bad entries

After any change, re-run with `--no-alerts --skip-market-check` on a past date to see how scores shift.
