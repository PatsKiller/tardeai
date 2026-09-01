# Reports Desk v3 — Phase 0 Diagnosis (2026-07-17)

Status:      HISTORICAL
as_of:       2026-07-17T11:03:10-04:00
Measured at: efcc51365 / not measured

## Version-numbering flag-back (session contract)
No `reports-v2` commits exist. The prompt's "v2" baseline (Library, structured brief, coverage
truth, analytics + parity line) matches the `reports-v1` ship (f6b481db..14caffb9, 2026-07-16)
feature-for-feature — naming drift, not missing work. The 07-17 10:31 ET snapshots are of the
v1 ship live. Proceeding with v3 on that baseline.

## 0.1 The 486-vs-18 bug — three corpora on one screen
- KPI chips ("Open actions 486") ← `/api/v2/reports/portal-summary` → `portal_summary()`
  (reports_portal.py): `_gather_rows(per_cat_cap=300)` — ALL categories, up to 300 rows each,
  N-day window, then `extract_action_items` per row. Corpus: portal-summary sample.
- The LIST ("15 shown · 18 total") ← `/api/v2/reports/list?category=X&page=1&per_page=15` —
  ONE category, paginated. Corpus: per-category archive page.
- Quick-views (`qv`) filter CLIENT-SIDE over the 15 fetched items (`rawItems.filter(qvMatchesItem)`).
- Server-side exact filters already exist on `action_items(classes=, severity=)` ("so quick views
  stay exact regardless of limit") — the UI never adopted them for the list.
Fix shape (A2): `/reports/list` grows `qv=` server-side predicate + returns `qv_counts` computed
in the same pass over the same (category, days, q) scope; chips and list become one query family.

## 0.2 Corpus census (every number → its store)
| Rendered number | Source | Store |
|---|---|---|
| Severity headline (~20,199) | `/api/v2/reports/analytics` (api_v2:1657) | alert_events RAW |
| "7,859 items indexed" / parity line | analytics parity pass | portal index (curated union) |
| Retention chip (660) | reports_portal purge/retention counters | portal index |
| KPI chips (486 open actions etc.) | portal-summary | portal sample (300/cat) |
| List counts (15/18) | /reports/list | per-category archive page |
| acked 0 per type | analytics; `acknowledged_at` read | alert_events (no write path) |

### WS-A corpus policy (declared roles)
| Store | Role | Panels that read it |
|---|---|---|
| alert_events (+telegram_outbox, notification_log, ai_reports raw) | raw firehose | Analytics aggregates, severity headline (INSIDE analytics fold, tagged `raw events`) |
| portal archive index (curated union via reports_portal categories) | operator record | List, quick views, KPI chips, retention |
| telegram_outbox / notification_log (delivery) | outbound ledger | parity line only |

## 0.3 `_reports_hub()` (api_v2:19470) already aggregates
agent analyses 7d + avg confidence (watchlist_agent_results), proposals by status
(paper_trade_proposals), pipeline runs 7d (pipeline_runs), learning hypotheses 30d,
incubator by status — the System rollup can render these TODAY; extend with journal W/L,
alerts by severity (raw-tagged), research counts, catalog runs, directive activity, health strip.

## 0.4 Preamble leak — writer identified
`scripts/iterate_research_topics.py` (`iterate_topics()`): local-LLM "updated advisory" prompt →
`UPDATE user_research_topics` (+ portfolio_intelligence_events) with RAW model output. No QA lint
in the path (the shared lint exists from RI v3.1 but this writer bypasses it) → "Okay, here's your
updated advisory based on the DJUL research iteration #3…" stored verbatim and rendered.

## 0.5 Analyst need-refresh 105 vs 223
Both derive from `reporting_engine.prospectus_needs_refresh`; coverage() sums holdings rows +
watchlist rows (`needs_refresh` at :393-394 = rows + wl_rows) → 223 (all covered universe);
the batch button's 105 = eligible-scope subset (api_v2:1721 /analyst/status registry pass).
Genuinely different scopes → label both (D1), don't collapse.

## 0.6 Registry verbs on held names
Generated list renders the ORIGINAL registry verb; the C2 display-vocabulary fix (v1 WS-C) was
applied at the reporting_engine display site but the ReportsHub Generated list bypasses it.

## 0.7 acked
`acknowledged` is READ everywhere (reports_portal :727-:993 maps lifecycle_state/read) but NO
write path exists in UI or API (only my incident-response SQL updates today). Ornamental →
D4 = remove the dead per-type "acked 0" display (smaller honest option).

## 0.8 psql carryover
`psql -U johnclaw` fails because the role DOES NOT EXIST — v1 finding stands ("psql-johnclaw
myth"): standing practice is `psql -U trade_ai` + ~/.pgpass (installed in v1). Not an auth
regression; nothing to repair. NOT evidence of a completed DB rotation — key rotation for
Anthropic/OpenAI/OpenClaw/Telegram/GH remains OPEN (operator item).
