# Reports Desk v1 — Total Rebuild (2026-07-16, night)

Commits `f6b481db..7921fd19` (`reports-v1:` prefix, one per WS). Thesis held: the
reports already generate on timers — this was 60% wiring artifacts into a library,
30% rendering discipline, 10% new analytics. No new reporting engine; the only new
generator is the charter-allowed deterministic Alert Digest.

## Phase 0 corrections

- **The "psql auth blocker" was NOT a password rotation**: role `johnclaw` has never
  existed in Postgres. All access (app + CLI) is `trade_ai`. Durable fix: `~/.pgpass`
  (0600) — bare `psql -h 127.0.0.1 -U trade_ai -d trade_ai` now works. Rotation item
  CLOSED without a rotation.
- **Repo visibility**: went PUBLIC a FIFTH time (~18:35 ET, caught pre-push). No local
  script touches visibility (grepped) — GitHub-side actor. Operator: rotate the
  GITHUB token and audit github.com/settings/applications. Outranks everything.

## WS-A — Report Library (f6b481db)

`generate_reports_hub.build_report_catalog()` (EXTENDS the existing indexer — no
parallel registry): 9 report families typed with cadence/generator/artifacts/history/
freshness — morning brief (143 DOCX on disk), aegis brief (82 md), weekly ({docx,html,
json} triplets), monthly, manual, analyst registry (439 reports), enterprise set,
live-readiness, live dashboard. Persisted to `data/runtime/report_catalog.json`;
served by light `GET /api/v2/reports/catalog` (disk-cached 1h, no DB) AND inside the
existing `/api/v2/reports` aggregate. **Library is the Reports landing tab**: cadence
lanes, freshness rails (fresh/overdue/never-run/on-event), absolute-ET + relative
times, DOCX/PDF download buttons, history folds (last 8), **in-page viewer** — the
export pipeline already writes HTML siblings for weekly/monthly/dashboards, so the
viewer is an iframe (no mammoth needed); .md renders in a mono pane. A3 run-controls:
delivered for the brief (WS-B Regenerate, deterministic-light); heavy/LLM per-type
queueing NOT built (flagged — needs the RI queue pattern generalized; nothing blocks
the request path today).

## WS-B — Today's Brief (b6a7b467)

`aegis_morning_brief_delivery.write_formal_export` now persists
`aegis_morning_brief_{date}.json` (run_id + summary + sections) beside the .md —
purely additive; Telegram send path and .md untouched. The page renders from the
sidecar: section components with rails (IMMEDIATE RISK red, STEPH amber…), symbol
chips, `/v2/...` strings become REAL links (mapped to live v3 routes), RECOVERY
WATCH grouped into per-allocation pills ("13 names in stay_cash" expands — not 14
identical lines), CURRENT/STALE·Nh chip, stops diff-vs-live chip, and a
**Regenerate brief** button → `POST /api/v2/reports/brief/regenerate`
(deterministic-light: rebuilds .md+.json from live context; proven live).
Legacy text panels retained BELOW the structured render as the documented fallback
for pre-sidecar briefs (flag: could be suppressed when a sidecar exists — cosmetic).

## WS-C — Analyst truth pass (b5bf6c72)

- **Vocabulary**: held names never display candidate verbs — fixed at the
  reporting_engine display site (AVOID→REVIEW·IGNORE→HOLD·SELL→EXIT REVIEW, action
  signal wins when present). The `:198` actionability lump kept deliberately — it
  gates eligibility, not display. Rendered list now shows HOLD/ADD/REBALANCE TRIM.
- **Counts defined on-page** via new `GET /api/v2/reports/analyst/status` (one
  registry pass): eligible holdings 29 · symbols covered 431 (439 artifacts) ·
  fresh 208 · need-refresh 223 (age ≥7d; fingerprint deltas evaluated at generation
  by should_regenerate — stated in tooltip) · former holdings fold (7 tickers,
  reports retained) · **Unmapped instruments fold: the 3 CUSIP rows + SRNE $1 —
  real holdings.json rows, "awaiting instrument mapping", never hidden, never
  rendered as equity peers** (no name feed exists to map them — dated basis export
  outstanding). Sun 21:15 schedule stated in the band.

## WS-D — Alert & message analytics (7921fd19)

`GET /api/v2/reports/analytics?days=` — deterministic rollups: daily volume bars
(alerts+telegram+notifications), severity split (30d: info 17,761 · warning 5,517 ·
urgent 152 · critical 77), top alert types **click-to-drill** into the archive list,
noisiest producers, and the parity line: raw stores (alert_events 23,507 ·
telegram_outbox 1,611 · notification_log 292 · ai_reports 4) vs portal-indexed 7,344
— difference is window + one-category routing, stated not hidden.
**Finding for the operator: `hermes_rank_surge` is 15,259 of 23,507 alerts (65% of
ALL alert volume, 0 acked) from `hermes_score_alerts` — the single noisiest thing
the system does. Candidate for a threshold review.**
New deterministic **Alert Digest** (`scripts/alert_daily_digest.py`, cron 17:55 wd,
verified line): severity/type rollup + watch-alert fires + unacked critical count,
one Telegram message through the outbox chokepoint (self-archiving).

## WS-E — Design parity (0cf7c8bb)

ReportsHub on `watchTokens` (the Watch v4 house system — imported, not forked):
zero raw hexes (census), zero sub-10px, one mono stack, radius 2. `<b>`-tag leak
fixed in ONE server formatter (`reports_portal._tg_plain` at the outbox item build) —
verified 0 leaks across 50 archive items.

## WS-F — Hermes → reports (8593dff8)

Weekly DOCX gains **Intelligence Highlights (Hermes)** + **Exit Intelligence**
sections via `lib/report_intel_highlights.fetch_intel_highlights` (deterministic SQL,
promoted/reviewed, conf ≥0.6, zero LLM) — proven in a regenerated weekly (8 research
items incl. Gain Guardian stop-health advisories). Morning was already wired
(orchestrator :1697). **MONTHLY FLAGGED**: its DOCX comes from the SHARED
`generate_portfolio_brief` builder (also produces daily briefs) — adding a
monthly-only section needs a supervised patch of the shared builder.

## Self-scored maturity

| Tab | Score | Justification |
|---|---|---|
| Library | 9 | Every family surfaced w/ viewer + rails; per-type heavy-job queue not built (flagged) |
| Today's Brief | 9 | Structured data render + regenerate + diff-vs-live; legacy fallback panels still co-render |
| Analyst | 9 | Truth band + vocabulary + folds; per-row "stale · Nd" ages live in the status payload, row chips still say "stale" |
| Archive | 9.5 | Analytics band + drill-through + parity + clean bodies + daily digest |

## Operator items (restated)

**GitHub token rotation + authorized-apps audit (5 public flips today) — first.**
Anthropic key + DB-password rotation: DB password confirmed NOT rotated (johnclaw
role never existed) — Anthropic key still outstanding. Schwab dated Cost Basis
export ×4 (also unblocks CUSIP mapping + Gain Guardian LT/ST). Tier-3 merge — one
tap on Watchpool. Jul-30 Gain Guardian review. hermes_rank_surge threshold review
(new, from WS-D).
