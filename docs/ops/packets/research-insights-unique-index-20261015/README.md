# Packet: UNIQUE index on research_insights(source_reference) (DDL, NOT APPLIED)

Source: `~/n8n-maturity-verification/arch-review-20261014/CANARY_DOUBLE_EFFECT_AUDIT.md`, finding 2.
Branch `fix/canary-effect-keys-20261015`. Prepared by Agent A, 2026-10-15. Not applied: the operator runs it.

## Why

`scripts/research_insight_extractor.py` inserts one `research_insights` row per news article or catalyst, and
guards each insert with `NOT EXISTS (... source_reference = 'news:<id>' / 'catalyst:<id>')`. That guard stops a
sequential second run from writing a duplicate. It does not stop two concurrent runs (cron and n8n in the same slot,
as on 2026-10-13 06:50 ET). A unique index makes a concurrent duplicate fail instead of landing.

## Evidence (read-only, 2026-10-15 ~01:00Z)

`check_research_insights.py` (SELECT only, `transaction_read_only = on`, `trade_ai@localhost:5432`, via
`scripts/db_adapter._get_conn()`):

| | |
|---|---|
| rows | 52,684 (2026-07-16 06:50 → 2026-10-14 18:50 ET) |
| distinct `source_reference` | 52,684 |
| NULL `source_reference` | 0 |
| **duplicate groups** | **0** (0 extra rows) |
| prefixes | `news:` 26,437 · `catalyst:` 26,247 |
| existing indexes | `research_insights_pkey`, `idx_research_symbol`, `idx_research_thesis` (no unique on source_reference) |
| size | 63 MB |

## Files

| File | What |
|---|---|
| `sql/migrations/20261015_research_insights_source_reference_unique_concurrently.sql` | **Use this.** Preflight DO block (refuses on duplicates or an INVALID leftover), `CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS`, postcheck DO block (present, VALID, UNIQUE, on `(source_reference)`). Autocommit, outside a transaction. Writers keep inserting while it builds. |
| `sql/migrations/20261015_research_insights_source_reference_unique.sql` | Plain variant in one transaction (`lock_timeout 5s`). Same checks. Blocks writes to the table for the build (seconds at 63 MB). Use it only if CONCURRENTLY cannot be used. |
| `sql/migrations/20261015_research_insights_source_reference_unique_rollback.sql` | `DROP INDEX CONCURRENTLY IF EXISTS`. No row is touched. |
| `check_research_insights.py` | Read-only preflight / `--post` verify. |
| `01_apply.sh`, `09_rollback.sh` | Operator wrappers. Each is a dry run unless `APPLY=1`. |

Both variants are idempotent: a re-run after success is a no-op. Neither deletes or rewrites a row. If duplicates
appear before you apply, both refuse and change nothing. Resolve the duplicates by an archived, reviewed step,
never inside this migration.

## Steps (operator; run outside the extractor slots :50 at 06/12/18 ET)

```bash
CODE=$HOME/trade-ai-releases/portfolio-server/CURRENT      # after the PR is promoted
P=$CODE/docs/ops/packets/research-insights-unique-index-20261015
python3 "$P/check_research_insights.py" --code-root "$CODE"          # expect "verdict": "PREFLIGHT OK", dup_groups 0
bash "$P/01_apply.sh"                                               # dry run: prints the psql command
APPLY=1 bash "$P/01_apply.sh"                                       # builds the index CONCURRENTLY
python3 "$P/check_research_insights.py" --code-root "$CODE" --post   # expect "VERIFY OK", index valid + unique
```

If the CONCURRENTLY build fails partway (a lock timeout, or a duplicate inserted during the build), it leaves an
INVALID index. Run `APPLY=1 bash "$P/09_rollback.sh"` to drop it, then re-run `01_apply.sh`. The preflight refuses
to build while an INVALID index is present, because `IF NOT EXISTS` would otherwise keep it silently.

## After the index: behaviour change and follow-up

- The extractor's INSERT has no `ON CONFLICT`. With the index in place, a concurrent duplicate raises
  `UniqueViolation`, so that one run fails loudly (exit != 0) and nothing duplicates. That is the intended trade.
- Follow-up (separate PR, not in this packet): `INSERT ... ON CONFLICT (source_reference) DO NOTHING RETURNING id`
  in `research_insight_extractor.extract_insight`, so a raced insert becomes a quiet skip. It needs the index to
  exist first: an `ON CONFLICT (source_reference)` target without a matching unique index is an error.
- `db_retention.py` deletes rows older than 90 days. The index does not affect it.
