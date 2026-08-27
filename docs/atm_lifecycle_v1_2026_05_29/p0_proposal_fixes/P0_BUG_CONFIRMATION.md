# P0 Bug Confirmation — 2026-05-29

## Bug #1: `expired` vs `EXPIRED` case inconsistency

**Function**: `_expire_stale_proposals(conn)` in `scripts/api_v2.py`
**Lines**: 7501, 7510, 7519
**Endpoint**: Called from background sweep during API lifecycle
**Field**: `SET status='expired'` (lowercase) while all other scripts use `'EXPIRED'` (uppercase)

**Affected rows**: 3 proposals (ids 10, 97, 124 — BLBD, TLSI, EVER)
**Impact**: Queries using `status = 'EXPIRED'` miss these 3 rows. Hygiene counts are wrong.

**Fix**: Change `status='expired'` → `status='EXPIRED'` in all 3 UPDATE statements.
**Frontend change needed**: NO

## Bug #2: Hygiene panel uses `signal_decision` instead of `status`

**Function**: Inline in proposal-hygiene handler, `scripts/api_v2.py`
**Line**: 20494 (was `status = r.get("signal_decision") or ""`)
**Endpoint**: `GET /api/v2/atm/proposal-hygiene`
**Field**: Classification logic read `signal_decision` (which is often NULL or "GO") instead of `status`

**Impact**: Proposals with `status='expired'` but `signal_decision='GO'` (BLBD id=10, TLSI id=97) were NOT classified as expired. Similarly, proposals with `status='REJECTED'` but `signal_decision='GO'` were not classified as rejected.

**Root cause**: The SQL query didn't even SELECT the `status` column. Only `signal_decision` was available.

**Fix**:
1. Add `status` to the SELECT query
2. Use `(r.get("status") or "").strip().upper()` for classification
3. Check against `("EXPIRED",)` and `("REJECTED", "RISK_BLOCKED")` tuples
4. Keep `signal_decision` in response as secondary context
5. Response now includes both `status` (uppercase normalized) and `signal_decision`

**Frontend change needed**: NO — ProposalHygienePanel uses `Record<string, any>` and renders whatever the API sends. The `status` field was already in the response, now it's correct.

## DB Row Mutation
**NO** — both fixes are code-only. The 3 lowercase rows remain as-is in the DB. The hygiene panel normalizes to uppercase at query time. Future proposals will be written as EXPIRED (uppercase) preventing recurrence.
