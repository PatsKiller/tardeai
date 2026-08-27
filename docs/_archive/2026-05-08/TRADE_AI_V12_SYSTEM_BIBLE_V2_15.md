# Trade AI v12 System Bible v2.15

**April 28, 2026 | ms01-openclaw | v2.15 — Live Tax Data + Smart Automation + IRMAA**

---

## Changes in v2.15

| Change | Status |
|--------|--------|
| `personal_tax_history` table (yearly) | **DONE** — 2025 + 2026 seeded from real return |
| `tax_events` table (granular dated) | **DONE** — Roth conversions, dividends tracked |
| Live tax context in every Alex analysis | **DONE** — bracket room, YTD conversions, business loss carryforward |
| `/api/v2/tax-situation` endpoint | **DONE** — real-time bracket room calculation |
| `run_alex_daily.py` with daily/weekly/monthly modes | **DONE** — cron scheduled |
| 2025 tax return parsed into DB | **DONE** — AGI $11,974, $0 taxable, -$4,392 biz loss |

### Tax Data Now in Every Alex Analysis

When Alex analyzes any position (e.g., `alex V`), the prompt now includes:
```
TAX SITUATION (LIVE FROM DB):
2026 estimated AGI: $49,342
Roth conversions YTD: $35,000
Current bracket: 12%
Remaining 22% bracket room: $66,883
Max additional Roth conversion at 22%: $66,883
2025 business loss carryforward: $4,392 (extra conversion capacity)
```

This means Alex can give advice like:
- "With your $66,883 remaining bracket room, you could convert another $66K before hitting 24%"
- "Your $4,392 business loss effectively gives you extra conversion headroom"
- "Selling V in your Roth has zero tax impact. In IRA, gains are deferred. In taxable, long-term capital gains apply."

### Smart Automation Schedule

| Mode | Schedule | What it does | LLM |
|------|----------|-------------|-----|
| Daily | 5:00 AM M-F | Light portfolio scan, alerts on >3% moves, SMA crosses | Local |
| Weekly | Sunday 8 AM | Strategy review, income gap, rebalancing, Roth note | Local/Grok |
| Monthly | 1st of month 9 AM | Deep reconciliation, Roth ladder refresh, full tax review | Claude |

### 2025 Tax Return Data (Stored)

| Field | Value |
|-------|-------|
| AGI | $11,974 |
| Taxable income | $0 |
| Total tax | $0 |
| Business loss (Sch C) | -$4,392 |
| Itemized deductions | $28,162 |
| Mortgage interest | ~$25,000 |
| Property taxes | ~$3,162 |
| Capital gains (net) | $60 |
| Filing status | Single |

### 2026 Tax Tracking (Live)

| Field | Value |
|-------|-------|
| Estimated AGI | $49,342 |
| Roth conversions YTD | $35,000 |
| Dividend income | $14,342 |
| Current bracket | 12% (22% starts at taxable $47,150) |
| 22% bracket room | **$66,883** |
| Using deduction | Standard ($15,700) |

---

## System Summary

| Metric | Value |
|--------|-------|
| Portfolio | ~$1,197,985 |
| Actionable recs | 22 |
| LLM providers | 4 (Local, Grok, Claude, OpenAI) |
| Agents | 7 (Maria, Steph, Risk, Tax, Full Chain, Alex, Aegis) |
| DB tables | 121 |
| UI pages | 27 |
| API endpoints | 31+ |
| Cron jobs | 21 |
| Maturity | **6.5 / 10** |

---

## What Should John Trust?

| Category | Trust? |
|----------|--------|
| Tax bracket room ($66,883) | **Yes** — computed from 2025 return + 2026 events |
| "Alex says convert another $50K at 22%" | **Directional yes** — math is real, verify with CPA |
| Portfolio value, income gap | **Yes** — real data |
| Safety blocks on SCHD/CSWC | **Yes** — logic is sound |
| Daily scan alerts | **Yes** — based on real market data |
| Agent recommendations | **With caution** — 1.7B model quality for most agents |
| Decision outcomes | **Ignore** — still synthetic |

---

**v2.15 — Tax return integrated, live bracket room in every analysis, smart daily/weekly/monthly automation. Maturity: 6.5/10.**
