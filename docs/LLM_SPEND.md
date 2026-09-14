# LLM and paid-API spend

**Status:** built 2026-09-14 (operator ask and approval).
**Code:** `scripts/lib/llm_spend.py` (report) · `scripts/llm_spend_report.py` (Telegram) · `GET /api/v2/consumption/spend` · Command Center `/v3/consumption` → *Spend* panel.
**Caps:** `scripts/lib/llm_consumption.py::calibrated_projected_usd`, `scripts/lib/cio_governed_model_bridge.py` (step 5).
**Authority:** READ_ONLY_ADVISORY.

## Why

The operator said: "It's a $7 limit, but we never go above 7 cents or 50 cents. Something's not adding up."

Three different numbers had all been called "spend":

| Number | Where | What it is | Measured, week to 2026-09-14 |
|---|---|---|---|
| **Real** | `llm_consumption_log.estimated_cost_usd` | provider token usage × effective price schedule | $4.73 ($0.72/day) |
| **Counted** | `llm_cost_reservations` (settled `actual_usd`, open `projected_usd`) | what the cap system holds; failed or ambiguous calls settle conservatively | $5.50 |
| **Projected** | pre-call check | the worst case for one call (32,000 input tokens at list price, +15%) | $214.61 for advisory opinions alone |

A cap is compared against *counted* spend plus the *projected* cost of the next call. The projection was the worst case, so a $0.50 global cap refused research when real spend was a few cents.

Test suites also wrote $0.60 rows into the production ledger. Rows with `test_` ids were excluded, but the cap-race test used `caprace_` ids, which were not. It now uses `test_caprace_`.

## What changed

1. **Caps count actual spend.**
   - `calibrated_projected_usd` projects a call at the 90th percentile of that process's settled actual cost over the last 7 days × 1.5, never above the worst case.
   - A process with fewer than 20 settled calls stays on the worst case.
   - Measured examples:

     | Process | Measured projection | Worst case |
     |---|---|---|
     | Advisory opinions | $0.00044 | $0.0069 |
     | Maria narratives | $0.0013 | $0.0069 |
     | Symbol research (big prompts) | $0.0066 | $0.0069 |

2. **One durable global cap of $2.00/day**, set in `~/.config/tradeai/llm_global_daily_usd_cap.env`.
   - Every unit loads that file last through a `99-llm-global-cap.conf` drop-in, because systemd `EnvironmentFile` overrides `Environment=` and the Bitwarden-rendered `%t/tradeai/env` carries 0.50.
   - Cron lines setting the cap inline use the same value.
   - The temporary `backfill-cap-override.env` ($7.00, from 2026-09-06) and the portfolio-server $1.50 override are archived, not deleted.
3. **Spend report** by provider, model and process, with the peak / off-peak split and scheduled work that ran on peak.
4. **Telegram spend texts:**
   - daily at 07:05 ET for yesterday, with month to date;
   - weekly on Monday at 07:10 for last Monday–Sunday;
   - monthly on the 1st at 07:15 for last month.

## Definitions

- **Peak** means DeepSeek's official peak pricing hours, `deepseek_offpeak.DEEPSEEK_PEAK_UTC`:
  - 01:00–04:00 and 06:00–10:00 UTC, which is 09:00–12:00 and 14:00–18:00 Beijing;
  - Monday to Friday only.
  - Everything else is off-peak, including China night and the whole weekend.
  - Operator rule: scheduled work runs off-peak.
- **Scheduled** is `trigger_mode = automated` (cron, timers, workers). **Ad hoc** is `manual`.
- **Paid** is `estimated_cost_usd > 0`. Grok and ChatGPT OAuth lanes and local models cost $0 and are listed separately.
- **Brave Search** is a paid plan, but no per-request price is configured, so requests are shown rather than dollars.

## First measurement (dry runs, nothing sent)

- **Yesterday (Sun 2026-09-13):** $0.41 real; off-peak $0.35 (86%), peak $0.06; 1,358 calls, of which 546 paid.
- **Week of 2026-09-07:** $5.45 real ($0.78/day), counted $6.21; off-peak $3.40 (62%), peak $2.05 (38%).
  - Advisory Desk per-row opinions ran 8,424 scheduled calls on peak ($2.01).
- **September to date:** $8.10 real ($0.60/day).

## When scheduled work may run (operator rule, 2026-09-14)

> "off peak hours ... are 9 a.m. to 9 p.m. Eastern Standard Time in the U.S. and on the weekends, and only
> a la carte stuff that is urgent, that's requested by the operator, is ran during peak hours."

**DeepSeek's billing.** From api-docs.deepseek.com/quick_start/pricing, checked 2026-09-14:
- **Peak hours:** 01:00–04:00 and 06:00–10:00 UTC, Monday–Friday. Everything else is off-peak, at half price.
- **deepseek-flash, per 1M tokens:** off-peak $0.003 cache hit / $0.15 cache miss / $0.60 output; peak is double.

**The rule in code.** `scripts/lib/deepseek_offpeak.py::should_scheduled_skip`. A scheduled run proceeds only when both hold:
- it is inside weekdays 09:00–21:00 ET, or any hour on a weekend;
- it is outside DeepSeek's billing peak.

The second check matters twice. Sunday 21:00–24:00 ET is Monday 01:00–04:00 UTC. In winter (EST), weekday 20:00–21:00 ET is 01:00–02:00 UTC.

**Where it applies.**
- **Cron lines:** `run_with_deepseek_offpeak.sh --scheduled -- <command>`. Manual runs never pass through the wrapper, so an operator run is never blocked. `TRADEAI_ALLOW_SCHEDULED_PEAK=1` overrides one scheduled run.
- **Gated this way:** the usefulness scorer (`hermes_external_feedback_loop.py`) and due-diligence questions.
- **Rescheduled:**
  - holdings research 08:00 → 09:05;
  - flash market agent 06–19 → 09–19;
  - advisory lessons reflection 21:40 → 19:40;
  - shadow seed 21:45 → 19:45;
  - advisory cache worker 08–22 UTC → 09–19 ET.

**Measured before the change** (Thu 09-10 → Mon 09-14):
- $0.58 of $2.46 ran outside the window.
- $0.19 of that was the 08:00 holdings run, $0.08 the usefulness scorer and $0.03 due-diligence questions.
- $0.22 sat under the shared `advisory_desk_opinion` id and could not be attributed.

**Cross-check against DeepSeek.** `scripts/deepseek_balance_snapshot.py` records the account balance hourly. The spend report compares the balance drops with the logged DeepSeek cost over the same span.

Last week's logged $5.45 recomputed from token counts at the published prices, peak-aware, gives $5.42. 21,160 rows had no cache split and were priced as cache misses, an upper bound.

## Commands

```bash
python scripts/llm_spend_report.py --period daily            # dry run: prints the text
python scripts/llm_spend_report.py --period weekly --send    # sends once per week (ledger)
curl -s 'http://127.0.0.1:7777/api/v2/consumption/spend?period=month' | jq .data.report.totals
```
