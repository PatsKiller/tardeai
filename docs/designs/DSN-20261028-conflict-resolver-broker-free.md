---
id: DSN-20261028-conflict-resolver-broker-free
title: conflict-resolver broker-free re-route (break the positions_sync -> schwab_transport import chain)
status: PROPOSED
approval: awaiting operator / W10 owner (touches the data-broker read path §7A and, optionally, the positions single writer)
source: docs/governance/OPEN_ITEMS.md OI-135
phases:
  - id: DSN-20261028-conflict-resolver-broker-free-P1
    title: Break the transitive broker reach
    status: PROPOSED
    tasks:
      - id: DSN-20261028-conflict-resolver-broker-free-P1-T1
        title: Move the broker-free positions-freshness contract into lib/portfolio_positions.py and repoint watch_domains
        status: PROPOSED
        areas: [scripts/lib/portfolio_positions.py, scripts/lib/data_broker/watch_domains.py]
---

# conflict-resolver broker-free re-route

## 0 · The finding (OI-135)

`tests/test_lane_transitive_capabilities_20261015.py` refuses the conflict-resolver lane because its import
closure reaches `broker_module` **and** `order_placement`:

```
scripts/conflict_resolver.py
  -> scripts/lib/data_broker/watch_intelligence.py   (compose_universe)
  -> scripts/lib/data_broker/watch_domains.py        (_store_freshness, line 321: `import positions_sync as ps`)
  -> scripts/positions_sync.py                       (line 97: `import schwab_transport as st`, lazy)
  -> scripts/schwab_transport.py                     (broker)
```

This is the OI-072 class — token-clean on the surface, reaches broker code transitively. It is a real rail,
not a cosmetic test, so the admission must not ship red.

## 1 · What the chain actually is (measured)

The reach is **import-only and accidental**. The three functions `watch_domains` pulls from `positions_sync`
are pure and broker-free:

- `positions_sync.load_sync_config()` — reads `config/portfolio_positions.yaml` `positions_sync:` over `_SYNC_DEFAULTS`. No broker.
- `positions_sync.market_open_now()` — `zoneinfo` + `datetime` only. No broker.
- `positions_sync.freshness()` — arithmetic over `last_complete`, `cfg`, `now`. No broker.

`positions_sync.py` imports `schwab_transport` only at line 97 (`import schwab_transport as st`, inside the
actual sync path). Importing the module to call a pure helper still registers the whole module's lazy closure,
which is what the audit correctly flags.

## 2 · The recommended fix (minimal, one source of truth)

Move the broker-free freshness contract into `scripts/lib/portfolio_positions.py` — the already-approved,
already-broker-free positions accessor (§7A single read path) — and repoint `watch_domains._store_freshness`
to call it there:

1. Add to `lib/portfolio_positions.py`: `positions_sync_defaults`, `load_sync_config`, `market_open_now`,
   `freshness` (copied byte-for-byte from `positions_sync.py`; pure functions, no broker import).
2. Change `watch_domains._store_freshness` line 321 from `import positions_sync as ps` to
   `from lib import portfolio_positions as pp; pp.freshness(...)`.
3. Optionally (separate decision): make `positions_sync.py` import these helpers from `lib/portfolio_positions`
   instead of keeping a duplicate — this touches the single writer, so it is the W10/§7A owner's call.

Result: the conflict-resolver import closure no longer reaches `positions_sync` → `schwab_transport`, and
`test_lane_transitive_capabilities` passes without a baseline exception.

## 3 · The alternative (baseline justification, operator-only)

The audit message itself offers: *"justify in the baseline AND the frozen set here."* If the reach is judged
acceptable as import-only (the dry run never calls a broker function), record it in
`config/n8n_lane_capability_baseline.json` + the frozen set in the test, with the operator's approval (§0 rule 2
/ §7A — the operator decides a broker-adjacent lane's reach). This is faster but weaker than removing the reach.

## 4 · Ownership and gates

- `lib/portfolio_positions.py` and `watch_domains.py` are the §7A data-broker read path — a single-writer/single-
  read-path change, reviewed, not unilaterally shipped.
- `positions_sync.py` is the **single positions writer** (§7A) — editing it is a §0-rule-2-adjacent decision;
  the recommended fix does **not** require it.
- The conflict-resolver admission (PR #2266) stays held until this re-route (or the operator baseline approval)
  lands and the lane passes the transitive-capability audit.

## 5 · What does not change

No broker, order, stop, sizing, secret or egress path. The re-route moves a pure helper; the broker reach is
removed, not weakened. `MBI_BEHAVIOR = 0`.
