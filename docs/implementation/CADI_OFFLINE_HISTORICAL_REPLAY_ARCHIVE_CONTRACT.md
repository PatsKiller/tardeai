# Offline CADI historical replay archive contract

Status: SOURCE_ONLY — offline adapter implemented; production EV readiness unchanged
Owner: platform / Cross-Asset Decision Intelligence
as_of: 2026-10-09
Measured at: base `bbff99766cd80ea630543abfaa639eb41eae5eb9`, dedicated replay worktree
Authority: READ_ONLY_ADVISORY; no financial action, model, provider, scheduler or sender authority

The historical CLI now reads explicit archives and calls the existing pure
`scripts/lib/cross_asset_decision.py` evaluator. Before this correction, merely
creating `signals.jsonl` and `prices.jsonl` produced `AVAILABLE` with zero
signals evaluated. The archive formats were undefined in the five CADI plans.
This document defines an offline input adapter. It creates no production store,
writer, data-source registration, archive export, scheduler or live import.

## Inputs

The caller supplies `--archive-dir`. Each nonblank JSONL line must be an object
with the declared schema. Invalid JSON, nonfinite numbers, unknown schemas,
unconfirmed identities and missing/ambiguous timestamps return `INVALID_DATA`.
A malformed archive is refused as a whole; partial processing cannot claim a
successful score comparison. Missing archives remain `INSUFFICIENT_DATA`.

| File | Contract | Required fields |
|---|---|---|
| `signals.jsonl` | `CrossAssetHistoricalReplaySignal@v1` | `event`, `identity`; optional `position` |
| `prices.jsonl` | `CrossAssetHistoricalPrice@v1` | `symbol`, `security_guid`, `as_of`, positive finite spot `price`, `source_ref` |
| `expression_facts.jsonl` | `CrossAssetHistoricalExpressionFacts@v1` | `event_id`, `symbol`, `security_guid`, `as_of`, `source_ref`, `facts_by_structure` |

`event` is the existing `CrossAssetDecisionEvent@v1`: `event_id`, `symbol`,
supported `signal`, `source`, `observed_at` and object `payload`. The supported
signal/candidate matrix comes from the existing evaluator. `identity` uses its
existing vocabulary: the symbol must match the event; `security_guid` must be
present; `identity_status` must be `CONFIRMED`; `as_of` must be known no later
than the signal. Optional `position` uses existing `held`/`shares` fields and
requires its own `as_of` no later than the signal. This is a historical snapshot,
not an instruction to size a position.

All timestamps are ISO instants with seconds and an explicit `Z` or UTC offset.
The CLI refuses naive timestamps. `facts_by_structure` uses the evaluator's
existing fields, including `score`, `expected_return`, `capital_required`,
`maximum_risk`, liquidity/quote/earnings/position blockers and review state.
Each individual fact must have an aware `as_of` no later than its snapshot.
Numeric facts must be finite numbers; booleans cannot masquerade as scores.
No score, option price, IV, fill, return or risk threshold is invented by replay.

`prices.jsonl` contains actual archived spot prices. It is not an alias for
scores, expression facts or option contracts. Summary-only chain snapshots and
current prices do not substitute for timestamped archived option economics.
The `option_chains` directory is reported for compatibility, but its existence
is never proof of a comparison and its contents are not priced by this adapter.

## Selection and evaluation

The window is inclusive `[as_of - days, as_of]`, measured in instants. Signals
outside the window and future signals have separate exclusion counters. An
explicit `--as-of` reproduces the window deterministically; if omitted, the CLI
captures the current time once for all 30/60/90 windows and records it.

For each valid signal, replay selects the latest spot snapshot for the same
symbol and security GUID that was known at the signal instant. Missing price
proof skips that signal and records `PRICE_AS_OF_MISSING`; future prices are
counted and excluded. Optional expression facts must additionally match the
exact event ID. Future facts are excluded. Individual fact timestamps cannot
look ahead of their containing snapshot. Conflicting duplicate events or
selected equal-time snapshots are refused rather than arbitrarily reconciled.

Replay builds the existing `SymbolDecisionObject@v1` and applies the existing
expression evaluator. Existing blockers remain in force. It records the
comparison, input price/provenance, event/evaluation IDs and timestamps. It
never resolves current identity, holdings, research, DB rows, providers or
models to fill a historical gap. Exact duplicate events are counted once.

## Metrics and limits

Output remains `CrossAssetHistoricalReplayMetrics@v1`, with window counts,
price coverage, skips/refusals, future exclusions, comparison rows and scoring
winner counts. `data_quality` is one of:

- `INSUFFICIENT_DATA`: required signal/price/comparison proof is absent.
- `SCORING_COMPARISON_ONLY`: supplied point-time scores support at least one
  unblocked stock candidate and one option candidate for every in-window signal.
- `INVALID_DATA`: an archive or parameter violates the input contract.

Scoring winner counts describe the supplied evaluator facts. They are not
realized investment counterfactuals. `shares_chosen`,
`options_would_be_superior` and `options_superior_rate` remain **null** because
actual choice/fill/exit/horizon economics are not proven. This repair does not
make expression EV READY or complete the end-to-end CADI program.

CLI exit is 2 for invalid input and 0 for a successfully generated report,
including an honest `INSUFFICIENT_DATA` report. The `ok` field on a written
report means the input contract was valid, never production acceptance. Output
must be outside the read-only archive directory. No input archive is rewritten.

## Evidence and remaining production work

Fixtures and source tests are TEST_ONLY. The meaningful prior-defect test
observed `signals_evaluated=0` for a valid archive; the repaired path evaluates
that archived signal, preserves input bytes and retains unknown realized
superiority. Tests cover missing/malformed inputs, aware/as-of identity proof,
future exclusion, temporal boundaries, price coverage and refusal receipts.

Production replay still needs a governed export of immutable signals/identities,
point-time price data and per-contract option economics with source lineage.
An upserted latest signal row or summary-only chain record does not establish
what was available at a historical decision time. Actual archive coverage and
end-to-end readiness require separate observed evidence and operator decisions.
No historical exporter or analytical model is introduced by this change.
