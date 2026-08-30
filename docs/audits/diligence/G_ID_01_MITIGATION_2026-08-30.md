# G-ID-01 — subject_guid carriage mitigation

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR=0  
**Branch:** `fix/cio-gap-id-carriage`  
**Gap:** G-ID-01 (subject_guid / instrument identity incomplete — **carriage**, not registry)  
**Do not edit** `docs/audits/CIO_DILIGENCE_GAP_REGISTER.md` in this package.

---

## Context

P2-WS4 measured production records at **≥98.9% resolvable** against the live
identity registry (10,279 entities / 5,277 symbols). The remaining gap was
**carriage**: product rows for reentry / opportunity / watch / holdings shipped
`subject_guid` at **0%**, while `NEW_POSITION_IF` was already stamped (slice 15).

Resolvable ≠ stamped. This package stamps when the registry answers; it does
**not** mint identities and does **not** invent ticker-as-GUID.

---

## Rails

| Rail | State |
|------|-------|
| MBI | 0 |
| Identities minted | **0** |
| Registry written | **no** |
| Ticker-as-GUID | **refused** (`_is_ticker_as_guid`) |
| Broker / notify | none |
| Gap register edited | **no** |

---

## Change

### Helper — `stamp_subject_guid`

`scripts/lib/cio_subject_guid.py`:

```text
stamp_subject_guid(row, *, symbol=None, root=None, metrics=None) -> row
```

* **Hit** — `lookup_subject` returns a GUID → set `subject_guid` + identity fields;
  increment `metrics["subject_guid_hit"]`.
* **Miss** — leave `subject_guid=None`; increment `metrics["subject_guid_miss"]`.
* **Never** call `register()` / mint.
* **Never** carriage a GUID that equals the ticker (corrupt-registry rail).

`stamp_row` (multi-symbol / S3–S7 situation detector) is unchanged.

### Writers wired (highest-traffic omissions)

| Writer | Surface | What is stamped |
|--------|---------|-----------------|
| `build_reentry_book` | `reentry_book.names` | each adjudicated reentry row |
| `build_opportunity_book` | `opportunity_book.top` + `not_former` | ranked / not_former rows |
| `collect_watch_block_summary` | `watch_block_summary.top` + `ready_near_named` | watch sample rows |
| `build_action_book` (holdings thesis) | `CURRENT_HOLDINGS_THESIS` | held thesis product rows |

Each book attaches an `identity_carriage` (or
`CURRENT_HOLDINGS_IDENTITY_CARRIAGE`) hit/miss counter dict for ops visibility.

`NEW_POSITION_IF` continues to use `stamp_row` (already 100% stamped in P2-WS4).

---

## Tests

`tests/test_cio_pipeline_slice15_subject_guid.py`:

* stamp hit → registry GUID, not ticker; hit counter ++
* stamp miss → `subject_guid is None`; miss counter ++
* ticker-as-GUID refused even if registry maps ticker→ticker
* no `register()` call
* `build_reentry_book` stamps when registry resolves

---

## Out of scope (deliberate)

* Minting / registering former-table category label `HEALTH` (already in
  `NON_TICKER_SYMBOLS`; not a tradable equity).
* Mutating broker `holdings.json` lots — carriage is on **product** holdings
  thesis rows, not lot DELETE / lot rewrite.
* Gap register row status flip (explicitly forbidden for this package).

---

## Proof intent

After promote + next product build against CURRENT (registry symlink present):

* `reentry_book` / `opportunity_book` / `watch_block` stamped % should move from
  ~0% toward resolvable % (near 100% for live book symbols).
* `cio_identity_confidence_census.py --json` `stamped` component should rise;
  `minted` stays 0.
