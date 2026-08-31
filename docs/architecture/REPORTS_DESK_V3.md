# Reports Desk v3 — One Corpus · The System Rollup · Zero Garbage (2026-07-17)

Status:      ACTIVE
as_of:       2026-07-17T11:25:59-04:00
Measured at: efcc51365 / not measured

Commits `a405b3c3..d552f00f` (one per WS). Builds on the v1 ship (f6b481db..14caffb9 — the
prompt's "v2" baseline; no v2 commits exist, naming drift documented in
`docs/_findings/reports_desk_v3_diagnosis_2026-07-17.md`).

## WS-A — One corpus per panel, filters that filter (a405b3c3)
The 486-vs-18 class of disagreement is structurally impossible: `/api/v2/reports/list` grew
`qv=` (server-side predicates in `reports_portal._qv_match`, ported from the UI) and returns
`qv_counts` computed in the SAME pass over the SAME scoped rows (category+days+q; enrichment
capped at 400 with honest `qv_scanned`). KPI chips read `list.qv_counts` (corpus tag
"· archive — <category> · <window>"); counter reads "N shown · M matching '<qv>' · T total in
scope". portal-summary powers ONLY the Action Queue. Severity headline lives inside the
analytics fold, tagged "· raw events". **Corpus policy** (declared in the diagnosis doc):
alert_events = raw firehose (analytics only) · portal index = operator record (list/chips/
retention) · telegram_outbox+notification_log = delivery ledger (parity only).
**A3**: indexing policy is CONFIG (`config/report_index_policy.json`) served as
`analytics.index_policy`, rendered as the parity-line legend.

## WS-B — The System Rollup + Daily System Digest (bc5117b8)
`/api/v2/reports/system-rollup?window=24h|7d`: pipelines (failure red rail) · agents+conf ·
proposals · paper W/L+P&L · alerts by severity (raw-tagged) · research · reports · directives ·
health strip (REUSES health snapshot + data-source health + consumption overview) · trends.
Per-panel corpus tags, fail-soft, `timings_ms` (all <200ms; contract said snapshot at >1s —
not needed). Reports hub gains the fifth mode tab **System** with 24h/7d toggle, drill links,
sparkline honest-empty (<3 daily snapshots = "no fabricated history").
`system_rollup_daily` (day PK, payload jsonb) + `scripts/system_rollup_snapshot.py` nightly
20:40 cron → snapshot row + deterministic md digest (`system_digest_<date>.md`, catalog family
`system_digest`) + ai_reports row + ONE Telegram line. First run live 2026-07-17: 784 pipeline
runs · 12 failures · 991 agent analyses · 2,680 raw alerts · health 48.

## WS-C — Zero garbage (fcd2f28f)
`research_intelligence_qa_lint.strip_preamble/clean_advisory` — deterministic openers
(curly-apostrophe variants, orphan meta-header lines) + `preamble_leak` lint flag.
`iterate_research_topics` (the leak source; bypassed lint) cleans at WRITE; preamble-only →
"research pending — no substantive findings yet (iter #N)" stub. Backfill: 16/31 stored
advisories cleaned IN PLACE (0 stubs — all had substance behind filler). Brief RESEARCH
ADVISORIES render first substantive sentence w/ display-time strip fallback; research-topics
payload gains `summary_line` + `off_universe` guard disclosure (DJUL/SAGT/CMRC confirmed
off-universe).

## WS-D — Analyst truth pass completed (7177d9cf)
D1: two need-refresh numbers are REAL different scopes, labeled — batch "N of 29 eligible
symbols' reports", strip "N across all 431 covered" (tooltip states the difference).
D2: "Residual positions (N)" fold — sub-$1k holdings (NOC/BAH/LDOS/CACI scraps + SRNE $1)
out of the peer list, still generatable. D3: Generated list shows CURRENT holdings-vocabulary
action for held names; registry verb in tooltip ("registry: IGNORE · <date>") — display only,
registry history untouched. D4: `acked` column REMOVED — no ack write path exists anywhere
(dead affordance).

## WS-E — Taxonomy + polish (d552f00f)
`config/report_producer_registry.json`: source string → logical producer + kind chip
(engine·pipeline·monitor·log); unmapped = red `raw` chip (visible debt). Severity rails on
list rows already shipped via SynthesizedReportCard — confirmed, not repainted.

## Self-scored maturity (per tab, 1-5)
| Tab | Score | One line |
|---|---|---|
| Library | 4.5 | catalog+viewer solid; system_digest family added; DOCX preview still iframe-sibling only |
| Today's Brief | 4 | structured render + clean advisories; regenerate is deterministic-light, not full |
| Analyst | 4.5 | every count labeled+scoped, folds honest; batch generation still operator-paced |
| Archive | 4.5 | one corpus per group, server-side qv, policy legend; per_cat row source caps stated not tunable in UI |
| System | 3.5 | live rollup + digest + trends table shipped; sparklines need ≥3 days of snapshots to prove out |

## Standing gotchas
- `_qv_match` mirrors the UI predicate list — new quick views must be added in reports_portal
  (server), not the component.
- New ROUTES handlers: never register a 1-param non-query handler bare (the trade_ai
  force-collision class, fixed 2b242e47) — the trade-ai route comment is the canonical warning.
- hermes_rank_surge threshold review STILL pending (65% of raw alert volume; aggregates-only
  policy now stated in config, but the volume itself is unreviewed).
