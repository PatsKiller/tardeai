Status:      ACTIVE
as_of:       2026-10-22T17:05:00-04:00
Measured at: origin/main b9804fa57 / live DB read-only (dry run 2026-10-22 ~17:00 ET); crontab line 474 read with `crontab -l`

# Enrichment-coverage audit — rescoped to the curated Watch (2026-10-22)

Lane `audit-enrichment-coverage` (`scripts/audit_enrichment_coverage.py`, rules in `scripts/lib/enrichment_coverage.py`).

## Operator approval (provenance)

Operator, 2026-10-22, in session, verbatim: **"Yes, I agree with your recommendations."** — given to the read-only
investigation's two recommendations: (1) fix this alert; (2) fix the `in_directive_watch` flag at its source (clear it
when a directive expires or is archived; only operator-created directives set it). This document covers (1). (2) is
`docs/ops/DIRECTIVE_WATCH_FLAG_2026-10-22.md` (separate PR).

## What was wrong `[VERIFIED]` 2026-10-22

| Finding | Evidence |
|---|---|
| Scope was the directive flag: `watch_universe.directive_symbols()` = every `watchlist_items` row with `in_directive_watch=true` — 2,310 symbols, 2,201 with gaps | `scripts/watch_universe.py:47-51`; receipt `audit-enrichment-coverage_last.json` 2026-10-22 20:45 UTC `directive_gaps: 2201` |
| Message: first 12 alphabetically (`[:12]`), no total, so "A…" names every day | old `audit_enrichment_coverage.py:129` |
| P2 every weekday, no dedupe | old `:142` `priority="P2"` |
| "Fix: the relevant fetcher skipped the canonical watch universe" — false: news ingestion caps at `NEWS_INGEST_MAX=60`; the cloud LLM lanes fund T0/T1 only (`config/hermes_research_budget.yaml` `external_cloud_tiers`) | `scripts/news_ingestion.py:573`; budget yaml |
| Full gap list dumped to the log (5.1 MB) | `logs/enrichment_coverage.log` |
| Root cause upstream: `directive_promotion.py:377` sets the flag for any directive (incl. automated think_tank / sector_universe), nothing clears it | see the flag document |

## What it does now

- **Scope = curated Watch membership** (AGENTS.md §26: the CIO prospect record / curated Watch membership is the one
  watch list). It prefers the `cio_prospect` projection (PR #1944) **only** when it answers from the granted store
  (`source.kind == "store"`); a shadow build is not authoritative. Until then, interim membership:
  `watchlist_items status='active'` + held names through `lib.data_broker.watch_domains.membership_held` (the one held
  reader; holdings.json is no longer read directly — the file left the frozen direct-reader allowlist) + ACTIVE ticker
  directives the operator created (`created_by` in `operator`, `operator_audit`), read through
  `lib.data_broker.watch_intelligence.active_operator_ticker_symbols` (the watch_directives projection owner).
- **Expectations match the funded policy.** technicals + analyst for every member; `news_7d` for held / proposed;
  `llm_curation` for held / proposed / high-rank (T0/T1); `protection_advisory` for held names with technicals; a failed
  latest synthesis. A held / proposed name with **no articles from any source, ever** is counted and is not a gap.
- **Message**: counts first (members, gaps per surface, membership source), then the top 10 by priority (held,
  proposed, operator directive, high-rank, active; more missing surfaces first), then one cause line per surface from
  the lane receipts (e.g. `hermes_top20_external_intel last run FAILED … (OperationalError); last ok …`) and the policy.
- **P3 notification intent** (the digest), sent only when the gap count rises or a new (symbol, surface) gap appears.
  Dedupe state: `data/runtime/audit-enrichment-coverage_state.json`.
- **Log**: a summary only. The full list goes to `data/runtime/audit-enrichment-coverage_manifest.json`, capped at 500.
- **Receipt**: `LaneRunReceipt@v2`, `produced_count` = curated Watch members audited; allowlist `output_receipt: "v2"`.

## Dry run against the live DB `[VERIFIED]` 2026-10-22 ~17:00 ET (read-only session; nothing written)

```
$ python scripts/audit_enrichment_coverage.py --alert --dry-run
DRY RUN: would send P3 alert (36 members with gaps; reason first_run):
ENRICHMENT COVERAGE — curated Watch
36 of 208 members have gaps (technicals 15 · news_7d 14 · llm_curation 6 · protection_advisory 2)
Members: held 20 · proposed 34 · operator directive 45 · high-rank 8 · active 154 (source: interim: watchlist active 156 + held 20 (holdings_accounts.holdings_json) + operator ticker directives 45)
Not a gap: 1 held/proposed name(s) have no articles from any source
Top 10 by priority:
• AMANX [held]: news_7d
• NAVN [held]: protection_advisory
• SRNE [held]: protection_advisory
• MRNA [proposed]: news_7d, llm_curation
…
Why (lane receipts + funded policy):
• technicals (15): technicals-gap-backfill last ok 2026-10-22 20:30 UTC; ticker_snapshot_daily rsi within 3 days
• news_7d (14): news_ingestion --priority covers held + proposals first and caps the run at NEWS_INGEST_MAX=60 symbols
• llm_curation (6): hermes_top20_external_intel last run FAILED 2026-10-22 20:08 UTC (OperationalError); last ok 2026-10-22 18:07 UTC; cloud LLM lanes fund T0/T1 only …
• protection_advisory (2): hermes_research_intelligence protection_advisory within 7 days
DRY RUN: nothing sent; no receipt, state or manifest written
LANE_OUTPUT {"attempted_count": 208, "produced_count": 0, "empty_reason": "dry_run", …}
```

2,201 flagged gaps → 36 members with real, funded gaps. `ls data/runtime | grep audit-enrichment` after the dry run
shows only the 16:45 receipt (unchanged).

## n8n lane — shadow first, then the cron line retires

The lane is already a dispatcher row at `stage: shadow` (`config/lane_registry.json`, dispatch `dry_run`
`45 16 * * 1-5`), allowlisted (`--dry-run`, `live_arg: null`, lock `/tmp/enrich_coverage.lock` shared with the cron
line), with a grandfathered DRAFT contract (updated here: purpose, inputs, outputs, unit, receipt). It reads the DB
only; no broker, no secret. The cron line (crontab line 474, inventory `cron:L472`) keeps doing the real work.

Ladder (AGENTS.md §23.21): shadow dry-run fires (now) → canary PR (owner REVIEWs the contract; allowlist
`live_arg: ["--alert"]`; registry `stage: canary`, `dispatch.mode: live`) → one live n8n RUN_DONE with
`produced_count ≥ 1` → retire the cron line.

**Operator one-liner to retire crontab line 474 — only after the canary's live n8n RUN_DONE** (cron freeze: the
inventory row must be Approved first). Dry run, then apply; the repo's cutover tool backs up the crontab, comments the
line with the `# RETIRED <date> n8n-cutover audit-enrichment-coverage` tag (never deletes) and reads it back:

```bash
S=$(readlink -f ~/trade-ai-releases/portfolio-server/CURRENT); PY=~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
$PY $S/scripts/n8n_cutover_wave.py comment-cron --code-root $S --lanes audit-enrichment-coverage --date $(TZ=America/New_York date +%F)          # dry run
$PY $S/scripts/n8n_cutover_wave.py comment-cron --code-root $S --lanes audit-enrichment-coverage --date $(TZ=America/New_York date +%F) --apply  # after proof
```

The dry run, run 2026-10-22 against served CURRENT `82180caba` (reads `crontab -l`, writes nothing), names exactly
one line:

```
  L474 audit-enrichment-coverage: # RETIRED 2026-10-22 n8n-cutover audit-enrichment-coverage 45 16 * * 1-5 cd $PROJ && flock -n /tmp/enrich_coverage.lock $PY scripts/audit_enrichment_coverage.py
{"apply": false, "backup": null, "read_back_ok": null}
```

Rollback: `python3 scripts/pipelines/cutover/_cutover.py rollback --lane audit-enrichment-coverage --apply`
(uncomments exactly the tagged line). The after-close pipeline step `audit_enrichment_coverage`
(`config/pipelines/after_close.json`) runs the same command and is unchanged.

## Tests

`tests/test_enrichment_coverage_audit_20261022.py` (gate `enrichment_coverage_audit_20261022`) and the updated
`tests/test_refactor_w1_audit_reports_20261010.py`, `tests/test_notification_intents_wave3_20261011.py` (P2 → P3).
