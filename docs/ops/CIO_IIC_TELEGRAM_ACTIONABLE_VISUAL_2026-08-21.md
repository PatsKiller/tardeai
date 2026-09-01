# CIO IIC Telegram — actionable visual + raw dump kill (2026-08-21)

Status:      HISTORICAL
as_of:       2026-08-21T10:25:48-04:00
Measured at: efcc51365 / not measured

**READ_ONLY_ADVISORY.** Telegram has no text colors — hierarchy uses **severity emoji + HTML `<b>`**.

## Why

1. Pre-IIC `CIO material change · BOOK` bullet dumps were noisy and non-actionable.
2. Early IIC cards used `*Markdown*` but delivery forced `parse_mode=None` → asterisks showed literally (no bold).

## Visual language

| Severity | Emoji | When |
|----------|-------|------|
| HOT | 🔴 | Upgrade → READY/REENTER; DO_NOW; top opp ranks |
| WARM | 🟠 | Added/upgraded → NEAR; opportunity added |
| COOL | 🟡 | Downgrade; AVOID/WAIT |
| COLD | ⚪ | Removed / book housekeeping |
| Research | 🔬 / 📐 | FRESH_RESEARCH / DETERMINISTIC_RANK |

Lead line: `{emoji} <b>SYM · verb · from → to</b>` then **Do this** · Why now · Levels · Thesis.

## Raw dump kill

- Enqueue already emits IIC cards (max 3) not kind/from→to lists.
- Book fallback subject: `CIO book update · {label}` (not `CIO material change`).
- Delivery: `is_raw_product_dump_body` → `SUPPRESSED_RAW_PRODUCT_DUMP`.
- Notes set `parse_mode: HTML`; transport honors opt-in only.

## Follow-up

Churn dwell/hysteresis for UBER↔ARKG↔AUUD flip-flops (not this change).

## Tests

`test_cio_symbol_intelligence_card.py`, `test_cio_raw_product_dump_suppress.py`, transport plain-ids HTML pass-through.
