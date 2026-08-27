# P0 Read-Only Validation — 2026-05-29

## Status Distribution (DB, unmodified)
| Status | Count |
|--------|-------|
| EXPIRED (uppercase) | 62 |
| expired (lowercase) | 3 |
| Total expired | 65 |
| REJECTED | 72 |
| RISK_BLOCKED | 2 |
| APPROVED_FOR_PAPER_TEST | 2 |
| PENDING | 0 |
| NULL/empty | 0 |
| **Total** | **141** |

## The 3 Lowercase Rows
| ID | Symbol | status (DB) | signal_decision |
|----|--------|-------------|-----------------|
| 10 | BLBD | expired | GO |
| 97 | TLSI | expired | GO |
| 124 | EVER | expired | (empty) |

## Before/After Behavior

### Before (old hygiene logic)
- Classification field: `signal_decision`
- BLBD (id=10): signal_decision=GO → NOT classified as expired → falls to age-based (stale_needs_review)
- TLSI (id=97): signal_decision=GO → NOT classified as expired → falls to age-based (stale_needs_review)
- EVER (id=124): signal_decision="" → NOT classified as expired → falls to age-based
- expired_count: ~62 (missed 3 lowercase rows)

### After (fixed hygiene logic)
- Classification field: `status` (normalized uppercase)
- BLBD (id=10): status=EXPIRED → classified as expired
- TLSI (id=97): status=EXPIRED → classified as expired
- EVER (id=124): status=EXPIRED → classified as expired
- expired_count: 65 (all expired rows counted correctly)

## DB Rows Mutated
**NONE** — all validation was read-only. The 3 lowercase rows remain as `expired` in the database. Normalization happens at API query time via `.strip().upper()`.
