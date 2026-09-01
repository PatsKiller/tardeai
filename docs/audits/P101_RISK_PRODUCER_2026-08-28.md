# P10.1 — `risk_management.json` has a producer. It writes to the wrong tree.

Status:      HISTORICAL
as_of:       2026-08-30T15:13:40-04:00
Measured at: efcc51365 / not measured

P8.5 recorded, explicitly as unproven, that no scheduled writer could be identified. **That
was wrong**, and the method that produced it is the same pattern-matching that has now
misled this work three times. Corrected below.

`[VERIFIED]` = command run against live state, output quoted. `[CODE]` = read from source in
`46bda9d8-main-exact-phase2-20260828-092136`.

---

## The producer exists, is scheduled, and ran today

Demonstrable, not inferred `[CODE]`:

```python
# scripts/portfolio_stops.py:398
def save_risk_state(risk_data: Dict, state_dir: Path) -> None:
    out = state_dir / "risk_management.json"
    out.write_text(json.dumps(risk_data, indent=2, default=str))
```

Called from `portfolio_orchestrator.py:311`, which is cronned `[VERIFIED]`:

```
15 7 * * 1-5   cd $PROJ && safe_flock /tmp/portfolio_orch.lock $PY scripts/portfolio_orchestrator.py
```

And it succeeded this morning `[VERIFIED]` — from the orchestrator's own log:

```
✅ Risk: heat=0.1% | 26 stops | 0 triggered
```

Why the earlier pass missed it: `portfolio_stops.py` never appears in a grep for modules
*mentioning* `risk_management.json` alongside the readers, because the write is in a
one-line helper whose caller imports it locally inside a `try:` block. The lesson is the one
already learned twice this phase — **"appears to write" is not a method.** Following the
symbol to a `write_text` call is.

## The actual defect: the producer writes a copy the consumer never reads

```
tree                          mtime          size
$PROJ (checkout)              08-28 07:30    10,247   <- written today, on schedule
persistent-state              08-26 07:31    10,239   <- what the CIO reads
release .../data/portfolios/state  -> symlink to persistent-state
```

The cron runs `cd $PROJ`, and `portfolio_orchestrator` resolves `state_dir` from its own
working directory, so the fresh file lands in the checkout. The CIO snapshot reads
persistent-state. The release symlinks that directory, so the served copy is the stale one.

**The content genuinely differs** `[VERIFIED]` — this is not an mtime artefact:

```
differing fields: positions, total_unprotected_mv, unprotected, stop_count, total_mv
  stop_count          checkout 26   persistent 25
  portfolio_heat_pct  checkout 0.09 persistent 0.09
```

So the CIO has been reasoning about a two-day-old risk picture with a different stop count
and different position and market-value totals, while a correct one was written into the
checkout each weekday.

This is the served-copy split again — the same shape as the release-local `logs/` fork
(#569) and the two holdings copies (#570, P8.6). Third instance, same cause: a writer whose
path resolves from its own cwd, and a reader on the canonical path.

## What this does to P8.5

P8.5 is **unblocked, and its held decision was right for the wrong reason.**

The flip would have blocked three purposes on `risk` being 50 hours stale. That staleness is
real *at the path the CIO reads* — but it is not a missing producer, and stamping was never
the question. **The fix is the write path, not the stamp.** Once the producer writes where
the consumer reads, `risk` refreshes each weekday at 07:30 and its 24h threshold is
comfortably met on weekdays.

Two consequences worth separating:

1. **Do not stamp `risk` to make the flip cheap.** P8.5 said this and it still holds. An
   honest stamp on the stale copy blocks three purposes, correctly.
2. **The flip stays held**, but on a smaller question than before: fix the split, re-measure,
   and the blocker likely disappears without touching the gate. That is a code change on a
   money-adjacent path and is not being made here — P10.1 was scoped to establish the
   producer.

A weekend caveat the flip must account for: the producer is `1-5`. On Sunday the file is
legitimately ~48h old against a 24h threshold, so a blocking gate would block every Monday
morning. That is an argument about the threshold, not the data.

## The general list — domains never age-checked

Any domain carrying no stamp can hide an arbitrary gap. One instance has now been found; the
population is `[VERIFIED]`:

```
domain              state       threshold   required by
risk                AVAILABLE      24h       3 purposes   <- the gap found here
cost_basis          AVAILABLE     720h       1 purpose
investment_policy   AVAILABLE     168h       1 purpose
model_portfolio     AVAILABLE     168h       1 purpose
hermes_research     AVAILABLE      24h       0
sectors             AVAILABLE      24h       0
transactions        AVAILABLE      24h       0
```

Three of the seven are required by a passing purpose and none of them is age-checked. `risk`
was the one instance anybody looked at, and it was two days stale. **The other six have not
been checked**, and the same class of gap can hide behind any of them. That is the finding
this list exists to make: not that the six are stale, but that nothing would say so if they
were.

`hermes_research`, `sectors` and `transactions` are required by no purpose, so a gap there
degrades quality without blocking anything — the least urgent and the easiest to leave.

## Status

Nothing changed. The producer question is answered, the staleness is explained, and P8.5's
hold is now resting on a specific, fixable cause rather than an unknown.
