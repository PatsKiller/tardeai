---
name: research-intelligence-desk
description: Canonical knowledge for Trade AI v12's Research Intelligence desk (CC v3 → Intel → Research Intel), Gain Guardian exit-intelligence engine, Watch Desk, and the Engine Room infrastructure track. Trigger on: Research Intelligence, RI desk, briefs, staged ideas, star/hide/dismiss, QA lint, desk snapshots, Gain Guardian, exit intelligence, parabolic/giveback/HWM, trim advisories, 17:40 shadow run, watch desk, watchlist, watch directives, directive gate/dedup, pullback/MACD, sector monitor, held badges, source scoreboard, operator alerts, maturing the research engine. Written 2026-07-16 (post-Watch-Desk-v3 rev, five-session day). Anything dated later supersedes — diagnose live before trusting details.
---

# SKILL: research-intelligence-desk

Written 2026-07-16 late rev after the FIVE-session build day (RI v3.0 → Gain Guardian shadow → RI v3.1 → Watch Desk v2 → Watch Desk v3) plus the trade-ai/summary transport fix. Anything dated after 2026-07-16 supersedes this file — diagnose live before trusting details here.

## 1. WHAT THIS FEATURE IS

A single intelligence desk aggregating company research, news/sentiment, analyst consensus, retirement/tax monitors, Hermes engine signals, and portfolio-aware sizing into an actionable feed. Design bar: institutional (Bloomberg/Goldman-desk trust standard) — instant load, every claim dated and sourced, operator curation that persists, no regurgitated garbage, direct paths from insight → staged idea → watchlist / watch directive / paper proposal. Advisory-only; nothing on this surface executes anything.

**Key surfaces:** `ResearchIntelligenceHub.tsx` (frontend), `scripts/lib/research_intelligence*.py` (feed builder + narrative + portfolio + stage modules), routes in `scripts/api_v2.py`, content produced by Hermes topic research + monitor writers. Dashboard route: `/v3/research-intelligence`.

## 2. VERSION LINEAGE (all shipped 2026-07-15/16)

- **v1 → v2.7** (7/15–7/16 pre-dawn): taxonomy, freshness/archive, retirement pillar, narrative enrichment, category-gated advisory, conviction/action strips, Stage Trade + cross-theme.
- **v3.0 Decision Desk** (45bfa56b…9649cd8a): trust fixes (counts were PRE-DEDUPE, not archive-inclusive — root cause), lane filters made real, registry-echo stubs demoted to "Queued research" cards with Run-research buttons, Hermes deep integration (composite/rank chips, ✦ external-intel badges, wire from `alert_events` — `hermes_score_alerts` table does NOT exist, flag-back canon), watch-directive chips, research queue (drains 16:45 ET + 02:40), Discovery→proposed-topics rail, staged-idea lifecycle (staged → watchlisted / directive_created / proposed_paper / dismissed / expired-14d) with verified promotion (XLV → paper proposal #2719). E3 rule: staging REQUIRES a caller-provided exit/stop note.
- **v3.1 Institutional Desk**: materialized snapshots (`data/runtime/ri_snapshots/{lane}.json`, ETag/304; warm 10–19ms, 304 ~1.1ms/0B), calm client (exp backoff + "Desk as of" chip), ★ Saved tab, per-brief Hide (`hidden` column; unhide fold; never deletes), ▼ demotes rank, weekly feedback tallies, provenance banner + absolute-ET hovers + `fmtET()`, deterministic QA lint (first run 21/50), outbound links (SourceLinks + shared `components/TickerLinks.tsx`), tabular numerals. Keyboard nav SKIPPED (timebox).
- **Adjacent same-day:** `/api/v2/trade-ai/summary` (~500B) replaced the multi-MB header pull — the VIX "—" tile was a TRANSPORT bug (Tailscale + 30s abort + 6-connection limit), not data. Lesson generalized: tiles must never poll multi-MB endpoints.

## 3. GAIN GUARDIAN (holdings exit intelligence — live book)

**Why:** paper had the full profit-protection ladder (Phase 191/206); nothing watched the real ~$1.27M for parabolic extension or gain giveback. Journal evidence: avg entry RSI 68, 81% D-graded entries, ~$196K left on table, V ≈ 96% of all P&L.

**Engine:** `scripts/holdings_gain_guardian.py`, cron **17:40 weekdays** (after 17:05 protection advisor + 17:35 stop-drift), flock-guarded, zero LLM. Imports (never refactors) `holding_protection_advisor` + `holding_family`. `--test-render` exercises chart+digest with zero writes.

**Data model:** `holding_high_water_marks` (ratchet-only; `seeded_from='bars_252d'` — purchase-anchored HWMs impossible: `schwab_cost_basis_lots` 24 rows / 0 dated / 2-of-4 accounts / stale 06-10) + `holding_exit_metrics` (ext50/ext200 ATR, rsi14, rvol20 fail-soft with weight renormalization, up_streak, slope_accel, open_gain_pct, giveback_frac).

**States** (config/gain_guardian_thresholds.json): EXTENDED(≥55)→RAISE_STOP; CLIMAX_RISK(≥75+rvol≥2)→TRIM 25%/33%@≥8%wt; GIVEBACK_WATCH(≥0.25 on gain≥15%)→REVIEW; GIVEBACK_BREACH(≥0.40, or ≥0.30@≥8%wt)→TRIM+RAISE_STOP urgent. Priority cohort: unprotected ≥$10K gain≥15% first. Unstoppable funds + names stopped out ≤5 trading days: never RAISE_STOP. Provisional HWMs cap at REVIEW.

**Tax gate:** NO LT/ST claims — "holding-period term unverified — export dated Cost Basis from Schwab to confirm LT/ST before acting"; IRA-first routing; gain-$ arithmetic only; basis_unknown → REVIEW cap.

**Outputs (DARK until `--promote`):** `exit_intelligence` RI rows (→risk_regime), mplfinance charts → `data/runtime/gain_guardian_charts/` (gitignored), ONE Telegram digest/run, morning-brief GAIN GUARDIAN section, `stage_prefill` in evidence (passes RI E3 stop-note gate). Outcomes: `exit_advisory_outcomes` Sunday 09:00 (+5/+21d vs SPY).

**SHADOW WINDOW: first cron run 2026-07-16 17:40; promote NO EARLIER than ~2026-07-30 after reviewing `gain_guardian_shadow_report.py --days 10`.** First manual runs: 32 positions, 0 advisories, V nearest EXTENDED (46.8), 0% provisional. Inert by design until reviewed.

## 4. QA LINT + CURATION SEMANTICS

Deterministic lint (`research_intelligence_qa_lint.py`, inside materialization): `undated_claim`, `off_universe_mention` (Beauty-Farm class; corporate-suffix detector + universe check), `unsourced_advisory`, `no_counter_view` (else "single-view — treat as unconfirmed"), `duplicate_of` (0.8 shingles). Flags cap Tier A→B, gray chips, `qa_flag_counts` tracked. First run 21/50 → 0/50 after Engine Room v1 (2026-07-16): prevention now lives at write (wire degrade + universe guard); lint remains the backstop for unguarded legacy items.

Curation: ☆ star (rank boost; ★ Saved tab), ✕ Hide (`hidden=true`, recoverable, never deletes), ▼ demotes, topic-proposal Dismiss is a DIFFERENT object. Stage/RI Ideas → `ri_staged_ideas.json` (lifecycle, 14d expiry, created/expires/source shown).

## 5. REFRESH MODEL

Content production overnight/after-close ONLY. Queue drains 16:45 ET + 02:40 (≤10 topics). Snapshots rebuild after content runs + drains + 06:35 cron + operator "Rebuild desk (≈30s)" (compute, RTH-allowed); "↻ Refresh desk" just refetches. Cards: relative age + absolute hover + refresh-due chip (amber = Queue-button population).

## 5b. WATCH DESK v2 (7d72bdb + e155dbe)

**Header truth (SPAXX finding):** the $98,650 flip was `overview()` silently swapping canonical total for derived Σ(market_value) on >$500 drift while SPAXX ($96.9K Fidelity MM sweep) sat unpriced mid-pipeline. Canonical NEVER swaps now; drift = labeled `total_value_drift`. Lesson: silent fallback substitution of a canonical number is always a bug.

**Directive governance:** `lib/watch_directive_gate.py` fences every trend creator (challenger, strategy_planner, sector_universe, Telegram soft-warn, UI needs_confirm+force) via `canonical_family()` — same-family → alias on survivor, zero new rows. Cap 150 (config); overflow → `status='proposed'` + Promote fold. Sunday 10:30 hygiene (tiers 1–2 auto, tier-3 Telegram one-tap). State at v2 close: 288 active / 27 paused / 193 archived.

**Position-aware:** `_held_context()` (holdings + stop_lifecycle) → `● HELD · shares · stop (signed)` badges; held TRIGGER near stop → amber averaging-down conflict strip. `components/TickerLinks.tsx` shared. "Top 200 of 5,168 · Hermes rank".

**Pullback loop:** `pullback_trigger_history` + `reconcile_pullback_outcomes.py` (Sun 09:45; same-bar → stop conservatively) + honest hit-rate header. The UI's Dismiss endpoint NEVER EXISTED server-side before v2 — now one canonical handler with 10-trading-day cooldown (re-show early on ≥25% score gain).

## 5c. WATCH DESK v3 (19434adc) — from watching to learning

**Source scoreboard:** `watch_candidate_events` (13,093 events, 120d backfill; anchors only where first_seen_price real — 95% of directive hits unanchored → NOT_EVALUABLE; **journal hop UNLINKABLE** — trade_journal has no source keys, attribution stops at the proposal hop) + `reconcile_watch_outcomes.py` (Sun 09:50, 400/run). **FIRST EVIDENCE: ai_discovered median 21d α −4.82% (n=385); operator_add −6.67% (n=13)** — the discovery lane underperforms SPY. Directive rows carry `21d α (n)` + `conv %`; needs-review sort = worst-α-then-coldest; Finds track-record header; source-league line in freshness report + hygiene digest. Evidence renders, operator culls — no automation.

**Operator alerts:** `watch_alerts` + `watch_alerts_eval.py` (*/20 RTH). Conditions: price_cross_above/below, rsi_above/below, directive_hit ONLY (52w/ATR/earnings columns don't exist — flagged, not faked). `watch_alert` added to alert_events CHECK constraint. Batched Telegram via `bypass_router=True` (operator-armed = P1), cap 12/day (config/watch_alerts.json), `(alert_id,date)` dedupe, one-shot auto-disarm / recurring 5-td cooldown. 🔔 composer on watchlist rows; armed chip on WatchHub; list at `/api/v2/watch/alerts/list` (SPLIT from POST path — see gotchas). E2E verified live (CSCO).

**Context layer:** `setup_context` per row REUSES server `_hermes_setup(rsi, trend)`; glyphs + hint + "deterministic context — not a quality score" label; rendered ABOVE locked Card v4, never inside. `setup_quality_prior` untouched (sample gate is deliberate — 0 favorable is honest). Regime chip once at tab level.

**Thin surfaces:** Finds tab = CIO band + ALL 90d screener/discovery emissions with per-row α/verdict/→proposal + track record (10,141 finds · α −4.82% · 123 converted). `imports/tos_watchlists/` created with honest awaiting-export README (no blind parser). items payload 1.41→1.12MB (conservative: `hermes_score_components`/`dual_consensus_json` KEPT — locked Card v4 reads them; tail = Engine Room follow-up).

## 5d. WATCH DESK v4 — TERMINAL GRADE (EXECUTED 2026-07-16 late — see docs/architecture/WATCH_DESK_V4.md)

Commits 65d79b18..c776a8a4. **WS-A**: `lib/watchTokens.ts` + `components/TerminalChip.tsx` are THE design system for all Watch tabs (zero raw hexes, TYPE floor 10, one mono, rails, 4-class chips, j/k+s+a keyboard; Card v4 still LOCKED — pages conform TO it). `terminalHubChrome` raised 9→10px for ALL hubs. **WS-B**: server-side saved views via new `ui_prefs` table (`/api/v2/ui/prefs` POST, `/get` GET — GET-map-swallows-POST hit AGAIN); bulk Star/Alert cap 25 (Stage/Hide have NO row endpoints — open); items payload 929KB honest floor (ToS desk uses ?full=1; dual_consensus_json is NOT card-rendered — the v3 'keep' was over-cautious). **WS-C**: directive drawer (`/watch/directives/detail`), ttl_days ENFORCED in Sunday hygiene ('expired' status added to CHECK; resume un-expires), tier-3 merge approvals in-UI via dedup module plan([3]) + governed merge_into (#420+#612→#244 pending). **WS-D**: converted-α −11% (n=4) vs all −4.82% (n=385); `config/watch_quality_gate.json` gate (n≥30, α<−2%) folds ai_discovered emissions; auto-lifts. **WS-E**: `sector_rs_daily` + cron 17:20wd + sparklines; book overlay via resolved_sectors look-through — Tech 23.8% flagged overweight-lagging. **WS-F**: regime disclosure, score-formula hover, `discovery_trace_id` threaded pullback-proposal→fill (pbm- slugs); FLAGGED broker-adjacent: alpaca_paper_adapter/alpaca_sync direct fills + watchlist/screener proposal writers still traceless.

## 5j. DEFENSE DESK v3 (EXECUTED 2026-07-18 — see docs/architecture/DEFENSE_DESK_V3.md)

Commits affddabc..3a41ab29. CUT LINE INVERTED — recommendations FIRST. **WS-R** defense_recommendations.py (17:50) + config/defense_recommendations.json (ALL knobs): R3 rotate-in (underweight LEADING sectors, ETF-always + top-2 Hermes constituents w/ liquidity/extension/earnings rails), R2 move-out (≥3 factors w/ values, tax-gated, 10d SHADOW from 07-18), R4a inverse (PSQ if QQQ rs20<−2 else SH, decay warning), R4b taxable shorts (LAGGING pool, anti-squeeze SF<10%, min_price $10, stop≤10%, NEVER-held-symbols, buy-stop mandatory, ≤2% cap), R4d CC (100sh+ in WEAK/LAG sectors, 21-45DTE 0.2-0.3Δ); put structures render LOCKED (options_level unfilled); field guard 12 fields complete-or-absent (unit-tested); paper twins → paper_trade_proposals PENDING (defensive_short/inverse_etf_hedge). **R1** options_chain_snapshot.py (17:35): read-only chains via existing fence, 20/21 covered (DIVI chainless), aggregates→option_chain_snapshots, deltas/PC-means accrue w/ n stated. `/api/v2/defense/recommendations`. **WS-T** W/M/Q boards (sectors rs5/20/60; industries rel1w/1m/1q client-computed vs SPY.long — industry_performance table NEVER existed, it's industry_momentum_state) + movement chips (rank vs next-longer TF). **D3**: DASH scale in watchTokens (verdict22/panel16/section14/data12/chip10-caps, 7-9px BANNED); check_design_tokens.sh IN npm build (baseline-ratchet, 197 legacy frozen, defense=0, proven blocking); 4-row hierarchy w/ collapsed folds. Rails caught day-1 garbage: LDOS short-while-held, MNTS 32%-stop (twin cancelled). GOTCHAS: enrichment cache has NO price (use ticker_prices); git-checkout destroyed an uncommitted rewrite once; cron cd 6th miss; NO 401k account exists (tabs from capabilities config). Self-score 6.5/10 — caps: shadows unproven, OI history thin, options_level unfilled.

## 5i. DEFENSE DESK v2 (EXECUTED 2026-07-18 — see docs/architecture/DEFENSE_DESK_V2.md)

Commits 4c72aa5a..57e4ff37. **A2**: compute_market() — SPY/QQQ/IWM/DIA rs vs SPY, style spreads (VUG−VTV, IWM−SPY, RSP−SPY) persisted as `STYLE:<key>` rows sharing the sector debounce, NH/NL from movers capture (top-15-capped, labeled), market_state_line() one-liner (template unit-tested). **C2**: v1 "—" cells = NAME MISMATCH (Financial Services/Consumer Cyclical/Basic Materials/Consumer Defensive/Communication Services) → `sector_aliases` config + `_aliases()` in breadth/hermes/news queries; all 11 sectors populated. **B2**: finviz_industry_groups.py — grp_export.ashx **v=141** (144 industries × Perf W/M/Q/H/Y/YTD; v=152 lacks perf), quadrants = rel1m level × rel1w direction via same classify(); states persist on `--close` only (cron 12:30 refresh + 16:18 close, 2×/day); alerts ONLY for book/`operator_starred_symbols` intersections (watchlist_items' 5,200 actives would mark everything watched) cap 3/day; candidate pools source_type=industry_momentum; fail-closed <100 groups; `/api/v2/defense/industries` (separate — Home strip stays light). **D2**: DefenseHub rebuilt — RRG SVG scatter (Sectors|Industries toggle; industries plot held/starred+extremes), heatRamp cells, book bars, industry drill, 30-session confirmed-transitions timeline (backfill now emits debounced `confirmed` ledger via same fire() rule; 89 raw→64 confirmed), whf fold debounced w/ raw-flip footnote, zero raw hex. **E2 = CUT** (no v1 engine started; all pre-verified viable — session 3 order: WS-B→WS-C→WS-D2-D5). GOTCHAS: held-ETF repricer rows force date-intersection in RS math; fail-soft excepts need rollback() (InFailedSqlTransaction); dispatcher wraps payloads under `data`; cron `cd` caught a FIFTH time.

## 5h. DEFENSE DESK v1 (EXECUTED 2026-07-17 late — see docs/architecture/DEFENSE_DESK_V1.md)

Commits c332fd6f..fbfb2598. Visibility core A+E+F+D1 (B/C/D2-D5 next session, ALL pre-verified: chains readable via get_option_chain, short_float_pct captured, paper short works, TAXABLE MARGIN VERIFIED type=MARGIN). sector_momentum_engine.py nightly 17:25: RS 5/20/60 vs SPY from ticker_prices (date-aligned!), 4 quadrants, 2-close debounce, <=4 alerts/day, book-weighted severity; sector_momentum_state table + /api/v2/defense/posture + Trade->Defense page + Home strip. Would-have-fired: Tech->LAGGING Jul 13, alert would fire Jul 14. GOTCHAS: book sector weights = direct holdings only (SCHG lookthrough pending D2); news sentiment lane idle; hermes table = hermes_score_history NOT hermes_composite_scores; CRON NEEDS cd (4th catch).

## 5g. HOME v2 COMMAND BRAIN (EXECUTED 2026-07-17 — see docs/architecture/HOME_COMMAND_BRAIN_V2.md)

Commits 50fd3de0..b7fc3391. Row 1 = Market Movers (finviz_market_movers.py, 10 signal screens via the PROVEN export.ashx path + GLOBAL finviz_throttle, cron */12 RTH w/ cd+flock, /api/v2/market-movers ETag+held flags) · Book Treemap (/api/v2/portfolio/book-map = holdings×symbol_profiles-sector×risk-stop-overlay; dependency-free squarify; heatRamp() in watchTokens is THE ramp) · Major News (/api/v2/news/symbol-headlines = news_articles through news_symbol_guard ONLY, honest empties). homeLabels.ts = the plain-English dictionary (states/runLabel/thresholdSentence/plainAlert + raw-chip fallback; raw ALWAYS in tooltips); D3 'n/a · transfers' suppression in BOTH perf cell renderers. Click map complete (findings doc). DEBT: 59 legacy hex in HomeHub; performance endpoint AT 100KB budget.

## 5f. REPORTS DESK v3 (EXECUTED 2026-07-17 — see docs/architecture/REPORTS_DESK_V3.md)

Commits a405b3c3..d552f00f. ONE CORPUS RULE: /reports/list?qv= filters server-side and returns qv_counts from the same pass — chips can never disagree with the list; portal-summary feeds ONLY the Action Queue; severity headline = raw events, inside the analytics fold. Indexing policy + producer registry are CONFIG (config/report_index_policy.json, config/report_producer_registry.json). SYSTEM tab = /reports/system-rollup (reuses health snapshot/data-source/consumption; per-panel timings_ms) + system_rollup_daily nightly 20:40 + Daily System Digest (deterministic md, catalog family system_digest, ONE telegram line). Preamble: strip_preamble/clean_advisory in research_intelligence_qa_lint (preamble_leak flag); iterate_research_topics cleans at WRITE; 16/31 advisories backfilled. Analyst: need-refresh counts are TWO labeled scopes (eligible vs all-covered); sub-$1k residual fold; registry verbs display-mapped for held names; acked REMOVED (no write path). GOTCHA: new quick views must be added server-side (_qv_match), and never register 1-param non-query ROUTES handlers bare (trade_ai force-collision class).

## 5e. REPORTS DESK v1 (EXECUTED 2026-07-16 night — see docs/architecture/REPORTS_DESK_V1.md)

Commits f6b481db..7921fd19. Library = Reports landing tab (catalog via EXTENDED generate_reports_hub — one indexer; light `/api/v2/reports/catalog`; viewer = HTML-sibling iframe, no mammoth). Brief renders from `aegis_morning_brief_{date}.json` sidecar (additive; Telegram sacred); `/reports/brief/regenerate` is deterministic-light. Analyst: held names never show candidate verbs (reporting_engine display-site fix), `/reports/analyst/status` defines counts (eligible 29 · covered 431 · fresh 208 · refresh 223 age≥7d), CUSIP fold. WS-D `/reports/analytics` + alert_daily_digest 17:55wd; **hermes_rank_surge = 65% of ALL alert volume (15,259/23,507, 0 acked) — threshold review pending**. `reports_portal._tg_plain` = THE formatter for stored Telegram HTML. Weekly DOCX has Hermes Intelligence Highlights (lib/report_intel_highlights); MONTHLY flagged (shared generate_portfolio_brief). psql-johnclaw myth killed: role never existed; ~/.pgpass installed.

## 6. ENGINE ROOM v1 (EXECUTED 2026-07-16 — see docs/ENGINE_ROOM_V1.md)

All four workstreams shipped + verified same-day. **WS-1 Path B** (Path A gunicorn INFEASIBLE — raw http.server handler, not WSGI): `_peer_closed()` disconnect detect before compute + in-flight registry + 25s abandoned-compute watchdog thread in portfolio_server.py; verified 15-abort storm → health 1ms, CLOSE-WAIT ~0 (was ~33/10min). GOTCHA: `recv(MSG_PEEK)` on a timeout-mode socket blocks the full socket timeout — the zero-timeout `select` guard in `_peer_closed` is load-bearing. symbol-cards (1.95MB top offender) now 5-min cache + ETag → 304/14ms. **WS-2**: `user_research_topics.sources_json` + auto_research persists web sources; sourceless advisory degrades to wire in `enrich_narrative` (`provenance_grade`); synthesizer `--ids` targeted regen; lint 21→0. **WS-3**: `lib/universe_guard.py` at generators (synthesizer + auto_research), unknowns disclosed in-brief + conf capped 0.5, stored in `evidence_json.universe_guard`; lint skips guarded items. **WS-4**: backlog was 99% dup inflation (3 topics × ~825) → collapsed 2,480 reversibly (`rejected`+`duplicate_collapsed`), true backlog 30; source_surface 2,505-unknown → 0 (writers now attach); drain was STARVED (oldest-60 window all resolved) → `drained` tag excluded in SQL; nightly drain cron 02:20 N=25 + Telegram line.

## 7. HARD GUARDRAILS

Advisory/paper only; no broker writes, no 2FA/gate/threshold/supervisor/Phase-191/scope-governor/momentum_scalp edits. Zero cloud LLM in request paths. Never delete — hide/flag/expire/alias are states. Iron-rule holdings check around `data/` writes ($1.0–1.4M, count>0, else STOP). No secrets (hooks live). `npm run build` before UI screenshots; verify SERVED bundle. Honest sample sizes (n<10 → render n, abstain).

## 8. WORKING PATTERNS + GOTCHAS (proven this cycle)

- Diagnose-first with flag-backs; docs lag 30–40%, live tree wins. DB user is `trade_ai` NOT `johnclaw`; port 7777.
- lib/ edits need full server restart (`kill -TERM MainPID`); hot-reload covers api_v2 only; snapshots need re-materialize after lib changes.
- **Paths in the GET route map swallow POSTs to the same path** — split list routes (`/list`).
- **`percentile_cont(...) FILTER` attaches to the aggregate, not `round()`.**
- **Crontab lines installed via subshell keep losing the `cd $PROJ &&` prefix — verify every installed line.**
- Playwright: `domcontentloaded` not `networkidle` (constant polling); operator status digests need `send_telegram(..., bypass_router=True)` (router suppresses P2).
- Shared-file races: parallel sessions on `research_intelligence.py` — single-line edits last, own commit.
- GitHub visibility flips: push-guard lags gh API; verify with authenticated `gh` immediately before push. Repo public ~09:40–13:07 on 7/16 — treat history secrets as burned.
- Card v4 family is LOCKED — data-wiring only; new UI renders around it, never inside.

## 9. OPEN ITEMS + DATES

**Operator:** 1) **Key rotation OVERDUE** (repo public twice 7/16; gitleaks full-history; before open 7/17). 2) Schwab dated Cost Basis export ×4 → GG v1.1. 3) Hard-reload pre-calm-client tabs. 4) **~2026-07-30 combined evidence review** (GG promote decision + lint trend + feedback tallies + source-league) — the gate for v3.2 desk work. 5) Tier-3 directive merge in Telegram (#420, #612 → #244). 6) ~~CLOSE-WAIT topology~~ DONE (Engine Room WS-1 Path B, 2026-07-16).

**CC queue:** (Engine Room v1 DONE 2026-07-16.) Parked: keyboard nav, GG v1.1, Level II, ToS parser (awaiting real CSV), journal source-keys (unblocks full attribution chain), items payload tail.

**Strategic:** trading evidence base — strategy proof ~2/10 vs system maturity ~7.7; canary gate chain expired 06-22; live-money target 2026-11-15 ⇒ 60-day shadow must start ~2026-09-15.

## 10. KEY NUMBERS (2026-07-16 close)

Portfolio ~$1,268K / 41 holdings (37 non-cash, 4 accounts). SCHG 25.4% (high), Top-3 ~56%, heat ~8.8%. Desk ~147 items, snapshots 10–19ms/304s 1ms. Directives 288 active / 27 paused / 193 archived. Scoreboard: 13,093 events; ai_discovered α −4.82% (n=385). 7/16 morning: 4 defense stops fired (NOC/BAH/LDOS/CACI), 12 large positions unprotected ≈ $355K (GG priority cohort). Hermes backlog 2,510 (WS-4 target). Day: 5 sessions, 24+ commits, all pushed.
