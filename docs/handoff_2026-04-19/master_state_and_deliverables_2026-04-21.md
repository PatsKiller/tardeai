# Master State & Deliverables Ledger

**Version:** 1.0  
**Date:** 2026-04-21  
**System:** Trade AI v12 + OpenClaw Portfolio Advisor  
**Server:** ms01-openclaw (Ubuntu 25.10, 64GB RAM, PostgreSQL 17.9)

---

## 1. Executive Summary

The system is a **multi-layer portfolio intelligence platform** with three roles:
1. **Trade AI** — scalp/day-trade screener (Finviz → scoring → dashboard)
2. **Portfolio Intelligence** — portfolio monitoring, AI analysis, reporting, performance tracking
3. **OpenClaw Advisor** — emerging advisor-memory layer with observations, escalations, recommendations, and market intelligence history

**Major layers complete:**
- Full Postgres activation (18 tables, all dual-write paths verified)
- Automated backup mechanism (daily pg_dump timer, 30-day retention — manual dump path needs re-verification)
- Data freshness gate with holdings-hash cache invalidation
- Advisor memory foundation (observations, escalations, daily summary, recommendation drafts)
- Market intelligence history (ticker snapshots, analyst consensus, Yahoo targets, article index)
- Multi-source watchlist (user + analyst-curated, CC modal)
- Steph bridge skill (read-only query to advisor memory, 5 query types)

**Still deferred:** Notifications, approval/action gate, external model escalation, AI-generated watchlists, forecast engine.

---

## 2. Completed Deliverables

### TradeAI Database Activation (Tier 1-3, Tasks 1-12)

| Deliverable | Status | Key Components |
|------------|:---:|---|
| P2-1: portfolio_snapshots writes | ✅ | .env loader in portfolio_performance.py |
| P2-2: price_cache mirror | ✅ | 130,984 rows backfilled |
| P5-1: Automated pg_dump backups | ✅ (mechanism) | run_pg_backup.sh + portfolio-backup.timer. Manual backup path needs re-verified .env-safe DB dump command. |
| Phase 0: Data freshness gate | ✅ | _freshness.json + /api/freshness + holdings_hash |
| P2-3: run_summary writes | ✅ | save_run_summary() in trade_ai_orchestrator |
| P2-4: trade_ai_state writes | ✅ | save_state() in delta_tracker (47 tickers/day) |
| P3-1: performance_daily table | ✅ | Computed returns per day, numpy pre-cleaned |
| P5-2/P5-3: Autovacuum + /api/db/health | ✅ | 3 tables tuned + health endpoint |
| P3-2: intel_briefs table | ✅ | Brief generation history |
| Phase 4: Smart cache invalidation | ✅ | holdings_hash + personal-write invalidation |
| P3-3: action_signals_history | ✅ | 40 rows/day, per-ticker daily signal history |

### OpenClaw Advisor Foundation

| Deliverable | Status | Key Components |
|------------|:---:|---|
| Phase A1: dividend_history + advisor_observations | ✅ | 11 dividend tickers + 7 observations/run |
| Phase A2-supervisory: escalation_queue | ✅ | 5 trigger rules, 3 escalations/day |
| Phase A2-enrichment: Ollama daily summary | ✅ | qwen3:1.7b, think:False, banned-phrase validation |
| Steph bridge skill | ✅ | advisor_memory_reader.py, 5 query types |
| Recommendation drafts | ✅ | Rule-template from severity 1-2, Yahoo + article context |

### Market Intelligence Layer

| Deliverable | Status | Key Components |
|------------|:---:|---|
| ticker_snapshot_daily | ✅ | 84 tickers, 43 fields, daily enrichment history |
| analyst_consensus_history | ✅ | 57 tickers (Finviz-derived placeholder) |
| yahoo_analyst_targets_history | ✅ | 36 stocks, real consensus (authoritative) |
| article_index | ✅ | URL-deduped, 40+ articles/day, portfolio + watchlist |
| Watchlist article coverage | ✅ | User watchlist symbols in news fetch + scoring |
| Article-backed recommendation rationale | ✅ | Drafts cite 7-day article context |

### Watchlist System

| Deliverable | Status | Key Components |
|------------|:---:|---|
| watchlist_items table | ✅ | UNIQUE(symbol, source_type), Postgres-backed |
| User watchlist modal (CC) | ✅ | Add/remove with dual-write, JSON compatibility |
| Analyst-curated watchlist (manual) | ✅ | API + CC modal for manual add/remove, Postgres-only. No automated ingestion from news/analyst signals yet. |

### Bug Fixes

| Fix | Status |
|-----|:---:|
| RVOL/gap/float missing from Trade AI scoring (v=111→v=152) | ✅ |
| Garbled Telegram emoji encoding (continuous_runner.py) | ✅ |
| Data quality alert for missing screener columns | ✅ |
| Copy WAIT button + clipboard fix (html_dashboard.py) | ✅ |

### Documentation

| Doc | Status |
|-----|:---:|
| schemas_reference v2.0 | ✅ |
| Security cleanup (13 passwords removed) | ✅ |
| Path corrections + status corrections | ✅ |
| 67 markdown files in docs/handoff_2026-04-19/ | ✅ |

---

## 3. Current Live Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    USER (John)                            │
│            Telegram / WhatsApp / CC Browser               │
└─────┬─────────────────────┬──────────────────────────┬───┘
      │                     │                          │
      ▼                     ▼                          ▼
┌─────────────┐   ┌─────────────────┐   ┌──────────────────┐
│ MARIA (🌿)  │   │ STEPH (📊)      │   │ Command Center   │
│ Personal    │──▶│ Wealth Advisor  │   │ (port 7777)      │
│ Assistant   │   │ + Bridge Skill  │   │ Watchlist Modal  │
└─────────────┘   └────────┬────────┘   └─────────┬────────┘
                           │ reads                  │ reads/writes
                           ▼                        ▼
┌──────────────────────────────────────────────────────────┐
│                  PORTFOLIO SERVER (7777)                   │
│  /api/health  /api/freshness  /api/db/health              │
│  /api/personal/*  /api/watchlist/*  /api/env/*            │
└─────────────────────────────┬────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────┐
│              POSTGRESQL (18 tables)                        │
│  Operational: holdings, personal_history, price_cache,    │
│    portfolio_snapshots, run_summary, trade_ai_state,      │
│    performance_daily, intel_briefs, action_signals_history │
│  Advisor: advisor_observations, escalation_queue,         │
│    advisor_recommendations, dividend_history               │
│  Market Intel: ticker_snapshot_daily,                     │
│    analyst_consensus_history, yahoo_analyst_targets_history│
│    article_index, watchlist_items                          │
└──────────────────────────────────────────────────────────┘
```

---

## 4. Database Table Inventory (18 tables)

| Table | Purpose | Rows/Day | Source |
|-------|---------|:---:|--------|
| `holdings` | Daily portfolio JSONB snapshot | 1 | portfolio_loader |
| `personal_history` | Personal situation field changes | On edit | portfolio_server |
| `price_cache` | OHLCV prices (2020-present) | 130K total | portfolio_price_cache |
| `portfolio_snapshots` | Daily total value | 1 | portfolio_performance |
| `run_summary` | Trade AI run results | 1-4 | trade_ai_orchestrator |
| `trade_ai_state` | Per-ticker delta tracking | ~47 | delta_tracker |
| `performance_daily` | Computed period returns | 1 | portfolio_orchestrator |
| `intel_briefs` | Brief generation log | 1 | portfolio_orchestrator |
| `action_signals_history` | Per-ticker daily signals | ~40 | portfolio_signals |
| `advisor_observations` | Agent memory (observations) | ~8 | portfolio_orchestrator |
| `escalation_queue` | Threshold-crossing queue | ~3 | portfolio_orchestrator |
| `advisor_recommendations` | Review-oriented drafts | ~2 | portfolio_orchestrator |
| `dividend_history` | Per-ticker yield tracking | ~11 | portfolio_orchestrator |
| `ticker_snapshot_daily` | 43-field enrichment history | ~84 | portfolio_orchestrator |
| `analyst_consensus_history` | Finviz-derived analyst signal | ~57 | portfolio_orchestrator |
| `yahoo_analyst_targets_history` | Real analyst consensus | ~36 | portfolio_orchestrator |
| `article_index` | News metadata (URL-deduped) | ~40 | portfolio_orchestrator |
| `watchlist_items` | Multi-source watchlist | On edit | portfolio_server |

---

## 5. OpenClaw Agent Inventory

| Agent | Status | Key Config |
|-------|--------|-----------|
| **Maria** (🌿) | Active | `~/.openclaw/workspace/` — personal assistant |
| **Steph** (📊) | Active | `~/.openclaw/workspace-steph/` — wealth advisor |
| **Bridge Skill** | Active | `advisor_memory_reader.py` — 5 read-only query types |
| **Gateway** | Active | Port 18789, v2026.4.11 |

Bridge skill query types: `observations`, `escalations`, `daily_summary`, `recommendations`, `articles`

---

## 6. Source-of-Truth Rules

| Data | Authoritative Source |
|------|---------------------|
| Portfolio positions/values | `holdings.json` (JSON) |
| Personal financial fields | `personal_situation.json` (JSON) |
| Historical snapshots | `portfolio_snapshots` (Postgres) |
| Price history | `price_cache` (Postgres) |
| Analyst consensus | `yahoo_analyst_targets_history` (Postgres) — NOT `analyst_consensus_history` |
| Action signals | `action_signals.json` (JSON, current) + `action_signals_history` (Postgres, history) |
| Advisor memory | Postgres (observations, escalations, recommendations) |
| Watchlist (user) | `watchlist.json` (JSON) + `watchlist_items` (Postgres) |
| Watchlist (analyst-curated) | `watchlist_items` (Postgres only) |
| Schemas reference | `schemas_reference_2026-04-19.md` v2.0 |

**Semantic caveat:** Finviz `recom` field is price-distance-to-target (%), NOT true consensus. Yahoo data is authoritative for analyst context.

---

## 7. Deferred / Not Yet Implemented

| Item | Status | Depends On |
|------|--------|-----------|
| Gmail/Telegram notification delivery | Deferred | notification_log table + gog integration |
| action_queue / approval_log | Deferred | notification layer |
| External model escalation (Sonnet/GPT-4o) | Deferred | local patterns + budget framework |
| AI-generated watchlist entries | Deferred | recommendation quality |
| Analyst-curated automation (from articles/news signals) | Deferred | article frequency patterns + escalation rules |
| Yahoo fundamentals history (revenue/margins) | Deferred | low priority vs analyst targets |
| Forecast engine (1Y/2Y/3Y/5Y) | Deferred | significant design work |
| Phase 11: Historical portfolio reconstruction | Deferred | 30+ days of snapshot accumulation |
| Task 10: Hardcoded numbers extraction | Investigation complete, architect decision pending |
| Steph SOUL.md auto-refresh | Deferred | nightly regeneration script |
| Escalation expiration daemon | Deferred | simple cleanup query |

---

## 8. Recommended Next Steps (ranked)

1. **Commit all work** — everything is uncommitted. Run the prepared commit commands.
2. **Notification planning** — design `notification_log` table + Gmail digest + Telegram alerts
3. **Escalation expiration** — add simple cleanup (SET status='expired' WHERE expires_at < CURRENT_DATE)
4. **Task 10 implementation** — extract hardcoded `HOLDING_YIELDS` dict to live data source (highest remaining code quality risk)
5. **Steph SOUL.md auto-refresh** — nightly script regenerates portfolio snapshot section from live data

---

## 9. Risks / Caveats

| Risk | Severity | Status |
|------|----------|--------|
| Git history contains plaintext DB password | HIGH | BFG/filter-branch before any remote push |
| Finviz `analyst_consensus_history` labels are misleading | MEDIUM | Documented; Yahoo is authoritative |
| Hardcoded `HOLDING_YIELDS` in rebalancer | MEDIUM | Task 10 audit complete, extraction pending |
| Steph SOUL.md has frozen Apr 2026 portfolio snapshot | MEDIUM | Bridge skill partially mitigates |
| `wealth/steph-wealth-advisor` deprecated skill copy | LOW | Should be deleted |
| Escalation expiration not enforced | LOW | expires_at set, no cleanup daemon |
| Yahoo API latency (50 symbols × ~2s) | LOW | Acceptable for daily pipeline |
| Backup manual path failed on ad-hoc test | MEDIUM | Automated timer mechanism exists but manual `pg_dump` via `.env` sourcing needs safer parsing. Re-verify live backup success. |

---

## 10. Deliverables Ledger

### ✅ Complete
- [x] Tier 1 (Tasks 1-4): Postgres activation + freshness gate
- [x] Tier 2 (Tasks 5-9): Database completeness + monitoring
- [x] Tier 3 Tasks 11-12: Cache invalidation + signals history
- [x] OpenClaw Phase A1: Advisor memory foundation
- [x] OpenClaw Phase A2: Escalation queue + Ollama enrichment
- [x] Steph bridge skill (5 query types)
- [x] Recommendation drafts (rule-template, article-backed)
- [x] ticker_snapshot_daily (84 tickers)
- [x] analyst_consensus_history (57 tickers, placeholder)
- [x] yahoo_analyst_targets_history (36 stocks, authoritative)
- [x] article_index (40+ articles/day, URL-deduped)
- [x] Watchlist article coverage + persistence refinement
- [x] watchlist_items + user modal + analyst-curated manual support
- [x] RVOL/gap/float scoring fix
- [x] Telegram emoji encoding fix
- [x] schemas_reference v2.0
- [x] Security cleanup (passwords removed)
- [x] 67 documentation files

### 🔶 Partial / Investigation Complete
- [ ] Task 10: Hardcoded numbers audit (investigation done, extraction pending)
- [ ] Task 13: Snapshot completeness (investigation done, migration complete)

### ⬜ Deferred
- [ ] notification_log + Gmail digest
- [ ] action_queue + approval_log
- [ ] External model escalation (Phase D)
- [ ] AI-generated watchlist entries
- [ ] Analyst-curated automation from news signals
- [ ] Yahoo fundamentals history
- [ ] Forecast engine (1Y-5Y)
- [ ] Phase 11: Historical portfolio reconstruction
- [ ] Steph SOUL.md auto-refresh
- [ ] Escalation expiration daemon

---

*Master state document created 2026-04-21.*
