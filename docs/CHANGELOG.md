# Changelog

## 2026-08-22 — T3 catalyst-only + S7 retention snapshot

MATURITY_IMPACT: `Research cadence T3 14d sweep → catalyst-only, proven by crontab cold-floor commented and TIER_SLA T3 includes deepseek gated by catalyst`. CURRENT pin not promoted.

- S7: `hermes_external_research` DELETE at 180d via daily 17:00 self-tune. Oldest 2026-06-07 (76d). `llm_consumption_log` has **no** rotation. Nothing under 90d. Snapshot `/home/johnclaw/archives/research-corpus-2026-08-22/`.
- 94 thesis.changed cards = 47 symbols × 2 mint batches. STRENGTHENS/WEAKENS/INVALIDATES/CONFIRMS = **0**. Mint artifact.
- T3: add deepseek to lanes; keep catalyst gate; disable cold-floor cron. Projected clock ~312/day vs 545 confirm-run. 50–80 still needs R3.
- R1 post-#457 QCOM prompt: OUTPUT contract is the thesis; INPUT still has no standing `symbol_thesis`, no what-changed, no operator feedback. Temperature 0.3.

## 2026-08-22 — Recover the research we already paid for

MATURITY_IMPACT: `Portfolio mgmt substantive_pct 0/22 → joined mint on disk (projected ~12/19 CURRENT of RESEARCH_REQUIRED), proven by data/cio/held_thesis_coverage_latest.json after --apply-live`. Freeze lifted by operator (payload window invalid). CURRENT pin `5e91225a` **not promoted**.

- S1: columns are TEXT. recommendation p50=230/p90=500/max=4000. No VARCHAR(500). `data_i_doubt` never stored. Parser slices were the loss, not the schema.
- S2: `raw_response TEXT` migrated, 0 historical rows. #449 fallback put 50 raw dumps into `recommendation` (first 2026-08-22 11:05).
- S3: today 545 — (a) join-recoverable **545/545**, (b) raw-in-rec 50, (c) gone **0**. Joined CURRENT 474/545 vs rec-only 111. 30d n=546.
- S4: parser 4000, raw always, ceiling 4096, recommendation IS the thesis. Overlay onto rebuild `$PROJ` still required for crontab.
- S5: mint reads rec+dissent+evidence. Rec-only 2/19 CURRENT; joined 12/19. No grandfather DIV/DIVI/JEPI.
- S6: do not re-call. Re-parse 50 dumps for free.
- S7: retention 180 days.
- R1: QCOM prompt has no `symbol_thesis`, no what-changed, no trend, no operator feedback. Temperature 0.3. Amnesiac re-ask.
- R2: trigger was SLA due. Live crontab now `RESEARCH_SKIP_GATE=1` (code default still 0). Ledger empty until Mon 08:00 ET.
- P4: `thesis.changed` CIO Desk card (`thesis_change_cards.jsonl` + event bus). Telegram still default off.
- R3/R4/G2–G6: not built. T3 14-day SLA is what makes 545/day; 50–80/day needs operator OK to drop it.

## 2026-08-22 — Burn-in is four surfaces or it is not a burn-in

MATURITY_IMPACT: `Reasoning payload-coverage → four-surface emit + change-gated reentry, proven by agent_run_traces.jsonl DecisionPayload@v1 by surface` (watch/holdings/advisory/opportunity no longer structurally zero). Freeze-safe: write-only traces, flag-gated, no decision semantics.

- N1 traced, not inferred. holdings/opportunity: emit **absent**. advisory 09:15: emit present, **dry-run never calls it**. watch_alerts: emit present, crontab flag was 0 and 0 fires 8/21–22. Wired emit + `env AGENT_DECISION_PAYLOAD=1` on those producers. Keep 8/27.
- N2: 8/22 reentry 3175 rows / 25 names = 127 each. **1 action change, 3149 unchanged re-emits (0.03%)**. Now change-or-4h-heartbeat.
- N3: sweep `source_status=DEGRADED_STALE_SOURCE` when CURRENT pin ≠ origin/main. Targeted replace until D4 8/27.
- Q1: rec-only 2 CURRENT / 15 THIN / 2 STUB (NOC, PFLT). No unlabeled 5.
- Q2: post-mint CURRENT 2/22 not 5/22 (existing 3 stay THIN on read). Not 19/19.

## 2026-08-22 — M1 substantiveness gate (THIN ≠ CURRENT)

MATURITY_IMPACT: `Portfolio mgmt coverage+fresh → coverage+fresh+substantive, proven by data/cio/held_thesis_coverage_latest.json substantive_pct` (target ≥70; THIN excluded). Freeze: no live mint, no CURRENT promote, production `max_output_tokens` still 1024.

- Living thesis `CURRENT` is PASS-grade (Q1 survivable). Grade B/C mint as `THIN`.
- Three numbers: `coverage_pct` (THIN counts), `fresh_pct` (age; THIN can be fresh), `substantive_pct` (PASS only). Targets 100 / ≥90 / ≥70. `sla_met` requires all three.
- Projected split of the 19: rec-only **2/19 CURRENT**, joined **12/19 CURRENT**. Existing DIV/DIVI/JEPI re-grade **THIN**. Live `substantive_pct=0.0`.
- Coverage-stall fires on PASS < 70% of held, not row-exists.
- M2 report: stored rec p50=230 because `recommendation[:500]`; tokens_out p50=824; 11.4% at 1024 cap. Sandbox 20 at 4096: raw PASS 100%, joined 90%, rec-only 40%. Propose parser/prompt/4096 — **not applied**.
- M3 Drive sweep (CURRENT overlay): uploaded=26 failed=0 exit 0. Excludes `_archive`, dated dumps, `_findings`, `ui_review`.
- M4: payload v1 8/21=268 (reentry 165, material_scan 102) → 8/22=3500 (reentry 3125, material_scan 375). No producer diff vs #453. Pin `5e91225a` not promoted.

## 2026-08-22 — Session closeout (findings + fixes index)

MATURITY_IMPACT: NONE (docs). Pointer: `docs/ops/SESSION_CLOSEOUT_2026-08-22.md`.
Lane-health overnight section rewritten: timer is US ChatGPT 22:00–06:00 ET (#453), not China-night gemma.

## 2026-08-22 — Research quality sample + thesis-mint dry-run + alarm holes

MATURITY_IMPACT: live metric `data/runtime/research_lane_health.json` `firing` includes `coverage-stall`; systemd lane-health **exit 0** when the check ran. Freeze: staging mint only, no live `cio_theses.jsonl`.

- Q1 sample n=40: median 320 chars, 45% <300, 15% generic, 0% cross-ticker dupes, 27.5% thesis-survivable.
- Q2 dry-run: **19/19** RESEARCH_REQUIRED holdings mintable from disk. Coverage was a join gap.
- Q3: DeepSeek always watched in Telegram; exit 0 on alarm; coverage-stall lane.
- Q4: overnight timer retarget US 22:00–06:00 ET ChatGPT; autonomous-loop refuses gemma when local-LLM off.
- Q5: process call cap 120→600; cold-floor 20→180; dollar cap $0.50 unchanged.

## 2026-08-22 — Telegram P0 card gates (T1/T2)

MATURITY_IMPACT: live metric `data/cio/telegram_p0_suppress.jsonl` count by `rule` (quote_fail, invalidation_contradicts_price). Freeze-safe: **suppression only**, no new feeds/producers. CURRENT not promoted.

- T1: R:R from entry/stop/target (never `0.0:1`); quote-fail withholds proposal; inverted invalidation suppresses IIC.
- T2: transport retries **edit** the original (`idempotency_key`); no markdown→plaintext second send.
- T3–T7 (join, IDs, four-feed split, 30/day) queued after 8/27. `docs/ops/TELEGRAM_FEED_REMEDIATION_2026-08-22.md`.

## 2026-08-22 — Watchlist/research tiers + LLM cadence (confirm-run)

MATURITY_IMPACT: NONE (docs). Live metric n/a. Freeze 8/21–8/27: no CURRENT promote, no flag flips.

- **One** watchlist *research* tier: `T1-WATCH`. Five universe tiers total (T0-HOLD / T0-PROP / T1-WATCH / T2-INCUB / T3-COLD). Reentry READY/NEAR joins T1. Hermes S0–S3 and directive hygiene 1–3 are **not** LLM queues.
- Confirm-run (manual Saturday, ignore standing $0.50 in-process; process cap restored 120 / $0.30): T0-HOLD **22/22**, T0-PROP **30/30**, T1 **331/331** (reentry **25/25**), T2 **141/141** (forced vs production catalyst-only), T3 **20/20** slice not 2537. `hermes_external_research` **$0.168934**.
- Canonical: `docs/ops/RESEARCH_TIER_LLM_CADENCE.md`.

## 2026-08-21 — DecisionPayload landing + Drive silent-shape + post-window cutover plan

MATURITY_IMPACT: measurement. Live metric = `data/cio/agent_run_traces.jsonl`
DecisionPayload@v1 count since pin `cf5768a6` 19:20:47 ET, and
`drive-sync` RAW last-result. No flags, no routing, no new producers.

- **D1** 213 v1 rows all-time. First = 2026-08-21T18:15:38Z (today). Since pin:
  27 (24 reentry + 3 material_scan). Watch/advisory/holdings/opportunity = 0
  (wiring, queued). Watch cron pointed at CURRENT (emit-only diff).
- **D2** Hourly 23:05–23:30Z: **0 uploaded, 1982 unchanged, 1230 FAILED 404s**.
  Rebuild script did not write last-result. Backfilled RAW file; alarm fired
  `zero_uploaded_with_failures:1230`. Next :05 uses CURRENT script (writes JSON).
- **D3** Freeze 8/21–8/27 close. Skip gate 0, influence 0.
- **D4** `docs/ops/CURRENT_CUTOVER_AFTER_2026-08-27.md` — execute after window.

## 2026-08-21 — CURRENT pin + Drive RAW health + bake-off sheet rescue

MATURITY_IMPACT: live metric path `scripts/research_lane_health.py` now includes
`current-pin` (CURRENT scripts/+docs/ vs SOURCE_COMMIT) and `drive-sync` (RAW
`~/.local/state/drive-sync-last-result.json`, fire if no success in 24h or
0-uploaded-with-404s). Operator-blind bake-off sheet rescued off `/tmp`.

- **P0** `docs/ops/LANE_QUALITY_BAKEOFF_OPERATOR_BLIND_2026-08-21.md` (+ keys under
  `docs/ops/bakeoff-2026-08-21/DO_NOT_OPEN_UNTIL_SCORED/`).
- **P1** `a7f30d89` **does** contain #437/#438/#440 (all ancestors). Overlay was
  #441 docs on that pin. Deploy `cio_phase2_exact_main_deploy.sh` now refuses
  HEAD≠origin/main, dirty tree, and pin mismatch; rsyncs full `scripts/`+`docs/`.
- **P2** gemma default-off is **recommendation-only** until the blind sheet is
  scored. Flash is **not** the workhorse until 5-day burn-in (start 19:10 ET
  2026-08-21). Flag `RESEARCH_ALLOW_LOCAL_LLM` stays 0.
- **P3** Drive canonical `docs/` folder `1BMxbxU9c9rF3NBvXVQtVEewdvkifVkwP`.
  Duplicate `1Rb6qcu…` deprecated. gog alias `default` = john@jwwhiting.com.
- **TSLA** `mem_5989433c…` latest-wins **RETRACTED** `p0_adversarial_quarantine_2026-08-21`;
  search does not return it. JSONL keeps historical ACTIVE as audit.
- `RESEARCH_SKIP_GATE` stays 0. `MEMORY_BEHAVIOR_INFLUENCE` stays 0.
- `AGENT_DECISION_PAYLOAD=1` already on producer drop-ins (B.1); 5-trading-day
  window starts after this lands — nothing else flipped with it.

## 2026-08-21 — Research P0–P4 closeout (docs)

Merged #440 (llm_lane import + RAW-store lane health), #437 (22-ticker denominator), #438 (R1–R5 flags default 0), #439 (bake-off). CURRENT `a7f30d89`. Scheduler-path DeepSeek proof id=45900. `$0.42/14d` spend void (crash loop). 27b is CPU, not GPU deep. Overnight *policy* ChatGPT; *live timer* still China-night gemma. `RESEARCH_SKIP_GATE` unset. Influence 0.

## 2026-08-18 — Header STALE badge rebased on journal-rebuild freshness

The TRADING / REALIZED header tiles were flagging `⚠ STALE` because staleness was computed from
`journal.last_close_date` = `MAX(close_date)` — the date of the most recent *closed* position. A quiet
market (no Schwab position closed since Jul 24) was being mislabeled as "stale data" even though the
journal pipeline (`schwab_transaction_ingest` → `schwab_journal_builder`) was running every cycle.

- **`scripts/api_v2.py`**: `/api/v2/overview` now exposes `journal.last_ingested_at`
  (`MAX(created_at)` over `trade_closed` schwab rows = last successful rebuild) and
  `journal.ledger_last_trade_time` (`MAX(trade_time)` over `trade_transactions` `schwab_api` rows).
  `last_close_date` remains as neutral "last close" info.
- **`apps/command-center-v3/src/components/MetricStrip.tsx`**: staleness now keys off
  `last_ingested_at` (>72h → STALE, spans weekends) instead of `last_close_date`. Tile tooltips read
  "last close <date> · journal rebuilt <time>" rather than implying the data is broken.
- **`scripts/health_agent.py` + `config/health_agent_policy.json`**: the parallel `trade_closed_stale`
  check was rebased from `MAX(close_date)` to `MAX(created_at)` (rebuild freshness), threshold 7d → 3d.
- **`tests/test_journal_staleness_semantics.py`**: pins the decoupled contract across API, header, and
  health agent.

## 2026-08-16 — Deep docs/ cleanup (3,436 → 1,779 files; 2.30 GB → 17 MB)

Due-diligence pass over `docs/` to purge "version one/two" snapshots, stale backups, and
troubleshooting screenshots that had accumulated across sessions. No broker/order path, no code
change — documentation only.

- **Stale binary backups (2.13 GB):** `docs/backups/trade_ai_backup_20260619.zip` (2.08 GB),
  `docs/playwright/journal_audit_20260606_1353.tgz`, `docs/ui_review/journal_audit_20260611.tar.gz`.
- **`docs/_archive/` removed (1,232 files, 10 MB):** session 17–43 / phase A/B1 / pre-cloud-rebuild /
  2026-05-24-cleanup snapshots. Recoverable via git history.
- **`.bak_*` DOCX backups (31 files):** duplicate `Trade_AI_v12_Reference_Architecture.docx` snapshots.
- **Troubleshooting screenshots (~94 images, ~30 MB):** `ui_review/`, `_findings/{watch_v4_shots,
  sector_leaders_s1, defense_redesign, inverse_stoplight_screens, options_lifecycle_screens}`,
  `hermes/PHASE206H_v3_hermes_legacy.png`, 2 unreferenced `architecture/v3_*.png`. Referenced
  architecture diagrams and `design/ActiveTrader_Implementation_Pack` graphics were kept.
- **23 dated snapshot dirs (1.2 MB):** `atm_lifecycle_v1_2026_05_*` and the 2026-06-08 monitor/audit
  folders. `atm_audit_2026_05_26/` was kept (canonical, TIER 1).
- **Morning briefs:** kept latest 7 `openclaw_aegis_morning_brief_*.md`, removed 75 older.
- **`DOCS_ROSTER.md` removed:** self-labeled "stale, last full scan 2026-05-26", superseded by
  `DOCUMENTATION_INDEX.md`.

Canonical docs updated to drop the now-removed `docs/_archive/` / `docs/backups/` pointers:
`DOCUMENTATION_INDEX.md`, `A1A.md`, `LIVE_SYSTEM_FACTS.md`, `operations/DOCUMENTATION_STANDARDS.md`.

Note: grok/chatgpt references were left intact — those lanes remain in active production use
(top-20 external curation, subject enhancement, protection advisor, grok stop review per live
crontab). Only the `research_scheduler.py` position-research lane migrated to DeepSeek (already
documented in `RESEARCH_PRIORITIZATION.md`).

## 2026-08-13 — Topic ingest<->curate loop broken + projections surfaced to desk

Root-caused the 8/3 burst: `topic_ingestion.py` auto-spawned `topic_curator.py --improve-queries`
after every run that saved articles, and the curator's "Step 3b" re-ran `topic_ingestion.py`
unconditionally — so a run that kept finding fresh articles looped until the external APIs
throttled (~110 cycles / 2.5h, one "across 1 topics" message every 2-3 min).

- **`topic_ingestion.py`**: added `--no-auto-curate` (skip the post-ingestion curator spawn) and a
  global min-interval re-entry guard (`/tmp/topic_ingestion.interval`, 30s) that skips sub-interval
  re-invocation without blocking legitimate sequential drains (RI queue, iris `--gaps`, reground —
  all run one topic per subprocess at >30s spacing). `--dry-run` is exempt.
- **`topic_curator.py`**: Step 3b now passes `--no-auto-curate` to the re-ingest, capping the chain
  at exactly one curator hop per ingestion.
- **`advisory_desk.py`**: new `_load_ingestion_health` loader surfaces the silenced
  `data/runtime/topic_ingestion_latest.json` / `topic_curator_latest.json` projections as a
  portfolio-level `ingestion_health` evidence item.
- Tests: `tests/test_topic_ingestion_loop_break.py` (5 checks pinning the loop-break + guard).

No broker/order path. Data truth unchanged; only the ingest/curate feedback loop narrowed.

## 2026-08-13 — Topic ingestion/curation count noise routed to desk (no Telegram)

The hourly "Topic Ingestion: N articles + 0 transcripts saved across 1 topics" and
"Topic Curator: N approved, M blocked" messages are non-actionable count spam. The
underlying data (articles/transcripts) already lands in `news_articles` /
`youtube_transcripts` — the canonical desk store the CIO/advisory/analyst lanes read —
so the Telegram text was pure redundancy.

- **`topic_ingestion.py`**: removed the direct `urllib.request` Telegram send (a
  chokepoint bypass). Per-run counts now write `data/runtime/topic_ingestion_latest.json`
  (desk-side projection) instead of texting. Chokepoint baseline re-ratcheted 47→46 files.
- **`topic_curator.py`**: removed the "Topic Curator:" Telegram summary; curation counts
  now write `data/runtime/topic_curator_latest.json`.
- `research_intelligence_queue.py` drain digest (🔬 RI queue drained: ok/failed) retained
  — it is a once-per-drain, actionable summary, not count spam.

No broker/order path. Data truth unchanged; only notification surface narrowed.

## 2026-08-13 — Telegram noise suppression + research lane migrated to governed DeepSeek

Telegram thread audited for non-actionable noise (hourly "ChatGPT research update" per-symbol spam,
near-duplicate entry/stop alerts, pipeline-failure spam). Outcome: raw research prose is suppressed from
Telegram and routed desk-side; only synthesized thesis changes text the operator.

- **Research lane → DeepSeek** (`hermes_external_researcher.py`, `research_scheduler.py`,
  `config/llm_process_registry.json`): the automated external skeptic is now the governed DeepSeek V4 Flash
  lane (`deepseek_only`, FAST policy, daily cap 120 calls / $0.30 via `hermes_external_research` process).
  Free OAuth `grok`/`chatgpt` lanes retained but `auto: False` (no longer auto-dispatched).
- **Raw research-update Telegram suppressed** (`research_scheduler.surface_holding_event`): no longer sends
  per-symbol `📊 ChatGPT research update` messages. It now fingerprints material change (content hash) and
  leaves surfacing to the Advisory Desk `external_research` evidence loader
  (`advisory_desk._load_external_research`, reading `hermes_external_research`).
- **Producers routed through the chokepoint**: `watchlist_entry_planner._alert` (entry alerts) and
  `morning_eval_check.sh` now go through `telegram_alert.send_telegram` / `send_operator_alert.py`;
  `alert_dispatcher_unified` uses the approved low-level `_raw_send_telegram` for pipeline-critical
  (immediate) delivery. Chokepoint baseline re-ratcheted.
- **Thesis change surfaces on Telegram** (`cio_theses.publish` → `_notify_thesis_publish`): a versioned
  CIO thesis publish now emits a concise `thesis_update` notification (classified `ROUTE_IMMEDIATE`,
  1-hr dedupe in `operator_alert_policy_v2`).
- Docs: `docs/RESEARCH_PRIORITIZATION.md` updated (lanes, SLA, event surfacing).

No broker/order path. SHADOW / notify-on-thesis-change only.

## 2026-08-11 — Advisory desk CIO tracks P1–P5 (feature/advisory-desk-v1)

READ_ONLY_ADVISORY desk continuity on `feature/advisory-desk-v1`:

- **P1** dedicated CIO Telegram converse (`cio_telegram_converse`, allowlist bot unit)
- **P2a** situation catalog S1–S8 + plan store; **P2b** plan enrichment under governed LLM cap
- **P3** versioned desk thesis store (`CIOThesisStore`, pins `desk@vN`)
- **P4** WhatsApp mirror channel (Meta Cloud API; shared `cio_converse_core`; flag default off)
- **P5** lightweight wake traces (`cio_wake_traces.jsonl`, `/cio traces`)
- Docs: `docs/cio/THESIS_STORE_P3.md`, `WAKE_TRACES_P5.md`, `P2B_PLAN_ENRICHMENT.md`,
  `CIO_TELEGRAM_CONVERSE_RUNBOOK.md`, `CIO_WHATSAPP_CONVERSE_RUNBOOK.md`;
  index `docs/advisory/desk-v1/README.md`

No broker/order path. SHADOW / notify off by default.

## 2026-08-06 — Defense Desk v10: cross-desk consistency audit, DeepSeek oversight fix, stop re-entry thesis

Cross-desk audit across Watchlist (200 items), Defense (13 stances), Holdings (22 positions),
and Re-Entry (108 rows, 77 stop watches). All data sourced from the **data broker** as canonical
source of truth. **0 hard contradictions** found between desk systems. Four soft conflicts
(SCHD, JEPI, ARKX, XAR flagged TRIM) are legitimate defensive recommendations, not logic errors.

DeepSeek oversight fully repaired across 3 layers: client now returns partial content with
`truncated=True` instead of `ok=False`; `llm_lane` no longer raises on `OUTPUT_TRUNCATED`;
`defense_oversight` increased `max_tokens` from 150 to 4096 and salvages truncated JSON via
`raw_decode` fallback. All "deep sea" / "deep_sea" references renamed to "deepseek".

Sector staleness fixed: `price_db_sync.py` now prices all 11 sector ETFs regardless of
watchlist/portfolio membership; `sector_momentum_engine.py` stamps fresh `as_of` dates.

Stop re-entry watches now accept an optional `thesis_map` parameter so the data broker
can inject thesis text per symbol; symbol-specific triggers appended when a thesis exists.

UI polish: 4 MetricStrip tooltips, 5 SectorLeadersCard column tooltips, sizing policy
column in CashAlternatives, LLM timeline last-run timestamps, actual days-stale display.

Docs: `docs/architecture/DEFENSE_DESK_V10.md`. Cross-desk health monitor designed
(collector for health_agent.py using data broker projections, routing contradictions
through the escalation queue to LLM for repair). 21 files changed, ~2800 additions.

## 2026-07-22 — V5 §17: institutional technical intelligence (canonical service + pattern engine)

technical_intelligence.py canonical multi-TF snapshot in every packet; chart_patterns.py
deterministic pattern engine (fixtures-tested, no lookahead, scale-invariant); shim parity for
obv/cmf/adx/aroon (silent-NEUTRAL removed, capability audit); weighted family confluence with
correlation caps; OB/OS context semantics; max-6 technical pills on the card; /watch/decision/
technicals drawer endpoint. 44 V5 tests green. Advisory-only; no new action authority.

## 2026-07-22 — Watch Decision Desk V5: refresh semantics corrected, tiers, server-owned cadence

Branch `wt/watch-decision-desk-v5` (feature flag `WATCH_DECISION_DESK_V5`, v4 rollback kept).
ROOT CAUSE fixed: card "Refresh Strategy" hit the enrichment endpoint and never rebuilt the
decision packet (CECO proven live). New canonical orchestrator `watch_decision_refresh.py`
(scopes INPUTS_ONLY/AFFECTED_DIMENSIONS/FULL_STRATEGY; tiers LOCAL_QUANT/STANDARD_BLIND/
PREMIUM_REVIEW fail-closed), run/job tables + per-symbol locks + idempotency + sweeper,
policy YAML v5.0.0 + `watch_decision_scheduler.py` (browser sweep retired), Section-8
freshness contract (timestamps in EVERY state incl. stale), deterministic thesis engine
(`deterministic_thesis.py` — factor-based, instrument-aware, misparse-hardened), StrategyRail
(5 families always visible), desk toolbar, bulk Rebuild-Local/Standard-Blind/Premium-Estimate,
legacy plan grid removed when a packet leads, list packet trim + snapshot cache.
Baseline audit: `docs/audits/WATCH_DECISION_DESK_V5_BASELINE_2026-07-22.md`. 19 new tests.
Advisory-only throughout — no order, approval, or 2FA surface touched.

## 2026-07-21 — Alpaca multi-account taxonomy R1–R5

Registry unification (interlock → `broker_accounts` + parity log), credential slots
(`ALPACA_PAPER_*` / `TAXABLE_*` / `IRA_*`), hard identity map to `tradeai_automated`, live
scaffolds `alpaca_taxable_live` / `alpaca_ira_live` DISABLED, TradingView lanes doc + 503 stub.
P0 host-lock on stop/reconcile (`c9f31f6b`). Tip: `4fa3ba33`.
Session: `docs/sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md`.

## 2026-07-21 — Holdings stop-kind pill + P/L-if-fired + trailing-STOP-LIMIT placement

Docs: `docs/STOP_METHODOLOGY.md` (v3.1). Commits: `d251c84b`, `06cc5349`.
Tests: `tests/test_holdings_pl_if_fired.py` (15), `tests/test_stop_kind_taxonomy.py` (13),
`tests/test_stop_kind_pills.py`, `tests/test_trailing_limit_placement.py` (12).

- **Holdings table P/L-if-fired** — each row shows "if fired ±$N", the realized position P/L if the
  current stop executes: `pl$ − shares × (price − stop)` = `(stop − cost) × shares`; live broker stop
  preferred, advisory fallback; null (never 0) when no stop/cost/price; tooltip names the stop source.
- **Holdings stop-kind pill** — colour-coded FIXED / STOP LIMIT / TRAILING / TRAILING LIMIT / MONITORED /
  NO STOP, from the shared `StopKindPill` + `deriveStopKind` (`lib/stopManagement.ts`); the Stop
  Management desk imports the same component — one source of truth, no fork; unknown types → NO STOP.
- **Trailing STOP-LIMIT** — 4th protective placement option (Schwab `TRAILING_STOP_LIMIT`): trail offset
  + limit offset (`limit_offset ≥ trail_pct`, clamped in UI, revalidated in the spec builder). Full path
  through `protective_stop_pilot` / `protective_stop_policy` / `api_v2` / `HoldingProtectionActions`;
  Fidelity/SnapTrade unsupported (advisory/manual). Advisory/preview + per-order 2FA; no order submitted.
- **Primary-card tests reconciled** — `test_primary_card_replacement.py` moved from stale literal-copy
  assertions to semantic operator-contract assertions after the `82415fa6` operator-card refactor
  (band leads, legacy only in audit drawer, READY-only proposal CTA, stale→REFRESH, held→position language).

## 2026-07-21 — Alpaca paper due diligence + trading-env taxonomy

Docs: `docs/brokers/ALPACA_DUE_DILIGENCE_AUDIT_2026-07-21.md`,
`trading-environments.md`, `paper-trading.md`, `alpaca-live-accounts.md` (supersedes `paca-accounts.md` pointer).

- Full-repo inventory of Alpaca/paper; as-is Path A procedures.
- **D1 account keys (later R1–R5):** `tradeai_automated` | `alpaca_taxable_live` | `alpaca_ira_live`
  (`paca_*` naming superseded).
- Gap analysis for live personal/IRA; credential split + factory (implemented R2).

## 2026-07-21 — Operator decision card + RTH few-hour plan refresh

Docs: `docs/architecture/DECISION_PACKET_OPERATOR_CARD_AND_RTH_REFRESH.md` · watchlist: `docs/COMMAND_CENTER_V3_WATCHLIST.md`.  
Commit: `b2fbcd90`.

- **Operator card** — `DecisionPacketBand` + `operatorDecisionCard.ts` replace audit-dense packet UI with one primary state (READY / WAIT / REFRESH / BLOCKED / NO TRADE / MANAGE POSITION), one CTA, mechanics line, Details drawer. No orders / no 2FA.
- **Timestamps** — card shows build clock time (ET), age, and TTL applied; `should_be_stale` forces NEEDS REFRESH.
- **RTH TTL (4h)** — `packet_invalidation.effective_ttl_hours`: US cash Mon–Fri 09:30–16:00 ET uses 4h so star / buy / strong-buy plans re-arm every few trading hours; overnight/weekend 12h. Technicals age gate mirrors RTH (4h) vs off (36h).
- **should_be_stale fix** — action policy no longer hard-defaults `ttl_hours=12` (which blocked RTH); exposes `generated_at`, `packet_age_hours`, `ttl_hours_applied`, `rth`, `should_be_stale`.
- **Technical hash** — material RSI/chg/rvol bands only; enrichment `as_of` churn is not `TECHNICALS_CHANGED`.
- **Shadow batch** — default freshness is RTH-aware (unset `SHADOW_BATCH_FRESH_HOURS`); classifies via full invalidation contract.
- **HELD** — sold names cleared via portfolio membership sync; phantom portfolio source rows no longer invent held.
- **Tests** — invalidation + action-policy RTH cases; operator card contract; Playwright operator-card screenshots.

## 2026-07-19 — Options Lifecycle Desk (v1.0 + v1.1 same day)

Docs: `docs/OPTIONS_LIFECYCLE_DESK.md` · findings: `OPTIONS_LIFECYCLE_DESK_DIAGNOSIS_2026-07-19.md`, `OPTIONS_LIFECYCLE_V1_1_INTEGRATION_AUDIT_2026-07-19.md`.

- **v1.0 (32eeb596..8c56ba66)** — strategy-aware open-position management built ahead of the first position (Phase-0 truth: ZERO open options anywhere). Canonical strategy model (never loose legs, roll ancestry, UNKNOWN stays NULL), versioned policy engine v1.0.0 with harvest/giveback + assignment/expiry review, persistent alert lifecycle, hash-bound 2FA tickets (manual-ticket boundary; Schwab pilot stays disarmed), first-class Lifecycle UI + Defense strip, outcomes ledger (0 rows, no fixtures), 8 fail-closed health checks. STRUCTURALLY COMPLETE / OPERATIONALLY VERIFIED (partial) / OUTCOME VALIDATED: NO.
- **v1.1 (same session)** — single-primary recommendation reducer (precedence, subordinate context), ticket/2FA idempotency (one active ticket per key; challenge generations, revocation), contract-exact quote resolution (48/120/250 strike escalation + expiration verification), basis-resolution workflow (priority chain, operator evidence with mandatory document ref, cumulative roll economics), authoritative journal bridge (one strategy = one trade_instances row; identity strategy_position_id+roll_root_id+account+underlying; events from fill evidence only; v_options_journal), per-ticker stock/options/dividends attribution with machine-checked reconciliation invariant, free-lane exception oversight (advisory-only; paid disabled by default), alert identity + delivery evidence, Drive docs parity checker.


## 2026-07-16 — Morning ops stability (desk reliability + RI overnight)

Findings: `docs/_findings/ops_morning_stability_2026-07-16.md`.

- **Dashboard** — gzip large JSON; concurrency semaphore timeout → 503; health/static bypass; trade_ai never recomputes on GET; atomic cache write; RI feed TTL + single-flight lock; Refresh desk toast/cache-bust.
- **Finviz** — per-screener SAVEPOINT + membership nested savepoint so lock timeout no longer aborts whole pipeline.
- **Telegram scalps** — NEW GO still P0 when Critic DOWNGRADE/BLOCK (text stays in message).
- **RI production** — overnight / after close only (`non_trading_hours_gate`, overnight runner, crontab installer); desk reads remain 24/7.

## 2026-07-16 — Research Intelligence v2.7 (stage trades + cross-theme)

- **Stage Trade** — persistent `ri_staged_ideas.json`; GET/POST stage APIs; incomplete data blocked.
- **Staged Ideas** panel + sidebar on RI desk; toast confirmation; dismiss + links to Trading/Stops.
- **Cross-theme strips** — income↔retirement MAGI, SCHG funding for power/AI, infrastructure cluster.
- **Concentration banner** — SCHG ≥24% or top-3 ≥50% desk-level alert.
- **CTA hierarchy** — Stage first; Propose Trim SCHG; demote Stage on incomplete cards.
- **Docs** — `RESEARCH_INTELLIGENCE_V2_7_STAGING.md`. Feed `2.7`.

## 2026-07-16 — Research Intelligence v2.6 (maturity: transparent conviction + actions)

- **Conviction breakdown** — RSI, RS, valuation, Finnhub analyst, earnings, SMAs, options, liquidity shown as scored components.
- **Data gate** — adds require RSI + relative strength or demote to watchlist / incomplete badge.
- **Analyst** — Finnhub consensus from `stock_intelligence.json` (not broken enrichment Strong Sell stamps).
- **Options** — IV rank + bias from options desk proposals; explicit empty state.
- **Sizing** — $ band, 1% risk budget, cash-aware unfunded caps; funded-add still forced on concentration.
- **Action bar** — trade ticket, watchlist, trading, stop, trim links on cards.
- **Docs** — `RESEARCH_INTELLIGENCE_V2_6_MATURITY.md`. Feed `2.6`.

## 2026-07-15 — Research Intelligence v2.5 (security data + multi-factor sizing)

Closes the “theme + portfolio math only” gap with security-level edge and smarter size math.

- **`research_intelligence_security.py`** — RSI, relative strength vs SCHG, earnings momentum, PE/PEG valuation, liquidity, beta; conviction score A/B/C + why-selected.
- **Multi-factor sizing** — theme room × heat × concentration (incl. top-3>50% ×0.75) × vol × conviction; SCHG≥24% forces funded trim.
- **Ticker selection** — theme adds ranked by conviction; overbought/thin liquidity demoted to watchlist.
- **UI** — conv tier, RSI/RS/PE on ticker chips; why-selected copy.
- **Card template** — standard section list on every advisory payload.
- **Docs** — `RESEARCH_INTELLIGENCE_V2_5_SECURITY_MULTIFACTOR.md`. Feed `2.5`.

## 2026-07-15 — Research Intelligence v2.4 (concentration-aware sizing)

Concentration risk and portfolio heat become **active sizing inputs**, not sidebar labels.

- **Concentration framework** — single-name elevated/caution/high/extreme; book top-3 + score; theme soft max + room.
- **Heat from risk_management.json** — size multipliers; protected %; prefer funded adds when heat ≥ moderate.
- **Sizing engine** — `size_new_position`, `size_held_review`, `funding_sources` with transparent **Why this size**.
- **Roles** — `add_candidate` / `trim_candidate` / `hold_review` / `protect` / `watchlist`.
- **Narrative** — portfolio-aware bull/bear; systematic quality tiers A/B/C.
- **UI** — Concentration & heat rail, theme capacity, sizing reason, conc badges.
- **Docs** — `RESEARCH_INTELLIGENCE_V2_4_CONCENTRATION_SIZING.md`. Feed `version: "2.4"`.

## 2026-07-15 — Research Intelligence v2.3 (consistent portfolio-aware recommendations)

Quality and consistency upgrade so every relevant brief feels advisory-grade.

- **Category-gated advisory** — company/options/thesis stay single-name (no SCHD/JEPI sleeve spam); dividend sleeve only for income-strategy titles; risk shows top protect weights; compounding maps SCHG/growth.
- **Narrative polish** — `_polish_narrative_depth`: strip stubs, ensure bull/bear/takeaways, inject portfolio context when thin; topic monitors use category-aware copy.
- **Quality tiers** — `A` / `B` / `C` on feed items; sort boosts mature advisory briefs.
- **UI** — Tier badges, ticker-rec chips, prominent sizing panel, stronger action strip hierarchy.
- **Version** — feed `2.3`. Docs: `RESEARCH_INTELLIGENCE_V2_3_CONSISTENCY.md`.

## 2026-07-15 — Research Intelligence v2.2 (portfolio-aware tickers & sizing)

Advisory upgrade: briefs now cite **live holdings weights** and suggest specific tickers/sizing with risk caveats.

- **`research_intelligence_portfolio.py`** — aggregate household weights, concentration flags, theme sleeves.
- **Advisory fields** on every item: `investment_implications`, `ticker_recommendations`, `sizing_guidance`, `risk_caveat`, `portfolio_snapshot`.
- **Next step** prefers portfolio-aware CTAs (trim SCHG to fund theme, protect DXCM stop, income sleeve vs IRMAA, etc.).
- **UI** — expanded Recommended next step strip (ticker chips + sizing); Book weights rail.
- **Docs** — `RESEARCH_INTELLIGENCE_V2_2_PORTFOLIO_ADVISORY.md`.

## 2026-07-15 — Research Intelligence v2.1 (narrative quality + editorial UI)

Major UX/content upgrade so the desk reads like financial research, not a DB browser.

- **Narrative layer** — `research_intelligence_narrative.py`: lede, multi-paragraph executive summary, key takeaways, bull/bear, why-it-matters, structured next_action on every feed item (deterministic default; optional local-LLM batch via `research_intelligence_narrative_enrich.py`).
- **UI redesign** — Seeking Alpha / Benzinga–inspired masthead, featured briefing, Article/Cards/Wire views, soft editorial palette, right rail (retirement pillar + freshness), recommended-next-step CTA strip on every card.
- **Actionability** — Primary CTA answers “what should I do?” (Roth plan, position review, refresh, income sleeve, risk).
- **Docs** — `docs/architecture/RESEARCH_INTELLIGENCE_V2_1_NARRATIVE_UI.md`.

## 2026-07-15 — Research Intelligence v2 (freshness, archive, retirement pillar)

Professional intelligence desk upgrade on top of RI v1.

- **Freshness policy** — `config/research_intelligence_freshness.json`: live/fresh/aging/stale/archive tiers, per-category refresh cadence, SLO; UI labels like “Updated 14m ago”.
- **Archive (searchable, never delete)** — Hermes soft-archive via `research_intelligence_refresh.py --archive`; retirement pillar protected; `include_archived=1` search.
- **Retirement module** — `config/research_intelligence_retirement_topics.json` + `research_intelligence_retirement_seed.py` seeds Roth ladder, Golden Window, IRMAA, RMD, SSDI, MAPT, tax-bracket room into `topic_monitor` (`owner=shared`, tight `max_age_days`).
- **Feedback loop** — `research_intelligence_feedback` table; `POST /api/v2/research-intelligence/feedback` (star / thumbs / note).
- **API** — feed filters: freshness, starred, sentiment, include_archived; `GET …/freshness` SLO report; taxonomy returns freshness policy.
- **Content fields** — key_questions, data_gaps, sentiment, source_count, needs_refresh, freshness_tier/label.
- **UI** — cards/list/compact views, richer filters, stale-monitor banner, star/vote, cross-links to Retirement/Hermes/Portfolio.
- **Docs** — `docs/architecture/RESEARCH_INTELLIGENCE_V2.md`.

## 2026-07-15 — Research Intelligence v1 (CC v3 first-class cockpit)

Mature Research Intelligence surface replacing the immature “Research Topics list” as the primary operator cockpit. **Aggregates existing Hermes / auto-research / topic_monitor** — does not reinvent ingestion.

- **Taxonomy** — `config/research_intelligence_taxonomy.json` (9 categories: retirement_tax, dividend_income, sector_thematic, macro_geo, company_ticker, compounding_wealth, risk_regime, catalyst_event, academic_pro + subcategories).
- **Aggregator** — `scripts/lib/research_intelligence.py`: rule + research_type classification, holdings join, priority, source extraction, `build_feed()` with focus-boost sort and **priority lanes from full match set** (Retirement / Dividends / Macro-Sector never empty solely because page-1 is stop-noise).
- **API** — `GET /api/v2/research-intelligence` (filters: category, q, priority, symbol, holdings_only, limit); `GET /api/v2/research-intelligence/taxonomy`.
- **CC v3** — `ResearchIntelligenceHub.tsx`: KPI strip, priority lanes, taxonomy chips, search, high/holdings filters, card grid, DetailDrawer drill; Nav **Research Intel**; `/research` → `/research-intelligence`.
- **Docs** — `docs/architecture/RESEARCH_INTELLIGENCE_V1.md` (taxonomy, architecture, data model, UI, pipeline, integration).

## 2026-07-15 — Transfer-aware performance, Fidelity period fills, daily YTD pin

Rollover / Roth-ladder resilience so mid-year account moves no longer break YTD or blank Fidelity weeks/months.

- **Data model** — `migrations/2026_07_23_position_transfer_history.sql`: `position_transfer_history`, `position_normalization_log`, `position_transfer_notifications`. Holdings rows gain `original_source_account`, `current_account`, `transfer_history[]`, dual share fields, `performance_adjusted` / normalize status notes.
- **Normalize pipeline** — `scripts/lib/position_transfer_normalize.py` + hook via `cost_basis_transfer.process_holdings_change` on every `protected_holdings_write` (Schwab/SnapTrade). Classifies `fidelity_to_schwab` / `traditional_to_roth` / internal; auto basis carry-forward when high confidence; DB audit + stop-impact flags; operator notifications.
- **Performance** — `portfolio_period_quality.py`: household residual YTD (ex-transfers); Fidelity 401k↔rollover **linked economic sleeve** fills missing 1W/1M/3M/6M/1Y; portfolio periods = **Σ account display** (Fidelity no longer dropped from 1W/1M); outlier snap filter (e.g. partial 2026-07-14 wipe); **daily YTD pin** `data/portfolios/state/ytd_daily_pin.json` (first compute freezes ≈ market; `YTD_PIN_FORCE=1` to recompute).
- **API** — `GET /api/v2/holdings/transfer-history`, `transfer-notifications`, `POST …/dismiss`, `POST …/transfer-detect`; holdings payload includes transfer provenance fields.
- **CC v3** — Returns panel account matrix + transfer notes/notifications; holdings provenance chip; position detail transfer history; look-through allocation/sector normalize and PARTIAL stop coverage UX from the same release window.
- **History rebuild** — `portfolio_performance_history.py` includes `fidelity_rollover_ira` + linked 401k snapshot anchors.
- **Docs** — `docs/features/transfer-aware-performance.md`.
- **Tests** — `tests/test_position_transfer_normalize.py` (+ existing cost-basis transfer tests).

## 2026-07-14 — Dynamic stop policy: volatility/regime tiers, advisory surfaces, drawer controls

Nine-commit release (da36bf72…2f63d77d), advisory-only throughout — swing-low anchoring, family
floors, per-order 2FA, Fidelity manual and Alpaca paper paths all untouched (test-enforced).

- **`config/stop_policy.yaml`** (NEW, operator-editable, mtime hot-reload, fail-soft to legacy
  bands): tiers vol_low 5–8%/trail 6–8 (trail only ≥+20% gains), vol_medium 8–11/9–11, vol_high
  9–13/10–13 + the five asset-type tiers + legacy families unchanged; `volatility_classification`
  (beta/ATR%/yield/defensive+high-vol sectors — NO hardcoded symbols; `symbol_tier_overrides`
  emptied); `regime_adjustments` (risk-on: vol_high trail cap +1 only; risk-off: all caps −1;
  stale snapshot → neutral); `lifecycle_modifiers` (watch −1 / trim −2); `conviction_modifiers`
  (stock <$10k −1); `portfolio_drawdown_guard` (90d peak, warn ≥10% / critical ≥12%, dedup 6h).
- **Engine** — `holding_family.py`: `classify_volatility_tier()`, `volatility_tier()` (state file →
  live enrichment cache; the cache's `volatility_w_pct` is a misparsed Finviz column and is
  deliberately unused), `current_regime()` (10-min cache, fail-closed to neutral),
  `protection_bounds(lifecycle_stage=, regime=, position_value_usd=, is_stock=)` with full
  adjustment provenance. `volatility_tier_refresh.py` cron 06:45 → `symbol_volatility_tiers` DB
  table + `volatility_tiers_latest.json`, chained with the migration-report regen.
- **Advisor batch** rerun across the book: 23/25 stoppable holdings advised under the new tiers
  (SPCX no daily bars; SPAXX/AMANX funds excluded by design). Sanity gate flagged 4 gemma3:4b
  arithmetic claims (NOC/BAH/LDOS/CACI) — advisories carry the warnings.
- **CC v3** — color-coded VOL badges on Holdings table/cards/drawers; three-line comparison
  ("Current live stop / Advisory: Widen to|Tighten to|Set A–B% (tier + regime) / Minimum floor")
  as badge tooltip AND on-screen drawer panel; drawer cells CURRENT LIVE BROKER STOP vs ADVISORY
  RECOMMENDATION; buttons Apply Fixed/Advisory Trailing/Stop-Limit (2FA) + Keep Current Stop;
  operator-editable stop/limit/trail order parameters (blank = advisory; out-of-band warning;
  UI previously never sent `limit_price` although the backend supported it since Stage 2c);
  Stop Management → Policy sub-tab (ranked band divergences; deliberately no mass-update control).
- **Endpoints** — `GET /api/v2/portfolio/stop-policy-migration` (disk-read of the report state
  file); `POST /api/v2/holdings/protective-stop/keep` (audit-only `stop_decisions` KEEP_CURRENT).
- **Hermes/rotation** — rotation candidate evidence surfaces `stop_tier`/`volatility_tier`
  (display only, scoring untouched).
- **Migration** — `stop_policy_migration_report.py` + `docs/audits/STOP_POLICY_MIGRATION_2026-07-14.txt`:
  10 live stops sit TIGHTER than their new tier floor (largest: SCHG ~$237k at 5.7% vs 9% min) —
  each widening is an individual operator 2FA/manual action.
- **Tests** — `tests/test_stop_policy.py`: 28 gates incl. band values, resolution order, regime
  math, no-hardcoded-pins, no-bulk-UI, L3-hybrid-stays-OFF, no-broker-imports, fail-soft fallbacks.
- Playwright-verified throughout (badges, Policy panel, drawer params, 13/13 final sweep).

## 2026-07-14 — Redeploy oversight-adjudication corrective (10 blocking findings closed)

Corrective release against the operator oversight adjudication (verdict needs_review, 10 blocking
findings). All rerun requirements executed; **Plan F (staged implementation of the Plan B
destination) subsequently PASSED both oversight lanes on the version-bound v31 snapshot and is
legitimately OPERATOR-READY.**

- **OVR-P0-DEPLOY-NOW-DOUBLE-COUNT** — UI no longer sums executable + staged-limit valuations of
  the same legs ($211k on $107k proceeds); reconciliation line reads financials fields verbatim.
- **OVR-P0-TARGET-VS-CURRENT-ACTION** — four distinct capital fields everywhere (header, DECISION,
  comparison, Plan Lab): ULTIMATE TARGET / IMPLEMENT NOW (stage-1) / PENDING STAGES / UNCOMMITTED
  CASH (+reserve, residual); "DEPLOY NOW" label eliminated.
- **OVR-P0-CAPITAL-POOL-OVERCLAIM** — account capital-reservation ledger in the Capital Book
  (visible cash − locked − selected − implemented = allocatable; locked→selected→oldest-first
  allocation; per-row capital_status; rollover IRA honestly shows **OVERCLAIMED $53,159** with
  event #144 `awaiting_capital` + red banners).
- **OVR-P0-OVERLAP-FALSE-NEGATIVE** — same-ticker overlap detected from holdings.json at leg build
  (XLI flag now feeds the diversification score); LOOK-THROUGH renders the three separated tables
  (underlying economic issuers wrapper-free; legacy table only as labeled fallback).
- **OVR-P0-INCOME-DELTA-BASELINE** — plan income + vs-post-sale + vs-pre-sale with stated baselines
  on every surface.
- **OVR-P1-DESTINATION-CADENCE-CONFLATION** — two-axis model: destination (A–E/G) × implementation
  policy (immediate/staged/hold). Plan F is now built AFTER scoring as the staged implementation of
  the top eligible destination (currently Plan B) — same securities, staged cadence, ultimate target
  + tranche triggers displayed.
- **OVR-P1-SECTOR-OVERSHOOT** — Plan B uses a greedy tracking-error minimizer (dollar-for-dollar
  across ALL removed sectors, largest first): capped restoration 68%→**84.6%**, over-restoration
  →**$0**, tracking error $70.8k→**$16.4k**; restoration shows gross/capped/over/unrestored/tracking.
- **OVR-P1-CONCENTRATION** — hard caps at construction (single equity/BDC 15%, single ETF 45%);
  Plan C rebuilt diversified (HTGC 15/JEPQ 45/CSWC 15/ARCC 15/JEPI 10); violators excluded from
  primary with stated reasons.
- **OVR-P1-PACKET-VERSION-STALE** — `scripts/redeploy_operator_packet.py` regenerates the packet
  BOUND to the exact plan version (`FCNTX_144_DECISION_PACKET_v31…` + _LATEST pointer); stale
  unversioned packet removed; oversight prompt carries the plan version + full accounting block.
- **OVR-DATA-STALE-QUOTE** — XLC + all leg symbols refreshed pre-regeneration.
- **Tie policy** — score gap < 2.0 ⇒ NO DECISIVE WINNER banner + documented risk-off staged
  tie-breaker (weights frozen pre-generation; decision_1.1.0). Current outcome is decisive
  (F 73.6 vs B 61.1) without needing the tie-breaker.
- **Reserve honesty** — reserves modeled as explicit executable BIL positions (shares/quote/ER,
  RESERVE REQUIRES PURCHASE pill); yield credited only on the modeled position; no-quote ⇒ plain
  cash with zero yield credit.
- **Live readiness** — /deploy/plans recomputes readiness from CURRENT oversight status (a verdict
  landing after snapshot persistence flips readiness without a regeneration that would reset it).
- Tests: capital-ledger suite added; full redeploy + stop suites green (92).

## 2026-07-14 — Redeploy semantic-integrity release (23-defect corrective, decision workstation)

Full corrective release against the operator sign-off review (defect map:
`docs/audits/REDEPLOY_DEFECT_MAP_2026-07-14.md`; decision packet:
`docs/audits/FCNTX_144_DECISION_PACKET_2026-07-14.md`).

- **Exact accounting (P0-2/3)** — every plan carries `financials`: legs + reserve + whole-share
  residual = deployable, asserted at generation AND re-cut after Phase-C quote refresh
  (`refresh_plan_snapshot`); residual is displayed, never dropped; each amount labels its meaning
  (strategic target / executable at quote / staged limits / modeled). Cross-tab: Plan Lab, Performance,
  Pro Forma, PM Memo and the recommendation all quote the SAME snapshot (verified identical A–G).
- **Governed readiness (P0-1)** — `redeploy_decision.readiness_state`: majors are never
  operator-ready with oversight pending → "ANALYTICS READY — OVERSIGHT PENDING"; distinct
  SYSTEM PRIMARY / OPERATOR SELECTED / OPERATOR LOCKED / HIGHEST QUANT RANK chips.
- **Per-plan export freshness (P0-4)** — `assess_export_readiness(plan_archetype=…)`; Plan B's stale
  XLC can no longer block a Plan F export.
- **State-aware narratives (P0-5)** — objectives/risks derive from settlement + regime; all
  settlement language regenerates away once verified (Plan F: "Stage exposure because the current
  regime is risk-off…").
- **Audit lineage (P0-6)** — `redeploy_audit_log` (migration `2026_07_21`) + writers on plan-version
  generation / oversight / lock / export + event-144 backfill (25 rows; unprovable moments labeled
  `INFERRED_FROM_CURRENT_STATE`); AUDIT tab renders lineage, empty = red governance warning.
- **Whole-plan analytics (P1-7/8/9)** — invested-sleeve vs whole-plan blocks (75%-reserve plan shows
  ~1.6% whole-plan, not the sleeve's 6.7%); canonical income model `redeploy_income.income_snapshot`
  (FCNTX: trailing 4.27% KNOWN with capital-gain note — never "unknown" beside a number).
- **Scenario honesty (P1-10/11)** — ±1σ rows relabeled STATISTICAL_BAND ("NOT a forecast");
  reserve-only coverage renders UNAVAILABLE FOR RISKY LEGS, never 0%.
- **Honest archetypes (P1-12/13/14/16)** — A = "Strategic redesign"; B = "Partial multi-sector
  restoration (top N of M)" with per-sector restoration; E gap-capped
  (min(gap, 20%/leg, 30% sleeve): ITA $21.3k + XLE $2.9k vs the prior $53k/$53k); F states its
  ultimate target + tranche triggers; G holds a named reserve vehicle (BIL 3.85%, revisit date,
  opportunity-cost reference); every leg carries a role.
- **Candidate-driven selection (P1-15/18/19/20)** — plans select per ROLE from the validated universe
  with visible competition (method, score, margin, alternatives + why-lost; e.g. AGG beat BND/TLT/SHY);
  security master rejects prose tokens (FORUM/WOULD/UNI → INVALID_SYMBOL); exclusions classified
  (HISTORY_NOT_LOADED/PROVIDER_FAILED/GAPPED/INSUFFICIENT…); auto-backfill loaded MSFT/VIG/DGRO+22 more;
  implausible short-series yields (ARKQ "23%") excluded from income roles by plausibility guards.
- **Decision engine (Phases 5/6)** — transparent 10-dimension scorecard (visible, versioned,
  operator-configurable weights in `config/redeploy_decision_weights.yaml`), plain-language
  recommendation (primary + choose-when alternatives + do-not-choose), structured 18-section PM memo
  (no raw JSON anywhere).
- **Decision UI (Phases 13/16/17)** — new DECISION tab (default landing per event) + persistent
  decision header (lean, selection, readiness, deploy/reserve, income Δ, next action); comparison
  preloads primary+A+C+F; ENTRIES reorganized (IMPLEMENT NOW / WAIT FOR STAGE 2-3 / RESERVE /
  BLOCKERS / CURRENT ACTION); oversight prompt now includes the exact accounting block.
- **Tests** — +25 `test_redeploy_semantic_integrity.py`; full suite 97 green.
- Oversight lanes ran live: Grok passed B/F; ChatGPT lane returns needs_review → plans honestly stay
  OVERSIGHT PENDING (operator adjudication is the next action; the gate is working as required).

## 2026-07-14 — Redeploy 404 link + poisoned-connection self-heal

- **404 on `/redeploy?...`** — `RedeployPanel.openModal` navigated without the `/v3` base path
  (operator hit it live). Fixed to `/v3/redeploy?...`; `portfolio_server` now also 302s bare
  `/redeploy` → `/v3/redeploy` (query preserved) so previously shared links keep working.
  Regression tests: base-path scan of EVERY in-app `window.location` navigation + server-redirect
  assertion (`test_redeploy_phase13_ui.py`, 9 tests).
- **Panel showed "0 open" despite 4 open events** — one server worker thread's shared DB connection
  was poisoned ("current transaction is aborted…": an earlier swallowed error, never rolled back),
  so every request landing on that thread failed while curl on other threads succeeded.
  `db_adapter._get_conn()` now self-heals: a handed-out connection in `TRANSACTION_STATUS_INERROR`
  is rolled back before reuse. Verified: panel lists 4 events, OPEN → workstation, 69 tests green.

## 2026-07-14 — Redeploy Phase-13 completion: scenarios, candidates, comparison tab, quote-freshness chain

- **Scenario engine** (`redeploy_performance.py` 1.1.0) — 10-scenario plan-level matrix (bull/base/bear
  1Y forecast bands, −20% equity-drawdown and −25% tech-selloff deterministic models, 2022 rate/inflation
  + 2020 recession + 2022 geopolitical historical observations, regime-transition model), each row typed
  FORECAST / DETERMINISTIC_MODEL / HISTORICAL_OBSERVATION with dollar-coverage %; unavailable ≠ zero.
  New `geopolitical_2022` stress window in `redeploy_price_history`. Rendered in PERFORMANCE tab.
- **Candidate universe** (`redeploy_candidate_research.py` 1.1.0) — +tradable mutual-fund roster
  (SWPPX/SWTSX/SWAGX/FXAIX/FZROX, 5Y history backfilled), observed 30-day catalysts from
  `catalyst_events` per candidate (forward calendar honestly "unavailable"), geopolitical sensitivity
  from the deploy-intelligence sleeve map. Universe 130→144.
- **UI** — PLANS split into **PLAN LAB** + dedicated **PLAN COMPARISON** tab (12 tabs; deployment/reserve/
  legs/income/readiness/stale-legs/principal advantage-compromise-risk rows; `?tab=PLANS` deep-links alias).
- **Quote-freshness chain fixed end-to-end** (was: plans NEVER operator-ready):
  1. `_parse_snapshot_ts` assumed UTC for local-time stamps → every quote age overstated by 4h;
  2. `load_technicals` now overlays the repricer's live `market_quotes` price when the morning
     technical snapshot is stale — REFRESH QUOTES + RECOMPUTE actually refreshes;
  3. capital book judged staleness across ALL historical plan versions (superseded v1 legs kept fresh
     v20 flagged stale forever) → latest-version scope; `plan_count` = latest-version archetypes;
  4. per-plan readiness — one stale leg in another archetype no longer gates every plan.
  Verified: FCNTX plans OPERATOR-READY with 14m quotes; XLC refreshed via `external_market_data_ingest`.
- **Tests** — `test_redeploy_phase13.py` (18) + `test_redeploy_phase13_ui.py` (7): duplicate-event
  prevention, settlement reconciliation, decomposition≈100% with explicit residual, unknown≠zero,
  whole-share/residual arithmetic, look-through/issuer overlap, income/fee honesty, stale-export gate,
  versioning, lock concurrency, zero fixtures in production, **no broker-execution path** in any redeploy
  lib or the workstation UI. Suite: 51 redeploy tests green.
- **Visual matrix** — `scripts/redeploy_visual_matrix.py`: 1440/1680/1920/2560 widths × zoom 125/150/200,
  asserting no horizontal overflow + non-blank; 22/22 pass; captures under `artifacts/` (ephemeral policy).
- **Policy migration** — `docs/ui_redesign/screenshots/redeploy_workstation/` removed from Git (1.9 MB);
  all captures now live under gitignored `artifacts/playwright/redeploy/`.

## 2026-07-14 — Redeploy institutional rebuild merged + fixture cleanup executed + deployed

- **Merged** (operator-approved, in order): #142 P0 data-integrity guards → #148 docs truth (reopen of
  #143) → #144 capital-allocation book → #145 candidate/pro-forma/performance engines → #146 full-page
  `/redeploy` workstation → #147 Phase-0 cleanup + ephemeral artifact policy. Stack branches deleted.
- **Fixture cleanup EXECUTED** (operator-approved): `redeploy_fixture_cleanup_2026_07_13.sql` — all 5
  pre-verification counts matched; 3 JEPQ fixture fills, 3 monitor snapshots, 5 audit rows, 3 pending
  Hermes ledger rows, 2 oversight runs deleted; event #144 unlocked (`open`, no locked plan, `phase_e`
  metadata stripped); plan 8 lock/oversight reset. Outcome bus verified clean (0 JEPQ rows).
- **Deployed**: migrations `2026_07_19`/`2026_07_20` applied; cc-v3 rebuilt; full server restart —
  killed the orphaned Jul-13 `portfolio_server` that held :7777 and had the systemd unit in a
  **56,329-restart crash-loop**; unit now active/running and serving the new routes.
- **Cron installed**: `install_deploy_redeploy_cron.sh` — detect 10:10 / recompute 10:15 / monitor
  10:20 ET, trading days.
- **Plans**: manual `deploy_recompute --apply` built A–G plan sets for all 8 material open events
  (FCNTX #144, V #114/#124, HPE #128, PFE #115, SMCI #134, ARKG #138, ARKQ #142).
- **Tests**: 26/26 redeploy suites green (capital book, analytics, Phase-E guards, UI tokens).

## 2026-07-14 — Schwab stop replace hardened (verified cancel-then-place) + stop badge truth

### Protective-stop replace — no path can double-stop

- **`scripts/schwab_transport.py`** — `cancel_order_for_replace()` + `verify_order_canceled()`: the old stop's cancel is now **verified at the broker** (polled to a terminal state or gone from open orders) before the new stop is submitted; unverifiable cancel ⇒ `NotProvenWrite: replace_cancel_incomplete`, new stop NOT placed. Cancel-then-place moved **inside `place_order`** (single gate for web confirm + Telegram auto-fire; no double-DELETE). Duplicate-SELL-stop guard now blocks when the replace target is **still live** instead of skipping it. Repeat DELETE after a successful cancel treated as idempotent (broker truth re-checked). Read-back `REJECTED` ⇒ pilot row `rejected_by_broker` + structured error (no silent "submitted").
- **`scripts/brokers/intent_submit_router.py`** — shared `cancel_replace_stop_if_needed()` (Fidelity monitored-stop replace path); Schwab replace cancel deferred to the transport gate.
- **`scripts/telegram_callback_handler.py`** — `bkapprove` surfaces `modify_cancel` blocks ("Replace blocked — old stop not canceled").
- **`scripts/open_trades_intelligence.py`** — broker-stop payload stamps **`pilot_placed`** from `schwab_pilot_orders` so only app-placed orders are replaceable in-app.
- **`scripts/portfolio_server.py`** — api_v2 hot-reload also reloads the pilot submit stack (`intent_submit_router`, `schwab_transport`, `protective_stop_pilot`).
- **UI (`HoldingProtectionActions.tsx`, `PositionDecisionCard[V4].tsx`)** — `replace_order_id` sent only for `pilot_placed` orders and resolved from the freshest preflight live-stop snap; submission + preview use the **floor-reconciled advisory stop** (`logic.advisoryStop`, SCHD case) not raw `pr.stop_price`; Telegram-approval polling flips the card to "LIVE stop … approved via Telegram" without re-typing the ticker; after-hours ack checkbox removed (backend readiness still gates); `closed` session renders warn not block; trailing-upgrade button now runs preflight first.
- **`holdingsRowModel.ts`** — stop badge tracks stop-management truth first: `KEEP_EXISTING_STOP` ⇒ stable/concern (by stop distance), never "Action" purely because LLM health/signal says TRIM.
- **Tests** — `tests/test_stop_replace_flow.py` (verified cancel before replace submit, single router path, live-target guard), `tests/test_schd_advised_order_params.py` (floor-reconciled fixed stop + suggested trail pct parity), `test_stop_management_endpoint.py` marker updated.
- **Docs** — `docs/brokers/stop-management-architecture.md` §5 Modify + components map updated.

### Hermes — vehicle_auctions research domain

- **`config/hermes_research_domains.yaml`** — new `vehicle_auctions` domain (NYC DOF auction research: title brands, salvage/total-loss, NMVTIS/VIN history, comparable sales). `risk_level: operational`, promotion paths `research_topic`/`escalation_candidate`, **operator-gated, advisory only** — never authoritative pricing or title status.

### Replay integrity

- `docs/audits/REPLAY_INTEGRITY_2026-07-11.{md,json}` + `REPLAY_INTEGRITY_LATEST.*` refreshed by the scheduled replay audit.

## 2026-07-13 — Redeploy Desk REOPENED: P0 fixture audit + documentation truth

- **P0 audit** — `docs/audits/REDEPLOY_FIXTURE_AUDIT_2026-07-13.md`: Phase E test suite
  committed 3 synthetic JEPQ fills to production event #144 (false \$3,246 / 3% restoration);
  8 contaminated locations incl. a test plan-lock and 3 pending Hermes ledger rows.
- **Guards** — migration `2026_07_19_redeploy_data_integrity.sql` (`environment` column,
  fixture quarantine, content-level unique fill index, `broker_confirmation_id`);
  `record_stage_fill` rejects fixture markers/test env/duplicate content; `list_fills`
  production-only; polluting test replaced by rollback-only guard tests.
- **Gated cleanup (NOT executed)** — `scripts/maintenance/redeploy_fixture_cleanup_2026_07_13.sql`
  + outcome-bus cleaner; requires operator approval.
- **Documentation truth** — design doc gained §0 implementation-truth matrix; desk status
  corrected from "complete institutional desk" / "Phase A in progress" (both wrong) to
  **REOPENED**: Phase A–E infrastructure real, analytics + full-page UI rebuild in progress.
  Index + runbook resynced; Drive resync of both docs.


## 2026-07-13 — Fidelity GTC stops audit (••5199)

- **`config/fidelity_rollover_stops.json`** — synced all 8 open GTC stops from Fidelity Activity & Orders (Jul 13): added **QCOM** trail 7% @$174.79 (55 sh); refreshed **ANET** trigger to $178.03, **DXCM** to $71.06; `_fidelity_as_of` → 2026-07-13.
- **`scripts/lib/fidelity_stop_sync.py`** — fallback defaults aligned with config.
- **Tests** — `tests/test_fidelity_stop_sync.py` (8 symbols incl. QCOM).

## 2026-07-13 — Price history backfill, report grounding, proposal parity, escalation 4b

### `ticker_prices` backfill (watchlist + proposals)

- **`scripts/price_db_sync.py`** — `ensure_price_history()` syncs `market_quotes` → `ticker_prices` and yfinance gap-fills symbols short on history; daily job now covers Hermes top-250 **and** active proposal symbols.
- **`scripts/backfill_ticker_prices.py`** — one-shot backfill (`--hermes-top`, `--rated`, `--proposals`, `--symbols`).
- **`scripts/watchlist_enrichment_sweep.py`** — after each enrich batch, persists quotes into `ticker_prices`.
- **`POST /api/v2/watchlist/<SYM>/refresh`** — runs `ensure_price_history` before strategy-card materialize.
- **Proposals** — same path in `proposal_enrichment_loop.py`, `paper-proposals/refresh-data`, `broker-proposals/refresh-prices` (+ batch), `broker_proposal_curator.py`, `remediate_proposal_trade_plans.py`.
- **Tests** — `tests/test_price_db_sync_backfill.py`

### Weekly / monthly report action grounding (OAuth)

- **`scripts/portfolio_report_llm.py`** — held-position table, OAuth via `llm_lane`, `sanitize_action_text()` blocks unheld tickers and >20% price drift (fixes TSLA @ $195 class hallucinations).
- **`portfolio_weekly_report.py` / `portfolio_monthly_report.py`** — all narrative sections OAuth; Telegram send re-validates action before dispatch.
- **`scripts/remediate_weekly_report_action.py`** — patch saved weekly JSON/HTML + optional correction Telegram.
- **`linux_launchers/run_portfolio_weekly.sh`** — log string updated (no longer "Ollama qwen3:14b").
- **Tests** — `tests/test_portfolio_report_llm.py`

### Social awareness lane (Trading Hub)

- **`scripts/lib/social_awareness.py`** — `SOCIAL_AWARENESS` status, catalyst builder; social-only `trade_ai_scans` rows tagged in API + CC v3 (teal **AWARE** pill, filter, catalyst ST badge).
- **`premarket_watcher.py`** — catalyst on persist; never GO without Finviz enrichment.
- **Tests** — `tests/test_social_awareness.py`, `scannerSelection.test.ts`

### Scalp Telegram alerts — country + source badge

- **`scripts/lib/scalp_alert_format.py`** — shared formatter (country flag/name, source badge like Command Center).
- Wired in `continuous_runner.py`, `social_scalp_scanner.py`; **Tests** — `tests/test_scalp_alert_format.py`

### Escalation handler — Tier 3b reliability

- **`claude_escalation_handler.py`** — market hours / batch ≥2 / high load → **gemma3:4b** (not 12b); longer timeout; automatic 4b fallback on 12b failure. Output remains **advisory** (logged + Telegram; Tier 1 retry_cmd unchanged).

## 2026-07-11 (late night 2) — Manual exit review: hard stop vs trailing + stop context

- **Review tab** — Exit type picker + exit signal chips (stop loss hit, trailing stop, etc.); stop management context panel from `manual_broker_stops` / confirmations.
- **Save** — modal stays open for corrections; `auto_confirm_enriched_tags: false` until operator saves.
- **API** — `stop_context_for_trade` on `GET /api/v2/journal/review/<key>`.

## 2026-07-11 (late night) — Tagging queue: save clears trade (AI critique optional)

- **`score_trade_tags`** — `ai_critique` / `ai_critique_stale` no longer block queue completeness; surfaced as optional `critique_gaps` only.
- **Review save** — re-score after marking critique stale; operator save always sets `tagging_complete` when signed off.
- **Tagging Queue UI** — shows purple optional critique chips; "Tags complete" when only critique is outstanding.

## 2026-07-11 (night) — Journal auto-enrich + CC v3 terminal (always on)

### TradeInView — auto-tag, backfill, confirm

- **`tagging_queue_auto_enrich`** — one-pass enrich: setup (AI heuristic), psychology (Calm),
  **industry** (`symbol_profiles`), **market regime at entry + exit dates**
  (`market_regime_snapshots` → journal labels), auto-confirm when complete.
- **API** — `POST /api/v2/journal/tagging-queue/auto-enrich`; CSV import triggers enrich after Schwab rebuild.
- **CLI** — `scripts/journal_trade_in_view.py --auto-enrich --days 365`
- **Policy** — `config/trade_in_view_tagging_policy.json`: `auto_confirm_enriched_tags`,
  `queue_requires_ai_critique: false` (critique is separate “Generate AI critiques” flow).
- **CC v3 Tagging Queue** — auto-enrich on tab open (once/session); cards show `Regime: Entry → Exit`.
- **Tests** — `tests/test_journal_auto_tag.py`

### Command Center v3 — Bloomberg terminal (no toggle)

- Terminal UI **always on** — removed Metric strip Terminal ON/OFF, Portfolio layout toggle, CVD toggle, Options Novice toggle.
- Terminal chrome on all hubs; card v4 only (Open Trades, Watchlist, Proposals).
- Archive fallback: `apps/command-center-v3/_archive/terminal-redesign-20260711/RESTORE.md`

### Cost basis transfer (cross-account)

- **`scripts/lib/cost_basis_transfer.py`** — detect Fidelity→Schwab (etc.) moves, write overrides, tag destinations.
- Hook in `schwab_position_sync.py`; CLI `scripts/cost_basis_transfer_detect.py`; tests `tests/test_cost_basis_transfer.py`

## 2026-07-11 — Fidelity GTC stop registry audit (••5199)

- **config/fidelity_rollover_stops.json** — reconciled to Fidelity Activity & Orders 2026-07-11 11:00 ET:
  CSCO $115, ANET trail 6% @$176.37, SCHG trail 6% @$32.60, DXCM trail 6% @$71.04,
  ARKX $31.06, XAR $263.03, DIVI $40.58 (was stale: SCHG 8%/$31.43, ANET 9%, DXCM fixed).
- Applied via `fidelity_stop_sync --apply` → `manual_broker_stops` + `stop_confirmations`.
- Holdings terminal: Fidelity trailing stops show `Keep trail 6% → $32.60` when GTC is in sync.

## 2026-07-11 (late2) — Holdings stop imperative copy (→ target)

- Stop column shows **what to adjust to**, e.g. `Tighten stop → $32.43` with `Live $35.00 now → $32.43` context.
- Uses canonical `buildStopLogic` decisions (place / tighten / keep) — not passive distance-only text.
- Column header: **Stop → target**; action labels aligned (Create Ticket, Replace Stop, Tighten Stop).

## 2026-07-11 (late) — Holdings stop clarity + action → stop drawer

- **Stop column** — removed ambiguous bare `6.4%`; now reads `Stop $32.43 · 6.4% below price` (not portfolio %).
- **Wt % column** — renamed from `% Port`; tooltips clarify total-portfolio weight vs stop distance.
- **Action buttons** — open drawer scrolled to **Stop management · SYMBOL · account** with 2FA/ticket controls.
- **Drawer** — stop block moved above evidence; amber highlight when opened via action.

## 2026-07-11 (eve) — Holdings Terminal + Cards UX polish

- **Globe icon fix** — portfolio feed omits HQ country; default US flag for domestic tickers (ADR overrides unchanged).
- **Taller terminal rows** (46px) with tooltips on every column, row, and action button.
- **Actionable items** — amber left border, `▸` prefix, solid amber buttons, footer count of rows needing action.
- **Cards (legacy)** — new `HoldingsCard` component: Bloomberg palette, country flag, stop pill, primary action button, opens side drawer.

## 2026-07-11 (pm) — Holdings Terminal Bloomberg color alignment

- **Palette** — `#0f172a` rows, `#ffb000`/`#ffa028` amber, `#22c55e` up, `#ef4444` down, `#94a3b8` labels.
- **Semantic colors** — green/red (or blue/red in CVD) for P&L and today's change only; amber for actions.
- **Stop column** — left border + tinted background; green stable / amber concern / red action.
- **Row hover** — subtle amber tint (Bloomberg selection pattern).
- **CVD toggle** — Terminal layout: `CVD on/off` persists in localStorage (`cc-v3-holdings-cvd`).

## 2026-07-11 — Portfolio Holdings Terminal view (v2, approved)

- **Holdings Terminal** — Bloomberg-inspired single-row table (default): symbol, account, value/P&L,
  % port, price/cost, stop status, primary action, report icons, agent badges.
- **HoldingsSideDrawer** — progressive disclosure: full stop controls (2FA, Fidelity ticket),
  evidence, analyst, news; row click or amber action button opens drawer.
- **Cards (legacy)** — prior tall card grid retained via Layout toggle; preference in localStorage.

## 2026-07-10 (eve) — Hermes Research Backlog UX fix

- **Win rate display** — backlog topics stored decimal WR as `0.167%`; UI now shows **16.7%**;
  librarian loop writes `WR={pct:.1f}%` and includes strategy id in topic.
- **Default filter: Active** — hides 2500+ archived dupes; tabs Active / Staged / Archived / All.
- **API** — `GET /api/v2/hermes/research-backlog?status=active|staged|archived|all` (default active).

## 2026-07-10 — Ross/Warrior TradeAI alignment + CC v3 scanner polish

### Trade AI awareness lanes (P0–P6)

- **MANUAL_REVIEW lanes** — squeeze, high-RVOL runner, micro-float, low-price spike, top-gainer awareness,
  catalyst exception; persist via `scan_persist_extra.py` + `migrate_awareness_fields.py`.
- **Universe injects** — Finviz top-30 gainers (`universe_coverage.py`), ticker aliases (`ticker_alias.py`),
  Ross catalog symbols (`ross_catalog_universe.py`).
- **Finviz snapshot reliability** — `finviz_snapshot.py` for audit + volume backfill on scanner rows.
- **Warrior audit** — `warrior_tradeai_audit.py`, `warrior_weekly_audit_cron.py`,
  `GET /api/v2/warrior-audit/latest`, Ross Alignment Audit strip on Trade AI tab.
- **Cron** — Mon 8:30 AM ET via `linux_port/launchers/run_warrior_weekly_audit.sh`
  (`crontab_warrior_audit_proposal.txt`).
- **Backfill** — `scripts/backfill_scan_awareness.py` for historical scan rows.

### Command Center v3 — Trade AI scanner UX

- **Default filter: Actionable** (GO + WAIT + Manual) — replaces noisy 1522-row Universe default.
- **Consolidated Manual tab** — Squeeze / Runner / Micro / Low under one filter.
- **Sort dropdown** — Awareness (default), Score, RVOL, Change %, Symbol A–Z; copy lists use same sort.
- **LOW pill** — yellow low-price MANUAL_REVIEW lane.
- **Vol column** — today's share volume from Finviz scan.
- **`CountryFlag`** — PNG flag images + country-name tooltip (fixes Linux emoji→two-letter rendering).

### Docs synced

- `docs/WARRIOR_ROSS_TRADEAI_ALIGNMENT.md` (new)
- `ARCHITECTURE.md`, `OPERATIONS.md`, `docs/DAILY_OPS_LOG.md`

## 2026-07-09 (late) - Weekly Learning tab clarity

- **`/api/v2/weekly-learning`** — full tier counts (realtime/overnight/weekly); week rollups
  (`paper_trade_id=0`) separated from per-trade reviews; JSON `weekly_summary` unwrapped;
  phantom-exit flag; agent trend from calibration windows (not stale `agent_performance`).
- **CC v3 Weekly Learning** — week rollup section, phantom badges, tier legend.

## 2026-07-09 (late) - Scalp agents show GO/WAIT/AVOID on roster

- **`/api/v2/agents/summary`** — `social_scalp` and `scalp_critic` now map
  `scalp_scan_results` decisions (GO/WAIT/AVOID) instead of hardcoded 0/0/0 buy/sell/hold.
- **CC v3 Roster** — scalp rows display **51 / 362 / 1959** (GO/AVOID/WAIT) with tooltip.

## 2026-07-09 (late) - Agent Performance tab removed; calibration is canonical

- **CC v3 Agents → Performance tab removed** — duplicate of Calibration after wiring
  `/api/v2/agent-performance` to live `agent_calibration_windows`. Accuracy lives on **Calibration** only.
- **`/api/v2/agent-performance`** — still returns calibration windows (v2 CIO dashboard / integrations).
- **`scripts/lib/agent_performance_api.py`** — mapping helper + tests.

## 2026-07-09 (eve) - Maria OAuth priority tier (~30–80 calls/day)

### Watchlist agent worker

- **Maria-only OAuth routing** — Replaced fleet-wide `_prefer_cloud_narrative()` (priority ≤2) with
  `_prefer_maria_oauth()` scoped to portfolio holdings, top-3 `WAIT` setups (48h), and manual refresh
  jobs. Steph/Risk/tail research remain on local gemma.
- **Daily cap** — `watchlist_maria_priority` process in `llm_process_registry.json` (automated, 80/day
  soft cap) with consumption logged via `gate_and_generate` / `llm_consumption_log`.
- **Helpers** — `scripts/lib/maria_oauth_priority.py`; `llm_consumption.calls_today()` /
  `over_daily_cap()`; registry seeds `daily_soft_cap`.

### Tests / docs

- `tests/test_maria_oauth_priority.py`
- `docs/AGENT_AND_HERMES_WORKFLOWS.md` — Maria OAuth tier note.

## 2026-07-09 (pm) - Agent input hygiene, confidence normalization, defense_thesis remediation

### LLM input curation & agent fleet

- **Symbol gate** — `process_watchlist_agent_jobs.py` now calls `gate_watchlist_symbol()` (reuses
  `hermes_discovery/symbol_validation.py`) before any LLM call. Rejects non-ticker shapes (e.g.
  `543354104`), denylist tokens, and unknown symbols not in `symbol_profiles`. Portfolio-held tickers
  in `holdings.json` pass shape check even if profile sync lags.
- **Confidence normalization** — `normalize_agent_confidence()` in `cio_agent_contract.py` maps 0–1 /
  0–100 scales and drops poisoned values (>100). Applied at parse, `/api/v2/agents/summary` SQL,
  peer-note prompt lines, OAuth synthesis `_rec_from()`, and CC v3 `AgentsHub` `fmtPct`.
- **Root cause (Steph 2053%)** — one `watchlist_agent_results` row stored income-scale garbage as
  confidence; API avg now excludes outliers.

### Broker proposals — defense_thesis sleeve

- **`broker_strategy_resolver.py`** — watchlist sleeves (`defense_thesis`, `income`, …) map to
  executable YAML strategies (`defense_thesis` → `swing_breakout`) before live route; classification
  no longer returns allocation-policy sleeves as trade strategies.
- **`remediate_proposal_trade_plans.py`** — applies sleeve→YAML reconcile + authoritative levels;
  cleared active **LHX** / **RTX** queue items (LDOS #1832 already REJECTED).

### Tests

- `test_watchlist_symbol_gate.py`, `test_normalize_agent_confidence_scale_and_poison`,
  `test_defense_thesis_sleeve_maps_to_executable_strategy`.

### Docs synced

- `docs/AGENT_AND_HERMES_WORKFLOWS.md` — LLM prompt layers + symbol gate.
- `docs/BROKER_PROPOSALS_UI.md` — sleeve reconciliation note.
- `docs/project/project_openclaw.md` — Maria Telegram exec model + CC mirror commands.

## 2026-07-09 - Telegram noise reduction, momentum GO delivery, Maria portfolio fix

### Trade AI — alert routing + data quality (committed here)

- **Momentum scalp GO delivery** — `continuous_runner` `Trade AI LIVE` + `NEW GO` messages were classified
  `P2_DASHBOARD_ONLY` (archived to Reports, never Telegram). `telegram_alert_router.py` now carves out
  `NEW GO` before the generic LIVE sink when score ≥ `scalp_realtime_min_score` and Critic is not
  BLOCK/DOWNGRADE. Policy: `scalp_realtime_min_score` 18 (was 25), `max_trade_ai_live_alerts_per_hour` 10
  (was 3).
- **ATM expiry dedup** — parallel ATM cycles each sent their own expiry Telegram batch for the same symbols
  (DOC, BLZE, AGNC). `atm_auto_approver._telegram_expiry_batch()` suppresses per-symbol repeats for 24h;
  uses `send_telegram` instead of raw `_telegram_both`.
- **Finviz DATA QUALITY noise** — pre-market Finviz exports `Rel Volume = 0` while `Volume` + `Avg Volume`
  are populated, tripping the all-zero gate 3× in 7 minutes. `finviz_ingestion.py` backfills
  `relative_volume = volume / avg_volume` when missing; 1-hour Telegram cooldown per distinct issue key.
  `TRADE AI DATA QUALITY ALERT` → `P2_DASHBOARD_ONLY` in the router.
- **Tests** — `test_finviz_rvol_backfill.py`, `test_atm_expiry_telegram_dedup.py`; router expectations
  updated in `test_telegram_alert_router_jun25.py`.

### OpenClaw — Maria Telegram portfolio (local `~/.openclaw/`, not in this repo)

Documented in `docs/project/project_openclaw.md`:

- Telegram DMs now **bind to Maria** (not `main`); `main` had leaked garbled `gpt-5.4` tool syntax on
  portfolio questions.
- Maria model chain: **`claude-cli/claude-sonnet-4-6` primary** (exec/tools); Grok/ChatGPT OAuth for
  `tradeai-watchlist ask` chat only — OAuth lanes do not run shell tools reliably.
- `tradeai-readonly` skill: new `portfolio-today` / `today` / `movers` composite; holdings API unwrap fix
  (`data.holdings` dict); `SKILL.md` + Maria `SOUL.md` synced.

### Command Center v3 (same release)

- Watchlist + Trading Hub: HQ country flag column via `lib/country.ts` (`resolveCountry`, ADR-aware).

## 2026-07-07 - Proxy graph, Journal by-ticker, pullback widget + quote-refresh deadlock fixes

Four independent PRs off `main` (proxy on the existing proxy branch), all advisory/review-only, no
trading-path changes:

- **Private-company proxy GRAPH (PR #127)** — discovery no longer stops at the operator-seeded ticker.
  `hermes_private_proxy_research.py` now maps the FULL public-proxy graph for a private target
  (direct/strategic/CVC investors, convertible/preferred, cloud/chip suppliers, customers, comparables,
  ETFs), each scored (confidence/materiality/dilution/disclosure + live market cap + optionability),
  RANKED (direct exposure > materiality-vs-mktcap > disclosure > catalyst > liquidity > options >
  dilution) and bucketed (best direct / materiality / options / lower-risk equity / too-diluted-watch /
  rejected). Multi-proxy scanner, `GET /api/v2/proxy/targets` returns the ranked graph + bucket picks,
  `PrivateProxyCard` graph view. Citations required per proxy; unknown stakes labeled, never fabricated.
  See `docs/PRIVATE_COMPANY_PROXY.md`. LLM lanes (Grok/ChatGPT) were 502-flapping at build; `_llm()`
  retries across lanes; live Anthropic population lands on lane recovery / the research cron.
- **Journal per-ticker view (PR #130)** — new **By Ticker** tab (the Journal aggregated by day /
  strategy / account but never by symbol). `GET /api/v2/journal/by-ticker[?symbol=&from=&to=&account=]`
  → per-symbol realized rollup over `trade_closed` (#trades, win rate, total/avg P&L, avg hold,
  best/worst, profit factor), account + date-range filterable; `?symbol=` adds per-strategy/per-account
  splits + individual trades. Component `tradeinview/ByTickerPanel.tsx`.
- **Pullback/MACD widget over-count fix (PR #128)** — the "Pullback / MACD triggers" widget counted any
  trigger with a `proposal_id`, incl. EXPIRED/REJECTED, so it drifted above the filtered list ("3 in
  queue but 0 shown"). `_pullback_macd_candidates` now LEFT JOINs the proposal and returns
  `proposal_live` matching the list's status gate; widget counts only live, badges stale as
  expired/rejected. See `docs/PULLBACK_MACD_SCREENER.md`.
- **proactive_quote_refresh nested-flock deadlock (PR #129)** — every cron tick recorded the pipeline
  FAILED (`errors:[]`, 0 rows) and the quote refresh never ran: the cron wraps the script in
  `flock -n /tmp/tradeai_quote_refresh.lock` and the script re-locked the SAME file, so the inner
  `flock -n` always exited 1 and the Python never executed. Fix: distinct inner lock
  `/tmp/tradeai_quote_refresh_run.lock`. Gotcha: never `flock` a lock inside a script the cron already
  `flock`s on the same file (latent in other `run_scheduled_*.sh`, but their cron lines are commented).

### Known issue surfaced (not yet fixed)
- **Schwab token: health lies about revocation.** `schwab_token_manager.health()` reports
  `refresh_valid: true` off the 7-day TTL even when Schwab has REVOKED the refresh token (rotating-token
  reuse-detection race). Ground truth is the authlib `invalid_grant` on refresh. A revoked token has no
  programmatic recovery (GATE A) — needs one manual `reauth-url` → `exchange-code`. Health should mark
  degraded on the actual `invalid_grant`, not just the TTL date, so ingest gaps alert instead of silently
  dropping a day. (Broke overnight 2026-07-06 15:40 → revoked; ingest stalled at 2026-07-06 data.)

## 2026-07-07 - Options paper position lifecycle monitor + Open Options tab

Stacked PRs (core → alerts → API/UI → cron) for Alpaca paper options after fill:

- **Registry** — `options_monitored_positions` + snapshots (`migrations/2026_07_07_options_monitored_positions.sql`);
  hybrid ingest from Alpaca reconcile; orphan legs → ERROR row.
- **Monitor** — `scripts/options_paper_position_monitor.py` + `config/options_paper_monitor.yaml`: Schwab-chain
  marks, advisory P/L labels, strategy rules for all desk strategies, `DATA_STALE` on quote failure.
- **Alerts** — UI + Telegram on by default (`paper_position_alerts.py`); P0 router for fill/close/orphan.
- **API** — `GET /api/v2/options/paper-positions`, `/paper-positions/alerts`, `POST .../alerts/ack`,
  `GET /api/v2/options/open-positions` (unified broker + monitored legs).
- **UI** — Options hub tab **Open Options**; `OptionPositionCardV4` route + **NO LIVE PATH** safety badge.
- **Cron** — `bash scripts/install_options_paper_monitor_cron.sh` (market-hours monitor hook, hourly reconcile,
  17:10 after-hours snapshot); `run_options_monitor.py` lifecycle hook; job coverage entries.
- **Card semantics polish** — paper blocked rows: **NO LIVE PATH** (not generic BLOCKED), **Review Paper Guards**
  action; true desk blocks keep **BLOCKED**; `safety_status_badge` on proposals + open positions.
- **Cron install fix** — job-lines-only block, `crontab -T` validation, file-based install (fixes `bad hour` parse).

## 2026-07-05 - Options desk card semantics + v4 cards live

Options Desk UI safety pass (presentation-only — no broker execution path changes):

- **Debit/credit labeling** — `card_semantics.py` / `optionsCardSemantics.ts`: deep ITM, protective puts,
  ATM long premium show Total debit (neutral styling); income strategies keep Total credit (green).
- **Blocked action gating** — blocked / Aegis BLOCK / enterprise blocks hide Sell/Buy verbs; show
  View Chain, Review Block Reason, Rerun Review, Pass. Manual log hidden on blocked and paper rows.
- **Route vs data source** — Schwab chain badge separate from execution route (Fidelity manual,
  Schwab 2FA, Alpaca paper, Paper model). Fidelity rows never show Schwab live-path copy.
- **PRIME bands** — &lt;50 NOT PRIME, 50–64 PAPER WATCH, 65–79 PRIME FOR PAPER, ≥80 LIVE REVIEW
  ELIGIBLE · OPERATOR ONLY (score 63 no longer renders bare "PRIME").
- **Liquidity warnings** — OI=0 illiquid banner + display edge cap; collapsed and expanded card views.
- **Alpaca paper copy** — two-step Mark Ready → Submit 1-Contract Paper Limit Order; simulated-order disclosure.
- **Card v4 live** — `readCardsV4()` locked true; Options hub always renders `OptionProposalCardV4` /
  `OptionPositionCardV4`; Watch hub shows "Card v4 · live" badge (v3 toggle removed).
- **Tests** — `test_options_card_semantics.py`, `test_options_action_gating.py` (35 new tests green).

## 2026-07-05 - Hermes maturity hardening (measurable self-learning, advisory-only)

Closed-loop maturity lift (~5.8 → ~7.1 self-learning score) without increasing live-trading authority.

- **Daily Learning Scorecard** — `scripts/hermes_learning_scorecard.py` → `data/runtime/hermes_learning_scorecard.json`;
  `GET /api/v2/hermes/learning-scorecard`; Command Center Closed Loop **Learning Scorecard** panel (signals, promotions/demotions,
  research usefulness, operator accept/reject, FP/FN proxies, threshold proposal counts, maturity by subsystem).
- **Evidence gates** — every threshold proposal carries `sample_size`, `lookback_days`, `regime_count`, `confidence`,
  `minimum_required_sample`, `allowed_action`, `blocked_reason`; insufficient sample blocks “learned” status
  (`config/hermes_thresholds.yaml` → `evidence_gates`).
- **Counterfactual evidence** — top help/hurt examples, estimated FP/FN/coverage/resource/outcome-yield impact per proposal.
- **Do-no-harm regression** — `scripts/hermes_threshold_evaluator.py` + `hermes_do_no_harm_report.json` after eval cycles;
  recommends revert when hit rate, efficiency, scope churn, or alert volume degrades.
- **Symbol journey** — extended `GET /api/v2/hermes/symbol-journey` (conviction, research rows, threshold effects,
  latest recommendation, `advisory_only`).
- **Governance** — `lib/hermes_thresholds/governance.py` hard-blocks broker writes, OCO, stops, 2FA, liquidation;
  scope budget / strategy config require operator approval; auto-apply only inside declared rails with gates pass.
- **Tests** — `tests/test_hermes_maturity_hardening.py` (35 related tests pass). No Schwab/Fidelity execution gates changed.

## 2026-07-04 - Schwab protective-stop canary hardening (PR #33 maturity)

Canonical after-hours policy reconciled across runbook + code: default `READY_FOR_OPERATOR_NEXT_REGULAR_SESSION`;
`READY_FOR_OPERATOR_AFTER_HOURS_GTC` only with `SCHWAB_AFTER_HOURS_STOP_OVERRIDE=1` + operator ack + all standard
gates. Per-account arming: `schwab_pilot_arm.py --arm` now arms **only** `schwab_rollover_ira` by default;
`schwab_roth_ira` stays `api_write_enabled=FALSE` unless deliberately armed via `--accounts`. One-V-canary
discipline + lifecycle states (`protective_stop_canary.py`) + broker read-back result recording.
`broad_stop_placement_blocked` until `SUCCESS_READBACK_CONFIRMED`. UI shows CANARY TARGET, account armed status,
lifecycle, and explicit disabled reasons. OCO off; Fidelity manual-only; no broker request sent during tests.

## 2026-06-30 - Live broker stops (60s) + fixed/trailing validation + last-reviewed tooltips

Portfolio and Open Trades now show **current** Schwab protective-stop state with explicit review timestamps.

- **`GET /api/v2/holdings/live-stops`** (`_holdings_live_stops`): read-only live Schwab/Alpaca SELL stops,
  keyed `SYMBOL:account`, 60s cache. Portfolio polls every 60s and merges into `confirmedStop` (broker truth
  overrides stale llm-coverage overlay).
- **`open_trades_intelligence._broker_protective_stops`**: each broker stop carries `fetched_at` (ISO UTC);
  summary includes `broker_stops_fetched_at`.
- **`llm-coverage`**: exposes `family_floor_pct` / `family_bounds` for floor-mismatch UI; broker overlay
  includes `fetched_at`.
- **`stopManagement.ts`**: `resolveLiveStop()` / `isTrailingBrokerStop()` — trailing orders with
  `stop_price=null` + `trail_offset` resolve to `LIVE BROKER STOP` (estimated floor = price × (1 − trail%)).
- **`stopReviewTooltip.ts`**: multi-line tooltips — broker last read, advisory last reviewed, quote as-of,
  operator confirmed. Wired into Portfolio `HoldingProtectionActions`, Open Trades `PositionDecisionCard`,
  and the 🛡 stop badge.
- **Tests**: `tests/test_stop_fixed_trailing_validation.py` (fixed vs trailing math/UI/backend parity);
  `test_stop_management_ui_hardening.py` test_16 for live-stops + review tooltips.
- Build marker: `cc-v3 live-stops-review-ts 2026-06-30`. Safety unchanged: per-order 2FA, evidence binding,
  no autonomous submit, OCO OFF, Fidelity manual-only.

## 2026-06-30 - Schwab live-stop: latest-quote refresh + after-hours GTC override + explicit canary target

Reconciles the after-hours policy and adds the operator's refresh-quote path. After-hours GTC is supported
**only** when the latest quote is refreshed + fresh, the override is enabled, and the operator acknowledges.

- **Refresh-quote endpoint** `POST /api/v2/holdings/protective-stop/refresh-quote` (`_protective_stop_refresh_quote`):
  fetches the LATEST available quote read-only, comparing all sources (Schwab extended-hours / Alpaca /
  market_quotes / Finviz) and picking the **freshest** (trust breaks ties) — after-hours Finviz/Schwab beat
  Alpaca's 16:00 close. Persists the refreshed quote; returns price/bid/ask, raw+normalized timestamp, source,
  session, freshness, `after_hours_ack_required`, `can_submit_gtc_after_hours`, blockers, `operator_readiness`.
  `broker_request_sent=false` — never submits.
- **Session-aware freshness** (`quote_time.is_fresh`): regular 15m, extended hours 60m (a GTC stop rests).
- **After-hours policy (reconciled):** default after-hours → `READY_FOR_OPERATOR_NEXT_REGULAR_SESSION`.
  `AFTER_HOURS_GTC` only with the explicit override (`SCHWAB_AFTER_HOURS_STOP_OVERRIDE=1` /
  `--allow-after-hours-gtc`) AND the operator after-hours acknowledgement. Never READY while stale/unparseable.
- **Explicit canary target + rollover-vs-roth:** readiness/preflight bind symbol+account+qty+residual+order_kind
  +trail+TIF+session+quote into the evidence `order_spec_hash` (`canary_target`). The UI shows a large CANARY
  TARGET block + Refresh button + after-hours ack. `schwab_roth.api_write_enabled=FALSE` (ticket mode) →
  readiness BLOCKED with a clear "not armed for live API writes" reason; the armed live-write account is
  `schwab_rollover_ira`. One-V-canary-only conflict check blocks simultaneous rollover+roth canaries.
- **Preflight** `--time-in-force --refresh-quote --allow-after-hours-gtc`; reports `canary_target`,
  `operator_readiness`, `after_hours_ack_required`.
- Unchanged: evidence-bound approval, per-order 2FA, whole-share, read-back; no broad stops; OCO OFF; Fidelity
  manual-only; no autonomous submit. Build clean; **63 tests pass**; validator 27/27; no broker request sent.

## 2026-06-30 - Schwab live-stop: after-hours works 24/7 via GTC + operator acknowledgement

**SUPERSEDED (2026-07-04):** canonical policy is override-required; see the 2026-07-04 entry above and
`docs/runbooks/protective-stop-integration-2026-06-30.md`. This section is retained for history only.

Supersedes the regular-session-only after-hours policy below. A protective stop is submitted **GTC**
(`GOOD_TILL_CANCEL`) and rests until triggered, so it is valid to place 24/7 — an after-hours quote should
not hard-block the canary. The discipline becomes an **operator acknowledgement**, not a session block.

- **`api_v2`**: the after-hours gate no longer requires a regular session / env override. After-hours /
  pre-market submission is allowed with the operator `after_hours_ack` (gate `after_hours_ack_required` until
  acknowledged). Optional kill-switch `SCHWAB_AFTER_HOURS_STOPS_DISABLED=1` forbids it entirely. The readiness
  endpoint returns `canary_state=READY_FOR_OPERATOR_AFTER_HOURS_GTC` + `requires_after_hours_ack` for a fresh
  after-hours quote (was `…_NEXT_REGULAR_SESSION`).
- **`protective_stop_2fa_preflight`**: `--after-hours-ack`; reports `operator_readiness=READY_FOR_OPERATOR_
  AFTER_HOURS_GTC` and `quote_freshness_class=after_hours_gtc_ack_required|after_hours_gtc_acknowledged`.
- **UI**: an after-hours acknowledgement checkbox ("I understand this is after-hours; Schwab may accept the
  GTC order but trigger behavior depends on regular-market conditions") appears when the quote is after-hours;
  checking it (plus whole-share confirmation) enables the trailing-stop button. Three-state badge now shows
  `READY — AFTER-HOURS GTC` / `ACKNOWLEDGE AFTER-HOURS`.
- **Unchanged discipline:** fresh+parseable quote, evidence-bound approval, whole-share qty, per-order 2FA,
  read-back; no broad stops from an after-hours canary. Stale/unparseable still BLOCK. `OCO_BRACKETS_SCHWAB`
  OFF; Fidelity manual-only. 60 tests pass; validator 27/27; V dry-run preflight PASS (`broker_submitted=false`).

## 2026-06-30 - Schwab live-stop: ET-aware quote timestamp normalization + after-hours canary policy

The V trailing-stop canary was blocked by `Quote validation failed: Invalid isoformat string: '2026-06-30
16:15:02 ET'` — the protective-stop quote gate (`api_v2`) parsed the quote timestamp with
`datetime.fromisoformat()`, which can't handle the ` ET` / space-separated shapes the holdings feed emits.

- **Shared normalizer** `scripts/brokers/quote_time.py`: `parse_quote_ts` accepts ISO+offset, ISO `Z`,
  space-separated local, and a trailing ` ET`/`EDT`/`EST` (America/New_York via `zoneinfo`, EDT/EST resolved
  by date — never a fixed offset, never a silent naive datetime). `classify_session` →
  `regular | pre_market | after_hours | closed | unknown`. Unparseable → `None` so callers BLOCK with a human
  message, never a raw isoformat error.
- **Backend gate** (`api_v2` protective-stop handler + `_stop_live_readiness` + `protective_stop_2fa_preflight`)
  now route quote timestamps through the normalizer. Unparseable → "Quote timestamp could not be parsed;
  refresh quote." Stale → block. Session surfaced.
- **After-hours policy**: a Schwab live-stop canary requires a **regular-session** quote. After-hours (fresh)
  → `READY_FOR_OPERATOR_NEXT_REGULAR_SESSION` (never auto-armed). Override is opt-in only — requires BOTH
  `SCHWAB_AFTER_HOURS_STOP_OVERRIDE=1` AND an operator `after_hours_ack`; default OFF. No other gate relaxed.
- **UI** (`HoldingProtectionActions`): readiness panel now shows Quote (parsed/fresh), Session, and
  raw→normalized timestamp, a three-state canary badge (`READY_FOR_OPERATOR` / `… NEXT REGULAR SESSION` /
  `BLOCKED`), and a human readiness message — never the raw parse error. After-hours/unparseable also disable
  the live-stop button with their reason.
- Verified: `2026-06-30 16:15:02 ET` → `2026-06-30T16:15:02-04:00`, session `after_hours`; V dry-run preflight
  PASS (`broker_submitted=false`, hashes match, whole 201 / residual 0.4412, no active lock,
  `operator_readiness=READY_FOR_OPERATOR_NEXT_REGULAR_SESSION`). Build clean; **59 tests pass** (12 new);
  validator 27/27. No broker request sent; `OCO_BRACKETS_SCHWAB` OFF; Fidelity manual-only.

## 2026-06-30 - Schwab live-stop: expose disabled reason + live-stop readiness panel (PR #33 canary prep)

A disabled Schwab `STOP` / `STOP_LIMIT` / `TRAILING_STOP` button no longer grays out silently. The V Schwab
rollover IRA trailing button was disabled solely by the `fractional_qty` blocker (201.4412 sh, residual
0.4412, whole-share confirmation unchecked) — but the tooltip only described the action, never the reason.

- `stopManagement.ts`: `buildStopLogic()` now exposes `disabledReason` / `disabledReasonHuman` (priority-
  ordered blockers; whole-share confirmation last).
- `HoldingProtectionActions.tsx`: disabled buttons show the reason (tooltip `Disabled — …` + inline
  `⛔ Disabled: …`); the whole-share checkbox is prominent and immediately above the action row, relabeled
  `"I confirm this Schwab stop will sell N whole shares of <SYM>; residual … remain monitored."`; checking it
  enables the button when all gates are clean. Backend hard-blocks (execution_state / DB-evidence / OCO on)
  also disable with a clear reason.
- New **read-only** `GET /api/v2/holdings/stop-readiness` (`broker_request_sent=false`; no broker calls /
  evidence writes / order placement) + a "LIVE STOP READINESS" panel (build marker, quote, db/evidence,
  validator, execution, active approval, whole-share, preflight, OCO off, broker submit) with ✅/⚠️/⛔ icons
  and a `READY_FOR_OPERATOR` / `BLOCKED` badge.
- Validation: build clean; **60 tests pass** (48 existing + 12 new `tests/test_stop_canary_readiness_ui.py`);
  `validate_schwab_write_policy` 27/27; V dry-run preflight PASS (`broker_submitted=false`).
- Safety unchanged: no live order submitted; `OCO_BRACKETS_SCHWAB` OFF; Fidelity manual-ticket only; Schwab
  stays operator-approved + per-order 2FA + evidence-bound + whole-share + read-back.

## 2026-06-30 - Protective stop integration + Fidelity activity lifecycle

- Created the `fix/stop-execution-journal-reentry-integration` stack to combine DB timeout guards, holding quote timestamps, OCO DD hardening, stop-card decision UI, and lock-in trailing advisory before any OCO canary.
- Fixed Schwab protective STOP / STOP_LIMIT / TRAILING_STOP evidence binding: fully approved intents now create an evidence-bound record tied to the exact Schwab order JSON hash, and broker submit revalidates that hash before `place_order`.
- Added Fidelity manual stop-ticket helper with `MANUAL_PENDING`, `MANUAL_PLACED`, `MANUAL_SKIPPED`, and `MANUAL_NOT_APPLICABLE` status payloads. Fidelity remains manual-only with no API submit.
- Extended SnapTrade/Fidelity activity ingest to preserve reinvested dividend / DRIP rows.
- Added ticker lifecycle aggregation and stop-out re-entry watch helpers. Uploaded Fidelity examples calculate HPE realized P/L `-$4,906.86` and GCTS realized P/L `-$1,370.10`; dividends are income, rollover cash is not trading P/L.
- Added read-only `scripts/oco_readiness_report.py`; OCO remains blocked until basic protective STOP and trailing STOP canaries, evidence binding, read-back, DB, validator, execution state, and kill switches are clean.
- Opened draft PR #33 and documented validation state in `docs/runbooks/protective-stop-integration-2026-06-30.md`: UI build and requested pytest group pass; DB-dependent Schwab validator and DB timeout checks remain blocked by PostgreSQL unavailability in the local session.
- Hardened the Schwab protective-stop evidence failure path after the V trailing-stop incident: evidence now records proof type/hash and TIF/residual details, internal evidence blocks return `broker_submitted=false`, UI copy says Trade AI blocked before Schwab, and `scripts/protective_stop_2fa_preflight.py --dry-run` proves order-spec hash binding before any canary.
- Refreshed the PR #33 runbook validation snapshot after the incident fix: UI build marker is present, requested pytest group is `66 passed`, and V preflight fails closed at PostgreSQL unavailability with no broker request sent.

## 2026-06-30 - Fix: bound lock_timeout/statement_timeout per connection to stop dashboard hangs

The dashboard repeatedly froze (`⟳ Reconnecting to backend… showing last-known data`, all KPIs `—`). The
server (`portfolio_server.py`, :7777) stayed alive but blocked: an additive `ALTER TABLE` on a hot table
(`paper_trade_proposals`) queued behind an idle-in-transaction `AccessShareLock` holder, and with
`lock_timeout = 0` (unbounded) it waited indefinitely — every subsequent query on that table piled up
behind it, blocking the server's request threads.

- `db_adapter._get_conn()` now sets **`lock_timeout='3s'`** (the anti-cascade guard — a lock wait fails fast
  instead of queuing the table) and **`statement_timeout='180s'`** (kills runaways), alongside the existing
  `idle_in_transaction_session_timeout='120s'`.
- Added `docs/runbooks/DB_HANG_PREVENTION.md` — diagnosis, recovery steps, and the **role-level** guards
  (`ALTER ROLE trade_ai SET lock_timeout/idle_in_transaction_session_timeout/statement_timeout`) that cover
  the ~300 raw-`psycopg2` connection paths `db_adapter` can't reach (run once; covers every connection).
- Verified: fresh `db_adapter` connections report `lock_timeout=3s` (was `0`); server restarted and serving
  `/api/v2/overview` 200 in ~0.3s, stable.

## 2026-06-30 - SnapTrade/Fidelity activity ingest documented

Clarified the SnapTrade/Fidelity data split: `scripts/snaptrade_sync.py` is positions/balances only, while
Fidelity activity requires `scripts/snaptrade_activity_ingest.py --apply`.

- Cash dividend receipts such as `DIVIDEND RECEIVED ... (Cash)` must be imported through the activity ingest
  to reach `trade_transactions`.
- Reinvested dividends / DRIP rows also require the activity ingest. When Fidelity/SnapTrade exposes separate
  dividend-income and share-purchase legs, both should be preserved; if it exposes one reinvestment row, keep
  the raw description for reconciliation.
- This remains read-only against SnapTrade/Fidelity and does not enable Fidelity API trading.

## 2026-06-30 - Fix: protective-stop panel falsely "BLOCKED STALE QUOTE" on every holding

The real-account stop panel showed `BLOCKED STALE QUOTE · Price timestamp: missing` for **every** holding
even though prices were live. Root cause: `portfolio_holdings()` (`/api/v2/portfolio/holdings`) resolved a
live price + source but never attached a **timestamp**, so the frontend freshness gate
(`stopManagement.ts` → `quoteAgeSeconds`) saw `null` and conservatively marked every quote stale, blocking
the live-stop request buttons.

- Each holding now carries `source_timestamp`, stamped from the source it actually used: `market_quotes` →
  that symbol's `fetched_at`; `finviz` → the cache `last_fetched`; broker-synced (`schwab`/`holdings`/
  `snaptrade`) → the freshest live tick we hold for the symbol (the same source the reprice draws from),
  falling back to `last_repriced` → `updated_at` → `as_of`.
- Verified live: **34/34 non-cash holdings now resolve FRESH (≤15 min)** with parseable timestamps (ISO or
  the `ET` format the frontend already handles); cash rows correctly carry none. Was 38/38 stale.
- Advisory/display only — no change to stop placement, broker writes, 2FA, or gates.

## 2026-06-30 - Stock-management due-diligence: paper OCO hardened before any Schwab canary

Closed the paper-side OCO gaps that had to be airtight before a one-share Schwab OCO canary. **No change to
live Schwab submit enablement; `OCO_BRACKETS_SCHWAB` stays OFF; 2FA / operator gates untouched; no live
broker writes.**

- **Stop-never-absent is now crash-safe.** `convert_to_oco` (`scripts/alpaca_stop_manager.py`) sets
  `bracket_state='OCO_REPLACING'` and persists the last-known stop price **before** canceling the standalone
  stop, so a process death mid-convert leaves a recoverable marker, not a silently naked position. Added
  **read-back verification** after every OCO POST (re-reads broker orders; if it can't confirm an OCO it
  rolls back to a standalone stop instead of declaring `OCO_ACTIVE`).
- **Repair supervisor** `repair_oco_replacing()` (`--repair-oco`): scans `OCO_REPLACING` rows and reconciles
  to broker truth — OCO present → `OCO_ACTIVE`; standalone stop → `STOP_ONLY` restored; **neither (naked) →
  immediately re-place a stop at the last-known price + alert**; broker unreadable → leave it, never guess.
- **Reconciler split.** `alpaca_paper_reconciler.py --fix` is now **DB-metadata-only** — the OCO auto-bracket
  (a broker write) moved behind the explicit `--apply-oco-retrofit` flag and no longer rides along on `--fix`
  (and is not auto-scheduled).
- **`qty_available` fails closed.** `apply_paper_protection_adjustment.py` no longer assumes `avail=shares`
  on a failed position read; unreadable qty → `BROKER_QTY_UNKNOWN` / `DEFER_RECHECK` (no order placed) with a
  bounded recheck cap (6) that turns terminal instead of looping the ATM pass.
- **Tests:** new `tests/test_oco_dd_gaps.py` **14/14**. Existing `test_schwab_oco_bracket` 12, 
  `test_protective_policy_oco` 6, `test_no_broker_write_bypass` 9 green; Schwab no-write validator 27/27.

## 2026-06-29 - Hermes governance: post-deployment verification + LOCAL_LLM policy restored

Re-audit after the budget guard went live (deployed 13:01 ET). **Broad-universe LLM research is confirmed
eliminated:** `top20_curation` (the 20k-call driver) dropped to **zero LLM calls after 13:01** — every 7-day
row is now `budget_decision='legacy'` (pre-guard) — and a live guard check returns `METADATA_ONLY` (T3) for
`top20_curation` on every LLM lane (grok / chatgpt / gemma3:12b). Guard selftest clean; **28/28 tests pass**
(broad-universe-no-LLM, unknown→fail-closed, market-hours-heavy-blocked, free-OAuth-unavailable→DEFER-not-paid,
T0 holdings ALLOW, T1 cap, T2 needs-trigger, duplicate→DEFER, expiry, no broker writes).

- **Verified scope (re-audit):** 30d = 30,092 research calls (24,074 cloud-free-OAuth + 6,018 local-GPU);
  1d = 7,888 (942 distinct cloud symbols + 73 local); 7d = 23,306. LLM by lane/30d: free-OAuth **24,544**
  (grok-3-mini 16,333 · gpt-5.4 8,113), local **4,841** (gemma3:4b 1,635 · librarian 2,485 · gemma3:12b 721),
  **paid 39** (claude-sonnet, monthly protection meta-review — deliberate cost-gated, never a fallback).
  No-active-trigger 66/1,295 (5.1%). Regenerated `docs/HERMES_RESEARCH_SCOPE_AUDIT.md`.
- **Restored** `docs/diligence/current/LOCAL_LLM_RUNTIME_POLICY.md` — the canonical local-GPU doc the guard
  claims to match was referenced everywhere but absent on disk; reconstructed from the live enforced rules
  (06:00–12:00 ET local-heavy block, single-resident-model + file lock, free-OAuth-only, no paid fallback).
- **Remaining (legacy/historical, not live leaks):** the 30d duplicate (~51%) and broad-universe totals are
  dominated by pre-guard activity; the guard now DEFERs duplicates and METADATA_ONLYs broad names going
  forward. Synthesis/source-curation tables (`watchlist_final_synthesis`, `source_*`, `rec_source_quality`)
  still lack the provenance vocabulary — a follow-up if their research is to be tier-governed too.
## 2026-06-29 - Stop methodology: family-floor enforcement, free-lane fallback, doc

Audit of SCHD's stop ($31.16, ~2.4% below — tighter than its 4% income-family floor) surfaced a systemic
gap: the 20d-swing-low anchor produced sub-floor stops on low-volatility holdings (whipsaw risk on core
holds). Advisory only — no broker action.
- **Family-FLOOR enforcement** (`holding_protection_advisor.py`): stops tighter than the family minimum are
  widened to the floor (income 4% / position 5%), with the widening in the rationale + a `floored` flag in
  evidence_json. `_sanity_check` now also flags below-floor stops. Full re-sweep widened **9 holdings**
  (SCHD/BND/JEPI→4%; DIVI/SCHG/ARKX/CSWC/HPE/XLB→5%).
- **Free-lane resilience**: on a Grok/ChatGPT OAuth 403 the advisor falls back to **local gemma** (free) —
  never to a paid key (no-paid-fallback). Proven live (Grok proxy was intermittently 403).
- **Monthly Claude meta-review** now carries the `floored` flag per symbol so widenings are sanity-checked
  explicitly.
- **Live stop %** on the Portfolio card (was the stale generation-time string).
- New `docs/STOP_METHODOLOGY.md` (registered in DOCUMENTATION_INDEX) — the canonical write-up.

## 2026-06-29 - Portfolio v3 holding cards: price/cost, stop status clarity, bigger reports

Operator-requested clarity pass on the Portfolio hub holding cards (advisory display only — no data/API
or execution change):
- **Per-share price + cost** — new row `Price $X` (market_value/shares) + `Cost $Y` (cost_basis/shares;
  "—" for 401k funds without per-lot basis).
- **Stop status is now unmistakable** — three distinct states: `● STOP LIVE` (green, resting broker order),
  `◉ MONITORED` (purple, software-watched, not a broker order), `○ ADVISORY stop … not placed` (amber,
  recommendation only). Previously a proposed advisory stop looked the same as an active one.
- **Larger / more visible** — stop chip + live-stop line enlarged; protection explainer (fixed-vs-trailing)
  and fund-description text bumped from 8.5/9px to 10.5/11px; report links enlarged to 30x26 with text
  labels (📕 PDF / 📘 Word / 📄 Generate) and a larger timestamp.

Files: `apps/command-center-v3/src/pages/PortfolioHub.tsx`,
`apps/command-center-v3/src/components/HoldingProtectionActions.tsx`,
`apps/command-center-v3/src/components/HoldingReportLinks.tsx`. v3 build (tsc+vite) passes.

## 2026-06-29 - Hermes research scope audit + budget governance (tiering + caps)

Applied the Finviz/LLM governance methodology to Hermes research. **Audit first:** `hermes_research_scope_audit.py`
found Hermes researching **~1,202 distinct symbols / 30d** via cloud lanes (**931 in one day**), with
**88% of external calls (20,574 / 30d) from one broad-universe source** (`top20_curation`, 1,047 symbols) and
**~11,776 redundant repeat calls (~50%)**. 39 paid `claude-sonnet-4-6` calls flagged. Advisory only — no trades,
no broker writes, operator/2FA untouched.

- **Budget policy + guard** `config/hermes_research_budget.yaml` + `scripts/hermes_research_budget_guard.py` —
  tiers T0 (held) · T1 (actionable, cap 50) · T2 (themed, needs active trigger, cap 80) · T3 (broad,
  **metadata-only, no LLM**) · T4 (cold, no research). Decisions ALLOW/DEFER/METADATA_ONLY/BLOCK. Fail closed
  for unknown source; no paid fallback; market-hours 27B/31B blocked (matches LOCAL_LLM_RUNTIME_POLICY);
  cloud-unavailable → DEFER (never paid/local-heavy); duplicate → DEFER. 28 guard tests + self-test.
- **Producers patched** `hermes_top20_external_intel.py` (the 20k-row driver) now gates every (symbol, lane):
  live dry-run over 923 candidates → ~104 ALLOW / 815 DEFER / 4 METADATA_ONLY (**~89% cloud fan-out cut**,
  coverage preserved within caps). `hermes_external_researcher.py` gains a central guard chokepoint +
  records provenance. `top20_curation` calls now tagged with the real tier-driving trigger_source.
- **Provenance** `migrate_hermes_research_provenance.py` — additive nullable columns (trigger_source, tier,
  budget_decision, lane_used, research_expires_at, downstream_outcome, …) on both research tables.
  `backfill_hermes_research_provenance.py` backfilled all **29,413 historical rows** (idempotent, factual,
  budget_decision='legacy'); 0 left unmapped; panel now reads stored tiers. Retrospective: **23,275 (79%)
  would have been METADATA_ONLY** under the new policy.
- **Governance panel** System → Hermes card + `GET /api/v2/hermes/research-governance` (read-only): research
  by tier, LLM by lane, local GPU, duplicate/stale/no-trigger, top expensive sources, budget posture.
  Served from a disk TTL cache (`HERMES_GOV_TTL_SEC`, default 600s; ~1-3ms cached vs ~3.5s fresh; `?fresh=1`
  bypass) pre-warmed by cron `*/10 6-20 * * 1-5 … --warm`; `api_v2` reaches it via an mtime-guarded reload.
- **Docs** `HERMES_RESEARCH_SCOPE_AUDIT.md`, `HERMES_RESEARCH_BUDGET_POLICY.md`, `HERMES_GOVERNANCE_PANEL.md`.

## 2026-06-29 - GPU/LLM overload + dashboard outage: tiered job prioritization + escalation 31B guard

Acute incident: dashboard `ERR_CONNECTION_RESET` (load 8+) during market hours. **Root cause = a feedback
loop:** the health agent investigated DEGRADED escalations via **gemma4:31b** (`llama-server` :8081,
~3 CPU cores), starving the single-threaded dashboard → more endpoint timeouts → more findings → more
31B investigations. Underneath: **361 cron jobs, 73 LLM-touching, 20–26 colliding every market hour**, all
sharing one local GPU with no time-of-day priority. No live trades / broker writes; operator/2FA untouched.

- **Escalation 31B guard (outage fix)** `claude_escalation_handler`: skip the gemma4:31b tier during the
  06:00–12:00 ET market window or when load1 > cap (4.0), falling through to a lighter lane. The runaway
  31B was terminated (load 8.25 → 3.4; dashboard recovered).
- **Job-schedule audit** `job_schedule_audit.py` — classifies every cron by tier (T1/T2/T3/INFRA) +
  resource class + LLM routing, with per-hour LLM-contention map. → `JOB_SCHEDULE_AUDIT.md`.
- **LLM priority guard** `llm_priority_guard.sh` + `apply_llm_priority_guard_to_crontab.py` — T3 LLM jobs
  that also run outside the window now DEFER during 06:00–12:00 ET (13 wrapped). Effective market-window
  LLM contention 20–26 → 12–16. Plus fixed the **Monday proposal-worker gap** (`0-5 2-6` → `1-6`).
- **LLM routing matrix** `LLM_ROUTING_MATRIX.md` — local-vs-cloud per use; **assessment: gemma4:31b is the
  wrong local model for this box** (CPU-spilling); keep gemma3:12b as the local ceiling, offload heavy
  T3 research/synthesis to the free cloud-OAuth lanes (Grok :8645 / ChatGPT :8646).
- **Embed timeout** `rag_retrieval` 30s → 90s (`EMBED_TIMEOUT_S`) so the proposal-review worker stops
  spinning on cold-embed timeouts under load.
- **Dashboard server made multi-threaded** (`portfolio_server.py` ThreadingMixIn + bounded semaphore
  `DASHBOARD_MAX_CONCURRENCY`=16) with **thread-local DB connections** (`db_adapter`) — fixes the
  recurring single-thread hang where one slow endpoint blocked `/api/health` (8–12s → ~2ms; verified a
  parallel slow request no longer blocks). Crons unchanged (one conn per process).
- **Zombie reaper** `reset_stuck_agent_jobs.py` — resets `watchlist_agent_jobs` stuck `processing`>30m →
  `queued` (worker died mid-job, no `updated_at`); on the health auto-remediation safety allowlist.
- **Cloud-OAuth usage monitor** `cloud_oauth_usage_monitor.py` — per-lane calls/day + auth-fail +
  **paid-fallback** detection (Grok :8645 / ChatGPT :8646); never routes free-only to a paid key.
- **Health-agent wiring** `collect_infra_optimization_health` — stuck-jobs (auto-remediated via reaper),
  cloud-OAuth issues, and an `llm_market_window_contention` regression alert if an unguarded T3 LLM job
  creeps back into 06:00–12:00 ET. Full design: `JOB_SCHEDULE_TIERED_PRIORITIZATION.md`.
- Still open (next): offload the 8 morning single-shot T3 LLM jobs to cloud; drop gemma4:31b off the box.

First trading morning after the every-5-min lane went in, Health Agent fired DEGRADED 69/100 and
`/api/v2/trade-ai` timed out. Investigation + fixes (source/scheduler/monitoring only; no live trades,
no broker writes, operator/2FA untouched, no gate weakened; pipeline gates were working correctly —
the GO candidate was correctly stale-quote-skipped). See `MOMENTUM_SCALP_HEALTH_INCIDENT_20260629.md`.

- **Server overload (real regression):** each 5-min lane run took ~210s (Finviz `--run` 90s + signal_sync
  86s + proposal 33s), saturating the single-threaded server → API timeouts + 4 flock-skips. **Fix:** split
  the cron — fast downstream chain every 5 min (`--skip-finviz-refresh`, `timeout 200`), heavy Finviz
  refresh every 15 min (`timeout 150`), one flock. Removes the 90s refresh from 11/12 runs.
- **Health check bug:** `momentum_scalp_signal_sync_stale` queried `strategy_signals.created_at` (doesn't
  exist) → `MAX(fired_at)`.
- **Pre-market false floods:** `proposal_gen_stale`/`social_scan_stale`/`sec_context` fired during the
  legitimately-quiet pre-open. Now scoped to the active session (09:30+); `proposal_gen_stale` is
  **condition-aware** (fires only when a fresh GO signal isn't converting, not on bare staleness); SEC
  window starts 06:00 (after its 05:45 cron). 23/23 source-health tests; no off-hours/pre-market floods.

## 2026-06-28 - Fix scalp-lifecycle-maturity 3.25 phantom regression (env-fragile evidence runner)

`SCALP_LIFECYCLE_MATURITY.md` had regressed to **3.25/5** with `alerts_test`/`liquidity_test`/`trace_test`
false. **Root cause: environment fragility, not a code regression or stale detector.** The maturity
generator ran its evidence tests with `sys.executable`; those tests import `social_scalp_scanner` /
`market_quote_provider`, which `load_dotenv()` at module top. When the doc was regenerated under the bare
sandbox python (no `dotenv`), the tests raised `ModuleNotFoundError` **at import** (before any assertion)
→ scored 0 → 3.25. Under the venv (the real runtime / cron / CI interpreter, which has `dotenv`) all three
pass and the score is **4.4/5**.

- Fix: `compute_scalp_lifecycle_maturity._run_test` now runs evidence under the **venv interpreter first**
  (`_evidence_interpreters`) so the result reflects real behavior, not the caller's environment. Tri-state
  `_run_test_state` (PASS / FAIL / **ENV_ERROR**) distinguishes a genuine assertion failure from an
  unimportable test; ENV_ERROR is surfaced as an explicit `evidence_indeterminate` warning ("re-run under
  .venv") instead of a phantom low score. Report adds `maturity_separation` (engineering vs empirical
  sample; source maturity / latency readiness reported separately, do NOT lift this score).
- Result: combined **4.4/5**, momentum 4.4, social 4.4 (was 2.5), engineering/control 5.0, `meets_4_5:
  False`. Capped at 4.4 by the empirical validation sample **2/30 (trade IDs 45 & 22)** — unchanged.
  **Strategy maturity 4.5+ NOT claimed.** No scores inflated.
- `SCALP_LIFECYCLE_MATURITY_REGRESSION_DIAGNOSIS.md` documents per-check classification (all three =
  environment fragility, none real/stale). New `test_scalp_lifecycle_maturity_regression.py` (21) guards
  it. No broker writes; operator/2FA untouched; no gate weakened.

## 2026-06-28 - Momentum scalp source maturity to honest 4.5+ (SEC/Form 4, latency states, consistency)

Raise the remaining 3.x source areas to honest 4.5+ via real evidence — not score inflation. No live
trades, no broker writes, operator/2FA untouched, no gate weakened. **No strategy maturity claim** —
empirical validation sample (2/30) remains the blocker to 4.5.

- **P0-1** Reconciled the validation-sample count: canonical = `scalp_trade_attribution.confirmed_closed`
  = **2/30** (trade IDs **45, 22**). Fixed `momentum_scalp_source_maturity_report` (was reading a
  non-existent `confirmed` key → raw COUNT(*) over-count of 3). New `test_validation_sample_consistency.py`
  fails if any report disagrees (source maturity / ops / tracker / lifecycle now all say 2/30).
- **P0-2** SEC/Form 4 **3.0 → 4.5-ready**: `run_sec_form4_momentum_context.py` (scheduled wrapper, dry-run
  default, lineage, reuses `sec_data_ingest`) + `sec_form4_source_maturity.py` (context classifier +
  evidence-based scorer) + cron `45 5` & `15 9` ET. Supporting evidence only — never GO, never bypass gates.
- **P0-3** Latency SLA distinct states: `PASS` / `WARN_PENDING_OBSERVATION` (no live samples — NOT a code
  failure) / `WARN_LATENCY` / `FAIL`; separate `latency_sla_readiness_score` (4.5) vs `…observed_score`
  (pending). Stale-quote DEFER still never a PASS.
- **P0-4** No-inflation enforcement: a source reads 5.0 ONLY with live in-window observation; report
  explicitly separates source maturity / latency readiness / observed latency / validation-sample maturity /
  live readiness. Combined source maturity **4.33 → 4.5**.
- **P0-5** Health monitoring extended to SEC/Form 4, signal sync, proposal generation, social scan
  (schedule-aware, no off-hours floods); SEC context auto-remediation added to the safety allowlist.
- **P0-6** SEC/Form 4 contributes the `catalyst_evidence` pillar only when a recent (≤7d) open-market
  insider buy is relevant; `social_velocity` still needs social; 5/5 still ≠ GO.
- **P0-7** docs (SEC context, lifecycle, maturity, latency SLA, pillars) + CHANGELOG + manifest; taxonomy 0.

## 2026-06-28 - Momentum scalp Finviz every-5-min early lane + source-maturity reporting

Source/scheduler/filter/reporting hardening to feed the validation fast path fresh candidates from
06:00–12:00 ET. No live trades, no broker writes, operator/2FA untouched, no gate weakened. **No
strategy maturity claim** — the empirical validation sample (still 3/30) remains the blocker to 4.5.

- **P0-1** `MOMENTUM_SCALP_SOURCE_LIFECYCLE.md` documents the discovery→scan→signal→proposal→validation
  path, current schedules, tables, and gaps.
- **P0-2** `run_finviz_momentum_scalp_scan.py` (window-gated 06:00–12:00 ET, dry-run default, handoff
  flags) + cron `*/5 6-11 * * 1-5` (flock, parseable JSON logs). Off-window = safe no-op.
- **P0-3** `config/finviz_momentum_scalp_screen.yaml` mirrors `momentum_scalp.yaml` filters;
  `test_finviz_momentum_scalp_filters.py` FAILS on float>20M / RVOL<5 / price>25 / social-only-GO;
  allows 2–4 pillar Social Scout surfacing.
- **P0-4** `momentum_scalp_early_lane_runner.py` — one command runs scan → signal sync → proposals →
  validation; per-stage JSON + latency; dry-run default; sandbox submit needs `--submit-validation`/env.
- **P0-5** `momentum_scalp_source_maturity_report.py` — per-source 0–5 maturity (Finviz/scanner/social/
  news/SEC/quote/signal/proposal/validation); combined **3.9→4.5** (→5.0 once the live 5-min window is
  observed). SOURCE maturity reported SEPARATELY from validation maturity; **does not claim 4.5+**.
- **P0-6** `momentum_scalp_source_latency_sla.py` — source→proposal / proposal→validation latency
  graded PASS/WARN/FAIL by window; a stale-quote DEFER is NEVER counted as a PASS (freshness preserved).
- **P0-7** Finviz→pillar source mapping documented + tested: pure-Finviz reaches 2–4 pillars but never
  `social_velocity`; Finviz+social+verified-catalyst = 5/5; 5/5 ≠ GO.
- **P0-8** docs (lifecycle/maturity/SLA/validation/pillars) + CHANGELOG + manifest; taxonomy audit 0
  violations. 183 backend tests green; no broker writes.
- **Health monitor + auto-fix** `health_agent.collect_momentum_scalp_source_health` (schedule-aware,
  06:00–12:00 ET) flags a stale/failing 5-min scan (`momentum_scalp_finviz_scan_stale` /
  `momentum_scalp_early_lane_error`) and **auto-remediates** by re-running the lane fast
  (`--skip-finviz-refresh`); script added to the auto-remediation safety allowlist (source/sandbox only,
  no broker writes); cooldown + circuit-breaker escalate to operator/code review if ineffective.

## 2026-06-28 - Trade AI scanner: top-30 pagination, Social Scouts, persistent selection, ToS copy

Operator UX/visibility + copy-list tooling for the Trading hub Trade AI scanner (Market Opportunities
Scanner). UI/API/report cleanup only — no live trades, no sandbox validation submit, no broker writes,
operator/2FA untouched. Social Scouts remain awareness-only and non-tradeable. **No maturity change.**

- **P0-1** Operator-facing taxonomy cleanup: "P-level" → "Validation level", "Automated Readiness" →
  "Validation Readiness", "P0/paper caps" → "P0/validation caps" (TradingHub); ATM panel "Paper account
  … paper endpoint" → "Validation account … sandbox endpoint (legacy alpaca_paper)". Release manifest
  regenerated; taxonomy audit 0 violations.
- **P0-2** Top-30 pagination, 10 per page (`1`/`2`/`3` + Previous/Next, "Showing X–Y of 30"); page
  count based on the top-30 window. Default sort score-desc; existing GO/WAIT/Universe filters preserved.
- **P0-3** Social Scout rows surfaced in the scanner: violet `SOCIAL SCOUT · N/5` pill (or `· LARGE
  FLOAT · N/5`) + `Social Scouts` filter tab + `SCOUT` decision label + `--social-scout` left border;
  tooltip with missing-pillar hints. GO rows suppress the pill. No execution affordance.
- **P0-4** Persistent checkbox selection across pages/filters/refresh via `localStorage`
  (`tradeai.scanner.selectedSymbols.<YYYY-MM-DD>`); de-duped; select/clear page + clear all.
- **P0-5** Thinkorswim copy list: selected count + selectable textarea (comma/newline/space) + Copy
  (clipboard API + textarea fallback) + "Copied N symbols". Cross-page symbols copied together.
- **P0-6** `/api/v2/trade-ai` already returns all ranked rows + scout pill fields (PR #17); no decision
  filter drops scouts; backwards-compatible when fields absent. (Deployed server restart exposes fields.)
- **P0-7** `apps/command-center-v3/src/lib/scannerSelection.ts` pure utils (paginate/toggle/TOS-format/
  pill) + `scannerSelection.test.ts` (32 checks, Node type-strip runner). Backend scout tests green.

## 2026-06-27 - Social Scout pillars (operator-awareness surfacing)

Surface partial social setups that are not yet validation-ready or momentum_scalp/GO-ready but meet
**≥2 of 5** Social Scout pillars, with a distinct violet pill so the operator sees "interesting, not
there yet." Surfacing/visibility only — **not** an execution feature. No live trades, no sandbox
validation submit from scout status, no broker writes, operator/2FA untouched. Validation maturity is
**unchanged** by this change (visibility, not empirical sample evidence).

- **P0-1** `social_scout_pillars.py` — deterministic 5-pillar model (social_velocity, market_confirmation,
  catalyst_evidence, structure_tradeability, strategy_risk_fit). 0–1 → no pill; 2–4 → `SOCIAL SCOUT · N/5`;
  5 ≠ GO (still gated). Always `not_tradeable` + `not_validation_ready`. (`tests/test_social_scout_pillars.py`)
- **P0-2** `social_route_policy` calls the pillar evaluator, adds a `SCOUT` actionability (stronger-than-WATCH,
  never tradeable) + scout fields. GO suppresses the pill; large-float → `SOCIAL SCOUT · LARGE FLOAT · N/5`.
- **P0-3** `migrate_social_scout_fields.py` (additive, idempotent) persists scout metadata on
  `scalp_scan_results` + `trade_ai_scans`; scanner stamps it (no raw social text).
- **P0-4** Command-center-v3 Trading hub Scalp screen: violet `--social-scout` pill + "Social Scouts"
  metric + tooltip; no Buy/Submit/Validate/Trade affordance.
- **P0-5** scout fields added to `/api/v2/trade-ai` + `/api/v2/scalp/live` (WS ringbuffer) payloads.
- **P0-6** a Social Scout can **never** create a strategy signal, enter the validation fast path, or fire a
  GO — enforced in `strategy_signal_sync`, `continuous_runner`, `momentum_scalp_paper_fast_path`
  (`SOCIAL_SCOUT_NOT_VALIDATION_ELIGIBLE`). (`test_social_scout_route_enforcement.py`, `..._validation_block.py`)
- **P0-7** `social_scout_replay_report.py` (read-only, JSON/MD): pillar histogram, scouts surfaced,
  large-float/social-only splits, graduated-to-GO, blocked-from-validation, top missing pillars.
- **P0-8** docs (`SOCIAL_SCOUT_PILLARS.md`, route matrix, validation fast-path, replay) + taxonomy audit
  0 violations. Social-only stays WATCH/WAIT/SCOUT only; large-float scouts manual-review only.

## 2026-06-28 - Validation sample-collection wiring (scheduled, sandbox-only)

Operator chose cron+submit-sandbox to accumulate the empirical momentum_scalp validation sample. Two
complementary sandbox-only paths now run weekdays in the 06:00–12:00 ET window; both idempotent, window
gate self-enforces. No gate weakened; operator/2FA untouched; no live broker write. Maturity stays at the
honest empirical level (2/30 confirmed) until the window runs — purely operational/data from here.

- **Hook (PR #15, merge `812504ee`)** `maybe_run_after_generation` now honors canonical
  `MOMENTUM_SCALP_VALIDATION_FAST_PATH=1` + `MOMENTUM_SCALP_VALIDATION_SUBMIT=1` (legacy `PAPER_*`
  aliases still honored). Default OFF; sandbox-only; idempotent. Wiring test 13/13.
- **Generation cron** env flags added to `auto_proposal_generator.py --today --apply` (`*/30 9-16 * * 1-5`)
  so the fast path fires immediately after each proposal batch — tightest timing before quotes stale.
- **Standalone cron** `*/2 6-11 * * 1-5 momentum_scalp_validation_fast_path.py --submit-sandbox`
  (flock-locked) catches proposals that become entry-valid between generation cycles. Crontab backed up.

## 2026-06-28 - Momentum scalp validation fast-path (no human validation approval)

Operator decision: momentum_scalp Validation sample-collection does not require human/operator paper
approval. Deterministic gates replace the approval queue so valid micro-float scalps convert to paper
promptly. Live trading unchanged (operator confirmation + 2FA). No live broker writes; LLMs advisory
only; social-only WATCH/WAIT; large-float scouts manual-review only. Maturity stays 4.4 (2/30).

- **P0-1** momentum_scalp.yaml: paper_approval_required=false, deterministic_gates_required,
  submit_mode=paper_only_fast_path; validation_gate paper_approval_required_for_sample_collection=false
  + human_approval_required_for_promotion=true; live_execution_policy (operator+2FA, autonomous=false).
  Validator fails on paper-approval regression OR weakened live/2FA/promotion language.
- **P0-2** momentum_scalp_paper_fast_path.py: deterministic gates (route/micro-float/window/TTL/plan/
  R:R/fresh-quote/drift/liquidity) → existing safe submit_paper (sandbox-only, idempotent). dry-run-first.
- **P0-5** env-gated wiring (MOMENTUM_SCALP_PAPER_FAST_PATH, default OFF) after generation; dedup +
  daily/concurrent limits; excludes EXECUTED proposals.
- **P0-3/P0-4** funnel adds paper_fast_path_* metrics + "no validation approval" note (approved-for-paper no
  longer a required/blocking stage); diagnosis recommended_fix = run fast-path promptly (not "approve
  faster"); SLA reframed to fast-path timing eligibility (within 1/3/5 min). Maturity not penalized
  for missing approval; still capped <4.5 until empirical sample met.
- **P0-7** live path / Schwab write policy / operator-2FA untouched (source-only 27/27, no-bypass green).


## 2026-06-28 - Scalp route persistence + hybrid large-float scout + conversion path (PR #10 follow-on)

Finishes the Social → Momentum Scalp lifecycle so TradeAI generates regular AND social-derived
scalps optimally, safely, traceably. Preserves PR #10 attribution/maturity (still 4.4/5, 2/30).
No real trades; no live broker writes; operator/2FA path unchanged; LLMs advisory only.

- **P0-1** `strategy_signal_sync.infer_strategy_id`: momentum_scalp fallback now micro-float (<=20M)
  + verified catalyst (was <=100M, no catalyst). Large-float verified -> large_float_social_scout.
- **P0-2** momentum_scalp.yaml prompt_context 13:30 ET -> 06:00-12:00 ET; validator now fails on
  stale human-facing window text (STALE_WINDOW_TEXT).
- **P0-3** additive migration (migrate_social_route_fields.py) persists route/actionability/
  strategy_id/reason_codes/catalyst on scalp_scan_results + trade_ai_scans; scanner stamps them.
- **P0-4** continuous_runner social injection is ROUTE-AWARE (classify_social_injection), not
  score>=25: only verified micro-cap GO is tradeable; large-float = labelled manual-review scout;
  social-only not injected. Carries discovery_trace_id + route labels.
- **P0-5** hybrid large_float_social_scout route + fields (float_class/scout_label/
  manual_review_required/operator_label "LARGE FLOAT SOCIAL SCOUT") + large_float_social_scout.yaml.
  Large-float names RETAINED + operator-visible, never standard momentum_scalp.
- **P0-6** strategy_signal_sync.route_enforced_strategy: durable route overrides loose YAML/fallback
  (watch_only/scout/meme never create momentum_scalp; social+unverified never momentum_scalp).
- **P0-7** momentum_scalp_fast_atm_runner.py (sandbox-only, dry-run-first): fresh in-window micro-cap
  -> WOULD_APPROVE; stale/expired/out-of-window/social/scout blocked. No gate weakened, no live path.
- **P1** freshness SLA report (27 stale-quote fails vs 0 TTL; median latency 9.95min, p95 173min;
  cadence eligibility) + route-policy replay (old score-only 30 vs new route-aware 0 tradeable,
  0 GO-leaks, scouts retained).


## 2026-06-28 - Scalp zero-sample reporting correction + paper-path diagnosis (branch `hardening/scalp-zero-sample-reporting-and-paper-path`)

**Operator correction 2026-06-28: no over-attributed momentum_scalp paper trades.** Prior reports
showed "17 opened / 1–3 closed" — wrong. They counted non-executed (cancelled/dedup) rows as opened
and an unlinked direct-label row as confirmed.

- **True attribution** (`scalp_trade_attribution.py`): a trade counts only when executed AND
  priority-1 `strategy_id='momentum_scalp'` AND lineage/fill evidence. Corrected confirmed = **2
  closed** (IDs 22, 45); 1 ambiguous excluded; 19 non-executed are not trades.
- **Funnel + maturity corrected**: funnel reports confirmed counts + unknown/ambiguous/non-executed
  stages + operator-correction note; maturity separates engineering (5.0) from empirical (0.33),
  caps zero-sample at 4.3 / 1–29-sample at 4.4. **Combined = 4.4; 4.5 NOT met.**
- **Paper-path diagnosis** (`diagnose_momentum_scalp_paper_path.py`): first bottleneck =
  `approval_fails_on_stale_quote` (148× `approve_proposal_failed`, ~18h-stale quotes). Freshness gate
  working — no code weakening; gap is operational (fresh in-window generation + timely approval).
- **Dry-run simulator** (`simulate_momentum_scalp_paper_path.py`): valid fresh in-window candidate →
  `WOULD_CREATE_PAPER_TRADE`; expired/social-only/liquidity-unknown/stale/out-of-window blocked/deferred.
- **Validation tracker** (`momentum_scalp_validation_tracker.py`): 2/30, gate false, never live-ready.
- No broker writes; operator/2FA path unchanged; LLMs advisory only; repo-level safety preserved.

## 2026-06-28 - Social → Momentum Scalp lifecycle hardening (branch `hardening/social-momentum-scalp-lifecycle-4-5`)

Closed all P0 lifecycle gaps from the Momentum Scalp / Social Scalp audit. No real trades; no
live broker write endpoints called; operator confirmation / 2FA path unchanged and out of scope;
LLMs advisory only; social-only signals never auto-tradeable without deterministic confirmation.

- **P0-1 ATM expiry:** `atm_auto_approver.resolve_atm_expiry` enforces the 30-minute intraday TTL
  (single source of truth) BEFORE approval — `EXPIRED_INTRADAY` / `intraday_ttl_expired`; the old
  4-hour rule is a non-intraday fallback only; fail-safe blocks unknown-age scalps.
- **P0-2 social alerts:** `social_scalp_scanner` keys alerts (and the `alerted` flag) off the FINAL
  capped decision, not raw score — a social-only WAIT can never fire a GO alert or mirror.
- **P0-3 config drift:** `momentum_scalp.yaml` float (20M) / window (12:00) / TTL (30min) aligned to
  `intraday_execution`; new `strategy_config_validator.py` fails on drift.
- **P0-4 liquidity:** intraday `_liquidity_prescreen` is fail-closed — unknown liquidity DEFERS
  (`DEFER_LIQUIDITY_UNKNOWN`), force bypass logged.
- **P0-5 routing:** deterministic `social_route_policy.route_social_candidate` (watch_only /
  momentum_scalp / meme_squeeze_momentum / portfolio_agents / reject); GO suppressed off-route.
- **P0-6 traceability:** additive `discovery_trace_id` migration (5 tables) + end-to-end threading;
  privacy-safe source metadata; backward-compatible.
- **P1:** funnel report, lifecycle maturity score (weighted + capped), outcome-learning loop
  (bounded advisory weights). Combined maturity computes **4.4/5** — engineering complete (raw 5.0),
  capped only by the unmet empirical validation sample (momentum_scalp still TESTING).

## 2026-06-27 - PO/P0/P1 maturity hardening → 4.5 (branch `hardening/po-p0-p1-maturity-4-5`)

Execution-safety, methodology, broker-truth, and diligence-evidence hardening. No live trades;
no broker write endpoints called; the operator confirmation / two-factor path is unchanged.

- **P0-2 evidence hashes:** `evidence_approval.py` now stores SEPARATE bundle hashes
  (approval/readiness/quote/risk/chain/model) and revalidates LIKE-TO-LIKE, fail-closed.
- **P0-4 readiness modes:** `execution_readiness.py` splits `preflight` / `submit` / `dry_run` /
  `audit`; submit-mode used by `schwab_transport`, preflight by the API endpoint.
- **P0-3 intraday window fail-closed:** new `intraday_window.py`; malformed/missing windows block
  auto-approval (`intraday_window_config_invalid`).
- **P0-5 broker truth:** `order_lifecycle.py` status normalization + idempotency fence;
  `reconcile_orders.py` full taxonomy report.
- **P0-1 release manifest:** tri-state PASS / WARN_NON_LIVE_ADJACENT / FAIL + frontend smoke.
- **P0-6 CI proof:** `run_release_ci_equivalent.py` + `.github/workflows/release-readiness.yml`.
- **P1-1 scanner:** `broker_write_scanner.py` (AST + regex), wired into the no-bypass test and the
  write-policy validator (now 27/27).
- **P1-2 audit ledger:** non-mutating chain verify + live-adjacent coverage report.
- **P1-3 options matrix:** `tests/fixtures/options_risk_blocks/` + matrix test + exported doc;
  added `min_buying_power` hard block.
- **P1-4 AI critique:** deterministic-first; LLM cannot overwrite deterministic facts; context/
  response hashes + deterministic-fallback flag; replay-integrity degrades status.
- **P1-6 health:** new execution-hardening collectors (release manifest, ledger coverage, stale
  approvals, chain snapshots, critique stale / replay-degraded rates).
- **PO diligence:** `compute_maturity_score.py` (weighted + capped), machine-derived
  `export_diligence_evidence.py`, and `docs/diligence/current/` pack incl. `MATURITY_4_5_ACCEPTANCE.md`.
- **CI source-only mode (sandbox fix):** GitHub Actions failed on environment, not regression —
  the runner has no Postgres/`psycopg2`, so 2 deployed-DB posture guards couldn't run (24/26).
  Added `--source-only` (auto-on via `TRADE_AI_CI=1`) to `validate_schwab_write_policy.py`: runs
  every code/source-level fence and SKIPS (loudly labeled, never silently passed) the DB-state
  guards, which are proven by the deployed run. Full mode unchanged = 27/27. Propagated through
  `run_release_ci_equivalent.py`; removed the `| tee` that masked the workflow exit code. CI is
  green + honest; deployed proof still full PASS. Maturity **4.95/5**, WARN_NON_LIVE_ADJACENT.
  Branch pushed; PR [#6](https://github.com/PatsKiller/tardeai/pull/6) — release-readiness check green.

## 2026-06-27 - AI Trade Critique persistence + system-wide access (UI 3.9)

**First-class data asset** — critiques persist in `journal_trade_reviews.payload` + queryable
`journal_ai_critiques` index (search, aggregation, coaching, morning brief).

- **Storage:** `ai_critique`, `ai_critique_meta`, `ai_critique_history` (10 versions); staleness from tag fingerprint.
- **API:** `GET/POST /api/v2/journal/ai-critique`; `/search`, `/insights`, `/setups`, `/summaries`, `POST /batch`.
- **Consumers:** Trade Detail, Advanced Reports (`AiCritiqueInsightsPanel`), Behavioral, Execution Coach, Morning Brief.
- **UI:** Stale banner + regenerate; trade-log `🤖` takeaway chips; **Generate AI critiques** / Grok batch toolbar.
- **Readiness:** `score_trade_tags` requires `ai_critique` (and flags `ai_critique_stale`).
- **CLI:** `--backfill-index`, `--reconcile-stale`; doc: `docs/AI_TRADE_CRITIQUE.md`.
- **Batch run (6M range):** 56 generated + 31 cached ≈ 87 critiques indexed (45 no replay/EQ data).

Commits: `65a48983` … `96be9bce`.

## 2026-06-27 - Universal replay backfill (all past + future trades)

- **`replay_backfill.py`** — pipeline: `build_trade_execution_quality` → `replay_chart_audit` for every trade.
- **`install_replay_backfill_cron.sh`** — weekday 22:15 ET cron; chained after Schwab journal ingest in health agent.
- **`buildReplayTrade()`** — single frontend helper; all replay entry points use it (Journal, Tagging Queue, Compare, Schwab).
- **`ohlc_charts._lookup_fill_times`** — 4-tier resolution: execution_quality → dedupe_key/srt → schwab match → symbol/date.
- **`/api/v2/journal`** + `fetch_closed_trades` — include `entry_time`/`exit_time` on every trade row.
- Full backfill run: **66 ok / 24 warn / 0 fail** (90 deduped trades).

## 2026-06-27 - Replay marker alignment (GOVX) + AI Trade Critique (UI 3.5)

**Remaining scale bug (root cause):** Tagging-queue replays passed dates only → markers snapped to midnight
UTC / first premarket bar (~$3) while journal fills were $4.08 @ 09:57 ET. Price lines floated above candles.

**Fix:**
- `ohlc_charts.py` — resolve fill times from `trade_execution_quality`; price-aware marker snap;
  per-marker `marker_aligned` integrity checks.
- `TradeReplayChart` — auto/lock scale toggle; VWAP/SPY excluded from Y autoscale; linked MACD/RSI time axes.
- Tagging queue + JournalHub pass `entry_time` / `trade_key` to replay API.

**Audit re-run:** 90 trades · **65 ok** (+3) · **25 warn** (−3 marker) · 0 fail. GOVX marker_aligned ✓

**AI Trade Critique:** `journal_ai_critique.py` + `GET/POST /api/v2/journal/ai-critique` + `AiTradeCritique`
panel in TradeInView detail (classification, execution, risk, opportunity cost, Grok narrative).
Persisted in `journal_trade_reviews.payload.ai_critique`.

## 2026-06-27 - Replay price-scale fix + full-trade integrity audit

**Root cause:** volume histogram shared the candlestick right price scale (`priceScaleId: ''`), so
share-count values (hundreds of thousands) stretched the Y-axis while $3–4 candles sat at the bottom.
BUY/SELL lines looked misaligned across all replays.

**Fix (UI 3.4):**
- `replayChartScale.ts` — centralized candle autoscale from OHLC + annotation levels only; volume/L2 on
  isolated hidden overlay scales.
- `TradeReplayChart.tsx` — sync scale after every replay paint step; **↻ Re-sync scale** button; dev
  integrity overlay.
- `ohlc_charts.py` — returns `price_bounds` + `integrity.marker_in_range` for client validation.

**Batch job:** `scripts/replay_chart_audit.py` — validates every closed trade, writes
`journal_trade_reviews.payload.replay_chart`, emits `docs/audits/REPLAY_INTEGRITY_*.md|.json`.
Run 2026-06-27: **90 trades · 62 ok · 28 warn (Finviz fallback or marker vs split-adjusted OHLC) · 0 fail**.
GOVX 2026-05-18 confirmed ok ($1.78–$4.39, 447 bars, Alpaca).

## 2026-06-26 - momentum_scalp: tightened criteria + intraday fast-path

Audit found momentum_scalp generated 104 proposals → 0 conversions: a 9h TTL (extended to 16:00 ET)
outran a minutes-long scalp window, so proposals expired/drifted before any fill. Fixed.
- **Criteria** (`config/strategies/momentum_scalp.yaml`): float **< 20M** (prime <10M, was 100M),
  RVOL **> 5**, `min_volume` 1M (high-volume floor), catalyst required, **6am–noon ET** window,
  social-momentum enabled (social-confirmed tradeable, social-only stays WATCH).
- **Fast-path mechanics:**
  - `proposal_lifecycle.get_expiry_datetime`: INTRADAY strategies now use a minutes TTL from
    `intraday_execution.proposal_ttl_minutes` (30m) with **no market-close extension** (was 8h→16:00).
    Verified: momentum_scalp expiry 0:30:00; swing unchanged.
  - `atm_auto_approver`: intraday trading-window gate — scalps only auto-trade inside their config
    window (6am–noon ET); outside → `outside_intraday_window`. Validated (06:00/10:30/12:00 in, 14:00 out).
  - Eligibility confirmed open: not blacklisted, ATM skip removed, alpaca_paper AUTO. So in-window
    scalps now convert on paper to build the sample needed to graduate off TESTING.

## 2026-06-28 - TradeInView P5–P6 (advanced reports, session recap, cron)

- **Session tab:** Pre-market plan vs EOD reflection (`journal_session_recaps`, `/journal/session-recap`).
- **Advanced tab:** Monte Carlo bootstrap, pivot grid (setup × regime), tax CSV export (`?tax=1` wash-sale flags).
- **Attachments:** Screenshot upload on trade detail (`journal_attachments`, `/journal/attachments`).
- **Options:** Multi-leg groups + book greeks in options summary lane.
- **Compare:** Win/loss side-by-side replay modal (`TradeCompareReplay`).
- **v2 redirects:** `/v2/journal*`, `/journal-analytics`, `/journal-reports`, `/paper-journal` → `/v3/trade-in-view`.
- **Cron:** Weekday Telegram annotation nudge (`journal_annotation_reminder.py` 23:30 UTC) + tilt Morning Brief hook (`journal_tilt_morning_hook.py` 12:00 UTC).
- **Migration:** `migrations/2026_06_28_trade_in_view_p5_p6.sql`.

## 2026-06-27 - TradeInView module (journal → performance analytics)

- **Branding:** `/v3/journal` → **TradeInView** (alias `/v3/trade-in-view`); nav label updated.
- **New tabs:** Exit Intel, Behavioral, Import (CSV + manual entry + options summary).
- **Unified detail:** `TradeInViewDetail` drawer (setup/review, reflection, trade rating, replay).
- **Trade log:** Cards ↔ sortable table; saved filter groups; CSV export; bulk-classify + review reminder.
- **Analytics:** Zella-like composite score on Analytics tab.
- **APIs:** `exit-intelligence`, `zella-score`, `behavioral`, `export`, `saved-filters`, `import-csv`, `manual-entry`.
- **Backend:** `journal_trade_in_view.py`, `migrations/2026_06_27_trade_in_view.sql`, `backfill_trade_in_view_mfe.py`.
- **Docs:** `TRADE_IN_VIEW_IMPLEMENTATION_PLAN.md`, `TRADE_IN_VIEW_GAP_AUDIT.md`.

## 2026-06-26 - Strategy monitoring remediation + source/strategy badges

Audit follow-up — see `docs/STRATEGY_MONITORING_20260626.md`.
- **`pullback_macd_reversal.yaml`** — strategy playbook for screener `default_strategy_id`; appears in
  `/api/v2/strategy-intelligence`.
- **Dual-lane entry parity** — watchlist bridge + pullback screener emit `tradeai_automated` (ATM) and
  `schwab_taxable` (2FA) per symbol via `scripts/proposal_routing_lanes.py`; `audit_proposal_source_parity.py`
  verifies coverage.
- **Broker-proposals sort** — neutral priority (Hermes + newest; no watchlist-first boost).
- **Source + strategy badges** — `ProposalSourceBadges.tsx` (watchlist, Pullback MACD, Protection, ATM test /
  2FA live lanes) + `ProposalStrategyBadge.tsx` on Broker Proposals, Proposals, Protection panels.
- **Enrichment throughput** — `auto_enrichment_runner.py` prioritizes `live_2fa` lane; curated light path for
  paper ATM; limits 40 / 15 (cron). `proposal_enrichment_loop.py` broker-first queue.
- **Cron restored** — `proposal_monitor.py` 4×/day (16:30, 18:00, 06:00, 06:30 ET);
  `run_scheduled_strategy_audits.sh` 17:05 weekdays. Install: `scripts/install_strategy_monitoring_cron.sh`.
- **`job_coverage_monitor.py`** — registry extended for ATM, protection pipeline, watchlist bridge, pullback,
  auto_proposal, enrichment, strategy audits.

## 2026-06-26 - Protection adjustments coupled to ATM (paper auto-apply, real operator)

Protection (stop-curation) recommendations were in a separate advisory table, not in the proposals
system and not governed by the ATM. Now coupled — see `docs/PROTECTION_ATM_COUPLING.md` (handoff).
- `proposal_kind` discriminator + ATM entry-path guard (`proposal_kind='entry'`) so a protection
  row can never reach the bracket-entry submitter.
- `protection_atm_pass`: PAPER positions auto-apply only the hard-guarded stop-UP actions
  (MOVE_STOP_TO_PROFIT_LOCK/BREAKEVEN via apply_paper_protection_adjustment — sandbox-only, REPLACE,
  risk-down-only); REAL stays operator (+2FA); other actions advisory. Wired into the ATM cycle +
  cron `*/15 9-16`. Flag `PROTECTION_ATM_AUTO_APPLY_PAPER` (default on).
- `GET /api/v2/protection-proposals` unifies them into the proposals view (API-layer union, not a
  physical row mirror — avoids re-triggering the LLM-oversight load fleet). Display rename
  paper→automated (TradingHub); `alpaca_paper` identifier left unchanged (high-risk to migrate).
- **Handed off** for review: union-vs-mirror, identifier migration, first-apply observation,
  Proposals-tab UI, protection-table retention. See the handoff doc.

## 2026-06-26 - Pullback/MACD: in-trade adjustment process (hourly, trading-days)

The intraday monitor is now a proper **in-trade adjustment** process — managing OPEN pullback
positions, not just pending proposals.
- Dedicated launcher `linux_launchers/run_pullback_macd_monitor.sh` + cron `35 9-15 * * 1-5`
  (hourly, open→close, **trading days only** via `market_day_gate` — skips weekends/holidays).
- `_adjust_open_trades`: for each OPEN position (`strategy_id=pullback_macd_reversal`), writes advisory
  guidance to `pullback_trade_adjustments` each pass — **trail the stop up** (swing-low / breakeven /
  under-VWAP, raise-only), **take-profit** at target, **exit** on thesis break (lost VWAP or MACD
  rolling back down). Advisory only — never modifies a live stop (operator / ATM stop manager owns it).
  `GET /api/v2/pullback-macd/adjustments`. Verified on a synthetic DDOG position (+6.6% → trail to BE).
- Fixed `_fetch_all` single-symbol MultiIndex bug (broke monitor/adjust when fetching one symbol).

## 2026-06-26 - Pullback/MACD: intraday proposal monitoring

Pullback proposals are now monitored multiple times a day and kept in sync with the live setup
(previously the screener only ran post-close). New `--monitor` mode (cron `15 10-15 * * 1-5`, hourly)
re-evaluates only the active candidate set + open proposals (cheap): refreshes proposals that still
fit the plan (live entry/stop/target/VWAP), and `_reconcile_proposals` **expires** those that no
longer fit — the name fell off the trigger (MACD inflection / VWAP / pullback no longer line up), or
live price hit/broke the stop/target. Verified live: caught STLD as a new intraday trigger, refreshed
DDOG's levels, and expired the morning AES proposal once it dropped below VWAP.

## 2026-06-26 - Pullback/MACD: earliest-recovery trigger + VWAP confirmation

The pullback screener now catches the move earlier and confirms it with two indicators:
- **Earliest recovery (MACD)** — triggers at the histogram **inflection** (turned up off the pullback,
  still pre-cross) instead of waiting for proximity-to-cross, which gave away the early move. Proximity
  is now a score input (`macd_require_proximity: false`). E.g. DDOG triggered today at prox 1.5% — the
  old proximity gate would have missed it.
- **VWAP confirmation** — a TRIGGER requires price **above intraday session VWAP** (`vwap_trigger: true`)
  in addition to the MACD inflection; recovering names below VWAP stay on watch. Intraday VWAP is pulled
  (5-min bars) only for the daily-screen survivors. New columns `vwap/above_vwap/vwap_dist_pct`
  (migration `2026_06_26_pullback_vwap.sql`), surfaced via API + a VWAP chip/metric on the tab.

## 2026-06-26 - Watchlist bridge revived (ranked + capped) + proposal-burst health guard

- **Watchlist→proposal bridge** was dormant (orphaned script, nothing scheduled it — last proposal
  2026-06-23). Revived: now ranks eligible promotions by **R:R then setup (Hermes) score** and creates
  only the top `--max-new` per run (best-first), instead of Hermes-order-then-cut. Scheduled on cron
  `*/30 10-15 * * 1-5 --max-new 5` so it drip-feeds (each new PENDING proposal triggers LLM oversight;
  the full 40-candidate run at once would re-cause the load incident).
- **Health guard** `collect_proposal_oversight_load` — flags a burst of newly-created PENDING proposals
  (`proposal_creation_burst`, warn ≥15 / critical ≥30 in 20m), the exact condition that overloaded the
  single-threaded server on 2026-06-26. So a bulk-emit can't recur unnoticed.

## 2026-06-26 - Release gates: Schwab validator 26/26 + metric consistency strict

- `validate_schwab_write_policy.py` — aligned with post-unlock policy (all three Schwab accounts in
  pilot allowlist when armed; IRA fail-closed via ExecutionBlocked/2FA; position sync degraded_noop;
  GATES_REMOVED canary pass-through documented).
- `validate_metric_consistency.py` — scoped win-rate labels; v3-only ambiguous scan; 0 strict hits.
- CC v3 KPI labels scoped (Journal/Paper/Backtest win rate).
- `RELEASE_MANIFEST_LATEST.md` regenerated — all checks PASS except repo hygiene WARN when runtime
  cron artifacts are dirty.

## 2026-06-26 - Live messaging: `live_trading_allowed=False` ≠ operator live off

- Split **Alpaca autonomous gate** (`paper_validation_policy.live_trading_allowed`) from **Schwab
  operator+2FA path** (standing unlock + per-order 2FA). `False` on the policy flag blocks auto
  live only — it does not prohibit operator-approved Schwab submit when standing unlock is active.
- `execution_state.live_trading_labels()` — canonical labels for both paths; surfaced on
  `/api/v2/live-trading-gate`, `/api/v2/atm/gate-status`, and `live_trading_gate.py --json`.
- `generate_state_of_repo_snapshot.py` — safety section no longer prints `PROHIBITED / OFF` for the
  policy flag when operator 2FA path is on.
- CC v3 badges (`ATMControlPanel`, `PipelineControlTower`, `MetricStrip`, `TradingHub`) — show
  **LIVE VIA 2FA** vs **AUTO LIVE BLOCKED** instead of blanket "LIVE TRADING PROHIBITED".

## 2026-06-26 - Institutional hardening: operator-approved automated trading 4.5/5

- `scripts/execution_state.py` + `docs/CURRENT_EXECUTION_STATE.md` — fail-closed execution state
- `scripts/brokers/execution_readiness.py` — central readiness resolver (all submit paths)
- `scripts/brokers/kill_switches.py`, `order_lifecycle.py`, `reconcile_orders.py`
- `scripts/brokers/evidence_approval.py` — evidence-hash-bound single-use approvals
- `scripts/audit_ledger.py`, `scripts/export_diligence_evidence.py`
- Hard risk blocks in `options_desk_enterprise.evaluate_hard_risk_blocks()`
- API: `/api/v2/execution/current-state`, `/readiness`, `/kill-switches`
- CC v3 `ExecutionStatePanel` on System → Control Plane
- 10 test modules under `tests/test_execution_*.py` etc.

Maturity targets: Proposal desk 4.5/5, Options desk 4.5/5, Execution safety 4.6/5.

## 2026-06-26 - Pullback/MACD: authoritative trade plans + proposal cap

- **Authoritative levels** — the screener now derives technical entry/stop/target (stop = recent
  swing-low support, target = retrace toward the 52-week high) and writes a `trade_plans` row per
  emitted proposal. `broker_trade_plan_gate` resolves it (`plan_source=trade_plans`, authoritative),
  clearing the system-wide "No authoritative trade plan — target is R:R math only (gambling blocked)"
  route block that fires on any generic `entry + 2×risk` target. Verified on AES: gate violations now
  empty (other gates — agent reviews, intel readiness — are independent).
- **Proposal cap** — `max_proposals_per_scan` (default 5) bounds proposals created per scan so a
  market-wide selloff producing many triggers can't overload the LLM-oversight fleet again. Highest
  score wins the slots; the rest stay on the tab + pipeline. The cap logs what it dropped.

## 2026-06-26 - Pullback/MACD screener: follow-ups (Telegram env + trigger-only proposals)

- **Telegram under cron** — the screener now loads the full `.env` (`_load_env`) before alerting.
  `db_adapter` only loads `DB_*` keys, so `TELEGRAM_BOT_TOKEN`/`CHAT_ID` were absent under cron
  (no shell profile) and alerts silently skipped. Verified the token loads under a bare `env -i`.
- **Trigger-only proposals** — `proposal_tiers` narrowed to `[trigger]`. The first run emitted 22
  proposals (21 watch + 1 trigger); `broker_promote_oversight` then ran per-proposal local+cloud LLM
  review on all 22, spiking machine load (~11) and starving the single-threaded API server (dashboard
  timeouts). Cancelled the 21 watch proposals (kept the AES trigger); watch-tier still shows on the
  tab and feeds the pipeline. Doc updated.

## 2026-06-26 - Pullback / MACD screener (new tool)

New daily S&P 500 screener: **uptrend names ~20% off their 52-week high with MACD approaching a
bullish cross** — a counter-trend dip-buy discovery tool. Dry-tested on the full S&P 500
before build (500 screened → ~208 uptrend → ~22 pullback → ~1 trigger; the setup is intentionally
rare). Advisory only — proposals require operator approval, nothing auto-executes.

- Engine `scripts/pullback_macd_screener.py` (pandas-native MACD/SMA, yfinance data, `--dry-run`)
- Tables `migrations/2026_06_26_pullback_macd_screener.sql`; config `config/pullback_macd_screener.yaml`
- Two tiers (trigger / watch); fans out to: candidates table + `GET /api/v2/pullback-macd/candidates`
  + Command Center **Pullback/MACD** screen (amber pullback banner), candidate/incubator pipeline,
  Telegram (new triggers), and advisory proposals into the approval queue (trigger + watch).
- Cron `40 16 * * 1-5`; health collector `collect_pullback_macd_screener` (freshness + universe size).
- Doc: `docs/PULLBACK_MACD_SCREENER.md`.

## 2026-06-26 - Options approval-queue backlog triage

Investigating the 19-item options approval-queue "backlog" (surfaced by the new health
check) showed all 19 were auto-**blocked** by liquidity gates (illiquid OI/volume/spread),
none operator-approvable. Three fixes:

1. **CASH data bug** (`options_engine.py`) — the covered-call generator iterated holdings
   without an `is_cash` guard (the protective-put generator already had one), producing
   nonsensical covered calls on `CASH` sweep lines. Added the guard; regeneration confirmed
   zero CASH proposals.
2. **Metric semantics** (`health_agent.py`) — `options_approval_backlog` now counts only
   **pending** (a real operator-review lag, `approval_backlog_warn` 15); auto-gated **blocked**
   items get a separate softer info signal `options_approval_blocked_pileup`
   (`blocked_pileup_warn` 30) instead of tripping the warning.
3. **Queue cleanup** — bulk-rejected the 19 blocked items (content-stable IDs → sticks).
   Combined with (2), the warning clears and stays clear as new blocked contracts churn in.

## 2026-06-26 - Options Desk: global snapshot retention sweep

Added `prune_chain_snapshots()` (global, all-symbol retention) to
`options_desk_enterprise.py` and wired it into the daily IV-snapshot cron
(`scripts/options_iv_snapshot.py`, `20 16 * * 1-5`). The per-insert prune only
touches the symbol being written, so names that go quiet kept their tails; the
daily sweep now bounds the whole table. Honors `OPTIONS_SNAPSHOT_RETENTION_DAYS`
(default 45). Verified against live DB.

## 2026-06-26 - Options Desk enterprise: post-merge audit fixes

Audit of the enterprise desk layer (`options_desk_enterprise.py`) surfaced six issues; all fixed:

1. **Theta sign (correctness).** Estimated theta (used when chain theta is missing — the common case for short premium) was not sign-flipped for short legs, so the book's net theta/day reported decay *paid* instead of *collected*. Root cause was in `_theta_decay_estimate` itself: a "sign" scalar flipped the already-negative approximation positive. Reworked it to return long-convention (negative) theta; `aggregate_book_greeks` now flips via `side_mult` consistently with real chain theta.
2. **Hardcoded $150 share-price proxy (No-Hardcoded-Values rule).** `portfolio_risk_preflight` derived net-delta-% from a magic `150.0`. Now uses real dollar-delta (`net_delta_notional` = share-equiv delta × each leg's actual underlying price) / book MV. Dead pre-overwrite computation removed.
3. **Earnings-cache blackout gap.** Symbols requested mid-window that weren't already cached were never fetched → silently skipped their earnings blackout. Cache now fetches the missing subset and records "looked, none found" to avoid refetch storms.
4. **Chain-snapshot persistence.** Stored full chain JSON byte-sliced to 500 KB → malformed JSON → `::jsonb` cast threw → snapshot silently lost on large chains. Now stores a small valid summary (`vol_analytics_json` is all `fetch_vol_history` reads).
5. **Snapshot retention.** `options_chain_snapshots` had no pruning (unbounded growth). Added per-symbol retention via `OPTIONS_SNAPSHOT_RETENTION_DAYS` (default 45), enforced on the cron-driven insert path (uses `idx_options_chain_snap_sym_time`).
6. **Live-eligibility invariant.** A proposal with no resolved chain contract (no verifiable fill liquidity) is now never `live_eligible`, independent of the `require_chain_for_live` override.

Files: `scripts/options_desk_enterprise.py`, `docs/options-module.md`. Smoke-tested greeks signs + preflight + enrich invariants.

## 2026-06-25 - Options Desk enterprise sprint (audit → enterprise layer → filters → lifecycle → tooltips)

Six-commit stack on `main` (`5645e068` … `606761c5`):

1. **Audit fixes 1–4 + research bridge** — conviction price resolution; per-strategy desk slots; separate debit/wheel edge models; CSP on non-owned names; BS fallback for thin spreads; `options_research_bridge.py` → Hermes + TradeAI runtime (`research_type=options_desk`).
2. **Enterprise trade desk** — `options_desk_enterprise.py`: FMP earnings blackout, OI/vol/spread liquidity gates, vol term structure + skew, book greeks, portfolio risk preflight, DB-backed approval queue; API `/options/desk/risk`, `/desk/vol-analytics`, `/approval-queue`.
3. **Docs** — full `docs/options-module.md` rewrite for enterprise workflow.
4. **UI filters** — proposal chips (group, call/put, side, spread pairs, sleeve, tier, live-eligible) + position filters; `filter_facets` counts; spread strike pairs on cards.
5. **In-trade monitoring** — dynamic R:R, premium captured %, `lifecycle_phase`, `maturity_note` on open legs; LET MATURE / HARVEST / DEFEND badges.
6. **UI tooltips** — `optionsTooltips.ts` + `OptionsTip.tsx` across OptionsHub, proposal/position cards, greeks chart, review bar, novice panel.

Doc: `docs/options-module.md`. Build: `apps/command-center-v3` `tsc && vite build` green.

## 2026-06-24 - Social/meme momentum: early discovery + proposals-channel alerts + meme banner wiring

**Root-cause fix (WEN case).** WEN's social pump (Reddit/StockTwits, RVOL 33×, +25% gap, "Heavily
Shorted… Meme Traders Pounce") was caught only mid-day and never surfaced on its proposal card. Three
disconnects, all closed:
**1. Discovery ingest:** `social_ingest` cron ran bare → holdings-only; the trending/discovery code
existed but was never invoked. Now runs `--source all` (06:00 + 12/18) and `--source stocktwits
--discover` intraday (08:30/10:30/13:30). Verified: discovery surfaces WEN as #2 StockTwits trending.
**2. Scalp scanner re-scheduled:** `social_scalp_scanner.py` (social_posts → Finviz → 6-pillar score →
momentum candidates) was unscheduled since May; now `0,30 6-9` then hourly `10-16` M-F (flock-guarded).
**3. Proposals-channel alerts:** scanner GO/A+ meme/social alerts now mirror to the proposals Telegram
(`TRADEAI_PROPOSAL_ALERT_CHAT_ID`) via `_raw_send_telegram` — delivery confirmed.
**Meme banner wiring:** fixed the path bug where rvol/gap lived in `intel.technicals` but the card read
`intel.catalyst.rvol` (always undefined). `broker_proposal_intel` catalyst packet now carries
rvol/gap + a `social` flag (from `hermes_research_intelligence` momentum_catalyst); broker-proposals
LIST emits rvol/gap/catalyst at top level (banner fires without a detail-load); `BrokerProposalCard`
reads technicals+catalyst+top-level and treats the social flag/catalyst text as meme triggers
(`social-momentum (N src)`). Verified: WEN banner renders (triggers: "Heavily Shorted"+"Meme", RVOL 33×,
gap +25%). Commit `01941081`.

**Hermes data access (canonical):** all agents + local (gemma) + OAuth (Grok/ChatGPT) LLMs now read
Hermes intelligence (composite score/rank, graded research, external-lane opinions) through one helper,
`hermes_data_access.py` (`get_hermes_context` / `hermes_prompt_block`); wired into `llm_context_engine`,
`process_watchlist_agent_jobs`, and `hermes_external_researcher` (redacted, whitelist-respecting).
Doc: `docs/HERMES_DATA_ACCESS.md`. Commit `ea333239`.

## 2026-06-24 - Proposals unified surface + safety + dashboard perf + meme-risk banner

**Unified proposals (A-E).** Paper proposals now appear in the single "Proposals" tab on the broker-card
design, source-badged `PROPOSAL · origin` (kind=all|broker|proposal filter); old Proposals tab retired;
EnsembleValidationCard standardized. Backend paper-automation maturation loop untouched.
**Backend safety:** append-only `proposal_promotions` snapshot on promote; centralized R:R floor +
price-freshness (`proposal_thresholds.py`, fixed stale-stamp bug); cloud-oversight fail-closed (visible
WARN on 0 lanes); de-hardcoded required-agents/votes; cleanup-sweep no longer rejects already-traded rows;
requeue/un-reject endpoint; live-submit-path tagging (`routing_path`). Execution/2FA/canary untouched;
`validate_schwab_no_writes` green throughout.
**UI:** Queue-Health audit panel + requeue button; bulk multi-select; a11y (aria/keyboard) + responsive
(<720px single-column); de-duplicated repeated card text; condensed header; legible text sizes.
**Dashboard perf:** `/api/v2/finviz-strip-map` disk TTL cache + pre-warm cron (~7s→50ms) — clears the
"Reconnecting to backend" flicker (same pattern as the earlier `/eligible` fix).
**Meme/high-risk banner:** a bold "⚠ MEME / HIGH-RISK SPECULATION" banner + agent consensus now surfaces
at the top of a proposal card when signals are present (meme/short-squeeze keywords in catalyst or agent
reviews + extreme RVOL + unverified catalyst) — the AI's verdict is no longer buried.
Audit doc: `docs/audit/PROPOSALS_BROKER_VS_REGULAR_AUDIT_20260624.md`.

## 2026-06-24 - Broker trade plan gate: no gambling 2×R, strategy alignment, policy R:R floor

**Gate:** `broker_trade_plan_gate.py` blocks Path B live routes without authoritative plans
(`trade_plans` / strategy card / confluence). Generic 2×R geometry is never waived on operator route.
Watchlist bridge skips symbols without real levels (872 skipped in enforcement run).

**Strategy:** `broker_strategy_resolver.py` maps watchlist sleeves → YAML strategies; exit plan uses
support/resistance with **policy R:R floor** when resistance is too close (`max(YAML target_rr, 2.0)`).
Held rows refreshed: MS `core_growth_compounder` 3:1, DFAI `international_dividend` 2:1, DB
`dividend_growth_compounder` 2:1. DFAI reclassified from `covered_call_income`.

**UI:** `BrokerProposalCard` disables Auto route on `trade_plan` BLOCK; diligence adds Trade plan stage.
Docs: `docs/BROKER_TRADE_PLAN_GATE.md`. Restart portfolio server after Python gate changes (submodules
not hot-reloaded with `api_v2.py` alone).

## 2026-06-24 - Analyst prospectus RC1: full coverage, card icon-links, urgent-change cadence

Full report coverage generated: 33 holdings (Grok + free dual-lane oversight) + 300 watchlist
(manual-add / buy / strong-buy, fast render-only), 0 failed. All 33/33 holding + 300/300 watchlist
eligible cards now show live report links (339 total served by `/api/v2/reports/analyst/links`).

**Per-batch controls:** `generate_report` gains an `oversight` toggle; holding/watchlist batches gain
`engine` + `oversight` so a bulk run can mix tiers (holdings = oversight, watchlist = render-only with
on-the-fly full generation per symbol from the card).

**Cards (Portfolio + Watchlist):** `HoldingReportLinks` rebuilt as icon-links (📕 PDF · 📘 Word · ↻
regenerate) with an oversight-verdict dot and a rich multi-line hover tooltip (date created + relative
age, generation #, stance, cloud-oversight verdict, Grok status). Registry entry + `report_links_map`
now carry generation / grok_edited / oversight_verdict.

**Cadence:** weekly baseline (Sun 21:15) now uses Grok + ChatGPT free dual-lane oversight via batch
defaults; new `scripts/analyst_urgent_refresh.py` (cron 7:35 weekdays) replaces the daily full-refresh —
regenerates ONLY holdings whose recommendation bucket flipped vs the last report and emails the operator
the updated PDFs attached (silent otherwise); monthly = metered Claude. `ai_oversight_audit` table
created (oversight audit log). On request, ad-hoc reports for RGTI/IBM/GFS/QBTS were generated with
Grok+ChatGPT oversight and emailed with PDFs attached.

## 2026-06-24 - Analyst prospectus v4.1: depth tiers + /eligible reliability fix

**R0 reliability:** `/api/v2/reports/analyst/eligible` hung >120s (froze the single-threaded dashboard
→ "Reconnecting to backend"). Root cause: `symbol_fingerprint` did a per-symbol Yahoo network fetch
(~160 symbols) and hashed live price (broke change-detection every tick). Fixed: fast-mode fingerprint
(no network) + coarse price bucket, plus `eligible_report_payload()` disk TTL cache pre-warmed by cron
(`*/15` market hours). >120s → 0.004s cached.

**Depth tiers (all read-only, honest 'not available' on missing data):** Earnings & Estimates (EPS/
growth/consensus-trend), Business Quality & Fundamentals (margins/ROIC/ROE/leverage), Valuation in
Context (multiples + PEG + reverse-DCF implied-growth read), Scenario Price Targets (bull/base/bear +
probability-weighted ER; skipped for ETFs/no-coverage), Catalysts & Structural Risk, Tax-Aware Position
View (LT/ST gain → tax cost, or LOSS → harvest benefit, from `schwab_cost_basis_lots`), Portfolio Fit &
Concentration (beta contribution), and a real Peer Comp grid (P/E·margin·5y-growth·yield·1M, subject-
highlighted). Footer credit "Produced by TradeAI v3.0". Oversight caught + fixed two real bugs (tax-loss
mis-framed as a cost; ETF synthetic price targets) and a YTD two-source contradiction. V = 22 sections /
10pp, DIVI = 18 / 7pp, both PUBLISH_WITH_FIXES.

## 2026-06-24 - Analyst prospectus v4: sell-side design re-platform + depth

Presentation re-platform on top of the v3.1 intelligence engine. Single HTML/CSS source of truth
(`scripts/report_render.py` + `templates/analyst_report.html.j2` + `assets/analyst_report.css`) rendered
to a paginated PDF via **headless Chromium/Playwright** (WeasyPrint/Pandoc blocked by sudo in this env —
flagged) and a styled DOCX via python-docx. Layout fixes: charts INLINE in their owning sections (no
trailing "Visual Summary" dump), spaced labelled KPI band, running header/footer with page X of N, TOC,
prose-first with one compact KPI table per section, fixed-layout wrapping tables (no "do not c"
truncation), single Senior Analyst Overlay, markdown-emphasis stripped. Real TA charts via **mplfinance**
(`chart_technical`: candlestick + volume + RSI + MACD + Bollinger + SMA20/50/200 with drawn
entry/stop/target/support lines matching the Action Plan). Oversight now ENFORCES: deterministic
`enforce_integrity` dedupes the agent panel (one row per agent+rec) and reconciles the peer-median PE
pre-render, plus re-validation that downgrades to BLOCK if a flagged issue survives. New depth sections:
**Options & Income** (`aegis_covered_call_candidates`; honest "IV/Greeks not available"; ETF skipped with
one-liner) and **Analyst Commentary** (rating/target CHANGES from `analyst_consensus_history` +
`yahoo_analyst_targets_history` + bull/bear synthesis). CLI `--engine playwright|weasyprint|legacy`. V (8pp)
and DIVI (6pp) render PUBLISH_WITH_FIXES. Tests: `test_report_render.py`. Doc: `REPORTING_ENGINE.md`.

## 2026-06-24 - Analyst prospectus v3.1: synthesis quality lift + Claude cloud oversight

Stale-finding fixes across the five report modules (no engine rewrite): continuity no longer
self-compares same-day builds (+0.00%); volatility uses 20-day realized/ATR (never the Finviz
weekly-range field); agent panel is freshness-filtered, de-duplicated, calibration-weighted with
stale-position suppression and ADD≈BUY stance bucketing; Layer-4 + dual-lane (Grok/ChatGPT) consensus
surfaced with the disagreement ×0.8 rule; thesis-validity band computed from support/stop/target for
holdings (no more "n/a"); peer universe rebuilt by industry/curated comps with reconstructed day-change
and a valuation read; new **Analyst Predictions & Ratings** section (targets, upside, Buy/Hold/Sell
split, target + rating-split charts); Hermes web-grounded research infused as a section; Finviz recom no
longer shown as a street rating (ETF-honest); reportlab `P&L;` encoding bug fixed; prose-first + curated
KPI tables; sharper high-DPI graphics. New `report_oversight.py` — advisory free dual-lane critique
(always) + cost-gated Claude arbiter (`--claude-oversight` / `REPORT_CLAUDE_OVERSIGHT`), stamped at
`meta.claude_oversight`; new `oversight-only` CLI + `claude_oversight` API param. Tests:
`test_report_oversight.py`. Doc: `docs/reporting/REPORTING_ENGINE.md`.

## 2026-06-24 - Analyst prospectus v3: full holdings + watchlist link coverage, autonomous refresh

Reporting engine v3 with narrative synthesis, `intelligence_view`, executive callouts, premium DOCX/PDF export.

**Eligibility:** all non-cash holdings; watchlist manual (`personal_watchlist`, `operator`, `origin_system=operator`) OR buy-side CIO (BUY / STRONG BUY / ADD / WAIT FOR PULLBACK). Verified disk-only links — no phantom URLs.

**APIs:** `/api/v2/reports/analyst/links`, `/validate`, `/eligible`; `batch_watchlist` generate mode.

**CLI:** `batch-holdings`, `batch-watchlist`, `autonomous` (holdings + watchlist, limit 200).

**Cron:** Mon–Fri 7:35 + Sun 21:15 `generate_analyst_reports_autonomous.py` — auto-creates new symbols (`never_generated`) and refreshes on fingerprint delta.

**UI:** `HoldingReportLinks` on Portfolio + Watchlist hubs; `useAnalystReportMap`. Doc: `docs/reporting/REPORTING_ENGINE.md`. Tests: `test_report_links.py`, `test_reporting_engine.py`.

## 2026-06-24 - Broker Proposals UI redesign (thesis band, refresh, cloud oversight)

Redesigned Command Center **Broker Proposals** tab: `BrokerProposalCard`, `ThesisValidityBar`,
`BrokerAccountPicker`; visual drift-gap / thesis validity range (`broker_thesis_validity.py`);
`POST /api/v2/broker-proposals/refresh-prices` (live quote + sizing recalc); Grok+ChatGPT per-lane
verdict display in `BrokerIntelPanel`; prominent account selection (Schwab auto/manual vs Fidelity FA);
per-card **Executed manually**. Doc: `docs/BROKER_PROPOSALS_UI.md`. Tests: `test_broker_thesis_validity.py`.

## 2026-06-22 - Broker promote: cash sizing + AI oversight (Grok/ChatGPT)

Paper→Schwab promote now re-sizes on destination **cash** (not Alpaca equity), enforces strategy
live caps, daily limits, and live market gates (`broker_promote_sizing.py`). New AI oversight layer
(`broker_promote_oversight.py`): blocks on pending Maria/Risk/Steph reviews, agent BLOCK votes, or
Grok+ChatGPT DISAGREE; warns on missing cloud review / cautious agent votes. APIs:
`prepare-promote`, `evaluate-promote`, `oversight`, `queue-oversight`, `run-cloud-oversight`,
`promote-from-paper`. UI: `BrokerPromoteModal`, `BrokerIntelPanel` with decision context + oversight
buttons. Doc: `docs/broker-promote-sizing.md`. Tests: `test_broker_promote_sizing.py`,
`test_broker_promote_oversight.py`.

## 2026-06-22 - Proposal Maturity L10: options fallback, health monitoring, UI fix

Audit: `docs/PROPOSAL_MATURITY_AUDIT.md`. Options engine fallback tier when strict gates empty;
BS estimate for defined-risk; `get_proposal_health_metrics()`; `collect_proposal_maturity()` health agent;
`/api/v2/health/proposals`; OptionsHub force-scan + error/stale UX; HealthHub proposal panel;
`unified_edge_score.py` for cross-module edge adoption.

## 2026-06-22 - Cancelled trades: specific reason in DB + operator Telegram

Broker-blocked / revalidation-blocked / timeout cancels now write `exit_reason=cancelled_*`,
notes with human detail (e.g. CONCENTRATION_CAP), `TRADE_CANCELLED` proposal event, and
Telegram `TRADE CANCELLED — {symbol}` with Reason + Detail (not generic phantom/sync copy).

## 2026-06-22 - APGE phantom fix: broker-blocked submits no longer pollute journal

Root cause: ATM approved APGE (#96) but Alpaca rejected submit (CONCENTRATION_CAP 13.3% vs 8%).
Pending row kept `lifecycle_state=open` (DB default) → monitor voided as phantom at 16m → digest
surfaced DATA_OR_BROKER_REVIEW. Fixes: `lifecycle_state='pending'` on approve; cancel pending row on
`ALPACA_PAPER_SUBMIT_BLOCKED`; ATM counts broker reject as rejected not approved; monitor only
phantom-checks broker-submitted opens; digest excludes PHANTOM/CANCELLED bookkeeping closes;
health_agent flags pending lifecycle mismatches + stale never-submitted rows.

## 2026-06-22 - Options Module v2: cron, execution, IV history, credit spreads

1. **Cron** — `run_options_monitor.sh` every 10m market hours; daily `options_iv_snapshot.py` at 16:20 ET.
2. **Schwab execution** — `options_execution_policy.py`, `options_order_pilot.py`, `options_pilot_arm.py`,
   guard `OPTIONS_EXECUTION_MARKER`, API preflight/confirm/status; operator approved 2026-06-22.
3. **IV rank history** — `options_iv_history` table + daily ATM IV snapshot for true 52-week IV rank.
4. **Credit spreads** — bull put vertical proposals + `SpreadType.CREDIT_SPREAD` / `OptionLeg` in `order_intent.py`.
UI: OptionsHub execution preflight flow + credit spread filter. Doc: `docs/options-module.md`.

## 2026-06-22 - Options Module (Trading tab)

Turnkey advisory options desk: `scripts/options_engine.py` (covered calls + defined-risk proposals,
open-position monitoring), API `/api/v2/options/{proposals,positions,monitor,overview}`,
`OptionsHub.tsx` under Trading → Options tab, `run_options_monitor.py` cadence script.
Doc: `docs/options-module.md`. Execution remains advisory (Schwab options write blocked).

## 2026-06-22 - Fidelity monitored stops: operator approved (live)

`snaptrade_pilot_arm.py --approve` with `APPROVE FIDELITY STOPS 2026-06-22` — DB
`fidelity_stops_enabled=true`, `armed_for_ui=true`, `fidelity_monitored_unlocked()` passes. Monitor-only
on `fidelity_rollover_ira` (no broker execution, no 2FA); breach = alert + Active Trader ticket.
Portfolio server restarted (PID 2585482, port 7777); pilot status verified post-restart.

## 2026-06-22 - Schwab pilot: all 3 accounts + standing unlock (2FA retained)

`PILOT_ACCOUNT_ALLOWLIST` = taxable + both IRAs; `schwab_pilot_standing_unlock` DB flag (no expiry);
`CANARY_SESSION_DATE` → 2099-12-31. Per-order 2FA unchanged on every submit.

## 2026-06-22 - Docs sync: SnapTrade/Fidelity stops + one-share test

MASTER Stage 2c row, DOCUMENTATION_INDEX broker table, DAILY_OPS_LOG, snaptrade-fidelity spec,
snaptrade-read-only spec — aligned to monitor-only (no 2FA) + one-share test path.

## 2026-06-22 - Fidelity monitored stops: drop 2FA (monitor-only)

SnapTrade/Fidelity path is advisory only (no broker execution). Arm monitored stop in one step without
2FA; breach sends alert + Active Trader ticket. Schwab live submit still requires per-order 2FA.

## 2026-06-22 - SnapTrade one-share test mode (no sandbox)

Added `one_share_test` envelope (exactly 1 share, ≤$50), `snaptrade_trade_pilot.py` preflight/execute
with 2FA, `--arm-test` on `snaptrade_pilot_arm.py`, and `POST /api/v2/snaptrade/trade/preflight|execute`.
Preview works without place; live test requires ENABLED commit + DB arm + trade-capable broker.

## 2026-06-22 - Fidelity monitored stops (SnapTrade mirror, operator-approve)

SnapTrade cannot trade Fidelity (read-only). Built Stage 2c mirror for `fidelity_rollover_ira`: monitored
STOP/STOP_LIMIT/TRAILING ratchet + per-order 2FA + Active Trader ticket on breach. New modules:
`snaptrade_protective_stop_policy/pilot`, `fidelity_monitored_stop`, `snaptrade_pilot_arm.py`. API routes
fidelity holdings through monitored path when `fidelity_stops_enabled` DB flag set via typed-phrase
`--approve`. Broker API path stays `ENABLED=False`. Doc: `docs/brokers/snaptrade-fidelity-protective-stops-spec.md`.

## 2026-06-22 - Docs consolidation (A1A) + runtime commit

A1A consolidation: new `docs/LIVE_SYSTEM_FACTS.md` as canonical scale-count authority; MASTER,
EXECUTIVE_ARCHITECTURE, CHEAT_SHEET, COST_MODEL rewritten to use live-fact pointers (no hard-coded
tables/crons/scripts/strategies). `generate_system_facts.py` drift detector tightened (excludes CHANGELOG,
fewer false positives). Closeout `docs/project/DOCS_CONSOLIDATION_2026_06_22.md`. Committed pending
runtime: 17 strategy YAML performance_context updates, 7 cron-generated runtime JSON files, finviz global
throttle (`scripts/finviz_screener_runner.py` + `scripts/alpaca_throttle.py`), ohlc_charts,
system_health_agent, 3 new scripts. Drive-synced via gog.

## 2026-06-22 - Stabilization session docs + maturity audit (≈7.1/10)

Operator requested system maturity scoring and Track-1 stabilization. Live probe: health score 64
(execution_health=0 from agent backlog + pre-fix screener log errors); paper gate 18 closed @ 61.1% WR /
3.02 PF; overnight LLM queue 1,941 pending (root cause: PHASE102-RETIRED `run_deep_overnight_llm_window.sh`
cron). Actions: acked resolved SIEM alerts (fused_signals midnight stale, DB SSL transient); started agent
drain batch (--limit 40) + daytime LLM catch-up (--limit 15); confirmed screener upsert fix `53636262`.
Operator items: review KTOS/KBR Schwab stop-outs, re-enable overnight LLM cron, P0 key rotation. Docs:
`docs/project/STABILIZATION_SESSION_2026_06_22.md`, `docs/project/MATURITY_AUDIT_2026_06_22.md`;
`DOCUMENTATION_INDEX.md` + `DAILY_OPS_LOG.md` updated; `SYSTEM_FACTS_LATEST.md` + `STATE_OF_REPO_LATEST.md`
regenerated.

## 2026-06-20 - Operator research topics route to BOTH trends + knowledge research

Verification (operator: "make sure these added, not hallucinations, in research engine; retirement/estate/
tax used for reports"): Maria's add-topic created REAL trend directives (#85-203 — not fabricated) but they
fed TICKER DISCOVERY only, so ~65 retirement/estate/tax/Medicare topics produced ZERO knowledge research
(Roth/IRMAA/Medicaid/SSDI all 0) and fed no report. Fix: (1) sync_research_directives_to_topics.py backfilled
124 trend directives into topic_monitor (owner='shared' → Hermes+TradeAI research bridge); (2) POST
/watch/directives now mirrors every trend directive into topic_monitor on creation, so future Telegram/UI
adds route to BOTH automatically; (3) /api/v2/retirement/planning-research + a 'Planning Research' tab on
RetirementHub surface the topic_research grouped by theme. Bridge cron bumped 5→40 rows/day. Verified:
topic_research now Roth 9/IRMAA 3/Medicaid 5/SSDI 7/Medicare 6 (was 0); 124 enqueued (staged for Hermes).

## 2026-06-20 - Multi-timeframe Fibonacci + swing + confluence on cards

New `scripts/fib_confluence_engine.py`: analyzes daily/weekly/monthly charts (yfinance OHLC) independently
— fractal swing pivots, trend/structure (HH-HL / LH-LL), Fib retracements (23.6/38.2/50/61.8/78.6) +
extensions (1.272/1.618/2.618) per timeframe — then clusters every level (Fib / swing / S-R) aligning
within 1.5% ACROSS timeframes into confluence zones ranked by strength (overlap + timeframe diversity +
signal-kind diversity), each tagged with originating timeframe + source. Endpoint
`/api/v2/symbol/fib-confluence` (on-demand, cached 30m). UI: lazy-loaded "Multi-TF Fib & Confluence" panel
on each watchlist card (per-timeframe table + ranked confluence zones). Advisory/read-only. Verified:
NVDA top zone $164.27-164.67 (4 signals/3 TFs, high); ANET 11 zones, top $177-180 (6 signals, 9.5 high).

## 2026-06-19 - ETF YTD performance + yield + dividends (net-new)

Operator: "I want actual ETF YTD performance ... yield and dividends" (previously untracked). New
`scripts/etf_performance_enrich.py` (yfinance: YTD price return year-start→now, trailing dividend yield,
TTM dividend $/share) → new `symbol_profiles` columns `ytd_return_pct`/`dividend_yield_pct`/`ttm_dividend`,
exposed in `/api/v2/watchlist/items`. The OpenClaw `etfs` skill command now shows YTD/yield/div/expense/
look-through per ETF; Maria reports the full breakdown (verified live: XAR +13.5%/0.3%, XLE +17.8%/2.65%/
$2.16, PSQ −16.8% inverse, ITA +12.8% look-through). Weekly cron Sat 07:15. Backfill: 75/75 ETFs/funds.
Commits e089a63a (instrument_type API), 1e93bdf3 (expense+look-through API), 722469b4 (YTD/yield/div).

## 2026-06-19 - ETF classification: authoritative yfinance quoteType + watchlist API surfacing

Operator flagged that the assistant said "no ETFs on the watchlist" when 51 are present (DIVI/SCHY just
added). Root cause was three-fold: (1) `/api/v2/watchlist/items` only joined `symbol_profiles.sector`, NOT
`instrument_type` — so ETF status was null everywhere (UI, OpenClaw skill, agent); (2) `classify_instruments.py`
had a yfinance `quoteType` pass but capped fetches at ~120 and re-fetched known symbols, so new tickers fell
past the cap and defaulted to `stock`; (3) DIVI/SCHY were keyword-misclassified `stock`.

Fixes: added `sp.instrument_type` to the watchlist items SELECT (commit e089a63a); hardened
`classify_instruments.py` (commit ea6ca439) to apply CACHED `quote_type` authoritatively with no network and
fetch only un-cached symbols, so new ETFs always get caught and the work converges. Full pass cached 478/488
symbols (the 10 nulls are non-market 401k proxy codes like AB-DISC-Z); caught 13 ETFs the heuristic missed
(51→64 etf). Delivery: `classify_instruments.py` runs weekly via cron `30 6 * * 6` (Sat 06:30, flock-guarded),
companion `etf_analyst_enrich.py` at `0 7 * * 6`. The OpenClaw watchlist skill now prints an
"ETFs/funds on watchlist (N): ..." line + per-row [ETF]/[FUND] tags.

## 2026-06-19 - Auto-detected purchased→sold→journal lifecycle (Rec Intelligence)

Operator: "I don't see the mapping/flagging of performance for watchlist & proposals that were purchased,
monitored till sale, also noted in journal — these should auto detect." The lineage layer mapped
source→symbol→executed but stopped there. Added `recommendation_intelligence_engine.lifecycle_performance()`
+ `symbol_outcomes()`: for each REAL closed trade (`trade_closed`) it auto-joins the discovery origin
(`rec_ticker_attribution`: watchlist / proposal / screener / research / directive) and the journal review
(`journal_trade_reviews`), matched by symbol/account/close-date — no manual tagging. Endpoints
`/api/v2/rec-intel/lifecycle-performance` + `/outcomes` (read-only, advisory, 5-min cache). Surfaced on
three places (operator-chosen): (1) Rec Intelligence "Purchased → Sold Lifecycle" table (origin → buy →
sell return/P&L/R/hold → journal ✓); (2) a `✓ sold +X%` badge on Watchlist cards and Broker
proposals; (3) a `via <origin>` chip on Journal trade rows. Auto-refresh: engine ingest cron (daily 07:10)
keeps attribution fresh; the joins recompute live. Verified: 124 positions, 115 (93%) with detected
origin, journal-matched, 0 console errors.

Open-position monitoring (follow-up, same day): `open_positions()` completes the
purchased→MONITORED→sold arc — currently-held real positions with cost basis (weighted-avg buy from
`trade_transactions`), current price, unrealized P&L, held-since, and auto-detected origin.
`symbol_outcomes()` merges held state (multi-account/lot aggregation → weighted unrealized %; a symbol can
be sold-before AND held-now). Endpoint `/api/v2/rec-intel/open-positions`. UI: Rec Intel "Open Positions
— Monitoring" table + `● held +X% unrl` badge on Watchlist/proposals. Live: 39 held, all origin-detected,
$7,552 total unrealized.

## 2026-06-19 - LLM auto-enhancement of trend/sector watch directives

Root cause of "directives entered but not processed": trend/sector directives created with only a label
(no spec.keywords / seed_symbols) surface 0 candidates — the Hermes discovery producer phrase-matches
keywords against research + uses seed symbols, so an empty/long-phrase keyword set finds nothing (AI
datacenter worked because it had 6 keywords + 4 seeds). Fix: `directive_keyword_enhancer.py` —
LLM-derives keywords + seed tickers from the theme, **ensembling local gemma + free OAuth lanes (grok
:8645 / chatgpt :8646)** and merging their coverage (no metered API; advisory metadata only, never a
trade). Backfilled the 4 keyword-less directives (Defense/Aerospace, Energy, data-center-cooling,
datacenter-storage → 7-8 keywords + 6-7 seeds each). **Automated** via cron `25,55 * * * *` (runs before
the */30 discovery; no-op unless a directive lacks keywords) — kept off the single-threaded server's
request path / shared DB conn for safety. New keyword-less directives now self-enhance within ~30 min and
start surfacing candidates.

## 2026-06-19 - Watchlist directive filter + Sector Monitor setups fixes

**Watchlist directive filter:** matched only `it.directive_id`, but trend/sector directives surface items
via `watch_directive_hits` (by symbol), not by setting directive_id (only 78 of 3437 items carry one) —
so any trend directive showed ~0 (AI datacenter: 1 instead of 5; archived 0-hit ones: 0). Fix: the
`/api/v2/watch-directives` endpoint now returns per-directive `hit_symbols`; the filter matches
directive_id OR symbol-in-hits. Directive card is now a toggle (click to clear). Empty state is
directive-aware — names the directive, shows its surfaced count, and offers "Clear directive filter" so a
0-hit directive can't dead-end the list.
**Sector Monitor setups:** `sectors/monitor` required `wi.status='active'` — only 16 active items, so
just 1 setup showed across all sectors. Broadened to `status IN ('active','researched')` (3421 researched)
→ 56 candidates surfaced across 10 sectors (top 12, CIO-AVOID excluded, capped 8/sector). Advisory only.

## 2026-06-19 - LLM-health dashboard panel + hermes daily auto-commit

**LLM-health on the dashboard:** the `/api/v2/llm-health` endpoint (was headless) is now surfaced on
System hub → LLM tab as an "LLM Review Lane Health" card (3 lane up/down chips local/grok/chatgpt +
corpus valid-rate). **Hermes daily auto-commit:** `scripts/commit_hermes_daily.sh` (cron 23:13) captures
the day's `docs/hermes/` self-learning artifacts (backlog_health / embedding / librarian / observations)
to git + Drive — scope-locked to that dir, IRON-guarded, secret-hook protected, only commits on change.
`verify_hermes_daily.py` Telegrams the result. Note re API versioning: backend stays `/api/v2/` (API
contract version) while the UI is "Command Center v3" (frontend generation) — independent version numbers.

## 2026-06-19 - LLM-health observability + strategy gate + doc governance (audit follow-ups)

**LLM review health** (`GET /api/v2/llm-health`, `llm_health_check.py`): 3-lane status (local Ollama /
Grok :8645 / ChatGPT :8646) by delegating to `llm_lane.available()` + corpus quality from
paper_trade_multi_reviews. NOTE the audit premise (85% error / 185-of-2102 valid) was false — corpus is
59 rows, 97.4% valid, all lanes up; this adds the missing observability, not a crisis fix.
**Strategy-performance gate** (`strategy_utils.is_strategy_promotable`, Task 4): read-only gate in
auto_proposal_generator + incubator_proposal_promoter — <5 closed=INSUFFICIENT_DATA, >=10 closed at
<25% WR=blocked; logs to `proposal_suppression_log`; leaderboard exposes `strategy_gate`. DORMANT (no
strategy qualifies); complements the allocation tilt (tilt steers flow, gate is the hard floor).
**Audit fixes:** v4_1_deployment_log.md created (A1A P0); CANARY_SESSION_DATE → 2026-06-22 (Monday);
8 defense/BDC rotate_gap watch directives (real schema) + Watchpool gap chip; DOCUMENTATION_INDEX.md
(path/status-verified, 14 corrections vs draft); stage2a canary runbook refreshed for the Monday session.
**Declined (false premise):** Task 3 agent-calibration weighting — calibration is already wired
(agent_collab injects per-agent accuracy for self-calibration); the named file doesn't aggregate votes.

## 2026-06-19 - Percent-of-equity sizing, unified queue, mid-trade scaling, broker proposals

Switched automated sizing from fixed-dollar caps to **percent-of-equity** (`account_policy.py` — one
implementation shared by the proposal generator + risk gate; live equity wired for Alpaca AND Schwab w/
fallback+cache). Shares = min(equity×position%/price, equity×risk%/stop_dist); SNOW 8→~85sh. All
sizing/risk controls moved into `account_automation_policies`, editable from the v3 admin modal (two-step
token + audit). risk_gate gates re-aligned so percent-sized positions aren't wrongly rejected. Unified
ONE approval queue for auto + manual (origin/target_account/intended_broker + `queue_router`): alpaca
live (paper), Schwab wired-but-gated 3-lock real submit, Fidelity record-only. `queue_decision_audit`
logs every approve/deny/modify/route. New Trading-hub **Broker Proposals** tab (Schwab/Fidelity manual
submit → manual proposal + strategy). **Mid-trade scale-in/out** (`paper_scale.py` + Open-Trades card,
preview→confirm, broker-routed, stop-reconcile + weighted-avg/partial-P&L). **Telegram** proposal alerts
gained ½×/2×/✏️Size/🎯Risk + FQDN review/policy links.

## 2026-06-19 - Strategy intelligence: leaderboard, backtest fix, targeted screens, allocation tilt

Live **strategy leaderboard** (`/api/v2/strategy-leaderboard` + Strategy-hub default tab, chart+table):
ranks by live expectancy (avg R), backtest+assessment as context, confidence by sample size. Fixed
corrupt backtest expectancy (clamped per-trade r to ±10R in `strategy_signal_simulator`; repaired 12
rows — the 27R artifact). **Targeted Finviz screens** for the live winners (swing_breakout_targeted,
fib_retracement_targeted) matching each config's criteria → 176+148 new candidates; momentum/day-scalp
screeners untouched. **Per-strategy allocation tilt** (`strategy_tilt.py`, bounded 0.5–1.5 from live
expectancy, momentum_scalp excluded): re-ranks candidates + scales risk budget toward winners AND
tightens their position cap inversely (boosted winners take more trades, not oversized positions);
**tilt-aware dedup** awards a multi-strategy symbol to the highest tilt-weighted score (fib stopped
losing its overlaps — first fib proposal in weeks, #256 CAST).

## 2026-06-19 - Trailing-stop integrity + money-market cash reflection

`alpaca_stop_manager` ratchet now stamps ALL stop columns + trailing flags (was stale on stop_loss/
current_stop) and reads COALESCE(stop_loss_price, stop_loss) so no managed position is skipped (the SNOW
symptom). SnapTrade now normalizes money-market sweeps (SPAXX/FDRXX/…) to $1 NAV cash (`snaptrade_read`)
— fixes the Fidelity IRA phantom -19.7% loss + $3,060 allocation collapse; IRA cash PINNED to the
verified manual reflection ($452,622.73) until the feed is trustworthy. IRA reconciles to $565,421.73.

## 2026-06-18 - CIO verdict: Grok + ChatGPT dual-consensus (was Grok-only)

The CIO final synthesis (the "CIO View" AVOID/BUY verdict) ran on free Grok OAuth primary / gemma fallback.
Now it runs BOTH free-OAuth lanes — Grok + ChatGPT — and reconciles (`process_watchlist_agent_jobs.py`
`_synthesis_dual`): if they AGREE → that verdict at the higher confidence; if they DISAGREE → take the MORE
CAUTIOUS verdict (conservatism rank: AVOID/SELL > IGNORE > TRIM > RESEARCH_MORE > HOLD > ADD > BUY), lower
confidence ×0.8, and flag "MODEL DISAGREEMENT" in conflicts + narrative. Per-model verdicts + agreement
stored (`grok_recommendation`/`chatgpt_recommendation`/`models_agree`/`dual_consensus_json`). Verified live —
DGXX: Grok AVOID(0.7) vs ChatGPT RESEARCH_MORE(0.28) → consensus AVOID, conf 0.22. Specialists (Maria/Steph/
Risk) stay local gemma; only the final verdict is dual. Both free OAuth (no metered API); ChatGPT capped
(`CIO_DUAL_CHATGPT_CAP=40`/run) to bound codex latency; gemma fallback if a lane is down. synthesis_version→3.

## 2026-06-18 - Methodology audit: close the rank≠conviction gap across all surfaces

Audited every surface that ranks tickers by Hermes/momentum or analyst upside for the same gap. Fixed the 3
true gaps + 2 secondary, same pattern (join CIO verdict `watchlist_final_synthesis.recommendation` + analyst
`number_of_analyst_opinions`; exclude/flag AVOID + thin <3 coverage):
- `strategy_planner._candidates` (redeploy picks fed to the CIO LLM): CIO-AVOID names removed; each carries
  cio_view + analyst_opinions + thin_coverage; prompt tells the LLM to distrust thin coverage.
- `_sectors_monitor` per-sector candidates: CIO-AVOID excluded; cio_view + thin_coverage attached.
- `rotation_intelligence_engine` ADD side: a high analyst upside from <3 opinions now earns 0.4× the add
  (a +79% from 1 analyst no longer scores like +34% from 9); `thin_analyst_coverage` evidence flag.
- `auto_proposal_generator`: proposals now stamped with the latest `cio_view` (advisory visibility; still
  PENDING + operator-approved, never blocks).
- Rotation rotate-in pool now searches ALL non-held names for CIO-endorsed targets (not just the top-Hermes
  display window), so it suggests e.g. AVAV→DLR (CIO ADD_ON_PULLBACK, 29 analysts) not AVAV→DGXX (AVOID, 1).
  Watchlist grid + watchlist context confirmed already CLEAN (show CIO view).

## 2026-06-18 - Methodology fix: rotate-in respects CIO view + analyst depth

Validated a systemic flaw (operator-reported via DGXX "watchlist says AVOID but rotation says buy"): rotation
rotate-in candidates were ranked purely by `hermes_rank` (momentum/setup/social composite) and **ignored the
CIO holistic decision + analyst coverage depth**. Every top rotate-in (DGXX/SKK/BDSX/ELVN/GCTS…) had CIO
recommendation = AVOID/IGNORE with 0–1 analysts, yet was suggested as a buy (DGXX: CIO AVOID, +79% "upside"
from a single analyst). Two parallel rankings — Hermes (rewards momentum/hype) and the CIO synthesis (the
considered buy/avoid verdict) — were unreconciled. Fix: `research_candidates` now join
`watchlist_final_synthesis.recommendation` (CIO view) + analyst opinion count; rotate-in **ideas only target
CIO-endorsed names** (BUY/ADD/ADD_ON_PULLBACK) — never AVOID; UI shows the CIO badge + analyst depth + "thin
coverage ⚠" so a high Hermes rank with CIO AVOID / 1 analyst reads as hype, not conviction.

## 2026-06-18 - ETF/short proposal-side support

`paper_trade_proposals` + `paper_trades` gain `instrument_type` + `side` (default stock/long; backward
compatible). `auto_proposal_generator` stamps instrument_type + side=long on every proposal. New
`POST /api/v2/rotation/propose-etf` creates an advisory **PENDING, manual-review-required** ETF/short
proposal from a sleeve play (long: stop −8%/target +12%; short: stop +8%/target −10%; ~$500 review size;
deduped per symbol). Sandbox-only, advisory — never auto-approved/executed; existing gates apply. UI:
**Propose LONG / SHORT (review)** buttons on the ETF Sleeve Play cards.

## 2026-06-18 - ETFs & Funds as first-class instruments (research / UI / rotations, long+short)

Closed a major gap — discovery/research surfaced only stocks. Full design in
`docs/project/ETF_FUND_INSTRUMENTS.md`.
- Instrument typing: `classify_instruments.py` gives every symbol `instrument_type` (stock/etf/fund/
  inverse_etf) via curated universe + heuristics + yfinance `quoteType` (authoritative; 32 ETFs). Captures
  **expense ratios** (SCHD 0.06%, SQQQ 0.95%). Persisted to symbol_profiles.
- Analyst for baskets: `etf_analyst_enrich.py` computes a holdings-weighted **look-through analyst upside**
  (≥2 covered constituents) — ITA +12.8%, PPA +12.1%, SOXX +12.9%. ETFs have no sell-side targets; this is
  the honest basket view.
- `config/etf_fund_universe.json`: ETFs/funds mapped to rotation sleeves with direction (long ETFs + inverse
  shorts). Rotation summary returns `etf_candidates`: LONG ETF for underweight sleeves (ITA/XAR Defense,
  XLE/XOP Energy), INVERSE/SHORT hedge for overweight (SARK/PSQ). research-gaps seeds the sleeve ETFs for
  Hermes/TradeAI research. Card layer exposes instrument_type/expense/look-through.
- UI: **ETF / Fund Sleeve Plays** section (long/short tags, instrument badges, expense, price) + instrument
  badges on research candidates. Weekly crons for classify + etf-analyst.

## 2026-06-18 - Recommendation Intelligence: rotation-pair detection feeds rotation outcomes

`detect_rotation_pairs()` infers rotation edges from the executed trade history (close X → open Y, same
account, 0–3d later; nearest 1:1, deduped, directional with cycle-safe chains). `measure_rotations()` uses the
actual trade exit/entry prices as baselines → `rotation_alpha_pct` per edge. Live: **22 edges, avg +13.7%
alpha, 14 of 22 beat holding the original** (FLYW→GCTS +85%, GCTS→INFU −92%); multi-hop chains
(CMCSA→MRVL→BWEN→INFU→GCTS). UI: **Rotation Chains & Edges** (color-coded by alpha) + Rotation Outcomes.
Edges are inferred from timing (labeled executed_pair); day-gap kept in metadata for transparency.

## 2026-06-18 - Recommendation Intelligence Engine (Phases 2 + 3)

- **Phase 2 — lifecycle journaling + rotation outcomes.** `emit_lifecycle_events()` appends immutable
  lineage events to the existing `lifecycle_events` spine (rec_promoted_to_proposal / rec_executed /
  rec_rotated; idempotent NOT-EXISTS; 198 promoted + 51 executed live). `measure_rotations()` computes
  from-leg vs to-leg return → `rotation_alpha_pct` ("did rotating beat holding?"). `build_chains()` assembles
  multi-hop A→B→C. New `GET /api/v2/rec-intel/lifecycle`; **Lifecycle Journal** + **Rotation Outcomes** UI.
- **Phase 3 — feedback/learning loop.** `compute_source_quality()` turns each origin source's realized
  outcomes into a bounded ranking multiplier (0.50–1.50), persisted to `rec_source_quality` + a json contract
  file. Live: screener 1.349× (boosted), incubator 0.718× (demoted). `get_source_quality()` helper; wired
  into `auto_proposal_generator` candidate ranking behind `REC_SOURCE_WEIGHTING=1` (default OFF — advisory
  ranking only, never touches risk gates/sizing/execution). **Source Learning** UI panel.

## 2026-06-18 - Recommendation Intelligence Engine (Phase 1)

Unified recommendation-lineage layer: trace every ticker from origin source → execution → outcome,
attributable by source / strategy / account. A unification + activation layer (sources already carry
attribution; this connects them + adds the cross-source analytics that didn't exist). Full design in
`docs/project/RECOMMENDATION_INTELLIGENCE.md`.

- `scripts/recommendation_intelligence_engine.py` (daily cron 07:10): self-bootstrapping schema
  (`rec_ticker_attribution`, `rec_rotation_links`); ingests watchlist/directives/proposals/scans/hermes
  research/cio/rotation/holdings/executions into per-ticker×source attribution with earliest+latest source,
  occurrences, executed flag. Idempotent, per-source commit isolation, `--dry-run`/`--analytics`. Live:
  3,434 tickers, 415 multi-source, 108 executed.
- Analytics: coverage by source, **return by ORIGIN source** (screener 66.7% win/+7.2% vs incubator
  15.8%/−0.28%), by-strategy, multi-source chains, rotation links.
- API: `GET /api/v2/rec-intel/summary` + `/rec-intel/ticker?symbol=X` (full per-ticker provenance).
- UI: `/v3/rec-intel` (nav "Rec Intelligence") — summary tiles, trace-a-ticker lineage, return-by-source
  table, coverage bars, strategy performance, multi-source grid.
- Phases 2–3 (lifecycle/journal events, rotation-outcome measurement, feedback→ranking loop) scoped in the doc.

## 2026-06-18 - Symbol-card freshness: enrich research candidates + auto-refresh

Root cause of "sector/analyst pending" research candidates: `data/runtime/symbol_cards_latest.json` (read by
the rotation engine + card layer) had **no refresh job** and went 2 days stale, so newly-surfaced research
names had no card. Fixed:
- Enriched the pending names (SKK/BDSX/FLNC/BLZE/ELMT/AI/SPAI) — `build_symbol_profiles.py --symbols ...`
  (sector + description + industry) + targeted analyst fetch; all research candidates now show sector +
  description uniformly (analyst upside where coverage exists; honest "none" for no-coverage microcaps).
- New `scripts/refresh_symbol_cards.py` (weekday cron 06:40): refreshes symbol_profiles for watch-grade
  names, then materializes symbol_cards_latest.json from `/api/v2/symbol-cards` (atomic; refuses a broken
  payload). So new research/watchlist names get cards automatically and the file never goes stale again.
- Fixed working-dir on the rotation-digest + oauth-keepalive crons (added `cd $PROJ`, use `$PY`).

## 2026-06-17 - OAuth lane keepalive + stale alert + monitor/control panel; ChatGPT proxy now LIVE

- **ChatGPT proxy fixed + working end-to-end.** Root cause of the earlier "no final response": `hermes -z`
  one-shot does NOT finalize codex headlessly, and the model slug was wrong. Switched to
  `hermes chat -q PROMPT -Q -m gpt-5.4 --provider openai-codex` (programmatic quiet mode) via **plain
  subprocess — no PTY** — and the correct ChatGPT-account Codex model `gpt-5.4` (gpt-5/gpt-5-codex/etc. are
  400-rejected). Verified: real generation returns clean output in ~13s. Default model updated to gpt-5.4 in
  the proxy, llm_lane, hermes_external_researcher, and rotation oversight.
- **Keepalive + stale alert:** `scripts/oauth_lane_keepalive.py` (daily cron 09:00) sends a tiny real
  generate to Grok + ChatGPT to **roll their OAuth tokens forward** (so an idle lane never lapses), checks
  Hermes/Nous + local gemma, writes `data/runtime/oauth_lane_status.json`, and sends a **deduped Telegram
  alert** (12h window) when a previously-healthy lane goes stale/expired, with the one-line re-login fix.
- **Monitor + control in the Command Center:** `GET /api/v2/llm/oauth-lanes` (now with last-ok freshness) +
  `POST /api/v2/llm/oauth-lanes/keepalive`. The rotation Independent Oversight panel has a **Free OAuth LLM
  Lanes** control card — per-lane status + last-ok + re-login hint, with **Run keepalive** and **Re-check**
  buttons. Covers Grok, ChatGPT, Hermes/Nous, and local gemma. Live: 3/4 ready (Hermes/Nous not logged in).

## 2026-06-17 - ChatGPT OAuth proxy (free openai-codex) — inline ChatGPT lane

Built `scripts/chatgpt_oauth_proxy.py` (:8646), an OpenAI-compatible proxy mirroring the Grok xAI-OAuth proxy
(:8645), so ChatGPT becomes an inline oversight lane like Grok. It drives the operator's already-authenticated
`hermes` openai-codex CLI in a real pseudo-TTY (pexpect) — **Hermes owns the OAuth; the proxy never reads or
refreshes raw tokens**. Free under the ChatGPT subscription, NOT the metered API. `/health` + `/v1/models` +
`/v1/chat/completions`; `token_expired` flag; clean 401 + re-login hint when the session is dead. Runs as a
user systemd service (`config/systemd/chatgpt-oauth-proxy.service`, Restart=always). `llm_lane` gains a
`chatgpt` lane; rotation oversight routes both lanes through their proxies.

**Shared across all Hermes tasks:** `hermes_external_researcher.call_codex_cli` now PREFERS the proxy
(falls back to the pseudo-TTY CLI), so every Hermes task using the ChatGPT/codex lane — external research,
curation, oversight — works headless through it. Grok was already proxy-backed (`call_xai_proxy` → :8645).

**Command-Center monitor:** new `GET /api/v2/llm/oauth-lanes` probes all free OAuth lanes — Grok (:8645),
ChatGPT (:8646), Hermes/Nous portal, and local gemma (ollama) — returning per-lane reachable/authenticated/
token_expired/status/hint. Surfaced as a live lane-health strip in the rotation Independent Oversight panel
(green ready / amber needs-login / red offline, with refresh). Live: Grok ready, ChatGPT session-expired,
Hermes not-logged-in, local gemma ready (2/4).

NOTE: the ChatGPT OAuth session is currently expired — operator must `hermes auth add openai-codex --type
oauth` to activate; until then the lane reports unavailable and oversight uses Grok inline + the ChatGPT
manual-paste fallback.

## 2026-06-17 - Rotation Intelligence: independent Grok + ChatGPT oversight layers

`POST /api/v2/rotation/oversight` runs two independent oversight models over the rotate-out flags, rebalance
ideas, and sector overweights — a second + third opinion on the engine. Both **free OAuth, no API key, no
paid API, no broker action**: Grok (local xAI-OAuth proxy) + ChatGPT (openai-codex OAuth, free under the
ChatGPT subscription — NOT the metered API). Lanes hard-restricted to grok/chatgpt (paid claude/openai paths
skipped). ChatGPT codex needs a TTY → may return available:false headlessly; endpoint returns the prompt for
a manual free-web paste fallback. UI: purple **Independent Oversight** panel, "Run Grok + ChatGPT Oversight",
both verdicts (AGREE/CAUTION/DISAGREE) side by side. Verified: Grok returned a substantive CAUTION verdict
(flagged PFLT income→microcap as a poor fit; noted missing Mag7/AI overweight rebalance proposals).

## 2026-06-17 - Rotation Intelligence: holdings-degradation rotate-out signals

"What to rotate OUT" is now driven by **real deterioration**, not just concentration. Summary joins each
held name to the latest Aegis nightly brief.

- `degraded_holdings[]` (thesis_status/severity/signal_source/escalation/price/value) → **Deteriorating
  Holdings** UI section; `top_candidates` + `research_rotation_ideas` from-leg gain a `degradation` object;
  rebalance trim pool reordered to put deteriorating names first. Degradation badge on cards.
- **Accuracy labeling:** `triggered/danger/warning` = deterministic stop-distance math (`aegis_surveillance`,
  conf 0.90-0.95, NOT LLM); `weakening/broken` = local-LLM read (`aegis_synthesis`, gemma3:12b/4b, conf
  ~0.55). Each row carries `signal_source` + `deterministic`; badge shows "TRIGGERED · stop math" vs
  "WEAKENING · LLM read". `near_52wk_low_pct`/`analyst_recom` from the nightly snapshot.
- Weekly digest (`rotation_rebalance_digest.py`) leads with deteriorating holdings, split deterministic vs soft.

## 2026-06-17 - Rotation Intelligence: live prices + advisory review quantities

Every rotation idea/candidate now carries a **live price** and an **advisory review share quantity** so the
operator sees what a trim/add would look like. Read-only (`market_quotes` DB + holdings snapshot); no broker
call, no order, no live HTTP from the request; quantities are review RANGES — nothing is sized or placed.

- `research_rotation_ideas[]`: `from_price`, `to_price`, `from_shares_held`, `sell_shares_range`,
  `buy_shares_range`. UI shows "`$31.93 · 403 sh held → $6.68`" + chips "review trimming ~206–618 sh SCHD"
  / "≈ 985–2,956 sh DGXX". Advisory language only ("review trimming", "≈"), never "sell/buy now".
- `top_candidates[]` + `research_candidates[]`: `price`, `day_change_pct` (green/red), `est_shares` for held
  review candidates. Symbols without a quote (e.g. `3905` 401k fund code) omit price — no fabricated number.

## 2026-06-17 - Rotation Intelligence: sleeve balance + amount ranges + continuous loop

Made the rotation advisor **sector-aware, range-aware, and continuous** — all advisory only, no broker
action, no API keys, no paid Grok/xAI API, no amount ever auto-executed.

- **Sleeve balance (overweight/underweight detection):** `GET /api/v2/rotation/summary` reads the portfolio
  look-through vs operator comfort targets in new `config/rotation_sector_targets.json`, returning
  `sector_overweights[]` (theme, pct, target, excess_pct, **excess_dollars**, top_holdings),
  `sector_underweights[]` (theme, pct, floor, gap_pct), and `portfolio_total`. New **Sleeve Balance** section
  on `/v3/rotation`. (Live: Mag 7 21.4% vs 15% ≈ +$81k, AI mega-cap +$71k, Nasdaq 100 +$53k, Semis +$19k;
  underweight Defense 1.23% / Energy 0.95%.)
- **Advisory amount ranges (operator-confirmed):** each `research_rotation_ideas[]` carries
  `review_amount_range {low, high, basis}` = 5–15% of the trim holding; shown on each idea card as a review
  range with "advisory, operator-confirmed, not auto-placed". Nothing is sized or placed automatically.
- **Continuous loop + TradeAI/Hermes research wiring:** `POST /api/v2/rotation/research-gaps` seeds
  `watch_directives` (created_by `rotation_advisor`, deduped) for underweight sleeves (trend) + rotate-in
  candidates (ticker) so **TradeAI + Hermes research the gaps**; "Have TradeAI + Hermes research these gaps"
  button. `POST /api/v2/rotation/feedback` writes operator review into `llm_feedback_observations` (learning
  loop); **Reviewed / Dismiss** buttons per idea. `scripts/rotation_rebalance_digest.py` weekly cron
  (Sun 18:00) computes the summary, seeds the gaps, and sends a Telegram digest — localhost-only, places
  nothing.

## 2026-06-17 - Rotation Intelligence: Command Center v3 feature + polish

New advisory-only Rotation Intelligence feature in v3 (commits `d419d240` → `d7f6c699`). Grounded local
review + free/OAuth Grok second opinion; no broker action, no API keys, no paid Grok/xAI API.

- **Pages/nav:** `/v3/rotation` (Rotation Intelligence) + `/v3/advisor-changes` (Advisor Changes), nav items
  Rotation + Advisor Changes; Intelligence-hub Rotation tab; Portfolio-hub Rotation Advisor card + per-holding
  `?question=` prefill.
- **API:** `GET /api/v2/rotation/summary` (cached engine run), `POST /api/v2/rotation/ask`
  (grounded/local/oauth_prompt/dual_oauth, safe subprocess args + timeout), `POST /api/v2/rotation/grok-prompt`
  (manual prompt), `POST /api/v2/rotation/grok-review` (**inline** free/OAuth Grok via the local proxy —
  no API key, no paid API; grounding stays authoritative; manual-paste fallback).
- **Polish:** "Ask Local" is grounded-first (instant ~1s) with optional "Validate with local model";
  Grok review runs inline (was copy-paste); empty "— → —" idea cards fixed (engine candidates are per-symbol,
  not pairs → real empty-state + a Review Candidates grid); worthless/delisted ($0) candidates filtered;
  candidate sectors backfilled from `symbol_profiles`; "Missing Analyst Upside" card wired (held tickers with
  no `analyst.upside_pct`); defensive JSON parsing so a slow/empty advisor reply never crashes the UI.
- **Substantive Grok** (`7ca44039`): the Grok prompt now asks for a real qualitative read (sectors, analyst
  upside present/missing/negative, concentration, taxable vs tax-deferred, factors for/against, what to check
  next) instead of just "range unavailable" — while still never inventing a numeric trim amount.
- **Rebalance from research** (`5c36bbd0`): the summary also returns `research_candidates` (top non-held
  watchlist names with conviction — Hermes rank, sector, analyst rating/upside) and `research_rotation_ideas`
  (advisory `ROTATE_REVIEW` pairs: a trim-worthy real-ticker holding → a research name; no dollar amount, not
  a model-supported signal; 401k fund codes excluded; deduped). New "Rebalance from Research" UI section.
- **Grok reviews the rebalance ideas** (`9eda4e68`): `POST /api/v2/rotation/grok-rebalance-review` gives a
  per-idea verdict (reasonable to review vs poor fit, and why) + overall WATCH/RESEARCH_MORE, inline via the
  free OAuth proxy. "Grok Review These Ideas" button in the rebalance section.
- The hardened `rotation_dual_llm_advisor.py` still never calls Grok over an API — the inline calls live only
  in the API layer via the free OAuth proxy. Full detail: `docs/project/ROTATION_LLM_ADVISOR.md`.

## 2026-06-17 - Strategy Planner UI redesign (live context + guided before→after flow)

The Planner was a bare form with no context. Rebuilt `StrategyPlanner.tsx` (commit `2eca90e2`):
- Live **"Current — <account>"** panel (value + top holdings, updates with the account dropdown).
- Resolved $ amounts ("sell all 10 positions in fidelity_401k = $573,968"); trims get a holding picker
  with per-position values + a max.
- Guided **4-step flow** (Declare · Impact · Redeploy plan · Approve) with numbered step chips.
- Impact rendered as **before→after** metric cards (cash weight, income lost, account-after) + the
  per-holding income breakdown + look-through delta in a 2-col grid. Fixed a nonsense "$0 →" income render.
- Frontend-only; backend `/api/v2/strategy/{plan,approve}` unchanged.

## 2026-06-17 - Interactive Strategy Planner (declare → impact → advise → approve→sync)

New **Strategy hub → Planner tab** (`/v3/strategy`) — the operator's "interactive strategy" loop.
Commit `f58cda6e`. Full detail in MASTER (Portfolio Look-through & Ask-the-Agents section).

- **Declare** an intent: roll account→cash, trim a holding, deploy new cash, or rebalance.
- **Impact (what-if, read-only):** exact **look-through theme delta** from `lookthrough_themes.json`
  `accounts_detail` (per-account exposure) + account refactor + cash freed/cash-% shift + **precise
  per-holding income hit** vs the $55k target. Income = Σ(market_value × dividend yield%) per affected
  holding, yields from the authoritative `dividend_calendar` (the raw `ticker_dividend_data` feed is rejected
  — it reported SCHD 12.98% / BAH 12.33% vs ~3.6%/1.7% real). Examples: rollover→cash loses $11,073/yr @
  1.92% (SCHD $4,783 / JEPI $4,246 / BND $932 / V $834); 401k→cash = $0 (tax-deferred funds reinvest, no
  spendable income); trim SCHD $50k = $1,790 @ 3.58%. Roll fidelity_401k→cash also drops S&P -17% / Nasdaq
  -16% / Mag7 -14% look-through. (commit `1eaa3648`)
- **Advise:** goal-aligned redeploy plan via the free LLM lane (income-gap / Roth golden-window /
  defense-thesis aware) + Hermes-ranked watchlist candidates.
- **Approve → sync both ways:** persists to `strategy_plans`, records a LEARNING observation
  (`llm_feedback_observations`, `workflow=strategy_plan`), and seeds DISCOVERY by auto-creating operator
  `watch_directives` → discovery engine + watchlist sweep source candidates. Closes the loop
  strategy → discovery → watchlist → proposal.
- Backend `strategy_planner.py` + `POST /api/v2/strategy/{plan,approve}`; frontend `StrategyPlanner.tsx`.
  Advisory + read-only — approval seeds discovery, never places a trade.

## 2026-06-17 - Unified card enrichment: 2-line blurbs, fund sectors, Hermes-rank sweep priority

Watchlist & Portfolio card-layer improvements. Commits `25fc0d70` + `84533b02` (profiles),
`2be1d626` (stale flag), `bc985555` (sweep priority).

- **Two-line company blurb + ETF/fund sectors** (`build_symbol_profiles.py`): the unified card layer
  (`symbol_profiles` → `/api/v2/symbol-cards`, rendered on Watchlist / Portfolio / Open-Trades) now shows
  a two-sentence "what it does" blurb. ETFs (no yfinance sector) get `_ETF_SECTOR` (SPDRs→GICS sector,
  broad/bond/income→asset-class label); open-end mutual funds get `_FUND_SECTOR` (Morningstar-style
  category, e.g. FCNTX→Large-Cap Growth). Profiled screener names (JRSH, SPAI) that had no card data.
  Refreshed all 94 existing profiles + every held symbol; weekly cron (Sun 19:00) keeps it fresh. Opaque
  401k fund codes / delisted CUSIPs stay blank (no name source).
- **AI-enrichment stale flag tightened 2h → 1h** (`WatchlistHub.tsx`): added `enrichColor` (green ≤1h)
  for the "AI Enriched" metric so its color matches the flag; "Validated" keeps the daily-cadence color.
- **Hermes-rank sweep priority** (`watchlist_enrichment_sweep.py`): no-directive *researched* cards (e.g.
  ELVN #3, SNOW) sat behind the 3,300-item stalest-first rotation and went 24–48h stale. Two-tier now —
  PRIORITY pool (directive/active/`hermes_rank<=150`, ~162 items, ~135/run → ~36-min cycle) keeps visible
  cards under the 1h flag; reserved TAIL slice (cap//4) rotates the rest so nothing starves (cap 150→180).
  Verified live: ELVN 21.6h→fresh, SNOW 42h→fresh, sweep enriched 174/174.

## 2026-06-16 - Data-accuracy fixes: ETF sectors, worthless equities, analyst upside, regime, ask-agents

Position-card and advisor accuracy fixes surfaced from an operator review of Trading → Open Trades.
Commits `bb1f3131` (sectors), `555d8827` (worthless/analyst/regime), `8a00eaeb` (ask-agents).

- **ETF sector mislabeling** — Finviz reports EVERY ETF as sector "Financial" (industry "Exchange Traded
  Fund"), so XLI (Industrials), XLB (Materials), BND (bonds), SCHD/SCHG, JEPI, ARKG all showed
  "Financial (XLF)". Authoritative `_ETF_SECTOR` map takes precedence in `open_trades_intelligence.py`;
  `aegis_nightly_ingestion._corrected_sector()` refuses a bare Finviz "Financial" on any ETF; 664 existing
  rows backfilled. vs-sector label no longer fakes "in-line" → "no sector benchmark" for asset-class ETFs.
- **Worthless/delisted equity** — a non-fund ticker collapsed to ~$0 with <−90% P&L (e.g. SRNE @ $0.0007)
  was showing cached RSI/SMA as live. Now flagged `worthless`, technicals nulled + stale, warning
  "delisted/worthless — verify & write off".
- **Analyst target upside** recomputed against the LIVE price (SPCX "−14.8%" was off a stale pre-spike
  price → correct −18.7%).
- **Regime ↔ VIX coherence** — `market_regime_classifier.py` could call `high_volatility` off a gap proxy
  while VIX was calm ("high volatility 43%" with VIX ~16). VIX-coherence guard dampens the gap-only score
  when VIX is low/normal.
- **Ask-the-Agents lowercase tickers** — `/api/v2/portfolio/ask` only matched UPPERCASE symbols, so a
  lowercase question ("trim xlb for spcx") found no positions and the LLM replied "no XLB position".
  `_tickers()` is now case-insensitive, validated against held/known symbols (filters words like "trim"),
  and the context carries shares/price/basis/per-account so the model can answer "how many shares to trim".
- **Restart note**: the service runs as user `johnclaw` with `Restart=always` — restart without sudo via
  `kill $(systemctl show tradeai-portfolio-server.service -p MainPID --value)`; systemd respawns it. (Earlier
  `sudo systemctl restart` attempts were failing silently on the password prompt, leaving stale code live.)

## 2026-06-16 - Reports Portal: every Telegram report surfaced + live LM feedback loop

Operator reports were sent to Telegram but never stored, so the v3 Reports hub couldn't show them.
Fixed by capturing at the send source and adding a live LM-review loop. Commits `0471ee51` (+ `e550d8ca`
link-mapping fix). Full detail integrated into MASTER §15 (Notification & Alerting → Reports Portal).

- **Capture at source**: `report_capture.py` `classify_report()` recognizes 20 report headers →
  persists to a new **`telegram_outbox`** store at the `telegram_alert._raw_send_telegram` chokepoint
  (best-effort; never blocks a send; skips already-self-logged transient alerts).
- **Routed 9 direct senders** through the chokepoint (`eod_open_trade_alert`, `scalp_critic_agent`,
  `portfolio_monthly_report`/`_synthesis`, `portfolio_weekly_report`, `morning_digest`,
  `send_morning_brief`, `weekly_summary_local`, `stop_decision_brief`) so they're captured + FQDN/`/v3`-
  normalized (DOCX `sendDocument` paths left direct).
- **Reports portal** (`reports_portal.py`) now unions 4 stores (`notification_log`, `alert_events`,
  `telegram_outbox`, `ai_reports`). New tabs: Portfolio Briefs, Monthly Reports, Weekly Reviews,
  Incubator Screen, Research & Intel, Trade Reports, Trade Critique, Learning Digest (17 total).
  Monthly (14) + Weekly (10) pull real history from `ai_reports`. Verified live post-restart.
- **Link integrity (`e550d8ca`)**: validated each report link lands on the page that actually contains
  the content (not just a valid route) — `recovery→/v3/risk`, `actions→/v3/` (Home), `approvals→/v3/trading`,
  added missing `approvals`/`intelligence-sources` normalizer rules; all 40 brief slugs resolve valid.
- **Central Intelligence LM feedback loop**: `POST /api/v2/agents/intelligence-feedback` (was a dead 404)
  runs the **local gemma LLM** and returns the review synchronously; operator **"also ask Grok"** option
  (`use_grok`, free OAuth proxy) shows local + Grok side by side. Both lanes recorded to
  `llm_feedback_observations` (learning loop) + persisted to `intelligence_feedback`. Verified end-to-end
  (local review 1061 chars + learning observation written).

## 2026-06-15 - Stage 2c stop management → FULL PRODUCTION + complete architecture doc

Protective stop management is live across the whole book. New canonical reference:
**[`docs/brokers/stop-management-architecture.md`](brokers/stop-management-architecture.md)**.

- **Unlock**: `POC_MODE=False` (all taxable, ≤$250k) + both Schwab IRAs enabled (`IRA_PROTECTIVE_ENABLED`
  + `api_write_enabled`). Fidelity 401k stays ticket-only (no API).
- **Standing, no-ARM** for protective stops (`_protective_unlocked()` = policy ENABLED +
  `system_controls['protective_stops_enabled']`); canary BUY pilot still ARM-gated. Manual + per-order 2FA
  (web ticker OR Telegram/email code) on every Schwab account.
- **Modify** (one-click cancel-old-then-place, single 2FA; never double-stops) + Cancel (no 2FA).
- **Monitoring engine** `stop_lifecycle_monitor.py` (lifecycle/coverage/proximity/health, Schwab + Alpaca)
  → `GET /api/v2/stops/lifecycle`; card ✓ PROTECTED banner + oversized/partial coverage warnings.
- **Health agent** `stop_health_check.py` → SIEM + Telegram + system_health + **Hermes** findings.
- **Grok** R:R curation `grok_stop_review.py` (reviewed-by-GROK on the card; advisory).
- **Alpaca = AUTOMATIC** `alpaca_stop_manager.py` — ratchets paper stops up to the R:R-optimal level
  (`strategy_trailing_policy`), sandbox-only, no 2FA; all other accounts manual.
- Live: 4 Schwab protective stops (DRS/KBR/KTOS fixed + IRDM trailing) + 4 Alpaca, all healthy.

## 2026-06-15 - Stage 2c: LIVE protective-stop submit wired (DRS POC) + email/telegram either-channel 2FA

**Protective stops on real holdings now place LIVE Schwab orders** (commit `d6598b07`), reusing the proven
canary write plumbing end-to-end. Operator-scoped to a one-ticker proof — **DRS · taxable · 1 share · fixed
STOP** — with the full path wired for every account.

- **Account-chosen routing (never the client):** Schwab + `api_write_enabled` + policy armed → builds a
  marked `OrderIntent`, runs the protective gate, **requests per-order 2FA, then submits LIVE on confirm**.
  Accounts with no trading API (IRAs / Fidelity-401k) or a disarmed pilot → exact thinkorswim ticket.
- **Either-channel 2FA** (`REQUIRED_CHANNELS=1`): web typed-ticker **OR** a 6-digit one-time code now
  delivered to **both Telegram and email** (`approval_service._send_approval_email`). Any one confirms.
- **Own committed envelope — never the BUY canary's.** `protective_stop_policy.ENABLED=True` + a POC layer
  in front of the full envelope: `POC_SYMBOL_ALLOWLIST=('DRS',)`, `POC_SESSION_DATE` auto-expiry,
  `POC_MAX_NOTIONAL_USD=$1k`; SELL-to-close only, stop-below-price, qty≤held, ±8% drift. `execution_guard`
  routes `PROTECTIVE_STOP_2C`-marked intents through this policy **instead of** the $4/$40 canary gate and
  **skips the canary 5-order cap** (protective orders tagged `kind='protective_stop'`; `pilot_caps` counts
  only canary rows, so the canary budget is untouched).
- **New:** `scripts/brokers/protective_stop_pilot.py` (spec/intent builders for STOP/STOP_LIMIT/
  TRAILING_STOP + request/submit + server-side spec rebuild on confirm). **Endpoints:** `POST
  /api/v2/holdings/protective-stop` (request) and `/protective-stop/confirm` (2FA + submit). **UI:**
  two-phase modal (review → REQUEST LIVE STOP → approve by ticker OR code) echoing qty/type/price.
- **Validation:** `protective_stop_policy.py` added to the write-policy tamper-evidence list → **26/26
  green**; canary gate 26/26, two-channel approval 11/11; gate logic dry-tested (DRS allowed; KBR / >$1k /
  IRA / stop-above-price all blocked); confirm-path spec round-trip verified.
- **To fire the proof:** ARM via v3 Trading → Broker Orders, then DRS card → Queue stop (fixed) → REQUEST
  LIVE STOP → approve. (Not yet proven live — needs the operator arm + confirm.)

## 2026-06-15 - Stage 2b canary: FIRST live order proven (place→cancel) + workflow fixes

**✅ WHAT WORKED — first live Command Center → Schwab write, end-to-end.** The $0 place→cancel canary
submitted a real order to Schwab and was cancelled cleanly:
- **BUY 10 GRAB LIMIT 1.70** · real **broker_order_id `1006761718313`** · `state:SUBMITTED` · pilot
  `orders 1/5`. Limit 50% below market → could not fill; rested, then operator cancelled in ToS →
  Schwab live status `canceled`. Proves the full chain: **arm → preflight → single-channel 2FA →
  execute → schwab_transport → live order → cancel.** This is the core Stage 2b write path validated.
- **Cancel-FROM-Command-Center proven (later in session):** placed order #4 (`1006763166956`) → rested
  `working` → clicked **cancel order** in the Pilot Orders list → **confirmation prompt** → cancel sent to
  Schwab (`guard:cancel:ALLOW`) → `canceled`. The cancel no longer has to be done in ToS.

**🔧 LATER FOLLOW-UPS SHIPPED:**
- **Order-status reconcile** — `_pilot_status` now reads Schwab's live order status for any non-terminal
  local order (by `broker_order_id`), overlays `live_status`, and persists it (so `submitted`→`canceled`/
  `working`/`filled` reflects the broker). Fail-open; stops polling once terminal. Closed the stale-status gap.
- **Cancel button** now shows for ANY cancellable status (was `submitted`-only, which the reconcile broke
  by renaming to `working`) and prompts a `confirm()` with the order details before the live cancel.

**🔧 WHAT DIDN'T (and the fixes shipped):**
- **Preflight hung** (HTTP 000, 20s) — a stuck Schwab quote connection inside the long-lived server
  process (`get_quotes` was 1.6s from a fresh process). Fix: server restart clears it; root cause is
  connection reuse, watch for recurrence.
- **"One order at a time" slot kept blocking submits.** Two causes: (1) `consume()` only burned the
  *confirmed* channel, so with single-channel approval the unconfirmed pending row lingered and held the
  slot → fixed: `approval_service.consume()` now also supersedes leftover pending rows. (2) The lower
  DRAFT cards rendered an ApprovalPanel; approving there (drafts never execute) created slot-holders that
  blocked the real submit → fixed: removed the approval flow from draft cards + edit modal — the **Pilot
  Console is the only approve+submit surface**. Also: the SUBMIT flow now auto-rejects a stale slot-holder
  and retries once.
- **Approval/submit intent mismatch** — each preflight makes a NEW intent; approving one then submitting
  a freshly-preflighted other = "approval missing". The one-action SUBMIT (request-approval → web-approve
  → execute on the same intent) is the fix; operators must not re-preflight between approve and submit.
- **Stale order status (KNOWN GAP, not yet fixed):** the Pilot Orders list shows submit-time `submitted`
  and does NOT reconcile against Schwab's live status (`canceled`). The broker is the source of truth.
- **Console ▸ numbering vs lower-card numbering mismatch** (console ▸2/5 = real fill, lower RUN 2/5 = $0
  bracket) was a real foot-gun → resolved by paring the battery to ONE $0 preset.

**🎚️ DECOUPLED / SIMPLIFIED.** `CANARY_BATTERY` reduced from the rigid 5-step sequence to a single
"$0 PLACE → CANCEL test" preset; "Canary battery · run 1→5" relabeled "Quick test"; 16 stale draft cards
cleared. One path now: tap the preset (or fill the manual symbol/qty/limit form) → type the ticker →
SUBMIT (chains preflight + 2FA + execute).

**📈 HOW TO WIDEN THE CANARY NEXT (the levers, each fail-closed):**
1. **Prove a real FILL + close** — the one untested capability (fill capture + read-back + clean exit).
   Manual form: GRAB / 10 / limit @ live ask → SUBMIT → let fill → SELL 10 to close. Real ~$36.
2. **Prove other order SHAPES** — stop / trailing-stop / bracket (all place-below-can't-trigger → cancel).
3. **Symbols:** `brokers/canary_gate.CANARY_SYMBOL_ALLOWLIST` (now GRAB, XRX) + commit `CANARY_SESSION_DATE`
   (single-day auto-expiry — re-commit for a new session).
4. **Price cap:** `schwab_stage2b_canary_preflight.STAGE2B_MAX_PRICE_USD` ($4.00 → higher).
5. **Qty / notional envelope** (≤10 sh / ≤$40) and **pilot order cap** (5) — `brokers/pilot_caps`.
6. **Accounts:** `brokers/pilot_caps.PILOT_ACCOUNT_ALLOWLIST` (taxable only → add accounts; IRAs excluded).
7. Promotion past the canary (lift `BROKER_DISABLED` fail-closed default) is the final, separate gate.

## 2026-06-15 - Journal edge-analytics + AI Q&A, Schwab sync repair, proposal generation fixes

**Journal analytics (TradeZella-style, incremental — no migration).** `journal_analytics_engine.py`
(read-only) computes what the Analytics tab was missing, all from data already captured
(`schwab_round_trips` + `journal_trade_reviews`): win-rate/P&L by **day-of-week, hour, and trading
session**; **equity curve + max drawdown + per-trade Sharpe + recovery factor**; **realized-R
distribution**; and **per-strategy/setup/emotion/mistake** edge. `journal_ask.py` answers
natural-language questions over that analytics via Grok (local fallback). Endpoints
`GET /api/v2/journal/edge-analytics` and `POST /api/v2/journal/ask`. v3 Journal → Analytics tab gains
the risk-KPI row, day/session bar charts, edge-by-strategy table, R-distribution, and a "💬 Ask your
journal" box. Live on 119 real trades (+$36.5K, recovery 13.4) — surfaced a real **edge** (Mon 66.7%,
midday 68.4%) and **leak** (Thu −$2.4K, after-hours 16.7%). MFE/MAE deferred (needs intratrade capture).

**Schwab → journal sync repaired + monitored.** Root cause of an empty journal: `schwab_transaction_ingest`
/ `journal_builder` / `journal_classifier` never loaded `.env`, and cron runs them bare — so
`SCHWAB_APP_KEY/SECRET` were absent, the transport returned `NOT_PROVEN`, and the 18:15 nightly ingest
pulled **zero rows for weeks**. All three now load `.env`. Added `_emit_health_alert` → urgent SIEM +
Telegram if auth fails or a weekday ingest is empty. Added a **15-min trading-hours sync**
(`*/15 9-16 * * 1-5`) so trades hit the journal within 15 min, not once a day. (Recovered the operator's
CAST scalp +$110.80 into the journal.)

**Proposal generation fixes.** (1) Swing/breakout plans now generate proposals: `_liquidity_prescreen`
is strategy-aware (only intraday scalps are gated; swing/breakout/fib/earnings hold longer and pass —
approval-time readiness stays the backstop), and the per-symbol dedup now picks the highest-priority
strategy that **clears** liquidity (so a too-thin-to-scalp name falls back to its swing_breakout plan).
(2) Fixed a miscount where a pre-promotion-gate-blocked proposal (e.g. rr 1.99 < 2.0) was logged as
"CREATED #None" and counted as created (and passed a null id to enrichment) — now recorded as
SKIPPED_PREPROMOTION. (3) Added a monitor: a weekday run with 0 proposals from >0 eligible signals fires
a warning → SIEM/Telegram with the filter breakdown.

**Stage 2b canary console (operator UX).** Per-order approval relaxed to either channel; canary step
buttons auto-run preflight; one-action "type ticker → SUBMIT" submit; fixed a server-side hung Schwab
quote that made preflight time out (HTTP 000). Live execution still requires the operator's own
arm + typed-ticker + submit (the AI cannot place a live brokerage order — hard safety line).

## 2026-06-15 - Stage 2b approval: either channel (web ticker OR telegram), not both

Operator directive 2026-06-15: typing the ticker is enough fat-finger protection on its own — don't force
both channels. The per-order 2FA was `web typed-ticker AND telegram code` (both required). Now **either one
approves**: `brokers/approval_service.py` gains `REQUIRED_CHANNELS` (default 1, env
`TRADE_APPROVAL_REQUIRED_CHANNELS`); `is_fully_approved`/`consume` use `>= REQUIRED_CHANNELS` instead of the
hardcoded `>= 2`. Both channels are still requested and usable — only the threshold to count as approved
changed (set 2 to restore strict dual-channel). UI copy (`BrokerOrders.tsx`) + the telegram callback
messaging updated from "channel 2 of 2 / both channels" to "either channel approves". Note: approval is the
*last* gate — the pilot must still be ARMED (typed phrase) to open the db-control / write-flag / standing
locks before any submit.

## 2026-06-14 - Stage 2b draft list: ordered canary battery + scratch cleanup

Pre-canary tidy of the Manual ToS Desk → Broker Orders draft list. The "Draft order intents" list dumped
all saved drafts in store order, so the canary battery (GRAB 10sh, tagged `CANARY n/5` in `meta.thesis`)
was interleaved with 7 leftover ad-hoc "Active Trader panel" scratch drafts (3× V no-limit BLOCKED, 2× V
short BLOCKED by the long-only gate, 2× GRAB 2sh dupes) and showed no run order. (1) Deleted the 7 scratch
drafts via `/api/v2/broker-orders/delete` — only the canary 1→5 remain. (2) `BrokerOrders.tsx` now sorts the
list by `CANARY n/5` (battery first, in run order; scratch after) and renders a green **`RUN n/5`** step
badge so the execution sequence is unmistakable (only step 4 fills; 1/2/3 place→cancel, 5 closes flat).

## 2026-06-14 - Home Morning Brief render + SIEM stop-echo de-noise + weekend-aware staleness + Hermes report lane

Operator-reported broken Home page and a weekend alert burst (SIEM P1 STOP_TRIGGERED, 61h staleness page,
PFLT stop) — root-caused and fixed:

- **Home → Morning Brief rendered raw JSON.** `HomeHub.tsx` dumped `action_items`, `strategy_health`, and
  `overnight_activity` via `JSON.stringify` (the API returns clean structured objects). Now formatted:
  severity-colored action rows with code chips, strategy-health stat chips (Active / New / Stuck + stuck
  names), and an overnight-activity metric grid with a "quiet overnight" empty state.
- **SIEM P1 was self-noise.** `notification_log` (our own outbound Telegram messages) was re-ingested and
  re-classified at source severity — every stop alert we SENT counted as a P1 `STOP_TRIGGERED` event (38
  events / 1 group). Since every P0–P2 alert is detected upstream first (alert_events / open_trade_alerts /
  system_health), notification_log echoes are now demoted to **P3** + tagged `echo:true` + given a separate
  dedupe group. P1 immediate count: inflated → 0. (`api_v2.py` `_system_siem_dashboard`.)
- **Staleness paged every weekend.** The 26h threshold in `portfolio_orchestrator.py` fired on the expected
  Fri→Sun market-closed gap. Now schedule-aware: +24h per weekend calendar date in the gap, so a 61h
  weekend gap is suppressed while a genuine multi-day outage (97h) still fires.
- **Hermes report second-read lane stale since June 9 (two bugs).** (1) `gather_report` in
  `hermes_subject_enhance.py` globbed `data/portfolios/reports/*` and picked the newest path by mtime —
  which became the `weekly/` **directory**; `read_text()` raised `IsADirectoryError`, swallowed by a bare
  `except → return []`, silently zeroing the lane. Fixed: files-only, prefers the `aegis_morning_brief_*.md`,
  `errors="ignore"`, skips empty text. (2) There was **no cron schedule** for `--type report` (scalp /
  proposal / position / sector / closed_trade were scheduled; report was not). Added
  `0 8,20 * * *` (twice daily; `FRESH_HOURS=12` prevents double-calls). Lane refreshed — the "✦ Grok" Home
  badge now shows the current day. **Verified end-to-end under cron's exact invocation** (flock + log
  redirect): the call path produced a fresh Grok read, the skip path correctly de-duped within 12h. Audit
  confirmed `gather_report` was the ONLY gatherer with the glob→mtime→read trap; all others are
  DB-query-only or read fixed paths, and every other "newest file by mtime" idiom filters by extension first.

## 2026-06-14 - Portfolio Look-through tab + Ask-the-agents + multi-agent advisory

New Portfolio → **Look-through** tab: true stock-level exposure (funds resolved to underlying holdings via
yfinance fund top-holdings) with theme baskets (Mag7 / Nasdaq100 / S&P500 / Semis / AI mega-cap / AI
datacenter-power / Nuclear / Energy / Cyber / Defense / China), **fund-source tooltips** per stock,
per-account filter, a top-10 concentration donut, rule-based advisories + a **Grok narrative** + **CIO /
Risk / Steph agent cards**. Engine: `portfolio_lookthrough_themes.py` (cached, scheduled daily 07:40);
endpoint `/api/v2/portfolio/lookthrough`. **Ask-the-agents box** (`AskAgents` component + `portfolio_ask.py`
+ `/api/v2/portfolio/ask`): natural-language Q&A that pulls REAL positions + analyst ratings + look-through
and routes to Grok (e.g. "R:R of trimming 5% V to fund SpaceX?" → answered with the actual numbers). Ask
alerts (`ask_alerts.py`) fire to Telegram on IPO-news/price conditions. Added to RiskHub too.

## 2026-06-14 - Private-symbol handling + defer-to-live-data (SpaceX/SPCX)

`private_symbols.py` registry flags genuinely-private names (OpenAI/Stripe/Anthropic/Databricks) on
watchlist cards + the ask box. IMPORTANT correction: SpaceX IPO'd 2026-06-12 (SPCX, Nasdaq) — AFTER the
model knowledge cutoff — so it was wrongly flagged "private". Removed SpaceX/SPCX/xAI from the registry and
hardened the ask prompt to **DEFER TO LIVE DATA over training knowledge** (a name with a live quote IS
public). SPCX price was stale ($173 from IPO-day "ai_discovered"); fixed the repricer universe
(`external_market_data_ingest` now UNIONs directive-watch/active watchlist) + a yfinance fallback in
`watchlist_enrichment_sweep._price` so tracked/newly-IPO'd names stay priced. CIO re-reviewed SPCX
(IGNORE/gemma pre-IPO → AVOID 0.72/grok on the now-public stock).

## 2026-06-14 - IPO lockup tracker (S-1 from EDGAR) + alerts + auto-update

`config/ipo_lockups.json` + `ipo_lockups.py`: when insiders can sell, per the **primary S-1/A pulled from
SEC EDGAR** (SpaceX CIK 1181412 — three groups: 180-day w/ early releases, a ~63% EXTENDED group locked
into 2027, Musk 366-day no-early-release). Wired into the Ask box. `ipo_lockup_alert.py` fires Telegram
14d before each tranche (with price-conditional logic on the +10% bonus). `update_lockup_earnings_dates.py`
auto-snaps earnings-tied tranches to the real report date (earnings+2 trading days) when announced.
Scheduled daily 08:15/08:18.

## 2026-06-14 - Fixes: requeue, analyst-rating atomic write, family-aware protection

(1) Watchlist **requeue** was a silent no-op (id col has no default → INSERT rolled back while reporting
success); now resets jobs to pending + clears the synthesis gate (final_synthesis_status) so re-review
runs end-to-end. (2) `build_pro_analyst_read_model` now writes **atomically** — the non-atomic write
briefly blanked ALL Strong-Buy/Buy ratings on the watchlist mid-rebuild. (3) Open-Trades protection
framing is now **family-aware**: income holdings → "Income role, stop optional"; open-end mutual funds /
401k-proxy codes → "no exchange stop — trim/rebalance"; stop-eligible ETFs/stocks keep the advised stop.
`is_unstoppable_fund` extended to opaque plan codes. Allocation panel + header total/day-P&L now follow the
account filter.

## 2026-06-14 - Phase3 look-through: yfinance sector fallback (auto-classify any stock)

Root-cause fix for the 'Other' bucket: phase3 resolved direct stocks only from the snapshot's
classification fields, which are usually empty → real holdings (Visa, RTX, NEE, sector ETFs) fell to
'Other / Unclassified'. Added scripts/sector_cache.py — a yfinance-backed GICS sector lookup (equity
sector / sector-ETF category), normalized + cached to data/.../sector_cache.json (one network hit per
symbol, self-healing). Wired as phase3 _resolve_direct_stock's fallback before 'Other'. Validated by
REMOVING the 20 manual equity entries — phase3 still classifies everything (Other = $0). New holdings now
classify automatically; no manual_sector_map entry required for ordinary stocks/sector-ETFs.

# Changelog

## 2026-07-21 — Alpaca multi-account taxonomy R1–R5

Registry unification (interlock → broker_accounts + parity log), credential slots,
label hard-map to `tradeai_automated`, live scaffolds DISABLED, TradingView lanes doc + 503 stub.
Session: `docs/sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md`.


## 2026-06-14 - Sector allocation fixed (401k look-through + unclassified stocks)

The Portfolio Allocation showed 98%% "Other" — two bugs: (1) overview() aggregated a non-existent
per-row sector_type field [fixed: now uses holdings.json resolved_sectors look-through]; (2) the SnapTrade
401k opaque fund codes (OG51/3905/O7Z6…) and several real holdings (Visa, XLI/XLB, JEPI, defense names)
were unclassified. Mapped the 401k codes to Morningstar categories + same-fund GICS sector_weights
(config/snaptrade_401k_fund_map.json + scripts/apply_snaptrade_fund_map.py, durable/idempotent) and added
GICS sectors for the unclassified equities to manual_sector_map. Result: Other 23%% -> 0%%; portfolio now
classifies as Financial Services 22.8%%, Technology 19.3%%, Industrials 11.5%%, Healthcare 11%%, etc.

# Changelog

## 2026-07-21 — Alpaca multi-account taxonomy R1–R5

Registry unification (interlock → broker_accounts + parity log), credential slots,
label hard-map to `tradeai_automated`, live scaffolds DISABLED, TradingView lanes doc + 503 stub.
Session: `docs/sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md`.


## 2026-06-14 - SnapTrade read-only holdings aggregation (LIVE — Fidelity 401k + IRA)

Added SnapTrade as an additive, read-only holdings source for accounts with no direct API (the Fidelity
401k, previously faked with proxy ETF codes). End-to-end and connected:
- **Credentials**: SnapTrade keys live in the central API Keys & Secrets manager (`SNAPTRADE_CONSUMER_KEY`
  masked secret + `SNAPTRADE_CLIENT_ID` config) AND a dedicated Connect-SnapTrade modal on Schwab Accounts;
  unified on `.env`. Personal (`PERS-`) keys: userId/userSecret are dashboard-provided/rotated, not minted
  (registerUser is production-only) — both editable on the secrets page.
- **Read path** (`brokers/snaptrade_read.py`, SDK v11): list_accounts / positions / balances + normalize.
  No write/trade surface (read-only today; not hard-blocked for future trading per operator).
- **Sync** (`snaptrade_sync.py`): dry by default, `--apply` merges ONLY mapped accounts
  (`config/snaptrade_accounts.json`, gitignored) via `protected_holdings_write`. Scheduled 3×/trading day
  (9:50 / 13:00 / 17:35 ET). Vanished-account auto-zero after 2 consecutive confirmations (transient-safe,
  alerts) — makes the 401k→IRA rollover hands-off.
- **Repricing**: broker-sourced fund/opaque codes keep the broker value (no public quote); real exchange
  tickers reprice intraday from the quote cache.
- **`is_unstoppable_fund`** extended to opaque plan codes (digit/non-ticker symbols like OG51/3905) so the
  protection advisor + Open Trades framing never offer an exchange stop on un-stoppable 401k funds.
- Live result: real Fidelity 401k = $566,790 (10 positions), portfolio total $1,254,255, all aggregates
  consistent. Spec: docs/brokers/snaptrade-read-only-aggregation-spec.md.

## 2026-06-14 - Local model FLEET health check (pings every installed model)

New `scripts/check_local_model_fleet.py` — walks the WHOLE Ollama fleet from `/api/tags` and pings each
model (tiny prompt for generation, short input for embedding), recording ok / latency / failure-reason
per model. The old `check_local_llm_health.py` only exercised the single SAFE model (4b), which is why
gemma3:12b could rot unnoticed. Detects three failure modes: HTTP 5xx, timeout, and **degenerate output**
— the probe found gemma3:12b returns `<pad><pad>…` special-tokens-only (30s) rather than 500ing, so a
"non-empty response" was NOT enough; the check strips `<pad>/<unk>/<eos>/<bos>` and fails if nothing real
remains. CRITICAL models (derived from `DEFAULT_LOCAL_LLM_MODEL` ∪ `LOCAL_LLM_MODEL` ∪
`LOCAL_LLM_SAFE_MODEL` ∪ `CRITICAL_LOCAL_MODELS`, no hardcoding) → exit 1 + `critical` alert; any other
model failing → WARN + `warning` alert, exit 0 (a broken-but-unused 12b is surfaced, not silenced).
`--alert` writes an `alert_events` row (curated `system_health` type, `parsed_payload.kind=local_model_health`)
so it flows into the existing SIEM/Telegram monitoring. `LLM_HEALTH_SKIP_MODELS` excludes heavy models
(the two 17GB ones) from the probe. **Scheduled:** cron daily 06:35 pre-market with `--alert`.

## 2026-06-14 - REVERT local default to gemma3:4b (12b broken) + CIO queue prioritization

**Revert:** the gemma3:12b switch below was REVERTED (commit 0f219183). A grok-vs-12b A/B exposed that
gemma3:12b **HTTP-500s on every prompt** — even a one-line one, in 2s — so it's broken at the ollama
runtime (VRAM/model-load failure, not a context limit), while gemma3:4b runs cleanly. Leaving 12b as the
default would have 500'd every local-default LLM call system-wide. DEFAULT_LOCAL_LLM_MODEL is back to
**gemma3:4b**; re-pull/fix 12b (`ollama rm gemma3:12b && ollama pull gemma3:12b`, check VRAM) before
retrying. The CIO-quality win comes from the **free Grok synthesis lane**, not 12b — and Grok "won" the
A/B by default since 12b couldn't run.

**Queue prioritization (commit 50ec6564):** the CIO job picker no longer drains the ~3,000-name backlog
FIFO. It tiers via EXISTS subqueries — directive-watch (0) → active (1) → BUY/STRONG_BUY card (2) → tail
(3), then priority, then created_at — so the ~50 names the operator cares about refresh first and the
long tail no longer starves them. Re-run cadence unchanged: 48h staleness → aegis queues → cron drains
5–10/run; decisions expire at 14 days.

## 2026-06-14 - Local LLM default → gemma3:12b (policy primary; was 4b)  [REVERTED — see above]

DEFAULT_LOCAL_LLM_MODEL switched gemma3:4b → gemma3:12b (installed, 8.1GB) so the specialist agents
(Maria/Steph/Risk) and all local-default consumers use the sharper 12b — matching the standing model
policy (12b primary, 4b fallback). Slower per call but better reasoning; per-process env keys still
override. CIO final-synthesis remains on free Grok OAuth (separate, committed prior). Directive +
buy-rated names' CIO View refreshed on Grok to reflect the upgrade immediately.

# Changelog

## 2026-07-21 — Alpaca multi-account taxonomy R1–R5

Registry unification (interlock → broker_accounts + parity log), credential slots,
label hard-map to `tradeai_automated`, live scaffolds DISABLED, TradingView lanes doc + 503 stub.
Session: `docs/sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md`.


## 2026-06-14 - CIO synthesis → free Grok OAuth (local fallback) + prompt versioning

The watchlist CIO View (final synthesis) was running 100% on gemma3:4b (verified: 323 syntheses / 7d,
0 Claude/Grok) — the smallest local model, hence loose decisions. Switched ONLY the final-synthesis
stage (the one call per symbol that becomes the CIO View) to the free **Grok OAuth** lane (llm_lane)
with local gemma fallback; the 3 specialist agents (Maria/Steph/Risk) stay local. Also FIXED a bug:
model_used was hard-coded to OLLAMA_MODEL regardless of what ran — now records the actual model.
Added prompt versioning: SYNTHESIS_PROMPT_VERSION stamp in the prompt + integer synthesis_version=2
stored per row. Proven live: CIFR re-synthesized on grok-3-mini — grok flagged an agent conflict +
returned AVOID (vs gemma's HOLD), the sharper read. Both lanes free; no metered API.

# Changelog

## 2026-07-21 — Alpaca multi-account taxonomy R1–R5

Registry unification (interlock → broker_accounts + parity log), credential slots,
label hard-map to `tradeai_automated`, live scaffolds DISABLED, TradingView lanes doc + 503 stub.
Session: `docs/sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md`.


## 2026-06-14 - Entry planner expanded to BUY-rated researched pool (pre-promotion plans)

watchlist_entry_planner now plans entry+stop+exit-ladder for the strongest BUY-rated RESEARCHED names
in addition to directive/active — so the ~195 candidates that showed $0.00/no-plan now get an entry
plan once they're a confident BUY, before promotion. Bounded HARD to avoid 400 LLM calls: only
BUY/STRONG_BUY (watchlist_research_cards.latest_recommendation) · CIO confidence ≥0.80 · top-N by
hermes score (--buy-rated-cap, default 20) · skips anything planned in the last 3 days so the cron
ROTATES coverage. Pre-promotion buy-rated names are planned but do NOT Telegram-alert (no-noise rule)
— they alert once promoted to an active watch/directive. Proven: DGXX(directive)+DY+HGV(buy-rated)
all got plans; only the directive name alerted. Disabled when a --symbols filter is used.

## 2026-06-13 - Holdings wired to trailing families → per-family stop widths (no "unclassified")

holding_family.py maps each holding to a trailing family (momentum/swing/income/position) by REUSING
the existing config/asset_classification_rules.json bucket_overrides (dividend_income/bond_income→income,
swing_trade→swing, growth_fund/defense→position) + asset_type + volatility fallback — zero new
per-symbol hardcoding. Each family carries a STOP/TRAIL width band (momentum 2-6% … position 5-12%).
The protection advisor now injects the family's bands + a family-specific fixed-vs-trailing rule into
the (already-bounded) prompt, and the sanity gate validates against the family's max. Family + source
stored in evidence, surfaced as a chip on the Open Trades card (replaces "unclassified"). PROVEN live
via free Grok: KTOS[swing] 8% stop · LMT[position] 5.6% · BND[income] 1.4% (anchored to low-vol
structure). This is the WIDTH layer; strategy_trailing_policy's R-tiers remain the WHEN-to-tighten layer.

## 2026-06-13 - Protection advisory: sanity gate + bounded prompt + free Grok OAuth (root-cause fix)

The display clarity fix made loose LLM advisories visible (ARKG 15% stop); this fixes the SOURCE.
(1) BOUNDED prompt (holding_protection_advisor PROMPT_V1): stop must be below price, anchored at/below
the 20d swing low, distance 1-12% (cap at 12% if swing low is further), stop_pct_below must equal the
computed value; explicit FIXED-vs-TRAILING rule (trail only if unrealized ≥+10% AND price>SMA50, else
fixed) — answers "do we categorize first": the fixed/trailing choice is now derived from profit-state
+ trend, no separate long/short/swing classifier needed; trail is PERCENT-only (3-10%), no ambiguous
$/ATR offsets. (2) _sanity_check validates every output against the real technicals (stop-below-price,
claimed-vs-actual %, reachable-swing-low anchoring, distance + trail bounds) → verdict ok/warn/fail
stored in evidence + surfaced as "⚠ check advisory" / "⛔ unreliable advisory" on the card. (3) default
lane → free Grok OAuth (tighter than gemma3:4b), local fallback. PROVEN live: gemma3:4b emitted an
inconsistent stop (gate flagged it); grok under the bounded prompt emitted a clean one (gate ok).

## 2026-06-13 - Stop/trailing-stop clarity across Open Trades + Proposals (consistent w/ Watchlist)

Open Trades protection advisory was garbled ("trail 0.3$1.04% above advised stop" — mixed %/$/ATR
units, run-together fields). Rebuilt PositionDecisionCard to render from STRUCTURED fields (not the
free-form string): stop $X.XX with % vs price, trail shown as BOTH $ and % (so $0.30 vs 0.3% can
never be confused), clean "price N% above stop" separator, +"⚠ wide stop" flag when the advised stop
sits >12% below price. Backend holding_protection_advisor string fixed ($ before value, not suffix).
Proposals (ProposalsRich) now carry the SAME layered exit ladder + plan-sanity warnings as Watchlist
(T1/T2/T3 + trailing + monitoring rules via lib/exitLadder), plus stop-distance % and inline R:R.
All three surfaces — Watchlist, Open Trades, Proposals — now speak one clear stop/trailing language.

## 2026-06-13 - Zero-shell arming: UI Arm/Disarm via auto-expiring DB session (operator choice)

Monday 2026-06-15 pilot is now 100% UI — no shell. The shell env-flag "physical key" is replaced by
an auto-expiring DB armed session (system_controls['pilot_armed_until'], ~6h, capped at session-day
end): _live_future_unlocked accepts env-flag OR unexpired session; arm()/disarm() set/clear it +
control row + standing approval + api_write_enabled(taxable). New POST pilot/arm + pilot/disarm
(typed date-phrase) and Pilot Console ARM…/DISARM buttons (typed-phrase modal). SAFETY POSTURE
MOVES, doesn't vanish: the two-surface protection shifts from arm-time to EXECUTE-time — per-order
Telegram 2FA (second device) still gates every submit, so a UI click alone places nothing; plus
typed phrase, ≤$4/$40 envelope, 5-order cap, AND the session auto-expires / any restart fails safe
to disarmed (operator accepted that the web UI can now open the armed window). Disarmed at rest;
canary 26/26; write-policy 26 guards. (Trade-off acknowledged: web UI alone can arm the window.)

## 2026-06-13 - SB-2: full single-leg canary battery executable via API (Monday 2026-06-15 session)

Expanded the Stage 2b pilot from BUY-LIMIT-only to the full 5-shape battery, all single-leg, all via
the API console (no fragile OTOCO): buy_cancel (BUY LIMIT below-mkt, place→cancel) · real_fill (BUY
LIMIT @ask, ~$33 fill) · protective (SELL STOP GTC) · trailing (SELL TRAILING_STOP GTC) · close (SELL
LIMIT @bid). Canary date re-pointed 06-13(Sat)→**06-15 Monday**. SAFETY: canary gate now counts
entry.stop_price so STOP shapes are envelope-bounded (every committed price ≤$4, qty×max ≤$40) — even
SELL/STOP/trailing can't escape; a true MARKET entry still blocks (no committed price). The $40
envelope means even a worst-case error caps at ~$40. New builders make_battery_spec/make_battery_intent
(preflight); pilot/preflight accepts a `shape`; execute path unchanged (generic spec). UI: Pilot
Console battery = 5 single-leg presets, param field adapts (limit/stop/trail), live bid/ask pulled for
fill/close. Validator +1 guard (battery shapes envelope-bounded; in-env allow, >$4 buy/stop + >10sh
block) → 26 guards. Tests: canary_gate 26/26 (section-2 now date-pinned for envelope isolation).
Still: taxable-only, api_write_enabled, standing locks, pilot 5-cap, per-order 2FA, disarmed at rest.

## 2026-06-13 - Backtest: STOP-V2.4 vs V2.3 A/B (proves expectancy before config flip)

backtest_hybrid_stops.py — read-only A/B over 20d-breakout entries, both policies through the REAL
recommend_stop (overlay fed POINT-IN-TIME levels, no lookahead). 3y / 6 names (V/RTX/LMT/NOC/GD/PLTR):
aggregate V2.4 expectancy +0.535R→+0.637R, PF 2.17→2.75, maxDD −7.0R→−6.04R (PROMOTE on aggregate).
BUT mixed per-symbol: better on V/RTX/GD/PLTR (RTX PF 3.1→10.25), WORSE on LMT (1.134→0.815R) and
NOC (0.765→0.699R); whipsaws 23→28. Honest read: helps most names, hurts some — promote PER-FAMILY/
per-name, not blanket. Config stays OFF pending operator decision. Advisory; no orders/config writes.

## 2026-06-13 - STOP-V2.4: structural trailing overlay (MA-trend / chandelier / dynamic-mult, default OFF)

Augments the R-multiple trailing (strategy_trailing_policy.py) with structure-aware stops instead of
building the redundant parallel `stop_trailing_engine` a pasted spec proposed (~70% of which already
existed: indicator_engine has ATR/EMA/SMA/ADX, trailing_stop_analysis is the audit table, qwen3 is
dead → gemma). Three new algos, config-gated per family in config/stop_trailing_hybrid.yaml
(master `enabled: false` by default): **ma_trend_filter** (only tighten in confirmed uptrend, defer
in chop), **chandelier** (highest_high(N)−mult×ATR), **dynamic_multiplier** (widen on high ADX /
near MAs, tighten when ranging). SAFETY: overlay can only RAISE the stop above the R-multiple
baseline, never lower it, never above price; disabled ⇒ byte-identical V2.3. Structural levels reuse
indicator_engine._fetch_ohlcv (one data path); unified_stop_supervisor passes symbol= to enable it.
CLI preview: `strategy_trailing_policy.py SYM STRAT ENTRY PSTOP CSTOP CPRICE` (forces overlay on for
A/B). Advisory; no broker write path touched; paper-first. Tests 15/15 (12 V2.3 unchanged + 3 V2.4:
default-off no-op, tighten-only invariant, no-order-symbols). Verified: V swing R=2.2 → overlay
tightens $310→$314.58 (chandelier+ma_trail+dyn_mult 2.93); losing/chop position holds.

## 2026-06-12 - SB-1: Schwab write pilot built (fenced), validator rewritten to write-policy

Operator-approved Stage 2b: SB-0 proved the "sandbox" is NOT a sandbox (same app/keyset returns
all 3 real accounts) -> pilot proceeds live-tiny under the committed $4/$40 canary envelope,
session day 2026-06-13. SB-1 ships the ONE write path: schwab_transport.place_order/cancel_order
behind taxable-only structural assert + api_write_enabled + execution_guard (canary gate ->
standing locks env/db/approval -> brokers/pilot_caps.py commit-only 5-order cap -> per-trade 2FA
web-typed-ticker + telegram, single-use, one-order-at-a-time); replace stays fenced; pilot row
persisted BEFORE POST (no-dedupe reconcile anchor). Arm/disarm via schwab_pilot_arm.py
(typed-phrase). API: broker-orders/pilot/{status,preflight,execute,cancel}; UI: Pilot Console in
v3 Trading->Broker Orders (reuses ApprovalPanel 2FA). Validator REWRITTEN:
validate_schwab_write_policy.py (25 guards; new: write-stack static+runtime proofs, pilot-caps
behavior, 2FA deny/grant matrix, tamper-evidence gate-modules-match-git-HEAD; old file = shim).
Everything fail-closed disarmed; armed still requires per-order canary envelope + 2FA.

## 2026-06-12 - Layered exit ladders end-to-end + Manual ToS account cash fix

Entry plans now carry a LAYERED exit, not a single capped target. Deterministic ladder (T1 +1R
sell-1/3 + stop->breakeven; T2 plan target sell-1/3 + trail to T1; T3 Street-mean runner with 1R /
prior-day-low trail) + in-trade monitoring rules, computed with IDENTICAL math in three places:
`watchlist_entry_planner.py` (`_exit_ladder`, stored in plan JSON + Telegram entry alerts, both
watchlist and proposals scopes) and `command-center-v3 lib/exitLadder.ts` (shared), rendered on the
Manual ToS desk and Watchlist cards with plan-sanity warnings (no-stop, R:R<1 reject / <1.5 thin,
plan-target-caps-below-Street-mean keep-a-runner, price-above-Street-mean no-headroom, notional >
100% of cash oversized). Desk exports (JSON/HTML) carry exit_ladder/plan_warnings/monitoring_rules.
Also: `/api/v2/schwab/accounts-live` now returns read-only cash/buying_power/account_value per
account (transport get_account; balances_status honest on failure) and ManualTosDesk `anyNum` no
longer coerces null->$0 — selected accounts show real cash/BP and %-of-account sizing. Advisory
only throughout; validator 18/18 green.

## 2026-06-12 - SSOT BASIS SHIELD: root fix for basis reverts, enforced at Gate B

Whodunit closed structurally: rather than chasing which of the interleaved 15-min pipelines reverts
corrected basis (two writers alternate on holdings.json; reconstruction has no callers; loader
reads-not-rebuilds — the culprit will now NAME ITSELF), basis stickiness is enforced at the ONE
write gate every holdings writer funnels through (protected_holdings_write; holdings_guard
re-exports it). Rows with cost_basis_source in (csv_lot, broker_api) cannot have their VALUES
changed by any writer except broker_basis_sync: the gate restores the protected value, recomputes
gain fields, and logs 'basis_shielded [writer-source]' to schwab_sync_history — so the reverting
pipeline is identified on its next attempt. PROVEN: simulated 4-row revert via the gate -> all
restored + logged with writer name; legitimate SSOT-sync update passes. Fail-soft. Validator 18/18;
audit 0/38 clean. The 16:33 self-heal cron stays as a second belt.

## 2026-06-12 - Basis-audit alarm cycle closed + canary session record + server backlog live

Basis audit re-run post-restart: **0 flagged / 38 clean**; server backlog-128 patch confirmed live
(queues under load instead of dropping). Defense stack: 16:33 daily basis self-heal -> 16:35 audit
alarm (env-sourced, honest-skip on API-unreachable). OPEN: repricer root fix (reads stale basis
inputs; reverts SSOT values — self-heal compensates daily until fixed).

Canary session record (stage2a-reconciliation-log.md): watchers ran live ~4h with clean read-backs;
draft 1/5 two-channel approved (fully approved -> still BLOCKED ✓); NO orders were placed in ToS —
session superseded by the Manual ToS Desk build, which formalizes the same workflow. Gate allowlist
auto-expired end-of-day by construction. Harness TODO: md logger should append only NEW/changed
orders (idle polling grew the log to 5,620 repetitive lines; truncated to the honest record).

## 2026-06-12 - Manual ToS Desk tab live + orchestrator STALE root-caused (failed cron retirement reverted)

**Manual ToS Execution Desk:** desk built across sessions (661583e9 et al); Trading hub gains the
'Manual ToS' tab (85cc7b97 — safe patch, all 9 original tabs preserved). Workflow: Trade AI prepares
ToS setup tickets -> operator executes manually in thinkorswim -> Schwab READ-ONLY activity
recognition confirms. No submit/send/place/cancel endpoints anywhere (no-execution grep clean);
validator 18/18; build green. NOTE: two Stage-2b API-write prompts arrived alongside and were
DECLINED this pass — they contradict the Manual ToS safety rules; a write-path threshold change
needs its own unambiguous order.

**Orchestrator STALE root cause:** 06-11's 'cadence fix' RETIRED the 0900/1000 orchestrator crons
as 'redundant (continuous_runner covers 04:00-11:00)' — but continuous_runner does NOT emit the
0900/1000 run artifacts (run_summary/LAST RUN/dashboards), and the health monitor's expectation
(0 9,10,12,14,16) was never updated -> real morning gap + STALE alarm; 0 proposals 'today' was
CORRECT downstream behavior (453 scans, 0 GO, 32 WAIT — generator fires on GO only, 0 errors).
Recovery: manual 0900 backfill ran clean; 1200/1400/1600 fired on their own crons (full ledger
0400-1600 today). FIX: failed retirement REVERTED — 0900/1000 cron lines restored per the
documented restore path, annotated with the reason.

## 2026-06-12 - Buy-process audit fixes: account selector in Edit modal + account badge on draft cards

Operator audit caught it live: the Edit modal carried account_key INVISIBLY (selector existed only
on the Active Trader panel) and draft cards displayed no account — breaking the runbook's per-order
panel==ToS account tick. Edit modal now leads with an amber 'ACCOUNT (must match ToS!)' select;
every draft card wears its account badge. All 5 staged canary drafts verified schwab_taxable.
Also clarified in-session: 'superseded' approval chips = consumed by this morning's live Part-C
verification (correct); Request approval issues a fresh pair at session time.

## 2026-06-12 - Stage 2a runbook hardening: order-5 short-safety (position-quantity) + wide OCO bands + abort-with-position

Doc-only. The oversell guard caught a LINGERING child but not a FILLED one — with ±2% bands a
target child can fill mid-test, flatten the position silently, and a blind closing sell opens the
same unintended SHORT by another path. E1: order-5 guard is now POSITION-QUANTITY-BASED — closing
sell only when position == +10 long AND zero working sells; if already FLAT (a child filled) the
session is DONE, do NOT sell. E2: order-5 OCO bands widened ±2% -> ±5-8% with the explicit note
that order 5 proves children ARM, not fill. E3: ABORT section gains the open-position case — abort
after order 4 means holding ~10 real unmanaged GRAB; manually flatten in ToS (same short-safety
check) and confirm flat before standing down. In-panel draft-5 cheat note synced to match (data
row, not code). No code/config/test changes; execution stays BROKER_DISABLED; validator 18/18.

## 2026-06-12 - Stage 2a PRE-SESSION PATCH: runbook oversell/token/account guards + gate date auto-expiry + approval verified live

**Runbook (stage2a-session-runbook.md):** A1 BLOCKING oversell guard before order-5's closing sell
(zero-working-sells must be VERIFIED via read-back — a lingering OCO child + closing sell = selling
20 vs 10 owned = unintended short); A2 token-freshness as a blocking green-light precondition
(known-fresh re-auth, never coasting toward 7-day expiry); A3 panel-account == ToS-account as a
PER-ORDER checklist tick (mismatch = false-FAIL reconciliation + wrong-account risk).

**Gate auto-expiry (canary_gate.py, commit-only):** CANARY_SESSION_DATE='2026-06-12' — allowlist
honored ONLY on that date; any other date (or an unreadable clock) treats it as () fail-closed, so
a forgotten post-session rotate-back can never leave the envelope armed. Tests 23->26 (on-date
passes, off-date 'allowlist EXPIRED', clock-failure fail-closed); validator 17/17 -> 18/18.

**Two-channel approval VERIFIED LIVE (Part C):** real Telegram sent to the proposals chat with the
Tailscale deep-link (/v3/trading?tab=Broker+Orders&intent=<id>); web click-only REJECTED; typed
'GRAB' CONFIRMED; telegram one-time code CONFIRMED -> FULLY APPROVED -> guard submit still
BLOCKED (BROKER_DISABLED) -> approvals superseded clean. The future-execution safeguard works
end-to-end while harmless. Execution remains BROKER_DISABLED; no writes anywhere.

## 2026-06-12 - CANARY SESSION SCREEN RUN + ALLOWLIST COMMITTED (GRAB primary / XRX fallback)

Operator-ordered screen per stage2a-canary-protocol: price $2-4 · vol >=5M · ZERO footprint
(holdings / watchlist / paper / journal / ledger). PRIMARY **GRAB $3.37** (51.2M avg vol, 0.6%
spread even after-hours, superapp mega-name) · FALLBACK **XRX $3.45** (6.3M, NYSE household name).
Screened out live: VIDA drifted to $4.20 (above cap mid-screen), ABEV/BBD/CIG (footprint),
LYG/ERIC (>$4). `CANARY_SYMBOL_ALLOWLIST = ("GRAB","XRX")` committed into canary_gate.py with the
full rationale; gate verified live (GRAB 10sh@$3.40 in-envelope, @$4.05 BLOCKED 'price > $4 cap');
gate tests 23/23 (resting-empty contract kept as patched assertion); validator 17/17; execution
remains BROKER_DISABLED — the allowlist arms nothing. Session reminders encoded in code+protocol:
re-verify spreads at the open (AH quotes), ROTATE allowlist back to () by commit post-session.
Remaining pre-session: fresh OAuth · start shadow-recon + activity-capture watchers · draft each
order in the panel first · manual ToS placement 11:30-14:00 ET, one at a time.

## 2026-06-12 - Home/overview truth fixes + analyst honesty correction + Today's-Move-by-account

**Analyst sources (operator question + correction):** abbreviations spelled out everywhere
('N analysts', 'target $X', 'targets only'). HONEST CORRECTION after live verification: the planned
"Finviz second opinion" was RETRACTED — finviz recom fields system-wide are target-distance math,
not a 1-5 rating (values like 517.84 produced 19 false divergence flags; the old read-model warning
was right; no true finviz Recom is captured anywhere). Yahoo = the only true rating source; the
real second layer shipped instead: Yahoo's analyst VOTE DISTRIBUTION (strong-buy/buy/hold/sell
counts from analyst_data_history) in every analyst tooltip. Polygon noted as the clean path to a
genuine second rating source if wanted (key already validated).

**Today's Move by account (operator request):** overview() returns today_by_account (change / pct /
value / top-2 movers per account); the TODAY metric drill lists accounts biggest-mover-first
(verified: rollover +$2,024 · fidelity +$1,185 · taxable +$654 · roth +$303).

**Home page truth fixes (operator: 'fix missing info'):** Weekly Movers showed 0.0% forever —
backend sent perf_week, UI read change_pct (field mismatch) + no symbol dedupe (double V); now real
values, deduped, '(1w)' labeled, funds included via the proxy snapshot fallback. AI Intelligence
Briefing rendered raw {"content":...} JSON — now parsed to full-width prose. 'sector: AMSS' stub
rows filtered from Portfolio News. BONUS root cause: pipeline_runs.run_completed_at NEVER existed
(column is finished_at) — the freshness query errored on every morning-command load since
inception; fixed, now 'All systems operational'.

## 2026-06-12 - Unified card layer: company sentence + sector-vs-sector + analyst + top-3 news on ALL cards

Operator: every card on Watchlist / Open Trades / Portfolio shows sector + performance vs sector,
one sentence on what the company does, analyst rating + predictions, top-3 latest relevant news.
- symbol_profiles table + build_symbol_profiles.py (yfinance longBusinessSummary first sentence —
  two when the first is just the company name; sector/industry; proxy fund codes get their
  asset-class label; 86/88 universe profiled; weekly refresh cron Sun 19:00).
- /api/v2/symbol-cards: ONE map for all three surfaces — description · sector + ETF (yfinance->GICS
  alias fix: 'Financial Services'->XLF) · week perf vs sector ETF · analyst consensus
  (rating/mean/opinions/targets/upside) · top-3 relevant news (14d, recency+relevance ranked,
  linked, sentiment carried).
- UI: Watchlist cards gain the full info block; Portfolio holding cards gain description/sector-vs/
  analyst line/news; Open Trades cards gain the description + vs-sector line (sector/analyst/news
  already present there).

## 2026-06-12 - Proposals get the watchlist treatment: inline grok entry validation + entry-zone tile; buys curated; dead-qwen warm fixed

**Inline (operator: "not weekly — grok reviews when a proposal is created"):** auto_proposal_generator
enrichment Step 5 now runs watchlist_entry_planner --scope proposals --lane grok per new proposal —
zone/limit/urgency/WAIT-READY tag written advisory-only at creation time (falls back local if proxy
down). Weekly cron removed. ALSO FOUND: enrichment Step 2 was warming hardcoded 'qwen3:14b'
(DISABLED + uninstalled) — silently failing on every proposal since qwen removal; now warms the
CONFIGURED primary model (local_llm_config). Proposal cards gain a 🎯 Entry Zone tile (range like
the watchlist: zone low-high · limit · urgency · tag · model); /api/v2/paper-proposals LATERAL-joins
the latest entry plan.

**Buy/strong-buy curation (operator order):** --symbols flag added to hermes_top20_external_intel;
grok ran ALL 29 buy/strong_buy watchlist names (19 called + 10 already-fresh = 29/29 ✦ badged).
ChatGPT lane root-caused: CODEX_HEADLESS_UNAVAILABLE was the ChatGPT-subscription usage cap (7 calls
then throttled; auth was fine) — detached retry self-fires after the cap window, skipping
already-sent names.

## 2026-06-12 - Entry Strategy pipeline + canonical watch universe + enrichment-coverage auditing agent

**Watchlist Entry Strategy (operator requirement, ADVISORY ONLY):** scripts/watchlist_entry_planner.py
+ watchlist_entry_plans table — per watch-grade symbol: entry thesis, typed setup (pullback/breakout/
support-bounce/reversal), entry ZONE + realistic limit, objective pullback definition + invalidation,
structural stop/target/R:R, urgency (watch/near_entry/ready, price-in-zone upgrades honestly),
proposal advice tag (WAIT/READY/NEEDS_CONFIRMATION — never queues/executes). Telegram entry alerts
(ticker/zone/limit/reason/urgency, 20h dedup). --scope proposals VALIDATES pending proposals' entries
against live structure (proposal untouched). First run: 5/5 directive symbols planned, 5 alerts.
Crons: watchlist 17:35 + proposals 17:45 M-F. Watchlist cards: 🎯 entry chip (zone·limit·urgency,
full plan tooltip); items endpoint LATERAL-joins latest plan. local_llm num_predict env-overridable
(300 cap truncated strict-JSON outputs).

**Root cause + the agent that checks the checkers (operator order):** scripts/watch_universe.py =
THE canonical watch-grade universe (held + paper-30d + pending proposals + GO/WAIT + active +
DIRECTIVES regardless of status/rank — operator directives outrank scores, encoded once).
scripts/audit_enrichment_coverage.py audits EVERY enrichment surface (technicals/analyst/news/LLM
curation/protection advisory/synthesis-failures) against that universe daily 16:45 w/ Telegram on
directive gaps. First pass honestly flags directive news_7d (fix lands next ingestion cycle) +
CIFR synthesis retry (re-queued — the dead-qwen 'LLM error: All providers failed' era: 409 stale
failure rows found, current-universe = only CIFR; agents re-run on gemma). pro-analyst read model +
fetch universes patched (CIFR strong_buy 16an $32 +41.4% now pills on the card); analyst-rating
filter pills added to Watchlist hub; psycopg2 LIKE-% bug fixed in audit.

## 2026-06-12 - FULL-portfolio arbitration COMPLETE (39 symbols) + directive-universe fix (analyst/news/LLM curation)

**Full sweep finished, free lanes first:** gemma 39/39 -> grok 39/39 -> ONE Anthropic arbitration
(superseded the earlier 10-symbol run): **39 symbols, 102 input recs, 9 systematic patterns** —
gemma trails LOSSES on 15+ underwater positions (trailing protects profits, not losses), places
stops AT swing lows (fills on normal retests) and even ABOVE stated support (LMT/NOC/TDG), plus
field-mapping data errors; grok graded systematically strong on ATR calibration (1.5-2.5x below
swing lows) with a minor trail-on-marginal-profit weakness; cross-cutting: neither model integrates
analyst-target distance or gain-magnitude/tax-lot sensitivity into trail aggressiveness. 39 CLAUDE
verdict rows -> badges on every advised card. Meta-review input compression + 8k output so a
full-portfolio review can never truncate mid-JSON.

**Directive-universe fix (operator: "why only one showing grok, no analyst, no news"):** three
enrichment pipelines each picked their own universe and operator-directive symbols (status=
'researched', rank 326/1172/1627) fell through ALL of them. Principle now encoded: OPERATOR
DIRECTIVES OUTRANK SCORES — pro_analyst_fetch + news_ingestion + hermes_top20_external_intel all
include in_directive_watch=true regardless of status/rank. Analyst data fetched immediately:
CIFR STRONG_BUY 16an target $32 (+41%) · DLR BUY 29an $218.72 · AXTI BUY 4an $96.50. ChatGPT+Grok
watchlist curation (top-20 + directives) launched. curate-top20 endpoint sys-import bug fixed.

## 2026-06-12 - FULL-portfolio LLM coverage + structured advisory chain (approve->draft->Schwab-ready) + fidelity proxy technicals

**Fidelity funds wired through proxies:** holding_proxies.py = single source of truth for the
fund->ETF map (was inlined in api_v2); technicals_gap_backfill fills FID-CONTRA-F/SP500-D/TRP-LVAL/
SS-SMMD/WM-BLAIR/AB-DISC-Z/FID-DIVINTL/SS-GACEQ/JPM-LGCG under the FUND code (source='proxy:<ETF>',
explicit asset-class caveat); open_trades_intelligence joins proxy-mapped codes -> all 10 401k funds
now show RSI/SMA/trend; their false 'data stale / RSI missing' CRITICALs clear.

**Full sweep (operator-ordered, free lanes first):** advisor floor 500->100, default limit 50,
per-symbol dedupe (V/SCHD/SCHG multi-account), 401k positions included with reframed prompt (stop =
NAV ALERT level for manual trim — stop ORDERS impossible in a 401k; proxy noted). gemma local
39/39 -> grok full sweep -> ONE Anthropic arbitration (operator-authorized).

**Structured advisory chain (future wiring: approved -> draft OrderIntent -> Schwab L4 -> monitor):**
/api/v2/portfolio/llm-coverage now returns NUMERIC stop_price / trail_type / trail_offset /
current price / **stop_distance_pct** per symbol + structured claude_verdicts (verdict_stop/trail,
agrees_with). Position cards show live 'X% above advised stop' (red <2% / amber <5% / green) and
'⛔ BELOW advised stop'. Everything stays ADVISORY — the approve/send legs are a future gated phase
on the existing dormant broker-orders rails.

**LLM holdings schedule (operator-approved, all installed):** daily 16:30 technicals checker ·
16:35 basis audit · 17:05 gemma full advisory (M-F) · WEEKLY Mon 17:20 grok full sweep ·
MONTHLY 1st 08:10 Claude arbitration. Free lanes always run first; Anthropic is monthly-only.

## 2026-06-12 - LLM sweeps RAN + monthly Claude arbitration + live API-key validator

Sequencing honored: data gates first (basis 0-flagged, technicals backfilled), then FREE lanes, then
the single metered call. gemma local 12/12 -> grok OAuth 12/12 -> Claude monthly meta-review
COMPLETED (10 symbols, 24 input recs): 7 systematic patterns (gemma trails 0.5-1x ATR too tight;
stops AT swing lows not below; grok ATR rounding; no trail-activation triggers on underwater
positions) + per-symbol verdicts -> claude lane rows (CLAUDE badges live). Root causes fixed along
the way: dead ANTHROPIC_API_KEY (admin showed 'set'-green while 401ing — operator rotated) and
_try_anthropic's 1024-token cap truncating the arbitration JSON (meta-review now calls Anthropic
directly at 4096).

**Live key validator** (operator-requested after the dead-key lesson): scripts/secret_validators.py
(15 providers, cheapest authenticated pings, key material never returned/logged; 402/429 =
quota_or_billing not invalid; Schwab/SMTP etc = not-validatable-by-ping, proven in their own flows)
+ POST /api/v2/admin/validate-secret + SecretsManager UI: 'Validate all keys' button, per-key
VERIFIED/INVALID/QUOTA chips, and VALIDATE-ON-SAVE so a dead key can never sit green again.
First sweep findings: BRAVE 402 (plan lapsed), NEWSAPI 429, FMP 403 INVALID, GEMINI not set,
12 keys verified.

Also: technicals_gap_backfill.py + 16:30 checker cron (operator-approved); delisted assets marked
once then ignored; expanded position cards show FULL news text; advisor yfinance bars fallback.

## 2026-06-12 - Portfolio holdings cards + LLM provenance/protection advisory + watchlist service-at-creation fix

**Portfolio Holdings redesign (operator request):** table -> large graphical cards (signal-colored left
border, account badge, value + P/L%, % -of-portfolio bar, RSI chip), signal sub-tab filters
(All / Buy-Add / Hold / Watch / Trim-Sell with counts), pagination 12/page, analyst pill retained.

**LLM provenance + protection advisory (operator request):**
- /api/v2/portfolio/llm-coverage — per-symbol 30d badges: which lane reviewed it (GEMMA local /
  GROK / GPT / CLAUDE), tooltip = model · date analyzed · review count. Status today: gemma local
  1,100+ reviews (active); Grok OAuth ACTIVE (264 sent, grok-3-mini); ChatGPT PARTIAL (21 sent,
  23 unavailable — OAuth gaps); Anthropic NOT yet enhancing (no lane traffic; fallback-only).
- scripts/holding_protection_advisor.py — curated versioned prompt (technicals ATR14/RSI14/swing-low/
  SMA50 + Yahoo analyst targets) -> strict-JSON stop / trailing-stop advisory per held equity; lanes
  local gemma (default) / grok; stores hermes_research_intelligence research_type='protection_advisory';
  🛡 chip on Portfolio cards with full tooltip. ADVISORY ONLY.
- scripts/monthly_protection_meta_review.py — monthly Claude arbitration of the month's gemma/grok
  protection recs ("fable-5 weighs in"): writes monthly_llm_meta_reviews + per-symbol claude-lane
  verdicts (lights the CLAUDE badge). Anthropic call is monthly by design.
- Proposed crons (await operator OK): basis audit 16:35 M-F · protection advisor 17:05 M-F (local) ·
  meta-review 1st of month 08:10.

**Watchlist workflow fix (operator caught CIFR missing):** root cause = watch_directives_service cron
is market-hours-only (every 30m, 9-16 M-F); a 22:47 ticker add sat unlinked + invisible until 09:00
with zero feedback. Fix: POST /api/v2/watch/directives now services TICKER directives synchronously at
creation through the same evaluation engine (directive_promotion.promote_directive_lead, auto=True;
cron stays as safety net + handles sector/trend discovery); Add-Watch modal reports the immediate
outcome (PROMOTED / staged / watching-no-qualify). Items endpoint joins watchlist_symbol_master ->
💼 HELD badge on watchlist cards (watchlist↔holdings overlap visible). CIFR + AXTI verified pinned
at the top of /api/v2/watchlist/items.

## 2026-06-12 - CRITICAL DATA FIX 2: cost-basis single source of truth (operator caught SCHG +108% phantom)

Operator question ("these don't add up") -> full 38-position audit (`scripts/audit_position_basis.py`,
4-source cross-check: holdings.json vs live API vs csv tax lots vs API fills). 8 positions carried
phantom basis from stale CSV-window reconstruction: SCHD rollover $4.02/sh vs broker $31.04
(+$111,392 fake gain), SCHG rollover $16.06 vs $30.81 (+$25,072 fake), V roth $43.58 vs $307.35,
V rollover $6.41 vs $80.10, PFLT $0.20 vs $9.49, ARKG (fake LOSS), FCNTX/AMANX/SRNE transfer-ins.
CSV lots + ledger fills corroborated the API in every checkable case.

Fix (operator decision: ONE source of truth, API->DB): new `schwab_positions_live` table (canonical
broker positions layer) + `scripts/sync_basis_from_broker.py` — basis hierarchy csv tax lot >
Schwab averagePrice > nothing; CSV reconstruction DEMOTED to Fidelity-only. 34 holdings rows
rewritten through Gate-B protected_holdings_write; re-audit 0 flagged / 38 clean (delisted CUSIP
dust = info-level). open_trades_intelligence: reconstructed_from_amounts REMOVED from trusted set,
never badged "verified" again; broker_api/csv_lot added as broker/tax_grade tiers.

Why no agent caught it: no monitor compared basis across sources (health=process/freshness, TCA=paper
fills, gainloss reconcile=realized-only, unscheduled). New control: audit_position_basis.py --alert
(Telegram on discrepancies); cron line proposed, awaiting operator approval.

## 2026-06-12 - CRITICAL DATA FIX: roth/rollover account-hash links were SWAPPED + Open Trades badges/filters + Schwab monitor sub-tabs

**Account swap (operator caught it via the new monitor: "rollover has way more than 2 positions").**
Root cause: `schwab_account_links` mapped schwab_rollover_ira->...9415 and schwab_roth_ira->...0258, but
Schwab's own 2026-04-21 CSV proves ...415 IS the Roth (V 130 + SCHG 43); the big 13-position account
(...0258: FCNTX/V 301/SCHD 4122/scalp activity) is the ROLLOVER. Every API read/ingest since cred-in
labeled those two accounts backwards; holdings.json + json_migration rows were always correct.
Fix (operator-authorized, backup table `_backup_acct_swap_20260612`, 179 rows): swapped the 2 link rows;
relabeled 177 schwab_api trade_transactions rows (164 roth->rollover, 13 rollover->roth) incl. the
account segment inside dedupe_key (prevents re-ingest duplicates); re-keyed the V IPO-basis override to
V|schwab_rollover_ira (the sells happened there); journal rebuilt — active stats unchanged (116 trips,
52.6%, +$37,046), long-term realized restored +$114,560, basis_unknown back to 13, round-trips now
rollover 46 / roth 1 / taxable 88. Monitor verified: rollover 13 positions + 27 orders, roth 2, taxable 22.
LLM grades for re-keyed trips regenerate on the nightly 18:15 classifier cron.

**UI (operator requests):** PositionDecisionCard account badge now loud + color-coded (📝 PAPER blue /
💰 REAL amber) — AGNC/NWG exist as both paper trades and real holdings, badge disambiguates. Open Trades
gains one-tap account filter pills (with per-account counts). Schwab Accounts monitor gains account
filter pills + sub-tabs: Positions / Working Orders (working statuses only, edit->DRAFT) / Order History
(FILLED/CANCELED/REJECTED read window). open_trades_intelligence normalizes UPPER(account) for paper
rows ('ALPACA_PAPER' vs 'alpaca_paper' showed as two phantom accounts).

## 2026-06-12 - Stage 2a readiness: ToS-style dormant UI + hardcoded canary gate + two-channel approval + L3 read-only prereqs

READ-ONLY throughout; execution stays BROKER_DISABLED; validator extended 12/12 -> 17/17 green.
- **Part D — hardcoded canary gate** (`scripts/brokers/canary_gate.py`): commit-only envelope (allowlist
  EMPTY until session-time commit · price<=$4 · qty<=10 · notional<=$40 · US equities · long-only) wired
  IN FRONT of the execution-guard mode logic; pure module (no env/DB/config); 22/22 unit tests incl.
  hypothetical BROKER_DISABLED-lifted scenario — out-of-envelope denied by the gate, in-envelope still
  denied end-to-end.
- **Part A1 — shadow-reconciliation harness** (`schwab_shadow_recon.py`): ~30s read-back of manual ToS
  orders, diffs Schwab's actual JSON vs translator prediction (∅ pass modulo documented renames;
  mismatch = session ABORT); tables schwab_shadow_recon_runs/_items + md session log; selftest proven.
- **Part A2 — canary analytics exclusion**: schwab_round_trips.canary (sticky, tagged at ingest from the
  gate allowlist); all 6 consumers filtered (api stats, trade_closed refresh, classifier, backtest recon,
  exec quality, gain/loss recon); proof test: $10k fake canary row moved ZERO aggregates (9/9).
- **Part A3 — activity capture** (`schwab_activity_capture.py`): poll-based order-status/transaction
  payload capture -> schwab_activity_log, surfaced in the Broker Orders safety log; streaming deferred.
- **Part B — stage2a-canary-protocol.md** revised to operator caps: $2-$4 session-time screen (ITUB/SNAP
  obsolete — violate the cap), <=10 sh, orders 1-6 far-from-market+cancel (~$0), 7 = the one attended
  micro-fill (<=$40), 8-9 OCO exits + canary-tagged close->ingestion; session rails + abort conditions.
- **Part C — ToS-desktop Active Trader panel** (v3 Trading -> Broker Orders): bid/last/ask strip, qty
  presets 2/5/10, structure-aware fields (SINGLE/BRACKET/MULTI-TARGET/TRAILING/OCO/LADDER) with static
  tooltips + inline explainers; EVERY control builds a DRAFT -> preview/translate -> guard BLOCK logged;
  no auto-send/submit endpoint exists (validator-checked). AI help advisory-only: local model default,
  Claude only on explicit escalation (/api/v2/broker-orders/explain).
- **Part C2 — all-Schwab-accounts monitor** (v3 Trading -> Schwab Accounts): live positions + open orders
  x3 accounts via /api/v2/schwab/accounts-live (fenced reads, 30s cache); "edit -> DRAFT only" seeds the
  order panel — never an API modify.
- **Part E — two-channel approval**: web channel now requires TYPING the ticker (click never confirms);
  one order at a time (slot check); Telegram approval message carries the Tailscale deep-link
  https://<TAILSCALE_HOSTNAME>/v3/trading?tab=Broker+Orders&intent=<id> (env-driven, not hardcoded);
  exercised end-to-end with execution still BLOCKED (11/11).
- Tests: 90/90 across canary gate / canary exclusion / two-channel approval / broker scaffold;
  validate_schwab_no_writes 17/17 (5 new guards: harness+capture read-only, gate purity+front-position,
  UI no-execution-path, consumer canary filters). Migration 2026_06_12_stage2a_canary_readiness.sql.

## 2026-06-11 - Modal reject/delete + test plan delivered (email + telegram)

Broker Orders modal gains '✖ Reject (keep record)' (supersedes approvals, state=REJECTED, audited) and
'🗑 Delete draft' (confirm prompt; row removed, audit events retained) - both smoke-tested via API. Master
test plan + stage-2a protocol + stage-1 review log emailed to john@jwwhiting.com via gog (msg
19eb948cbd381a0f) and the plan sent as a Telegram document to the proposals chat for developer review.


## 2026-06-11 - Edit-before-approval modal + 2-share fixtures + master test plan

All Broker Orders drafts regenerated at canary size (2 sh, named purposes; the "100 sh" was harness default,
never a plan). Edit modal: full order editing -> re-preview translation -> inline 2FA stepper.
docs/brokers/master-test-plan.md for external developer review: safety invariants matrix, 4 test levels w/
per-case hypotheses and UNVERIFIED traceability, entry/exit criteria. Screenshot-verified end-to-end.


## 2026-06-11 - Broker Orders tab humanized after operator feedback

"not functional makes no human sense" -> rebuilt for operators: order sentences ("BUY 100 sh MRVL limit
\$284.49") + condition pills + Purpose line (Stage-1 fixtures explicitly labeled "not a real plan") +
grouped identical fixtures + "If this were live:" consequence sentence + raw JSON behind an engineering
toggle + 2FA explainer + grouped Safety log (red=blocked-is-correct). Screenshot-verified.


## 2026-06-11 - Canary purpose + web-channel location documented (operator questions)

stage2a-canary-protocol.md gains plain-English sections: the 1-2 share orders test Schwab's RUNTIME order
handling (response JSON shapes, status lifecycle, TRIGGER-cancel semantics, fill events, OCO activation,
ingestion flow) - everything is currently verified only against the SDK schema and Schwab has no sandbox;
orders 1-6 never fill (cost \$0), orders 7-9 are one attended ~\$16 fill (cost ~ spread). Web approval
channel location: Trading -> Broker Orders -> inspect -> 2FA panel (screenshot-verified, mobile-usable).


## 2026-06-11 - 2FA trade approvals (telegram buttons -> proposals chat) + Broker Orders tab + v3 mobile

Per-trade two-factor approvals live (testable; execution still BROKER_DISABLED): web confirm + Telegram
ONE-TAP Approve/Reject inline buttons routed to the proposals chat (operator clarification; env
TELEGRAM_APPROVAL_CHAT_ID overrides), single-use, 10-min TTL, fail-closed; guard 4th lock denies unapproved
intents even with all standing locks open; bkapprove/bkreject callbacks (poller restarted); the operator-
spotted "100" was a labeled scaffold TEST fixture (now tagged in messages; real canary plan = 2sh ITUB,
PARKED awaiting plan approval). Command Center Trading->Broker Orders tab: execution-disabled banner,
canonical-vs-Schwab payload side-by-side, live 2FA panel, guard audit trail. v3 mobile responsiveness:
attribute-selector CSS layer collapses inline grids/flex at <=820px; 390px audit = zero overflow across
Home/Trading/Broker Orders/Journal - approvals fully operable from a phone. Tests 46/46, validator 12/12,
ZERO orders placed.


## 2026-06-11 - Stage 2a canary protocol: ITUB selected (live-screened), 2-share battery defined

paperMoney confirmed not API-visible -> tests are tiny REAL manual orders. Live screen via our batch-quotes
endpoint across 20 candidates: ITUB primary ($7.91, $0.02 spread, 33.9M vol, ZERO footprint in holdings/
watchlist/paper history - sterile), SNAP backup; NIO/LCID/BBD excluded (watchlist rows), held names excluded.
Size 2 shares (~$16 max). Nine-order battery (6 never-fill far-limits + 1 real micro-fill + OCO exits +
close), expected realized cost cents-to-dollars; pre-session requirements: canary_symbols analytics
exclusion, shadow-reconciliation harness, ACCT_ACTIVITY read-only capture. Stage 2b (API-write canaries)
remains separately gated. docs/brokers/stage2a-canary-protocol.md.


## 2026-06-11 - Stage 2 restructured: no Schwab sandbox exists -> shadow validation + micro-canary

Operator question: Schwab individuals get no dev/sandbox accounts - how to validate safely? Answer baked
into the migration plan: Stage 2a SHADOW VALIDATION (zero API writes) - operator places tiny test orders
MANUALLY in thinkorswim (paperMoney for structure questions); our read-only API reads them back and a
reconciliation harness compares Schwab's actual OTOCO/trailing/multi-target representations + status
lifecycle + partial-fill child behavior against translator expectations; ACCT_ACTIVITY subscribed read-only
(manual activity generates the events); rate limits observed from read traffic. Resolves 6-7 of 10
UNVERIFIED items with the write fence fully intact. Stage 2b (only for API-write semantics: replace,
priceLink-on-submit, reject taxonomy): attended micro-canary window - far-from-market LIMIT qty=1 on <\$10
stock, ACK->read-back->CANCEL - requiring its own signed approval + validator canary assertions FIRST;
explicitly out of scope until approved. Open-questions resolution paths updated per item.


## 2026-06-11 - Schwab migration Stage 1: 30-preview translation review — 30/30 CLEAN

translation_review.py harness (repeatable): 30 intents grounded in real recent symbols/prices covering
brackets (limit/market entries), stop + stop-limit entries, 4 trailing variants (LAST/BID/MARK/ASK x
PERCENT/VALUE/TICK), multi-target OCO (UNVERIFIED-flagged), 2/3-leg ladders, shorts, bid-link entry,
entry-range, AM/PM/SEAMLESS sessions, GTC/FOK/IOC TIFs, MOC, stop-only/target-only, plus 3 negative cases
(bad geometry rejected; options + notional blocked-as-expected). Field-level assertions on every payload;
qty conservation; guard granted execution 0 times. Two initial "defects" were the VALIDATOR correctly
rejecting real MRVL rows whose trailing stops sat above entry (winners past breakeven) fed as fresh LONG
intents — harness geometry sanitized; translator itself had zero defects. All 30 previews persisted as
audited drafts. Log: docs/brokers/stage1-translation-review-log.md. Gate now awaits operator sign-off to
advance to Stage 2 (dev-account validation of UNVERIFIED items).


## 2026-06-11 - ATOS phantom answered end-to-end + digest all-time fallback removed

Operator Q "if not a trade why is it showing": approval pre-creates a pending row; revalidator correctly
blocked (107% drift, Alpaca shows zero ATOS orders ever); the orphan row got phantom-voided to closed/\$0 and
review counted it. Fixed at every layer (cancel-on-block, journal/digest exclusion, sweep check, ATOS
reclassified - verified gone from journal). Verifying exposed a second flaw: digest silently reported ALL
history as "today" when zero trades closed today - removed; now honest "no trades closed today". Schwab
scaffold prevents the class by construction (no record before broker truth).


## 2026-06-11 - Validator boundary regex: two self-catches post-scaffold

The no-writes validator flagged api_v2 twice after the broker endpoints landed: (1) "from
brokers.translators import schwab" — our own pure-translator MODULE NAME matched the conservative
boundary regex; switched to function-form import rather than weakening the guard; (2) the explanatory
COMMENT itself contained the trigger phrase — reworded. 12/12 restored both times. The guard proving it
reads everything is a feature, not a bug.


## 2026-06-11 - Schwab integration program: research + dormant scaffold (6 phases, all committed)

Operator-approved ground rules: ZERO Schwab order-endpoint calls (dry-run = local translate/validate/audit);
options model+flags only; new Broker Orders surface; straight-through per-phase commits. Delivered: P1 Alpaca
current-state map (single submission site adapter:524; existing partial abstraction; coupling list); P2
21-category capability matrix (VERIFIED-LIVE/VERIFIED-SDK/UNVERIFIED; Schwab OTOCO/native-trailing richer
than Alpaca; NO Schwab paper env -> ExecutionMode enum is the environment separation); P3 ADR set; P4
scripts/brokers/ dormant scaffold (canonical OrderIntent, capability registry, pure translators, fail-closed
guard w/ Schwab=BROKER_DISABLED, adapter stub raising unconditionally, audit tables, 35/35 tests incl.
boundary rule, validator 12/12 untouched); P5 broker-orders endpoints (capabilities/preview/drafts; preview
returns exact would-be Schwab payload + blocked execution; live-smoked: TRIGGER->OCO[LIMIT,TRAILING_STOP]);
P6 ten docs under docs/brokers/. BONUS mid-phase: operator's ATOS \$0 report root-caused — REAL phantom
record/FALSE trade (revalidator correctly blocked 107% drift but approval-time pending row was never
cleaned; Alpaca shows zero orders); fixed class-wide (cancel-on-block, digest exclusion, sweep check,
row reclassified) — and the new scaffold prevents the class by construction. Also: pre-commit hook caught a
hardcoded broker default (annotated hardcode-ok as UI view default) — and caught that my filtered commit
pipelines had been swallowing hook rejections; two commits re-landed.


## 2026-06-11 - L2 strip live-verified on replay + TDZ render crash fixed

ELVN replay now renders all layers together: L2 imbalance strip (own price scale, +0.21 bid pressure at
entry), four escalating pre-entry catalyst headlines pinned + listed (trial data 08:55 -> FDA alignment
09:11 -> "why is it surging" 09:52 -> Phase 1 CML 10:36 -> 12:12 breakout entry), BUY/stop lines. Root cause
of blank charts: SPY/L2 setData referenced shownTime before its declaration (temporal dead zone ->
ReferenceError -> zero canvases whenever those layers had data; ATOS worked only because it had no L2 rows).
Hoisted; 21 canvases verified. Proposal-screenshot watcher expired without a pending proposal today (queue
empty after ELVN executed).


## 2026-06-11 - Replay news pins live-verified + three replay bugs fixed

ATOS demo proved the feature end-to-end: six pre-market offering/dilution headlines pinned + listed on its
11:02 scratch replay - the trade's full story on one chart. Fixed en route: (1) Journal Replay passed full
timestamp as entry_date (sliced to date -> midnight-UTC window = wrong bars, 8pm-ET prior evening); now
passes entry_time/exit_time + plan stop/target; (2) out-of-window catalysts were dropped by the 90-min bar
guard - now edge-clamp with (pre/post-window) tags; (3) headline-list render anchor had silently no-opped.
Validator 12/12.


## 2026-06-11 - Replay backlog complete (news pins / L2 strip / SPY overlay / error hints / chunking)

All five audit-backlog items shipped + live-verified (ELVN catalyst headline pinned on today's chart at
10:36; 7 L2 snapshots; SPY rebased overlay). UI maturity 7 -> 8; overall ~7.4. Validator 12/12.


## 2026-06-11 - Open-trade card enrichment + replay audit & upgrades

Operator Qs answered: news was never missing (6-7 items per position; renders on card expand); analyst data
existed but rendered as cryptic pills ("hold 8an") and ELVN was uncovered until pills rebuilt (universe DOES
include 30d paper trades; daily 06:10 cron). Cards now carry: explicit Analysts line (rating+mean+opinions+
target+upside, range/source/latest-event tooltip), live L2 book-pressure chip, Hermes H#rank (top-100),
short-float >=5% chip, earnings-date chip - all server-side from existing stores. Replay audited (agent
report) + immediate items shipped: planned STOP/TARGET lines, runner-type annotation on post-exit line
("pump - exit was right · gave back N%" vs "real runner - scale-out lesson"), MFE/MAE % badges, grade-why
tooltip (flags + coach), full-timestamp passthrough fixing same-day detection for overnight intraday holds.
Replay backlog (documented, not built): news pins, L2 strip, SPY overlay, finviz-error surfacing, Schwab
fallback pagination.


## 2026-06-11 - All 8 code-path areas raised to 7 (operator directive)

Docs hygiene (sync exclusions+retention) - integrity (9-check nightly sweep + event-sourced proposal
statuses) - Hermes (diversity cap, VIX regime weights, H#rank proposal chip, non-circular movers-fed
discovery) - scoring (reaction-weighted catalyst de-bias, percentile sector pillar, regime thresholds) -
ingestion (unified API budget ledger x6 providers, salted dedup, stale-cache guard, dead paths) -
backtesting (fib in PIT sim + REAL-fill reconciliation RECONCILED 18/20) - arbitration (signal_evidence
"why this signal won" on every proposal) - strategy (core-4 evaluator-verified + lifecycle transition
alerts). Maturity ~6.3 -> ~7.3 overall; floor now 7 everywhere except sample-gated residuals (documented).
Validator 12/12 throughout.


## 2026-06-11 - Maturity: code-only paths to 7 documented

Per operator question: 6 of 8 areas at 5-6 CAN reach 7 by code alone (docs hygiene, integrity sweep, hermes
diversity/regime, sector-neutral catalyst scoring, ingestion budget/dedup, backtest sim coverage+fill
reconciliation); arbitration + strategy framework reach 7 on mechanism but their differentiated/validated
claims need 2-4 weeks of samples. Code-only ceiling ~7.0-7.2 overall; beyond that evidence-driven.


## 2026-06-11 - Priority arc 1-5 complete; all maturity areas raised to >=6

Arc-1 pillar_breakdown persisted (both scan inserts). Arc-2 entry-criteria evaluator (deterministic, 5/5
self-tests, Gate-2 wired, criterion-ID rejections). Arc-3 freshness SLOs (baseline-relative, 7 sources, cron
2h, 7/7 green). Arc-4 arbitration: source_weights schema+job+cron, scoring consumes bounded weights,
source_tier backfilled 10,375. Arc-5 backtesting: PIT look-ahead fixed, 30bps cost model, real-vs-synthetic
split surfaced, and the POINT-IN-TIME SIGNAL SIMULATOR (criteria-driven entries over the screeners' own
historical universe, walk-forward 70/30, sample gates) - first falsifiable verdict: swing_breakout
no_edge_oos (32 signals, -0.18R with costs), persisted as pit_simulated. Alpaca free-SIP 403 handled +
Schwab read-only daily-bar fallback (operator request). hermes_score_history pairing index (calibration ran
48min unindexed). Maturity re-score: 5.4 -> 6.3 overall; backtesting 2->6, arbitration 2->6. Validator 12/12.


## 2026-06-11 - System maturity audit (15 areas scored /10)

docs/project/MATURITY_AUDIT_20260611.md - evidence-based scores from the day's six audits + fixes. Overall
~5.4/10: safety-mature (governance 9, broker integration 8, journal/coaching 8), intelligence-immature
(backtesting 2, cross-system arbitration 2, Hermes 4, scoring 4). Per-area evidence, gaps, recommendations +
priority arc: persist pillar breakdown -> entry-criteria evaluator -> freshness SLOs -> source weighting after
2-4 weeks of attributed data -> backtesting credible path.


## 2026-06-11 - Ingestion fixes 1-4 + investigations 5-6 (operator-approved)

Attribution restored end-to-end (screener_label finally written; per-list efficacy measurable). Outcome
feedback wired into both scorers (strategy-family WR scar in 65-pt scoring, bounded + min-sample;
realized-P&L pairs in hermes calibration at 2x weight). Sector self-heal at insert + 2,744-row backfill
(44%->33% empty). Librarian backlog loop investigated->fixed (no dedup + per-invocation cap caused 2,475
junk NULL-symbol rows/30d; now 14d-topic dedup + true daily cap; 2,474 archived; double-apply inserts 0).
Tech-tilt experiment: Healthcare GO lead structurally justified; TECH GO lead NOT explained by measurable
pillars (weakest RVOL/float/price/gap inputs yet 1.3x Industrials GO rate) -> residual = catalyst-tier
keyword/LLM bias; next step = persist pillar breakdown + sector-neutral catalyst tiering. Validator 12/12.


## 2026-06-11 - Ingestion & intelligence due-diligence review (Finviz / Trade AI / Hermes)

docs/project/INGESTION_INTELLIGENCE_REVIEW_20260611.md. Headlines: "momentum scout" = prime_setups (6x/day)
but per-list efficacy UNMEASURABLE - screener_name tagged at ingestion is dropped at orchestrator INSERT
(line 631), screener_label NULL on all 23,940 scans/30d; intake is sector-diverse but GO layer concentrates
(Tech 37 + Healthcare 27 of ~111) = scoring-layer tilt, 44% scans missing sector; Hermes is dynamic (30-min
recompute) but NOT adaptive (zero outcome feedback; calibration uses price pairs, advisory-only), sector
factor passive 12% w/ no caps/no VIX, YouTube discovery circular + engagement-biased; degenerate librarian
backlog loop = 2,475 NULL-symbol rows/30d all auto-promoted (inflates "Research staged"); no arbitration
layer in practice (source_tier NULL 3,167/3,184; scoring.py 0 hermes refs). Ranked fixes: attribution
end-to-end, outcome feedback into both scorers, kill backlog loop, sector backfill, diversity+regime
conditioning, hermes chip on proposals. Review only - no code changed.


## 2026-06-11 - Finviz 429s: global cross-process rate limiter (cause-level fix)

finviz_throttle.py: flock-based shared min-interval (2.5s, env-tunable) + global cooldown broadcast on any
429 (Retry-After honored), wired into ingestion/enrichment/news. Root cause was N independent processes each
self-throttling with no shared limit. Tested: 3 concurrent processes serialize 0/2.5/5.0s; fail-open 300s so
it can never deadlock. Complements the earlier handling fix (no version-hopping while limited, accurate
RATE-LIMITED alert).


## 2026-06-11 - L2 stream scheduled + proposal chip + three root-cause fixes

Stream: cron market-hours schedule (9:31 + flock-guarded 11/13/15 safety restarts; self-terminates at close;
systemd units staged for sudo install); running live today. ProposalsRich: L2 book-pressure chip (15m avg
imbalance, advisory). Root causes from operator alerts: (a) dedup-guard backfill left survivor status=pending
after fill (ELVN -> monitor false "no DB record"; trigger now promotes pending->open, row repaired, test
passes); (b) continuous_runner SELECT used float_m vs column float_mm - social-scalp injection silently dead
every cycle, now restored (26 rows); (c) float_shares all-zero Telegram spam was ETF/fund screeners (funds
have no float) - gate now exempts ETF rows, genuine zero still alerts. Validator 12/12.


## 2026-06-11 - Level-2 streaming spike (operator-gated, Rule-9 isolated)

schwab_stream_daemon.py captures read-only L1 quotes + NASDAQ Level-2 book for symbols auto-selected from
open positions/PENDING proposals/directives; computes book-pressure imbalance; own tables; kill switch;
market-hours aware; manual start only. schwab-py kept behind the transport boundary via build_stream_client
(the no-writes validator caught the initial direct import - guard proven). Endpoints:
/api/v2/schwab/stream/status + /stream/book (latest book + 15m pressure read, advisory-only). Live-tested:
111 book snapshots (NWG bid-heavy +0.40, TMHC ask-heavy -0.57). Never an execution trigger; 0 pipeline
imports; validator 12/12.


## 2026-06-11 - Schwab REST read surface fully wired

Added read-only option chains (near-the-money summary), option expirations, instrument fundamentals (P/E,
EPS, div yield, mkt cap, 52w), and index movers to schwab_transport + endpoints (/api/v2/schwab/option-chain,
/fundamentals, /movers; earlier today: /quotes batch + /market-hours). All live-tested (V chain @ 319.69 w/
18 expirations, P/E 28.16, SPX movers). Every readable Schwab REST capability is now wired. NOT wired by
design: news (no Schwab news endpoint exists; 7-source news layer remains canonical) and Level-2/streaming
(WebSocket streamer = Rule-9-fenced future spike, requires its own gated session). Write fence untouched,
validator 12/12.


## 2026-06-11 - Deep-review fixes implemented (all 5 approved items)

(1) P0 fixes: populate_performance_context column bug (strategy YAMLs now carry real performance; second
latent Decimal bug fixed); proposal dedup now symbol-wide across ALL strategies (BWEN x4 class blocked);
journal strategy labels honest (manual_scalp/manual_swing via schwab_round_trips join, 121/121 - unclassified
eliminated). (2) Strategy consolidation 23->4 trading core (momentum_scalp absorbs gap_and_go, swing_breakout
absorbs swing_trade, fib_retracement_bounce promoted TESTING, earnings_post_momentum) + 7 archived to
_archive/ + 2 PARKED + 10 reclassified ALLOCATION_POLICY; strategy_registry only core-4 active (risk gate
enforces: gap_and_go -> STRATEGY_KILLED; backup CSV saved). (3) Free-OAuth-only: catalyst-rescore fallback,
GO narratives, and stage-14 trade plans migrated off metered Claude to Grok lane + local fallback
(live-tested). (4) Cadence: redundant 0900/1000 orchestrator crons retired (continuous_runner owns
04:00-11:00; crontab backup saved). (5) Schwab READY wired read-only: batch quotes + market hours in
schwab_transport + /api/v2/schwab/quotes + /market-hours (live-tested: V 319.5, equity open). Validator
12/12 throughout.


## 2026-06-11 - System deep review (intake / integrations / proposals / strategies / backtesting)

docs/project/SYSTEM_DEEP_REVIEW_20260611.md - full read-only audit: 4 parallel code-tracing audits + DB
evidence + all 23 strategy YAMLs reviewed individually. Headline findings: (P0) populate_performance_context
queries non-existent columns and nightly writes closed_paper_trades:0 into every strategy YAML (governance
blind to real performance); cross-strategy proposal dedup hole (BWEN x3); strategy-label noise (63/102
unclassified); look-ahead bug in trade_backtest_engine entry grading (<= vs <); no signal-generation
simulator / walk-forward => edge claims not yet provable; 96% of backtest rows synthetic champion rows;
"Codex" = ChatGPT free OAuth (openai-codex Hermes lane); metered Claude (Haiku rescore + Sonnet trade plans)
inside the orchestrator flagged vs free-OAuth rule; Schwab READY capabilities unwired. Recommendation:
consolidate 23 strategies -> 4 trading core (momentum_scalp, swing_breakout, fib_retracement_bounce,
earnings_momentum) + income-sleeve/allocation policies; minimal credible backtest path defined. No code
changed in this review.


## 2026-06-11 - Real Accounts grade tooltip (entry/exit + why)

Applied the same E/X grade tooltip to the Real Accounts (SchwabJournal) rows: the E:A X:A pill now shows ⓘ and
hover-explains each grade from execution signals (entry timing + RVOL + VWAP, exit timing + capture% +
missed-runner) plus the Grok coaching line. Consistent with the Trade Log. Read-only, validator 12/12.


## 2026-06-11 - Trade Log grade pill: label entry/exit + explain why (tooltip)

The grade pill was an ambiguous 'D/B grade'. Now shows 'E D  X B' (E=entry, X=exit) with a hover tooltip that
explains each grade from the execution-quality signals: entry timing + RVOL + VWAP position, exit timing +
capture% + missed-runner, plus the Grok coaching line. A=best -> F=worst legend included. Read-only.


## 2026-06-11 - Trade Log redesigned into actionable cards + Execution Coach made drillable

Trade Log (Journal->Trades): replaced the dense 9-column row list with larger cards (WIN/LOSS/SCRATCH +
account + strategy + grade + execution pills, big P&L + R, Grok lesson), Replay + Details action buttons,
symbol search, 7 quick filters (Winners/Losers/Open/A-grade/Poor execution/Missed runner), and pagination
(12/page). Execution Coach panel: was a vague dead-end display; now every ranked coaching item (top 6) is
clickable to drill into its evidence (full action + affected trade keys + metrics), hypotheses get
plain-English labels (what each rule change tests) and drill to the backtest detail with a clear unsupported/
promising verdict. Read-only, validator 12/12.


## 2026-06-11 - Watchlist dedup: one row per symbol (NVDA + 118 others)

The watchlist is seeded from multiple discovery sources (operator personal_watchlist, ai_discovered,
paper_proposal), so 119 symbols had duplicate visible rows (167 redundant; NVDA x3, KBR x5, BND/JEPI x4).
Fixed at the query layer: /api/v2/watchlist/items now DISTINCT ON (symbol), keeping the best row per symbol
(directive-linked > operator-seeded > oldest), then applies the display sort + directive pin. Result: 200
distinct symbols, 0 duplicate rendering; NVDA once, AXTI pinned (pos 2). Also data-deduped NVDA's 2 redundant
rows -> removed (kept operator original id=129, reversible from backups/nvda_watchlist_dedup_20260611.csv).
Read-only, validator 12/12.


## 2026-06-11 - Pin directive-linked watchlist items above the 200 display cap (AXTI fix)

/api/v2/watchlist/items ORDER BY now sorts in_directive_watch=true items first, so operator
directive/promoted symbols are always within the 200-item cap. AXTI (directive_id=13, high priority) now
renders at position 4 (was below the cap and invisible), once, no duplicate. Read-only, validator 12/12.


## 2026-06-11 - Trade cards redesigned into actionable position decision cards

Open Trades cards rebuilt as decision cards. Backend (read-only, derived): open_trades_intelligence.py now
emits operator_priority/operator_decision/decision_reason/risk_flags/opportunity_flags/data_freshness/
news_freshness/protection_state/basis_quality/watchlist_state/directive_state/last_hermes_review_at/
latest_news_age_hours/primary_next_review/recommended_manual_actions + strategy_rationale (the WHY, from each
strategy config purpose) + sector fallback. Frontend: new PositionDecisionCard (6 zones: identity+priority,
decision banner, economics, evidence chips incl strategy WHY + sector, catalyst news with stale labeling,
manual-action buttons) + 10 quick filters + 11 sorts (priority default). Addresses operator feedback: sector
now shows, strategy + WHY shown. Playwright audit (5 shots, 0 console errors) + review doc. AXTI: present as
researched (no dupe) but below the watchlist 200-item display cap - pre-existing, not card-related. Read-only,
validator 12/12.


## 2026-06-11 - v3 header v2-parity + actionable approvals badge

v3 MetricStrip now matches the v2 header: added TODAY, JOURNAL P&L, VIX, LAST RUN tiles + a clickable
APPROVALS badge (all from existing /api/v2/overview + /trade-ai). The APPROVALS badge now navigates to Home ->
Action Inbox (where the stop-triggered + governance items are reviewed / drilled to source) instead of a dead
count-only drawer. Read-only; review stays drill-to-source (Level 7 prohibited). Noted: overview
pending_approvals count (13) includes john_decision_queue items that /api/v2/approvals/pending does not list
- a backend listing gap to reconcile separately.


## 2026-06-11 — Fix: pipeline false-failure flood (SystemExit(0) recorded as failed)

Root cause of the trade_ai_orchestrator pipeline_critical alert flood: PipelineRun.__exit__ treated ANY
exception as a failure, but the idiom  raises SystemExit(0)
on clean success -> recorded status=failed, errors="0" every run (the orchestrator itself succeeded, e.g.
9:00 logged v12 complete). Fixed __exit__ to treat SystemExit(0/None) as success (run_complete); real
failures (sys.exit(non-zero) / genuine exceptions) still record failed. Reclassified 28 historical
false-failures to success; alert dispatcher now finds 0 failures in the 4h window. Applies to every pipeline
using the PipelineRun idiom, not just the orchestrator. Validator 12/12.

## 2026-06-11 — NUVL duplicate resolved + paper_trades dedup guard

Resolved the journal integrity warning: NUVL had two open paper_trades rows from a race/retry double-insert
(0.67s apart). Verified against Alpaca (source of truth): real position 16sh @ $123.43375 == id=57 (Alpaca
order 16d6bb67); id=56 (no order id, $123.53) was the phantom -> marked cancelled (reversible, backed up to
backups/nuvl_dedup_20260611.csv, not deleted). Built a DB-level BEFORE INSERT dedup trigger
(paper_trades_dedup_guard) so the race cannot recur on any insert path: suppresses a second open row with the
same symbol+account+shares within 15s (backfilling the survivor with the incoming broker_order_id) and
suppresses any re-insert of an existing broker_order_id. Tested: race-suppressed+backfilled, legit positions
unaffected, order-id idempotent. No order-pipeline code touched; validator 12/12.

## 2026-06-11 — Journal UI visual audit (Playwright, all 6 tabs)

scripts/crawl_journal_ui.py — read-only Playwright crawl of Journal -> Trades/Analytics/Lessons/Protection/
Backtesting/Real Accounts + interactions (drilldowns, replay charts). 12 compressed JPEGs + REVIEW.md in
docs/ui_review/journal_audit_20260611/. Confirms live: Avg-R KPI + By-Strategy R column, Real-Accounts
execution badges + Grok lessons, Backtesting hypotheses (all hurts) + R-distribution, RGNT replay chart
(VOL/VWAP/MACD/RSI + BUY/SELL/MFE/MAE markers). Flagged: NUVL duplicate open-record integrity warning.
Screenshots contain real account data -> private repo + own Drive only.

## 2026-06-11 — Runner classification: parabolic_pump vs sustained_trend (opposite coaching)

Added runner_type to execution quality so the coaching queue separates REAL missed runners (hold/scale lesson)
from intraday PARABOLIC PUMPS (spike-then-collapse traps where selling was CORRECT). Detection: swing
post-exit retrace = trend_top (slow), intraday big spike + >=60% same-session give-back = parabolic_pump.
Verified: AGMH/ELBM/FUSE/GSIT -> parabolic_pump (selling right, do not chase); AXTI/ANY/SLDP -> trend_top
(real, scale-out lesson). Intraday fetch extended to session close so the fade is visible; bounded
missed-runner window unchanged. Surfaced in coaching-queue missed_runner items (pumps aggregated, low
severity), execution-quality API, and SchwabJournal badge tooltip. Read-only, validator 12/12.

## 2026-06-11 — Execution coaching: worked-example walkthrough documented

Added a worked example to EXECUTION_COACHING_QUEUE_20260611.md: a read-only replay walkthrough of three
trades the queue surfaced — CTXR scalp (entry leak: RVOL 0.26 into a dead tape, capture 48%), AXTI #255
(during-hold exit leak: rode $26.66 peak back to $18.83 exit on a 6.5x winner), AXTI #257 (post-exit leak:
sold $17.74, missed the run to $28.65 = +62%). Together they map both edge leaks (early entries, imprecise
exits) on net-positive trades. Directive remains study-the-replays, not change-the-rules. Read-only, no code
or live-behavior changes.

## 2026-06-11 — Daily Execution Coaching Queue (read-only; advisory)

Converts the execution-quality system into a ranked daily 'what to fix next' queue. Additive schema
(daily_execution_coaching_runs/items/grok_digests), build_daily_execution_coaching.py (dry-run default,
--apply to store, --brief manual-only no cron), grok_daily_execution_digest.py (strict JSON advisory),
read-only API (GET daily-execution-coaching[/latest], POST rebuild dry-run default), ExecutionCoachPanel in
Journal->Trades. Ranks repeated mistakes > one-offs with sample sizes; hypotheses surface as shadow-research
candidates ONLY (all 3 currently unsupported by evidence). Governance doc: coaching-only, no live-strategy
changes, full gate (sample/shadow/operator/A1A/rollback) before any promotion. Validator 12/12. No trading,
screener, GO/WAIT, ATM, proposal, broker-write, or strategy-YAML changes.

Also: journal R-multiple per trade + Avg-R KPI + By-Strategy R (paper real, Schwab MAE-proxy); SchwabJournal
swing rows now show Grok execution lesson.

## 2026-06-11 — Grok execution lesson on Real-Accounts lesson column (swings + scalps)

SchwabJournal rows now surface the Grok execution coaching (grok_what_to_do_next_time) as the visible lesson
text + tooltip, falling back to the classifier lesson. Fixes swings showing the contradictory classifier
'repeat this hold' text next to a weak/poor execution grade — they now read the actual coaching (e.g. GERN
'Wait for RVOL>1.5 + MACD rising before entry'). eq computed once per row (de-duplicated). Read-only.

## 2026-06-11 — Schwab public-repo intake memo (review only)

docs/project/SCHWAB_PUBLIC_REPO_INTAKE_20260611.md — read-only survey of 9 public Schwab-API repos (live
GitHub metadata). Records license/maintenance/risk (NO-LICENSE jononon + NOASSERTION hedge0 = do-not-copy;
itsjafer = reverse-engineered scraping anti-pattern), conceptual-reuse vs must-not-copy, and candidate
references for the deferred streaming/option-chain/batch-quote/market-hours work. Decision: keep schwab-py as
the REST wrapper; Schwabdev recorded ONLY as a future streaming/Level-II spike reference (not a dependency).
No code, no dependencies, no spikes. Validator 12/12.

## 2026-06-11 — Execution-quality calibration: capture during-hold + RVOL tuning (poor is genuine)

Fixed capture_ratio (was measuring through the post-exit window, wrongly grading well-timed exits poor — GOVX
captured 100% of the during-hold move but scored 32%); now capture = captured/MFE-during-hold, post-exit run
stays the separate missed-runner. Tuned scalp RVOL 2.0->1.5, day_trade 1.8->1.3 (above-average, not 2x).
Combined effect: poor 93->84, good 1->3, ok 9->12 (schwab). KEY FINDING: the fix + threshold relaxation barely
moved it -> the poor grades are GENUINE, not artifacts: 59 of 103 poor trades both entered weak-volume AND
exited below the hold's high; 48 scalps entered below average volume. Net outcomes +7K/52.6% but execution
consistently leaves money on both ends. All trades re-grok-reviewed clean. Read-only, validator 12/12.

## 2026-06-11 — Execution quality: full paper backfill + cutoff index-bug fix

Fixed a cutoff bug (cutoff=min(len(bars),...) let range index bars[len(bars)] -> IndexError) that crashed
every phantom/0-min trade (BWEN/INFU/BLBD) and silently dropped them via the per-row guard. Result: ALL 35
paper trades now graded (was 9); also recovered dropped scalps (OK-path 119->149, 155 total). Grok reviews
149 total, 0 parse_failed (35 paper + 114 schwab). Execution quality now fully backfilled across both brokers
and all trade types (scalp/swing/phantom). Read-only, validator 12/12.

## 2026-06-11 — Execution quality backfilled for swings + all trades grok-reviewed

Swing trades now graded via a DAILY-bars path (multi-day holds previously fetched ~95k 1-min bars and
failed): entry context + ~15 trading-day post-exit review, session-VWAP skipped where not meaningful,
bar_interval stored from the computed value. OK-path 30->119 (34 swing + 85 scalp; 6 truly-illiquid OTC stay
NO_INTRADAY_PATH). Grok reviews 98 total, 0 parse_failed. Real Accounts tab now badges 106/116 round-trips
(scalps + swings). Pattern surfaced: big PFE/GERN winners are weak execution (~50-63% capture, sold early);
swing losers (V/CSWC/PFLT/WRD/ARKG) are poor (held dead entries to the loss); AXTI multi-baggers win/ok with
severe missed-runner. Read-only, validator 12/12.

## 2026-06-11 — Alpaca SIP feed + intraday URL fix (OTC scalps get charts + badges)

Two fixes so OTC/microcap scalps get intraday bars: (1) Alpaca data feed iex->sip (full consolidated tape;
historical SIP free since 2024; env ALPACA_DATA_FEED, default sip). (2) _fetch normalizes isoformat +00:00 ->
Z — the + decoded to a space in the URL query so Alpaca 400d EVERY intraday fetch on the live endpoint (only
daily date-strings escaped). GCTS now 63 bars live; OTC scalps (GCTS/NUWE/ZSL/SHPH/GXAI) graded + grok-
reviewed (30 OK-path; 42 truly-illiquid stay NO_INTRADAY_PATH). Read-only, validator 12/12.

## 2026-06-11 — Drive sync fix: delete-before-upload (the --replace approach was impossible)

Root-caused why the hourly doc sync had been hanging at "sync start" with 0 updates for hours: the prior
--replace fix-forward was built on a false premise — gog CANNOT content-replace a Google Workspace Doc
("cannot replace content for Google Workspace files"), so every in-place update silently failed, and those
gog calls had no timeout so a stall froze the whole run. Reverted to the canonical delete-before-upload
(trash all copies by name -> create one fresh converted Doc = exactly one current Doc per name) with
per-call timeouts so a hung call is killed and skipped. Verified: full run completed (5 uploaded, 0 failed,
reached "sync done") instead of hanging.

## 2026-06-10 — Execution badges on main Trades tab + all paper trades Grok-reviewed

All 17 paper trades Grok-reviewed (24 total with the 7 Schwab; 0 parse failures). Execution badge (grade +
capture% + severe-runner warning + Grok-lesson tooltip) + replay overlay now render on the MAIN Journal
Trades tab (paper + schwab), not just Real Accounts. Fixed the badge-match bug: journal serializes entry_time
with T, execution-quality with a space -> normalized both (slice(0,19).replace(T,space)) in JournalHub +
SchwabJournal. Read-only; validator 12/12.

## 2026-06-10 — Execution-quality UI: hypothesis panel + chart MFE/MAE overlay

Backtesting tab now shows an Execution-Rule Hypotheses panel (sample, improved %, avg delta/sh, helps/hurts/
too-few verdict) from /api/v2/backtesting/execution-hypotheses — evidence only. Replay chart draws MFE (max
opportunity, blue), MAE (purple), and post-exit high (max-after-exit, orange) price lines from the
execution-quality record, so you see how much of the move you captured vs left behind. Endpoint extended with
entry_price/mfe_after_entry/mae_after_entry/post_exit_high. Read-only.

## 2026-06-10 — Execution quality: paper source + hypothesis backtest engine (E)

Paper-trade source added to build_trade_execution_quality.py (17 paper trades graded). Part E:
backtest_execution_hypotheses.py replays intraday bars and simulates rule variants vs actual fills
(volume_confirmed_entry, hold_above_vwap, macd_rollover_exit) -> trade_execution_hypothesis_results +
/api/v2/backtesting/execution-hypotheses. Evidence-only, never alters live configs; do_not_graft when sample
< 5. 46 trades x 3 variants: honest finding = avg deltas NEGATIVE (blindly applying would have hurt;
volume-delay -2.64/sh). Read-only, validator 12/12.

## 2026-06-10 — Execution quality: Grok coaching (D) + journal badges/overlay (F)

Part D: grok_execution_review.py feeds the COMPUTED metrics to Grok (free OAuth) -> strict JSON coaching
(execution_label, primary/secondary mistake, what-happened, what-to-do-next, backtest_hypotheses,
normalized_tags) stored in trade_execution_grok_reviews, SEPARATE from numbers; parse-strict (parse_failed,
no fabrication). 7/7 reviewed cleanly (NUWE premature_exit_before_runner, GXAI left 3.36% unrealized). Part F:
/api/v2/journal/execution-quality + v_trade_execution_quality_latest view; SchwabJournal shows an execution
badge per round-trip (grade + capture% + severe-runner ⚠, Grok lesson tooltip); replay modal shows
outcome/execution + capture. Read-only, validator 12/12. Remaining: paper source + Part E hypothesis backtests.

## 2026-06-10 — Replay-aware execution quality (foundation: schema + compute)

Separates OUTCOME from EXECUTION so profitable trades can be graded poorly. Part A: trade_execution_quality +
trade_execution_grok_reviews tables. Part C: config/execution_quality_rules.yaml (thresholds by strategy
family). Part B: build_trade_execution_quality.py computes entry RVOL/volume-confirmation, session-VWAP
relation, RSI/MACD, MFE/MAE, capture ratio, intraday + multi-day missed-runner, then deterministic grades +
flags (reuses Alpaca->Schwab bars). 48 Schwab trades graded (7 full intraday, 41 NO_INTRADAY_PATH honest);
RGNT=win/weak(early entry), GOVX/FATN/NUWE=win/poor(early entry+premature exit, 12-32% capture). Read-only,
validator 12/12. Deferred: paper source, Grok normalization (Part D), hypothesis backtests (Part E), UI (Part F).

## 2026-06-10 — 16:00 close marker + after-hours bars

Symmetric to premarket/open: afternoon trades (exit within 90 min of the close) now show the 16:00 ET close
marker (orange) + ~30 min after-hours bars. After-hours bars show price/volume but NO VWAP (session VWAP =
regular hours only, 9:30-16:00). Close marker renders only when the real 16:00 bar is in the window. Verified
AAPL 15:40 trade (30 after-hours bars + 16:00 marker) vs RGNT midday (none). Read-only.

## 2026-06-10 — Premarket bars + 9:30 session-open marker

Intraday charts now include premarket bars (fetched from 4:00 ET) and a yellow 9:30 open marker. Morning
trades (entry within 90 min of the open) display ~30 min premarket -> the open -> the trade; premarket bars
show price+volume but NO VWAP (session VWAP standardly resets at 9:30). The open marker only renders when the
real 9:30 bar is in the window (midday trades correctly show none). Verified: GSIT 09:47 scalp shows 4
premarket bars + 9:30 marker; RGNT 11:16 midday shows neither. Read-only.

## 2026-06-10 — True session VWAP (reset at 9:30 ET open)

Intraday charts now compute a TRUE session VWAP: bars are fetched from the 9:30 ET session open (not the tiny
display window), VWAP accumulates cumulative typical-price x volume from the open, and MACD/RSI get full
session context — then only the tight trade window is RENDERED. RGNT scalp: entry $3.35 shows below the ~$3.75
session VWAP (real context). Stopped using Alpaca per-bar vw (that is per-bar, not session). Read-only.

## 2026-06-10 — Chart audit fix: tight intraday window + ET times + Finviz cookie in modal

Audit found scalp charts showed the whole session (279 1-min bars for a 1-min hold) and dropped the fill
time. Fixed ohlc_charts: same-day trades now use a TIGHT window around the actual fills (pad = max(10min,
hold), capped 60min) — RGNT scalp 279 -> 21 bars; intraday timestamps converted to US/Eastern (DST-aware via
zoneinfo) so charts show market time; entry/exit markers land on the real fill timestamps (parsed from the
tz-aware stored times). Finviz: FINVIZ_COOKIE added to the Command Center secrets modal (refresh when it
expires); /api/v2/finviz-chart now returns a base64 data URI (server can't stream raw bytes) — tier-3
fallback image works (cookie verified VALID, the chart.ashx 302 just needed redirect-following + proper
serving). Validator 12/12.

## 2026-06-10 — Replay speed control + Schwab tier-2 OHLCV fallback wired

Replay charts gained a speed selector (0.5x/1x/2x/4x/8x). Schwab is now a REAL tier-2 data fallback:
schwab_transport.get_price_history (read-only market data, daily + 1-min) returns OHLCV; Schwab's payload has
no per-bar VWAP so the chart layer computes cumulative VWAP (typical-price x volume). Verified: Schwab
returned 21 live AAPL daily candles; VWAP computes for the Schwab path; validator still 12/12 (read-only, no
write surface). Hierarchy now fully live: Alpaca (OHLCV+VWAP) -> Schwab (OHLCV, VWAP computed) -> Finviz image.

## 2026-06-10 — Per-trade replay charts (TradingView Lightweight Charts, free)

Interactive per-trade charts in the journal: candlesticks + volume + VWAP + MACD + RSI panes, entry ↑ / exit
↓ markers + price lines, and a ▶ replay scrubber (TradingView-style bar replay). TradingView Lightweight
Charts (MIT, no account/data feed). Data hierarchy (all free/read-only): Alpaca historical OHLCV+VWAP
(daily + 1-min intraday for scalps) -> Schwab get_price_history (best-effort tier-2) -> Finviz Elite chart
image (tier-3, server-proxied cookie). scripts/ohlc_charts.py (fetch + EMA/MACD/RSI compute) +
/api/v2/trade-chart + /api/v2/finviz-chart. TradeReplayChart.tsx wired into Journal>Real Accounts (📈 per
round-trip) and the main Journal Trade Log (📈 per row). Verified live: AXTI swing 63 daily bars all
indicators + markers; RGNT scalp 279 1-min bars; delisted symbol falls back cleanly.

## 2026-06-10 — V basis corrected to Schwab authoritative + cost-basis intake + CSV upload tile

Operator uploaded Schwab Positions exports. The Roth Positions file proved the 130 V shares still HELD carry
cost basis $307.32/sh (NOT the $10.75 IPO override) — so V is not all IPO-basis stock. The override applied
$10.75 to 569 sold sh vs only 400 documented IPO sh. Fix: override format gained documented_qty (V capped at
400); the 169 excess sold sh underflow FIFO -> basis_unknown (true basis needs Schwab Realized Gain/Loss
export, never an extended hand override). V realized: +$168,160 -> +$117,356. Builder purges orphan rows on
classification flips. Authoritative basis infra: schwab_cost_basis_lots table + ingest_schwab_gainloss.py
(--apply ingests imports/schwab_gainloss/ realized+unrealized lots, --reconcile flags journal-vs-Schwab
divergences, Schwab wins); 24 held lots ingested. CSV upload tile (/api/v2/upload-csv + CsvUpload in
System>Brokers) for remote operators — whitelisted dirs, sanitized filename, traversal-blocked. Aggregates:
active 116 +$37,046 (52.6%), long-term trims 5 +$114,938, basis_unknown 13 (pending realized export).
Validator 12/12, no writes. imports/schwab_* gitignored. TAX NOTE: held V ~$307 basis suggests the in-kind
Roth transfer carried market-era basis — operator to verify with Schwab/tax advisor.

## 2026-06-10 — Journal consolidation + Drive-sync dedup fix

(1) JOURNAL: consolidated three divergent Schwab journal sources to ONE truth (schwab_round_trips). The
"Trades" tab (trade_closed) was stale (wrong V, missing 6/9 RGNT) and the backtester's paired_trade_
transactions was a stale MATERIALIZED view frozen 2026-04-30 (crude pairing). Now the builder refreshes
trade_closed from schwab_round_trips, and paired_trade_transactions is a LIVE VIEW over it (migration
2026-06-10). Both Trades tab + backtester show RGNT 6/9, V=+$168K long-term (not the phantoms), current.
(2) DRIVE SYNC: fixed the duplicate proliferation — sync-docs-to-drive.sh now finds the existing Doc by
name and uploads with --replace (update in place) + a name->id manifest (drive-sync-ids.txt), instead of
minting a new Google Doc every run. Existing duplicates archived separately (recoverable, not deleted).

## 2026-06-10 — Schwab API capability map (design doc, no code)

docs/architecture/SCHWAB_API_CAPABILITY_MAP.md — maps the full Schwab Trader API capability inventory to the
Trade AI v12 system design: BUILT (account/positions/transactions/orders/quotes reads, OAuth/Gate-A, ledger,
journal/round-trips, ToS watchlist fallback) · READY-but-not-wired (batch quotes, historical price, option
chains, fundamentals/instruments, market hours, real rate-limit numbers + split buckets, streamerInfo
streaming) · FENCED (every order type/management — Stage 2, api_write_enabled=false, NotProvenWrite) · N/A
(watchlists via API, paper-trading via API, streaming deferred by policy). Surfaces the "capable but not
wired" gap backlog (all read-only wires). Documentation only — no functions implemented.

## 2026-06-10 — Fix: pre-window long-held lots (V) — authoritative basis + FIFO-underflow guard

The journal was fabricating swing/day losses for positions whose opening lot predates the Schwab API window
(2025-07-19). schwab_journal_builder now seeds opening lots from operator-documented basis
(config/journal_basis_overrides.yaml — V at ~$10.75 split-adjusted IPO basis) + the old pre-window CSV buys,
in FIFO order; a sell with NO opening lot anywhere is flagged basis_unknown (entry/P&L null) — NEVER a
fabricated loss. New columns basis_status/basis_source; long-term trims (pre-window lots) are realized P&L
but EXCLUDED from active trading stats. Result: V flips from -$24K phantom "swing losses" to +$168K long-term
realized GAIN (a 16-year IPO hold trimmed at ~$307 vs $10.75); active trading +$37,046 / 52.6% win; 12
symbols flagged basis_unknown (ADBE/AMAGX/AMC/BRO/BUG/EKSO/FSELX/FSPTX/IPM/SCLX/TSLA/UBER). Endpoint splits
active vs long-term-trim vs basis_unknown; Real Accounts tab shows banners + active-only table. Schwab
read-only throughout; validate_schwab_no_writes 12/12 (guard 8 updated for the live cred-in read state).

## 2026-06-09 — Fix: in-kind transfers no longer counted as trades (Schwab journal correction)

A TRADE with netAmount~$0 = shares moved WITHOUT cash (in-kind transfer / re-registration disguised as a
trade), not a discretionary buy/sell. schwab_transaction_ingest.py now labels these Transfer In/Out so the
round-trip builder skips them. Real finding: 1,000 V (Visa) shares TRANSFERRED into the Roth ($349 carried
basis) were treated as a "Buy entry", so the later partial liquidation (575 sh @ $304-312) manufactured
three -$8K phantom "swing trade" losses (-$24K) that distorted the record. After fix + rebuild: 131->116
round-trips, win rate 48.9%->52.6%, net P&L +$17.4K -> +$37.0K; V drops from 3x-$8K to 1x-$176. The real
realized loss stays visible in the ledger as a transfer (tax-correct), not as trading skill. Permanent —
the daily cron applies it going forward; grok re-graded the corrected set.

## 2026-06-09 — Free Grok OAuth review lane + tightened journal prompts + lane badge

Journal reviewers (Schwab round-trips + paper trades) now default to the FREE Grok OAuth lane (xAI proxy
:8645) via shared scripts/llm_lane.py (grok|local, auto-fallback; no metered APIs). Prompts tightened:
lessons must be trade-specific (real numbers/hold/exit) and the generic "tighten stops" boilerplate is
banned unless the loss truly came from a stop — Grok output is far sharper (V loss -> "thesis was invalid
months earlier, demanded exit discipline" vs prior boilerplate). review_lane tracked (schwab_round_trips) /
coach_notes (paper); /api/v2/journal/schwab-round-trips returns it; Journal->Real Accounts shows a
grok/local badge + tooltip per row. Daily crons use grok by default (fallback local if proxy down).

## 2026-06-09 — LLM grade+lesson on real closed trades (Schwab + paper); backtest sims excluded

Journal review parity across real accounts. schwab_journal_classifier.py tagged all 131 Schwab round-trips
(strategy + entry/exit letter grade + lesson, in schwab_round_trips → Journal Real Accounts). New
journal_review_builder.py reviews real PAPER closed trades (trades view, source=paper_trades) into the
canonical journal_trade_reviews (setup, entry/exit grade→1-5 exec/risk score, lesson, strength/mistake tags),
idempotent by trade_key. Backtest SIMULATIONS (strategy_backtest_trades, 18,966 — synthetic per-strategy
replays, already strategy-scored, ~31h to grade, known false-positive labels) are EXCLUDED by design — only
the 201 real closed trades (48 paper + 153 Schwab) are graded. Daily cron: 18:15 Schwab ingest→build→classify,
18:30 paper journal review (both idempotent, flock-guarded, read-only vs Schwab).

## 2026-06-09 — Schwab Stage 1 LIVE: reads proven, ledger reconciled, journal round-trips (writes still locked)

Credential-in proof pass complete. OAuth bootstrapped (manual-paste, token through the manager, encrypted);
one login covers all accounts (canonical_token_key + per-account hash); 3 accounts hash-mapped by last-4
(ambiguity refused). Live reads proven (account/positions/orders/transactions/quotes; normalizers match
fixtures). schwab_transaction_ingest.py reconciled the ledger API-authoritative (replace-in-window): 508
lossy CSV -> 416 API rows (granular slippage fills, qualified/ordinary dividends, transfers; sweep/margin
noise filtered; $10,553 dividend income; backup taken). schwab_journal_builder.py built 131 round-trips
(5-min fill aggregation + FIFO): 48.9% win, +$17,410.96 net (RGNT scalp +$59.91). schwab_journal_classifier.py
adds LLM strategy/grade/lesson per trip. Surfaces: System->Brokers SchwabMonitor, Journal->Real Accounts
SchwabJournal. Daily cron ingest->build->classify. Separate from paper_trades (gate stays sandbox-only).
Schwab WRITES still NOT_PROVEN/fenced (validator 12/12, api_write_enabled=false). Deferred: Gate-A 7-day
roll-forward observation, real rate limits, CSV retirement (10-day dual-run), watchlists.

## 2026-06-09 — Schwab app creds in the Command Center secrets modal (credential-entry path ready)

System → Admin → API Keys & Secrets now manages SCHWAB_APP_KEY + SCHWAB_APP_SECRET (masked, write-only,
audited like every other secret) and SCHWAB_CALLBACK_URL (editable config, shown in full, `cfg` tag).
Reuses the existing modal mechanics exactly (secrets_admin.py KNOWN + new KNOWN_CONFIG; atomic .env 0600
write; audit by key name only). DELIBERATELY excluded: SCHWAB_REFRESH_TOKEN (OAuth-flow-owned by
schwab_token_manager) and SCHWAB_TOKEN_ENC_KEY (rotating it orphans every stored token). The token manager
already reads these from .env (_have_app_creds); no live Schwab call. Lets the app key/secret be entered
the moment the Developer Portal app is approved.

## 2026-06-09 — Schwab Stage 1: read-only transport via schwab-py (writes fenced; live NOT_PROVEN)

Adopted schwab-py 1.5.1 (MIT) as the READ-ONLY transport beneath schwab_token_manager.py (which stays the
encrypted system-of-record). Step-0 confirmed both flag-back conditions clear: auth decouples via
client_from_access_functions(token_read_func, token_write_func), and the wrapper writes are fenceable at
the boundary. New scripts/schwab_transport.py: token hooks wired to the manager (read_oauth_token/
write_oauth_token), pure normalizers (account/positions/orders/transactions/quote) proven vs recorded
fixtures, shared rate bucket, build_client fails closed (NOT_PROVEN) without portal creds. WRITE FENCE:
place_order/cancel_order/replace_order RAISE NotProvenWrite and the wrapper client's writes are never
called/exposed; schwab-py imported only at the transport boundary. validate_schwab_no_writes.py now 12/12
(added fence-static, no-wrapper-write-calls, boundary-only-import, runtime-fence, Rule-9). Watchlists
NOT_AVAILABLE in 1.5.1 (not fabricated). Everything Schwab-LIVE stays NOT_PROVEN until a separate
credential-in proof pass; payload schemas to reconcile then.

## 2026-06-09 — No-hardcoded-values rule now ENFORCED by the git hook

check_no_secrets.py (pre-commit/pre-push) now also BLOCKS hardcoded chat IDs and broker-name fallbacks,
making the "nothing hardcoded" rule mechanical:
- Chat IDs: flags any TELEGRAM_CHAT_ID / TRADEAI_PROPOSAL_ALERT_CHAT_ID value (read from .env) appearing
  as a literal in tracked .py — use tg_chat_ids.chat_ids().
- Broker names: flags the fallback/default anti-pattern (or "alpaca_paper" / or "schwab_x")) at end of
  expression — excludes membership tests (or "fidelity" in source); `# hardcode-ok` opts out a legit case.
Fixed the 2 pre-existing instances it caught (api_v2 proposal routing + atm_position_reconciler) to source
the default from DEFAULT_PAPER_ACCOUNT (.env / .env.example), so no broker name lives in code. Verified:
blocks a staged chat-ID + broker fallback; opt-out works; tree clean (3827 files).

## 2026-06-09 — Max-hold time-exit proposals (advisory, approval-gated)

Turns the previously-unenforced `auto_exit_at_max_hold` config into an ACTIONABLE, gated time-exit —
no silent auto-close. `generate_max_hold_exit_proposals.py` (cron 10:20 weekdays) creates a
paper_time_exit_proposal for each open position held past its strategy's max_hold_days. The operator
approves via System/Open-Trades UI or `POST /api/v2/time-exit-proposals/decide`; APPROVE is hard-guarded
(ALPACA_MODE==paper + live_trading_interlock on the trade's account + the existing close_paper_trade
path). Verified: guard chain passes for paper, refuses non-paper, reject path works. `GET
/api/v2/time-exit-proposals` + TimeExitProposals.tsx (Trading → Open Trades). Migration additive
(paper_time_exit_proposals).

## 2026-06-09 — Secrets hard-rule + Command Center secrets modal + DB stability

**HARD RULE — no credential hardcoded anywhere, ever synced to git (enforced):**
`scripts/check_no_secrets.py` + git **pre-commit/pre-push hooks** (`scripts/install_git_hooks.sh`) BLOCK
any commit/push containing an API-key pattern, a secret file (.env/*.key/*.pem/credentials), or any
literal value from `.env`. Verified: blocks a staged Anthropic key; tree clean (3819 files). `.env` +
`config/broker_credentials.env` + `secrets_admin_audit.jsonl` gitignored; Drive sync already excludes
`.env`/keys/credentials.

**Leaked-key response:** a now-DEACTIVATED Anthropic key was found in git *history* only
(`reports/portfolio_live.html`, repeated commits) — current tree clean, `reports/` gitignored, repo
private. (History scrub offered separately.)

**Command Center secrets modal:** System → Admin → "API Keys & Secrets" (`SecretsManager.tsx` +
`scripts/secrets_admin.py`, `GET/POST /api/v2/admin/secrets`). Write-only: lists key names + masked
`••••1234` only, never returns/logs/displays a full value; atomic `.env` (0600) write; audited (key
name only). For rotating ANTHROPIC_API_KEY etc.

**DB stability:** fixed a transaction leak in `unified_stop_supervisor.py` (a SELECT on the shared
db_adapter connection never rolled back → idle-in-transaction → ACCESS-EXCLUSIVE lock pile-up that hit
the connection-slot limit). Added `finally: rollback()`. Backstop: `ALTER ROLE trade_ai SET
idle_in_transaction_session_timeout='5min'` so any future leak self-terminates.

## 2026-06-09 — Holdings wipe-guard made mandatory (behavior change)

`protected_holdings_write()` is now mandatory for all 7 holdings/current-state writers (db_adapter,
portfolio_loader, portfolio_server, holdings_reconcile, phase2/phase3 resolvers, patch_holdings_cost_basis)
via `scripts/holdings_guard.py`. Added a catastrophic-drop reject (new total < 50% of last-good) + loud
Telegram alerts on block/restore. A/B split: wipe-guard mandatory for all; basis-preservation opt-in
(`protect_basis=True`, Schwab sync only) so legitimate basis edits aren't reverted. **Closes** the
programmatic-wipe vector; **does NOT close** the deploy/zip-extraction vector (tracked follow-up:
pre-deploy state-guard). Proven: empty→rejected, drop→rejected, forced-failure→restored byte-identical,
normal write OK ($1.24M/48, no false positive), 0 screener/classifier/GO-WAIT/ATM files touched. See
`docs/architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`.

## 2026-06-09 — Schwab Phase 1 scope clarification (docs/git-log only; no behavior change)

> Phase 1 proves safety guards under simulated Schwab failures. It does not prove live Schwab
> connectivity. Live OAuth, real reads, account-hash mapping, true rate limits, token roll-forward
> behavior, and Schwab API payloads remain NOT_PROVEN pending Developer Portal credentials.

- Commit `23f17865` uses "(PROVEN)" in its title to mean the safety guards were proven under simulation.
  It does NOT indicate live Schwab connectivity. See this clarification and
  `docs/architecture/SCHWAB_API_PHASE1_READONLY_FOUNDATION.md`.
- Commit `2f19ffba` is the honest Phase-1 doc ("guards proven (simulated) / live NOT_PROVEN").
- No code, config, migration, test, schema, gate, or capability-flag change in this clarification. The
  token manager, protected holdings writer, adapter, guards, and every NOT_PROVEN stub remain
  byte-identical.
