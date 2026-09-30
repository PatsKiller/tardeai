# CIO Portfolio-Aware Entry Alerts

Status:      IMPLEMENTED LOCALLY — pending merge and governed deployment
as_of:       2026-09-30
Measured at: `a7ec067d6` plus documentation follow-up

## Purpose

BUY_READY and ENTRY_NEAR alerts are portfolio decisions, not generic ticker
broadcasts. When the symbol is already held, the alert answers the operator's
actual question:

> Should I add here, wait for a better entry, or hold the existing position?

The feature is advisory only. It does not size a position, create an order,
request 2FA, or write to a broker.

## Surfaces

The same portfolio-aware facts are projected into:

- the CIO entry Telegram alert;
- the CIO Desk packet;
- Command Center watchlist decision cards;
- the Re-Entry page's Entry Alerts lane; and
- saved `BuyReadyInstitutionalPacket@v2` projections.

## Telegram CIO decision-card contract

CIO entry alerts, watchlist entry alerts, and pending CIO-review follow-ups use
the shared `cio_entry_alert()` layout in `scripts/lib/telegram_rich.py` when
`TELEGRAM_RICH_ALERTS` is enabled. The visible card is intentionally compact:

- CIO view and next action;
- current price, entry zone, stop, target, and current/ideal R:R;
- a stop-to-target price strip and deterministic display-only risk/reward gauges;
- held/new-position context, portfolio facts when available, and `Sizing: not provided`;
- catalyst, options status, CIO verdict, and quick-link buttons.

Thesis detail, opposing evidence, option rejection reasons, provenance, and the
advisory disclaimer are placed in Telegram's expandable evidence block. Emoji
markers provide the stoplight channel because Telegram does not support text
colors. Missing values render as `—` or `unavailable`; the card never invents
probability, expected value, liquidity, or sizing.

The existing `CIO entry —` routing sentinel, stance gate, primary-symbol scoping,
chart preview, and plain-text fallback remain intact. The CIO-only transport uses
the same rendered HTML card with its existing authorization and deduplication
controls.

## Decision language

| Situation | Action label |
|---|---|
| Held and inside a valid entry zone | `ADD_DECISION_REQUIRED` |
| Held and waiting above the preferred zone | `WAIT_FOR_ENTRY_ZONE` |
| Held with a deterministic hard block | `HOLD_EXISTING_POSITION` |
| Not held and inside a valid zone | `REVIEW_NEW_POSITION` |

The opening line for a held alert retains the `CIO entry —` routing sentinel,
then leads with `already owned: add decision required`. The UI card uses
`MANAGE POSITION` and makes the add/wait/hold state primary.

## Required displayed evidence

The alert and packet show, when the source provides it:

- shares held, position value, percentage of total portfolio, percentage of
  invested assets, and the IPS single-name limit;
- current price, preferred entry zone, stop, target, distance from the zone,
  R:R at the ideal entry, and R:R at the current price;
- catalyst, or explicit `unavailable` when no catalyst is present;
- the first deterministic hard block, or `no hard block recorded`;
- stock play and options play, including honest rejection of unsuitable
  structures;
- time horizon or DTE when available; and
- CIO review status. The status is `UNREVIEWED` unless a review ID exists.

Shares and portfolio weight are observational context only; they never imply a
recommended quantity. Missing data stays missing. A deterministic house-rule verdict is not a CIO
review and cannot populate the CIO commentary field.

## Source lineage

| Fact | Source |
|---|---|
| held flag and entry state | `cio_entry_state_runner` / `cio_entry_state.evaluate` |
| shares and concentration facts | `buy_ready_portfolio_facts` |
| stock versus options economics | `cio_options_fluency.comparative_equity_vs_options` |
| options qualification and rejection | `buy_ready_options_alternatives` and desk cache |
| CIO review status | `buy_ready_cio_review` result plus review ID |
| Command Center entry-alert projection | `buy_ready_packets_index` |

## Failure and safety behavior

- A stale quote, invalid plan, insufficient R:R, earnings block, quality block,
  wash-sale block, or stop violation remains a hard block.
- The first hard block is displayed; no model-generated substitute is used.
- Options Greeks, IV, probability, expected value, liquidity, and spread cost
  are displayed only when supplied by the validated chain or desk source.
- The feature never converts held shares into a new position recommendation.
- The feature never supplies a quantity, target weight, or execution command.

## Validation

The implementation was validated with:

- 78 focused Python tests covering entry rendering, institutional packets, and
  the Entry Alerts index;
- Ruff on changed Python files;
- TypeScript compilation for Command Center v3;
- `git diff --check`;
- repository secret scan; and
- local acceptance with 17/17 CI-equivalent release checks passing.

The implementation commit is `a7ec067d6`. This documentation follow-up is a
separate commit and remains pending the normal PR, merge, and deployment gates.
