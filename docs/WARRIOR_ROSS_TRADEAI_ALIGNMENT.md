# Warrior / Ross ↔ TradeAI Alignment

> **Audience:** operator + engineers tuning the momentum-scalp scanner for Ross-style awareness.
> **Goal:** surface Ross-catalog names in TradeAI without auto-GOing them; measure weekly recall.

## Overview

The Trade AI scanner (`scripts/trade_ai_orchestrator.py`, `scripts/continuous_runner.py`) produces
GO / WAIT / MANUAL_REVIEW / NO-GO decisions. Ross/Warrior alignment adds **awareness lanes** for names
the catalog mentions but the scalp critic will not auto-GO (squeeze, high-RVOL runner, micro-float,
low-price spike, top gainer, social scout).

**Design law:** awareness lanes are **Entry Desk only** — never validation-fast-path, never ATM auto-GO.

## Awareness lanes (backend)

| Lane | Module | Trigger (summary) | UI pill |
|------|--------|-------------------|---------|
| Squeeze | `scripts/lib/squeeze_manual_review.py` | Reverse-split squeeze pattern | Cyan SQUEEZE |
| High-RVOL runner | `scripts/lib/high_rvol_manual_review.py` | WAIT + extreme RVOL | Orange RUNNER |
| Micro-float | `scripts/lib/micro_float_manual_review.py` | Low float + RVOL | Purple MICRO |
| Low-price | `scripts/lib/low_price_manual_review.py` | Sub-$2 + >30% move | Yellow LOW |
| Top gainer | `scripts/lib/top_gainer_awareness.py` | Finviz prime-setup leaders | Orange TOP |
| Social scout | existing scout pillars | ≥2/5 social pillars | Violet SCOUT |
| Catalyst exception | `scripts/lib/catalyst_exception.py` | Momentum runner, catalyst optional, grade cap B | — |

Tags attach at API read time in `_compute_trade_ai()` (`scripts/api_v2.py`) and persist via
`scripts/lib/scan_persist_extra.py` + migration `scripts/migrate_awareness_fields.py`.

## Universe coverage

| Inject | Module |
|--------|--------|
| Finviz top-30 gainers | `scripts/lib/universe_coverage.py` |
| Ross catalog aliases (VRX→VRAX, etc.) | `scripts/lib/ticker_alias.py` |
| Ross daily catalog symbols | `scripts/lib/ross_catalog_universe.py` |

## Audit pipeline

| Script | Purpose |
|--------|---------|
| `scripts/warrior_tradeai_audit.py` | YTD / range audit vs Ross catalog |
| `scripts/warrior_weekly_audit_cron.py` | 7-day pilot; writes CSV + panel JSON |
| `scripts/warrior_daily_catalog_extractor.py` | Hermes + regex catalog rows |
| `scripts/lib/ross_catalog_hermes.py` | Hermes transcript catalog |
| `scripts/lib/ross_catalog_cross_video.py` | Cross-video symbol inference |
| `scripts/lib/finviz_snapshot.py` | Nearest Finviz snapshot for historical audit |
| `scripts/backfill_scan_awareness.py` | Backfill DB awareness columns (no full re-score) |

**API:** `GET /api/v2/warrior-audit/latest` — panel data for Command Center.

**Cron (Mon 8:30 AM ET):**

```cron
30 13 * * 1 /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/linux_port/launchers/run_warrior_weekly_audit.sh
```

Proposal line also in `crontab_warrior_audit_proposal.txt`. Telegram optional via
`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.

**Outputs:** `data/audit/warrior_weekly_YYYY-MM-DD.csv`, `data/audit/warrior_weekly_latest.json`.

## Command Center v3 — Trade AI tab

**File:** `apps/command-center-v3/src/pages/TradingHub.tsx`

### Filters (default: Actionable)

| Tab | Rows |
|-----|------|
| **Actionable** | GO + WAIT + MANUAL_REVIEW |
| GO | Auto-trade candidates |
| WAIT | Near-miss |
| Manual | Squeeze · Runner · Micro · Low |
| Social Scouts | Partial social setups |

Hides ~1500 NO-GO universe noise from the default table. Full universe remains in KPI strip + copy box.

### Sort

Dropdown: **Awareness rank** (default), Score, RVOL, Change %, Symbol A–Z. Table top-30 and GO/WAIT/Universe
copy lists share the same sort key.

### Country column

`apps/command-center-v3/src/components/CountryFlag.tsx` — PNG flags via flagcdn (Linux often renders
emoji flags as two-letter codes). Tooltip shows English country name. ADR-aware resolution in
`src/lib/country.ts` (PBR→Brazil, etc.). Used on Trade AI scanner + watchlist cards.

### Ross Alignment Audit strip

Rendered below the scanner when `/api/v2/warrior-audit/latest` is populated (recall %, sym-days, gap breakdown).

## Operator workflow

1. Open **Trading → Trade AI** — default **Actionable** view.
2. Review GO/WAIT; send Manual-lane names to **Entry Desk** (never auto-route).
3. Use **Sort → RVOL** or **Change %** for momentum triage.
4. Copy GO/WAIT lists into Thinkorswim (sorted, not raw DB order).
5. Check **Ross Alignment Audit** weekly — target is awareness recall, not blanket auto-GO.

## Backfill

```bash
python3 scripts/backfill_scan_awareness.py --since 2026-07-06 --until 2026-07-10
```

## Tests

`tests/test_*` for squeeze, high_rvol, micro_float, low_price, catalyst_exception, universe_coverage,
ticker_alias, finviz_snapshot, top_gainer_awareness, ross_catalog_*, warrior_tradeai_audit.