# PHASE 191E — Hermes Profit-Protection Second-Opinion Rule

Status:      HISTORICAL
as_of:       2026-06-02T11:12:46-04:00
Measured at: efcc51365 / not measured

**Implemented:** `scripts/hermes_profit_protection_check.py` + 5 new finding types
(migration `2026_06_02_phase191_profit_protection.sql`). **Advisory only — no trade mutation.**

---

## What it does
Reads the latest TradeAI advisory per open trade from `atm_profit_protection_advisories` and writes
an independent Hermes **second opinion** as `hermes_validation_findings` rows — comparing TradeAI's
view, the stop's profit-lock state, the giveback, and the trailing policy.

## Rules → finding_type / severity
| Condition | finding_type | severity |
|---|---|---|
| Large gain, stop below entry (no lock) | `large_gain_loose_stop` | urgent |
| Large gain, stop only ~breakeven | `stop_only_breakeven_on_large_gain` | urgent |
| >50% of unrealized gain given back if stopped | `profit_giveback_too_high` | urgent |
| Large gain, no take-profit | `large_gain_no_take_profit` | urgent |
| Trailing tier met but inactive | `trailing_policy_not_triggered_but_review_needed` | warning |
| Strategy/risk metadata missing | `strategy_metadata_missing_cannot_advise` | warning |
| Quote stale | `stale_quote_blocking_protection_review` | warning |

## Hermes output per trade
agree / disagree / caution / needs_evidence · recommended operator action · evidence (TradeAI
action + P&L) · missing fields. The advisory engine also stores a compact inline `hermes_opinion`
(`agree`/`caution`/`needs_evidence`) + reason for the side-by-side panel.

## Comparison surface
Hermes weighs: TradeAI stop/protection view · its own profit-protection view (loose stop / giveback)
· `strategy_trailing_policy` v2.3 output · journal/backtest context (when present). It flags
**missing fields** (e.g. `unknown_sync` strategy, no `planned_stop`) rather than asserting false
confidence.

## Live result
- **ANY:** `large_gain_loose_stop` (urgent), `large_gain_no_take_profit` (urgent),
  `profit_giveback_too_high` (urgent), `strategy_metadata_missing_cannot_advise` (warning) →
  Hermes **caution** (concurs there is a real protection gap, but notes missing strategy metadata).
- **SNOW:** `large_gain_no_take_profit` (urgent) only — Hermes does **not** raise loose-stop/giveback
  because SNOW's stop already locks profit. Hermes **caution** (confirm vs strategy timeframe).
- Others: no findings.

This gives the operator a genuine **second opinion**, not an echo: it agrees with TradeAI on the
gap but distinguishes ANY (loose) from SNOW (protected, only TP missing).
