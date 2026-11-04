# DSN-20261104 — PositionVerdict@v1 on disk (for readers: cc4 store, cc3 surface)

FQ-095 / SPEC_ONE_POSITION_VERDICT_20261104 §1b. Written so a consumer can read the store without reading the code.

## Where

`persistent-state/data/cio/position_verdicts.jsonl` — one JSON object per line, append-only, fsynced. A defensive
reader skips blank lines and never rewrites the file. `VerdictStore(path)` takes any path; production uses the default.

## The line

```
schema                 "PositionVerdict@v1"
symbol, account        the key — both required, account is never "ALL_ACCOUNTS" (refused at write)
action                 HOLD | EXIT | REDUCE | RE_ENTRY_READY | WATCHING | WAIT | OBSERVE
state, stage           engine state/stage at the time of the verdict
confidence             0..1
trigger                why this verdict exists now ("second stop-out on SPCX since 2026-10-14")
narrative              the operator sentence
as_of                  market time the verdict describes
known_at               when the CIO wrote it (this is the transaction time)
evidence[]             {source, as_of, ref} — every input that decided it
tax_constraint         per-account: {wash_sale_window_days, window_ends, holding_period, ...}
alternatives[]         {action, rejected_because}
sequence               1,2,3… per (symbol, account)
previous_verdict_id    the prior line's id, null on the first
verdict_id             "pv1-<24 hex>", a digest of the required fields
```

## Reading

- current: the line with the highest `sequence` for that `(symbol, account)`.
- history: every line for that `(symbol, account)`, ordered by `sequence`.
- a surface with no line renders **"CIO verdict unavailable"**; it never derives a verdict itself
  (`render_for_surface` in `scripts/lib/cio_position_verdict.py` is that rule as one call).

## Not in the record

Totals, weights, concentration, cross-account aggregates. Those are read-time computations over per-account
verdicts; an aggregate account is refused at write.
