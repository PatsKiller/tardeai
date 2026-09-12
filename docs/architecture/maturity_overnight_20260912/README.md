# Overnight maturity campaign — package, 2026-09-12

Campaign `trade-ai-maturity-overnight-20260912`, Claude implementation and
integration lane. One 12-hour window, 2026-09-12T00:31:44Z → 12:31:44Z.

**No maturity level is awarded here.** READY, 100%, M2_ACCEPTED, MVL_ACCEPTED
and L4/L5 acceptance appear nowhere as claims.

## Read in this order

| file | what it is |
|---|---|
| `MATURITY_SCORECARD_2026-09-12.md` | every clause with the number measured against it |
| `CIO_AS_IS_2026-09-12.md` | what the system actually does, with statuses |
| `CIO_GAP_2026-09-12.md` | what blocks the next level, ordered by what it unblocks |
| `CIO_FUTURE_2026-09-12.md` | the next moves, in dependency order |
| `STATE_ROOT_RECONCILIATION_RUNBOOK.md` | the one change this lane refused to make unattended |
| `VALIDATION_HANDOFF.json` | commands for an independent auditor, and what this lane does *not* claim |
| `../claude/CLOSURE_LEDGER.csv` | every blocker, its reproduction, repair, tests and disposition |
| `../claude/STARTING_IDENTITY.json` | identity recomputed at T0, nothing inherited |
| `../evidence/` | the raw measurements the documents above cite |

## What changed, in one paragraph

Five organic L3 judgments were found recording `$0.00` for real paid calls, no
prompt digest, no release, and one shared `judgment_id` across five distinct
answers; the cache that should have prevented the spend could never hit because
its key included a continuously-decaying weight. The lane was starved anyway by
a shared budget with no per-lane floor. The research circulation lane had not
completed a run in four days — 93 consecutive timeout kills — while its health
predicate reported `healthy: true`, because the predicate had no freshness
condition and treated *zero spend* as positive evidence. The local acceptance
gate had been silently skipping almost everything whenever an operator grant was
live, and fixing that surfaced 14 undeclared schedules, the entire maturity spine
among them. L4's contract turned out to exist; what was missing was anything that
looked at a commitment again after its horizon. And the board defects PR #974
reported were still open on main.

## What this lane refused to do

- **Reconcile the state-root split.** 164 served files are behind their
  producers, but 19 flow the other way and `data/portfolios/state` holds live
  holdings behind a scope this campaign did not hold. A newer-wins merge in
  either direction destroys real data. Detector shipped; runbook written.
- **Fast-forward the canonical tree.** Needs guard scope `maintree`.
- **Manufacture an operator reply** to close M2's inbound clause.
- **Claim L5** because this campaign repaired defects. That is not the
  unattended loop.

## The one thing no amount of work tonight could reach

DeepSeek's operator bulk window reopens at **14:00Z**, measured hour by hour
against `evaluate_offpeak_eligibility`. The campaign deadline is **12:31:44Z**.
Organic L3 authoring on the served epoch was therefore out of reach by 88
minutes, and the lane spent the window refusing correctly — which is the
behaviour the rail exists to produce, not a fault. The work was ordered so the
fixes land before that window opens.
