# InstrumentRecord@v1

`InstrumentRecord@v1` is the normalized operator projection for one instrument.
It is built from the existing `watchlist_items` row and linked canonical
identity, research, specialist, operator-turn, and lesson evidence. It is not
a second business-logic store.

The adapter lives in `scripts/lib/instrument_record.py` and is registered as
`instrument.records` in `CanonicalStoreRegistry@v1` (`POSTGRES`, table
`watchlist_items`). Ticker text is display-only; identity joins require a
canonical security or issuer identifier.

## Current implementation

The adapter normalizes thesis, Command Center narrative, event/price markers,
research and artifact IDs, operator turns, lessons, analyst/earnings timing,
research eligibility, notification priority, workflow identity, and data
quality. Missing identity or lineage is explicitly marked `LEGACY` or partial;
values are never inferred from ticker text.

## Remaining integration work

Existing writers still persist their evidence in their domain stores. Each
writer must call the adapter with the same `workflow_id`, and Command Center
sections must consume the normalized projection rather than independent table
queries. Notification threshold state and operator ack/defer updates also need
to be persisted against the same record. These are additive follow-up tasks;
historical evidence remains untouched.
