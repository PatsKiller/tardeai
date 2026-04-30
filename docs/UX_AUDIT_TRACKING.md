# UX Audit Implementation Tracker
**Source:** Comprehensive UI/UX Improvement Prompt (April 30, 2026)
**Total items:** 130+ across 28 pages + 15 global patterns
**Status:** In progress

## Legend
- ✅ Done
- 🔧 In progress
- ⬜ Not started

---

## CRITICAL BUGS (🔴)
- ✅ #9B — NaNd timestamp bug (timeAgo strips ET/EST/EDT timezone suffixes)
- ⬜ #15A — Tax page all $0 values (cost basis not loading)
- ⬜ #15B — Tax page 16,700 lots (dedup needed)
- ⬜ #24B-C — System Health: Claude/Grok "No Key" + $0 spend
- ⬜ #9G — Heat inconsistency 0.4% vs 6.2% (different metrics — need labels)
- ⬜ G12 — Journal trade count 37 vs 122 (filter scope difference)

## GLOBAL PATTERNS (applies to ALL pages)
- 🔧 G1 — Account badges on all recommendation cards
- ⬜ G2 — Funding source on all BUY/ADD recommendations
- ⬜ G3 — Broker execution disclaimer (advisory only banner)
- ⬜ G4 — Data staleness indicators ([Stale — Xd ago] badges)
- ⬜ G5 — Heat definition consistency (Intraday vs Stop Risk)
- ⬜ G6 — 401k visual indicator (🏦 icon, "managed via Fidelity NetBenefits")
- ⬜ G7 — NaN bug (✅ FIXED in format.ts)
- ⬜ G8 — Watchlist → Portfolio → Journal workflow breadcrumb
- ⬜ G9 — System Health vs Orchestration consolidation
- ⬜ G10 — "Stop Claude" button visibility
- ⬜ G11 — Personal Situation modal accessibility
- ⬜ G13 — Brave Search credit warning prominent
- ⬜ G14 — Reports page "Latest Report" sticky card
- ⬜ G15 — Portfolio Mode vs Trade Mode separation

## PAGE-BY-PAGE STATUS

### 1. Overview (/v2)
- ✅ 1A — Income Target tooltip (SSDI replacement explanation)
- ✅ 1B — Roth Room tooltip (convert FROM Rollover IRA → Roth)
- ⬜ 1C — Pending approvals urgency breakdown
- ✅ 1D — GO setups account context (Taxable only)
- ✅ 1E — Cash breakdown by account
- ✅ 1F — Beta interpretation tooltip
- ⬜ 1G — Period returns 6M/1Y "insufficient history" note
- ✅ 1H — Latest News 0 explanation

### 2. Portfolio/Holdings (/v2/portfolio)
- ⬜ 2A — PIRSI column split + tooltips
- ✅ 2B — Decision column legend (ADD/TRIM/WATCH/MONITOR)
- ⬜ 2C — Funding source on recommendations
- ⬜ 2D — 401k positions "—" explanation
- ⬜ 2E — 401k TRIM guidance (Fidelity NetBenefits)
- ⬜ 2F — 401k gain "—" explanation
- ⬜ 2G — Account subtotals

### 3. Rebalance (/v2/rebalance) — HIGHEST PRIORITY
- ⬜ 3A — Account field on every recommendation
- ⬜ 3B — V trim execution guidance (Roth first)
- ⬜ 3C — JEPI stop — account context
- ⬜ 3D — Stale $0 income badge
- ⬜ 3E — YAML Health Score explanation
- ✅ 3F — Advisory disclaimer to top
- ⬜ 3G — YAML config path link
- ⬜ 3H — Per-account next action summary

### 4. Recovery Watch (/v2/recovery)
- ⬜ 4A — "Stay Cash" account context
- ⬜ 4B — Money market specifics (SPAXX/FZFXX)
- ⬜ 4C — "Alternatives" rename
- ⬜ 4D — Re-entry monitoring guidance
- ⬜ 4E — Stop confirmation expand
- ⬜ 4F — Total freed capital summary

### 5. Risk Manager (/v2/risk)
- ✅ 5A — Unprotected 401k/mutual fund explanation
- ✅ 5B — Heat definition + action guidance
- ⬜ 5C — Stop Distance missing data explanation
- ⬜ 5D — Price $0.00 data bug
- ⬜ 5E — Protection improvement action

### 6. Retirement (/v2/retirement)
- ✅ 6A — Roth conversion FROM account
- ⬜ 6B — Remaining $16K guidance
- ✅ 6C — Golden Window explanation
- ✅ 6D — 401k loan payoff guidance
- ✅ 6E — IRMAA forward warning
- ✅ 6F — Medicaid context
- ⬜ 6G — Medicare enrollment guidance
- ✅ 6H — Roth allocation commentary

### 7. AI Analyst (/v2/ai-analyst)
- ⬜ 7A — Action items account context
- ⬜ 7B — Worthless security liquidation guidance
- ⬜ 7C — Agent last run guidance
- ⬜ 7D — Tab descriptions
- ⬜ 7E — Reports tab description

### 8. CIO Dashboard (/v2/cio)
- ⬜ 8A — Account column on decisions
- ⬜ 8B — Status code legend
- ⬜ 8C — Agent count context
- ⬜ 8D — V ADD funding source
- ⬜ 8E — Rotation proposals cross-link
- ⬜ 8F — MARL SIMS tooltip

### 9. Morning Brief (/v2/morning-brief)
- ✅ 9B — NaNd bug fixed
- ⬜ 9A — Stop triggered account badge
- ⬜ 9C — Covered call execution guidance
- ⬜ 9D — Covered call strike/expiry guidance
- ⬜ 9E — Rotation account context
- ✅ 9F — FRED macro dashboard (color-coded tiles done)
- ⬜ 9G — Heat inconsistency labels

### 10. Approvals (/v2/approvals)
- ⬜ 10A — Account on approval cards
- ⬜ 10B — "Auto-review failed" explanation
- ⬜ 10C — Total dollar impact
- ⬜ 10D — Tasks vs Approvals distinction
- ⬜ 10E — URGENT reason explanation

### 11. Forecast (/v2/forecast)
- ✅ 11A — Assumptions to top
- ⬜ 11B — Inflation note
- ⬜ 11C — RMD impact
- ⬜ 11D — 401k yield caveat
- ✅ 11E — Rollover IRA tax concentration note

### 12. Dividends (/v2/dividends)
- ✅ 12A — "Watch" safety explanation
- ⬜ 12B — Account breakdown of income
- ⬜ 12C — Gap closure guidance
- ✅ 12D — Qualified dividend tax explanation

### 13. Technical (/v2/technical)
- ✅ 13A — PI Score interpretation
- ⬜ 13B — Near Stop prioritization
- ⬜ 13C — 52-week range interpretation
- ⬜ 13D — Account column

### 14. Returns (/v2/returns)
- ✅ 14A — Roth YTD anomaly badge
- ✅ 14B — 6M/1Y insufficient history note
- ⬜ 14C — Rollover IRA loss context

### 15. Tax & Lots (/v2/tax)
- ⬜ 15A — $0 data bug fix
- ⬜ 15B — 16,700 lots dedup
- ⬜ 15C — Tax-loss harvesting guidance
- ⬜ 15D — Account filter

### 16. Actions (/v2/actions)
- ⬜ 16A — Pipeline runtime guidance
- ⬜ 16B — Reprice usage guidance
- ⬜ 16C — Pending tasks link
- ⬜ 16D — Account impact notes

### 17. Attribution (/v2/attribution)
- ✅ 17A — Alpha N/A explanation
- ⬜ 17B — Benchmark rationale
- ⬜ 17C — Inception date
- ⬜ 17D — Multi-account contribution note
- ✅ 17E — Sharpe/Sortino interpretation
- ⬜ 17F — Max drawdown context
- ⬜ 17G — Benchmark CAGR explanation

### 18. Correlation (/v2/correlation)
- ✅ 18A — "10 symbols" selection explanation
- ✅ 18B — High-correlation action guidance
- ⬜ 18C — Legend middle band
- ⬜ 18D — Diversification score
- ⬜ 18E — BND diversifier callout

### 19. Research (/v2/research)
- ✅ 19A — Cache explanation
- ⬜ 19B — Default ticker fix
- ⬜ 19C — Staleness indicator
- ⬜ 19D — 0 articles explanation
- ⬜ 19E — Add to Watchlist button
- ⬜ 19F — SMA% color coding

### 20. Watchlist (/v2/watchlist)
- ⬜ 20A — Workflow description header
- ⬜ 20B — AI Discovered vs AI Watchlist tooltip
- ⬜ 20C — PENDING explanation
- ⬜ 20D — Stage legend
- ⬜ 20E — R:R explanation
- ⬜ 20F — Submit workflow helper
- ⬜ 20G — Create Approval path

### 21. Trade AI (/v2/trade-ai)
- ✅ 21A — Account banner (Taxable only)
- ⬜ 21B — Position sizing guidance
- ⬜ 21C — WAIT explanation
- ⬜ 21D — NO GO list visible
- ✅ 21E — Grade legend
- ⬜ 21F — DELTAS tooltip
- ⬜ 21G — Catalyst quality flag
- ⬜ 21H — Copy ticker tooltip

### 22. Journal (/v2/journal)
- ✅ 22A — Trade count filter clarification
- ⬜ 22B — P&L by account
- ⬜ 22C — Trade type clarification
- ⬜ 22D — 401k fund trade note
- ⬜ 22E — Expectancy interpretation
- ⬜ 22F — Review prompt
- ⬜ 22G — Calendar navigation guide

### 23. Journal Analytics (/v2/journal-analytics)
- ⬜ 23A — CTA to review trades
- ⬜ 23B — Execution score explanation
- ⬜ 23C — Min sample size threshold
- ⬜ 23D — Emotion tagging prompt

### 24. System Health (/v2/system-health)
- ⬜ 24A — Ollama offline guidance
- ⬜ 24B — API key display fix
- ⬜ 24C — Spend tracking fix
- ⬜ 24D — Database state fallback
- ⬜ 24E — Screener count fix

### 25. Orchestration (/v2/orchestration)
- ⬜ 25A — Job health indicators
- ⬜ 25B — Long duration flag
- ⬜ 25C — Services description
- ⬜ 25D — Skills list expandable
- ⬜ 25E — Failed check remediation
- ⬜ 25F — Token refresh tooltip

### 26. Alerts & Actions (/v2/alerts)
- ⬜ 26A — Button text labels
- ⬜ 26B — Alert priority colors
- ⬜ 26C — Journal stats context
- ⬜ 26D — Risk data timestamp

### 27. Notifications (/v2/notifications)
- ⬜ 27A — Ticker names in subjects
- ⬜ 27B — Draft vs urgent explanation
- ⬜ 27C — View full message button
- ⬜ 27D — Export destination note

### 28. Ops Console (/v2/ops)
- ⬜ 28A — Import CSV format guidance
- ⬜ 28B — Pipeline hash tooltip
- ⬜ 28C — Dead rows guidance
- ⬜ 28D — Table row count note
- ⬜ 28E — Last import timestamp

---

## COMPLETED SO FAR
- ✅ NaNd bug (format.ts — timeAgo strips timezone suffixes)
- ✅ Overview tooltips: Total Value, Cash breakdown, Beta interpretation, Income Target/Gap/Roth Room actionable context
- ✅ FRED macro dashboard (color-coded temperature tiles)
- ✅ Morning Brief: agent modals, escalation paths, holdings context, Aegis content, raw toggle, dedup

## PRIORITY FOR NEXT SESSIONS
1. Global pattern G1 (account badges) — fixes 15+ items across all pages
2. Rebalance page (#3) — highest-priority page per audit
3. Tax page bugs (#15A-B)
4. Risk page price $0 bug (#5D)
5. System Health display fixes (#24)
