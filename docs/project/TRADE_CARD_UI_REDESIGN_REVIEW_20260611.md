# Trade Card Redesign → Actionable Position Decision Cards (review)

**Date:** 2026-06-11 · **Type:** Frontend + read-only API enrichment · **Scope:** Open Trades cards only.
**Read-only proof:** no Schwab/Alpaca writes, no stop/order paths, no GO-WAIT/screener/ATM/strategy-YAML
changes; all card actions are review/open/drill. `validate_schwab_no_writes.py` = **12/12**.

## Before → after
| | Before | After |
|---|---|---|
| Decision | a one-line `action_state.label` | **Decision banner** (most prominent): operator_decision + reason + next review |
| Priority | sort by alert/watch/ok | `operator_priority` critical/high/medium/low + colored left border + sort |
| "Large gain unprotected" | a chip | a full **Needs protection review** decision state |
| Basis | source string only | `basis_quality` (broker / tax_grade / owner_provided / unknown) chip |
| Stale data | small chip | **"Data stale — refresh first"** decision + red border on high-value |
| Strategy | name only | name **+ WHY** (strategy `purpose`) — *operator-requested* |
| Sector | "unavailable" for many | DB + fallback map (AGNC=Real Estate, NUVL=Healthcare, …) |
| Filters | 7 dropdowns | + 10 quick action-item filters (Needs protection, High priority, Watchlist/directive, Data stale, Basis issue, News fresh, Trailing candidate, Large gain, Underperforming) |
| Sort | 6 options | 11 (priority default, risk flags, unprotected gain, news freshness, market value, today move, watchlist/directive, …) |

## Part A — API enrichment (read-only, derived)
`scripts/open_trades_intelligence.py` now emits per position: `operator_priority, operator_decision,
decision_reason, risk_flags, opportunity_flags, data_freshness, news_freshness, protection_state,
basis_quality, watchlist_state, directive_state, last_hermes_review_at, latest_news_age_hours,
primary_next_review, recommended_manual_actions, strategy_rationale`. All derived from already-computed
signals — no source-of-truth math changed. Strategy "why" comes from each strategy's config `purpose:`.

## Part B/C — components + filters
`PositionDecisionCard.tsx` (6 zones: header identity+priority, decision banner, economics, evidence chips incl.
strategy WHY + sector, catalyst/news with stale labeling, manual-action buttons). `OpenTradesIntelligence.tsx`
refactored to use it + the new quick filters and sorts; default sort = priority.

## Part E — screenshots (docs/ui_review/trade_card_redesign_20260611/)
| Shot | View |
|---|---|
| 01 | Open Trades, default **priority** sort — decision banners + colored borders |
| 02 | **Needs-protection** quick filter |
| 03 | Expanded card — news/catalyst + sector detail |
| 04 | **Mobile width (430px)** — single-column, no horizontal scroll |
| 05 | Watchlist (Active+Researched) |
**Console errors: 0.**

## Part D — AXTI watchlist check (honest finding)
AXTI is present in `watchlist_items` as **`researched` ×1 (no duplicate)**. However the WatchlistHub endpoint
`/api/v2/watchlist/items` returns a **200-item cap (all 'researched')** and AXTI ranks below the cap by the
hermes sort, so it is not currently rendered. **This is a pre-existing watchlist display-limit issue — the
card redesign does not touch the watchlist** and did not cause it. Recommended follow-up: pin
directive/promoted symbols (incl. AXTI) above the display cap, or raise/paginate the cap. No duplicate
rendering observed.

## Acceptance
Materially more actionable ✓ · each card states next review ✓ · large-gain-unprotected = decision state ✓ ·
news age + stale labeling ✓ · basis quality visible ✓ · stale data obvious ✓ · Journal execution-quality
untouched ✓ · no trading/broker-write paths ✓ · validator 12/12 ✓. **Open item:** AXTI watchlist-cap (above).
