# P9.3 — the two surfaces disagree about the same book

**Two independent computations, not a time gap.** But the sharper finding is that they
are not two computations of the *same* quantity — they are two different quantities
sharing one name and one voice.

READ ONLY. Nothing fixed. `[VERIFIED]` = command run against live state, output quoted.
`[CODE]` = read from source in `9783395a-main-exact-phase2-20260828-082142`.

---

## Which of the two it is

The brief asked: a time gap between two runs of one computation, or two independent
computations. It is unambiguously the second, and the proof is structural rather than
statistical — **there are two separate `build_reentry_book` functions** `[CODE]`:

```
scripts/lib/cio_investment_product.py:581
    build_reentry_book(prev, queue, lessons, fs_rows, infl, *, root)

scripts/lib/cio_desk_depth.py:766
    build_reentry_book(*, pin, thr, cash_stage, cash_pct, symbol_weights,
                       sector_posture, heat_pct, max_display=10)
```

Disjoint signatures, disjoint inputs, neither importing the other. A time gap cannot
produce two function definitions.

### Which surface reaches the operator by which path `[CODE]`

| surface | book producer | reaches the operator via |
|---------|---------------|--------------------------|
| **A** | `cio_investment_product.build_reentry_book` | CIO run-complete Telegram · operator product / Command Center sections · Aegis evening packet |
| **B** | `cio_desk_depth.build_reentry_book` via `generate_desk_synthesis_v1` | `api_v3_cio.get_cio_desk_note` → Command Center desk note · **its own `note_telegram`** |

Both are operator-facing. Both emit Telegram. This is the two-writer problem at the
presentation layer, and the brief is right that it is worse than the holdings store,
because there is no reconciliation step between them — each is rendered as *the* book.

---

## What they actually say, measured five minutes apart `[VERIFIED]`

```
SURFACE A   as_of 2026-08-28T12:41:12Z
  posture   RISK ON TREND — SELECTIVE RISK
  book      67 names   NEAR 22 · WAIT 30 · AVOID 15
  nearest   GERN, TDG, ATAI, AIRE, ARKQ, AVAV, CSCO, DHX

SURFACE B   as_of 2026-08-28T12:46:59Z
  stance    defensive_observe · cash STAGE_0
  book      31 actionable   core 11 · micro 16 · dropped_bad_rr 1
  cards     ACHV, IRDM, UBER, SPRC, CSCO, KTOS, ZSL, AVAV, RKLB, AXTI
```

Overlap in the leading names: **CSCO and AVAV only.**

## Why they differ — and why neither is wrong

This is the part that would be wrong to report as a defect.

**They answer different questions.**

- **A** asks *which former holdings are near their re-entry trigger?* It ranks 67
  previously-exited names by distance to trigger and buckets them NEAR / WAIT / AVOID.
- **B** asks *which candidates have acceptable risk-reward at the current cash stage?*
  It builds core and micro cards, and discards one for bad R:R (`dropped_bad_rr: 1`).

**The postures come from different sources, and are different concepts** `[VERIFIED]`:

- A's `RISK ON TREND` derives from `collect_regime()["label"]` — a **measured market
  regime** `[CODE cio_investment_product.py:490]`.
- B's `defensive_observe` is the **governing thesis stance**, read from the desk thesis
  store `[CODE cio_desk_synthesis.py:508]`.

I initially suspected B's stance was the hardcoded fallback default at
`cio_desk_depth.py:351`. It is not: the desk thesis genuinely carries
`stance: 'defensive_observe'` `[VERIFIED]`, so this is a real curated value, not a
constant leaking through.

So one surface reports **what the market is doing** and the other reports **what the desk's
standing policy is**. Both true. Both current. They will routinely disagree, and *should*.

The defect is not the disagreement. It is that **nothing on either surface says which
question it is answering**, and both are rendered in the same voice, on the same channel,
under names that imply the same thing.

---

## Which surface should the operator believe?

**Neither is authoritative for the other's question, and nothing states this today**
`[VERIFIED]` — no field on either surface carries a scope, a question, or a precedence
marker.

The honest guidance, which does not exist anywhere in the system:

| the operator's question | the surface that answers it |
|-------------------------|-----------------------------|
| what is the market regime right now? | A |
| what is our standing posture? | B |
| which exited names are approaching a re-entry trigger? | A |
| which candidates clear risk-reward at this cash stage? | B |
| how much cash and at what stage? | B (`cash STAGE_0`) |

Establishing precedence is an operator decision. Merging the surfaces is not obviously
right — they measure different things, and collapsing them would lose one of the two.
The minimum honest fix is a scope label on each, which is the same remedy P9.0 recommends
for the register problem generally.

---

## The `as_of` lag, separately `[VERIFIED]`

Confirmed, and larger than the brief suggests:

```
holdings.json   as_of         2026-08-26
                generated_at  2026-08-28 06:15:01 ET
position-level  as_of values  2026-08-03, 2026-08-04, 2026-08-26
```

The document was regenerated this morning; its `as_of` is two days stale, and individual
positions carry stamps up to **25 days** old. `as_of` and `generated_at` record different
things, and repricing updates only the latter.

This is the same class as the date-only stamp fixed for `holdings_detail` in #566 — a
document-level `as_of` that ages from a date while the contents refresh underneath it.
The #566 fix corrected the *snapshot domain*; the holdings document itself still carries
the stale field, and every surface that displays a position `as_of` inherits it.

---

## Summary

| question | answer |
|----------|--------|
| time gap or two computations? | **two computations** — two function definitions, disjoint inputs |
| same quantity? | **no** — different questions, both legitimate |
| is either wrong? | **no** |
| does anything state which to believe? | **no** |
| is the `as_of` lag real? | **yes** — 2 days at document level, up to 25 at position level |

Reported, not merged. Surface authority is the operator's decision, as the brief states.
