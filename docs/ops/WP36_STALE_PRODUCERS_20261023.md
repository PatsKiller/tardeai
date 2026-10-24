# WP-36 item5: stale feed and report-producer reconciliation

Status: DRAFT owner-decision inventory; no scheduler or producer changed
as_of: 2026-10-24T03:25:20.281828+00:00
Measured at: source325ff34f2; canonical persistent paths; CURRENT directory d0c8b70d8-main-exact-phase2-20261023-182515
Task: DSN-20261023-handoff-v3-P7-T365

The five report tiles labelled NEVER RUN are not five demonstrated scheduler failures. Canonical file metadata and source paths show a retired producer, a reader-lineage mismatch, two on-event products and one unresolved monthly trigger. All five old catalog patterns currently have zero matches and the cached catalog calls them never-generated. That proves absence at those paths, not that no generator ever executed.

The [10-row inventory](packets/stale-producers-20261023/inventory.csv) records every remaining item, producer, reader, declared trigger, measurement, responsible role, proposed disposition and next action. The [artifact census](packets/stale-producers-20261023/report-artifacts.json) and [feed census](packets/stale-producers-20261023/feed-artifacts.json) contain only path/count/clock metadata. [Verification](packets/stale-producers-20261023/VERIFICATION.json) binds their hashes.

| Report family | Evidence | Proposed next action |
|---|---|---|
| Aegis morning brief | Registry lane aegis-morning-brief-delivery-0805 is RETIRED since2026-09-14; one morning-brief-0730 remains declared ACTIVE. Old report globs are empty. | Retire or relabel the legacy catalog entry; preserve the one-brief decision. Do not restart a duplicate sender. |
| Weekly portfolio review | Old weekly/weekly_* globs are empty;8 weekly artifacts exist under analyst/, newest file mtime2026-10-19T01:00:03Z. generate-weekly-docx is declared ACTIVE and exports there. The catalog's named generate_weekly_portfolio_review prints a DB report rather than saving those files. | Repair the tile's lineage to the existing canonical analyst output; add exact receipt/consumer proof before any scheduler cutover. |
| Monthly portfolio report | Canonical monthly globs empty. Source generator exists; the catalog's day1 controller description has no established direct registry mapping. | Reconcile the parent trigger and governed data/model/health contract before proposing activation. |
| Enterprise report set | No matching artifacts; catalog declares on-event and no maximum age. | Determine whether an authorized generation event occurred. Prefer an explicit optional/not-requested label over an invented periodic failure. |
| Live automation readiness | Expected latest file absent in CURRENT; catalog declares on-event and no maximum age. | Owner decides when to generate this source-readiness report. It is not a live-trading approval. |

| Feed | Evidence | Proposed next action |
|---|---|---|
| agent_debate_log | Historical captured UI clock2026-05-05; agent_opinion declares a no-producer gap, while agent_watchlist_engine contains a gated writer and has an ACTIVE daily registry row. Fresh PostgreSQL counts are NOT_MEASURED. | Owner chooses legacy-view retirement or restored eligible canonical events. Prove source eligibility and correlated runs before declaring the writer absent or reviving it. |
| defense would_have_fired | File generated2026-07-18. sector_momentum_engine writes it only under --backfill; its normal daily lane does not pass that flag. | Label historical hypothetical analysis. Any new backfill cadence is an owner decision, not a missed natural-fire repair. |
| redeploy analytics cache | File mtime2026-09-02; source is an on-read legacy cache and its broker projection already exposes the gap. | Review canonical replacement/retirement. Preserve the original clock; do not invent a background producer. |
| disposition outcomes | Materialized projection updated2026-08-20. Its writer is event/outcome-driven and memory behavior influence remains0. | Compare eligible dispositions with consumption under an authorized state/DB audit. Do not fabricate outcomes or advance MBI. |
| Warrior weekly audit | Latest file mtime2026-10-19T17:30:03Z, within168h at this census. Registry is weekly Monday; generated_at is naive local text. | Keep the weekly population and clarify timezone. A daily age threshold would misclassify it. |

## Boundaries and collection actions

No live API, crontab, timer change, database query, model, provider or sender was executed. Source registry rows are scheduling intent, not a fresh host census. Runtime environment path overrides are NOT_MEASURED. File presence/mtime is not receipt, report-content or consumer acceptance. Historical catalog values are preserved and not promoted into live success evidence.

Fresh scheduler readback requires the operator's cron grant under the freeze; a production SQL census requires approved credential access (the separate WP-29 request was rejected before execution by automatic approval review). The owner reviews each proposed repair/retirement, then a separate implementation claim can change the relevant catalog or admitted workflow with its tests. No source label or decision in this report grants authority.

Validation:10 unique inventory IDs,10 existing producer source paths,5 report families and5 feeds; artifact JSON parsed and hashes recorded; docs index/whitespace/claim checks. Documentation-only change, with no implementation-mirroring tests added.
