# Learning loop PR1 — stable recommendation ids, trade linkage, R attribution (2026-10-21)

```
Status:      BUILT, NOT APPLIED (branch feat/learning-loop-pr1-20261021). Migration ships as a file; the operator applies it.
as_of:       2026-10-21T13:30:00-04:00
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0 · no broker code, no broker call
Tests:       tests/test_learning_loop_pr1_20261021.py (gate learning_loop_pr1_20261021);
             CC-v3 node test src/lib/recommendationOrigin.test.ts
```

Operator, 2026-10-21, verbatim: *"Approve learning-loop plan and begin PR1 immediately. Stable recommendation IDs,
trade linkage, and R-multiple attribution provide the highest long-term value and should be implemented before
calibration."*

## What it does

1. **Every recommendation the operator sees gets a stable `rec_id`** in a new table, `recommendation_registry`.
2. **Every closed Schwab round trip is linked** to the recommendation it most plausibly came from, or is recorded as
   `operator_initiated`. The result goes in a new table, `trade_recommendation_links`.
3. **R is attributed** against the linked recommendation's plan stop, along with the planned R:R and whether the
   target or the stop was reached at exit.
4. **TradeInView shows it.** `/api/v2/journal` returns a `recommendation` block per trade. Each journal card gets a
   chip, and the trade detail shows "From recommendation … · source · confidence" with the plan, R achieved and
   planned R:R, or "Your own trade".

## Sources and ids

The id is `rec_` followed by the first 20 hex characters of `sha256(source | natural key)`. It is a pure function of
the source row, so it is the same whether the curator hook, the backfill or a re-run computes it.

| source | where it lives | natural key | levels | active window (TTL) |
|---|---|---|---|---|
| `cio_opportunity` | `data/cio/cio_opportunity_assessments.jsonl` | symbol + entry zone + invalidation + primary target + the `run_id` that **first** published that plan | zone, invalidation → `plan_stop`, primary target | first seen → 14 d after it was last re-confirmed; ends early when superseded |
| `paper_trade_proposal` | `paper_trade_proposals` | `id` | final (else proposed) entry, stop, target1 | `created_at` → `max_expires_at` / `expires_at` (else +5 d) |
| `scalp_alert` | `trade_ai_scans` (decision GO), `scalp_scan_results` (GO, alerted) | `table:id` | price at alert; no stop or target | 1 d |
| `entry_alert` | `alert_events`, types in `ENTRY_ALERT_TYPES` | `alert_uid` | price, stop_price, payload target | 3 d |

**How an opportunity's id is kept stable.** A version line that keeps the same plan, for example after a rank-band or
conviction change, keeps the same `rec_id`. A moved level gets a new one and supersedes the old rec. So does a plan
that disappears and later comes back, because its first-seen run is different. Conviction is stored **at issue** and
never updated. `OpportunityLineage` folds the append-only history in file order, and the curator hook and the
backfill use the same fold.

## Design decisions

- **New tables, not `agent_recommendation_registry`.** That table has no entry zone, stop, target, direction or
  expiry. It holds 549,908 agent-opinion rows. `scripts/agent_outcome_linker.py` joins **every** row of it to
  `paper_trade_proposals` by symbol, so registering proposals there would link proposals to themselves and
  contaminate agent calibration.
- **Not `trade_closed.signal_id` / `signal_linked_at`.** `signal_id` is an INTEGER and a `rec_id` is text. Also,
  `schwab_journal_builder.py` DELETEs every Schwab `trade_closed` row and re-INSERTs it on each `--apply`, which runs
  every 15 min in market hours and at 18:15. Anything written onto `trade_closed` is wiped within minutes, and this is
  why the columns read 0 of 247. Links are keyed on `schwab_round_trips.dedupe_key`, the stable natural key of a
  round trip. The API reaches them through `trade_closed.dedupe_key = 'srt:' || schwab_round_trips.id`.
- **`plan_stop` / `plan_target`, never `stop` / `target`.** These are published plan levels kept for attribution.
  `stop` is a CIO behaviour field (`cio_instrument_record.BEHAVIOR_FIELDS`), and a test asserts that no registry
  column or row key is a behaviour field.
- **Hooks.** The CIO opportunity curator registers at creation: on `--apply`, after the version lines are appended.
  The opportunity store is a file and had no id, so the hook belongs there. Proposals and alerts already have
  durable rows with stable primary keys, so their `rec_id` is a pure function of that key. They are registered by
  `scripts/recommendation_registry_sync.py`, which runs before the linker, rather than by editing the writers.
  - Proposals have nine writers. One of them, `defense_execution.py`, is broker execution code and outside scope
    (§0 rule 2).
  - The scalp GO path is the governed live n8n lane (§23.3), and adding a DB writer to it needs its own grant.
- **`alert_events` has no entry or scalp alerts.** No such alert types appeared in the 90 days to 2026-10-21. The
  scalp GO alerts the operator sees are rows in `trade_ai_scans` and `scalp_scan_results`, so those are the
  `scalp_alert` sources. `ENTRY_ALERT_TYPES` stays in place, so an entry alert written to `alert_events` later is
  registered without a code change.
- **Single writer, fail-safe.** `scripts/lib/recommendation_registry.py` is the only module that writes the registry.
  - Every write runs inside a SAVEPOINT. Before the migration the write reports `skipped`, and the caller's
    transaction is untouched.
  - Setting `TRADEAI_REC_REGISTRY_WRITE=0` turns the writes off.
  - A re-confirmed opportunity rewrites its row at most every 12 h.
  - `created_at`, the levels and `conviction_at_issue` are never updated.
- **The authority registry is proposed, not applied.** Two domain rows are drafted in
  `config/policy_proposals/data_source_authority_learning_loop_20261021.json`. Adding the writer of an authoritative
  store is an operator decision (§17, §7A).

## Linker rules (`scripts/lib/trade_recommendation_linkage.py`)

- **Candidates.** A candidate has the same symbol and the same direction as the trade. Schwab round trips are long, so
  a short proposal never matches a buy. The trade's entry time must fall in `[created_at, expires_at + 1 d grace]`.
- **Confidence tiers:**
  - `exact`: the fill is inside the entry zone. A single-price zone is widened by ±0.5%.
  - `zone`: the fill is within 2% of the nearer edge.
  - `window_only`: the fill is in the active window, 2–10% from the zone.
  - Further than 10% is not plausible.
- **Choosing the best match.** Highest confidence wins, then the smallest distance, then the most recently issued
  recommendation, then `rec_id`.
- **No match.** The trade is written `origin='operator_initiated'`, `link_confidence='none'` and `rec_id IS NULL`.
  A CHECK constraint makes that combination explicit.
- **R for a long:** `(exit − entry) / (entry − plan_stop)`. Shorts are mirrored. With no linked stop the journal's
  `trade_closed.stop_used` is used. With neither, R is null and `r_null_reason` says why. A stop on the wrong side of
  the fill is null with its own reason.
- **Planned R:R** is computed from the middle of the plan's entry zone.
- **Target or stop hit** is judged on the exit price (`hit_basis='exit_price'`), because there is no intratrade path
  here.
- **Writes.** The linker writes one row per round trip and is idempotent. A row is rewritten only when its link or
  attribution changed, and `linked_at` moves only when the `rec_id` changes.

## Live dry run (read-only session, 2026-10-21 ~13:23 ET)

Command:
`trade_recommendation_linker.py --from-sources --days 90`, run with CURRENT's venv from this branch. It used the
READ ONLY session.

Recommendations built in memory for the window, including 60 days of look-back for recommendations still active:

| Source | Count |
|---|---|
| CIO opportunity plans | 4,735 |
| Paper trade proposals | 11,833 |
| Scalp GO alerts | 192 |
| Entry alerts | 0 (none exist) |

`recommendation_registry_sync.py --days 90` (dry run) would register **13,992** recs, all with unique ids:

| Source | Count |
|---|---|
| CIO opportunity | 4,735 |
| Paper trade proposal | 9,069 |
| Scalp alert | 188 |

Of these, 13,804 carry a plan stop and target.

Linker result:

| Trades closed in the last 90 days | exact | zone | window_only | operator_initiated | with R |
|---|---|---|---|---|---|
| **73** | 0 | 0 | 0 | **73** | 0 |

Why nothing links, measured trade by trade (read-only diagnostic):

- **43 of the 73 were entered before the 90-day window,** as early as 2026-02. That is before most recommendation
  sources existed. CIO opportunity history starts 2026-10-08, and no Schwab trade was entered after 2026-10-12.
- **Only 6 trades have any recommendation active at entry:**
  - MCD ×3: the only active rec was a **short** defense proposal at 255.09, and the operator bought at 235–238.
  - SPCX ×3: a long proposal at 134.00, against fills at 167–174 (24–29% away).
  - DAIC: a CIO opportunity zone of 1.65–1.85, against a fill at 2.05 (10.8% away, just past the 10% cap).
- **0 of the 73 have a journal stop** (`trade_closed.stop_used` is never filled), so no R can be computed for an
  unlinked trade.

The brief's "84" was not reproduced. 81 round trips exited in the window: 73 have a basis, and 8 are
`basis_unknown` with no entry.

This is the honest baseline. The loop starts producing links as new trades are entered while recommendations are
active. The count to watch is `linked` in the linker receipt.

## Operator steps

1. **Apply the migration.** Additive, two new tables, idempotent:
   `psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_21_learning_loop_pr1.sql`.
   To reverse it, run `migrations/2026_10_21_learning_loop_pr1.down.sql`, which renames the tables and never drops
   them.
2. **Backfill the registry.** Dry run first, then apply:
   `$PY scripts/recommendation_registry_sync.py --days 90`, then `… --days 90 --apply`.
   The apply writes the receipt `data/runtime/recommendation_registry_sync_latest.json`.
3. **Link.** `$PY scripts/trade_recommendation_linker.py --days 90`, then `… --apply`. The apply writes the receipt
   `data/runtime/trade_recommendation_linker_latest.json`.
4. **Schedule.** Cron is frozen, so this is a proposal only (§17, cron-freeze inventory). `schwab_journal_builder.py`
   runs only from two crontab lines, at 18:15 weekdays and intraday, and no pipeline script calls it, so there is no
   pipeline step to add. That ingest line is class `broker_order` / KEEP_ON_CRON in `config/lane_registry.json`, so
   the linker is proposed as a **separate** line. It takes the same lock with a wait, so it always runs after the
   builder finishes:

   ```
   25 18 * * 1-5 cd $PROJ && flock -w 900 /tmp/schwab_ingest.lock bash -c "$PY scripts/recommendation_registry_sync.py --days 3 --apply && $PY scripts/trade_recommendation_linker.py --days 30 --apply" >> logs/trade_recommendation_linker.log 2>&1  # learning loop PR1: register recs + link closed trades (read-only of broker-synced tables)
   ```

   A lane registry row (`trade-recommendation-linker`, owner `cio`) goes with the grant.
5. **Optional.** Apply the two authority rows in `config/policy_proposals/data_source_authority_learning_loop_20261021.json`
   with the operator's approval recorded.

The curator hook starts writing on the first curator run after the migration. Before the migration its receipt shows
`rec_registry.status = "skipped"`.

## Files

- `migrations/2026_10_21_learning_loop_pr1.sql` and `.down.sql`
- `scripts/lib/recommendation_registry.py`: ids, lineage, mappers, and the single writer
- `scripts/lib/trade_recommendation_linkage.py`: matching, R math, and the API attach
- `scripts/recommendation_registry_sync.py`: backfill and incremental registration, dry run by default
- `scripts/trade_recommendation_linker.py`: the linker, dry run by default
- `scripts/cio_opportunity_curator.py`: the `register_recommendations` hook, on `--apply` only
- `scripts/api_v2.py` `journal()`: `tc.dedupe_key`, the per-trade `recommendation` block, and
  `recommendation_link_status`
- CC-v3:
  - `src/lib/recommendationOrigin.ts` and its test
  - `src/components/tradeinview/RecommendationOrigin.tsx` (design tokens only)
  - JournalHub card chip
  - TradeInViewDetail card
