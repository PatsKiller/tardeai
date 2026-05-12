# UX Audit Implementation Tracker
**Source:** Comprehensive UI/UX Improvement Prompt (April 30, 2026)
**Total items:** 130+ across 28 pages + 15 global patterns
**Status:** In progress

## Legend
- ✅ Done
- 🔧 In progress

---

## CRITICAL BUGS (🔴)
- ✅ #9B — NaNd timestamp bug (timeAgo strips ET/EST/EDT timezone suffixes)
- ✅ #15A — Tax page $0 values FIXED — backend now enriches from holdings prices + enrichment cache
- ✅ #15B — Tax page lots FIXED — 135 open lots (was 16,700) — closed/sold lots now excluded + dedup
- ✅ #24B-C — System Health: shows Ready/configured status + delta subtitles + Ollama guidance
- ✅ #9G — Heat inconsistency (labeled "Stop Risk Heat" with interpretation)
- ✅ G12 — Journal trade count (filter clarification in subtitle)

## GLOBAL PATTERNS (applies to ALL pages)
- ✅ G1 — Account badges on recommendation cards (Portfolio, Rebalance, Recovery, CIO)
- ✅ G2 — Funding source (Rebalance account summary shows cash per account)
- ✅ G3 — Broker execution disclaimer (Rebalance, CIO, Approvals, Trade AI have banners)
- ✅ G4 — Data staleness indicators (Rebalance stale banner, Research cache note)
- ✅ G5 — Heat definition consistency (Risk page: "Stop Risk Heat" with interpretation)
- ✅ G6 — 401k visual indicator (Portfolio subtotals 🏦, Rebalance Fidelity note)
- ✅ G7 — NaN bug FIXED in format.ts
- ✅ G8 — Workflow breadcrumb on Overview (Watchlist → Approval → Portfolio → Journal → Analytics)
- ✅ G9 — System Health ↔ Orchestration cross-links (subtitles + nav buttons both directions)
- ✅ G10 — N/A — "Stop Claude" button doesn't exist in v2 (was v1 only)
- ✅ G11 — Personal Situation modal (👤 button in header bar opens AdminModals personal view)
- ✅ G13 — Brave Search credit warning (red banner on Intel Sources when calls ≥ daily limit)
- ✅ G14 — Reports "Latest Report" sticky card at top (auto-detects most recent)
- ✅ G15 — Trade AI mode separation (⚡ icon in nav + persistent "Taxable scalps only" banner)

## PAGE-BY-PAGE STATUS

### 1. Overview (/v2)
- ✅ 1A — Income Target tooltip (SSDI replacement explanation)
- ✅ 1B — Roth Room tooltip (convert FROM Rollover IRA → Roth)
- ✅ 1C — Pending approvals urgency (stop-triggered + governance context in alert banner)
- ✅ 1D — GO setups account context (Taxable only)
- ✅ 1E — Cash breakdown by account
- ✅ 1F — Beta interpretation tooltip
- ✅ 1G — Period returns 6M/1Y insufficient history note (subtitle: "require 180+/365+ days")
- ✅ 1H — Latest News 0 explanation

### 2. Portfolio/Holdings (/v2/portfolio)
- ✅ 2A — PI Score tooltip (interpretation by range: Strong ≥65, Moderate 40-64, Weak <40)
- ✅ 2B — Decision column legend (ADD/TRIM/WATCH/MONITOR)
- ✅ 2C — Funding source (Decision column already shows account + 401k via Fidelity)
- ✅ 2D — 401k positions gain "—" tooltip (Fidelity reports account-level only)
- ✅ 2E — 401k TRIM guidance (via Fidelity) in Decision column
- ✅ 2F — 401k gain "—" tooltip explanation
- ✅ 2G — Account subtotals (clickable cards with value, position count, cash, gain)

### 3. Rebalance (/v2/rebalance) — HIGHEST PRIORITY
- ✅ 3A — Account field on every recommendation (already shown in rec cards)
- ✅ 3B — V trim execution guidance (shown in recommendations)
- ✅ 3C — JEPI stop — account context (in recommendations)
- ✅ 3D — Stale data banner (freshness indicator already present)
- ✅ 3E — YAML Health Score explanation + config path tooltip
- ✅ 3F — Advisory disclaimer to top
- ✅ 3G — YAML config path link (config/portfolio_config.yaml in Health Score)
- ✅ 3H — Per-account next action summary (BUY/ADD/SELL/TRIM counts + 401k Fidelity note)

### 4. Recovery Watch (/v2/recovery)
- ✅ 4A — "Stay Cash" account context (subtitle: "Freed capital stays as cash in original account")
- ✅ 4B — Money market specifics (SPAXX/FZFXX in subtitle)
- ✅ 4C — "Alternatives" section already labeled properly
- ✅ 4D — Re-entry monitoring guidance ("Monitor daily via Technical page. Aegis auto-reviews")
- ✅ 4E — Invalidation guidance ("capital rotates to next conviction or stays cash")
- ✅ 4F — Total freed capital summary (MetricTile with total)

### 5. Risk Manager (/v2/risk)
- ✅ 5A — Unprotected 401k/mutual fund explanation
- ✅ 5B — Heat definition + action guidance
- ✅ 5C — Stop Distance tooltip (distance interpretation + "CLOSE/Approaching/Comfortable" + "No stop set" for nulls)
- ✅ 5D — Price $0 FIXED — backend now enriches from holdings.json + enrichment cache. Prices populate correctly.
- ✅ 5E — Protection improvement (escalation lane + stop confirmation section)

### 6. Retirement (/v2/retirement)
- ✅ 6A — Roth conversion FROM account
- ✅ 6B — Remaining $16K guidance (bracket room section)
- ✅ 6C — Golden Window explanation
- ✅ 6D — 401k loan payoff guidance
- ✅ 6E — IRMAA forward warning
- ✅ 6F — Medicaid context
- ✅ 6G — Medicare enrollment (in Medicaid/Medicare section)
- ✅ 6H — Roth allocation commentary

### 7. AI Analyst (/v2/ai-analyst)
- ✅ 7A — Action items (already have account in Morning Brief agent cards)
- ✅ 7B — Worthless security guidance (Tax lot drawer: $0 value + cost basis → Fidelity disposal form)
- ✅ 7C — Agent last run (shown in agent health widget)
- ✅ 7D — Tab descriptions (already added in prior batch)
- ✅ 7E — Reports tab (description present)

### 8. CIO Dashboard (/v2/cio)
- ✅ 8A — Account column on decisions (backend enriches from holdings + AccountBadge in table)
- ✅ 8B — Status code legend (in page subtitle: ADD_REVIEW, HUMAN_REVIEW explained)
- ✅ 8C — Agent count context (Agent Activity section with totals)
- ✅ 8D — V ADD funding source (advisory banner present)
- ✅ 8E — Rotation proposals (MetricTile shown)
- ✅ 8F — MARL SIMS tooltip (explanation of shadow simulations)

### 9. Morning Brief (/v2/morning-brief)
- ✅ 9B — NaNd bug fixed
- ✅ 9A — Stop triggered (shown in Risk card with triggered count + symbols)
- ✅ 9C — Covered call execution guidance (30-delta, 21-45 DTE, ≥0.5% premium)
- ✅ 9D — Covered call strike/expiry (inline guidance in MorningBrief Opportunity panel)
- ✅ 9E — Rotation account context (rotations section shows from→to)
- ✅ 9F — FRED macro dashboard (color-coded tiles done)
- ✅ 9G — Heat labels (Risk card shows "Stop Risk Heat" with interpretation)

### 10. Approvals (/v2/approvals)
- ✅ 10A — Account on approval cards (backend enriches from holdings + AccountBadge in header)
- ✅ 10B — "Auto-review failed" explanation (in advisory banner)
- ✅ 10C — Total dollar impact (exposure shown in decision_summary)
- ✅ 10D — Tasks vs Approvals distinction (in advisory banner)
- ✅ 10E — URGENT urgency color coding (urgencyColor map + badge)

### 11. Forecast (/v2/forecast)
- ✅ 11A — Assumptions to top
- ✅ 11B — Inflation note (subtract ~3%/yr + purchasing power example)
- ✅ 11C — RMD impact (begin age 73, Roth conversion planning)
- ✅ 11D — 401k yield caveat (mutual fund reporting vs ETF)
- ✅ 11E — Rollover IRA tax concentration note

### 12. Dividends (/v2/dividends)
- ✅ 12A — "Watch" safety explanation
- ✅ 12B — Account breakdown (already in payers table by account)
- ✅ 12C — Gap closure guidance (SCHD/JEPI strategy, Rollover IRA focus)
- ✅ 12D — Qualified dividend tax explanation

### 13. Technical (/v2/technical)
- ✅ 13A — PI Score interpretation
- ✅ 13B — Near Stop prioritization (sorted by weakest PI first)
- ✅ 13C — 52-week range interpretation (color-coded + tooltip)
- ✅ 13D — Account column (shown in card subtitle)

### 14. Returns (/v2/returns)
- ✅ 14A — Roth YTD anomaly badge
- ✅ 14B — 6M/1Y insufficient history note
- ✅ 14C — Rollover IRA loss context (pre-tax, no tax deduction, focus on recovery)

### 15. Tax & Lots (/v2/tax)
- ✅ 15A — $0 data bug FIXED (backend enriches open lots with live prices)
- ✅ 15B — Lots dedup FIXED (135 open lots, closed/sold excluded, dedup key)
- ✅ 15C — Tax-loss harvesting guidance (harvest candidates metric + Taxable-only filter + per-lot action)
- ✅ 15D — Account filter (pill tabs for All/Taxable/Roth/Roll IRA/401k)

### 16. Actions (/v2/actions)
- ✅ 16A — Pipeline runtime (desc field: "Full daily pipeline" + "Fast ~30s")
- ✅ 16B — Reprice usage (desc: "Refresh current prices without full pipeline")
- ✅ 16C — Pending tasks (output/dest fields navigate to relevant pages)
- ✅ 16D — Account impact (advisory banner + output descriptions)

### 17. Attribution (/v2/attribution)
- ✅ 17A — Alpha N/A explanation
- ✅ 17B — Benchmark rationale (60% SPY + 25% ITA + 15% AGG, sector tilt)
- ✅ 17C — Inception date (in Benchmark Context card)
- ✅ 17D — Multi-account contribution note (all 4 accounts combined)
- ✅ 17E — Sharpe/Sortino interpretation
- ✅ 17F — Max drawdown context (significance assessment based on %)
- ✅ 17G — Benchmark CAGR explanation (blended label + component breakdown)

### 18. Correlation (/v2/correlation)
- ✅ 18A — "10 symbols" selection explanation
- ✅ 18B — High-correlation action guidance
- ✅ 18C — Legend middle band (0.40–0.70 Moderate)
- ✅ 18D — Diversification score (Good/Moderate/Needs Work + pair counts)
- ✅ 18E — BND diversifier callout (bond ETF suggestion when missing)

### 19. Research (/v2/research)
- ✅ 19A — Cache explanation
- ✅ 19B — Default ticker (first ticker auto-selected)
- ✅ 19C — Staleness (articles ingested nightly note)
- ✅ 19D — 0 articles explanation (24h delay for new tickers)
- ✅ 19E — Add to Watchlist button (+ Watchlist with personal_watchlist source)
- ✅ 19F — SMA% color coding (bullish/bearish tooltips on SMA rows)

### 20. Watchlist (/v2/watchlist)
- ✅ 20A — Workflow description (subtitle: "Pipeline: Raw → Strategy → Agent Review → Synthesized → Approval")
- ✅ 20B — AI Discovered vs AI Watchlist (source badges with tooltip: D=discovered, W=watchlist)
- ✅ 20C — PENDING explanation (DecisionBadge with PENDING/PARTIAL/CONFLICT labels)
- ✅ 20D — Stage legend (StageBadge with RAW/STRATEGY/ROUTED/PARTIAL/REVIEWED/SYNTHESIZED)
- ✅ 20E — R:R explanation (color-coded: ≥2 green, ≥1 amber, <1 red)
- ✅ 20F — Submit workflow helper (Submit bar with agent/type/note)
- ✅ 20G — Create Approval path (Full Chain submit button in drawer)

### 21. Trade AI (/v2/trade-ai)
- ✅ 21A — Account banner (Taxable only)
- ✅ 21B — Position sizing guidance (risk $150, shares calc, max position in drawer)
- ✅ 21C — WAIT explanation (in banner: marginal score 35-44)
- ✅ 21D — NO GO visible (in MetricTile row + filter)
- ✅ 21E — Grade legend
- ✅ 21F — DELTAS tooltip ("score/decision changes vs prior run")
- ✅ 21G — Catalyst quality (shown in drawer Catalyst section)
- ✅ 21H — Copy ticker (TOS export section with Copy button)

### 22. Journal (/v2/journal)
- ✅ 22A — Trade count filter clarification
- ✅ 22B — P&L by account (account filter pill row)
- ✅ 22C — Trade type (shown in Type column + filter row)
- ✅ 22D — 401k fund trade (account in trade detail drawer)
- ✅ 22E — Expectancy interpretation (tooltip: edge, commissions, formula)
- ✅ 22F — Review (drawer Review tab with save)
- ✅ 22G — Calendar navigation (prev/next buttons)

### 23. Journal Analytics (/v2/journal-analytics)
- ✅ 23A — CTA to review trades (banner with Open Journal button)
- ✅ 23B — Execution score (in Summary strip with color coding)
- ✅ 23C — Min sample size threshold (subtitle: 10+ for reliable, 30+ for strong)
- ✅ 23D — Emotion tagging prompt (existing: "Tag emotions in Psychology tab")

### 24. System Health (/v2/system-health)
- ✅ 24A — Ollama offline guidance (amber banner with restart command)
- ✅ 24B — API key display (shows "ANTHROPIC_API_KEY set" / model name)
- ✅ 24C — Spend tracking (shows budget used/remaining with color + "EXCEEDED" label)
- ✅ 24D — Database state fallback (shows "unavailable" message when empty)
- ✅ 24E — Screener count (shows DB count + note if discrepancy)

### 25. Orchestration (/v2/orchestration)
- ✅ 25A — Job health indicators (overdue ⚠️ when last_start >48h ago)
- ✅ 25B — Long duration flag (amber "(long)" when >60min)
- ✅ 25C — Services description (shown from API data)
- ✅ 25D — Skills list (rendered with agent/skill type badge)
- ✅ 25E — Failed check remediation ("Pipeline will not run if check fails")
- ✅ 25F — Token refresh (schedule shown in timer table)

### 26. Alerts & Actions (/v2/alerts)
- ✅ 26A — Button text labels (already have action labels)
- ✅ 26B — Alert priority colors (already done in prior batch)
- ✅ 26C — Journal stats (journal metrics shown: P&L, win rate, trade count)
- ✅ 26D — Risk data (heat_pct shown + triggered stops)

### 27. Notifications (/v2/notifications)
- ✅ 27A — Ticker names (shown in subject/body)
- ✅ 27B — Draft vs urgent explanation (already done in prior batch)
- ✅ 27C — View full message (Toggle Full/Summary button in notification detail, body column fallback)
- ✅ 27D — Export destination (Telegram channel noted)

### 28. Ops Console (/v2/ops)
- ✅ 28A — Import CSV format guidance (already done in prior batch)
- ✅ 28B — Pipeline hash (shown in audit data)
- ✅ 28C — Dead rows guidance (already done in prior batch)
- ✅ 28D — Table row count (shown in DB stats)
- ✅ 28E — Last import timestamp (recent_imports in audit)

---

## COMPLETED SO FAR
- ✅ NaNd bug (format.ts — timeAgo strips timezone suffixes)
- ✅ Overview tooltips: Total Value, Cash breakdown, Beta interpretation, Income Target/Gap/Roth Room actionable context
- ✅ FRED macro dashboard (color-coded temperature tiles)
- ✅ Morning Brief: agent modals, escalation paths, holdings context, Aegis content, raw toggle, dedup
- ✅ Batch 14: Portfolio account subtotals + PI tooltips + 401k gain explanation
- ✅ Batch 14: Rebalance YAML Health explanation + config path + per-account actions
- ✅ Batch 14: Recovery Watch freed capital + re-entry monitoring + invalidation guidance
- ✅ Batch 14: Trade AI position sizing + WAIT/DELTAS tooltips + grade in drawer
- ✅ Batch 14: Research Add to Watchlist + SMA tooltips + 0 articles explanation
- ✅ Batch 14: Correlation diversification score + BND callout + middle band legend
- ✅ Batch 14: Attribution benchmark rationale + multi-account note + max drawdown context
- ✅ Batch 14: Forecast inflation + RMD + 401k yield caveat
- ✅ Batch 14: Technical near-stop priority sort + 52W range color + account column
- ✅ Batch 14: Dividends gap closure strategy + account context
- ✅ Batch 14: Journal expectancy tooltip
- ✅ Batch 14: JournalAnalytics CTA + sample size + subtitle context

## PRIORITY FOR REMAINING
1. Tax page bugs (#15A-B) — backend required
2. Risk page #5C-D — stop distance / price $0
3. System Health display fixes (#24) — backend required
4. Orchestration (#25) — backend required
5. Remaining frontend: Returns 14C, CIO 8A-F, Approvals 10A-E, Morning Brief 9A/C/D/E, Watchlist 20B-G
6. Global patterns G1-G15
