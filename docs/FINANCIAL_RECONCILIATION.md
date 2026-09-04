# Financial reconciliation and record-level migration

## What this exists to prevent

Two copies of `tax_lots.json` disagreed. The obvious moves were both wrong.

Taking the newer copy would have deleted the tax lots for two positions the account
actually holds — `543354104` (3,000 shares) and `SRNE` (1,000 shares) — because the
newer copy had dropped them. Taking the served copy would have lost 5,000 shares of
`SCHD` in the rollover IRA, which the newer copy had right.

Neither file was correct. The correct answer was per record, and it came from the
broker.

## The rule

> A value becomes canonical because an authority asserts it, or because it can be
> rebuilt from canonical inputs. Never because its file was written later.

`scripts/lib/financial_reconciliation.py` enforces this. It is read-only. It never
places, changes, cancels or simulates an order.

## Authorities, and what each can actually settle

| Question | Authority | Notes |
|---|---|---|
| current share quantity | broker positions, per `(symbol, account)` | one account never answers for another |
| protective stop state | broker orders, by `broker_order_id` | sell-side, non-terminal status only |
| executions and cash flows | canonical transactions | deduplicated by execution identity |
| performance, attribution | rebuild from the above | never merged, never selected |

Schwab does **not** expose tax lots. So lot *identity* is never broker-verifiable.
What is verifiable is the sum: open lots for an account and security must add up to the
position quantity the broker reports. A copy that reconciles is evidence; one that does
not is disqualified. When both reconcile and the lot composition still differs, that is
precisely the case a person must settle, and the tool says so instead of guessing.

## The seven dispositions

`BROKER_VERIFIED`, `CANONICAL_TRANSACTION_VERIFIED`, `DERIVED_REBUILT`,
`SYNTHETIC_ADVISORY_ONLY`, `DUPLICATE_WITH_PROOF`, `STALE_SUPERSEDED_WITH_PROOF`,
`UNRESOLVED_OPERATOR_REVIEW`.

Only the first five migrate unattended. `SYNTHETIC_ADVISORY_ONLY` does not: an advisory
record is not broker truth. `UNRESOLVED_OPERATOR_REVIEW` never receives a canonical
value or a canonical side — asserted by `test_no_unresolved_record_is_ever_given_a_canonical_value`.

Unproven cost basis is `BASIS_UNVERIFIED`. It is never zero and never inferred.

## Running it

```bash
# 1. capture broker truth (the only step that connects to a broker; read-only)
python3 scripts/reconcile_financial_conflicts.py --capture-authority \
    --out evidence/whole_site/BROKER_AUTHORITY_SNAPSHOT.json

# 2. reconcile record by record
python3 scripts/reconcile_financial_conflicts.py \
    --authority evidence/whole_site/BROKER_AUTHORITY_SNAPSHOT.json \
    --out evidence/whole_site/CONFLICT_LEDGER.json \
    --operator-review evidence/whole_site/OPERATOR_LOT_REVIEW.json

# 3. build the manifest with the ledger, so settled records can move
python3 scripts/migrate_state_stores.py --manifest evidence/whole_site/MIGRATION_MANIFEST.json \
    --emit-manifest --conflict-ledger evidence/whole_site/CONFLICT_LEDGER.json
```

An account whose read fails, times out, or returns empty **without proof** is refused,
not believed. An account we could not read is not an account with nothing in it, and
treating it as empty is how holdings get wiped.

## Partial safe migration

`RECORD_LEVEL_MERGE` migrates the records their authority settled and leaves the rest
exactly as the served copy has them. Unresolved records get a sidecar written beside the
store — `<store>.json.conflicts.json` — holding both originals and their hashes.

Conflicts live *beside* the store, never inside it. A reserved key added to a collection
every consumer iterates would be read as a position by any consumer that does not filter
it. A sibling file changes no schema.

`GET /api/v2/financial/conflicts` projects that state. Scope is deliberately narrow:

- the disputed record renders `UNVERIFIED`, never a number
- only the calculations that read *that record* fail closed
- every other record in the same store keeps working
- every other surface is explicitly declared unaffected

One disputed historical tax lot is not a reason to stop rendering Watch.

## Quiescence is proven, not assumed

The producer pause list is a grep heuristic and is known to miss writers that build
their paths at runtime — `health_agent_status.json` has no discoverable writer and is
rewritten every five minutes. So the gate does not depend on discovery:

```bash
python3 scripts/migrate_state_stores.py --manifest <path> --verify-quiesced 600
```

It watches the target bytes and refuses if anything moves, whatever produced it. Exit 0
is the precondition for `--apply`.

## What is still open

`tax_lots.json` / `SCHD:schwab_taxable`. Both copies sum to the broker's 406.5436 shares
but allocate it across different lots (5 vs 4). All lots are reconstructed estimates —
none are broker lots — and the producer copy holds the same share count twice on
consecutive days, which is the shape a re-run duplicate leaves but is not proof of one.
Seven of the nine lots name an account different from the one in the record key, so the
record is not internally consistent in either copy.

Deciding it means deciding cost basis, which has tax consequences. See
`evidence/whole_site/OPERATOR_LOT_REVIEW.json` for the per-lot rows.
