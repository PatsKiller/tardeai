# CIO — teach the S6 detector the dust rule

Authority: **READ_ONLY_ADVISORY** · MBI **0** · INTERDICT **0** (left as found)
CURRENT pin at dry: `5a11041f` (#624) · health/cio/home 200

Closes the highest-value leftover from the Wave 2 overnight closeout. **The rule
only ever skips a fire — no threshold is loosened and no new fire is added.**

---

## What was actually happening

`S6_CONCENTRATION_OR_DISPOSITION` asks a question that presupposes a position.
On CURRENT it was firing on SRNE — a **$0.90** residual — and the plan carried
its own explanation:

```
fire_reasons: ['disposition_loss_100.0pct_hold_36.0m']
```

Not the concentration branch. The **disposition** branch. A residual share sits
at essentially zero against its cost basis, so it reads as a **100% loss held 36
months**, which clears `disposition_loss_pct 20.0` and
`disposition_hold_months 6.0` on *every* pass.

That is why it could not be fixed by cancelling. A residual can never stop being
a 100% loss, so the rule re-fired the moment the detector ran again: 20 plans
cancelled under authorisation on 2026-08-29, and a new one back within twenty
minutes.

The concentration branch was never the problem — a $0.90 position has no weight.
Only the loss branch could reach it.

## The rule

`_s6_subject_skip_reason` runs before the reason evaluation and drops a subject
that is not a position:

| reason | when |
|---|---|
| `dust_residual` | aggregate market value **< \$50** per ticker |
| `not_a_ticker` | the symbol is an instrument id (CUSIP), not a ticker |
| `no_symbol` | empty subject |

Same documented threshold as the rest of Wave 2
(`holdings_universe.DUST_POLICY`), and both of its guards carry over:

* **Aggregated across accounts** — SPCX at \$5 in taxable and \$21,834 in the IRA
  is one \$21,839 position, not dust.
* **An unknown market value is never dust.** `eval_s6` sums
  `_num(row["market_value"]) or 0`, so an unpriced leg used to contribute `0.0` —
  meaning a real position with a missing price would have looked like a residual
  and been silently dropped. The aggregate now tracks `market_value_known` and a
  single unpriced leg makes the whole subject unknown, which fails **open** to
  HELD.

Cash was already excluded and still is, before this rule is reached.

## Dry — live-shaped evidence, persist=False

```
candidates fired : 1
   SCHD     ['weight_28.4pct']
skipped subjects : 12507E201 not_a_ticker · SCHG dust_residual · SRNE dust_residual

SRNE in fired set: False   ← was disposition_loss_100.0pct_hold_36.0m
SCHG in fired set: False
CUSIP in fired set: False
```

**SCHD still fires** on its genuine 28.4% concentration. That is the point: the
rule subtracts non-positions and touches nothing else.

Skips are reported, not silent — `s6_skipped_subjects` rides on the candidates
that did fire, and `eval_s6_skipped_subjects()` answers for a dry run where
nothing fired at all.

## Live

The one plan that had reappeared, `plan_faab4607a89f` (SRNE), was cancelled under
the standing decision-4 authorisation. `cio_plans.jsonl` 5,007 → 5,009 lines,
append-only; **nothing deleted**. `would_cancel` is now **0**, and with the
detector taught, it should stay 0 rather than returning on the next pass.

## Rails

| Rail | State |
|---|---|
| Thresholds | **untouched** — asserted by test (12.0 / 20.0 / 6.0) |
| New fires added | **none** — the rule only skips |
| Cash handling | unchanged, still excluded first |
| History | append-only; nothing deleted |
| notify / Telegram | none; `notify: false` |
| ThesisDecisionGate | untouched |
| MBI / INTERDICT | 0 / 0 |

## Tests

`tests/test_cio_s6_dust_rule.py` — 15 assertions. Beyond the obvious ones, two
are worth naming:

* **`test_the_disposition_rule_would_otherwise_have_matched`** guards the guard.
  It runs the identical shape at \$50,000 and asserts it *does* fire on
  `disposition_…`. Without it, the main regression test would keep passing if the
  disposition branch ever stopped matching for an unrelated reason — protecting
  nothing while looking green.
* **`test_one_unpriced_leg_makes_the_whole_subject_unknown`** covers the
  fail-open path that the naive `or 0` sum would have got wrong.

Existing suites re-run clean: 102 tests across
`test_cio_situations_phase2a`, `test_r11_situation_engine`,
`test_r12_situation_matrix`, `test_cio_wake_detector` and
`test_cio_wave2_orphan_s6_hygiene`.

---

## Addendum — the skip fails open (follow-up)

Found after the first promote. The sole caller of `eval_s6` wraps it:

```python
try:
    found.extend(eval_s6(evidence, cfg, sym))
except Exception:
    pass
```

If the `holdings_universe` import inside `_s6_subject_skip_reason` ever raised,
the whole evaluator would raise and be swallowed — **silently disabling S6
entirely**. That trades a nuisance dust plan for a missed concentration alert,
which is the wrong direction here: SCHD's 28.4% weight is the alert this detector
exists to raise; a residual plan is an annoyance.

The import is now guarded and returns `None` on failure, so the subject goes
through and behaviour reverts to pre-rule. **A skip rule fails open; only the
safety gates fail closed.** Unlikely in practice — `holdings_universe` imports
only stdlib — but the failure would have been silent, which is what makes it
worth three lines. A test simulates the `ImportError` and asserts SCHD still
fires.

## Live verification

| time (UTC) | event |
|---|---|
| 03:30:26 | detector mints `plan_a067113b2660` (SRNE) — **old code** |
| 03:35:12 | #625 promoted; CURRENT `773b4182` |
| 03:35:41 | `plan_a067113b2660` cancelled under the standing decision-4 authorisation |
| 03:36:33 | first **post-promote** detector pass |
| 03:37:34 | `would_cancel` **0** |

Before the fix a new SRNE plan reappeared within ~20 minutes of every cancel.
The deployed detector at CURRENT carries `_s6_subject_skip_reason`, and both
detector services (`tradeai-cio-reactive`, `tradeai-cio-material-scan`) run with
`WorkingDirectory=CURRENT`, so both paths pick it up. There is a single call site
for `eval_s6`, so no path is left unguarded.
