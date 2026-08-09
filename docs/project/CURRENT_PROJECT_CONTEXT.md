# Current Project Context — Trade AI v12

**Last updated:** 2026-08-06
**Author:** Cross-desk consistency audit session
**Purpose:** Canonical handoff document for future Claude Code sessions

---

## 1. Current Safety State

- **ALPACA_MODE=paper** -- only paper trading endpoint accessible
- **LLM_DISABLE_LIVE_EXECUTION=true** -- live execution blocked at code level
- **Live trading: BLOCKED** -- no path to live orders exists
- **Holdings:** ~$1,265,000 / ~22 positions (Schwab only, re-priced Aug 6)

## 2. Defense Desk -- Active, Advisory-Only

Defense Desk v10 shipped 2026-08-06 (see `docs/architecture/DEFENSE_DESK_V10.md`).

- **Sector momentum:** 11 ETFs priced nightly, 3 producers (sector/industry/recs), 5d staleness threshold
- **Stances:** 13 positions >=$10K with HOLD/TRIM-WATCH/TRIM -- deterministic factor engine
- **Rotation Plan:** 6 active rows (ARKX/XAR TRIM ladders, QCOM/CSCO rollback, BND/SPCX advised)
- **Oversight:** 5 AI seats -- Grok, GPT, Grok Pro, GPT Pro, DeepSeek Flash -- coverage 25/25 cards
- **LLM timeline:** Shows last-run + next-scheduled per seat
- **DeepSeek:** Full oversight pipeline functional (primary seat, Flash ready)
- **Cash alternatives:** 17 vehicles ranked, advisory only

## 3. Cross-Desk Consistency Audit -- Complete 2026-08-06

Full audit across all four desk systems using **data broker** as canonical source of truth:

- **0 hard contradictions** between desks
- **4 soft conflicts**: SCHD, JEPI, ARKX, XAR flagged TRIM by defense -- legitimate (sector weakness, factor fires, ladder triggers)
- **Stop re-entry watches:** `build_reentry_watch()` now accepts `thesis_map` for data broker enrichment
- **Health agent gap:** `collect_cross_desk_consistency()` collector designed (pending implementation) to monitor contradictions and route through the escalation queue to LLM for repair

## 4. Portfolio Membership Sync -- Working

`sync_portfolio_watchlist_membership.py` called after every holdings write. All 25 held symbols have `in_portfolio=True` via `watchlist_symbol_master` view. `source='portfolio'` rows created on import, removed on sale. Bulk API pagination (200 cap) is the only visibility gap -- individual symbol lookups return correct data.

## 5. Re-Entry Desk

- **Decision desk:** 108 rows, fully deterministic via data broker (no LLM in path)
- **Stop re-entry:** 77 watches (CSWC, NOC, PFLT, RTX active for held symbols)
- **Entry plans:** QCOM and CSCO have plans with zone/stops/targets via `watchlist_entry_planner.py`
- **Thesis fix:** `stop_out_reentry_watch.build_reentry_watch(thesis_map=...)` wired, pending API deployment

## 6. Recent Fixes (this session)

| Fix | Status |
|-----|--------|
| DeepSeek `OUTPUT_TRUNCATED` -- 3-layer repair | Deployed |
| Sector staleness XLRE/XLC -- price scope + engine fix | Deployed |
| All "deep sea" renamed to "deepseek" (files, API, UI) | Deployed |
| MetricStrip 4 tooltips | Deployed |
| SectorLeadersCard 5 column tooltips | Deployed |
| CashAlternatives sizing policy column | Deployed |
| LLM timeline timestamps | Deployed |
| `build_reentry_watch` thesis_map parameter | Module tested, pending API wire |
| Staleness display shows actual days | Deployed |
| Hedging radar path fix in data rhythm | Deployed |

## 7. Do-Not-Do List

- No active ATM without operator command
- No new orders or trades
- No proposal approvals
- No live trading
- No strategy activation changes
- No YAML threshold changes
- No Finviz criteria changes
- No .env modifications

## 8. Deployment Mechanism

```bash
# Build frontend
cd apps/command-center-v3 && npm run build

# Create release
bash scripts/make_release.sh --label "<label>"

# Update systemd drop-in and restart
# ~/.config/systemd/user/portfolio-server.service.d/20-exact-sha-release.conf
systemctl --user daemon-reload
systemctl --user restart portfolio-server
```

Current release: `bc779f4a-sector-names-tooltips-20260806-111529`

## 9. Documentation

- `docs/architecture/DEFENSE_DESK_V10.md` -- v10 cross-desk audit (this session)
- `docs/architecture/DEFENSE_DESK_V9.md` -- v9 adjudication layer (Jul 18)
- `docs/CHANGELOG.md` -- through 2026-08-06
- `docs/sessions/` -- past session summaries
- `docs/design/watchlist-intelligence-v3/DATA_BROKER_WATCH_CONSUMERS.md` -- data broker consumer docs
- `docs/ui/REENTRY_DECISION_SCORECARD_v1.md` -- re-entry scorecard spec
