# SCREENER-ARCH-3C — Lifecycle Detection Design

## Algorithm

For each screener run (identified by `source` + `run_date`):

### Step 1: Load Prior Membership

```sql
SELECT symbol, membership_status, consecutive_missing_count
FROM screener_symbol_membership
WHERE screener_id = :source
```

### Step 2: Load Current Run Symbol Set

```sql
SELECT DISTINCT symbol
FROM trade_ai_scans
WHERE source = :source AND scanned_at::date = :run_date
```

### Step 3: Classify Transitions

For each symbol in current run:
- **No prior membership** -> `entered` (new symbol)
- **Prior status = dropped/stale/expired** -> `reentered`
- **Prior status = present** -> `present` (still here)

For each symbol in prior membership but NOT in current run:
- Increment `consecutive_missing_count`
- If `missing_count == 1` -> `dropped`
- If `missing_count >= STALE_THRESHOLD (3)` -> `stale`
- If `missing_count >= EXPIRE_THRESHOLD (7)` -> `expired` (archive only, no delete)

### Step 4: Multi-Screener Universe State

- Symbol is `active_in_universe` if present in ANY screener
- `dropped_from_screener` does NOT mean `dropped_from_universe` if still present elsewhere
- Only `expired` across ALL screeners = inactive

### Step 5: Write Events

For each transition, write to `screener_symbol_membership_history`:
- `entered`, `present`, `dropped`, `stale`, `expired`, `reentered`
- Deduplicate by `(symbol, screener_id, run_id, event_type)`

### Step 6: Update Membership

Update `screener_symbol_membership`:
- `membership_status` = new state
- `consecutive_missing_count` = increment or reset to 0
- `consecutive_seen_count` = increment or reset to 0
- `present_this_run` = true/false
- `last_seen_in_screener_at` = updated if seen
- `last_seen_run_id` = updated if seen

## Thresholds

| Threshold | Value | Configurable |
|-----------|-------|-------------|
| Dropped | missing 1 run after prior presence | N/A (always 1) |
| Stale | missing >= 3 consecutive runs | STALE_THRESHOLD |
| Expired | missing >= 7 consecutive runs | EXPIRE_THRESHOLD |

## Mass-Drop Protection

If >50% of prior symbols disappear in a single run:
1. Check if run produced results (at least 1 symbol)
2. If run had 0 results -> skip entirely (failed/auth/captcha)
3. If run had results but >50% drop -> mark `needs_review`, do NOT apply drops
4. Only apply drops if run appears complete (>50% retention OR explicit `exhausted` status)

## Run Sequencing

- Runs are ordered by `(source, scanned_at::date)` — one comparison per source per day
- Within a day, all time slots (0400, 0900, etc.) for a source are merged into one daily symbol set
- This avoids false drops from partial intraday runs

## No Deletions

- `expired` symbols are marked, never deleted from `screener_symbol_membership`
- `screener_symbol_membership_history` is append-only
- Catalog rows (`incubator_universe`) are never deleted by this system
