# CIO Investment Intelligence Card (Phase A) — 2026-08-21

**READ_ONLY_ADVISORY.** Replaces raw product-diff Telegram dumps with per-ticker narrative cards.

## Problem

Outbound product notify looked like:

```text
symbol=BOOK
trigger_symbol=SPCX
- reentry_added UBER → NEAR
```

## Fix

- `scripts/lib/cio_symbol_intelligence.py` — assemble + `render_telegram_card`
- `_enqueue_material_product_outbox` — **one card per material ticker** (cap 3)
- Sections: Why now · Thesis · Technical · Catalyst · Causality · Provenance
- Missing facts → `DATA_UNAVAILABLE` (no invention)
- Decision origin labeled `FRESH_RESEARCH` vs `DETERMINISTIC_RANK`

## Next (Phase B)

Inline Agree/Defer/Need-data buttons + shared feedback journal (continuity on next alert).

## Tests

`tests/test_cio_symbol_intelligence_card.py`
