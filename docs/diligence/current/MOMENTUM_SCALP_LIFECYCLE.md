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

## Operator correction (2026-06-28) — true paper-trade attribution

Prior reports over-attributed momentum_scalp paper trades (e.g. "17 opened / 3 closed"). Those
figures counted **non-executed rows** (cancelled / dedup_removed proposals that never filled) as
"opened" and an **unlinked direct-label row** as confirmed. Corrected, conservative attribution
(`scripts/scalp_trade_attribution.py`) yields:

- **Confirmed momentum_scalp paper trades: 2 closed** (trade IDs 22 GCTS, 45 ANY — both executed
  with `momentum_scalp` proposal lineage + paper fills). 1 ambiguous (pt 19, unlinked) → excluded.
  19 non-executed (cancelled/dedup) rows → **not trades**.
- This is **2 of 30** required closed paper trades → validation gate **NOT met**; momentum_scalp
  remains **TESTING**. No live-readiness claim.

### Paper-path bottleneck (why the sample is tiny)

`scripts/diagnose_momentum_scalp_paper_path.py` identifies the first bottleneck:
**`approval_fails_on_stale_quote`** — momentum_scalp proposals reach ATM but the approval call
fails (gate `approve_proposal_failed`, ~148×) because the quote is stale at approval time
(~1100+ min old). **The freshness gate is working correctly — this is not a code bug, and the
fix is NOT to weaken freshness.** The gap is operational: generate a momentum_scalp proposal with
a fresh in-window quote AND approve it before the 30-minute TTL. `simulate_momentum_scalp_paper_path.py`
proves a valid fresh in-window candidate reaches `WOULD_CREATE_PAPER_TRADE`; expired / social-only /
liquidity-unknown / stale-quote / out-of-window candidates are correctly blocked or deferred.
No broker writes; operator confirmation / 2FA path unchanged.

## Route persistence, large-float scout & conversion path (2026-06-28)

- **Single trading window everywhere:** 06:00–12:00 ET. Stale "13:30 ET" prompt language removed;
  the config validator now fails on any human-facing field that references a non-window time.
- **Standard momentum_scalp is MICRO-float (≤20M).** The signal-sync fallback can no longer infer
  momentum_scalp for float up to 100M, and requires a verified catalyst.
- **Large-float social names are RETAINED and operator-visible** as `large_float_social_scout`
  (manual review) — never standard momentum_scalp, never the momentum_scalp paper fast-path.
- **Route/actionability are durable** (persisted on scan tables) and enforced end-to-end: injection
  (continuous_runner), signal creation (strategy_signal_sync), and the fast ATM runner all honour them.
- **Paper conversion path:** `momentum_scalp_fast_atm_runner.py` (paper-only, dry-run-first) converts
  a fresh in-window micro-cap proposal via the EXISTING ATM approval path before the 30-min TTL —
  closing the operational timing gap WITHOUT weakening quote-freshness, TTL, liquidity, or window
  gates. The freshness SLA report shows 27 stale-quote failures vs 0 TTL expiries and that most
  proposals are evaluated ~10 min after creation (p95 ~173 min) — a cadence problem, not a gate problem.

Operator confirmation / 2FA path unchanged and out of scope. No broker writes. LLMs advisory only.
