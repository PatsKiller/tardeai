# Protective put / collar unit economics (D32 section 5) — FQ-142

The advisory returns **per-contract research economics**. It never selects a contract quantity,
places an order, writes a position or calls a broker. The operator alone decides any coverage.

For a known long single-stock holding above the configured share of the snapshot, with a known event
inside the configured window, the projection reports a put strike, expiry and premium when usable
quotes exist. A standard contract references 100 shares. These are units of an option quote, not
an order-size recommendation. `ProtectivePutAdvisory@v2` replaces the unsafe inferred-size contract.

- `cost_per_contract_usd` is the quoted ask times the standard multiplier.
- `floor_per_covered_share_after_premium` is the strike less premium **per covered share**, not a
  floor under all held shares. `position_floor_after_cost` is always null and `coverage_status`
  is `not_selected`. No aggregate cost, contract count or position-wide minimum is inferred.
- A 250-share or 140-share holding still receives unit economics without selecting two contracts or
  one contract, or implying protection of the remainder. Full coverage also requires an operator decision.
- A collar unit is shown only where at least 100 owned shares could cover a standard short call.
  A 40-share holding receives no collar. Each collar unit states its 100-owned-share requirement;
  it does not select any short-call quantity.
- A quoted expiry must reach the known event. A supplied snapshot without an event-reaching expiry
  or usable put returns `no_expiry_covers_event` or `no_usable_put_quote`; it is never described as
  an absent chain.
- Without a chain, the configured percentage gives a labeled estimate for 100 reference shares.
  No quoted strike, expiry or covered-share floor is asserted for this estimate.
- Unknown/malformed quantity is `position_quantity_unknown`; it never becomes an assumed long.

## Configuration and unavailable inputs

The documented default is repository `config/protective_put_advisory.json`. Its existing operator
policy values are unchanged. Missing, invalid, non-object or unusable configuration raises an explicit
error; it never silently re-enables the advisory. The configured disable switch is honored.

The threshold, event window, floor/cap distances, DTE bounds and premium/distance limits remain in
that file. The premium percentage gate is applied to the 100-reference-share unit value, matching
the per-contract price basis; no position-sized premium is invented. A distant strike remains labeled
with its target and warning. Premium at or above the strike withholds the covered-share floor.

The CLI uses `lib.portfolio_positions.read_store_document`, the sanctioned reader that preserves
absent, empty, unparseable and non-object states. Damaged snapshots, invalid position lists and invalid
configuration return exit 2 and JSON `status: unavailable` (or an error on stderr). A genuine empty
position list remains a successful zero-row observation.

## Offline snapshot usage

```
python scripts/protective_put_advisory.py --holdings H --events E --chains C --json
```

`H` contains `holdings` (or `positions`) as a list of objects. `E` maps symbols to event objects;
`C` maps symbols to chain objects with expirations/strikes. `--book-value` can supply a whole-book
snapshot total. There is no quantity-selection CLI option, paid call, notification or scheduler.

The registered synthetic tests exercise the actual default loader, module and CLI: disabled/damaged
config, missing/malformed quantities, event-covering expiry, quote availability, 40-share collar
suppression, unit costs, partial-holding uncertainty, damaged versus valid empty stores, and text/JSON
output. A causal mutation proves the configured threshold boundary test can fail.

Live page integration remains a separate task requiring the mockup approval named in the specification.
