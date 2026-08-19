# Watchlist Lifecycle Remediation — Build & Documentation

**Date:** 2026-08-19
**Follow-up to:** [`WATCHLIST_LIFECYCLE_AUDIT_2026-08-19.md`](WATCHLIST_LIFECYCLE_AUDIT_2026-08-19.md)
**Status:** ✅ LIVE — built, unit-tested, dry-run validated, and applied to production (cron installed, lanes primed)

This document records what was **built** to close the six gaps (A–F) found in the
watchlist audit, and exactly what had to change. It is the implementation counterpart
to the audit — the "what changed / what did you have to do" record requested so we can
fall back if something regresses.

---

## TL;DR

The watchlist lifecycle had six gaps. All six now have code/configuration in place:

| Gap | Problem (root cause) | Fix built |
|-----|----------------------|-----------|
| **A** | Social producers write `social_sentiment_history`, but the scorer/governor read `intelligence_entities.social_score` which is **never written** | New fold bridge `sync_social_to_intelligence.py` |
| **B** | Desk directives land as `STAGED_FOR_REVIEW` (110,612 rows) and are never auto-promoted (no hit-rate calibration) | New `desk_suggestions_digest.py` surface |
| **C** | Watchlist idea-gen was Finviz-only; Hermes/social research never became watchlist ideas | New `research_watchlist_discovery.py` lane |
| **D** | Discovery funnel orphaned (not in cron) + `candidate_discovery_events` empty + `hermes_discovery_candidates` frozen since Jul 5 | Rewired `candidate_discovery_orchestrator.py` + new `drain_discovery_backlog.py` |
| **E** | No `report_source()` liveness or `data_source_remediation` for watchlist research sources | Added source-health seed + remediation config |
| **F** | `ai_discovered` was a catch-all written by 3 scripts with no `origin_system` provenance | Added `origin_system` to all 3 writers |

**Nothing here changes trading execution or source behavior** — it is wiring,
surfacing, monitoring, and provenance only (per the audit's "out of scope" guardrail).

---

## Gap A — Social was dead to the scorer

**Root cause (3-way store mismatch):**
- Producers write `social_sentiment_history.sentiment_score` (`aegis_social_sentiment.py`, `hermes_social_sentiment.py`).
- Scorer + scope governor read `intelligence_entities.social_score` / `social_sentiment` (`hermes_watchlist_scorer.py:135`, `lib/hermes_scope_governor/inputs.py:105`).
- `intelligence_entities.social_score` (numeric) was **never written** — the only social writer was `symbol_enrichment.py` writing a `social_sentiment` string for GO-surfaced symbols only. Live check at audit: 0 of ~8.4k rows had a non-null `social_score`.

**What was built:**
1. `scripts/sync_social_to_intelligence.py` — folds the latest `social_sentiment_history`
   per tracked symbol onto `intelligence_entities` via the single-writer
   `intelligence_entity_manager.upsert_entity()`. Mapping: `sentiment_score` (-1..1) →
   `social_score` (0..100) = `50 + 50*score`; label from polarity thresholds. Only folds
   sentiment within `SOCIAL_FOLD_MAX_AGE_HOURS` (default 168h/7d). Reports
   `report_source("social", ...)` on `--apply`.
2. `migrations/2026-08-19_watchlist_source_health.sql` — seeds the five
   `data_source_health` rows the watchlist lanes report to (`social`, `hermes_social`,
   `research_discovery`, `social_scalp`, `yahoo_movers`) — they were missing, so
   `report_source()` UPDATEs silently no-op'd.

**Verified:** dry-run resolves the 42-symbol universe and reports `0 rows` (correct —
`sentiment_history` is stale since Aug 9 until the producers run again). `_sentiment_to_social`
mapping is unit-tested.

**Still needed (runtime, not code):** cron for the producers/bridge (see Cron section).

---

## Gap B — Desk "curate in" edge never promoted

**Root cause:** `watch_directives_service.py` `_auto_apply` has no hit-rate calibration
(`hr=None`), so `auto_apply_gate` forces `STAGED_FOR_REVIEW` for every desk lead. Live
check: `watch_directive_hits` has **110,612 `STAGED_FOR_REVIEW`** vs 2,033 `PROMOTED`.
Desk sources surface fine (trade_ai 105,292 / hermes 4,999 / reentry 169 / advisory 73 /
defense 67 / cio 12) — they just never promote.

**What was built:**
1. `scripts/desk_suggestions_digest.py` — prints a daily digest of the pending
   `STAGED_FOR_REVIEW` backlog (counts by `surfaced_by` + newest suggestions with reason),
   so the operator sees "here's what the desks want to add/trim" instead of it being
   silently drained.

**Verified:** digest runs against live DB and surfaces real suggestions (e.g.
`advisory:Advisory RE_ENTER (55 conviction): GXAI`, `defense:Defense rotate-in: XLU`).

**Policy decision (resolved 2026-08-19, operator):** enable graduated auto-apply
(`CURATION_AUTO_APPLY=1`). With no calibrated hit-rate yet, `_auto_apply` treats the
missing hit-rate as a floor of `0.65` (bootstrap soak) so qualifying desk leads
(trusted tier + non-divergent) promote through the governor instead of piling up as
`STAGED_FOR_REVIEW`. The flag is injected on the `watch_directives_service.py --apply`
cron line (see Cron section), so it only affects the scheduled service — not ad-hoc runs.
The one-tap manual promote path (`POST /api/v2/watch/directives/promote`) remains.

---

## Gap C — Same-sources research → watchlist ideas

**Root cause:** the watchlist was fed almost exclusively by the Finviz screener;
Hermes forum/web research and social momentum never became watchlist candidates on
their own.

**What was built:**
1. `scripts/research_watchlist_discovery.py` — a first-class research-discovery lane
   that reads the SAME research sources as the day-scalp pipeline
   (`hermes_research_intelligence` = Hermes/SearXNG forum+web; `social_sentiment_history`
   = social) and writes them into `watchlist_items` as **non-trading** research ideas
   (`status='researched'`, `bucket='research_discovery'`, `source_tier='candidate'`).
   It never auto-promotes to the watchpool or any execution rail.

**Verified:** dry-run found 30 Hermes research rows → 15 unique symbols to write (the
other 15 already exist in `watchlist_items`). Social side returned 0 (expected — stale
store until producers run).

---

## Gap D — Discovery funnel was stalled

**Root cause:**
- `candidate_discovery_orchestrator.py` was orphaned (no cron entry since a 2026-07-06
  audit; its Finviz liveness is now owned by `finviz_health_check.py`).
- It only wrote `candidate_discovery_events` in DEGRADED (Finviz-failure) mode, so the
  feed was permanently empty while Finviz was healthy.
- `hermes_discovery_candidates` had 644 `DISCOVERED` + 307 `CLUSTERED` frozen since
  2026-07-05.

**What was built:**
1. Rewrote `scripts/candidate_discovery_orchestrator.py` to poll the existing
   `discovery_sources/` package (finviz, social_scalp, news_catalyst, incubator,
   yahoo_movers, polygon), **always** write `candidate_discovery_events` on `--apply`,
   and `report_source()` per source (finviz skipped — owned by `finviz_health_check.py`;
   polygon skipped when no `POLYGON_API_KEY`). Added a rollback guard so a failed source
   query can't abort the shared connection for the rest.
2. Fixed `scripts/discovery_sources/social_source.py`: it queried `scan_date` on
   `trade_ai_scans`, but the column is `run_date` — this made the source silently fail
   and (with the shared connection) poison later sources.
3. `scripts/drain_discovery_backlog.py` — advances the Hermes inbox conservatively:
   `CLUSTERED` + recent + has `extracted_symbols` → `READY_FOR_REVIEW`; past-TTL →
   `ARCHIVED_COLD`. Operator rows are never touched; every transition writes a
   `hermes_discovery_audit` row.

**Verified:** dry-run polls all 6 sources (social 19 / news 50 / incubator 50 / yahoo 33
candidates; polygon 0 = no key) and reports 100 unique events. Drainer dry-run reports
404 to archive, 0 to promote (correct — the whole backlog is past-TTL).

---

## Gap E — No self-healing for watchlist sources

**Root cause:** the watchlist research sources (`social`, `hermes_social`,
`news_catalyst`, `incubator`, `polygon`) had no `report_source()` markers wired to their
producers, and no `data_source_remediation` entries, so `data_source_stale` findings
couldn't auto-remediate.

**What was built:**
1. `config/health_agent_policy.json` → `data_source_remediation` gained:
   - `social` → `scripts/sync_social_to_intelligence.py --apply`
   - `hermes_social` → `scripts/hermes_social_sentiment.py --apply`
2. `migrations/2026-08-19_watchlist_source_health.sql` seeds the `social` /
   `hermes_social` health rows (see Gap A).
3. The rewired orchestrator now reports liveness for `social_scalp`, `news_catalyst`,
   `incubator`, `yahoo_movers` (see Gap D).

**Verified:** `_data_source_retry_cmd` resolves `social`/`hermes_social` to their new
producers (unit-tested).

---

## Gap F — `ai_discovered` provenance opacity

**Root cause:** `watchlist_items.source='ai_discovered'` was written by **three**
scripts with no `origin_system`/`origin_detail`, so 10k+ active rows were untraceable:
- `finviz_screener_runner.py:316`
- `intel_auto_discovery.py:197`
- `sync_watchlist_items_to_db.py:172` (from `discovery_candidates.json`)

**What was built (additive only — no behavior change):**
1. `finviz_screener_runner.py` → `origin_system='finviz_screener'`.
2. `intel_auto_discovery.py` → `origin_system='intel_auto_discovery'`.
3. `sync_watchlist_items_to_db.py` → `origin_system` mapped from source
   (`ai_discovered`→`discovery_candidates`, `ai_watchlist`→`ai_watchlist`,
   `portfolio`→`portfolio`, `personal_watchlist`→`personal_watchlist`).

**Not done (documented):** historical `ai_discovered` rows remain unattributed — a
one-time backfill would be guesswork and is deferred until provenance is needed for a
specific decision.

---

## Cron wiring — installer + self-heal watchdog

Two new scripts make the cron rollout auditable, idempotent, and self-healing:

1. `scripts/install_watchlist_remediation_cron.py` — idempotent, reversible installer
   (dry-run by default; `--apply` backs up first). It reads the **live** crontab and:
   - adds the six remediation cron lines below (from the single source of truth in
     `job_coverage_monitor.py` `REGISTRY[].cron_line`),
   - injects `CURATION_AUTO_APPLY=1` on the `watch_directives_service.py --apply` line,
   - adds the `cron_self_heal.py --apply` watchdog line.

2. `scripts/cron_self_heal.py` — the "notify + auto-fix + re-enable" mechanism. It
   consumes the same `REGISTRY` and, for the six managed jobs:
   - `NOT_SCHEDULED` → re-add the entry to the live crontab (idempotent),
   - `STALE` → re-run the job's `remediate_cmd` (attempt-capped, 6h cooldown),
   - `NO_SIGNAL`/first-run → notify only,
   - sends a Telegram alert on failure (throttled, routed through the alert router),
   - persists attempt state to `data/runtime/cron_self_heal_state.json`.

The six scheduled entries:

```
# Watchlist research discovery (Gap C) — Hermes/social → watchlist research ideas
0 7 * * 1-5 cd $PROJ && $PY scripts/research_watchlist_discovery.py --apply >> logs/research_watchlist_discovery.log 2>&1

# Social → intelligence fold bridge (Gap A) — runs after the social producers (11:00/15:00)
30 11,15 * * 1-5 cd $PROJ && $PY scripts/sync_social_to_intelligence.py --apply >> logs/sync_social_to_intelligence.log 2>&1

# Hermes social producer (Gap A redundancy)
15 11,15 * * 1-5 cd $PROJ && $PY scripts/hermes_social_sentiment.py --apply >> logs/hermes_social_sentiment.log 2>&1

# Multi-source candidate discovery (Gap D)
15 6 * * 1-5 cd $PROJ && $PY scripts/candidate_discovery_orchestrator.py --apply >> logs/candidate_discovery.log 2>&1

# Hermes discovery backlog drain (Gap D)
0 6 * * 1-5 cd $PROJ && $PY scripts/drain_discovery_backlog.py --apply >> logs/drain_discovery_backlog.log 2>&1

# Desk suggestions digest (Gap B) — morning surface to operator
0 8 * * 1-5 cd $PROJ && $PY scripts/desk_suggestions_digest.py >> logs/desk_suggestions_digest.log 2>&1

# Self-heal watchdog — monitor + notify + re-enable the six jobs above
*/15 6-20 * * 1-5 cd $PROJ && $PY scripts/cron_self_heal.py --apply >> logs/cron_self_heal.log 2>&1
```

The six jobs are also registered in `job_coverage_monitor.py` (`schedule_match`,
`cadence_h=80`, DB/log heartbeat signals), so they appear in the existing job-coverage
report alongside the rest of the estate.

**Watch-the-watchman note:** `cron_self_heal.py` runs *by* cron, so it cannot re-add its
own entry if the whole crontab is wiped — that single recovery still needs the operator
(`scripts/install_watchlist_remediation_cron.py --apply` restores everything idempotently).

---

## Validation performed

- **Unit tests:** `tests/test_watchlist_remediation.py` (9 tests: `_sentiment_to_social`
  mapping + source-aware retry), `tests/test_cron_remediation_installer.py` (8 tests:
  installer `transform()` additive/idempotent/auto-apply-inject, `cron_self_heal`
  `_re_add` dedup + `_expand`). All passed.
- **Regression:** `test_health_agent_data_source_remediation.py`,
  `test_social_scalp_decision_alerts.py`, `test_two_way_curation.py` — full remediation
  suite green (23 tests this change; 77 across the earlier suites).
- **Dry-runs against live DB (read-only):** all six scripts run cleanly
  (`sync_social_to_intelligence`, `candidate_discovery_orchestrator`,
  `drain_discovery_backlog`, `research_watchlist_discovery`, `desk_suggestions_digest`).
- **Installer dry-run:** reports exactly 8 changes (6 jobs + auto-apply + self-heal) and
  is idempotent (re-running shows no re-adds).
- **Self-heal dry-run:** correctly classifies the six jobs as `NOT_SCHEDULED` and would
  re-add them; dry mode provably does not mutate crontab or state.
- **Config validation:** `health_agent_policy.json` parses; `data_source_remediation`
  entries resolve correctly.
- **Schema validation:** all `watchlist_items` columns used by the new scripts exist
  (`bucket`, `origin_system`, `origin_detail`, `source_tier`, `provenance_reason`, etc.);
  `migrations/2026-08-19_watchlist_source_health.sql` seeds the five source-health keys
  (`social`, `hermes_social`, `research_discovery`, `social_scalp`, `yahoo_movers`).

### Applied to production (2026-08-19)

The `--apply` rollout is **complete**:

1. `scripts/install_watchlist_remediation_cron.py --apply` — added the 6 remediation
   jobs + `CURATION_AUTO_APPLY=1` on `watch_directives_service` + the `*/15` self-heal
   watchdog. Backup written to `crontab_backup_pre_watchlist_remediation_20260819_111652.txt`.
2. `migrations/2026-08-19_watchlist_source_health.sql` — seeded the 5 source-health rows.
3. Each lane primed once (`--apply`) and verified:
   - `candidate_discovery_orchestrator` — polled 6 sources, recorded 100 events.
   - `hermes_social_sentiment` — 25 forum hits, 25 sentiment records persisted.
   - `sync_social_to_intelligence` — folded 42 symbols → `intelligence_entities.social_score`.
   - `research_watchlist_discovery` — wrote 42 research ideas.
   - `drain_discovery_backlog` — archived 404 stale candidates.
   - `desk_suggestions_digest` — surfaced the STAGED_FOR_REVIEW backlog.
4. Verified `intelligence_entities.social_score` went **0 → 42 non-null**; all seven
   source-health rows (`social`, `hermes_social`, `research_discovery`, `social_scalp`,
   `yahoo_movers`, `news_catalyst`, `incubator`) report `healthy` with fresh
   `last_success_at`.
5. `job_coverage_monitor.py` reports all 6 new lanes `OK`; `cron_self_heal.py` dry-run
   reports no actions needed (all scheduled).

---

## Git discipline

- Changes are uncommitted on the current branch (same discipline as the day-scalp
  publish). Commit/push requires the operator's `maintree` / `git-push` guard grants.
- No source behavior or execution paths were changed — only wiring, surfacing,
  monitoring, and provenance.
