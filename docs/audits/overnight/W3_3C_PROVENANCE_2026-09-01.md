# Night Three Wave 3c — provenance markers: writer=author; honest footer

**Date:** 2026-09-01  
**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR=0  
**Branch:** `wt/n3-w3c-provenance`  
**Rails:** Labelling only — no reentry population, no next_reviews/standing_policy judgment fields, no broker/cron.

## Live before (quoted)

Pin `d81ee8ae52d6a2e66f821b90a1c573f83067d43b` · `curl -sS http://127.0.0.1:7777/api/v3/cio/home`

```
cash_letter.writer          = "migration:deterministic"
cash_letter.author          = "migration:deterministic"
cash_letter.model_produced  = false
cash_letter.as_of           = "2026-08-03"   # evidence age (B4) — unchanged
cash_letter.what            = "Cash sleeve 630784.82."

provenance_footer = {
  "model_produced": false,
  "classes": "D counts/sums · T templates · A case-summary context",
  "writer_means": "author",
  "note": "Deterministic projection of cio.product.current + holdings. No model produced this operator product."
}
model_produced (home) = false

instrument_narratives writers:
  migration:deterministic  36
  cognition:defer_honored   1
  (n=37 subjects)
```

Footer was already honest (`model_produced: false`). The remaining lie was
`writer` / `author` naming the **migration copy step** on deterministic and
generated prose alike.

## Defect

AGENTS.md §9.2: *Every generated field is labelled generated, and `writer`
names the **author**, not the last hand that touched the record.*

`cio_migrate_instrument_records.py` stamped `writer="migration:deterministic"`.
Migration copied the blob into the InstrumentRecord spine; it did not author
the prose. B4/B5 then aliased `author = writer`, so the copy-step label became
the displayed author. Tests even asserted `author == "migration:deterministic"`.

## Fix

1. **Seed** (`cio_migrate_instrument_records.py`): stamp `writer="deterministic"`
   (the seed composer), never `migration:…`.
2. **`cc_narrative`** (`cio_instrument_record.py`): emit `author` alongside
   `writer`; add `normalize_writer_author()` that strips a `migration:` prefix
   and preserves it as `copy_step` when present.
3. **Passthrough** (`cio_record_narrative.py`): `build_cash_letter`,
   `narrative_for`, `record_narratives` all normalize writer/author.
4. **Display** (`cio_command_center.py` `_row_narrative` /
   `_stamp_cash_letter_provenance` / home `provenance_footer`): same
   normalisation; force `model_produced: false` on the footer.
5. **Footer text** (`cio_operator_renderers.PROVENANCE_FOOTER` +
   `cio_operator_product.provenance_footer`): keep `model_produced: false`;
   clarify `writer = author (not the copy step)`.

**Not changed:** reentry population, next_reviews / standing_policy judgment
fields, dollar amounts, broker paths.

## Agent-originated field count — before / after / why it moved

Method: Part 2 §10.1 truncation signature on `instrument_narratives.*.what`
(`len == 600` and not ending on sentence punctuation) — the cleanest available
proof of length-capped generated/copied prose. Count non-empty `what` /
`thesis_fit` / `risks[*]` on those subjects. Markers are **not** the detector
(Part 2 taught that).

| metric | before (live) | after (normalized display) |
|---|---:|---:|
| `instrument_narratives` subjects | 37 | 37 |
| subjects with `writer=migration:*` | **36** | **0** |
| 600-trunc AO subjects | 27 | 27 (unchanged) |
| 600-trunc AO fields | **101** | **101** (unchanged) |
| AO fields still labelled `migration:*` | **101** | **0** |
| `cash_letter.writer` | `migration:deterministic` | `deterministic` (+ `copy_step=migration`) |
| `provenance_footer.model_produced` | `false` | `false` |

### Why the number moved (mandatory)

- **Prose inventory (101 fields / 27 subjects) did not move.** Wave 3c
  relabels authorship; it does not rewrite `what` / `thesis_fit` / `risks`.
- **What moved is the mislabelled-copy-step count: 101 → 0** (and 36 → 0
  subjects carrying `writer=migration:*`). Those fields now read
  `writer=author=deterministic`, with `copy_step=migration` when the legacy
  prefix was present — the hand is visible without claiming it authored the
  prose.
- **vs Part 2 census (27 fields / 9 subjects at pin `a5006df1`).** Same
  truncation signature; today's store has more EXIT seeds capped at `[:600]`,
  so subject/field inventory grew (9→27 subjects, 27→101 fields). That growth
  is seed coverage over time, **not** a Wave 3c effect. Wave 3c's delta is the
  marker honesty column, not the prose count.
- **`cognition:defer_honored`** (1 subject) is left alone — already an honest
  author marker.

## Verification

```
PYTHONPATH=scripts:. python3 -m pytest -q tests/test_overnight_b4_b5_asof_provenance.py
# 12 passed
```

CI allowlist: already registered under `money_surface_honesty` in
`scripts/run_cio_hardening_ci.py` — no new file to add.

## Files

- `scripts/cio_migrate_instrument_records.py`
- `scripts/lib/cio_instrument_record.py`
- `scripts/lib/cio_record_narrative.py`
- `scripts/lib/cio_command_center.py` (scoped)
- `scripts/lib/cio_operator_renderers.py` (scoped)
- `scripts/lib/cio_operator_product.py` (scoped)
- `tests/test_overnight_b4_b5_asof_provenance.py`
- this audit note
