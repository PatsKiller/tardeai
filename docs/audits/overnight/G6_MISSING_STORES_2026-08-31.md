# Overnight G6 — Missing CanonicalStoreRegistry stores

**Wave:** Overnight G6  
**Date:** 2026-08-31  
**Authority:** `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR=0` · no deploy  
**Branch:** `fix/overnight-g6-missing-stores`  
**Rails:** Prefer report over inventing unread stores · evening packet forbids retired `cio_decisions`

```
Status:      ACTIVE
as_of:       2026-08-31
Measured at: persistent-state + portfolio-server/CURRENT
             origin/main tip at branch cut
```

## Rule

Create an **empty durable JSONL** only when **both** hold:

1. `CanonicalStoreRegistry@v1` lists the store, **and**
2. A **live production consumer** reads **that registry path** (the jsonl/path),  
   not a similarly named Postgres table, not a sibling filename.

Otherwise disposition = **`CONSUMER_ABSENT_OR_RETIRED`** — document and do **not** create.

## Existence (verified)

| store_id | registry path | persistent-state | CURRENT | notes |
|----------|---------------|------------------|---------|-------|
| `cio.decisions` | `data/cio/cio_decisions.jsonl` | **MISSING** | **MISSING** | `retired_as_canonical_current=true` |
| `notifications.outbox` | `data/cio/cio_notification_outbox.jsonl` | **MISSING** | **MISSING** | live sibling exists (below) |
| `learning.weekly` | `data/cio/weekly_learning.jsonl` | **MISSING** | **MISSING** | DB / other filename (below) |

**Live sibling (not the registry path):**  
`data/cio/operator_notification_outbox.jsonl` — **EXISTS** on persistent-state and CURRENT (~583 KiB, mtime 2026-08-30). This is what `NotificationOutbox()` defaults to.

**Not created this wave:** zero empty durable files.

## Decision table

| store_id | registry expects? | live consumer of **registry** path? | disposition | create? |
|----------|-------------------|--------------------------------------|-------------|---------|
| `cio.decisions` | yes | **no** (retired; evening packet forbids; shadow soft-miss only; do not confuse with Postgres `cio_decisions`) | **CONSUMER_ABSENT_OR_RETIRED** | **no** |
| `notifications.outbox` | yes | **no** (live writer/reader = `operator_notification_outbox.jsonl`; registry path would be an empty twin) | **CONSUMER_ABSENT_OR_RETIRED** | **no** |
| `learning.weekly` | yes | **no** (`multi_tier_trade_reviewer` → Postgres `paper_trade_multi_reviews`; API/materialize → `cio_weekly_learning_reviews.jsonl`) | **CONSUMER_ABSENT_OR_RETIRED** | **no** |

### `cio.decisions` — do not revive

- Registry: `retired_as_canonical_current: True`; note says Aegis must not hunt this file.
- `config/aegis_evening_surveillance.json` lists `cio_decisions` under `forbidden_inputs`.
- `scripts/aegis_evening_packet.py` stamps `retired_artifacts_forbidden: ["cio_decisions"]`.
- Production case store is `cio_production_cases.jsonl` (present). Postgres table `cio_decisions` is a **different** surface — out of scope for empty jsonl creation.
- `memory_consolidator_shadow.py` soft-reads the path and treats missing as `[]` — not a live intelligence consumer.

### `notifications.outbox` — path drift, report only

- Registry primary: `data/cio/cio_notification_outbox.jsonl` (absent).
- Live class `scripts/lib/cio_notification_outbox.NotificationOutbox` defaults to  
  `data/cio/operator_notification_outbox.jsonl` (present, populated).
- `control_plane_api` resolves the registry id (existence probe); `telegram_receipts` optionally lists the registry path and **skips if absent**.
- Creating an empty file at the registry path would make `exists=true` with zero events while the live sibling holds the real outbox — dishonest. Prefer report.

### `learning.weekly` — no jsonl consumer of registry path

- Registry path `weekly_learning.jsonl` is unread.
- Writer named in registry (`multi_tier_trade_reviewer`) persists to Postgres `paper_trade_multi_reviews`.
- `materialize_cio_weekly_learning.py` / `api_v3_cio._weekly_learning_store` use  
  `cio_weekly_learning_reviews.jsonl` (also absent on host — separate gap, not this registry path).

## Change this tranche

| File | Change |
|------|--------|
| `scripts/cio_missing_stores_g6.py` | Classifier + host existence probe + CLI |
| `tests/test_overnight_g6_missing_stores.py` | Locks create=false / CONSUMER_ABSENT_OR_RETIRED for all three |
| `scripts/run_cio_hardening_ci.py` | Allowlist gate `overnight_g6_missing_stores` |
| This audit note | Evidence |
| `docs/INDEX.md` | Regenerated for G3 drift gate |

**Durable files created on persistent-state / CURRENT:** **none.**

## Proof commands

```bash
python3 scripts/cio_missing_stores_g6.py --host-check
python3 scripts/cio_missing_stores_g6.py --json --host-check
python3 -m pytest -q tests/test_overnight_g6_missing_stores.py
python3 scripts/run_cio_hardening_ci.py
python3 scripts/check_test_coverage.py --fail-on-new
python3 scripts/check_dark_contracts.py --fail-on-new
```

## Deploy

None. Push + merge only. No empty store revival. No cron install.
