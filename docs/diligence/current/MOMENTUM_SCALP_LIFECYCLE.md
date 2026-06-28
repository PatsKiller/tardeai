# Momentum Scalp Lifecycle

_Source of truth for the intraday momentum_scalp lifecycle. Generated/validated by
`scripts/strategy_config_validator.py momentum_scalp` and the P0 tests below._

## Status

**Momentum Scalp is TESTING until its validation gate is met** — paper only, taxable account
only. No social signal can bypass the deterministic risk gates. No LLM can unlock execution.
The existing operator confirmation / 2FA path is unchanged and out of scope.

## Single source of truth (P0-3)

`intraday_execution` in `config/strategies/momentum_scalp.yaml` is authoritative for the
trading window, proposal TTL, fast-path account/mode, and max price drift. All other blocks
are aligned to it; `scripts/strategy_config_validator.py` fails the build on any drift.

| Parameter | Authoritative value | Source field |
|-----------|--------------------|--------------|
| Max float | 20M (preferred 10M) | `screen_filters.max_float_m` ↔ `entry_criteria.FLOAT_LOW` (both 20) |
| Trading window | 06:00–12:00 ET | `intraday_execution.trading_window_et` ↔ `entry_criteria.ENTRY_WINDOW` (720 min = 12:00) |
| Proposal TTL | **30 minutes** | `intraday_execution.proposal_ttl_minutes` (lifecycle declares `source_of_truth`) |
| Fast-path account | alpaca_paper | `intraday_execution.fast_path_account` |
| Max price drift | 3.0% | `intraday_execution.max_price_drift_pct` |

The legacy `lifecycle.proposal_expiry_hours: 4` (which contradicted the 30-minute TTL) was
removed and replaced with `proposal_expiry_minutes: 30` + `source_of_truth`.

## Proposal expiry enforcement (P0-1)

`scripts/atm_auto_approver.py` consults `resolve_atm_expiry()` **before any approval
decision**. For intraday strategies the authoritative expiry is `created_at + 30min`
(via `proposal_lifecycle.get_expiry_datetime`, honoring an earlier stored `expires_at`):

* `expires_at <= now` (or age ≥ TTL) → `status = EXPIRED`, `lifecycle_status =
  EXPIRED_INTRADAY`, `atm_expired_at = NOW()`, `atm_expiry_reason = intraday_ttl_expired`,
  with a `lifecycle_message` citing the age and TTL; a structured ATM decision logs the gate
  `intraday_ttl_expired`. **ATM cannot approve an expired intraday proposal.**
* The old 4-hour rule is a fallback only for non-intraday / legacy proposals without
  `expires_at`.
* Fail-safe: an intraday proposal whose freshness cannot be established blocks (never
  approves).

Covered by `tests/test_momentum_scalp_expiry_enforced.py`.

## Liquidity-unknown defers (P0-4)

`scripts/auto_proposal_generator.py::_liquidity_prescreen` is **fail-closed for intraday**.
A quote/provider error, a missing quote, or a stale quote returns
`DEFER_LIQUIDITY_UNKNOWN` and **no auto proposal is created**. Outside regular hours it may
proceed only with a fresh extended-hours quote. Non-intraday strategies keep prior fail-open
behavior. `force=True` may bypass only in dry-run / manual / operator mode and is always
logged — never a silent proceed. No broker write behavior changes.

Covered by `tests/test_momentum_scalp_liquidity_unknown.py`.

## Validation gate

```
min_closed_paper_trades: 30   min_win_rate: 0.50
min_profit_factor: 1.30       min_calendar_months: 6   human_approval_required: true
```

The funnel report (`SCALP_LIFECYCLE_FUNNEL.md`) and maturity score
(`SCALP_LIFECYCLE_MATURITY.md`) report whether this gate is met. Until it is, momentum_scalp
stays TESTING and the combined lifecycle maturity is capped at 4.4.
