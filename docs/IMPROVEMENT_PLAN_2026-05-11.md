# Trade AI v12 — Phased Improvement Plan
**Created:** 2026-05-11 | **Starting Grade:** 2.5/10 | **Target:** 7/10

---

## Phase 1: Fix What's Broken (Immediate — This Session)

**Status: DONE**

| # | Item | Status |
|---|------|--------|
| 1.1 | Telegram alert dedup — stop daily duplicate urgent_alert + draft_alert | DONE |
| 1.2 | Dividend alerting — surface current month payers via Telegram | DONE |
| 1.3 | CIO decision dedup — 24h gate in cio_decision_engine.py | DONE |
| 1.4 | StockTwits pipeline — persist pre-market data to DB | DONE |
| 1.5 | Recovery watch — exit classification (stop-out vs relist) | DONE |
| 1.6 | 4 missing API endpoints (recovery, cio, portfolio-monitor, reports) | DONE |
| 1.7 | Prospects — entry/stop/target via ATR fallback | DONE |
| 1.8 | Weekly DOCX report generator + cron | DONE |
| 1.9 | Documentation updated | DONE |
| 1.10 | Full system audit completed | DONE |

---

## Phase 2: Noise Reduction & Alert Quality (Next Session)

**Goal:** Every alert that reaches Telegram should be actionable and non-repetitive.

| # | Item | Effort | Impact |
|---|------|--------|--------|
| 2.1 | Audit all 55+ Telegram-sending scripts — classify each as: KEEP, CONSOLIDATE, ELIMINATE | 2h | High |
| 2.2 | Build a central alert dispatcher that deduplicates across ALL scripts (not per-script dedup) | 3h | High |
| 2.3 | Implement alert escalation tiers: INFO (dashboard only) → ALERT (Telegram) → URGENT (Telegram + sound) | 2h | High |
| 2.4 | Fix email digest — diagnose why it stopped after May 6 and restore | 1h | Medium |
| 2.5 | Add "alert fatigue" monitoring — if same alert fires >3 days, auto-downgrade to dashboard-only and surface a META alert: "Unresolved condition: X has been alerting for N days" | 2h | High |
| 2.6 | Add missing alerts: API credit depletion, proposal aging (>7 days PENDING), pipeline failure self-monitoring | 1h | Medium |
| 2.7 | Telegram morning brief upgrade — add dividends due, proposal actions needed, overnight price changes for holdings | 2h | High |

---

## Phase 3: Page Consolidation (1-2 Sessions)

**Goal:** 61 pages → ~40 pages. Every page must justify its existence.

| # | Merge | Pages Combined | New Page Name |
|---|-------|----------------|---------------|
| 3.1 | Portfolio Command | Portfolio + Portfolio Monitor + Portfolio Intelligence | `/portfolio` with tabs: Holdings / Health / Intelligence |
| 3.2 | Trade Journal | Journal + Journal Analytics + Journal Reports | `/journal` with tabs: Entries / Analytics / Reports |
| 3.3 | Paper Trading | Paper Outcomes + Paper Trade Intelligence + Paper Journal | `/paper-outcomes` with tabs: Outcomes / TCA / Journal |
| 3.4 | Pipeline Ops | Pipeline Health Master + Pipeline Controller | `/pipeline` with tabs: Overview / Stages |
| 3.5 | Alerts Hub | Alerts & Actions + Notifications + Action Center | `/inbox` — unified attention queue |
| 3.6 | Governance | Live Governance + Paper Governance + Learning Governance + Approvals | `/governance` with sections |
| 3.7 | System Ops | System Hub + Ops + Orchestration | `/ops` with tabs |
| 3.8 | Intelligence | Intelligence Sources + Entities + Whiteboard + Content Health | `/intelligence` with tabs |
| 3.9 | Eliminate | Correlation, Live Governance, Forecast | Remove routes |

**Implementation approach:** Tab-based components. Each "tab" is the existing page component, rendered inside a shared TabLayout container. Minimal code change — mostly router restructuring.

---

## Phase 4: Intelligence Delivery (1-2 Sessions)

**Goal:** Every page surfaces relevant intelligence from the ingestion/enrichment pipeline. Data exists — it needs to be connected.

| # | Item | What Changes |
|---|------|-------------|
| 4.1 | Unified Morning Command Page | New `/command` page: portfolio health, overnight changes, dividends due, proposals needing action, recovery items, top news, social sentiment — single starting point |
| 4.2 | Portfolio page — add news, catalysts, social sentiment per holding | Query news_articles + social_sentiment_history per symbol |
| 4.3 | Watchlist page — add price alerts, earnings dates, technical levels | Query indicator_confluence_cache + portfolio_alerts data |
| 4.4 | Prospects page — add LLM narrative when available | Display llm_screen_result from incubator |
| 4.5 | Recovery page — add technical chart links, sector context | Cross-reference with technical_snapshot + sector data |
| 4.6 | CIO page — add news context per decision symbol | Show recent news/catalysts that support or contradict the recommendation |
| 4.7 | Reports page — add intelligence summary (market sentiment, sector trends, key events) | Aggregate from news_articles + social + event_detector |
| 4.8 | Surface "what changed overnight" delta on every relevant page | Compare today's data vs yesterday's snapshot |

---

## Phase 5: Local LLM Integration (1-2 Sessions)

**Goal:** qwen3:14b is running but underutilized. Connect it to more surfaces.

| # | Item | What Changes |
|---|------|-------------|
| 5.1 | Rebalance local LLM fallback | When Anthropic API is unavailable, use qwen3:14b to generate rebalance suggestions from holdings + YAML targets |
| 5.2 | Watchlist LLM health refresh | Run holdings_llm_refresh for watchlist symbols, not just holdings |
| 5.3 | Prospects LLM narrative | For top-scored prospects, generate a 2-sentence thesis via qwen3:14b |
| 5.4 | Morning brief LLM synthesis | Use qwen3:14b to synthesize overnight news + portfolio changes into a narrative paragraph |
| 5.5 | Recovery watch LLM analysis | For reentry candidates, generate technical + catalyst analysis |
| 5.6 | Portfolio risk narrative | LLM-generated portfolio risk assessment from holdings + stops + heat |

---

## Phase 6: UI/UX Professionalization (1-2 Sessions)

**Goal:** Consistent layout, professional presentation. Prop desk standard.

| # | Item | What Changes |
|---|------|-------------|
| 6.1 | Shared page template | Header with page title + data freshness badge + global alert banner. All pages use same layout. |
| 6.2 | Global alert banner | Persistent banner for critical conditions (heat > 5%, positions without stops, stale data) across all pages |
| 6.3 | Consistent terminology | Standardize: "Prospects" (not "Trade AI Scan Results"), "Watchlist" (not "Symbol Master"), "Portfolio" (not "Holdings") |
| 6.4 | "Today's Actions" panel | Top of Overview page: prioritized list of things needing attention. Sourced from: proposals needing review, stops needing confirmation, recovery items, rebalance suggestions. |
| 6.5 | Data freshness badges | Every page shows when its data was last refreshed with color: green (<1h), yellow (1-6h), red (>6h) |
| 6.6 | Print/export capability | Every page can export its current view as PDF or CSV |
| 6.7 | Mobile responsiveness audit | Ensure key pages (Portfolio, Watchlist, Alerts) work on mobile for Telegram deep-links |

---

## Phase 7: Feedback Loop Closure (Ongoing)

**Goal:** Decisions → outcomes → learning → improved recommendations.

| # | Item | What Changes |
|---|------|-------------|
| 7.1 | Track human decisions on CIO recommendations | When user acts on (or ignores) a CIO decision, log the outcome |
| 7.2 | Proposal outcome tracking | Link approved proposals → paper trades → P&L outcomes back to the recommending agent |
| 7.3 | Alert effectiveness scoring | Track which alerts led to action vs were ignored. Downrank ignored alert types. |
| 7.4 | Strategy performance review automation | Weekly auto-generated strategy assessment from paper trade data |
| 7.5 | Agent calibration with sufficient sample size | Grow from 3 closed trades to 30+ for meaningful agent accuracy |
| 7.6 | Recovery watch outcome tracking | When relisted items eventually exit, capture whether patience scoring was correct |

---

## Phase 8: Production Readiness (Future)

**Goal:** System ready for live trading consideration.

| # | Item | What Changes |
|---|------|-------------|
| 8.1 | API authentication | Add auth layer before any network exposure |
| 8.2 | Automated backup verification | Test restore from backup monthly |
| 8.3 | High availability | Document single-point-of-failure risks and mitigation |
| 8.4 | Performance budget | Define max API response times, pipeline completion windows |
| 8.5 | Live trading gate validation | 55% win rate + 1.3 PF over 6 months of paper trading |
| 8.6 | Broker integration testing | Verify Alpaca live order flow before enabling |

---

## Priority Sequence

```
Phase 1 ████████████████████ DONE (this session)
Phase 2 ████░░░░░░░░░░░░░░░░ Next (alert quality)
Phase 3 ░░░░░░░░░░░░░░░░░░░░ (page consolidation)
Phase 4 ░░░░░░░░░░░░░░░░░░░░ (intelligence delivery)
Phase 5 ░░░░░░░░░░░░░░░░░░░░ (LLM integration)
Phase 6 ░░░░░░░░░░░░░░░░░░░░ (UI/UX)
Phase 7 ░░░░░░░░░░░░░░░░░░░░ (feedback loops)
Phase 8 ░░░░░░░░░░░░░░░░░░░░ (production readiness)
```

**Estimated progression:**
- After Phase 2: 3.5/10
- After Phase 3: 4.5/10
- After Phase 4: 5.5/10
- After Phase 5: 6.5/10
- After Phase 6: 7.5/10
- After Phase 7+8: 8.5/10
