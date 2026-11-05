# Protective put / collar advisory (D32 §5) — FQ-142

> Advisory only. The system never places, sizes, stops or cancels an order. Every suggestion says so in
> its own payload (`placed_by_system: false`), and the module has no import path to a broker, an order
> surface or a CIO behavior write (`scripts/lib/cio_instrument_record.BehaviorWriteRefused` is intact).

## What it does

For a **single-stock** position at or above a configured share of the book, with an earnings or known
event inside the configured window, it suggests:

- a **protective put** — the strike it would buy (the floor), the expiry, the contracts, and the cost;
- a **collar** — when a call is quotable, the cap strike, the call credit and the net cost (which can be a
  credit).

The suggestion exists so the operator can decide. Nothing is placed, and the module cannot place it.

## Config — `config/protective_put_advisory.json`

| key | default | meaning |
|---|---|---|
| `min_position_pct_of_book` | `2.0` | at or above this share of the book a position is worth hedging |
| `event_window_days_before` / `_after` | `10` / `2` | the same 10-before/2-after shape the earnings vertical registry uses |
| `put_floor_pct_below_spot` | `10.0` | floor target when the position carries no broker stop |
| `collar_cap_pct_above_spot` | `15.0` | cap target for the collar's short call |
| `estimated_cost_pct_of_position` | `2.5` | the **labeled estimate** used when no option chain is supplied |
| `min_days_to_expiry` / `max_days_to_expiry` | `7` / `60` | the expiries it will consider |

Config, not code: the operator can change the threshold or the window without a source change.

## Floor and cost, stated honestly

- **Floor basis.** A position that carries a broker stop targets the stop — it is already defended there.
  Otherwise the strike targets spot minus the configured percent.
- **Cost.** With a chain, the premium is the quoted ask and `cost_is_estimate` is `false`. Without one, the
  cost is a labeled estimate (a configured percent of the position value), `cost_is_estimate` is `true`, and
  the payload carries a `cost_basis` sentence saying it is not a quoted premium. A floor price from a quote
  is reported only when a real strike was chosen.
- **Cover.** One contract covers 100 shares; `cover` says `full`, `partial` or `over` rather than implying a
  perfect hedge.

## How to run it

```
.venv/bin/python scripts/protective_put_advisory.py --holdings /path/to/a/holdings-document.json
.venv/bin/python scripts/protective_put_advisory.py --holdings H --events events.json --chains chains.json --json
```

`--events` is `{symbol: {event_date, days_to_event}}`; `--chains` is the options snapshot shape
`options_advisory_candidates` consumes. With neither, every position is examined and skipped with a reason.

## Integration point (next step, not this change)

The projection is a pure function over data the caller supplies. The natural consumer is the same
read-only desk projection that feeds the Home/Risk surfaces: read `symbol_profiles.next_earnings_date`
(the earnings event model already resolves it), the holdings snapshot and, when available, the read-only
chain snapshot, then render the suggestions on the after-hours guard page. The page change needs the
operator's mockup approval first, per the SPEC's build note.

## Acceptance (what the tests pin)

`tests/test_protective_put_advisory.py` — 16 tests, registered by
`config/ci_gates/protective_put_advisory_20261105.json`:

- the size threshold is inclusive at exactly the configured percent, and one dollar below it is skipped;
- cash rows and option legs are never covered;
- no event, or an event outside the window, is skipped with a named reason (the window is inclusive at
  both ends, and negative days mean after the event);
- a broker stop sets the floor basis; otherwise the configured distance does;
- a quoted chain gives a real premium, strike and expiry; without one the cost is a labeled estimate;
- a collar appears only when a call is quotable, and a net credit is reported as such;
- a source AST sweep proves no broker/writer import and no order-shaped call;
- `BehaviorWriteRefused` still raises for `size_usd`/`stop` on the CIO record.
