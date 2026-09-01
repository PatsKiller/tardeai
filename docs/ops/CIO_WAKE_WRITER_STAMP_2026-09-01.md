Status:      ACTIVE
as_of:       2026-09-01T17:30:00-04:00
Measured at: origin/main 433511415 (pre-merge base)
Canonical repo path: docs/ops/CIO_WAKE_WRITER_STAMP_2026-09-01.md
Authority:   dated record of the wake writer-stamp fix; not a behaviour spec
See also:    docs/ops/litmus/LITMUS_WAKE_2026-09-01.md
             docs/ops/CIO_M5_FIRST_FIRE_2026-09-01.md

# Wake persist stamps `cc_narrative.writer` with the live path

## Verdict

**M5 stays `M5_CANDIDATE`.** This change only corrects authorship on a cognition
write that already happens. It does not claim days-earlier honor, does not
hand-run the entrypoint, and does not promote CURRENT.

## Problem (from LITMUS_WAKE / FIRST_FIRE defect 2)

The 13:35 unattended fire moved `EXIT:WLDS.next_eligible_at` via
`decide_after_load` → `apply_after_cycle` → `upsert`. The row's
`cc_narrative.writer` remained `migration:deterministic`. No migration wrote
it — the live wake path did. AGENTS.md §9.2: writer names the author.

Cause: when `decision` alone moved `next_eligible_at`, `apply_after_cycle`
passed `narrative=None`, so `apply_cognition` updated the cadence field and
left the prior narrative blob untouched.

## Change

| piece | what |
|---|---|
| `scripts/lib/cio_rehydrate.py` | when a decision moves `next_eligible_at` and no more-specific rule already authored a narrative, rebuild `cc_narrative` with `writer=cognition:decide_after_load`, preserving what / thesis_fit / evidence_refs |
| `tests/test_wake_writer_stamp.py` | flash restamp · cadence_not_due noop · defer writer kept · BehaviorWriteRefused · source-shape mutation |
| hardening allowlist | gate `wake_writer_stamp` |

Same `next_eligible_at` (the `cadence_not_due` shape) does **not** restamp —
otherwise every skip would become a false persist.

## Explicit non-goals

- wake_research_persist.json shape (#832) — untouched  
- cash_letter / CASH_SLEEVE / #777 — untouched  
- lane registry / sweep (#834) — untouched  
- `BehaviorWriteRefused` — untouched  
- No Telegram, no `outcome --apply`, no holdings, no `.env`  
- No `$PROJ` fast-forward, no promote  
- M5 not claimed OBSERVED  

## Follow-up

Follow-up to #831 litmus pack + FIRST_FIRE defect 2. One PR.
