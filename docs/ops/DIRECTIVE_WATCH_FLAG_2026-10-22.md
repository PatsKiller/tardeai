Status:      ACTIVE
as_of:       2026-10-22T17:30:00-04:00
Measured at: origin/main b9804fa57 / live DB read-only (dry run 2026-10-22, see below)

# `in_directive_watch` fixed at the source (2026-10-22)

## Operator approval (provenance)

This changes the writer of an authoritative store's field (`watchlist_items.in_directive_watch`), an operator-only
decision (AGENTS.md §17, §7A "Ownership and the grant"). Operator, 2026-10-22, in session, verbatim:
**"Yes, I agree with your recommendations."** — given to the read-only investigation's recommendations: fix the
enrichment-coverage alert, and fix the flag at the source — clear it when a directive expires or is archived, and let
only operator-created directives set it (no retirement of the flag or its consumers). No new writer module is added:
the setter and the clearer both live in `scripts/directive_promotion.py`, the flag's only writer (proved by
`test_the_flag_has_one_writer_module`). `watchlist_items` is the proposed domain `watchlist_membership`
(`config/data_source_authority.json` `proposed_domains[]`, writer UNCONSOLIDATED, no grant yet); the flag's writer is
recorded there in `_in_directive_watch_note`. The one-time clear of existing rows is an operator one-liner (below).

## What was wrong `[VERIFIED]` 2026-10-22 (read-only SQL)

- `directive_promotion.py:377` set `in_directive_watch = true` for every promotion, from any directive. Flagged rows by
  the directive that owns them (`watchlist_items.directive_id`), distinct symbols: sector_universe active 1,073,
  think_tank active 635, operator active 249, think_tank archived 78 / expired 51, defense expired 43, … — 2,310
  flagged symbols (3,686 rows: 3,561 `researched`, 125 `active`, 85 `removed`).
- Nothing cleared the flag when a directive expired or was archived.
- The same promotion un-removed rows the operator had removed, and inserted new rows as `active`, for automated
  directives too.

## What changes

1. **Only an ACTIVE operator-created directive** (`watch_directives.created_by` in `operator`, `operator_audit`) sets
   the flag or un-removes a row. An automated directive (think_tank, sector_universe, advisory, rotation_advisor,
   reentry, defense, claude_challenger, cio) still records its provenance — `origin_detail`, `directive_id`,
   `source_tier`, its `watch_directive_hits` row and its watchpool rows — but does not set the flag, never resurrects a
   removed row, and a row it inserts is `researched`, not `active`.
2. **Reconciler** (`plan_/apply_/restore_directive_watch_flag` in `directive_promotion.py`, door
   `scripts/reconcile_directive_watch_flag.py`): a flagged row keeps the flag when an ACTIVE operator-created directive
   matches it by ownership (`directive_id`), by ticker spec symbol, or by a promoted `watch_directive_hits` row (the
   promotion that set the flag; ownership can later move to an automated directive through the `directive_id` CASE,
   the match does not). Otherwise the flag is cleared. Backup of every before-value first (JSONL, fsync), the UPDATE
   re-checks the rule at write time, touches only `in_directive_watch` and `updated_at`, never deletes.
3. **Kept reconciled:** after the operator's one-time apply writes the marker
   `data/runtime/directive_watch_flag_reconcile_last.json`, `watch_directives_service.py --apply` (existing cron line,
   every 30 min in market hours; no new schedule) clears at most 200 newly-unmatched rows per run (a directive that
   expired or was archived since), with a daily backup file. Before the marker exists it does nothing.

## Dry run `[VERIFIED]` 2026-10-22 (read-only session; nothing written)

```
$ python scripts/reconcile_directive_watch_flag.py
in_directive_watch — keep rule: an ACTIVE directive created_by ['operator', 'operator_audit'] matches (ownership, ticker spec symbol, or a promoted hit)
  before: 3771 rows, 2310 symbols (watch_universe.directive_symbols)
  after : 842 rows, 401 symbols
  clear : 2929 rows, 1936 symbols
  cleared rows by owning directive (created_by, status):
    sector_universe      active     1466
    think_tank           active     895
    think_tank           archived   129
    think_tank           expired    94
    defense              expired    77
    advisory             active     45
    rotation_advisor     expired    39
    advisory             expired    35
    rotation             active     30
    sector_universe      archived   28
    rotation_advisor     active     26
    reentry              expired    22
    reentry              active     22
    rotation             expired    17
    rotation_advisor     archived   3
    claude_challenger    expired    1
  sample: 824430300(think_tank/active), A(sector_universe/active), AADX(think_tank/active), AADX(think_tank/active), AAL(think_tank/active), AAL(think_tank/acti …
DRY RUN: nothing written. To apply: --apply --expect-clear 2929
```

2,310 flagged symbols → 401. No row owned by an active operator directive is in the clear list (no `operator` line in the breakdown). The investigation's estimate was ~250: that counted ownership only (257 symbols); 144 more are matched by a promoted hit of an active operator trend directive whose ownership later moved to an automated directive, so the flag was set by the operator's directive and the directive has not expired — they keep it. A dry run on the day of the apply will differ slightly (the servicer keeps promoting).

## Operator one-liners

```bash
cd ~/trade-ai-releases/portfolio-server/CURRENT && PY=~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
$PY scripts/reconcile_directive_watch_flag.py                                  # 1. dry run: counts before/after + breakdown
$PY scripts/reconcile_directive_watch_flag.py --apply --expect-clear <N>       # 2. apply: N = the dry run's clear_rows
$PY scripts/reconcile_directive_watch_flag.py --restore <backup.jsonl>         # rollback dry run (backup path is in the apply output)
$PY scripts/reconcile_directive_watch_flag.py --restore <backup.jsonl> --apply # rollback
```

Run from the served release after this PR is released. Backups land in
`~/trade-ai-releases/persistent-state/data/backups/directive_watch_flag/`. The apply exits 1 if anything is left to
clear after it (a concurrent change); re-run the dry run.

## Expected effect on the consumers (they read the flag; no code change)

| Consumer | Reads | Effect |
|---|---|---|
| `hermes_top20_external_intel._top()` | rank ≤ 20 OR flagged | candidates ≈2,311 → ≈20 + the operator-matched set (dry run: 401 flagged symbols); the budget guard still tiers them |
| `news_ingestion --priority` | held, proposals, scans, active, flagged (cap `NEWS_INGEST_MAX=60`) | the cap stops being consumed by automated directive names |
| `pro_analyst_fetch` | flagged = tier 2 | automated directive names drop out of tier 2 |
| `build_pro_analyst_read_model` | flagged = `watch` | fewer `watch` rows |
| `external_market_data_ingest` | flagged OR status active/researched (`:73`); flagged = priority 1 (`:355`) | universe almost unchanged (cleared rows are mostly `researched`); priority-1 set shrinks |
| `watch_universe.symbols()/directive_symbols()` | flagged | directive set = the operator-matched set |
| enrichment audit | no longer reads the flag (`docs/ops/ENRICHMENT_COVERAGE_AUDIT_2026-10-22.md`) | — |

`hermes_top20._top()` is proven on a disposable Postgres to shrink exactly to rank ≤ N plus operator-matched names.

## Tests

`tests/test_directive_watch_flag_source_20261022.py` (gate `directive_watch_flag_source_20261022`): the writer's SQL,
one writer module, real-Postgres behaviour (plan counts, backup-first apply, write-time re-check, bounded apply,
restore, automated vs operator vs archived directive, hermes `_top` before/after), consumer contracts, the servicer
hook gated on the marker, the CLI's read-only dry run and `--expect-clear` refusal.
