## 2026-08-11 — Autonomy WS0 + reactive wakes (SHADOW)

Fixed agent_runtime@* ModuleNotFoundError (provider env comment + AUTH=0 override).
steph/morgan/alex --once SUCCESS; alex processed 8 wake jobs after event inject.
Drive backups pruned to latest-only per family. Librarian orphan purge live.
cio_reactive_cycle timer every 2m; goals store + operator runbook.
Docs: docs/ops/AUTONOMY_RUNTIME_TRUTH_2026-08-11.md, AUTONOMY_OPERATOR_RUNBOOK.md.
READ_ONLY_ADVISORY only — not free-running traders.

## 2026-08-11 — Situation Catalog v1 Phase 2a (code SHADOW)

Implemented plan store (`cio_plans`), detector skeleton S1–S8, config
`cio_situations.yaml`, SpaceX fixture tests (12 passed). Hooks fail-soft on
heartbeat + reactive cycle. Default shadow/notify=false. Docs:
`docs/cio/SITUATION_CATALOG_V1.md`.

## 2026-08-11 — Situation Catalog v1 FREEZE (pre Phase 2)

Froze S1–S8 READ_ONLY situations + shared plan schema + SpaceX-class S1/S2
acceptance fixture. Doc: `docs/advisory/desk-v1/SITUATION_CATALOG_V1_FREEZE.md`.
Next: P0 timer-host deploy if needed, then Grok Build slice = catalog + plan
object + detector skeleton only (not full multi-phase stack).

## 2026-08-11 — Goal/thesis store + agent_runtime --once green (SHADOW)

Fixed `AGENT_RUNTIME_PROVIDER_MODULE` inline-comment import break; alex/morgan/steph
`--once` COMPLETED. Added `CIOGoalStore` (`data/cio/cio_goals.jsonl`) and
`CIOWakeDispatcher.enqueue_goal_wakes` (GOAL_DUE, 30m dedup). Not fully autonomous;
heartbeat remains safety net. Docs: `docs/advisory/desk-v1/RUNTIME_TRUTH_2026-08-11.md`,
`AUTONOMY_GOAL_THESIS_COMPLETE.md`. backup_enforcer local dumps=1 compliant.

## 2026-08-11 — Advisory Desk v1 Phases 0–7 closed (code); autonomy truth documented

Branch `feature/advisory-desk-v1`: governed bridge + Flash opinions + Pro synthesis,
lots/holdings evidence, memory/feedback/outcomes, `/v3/advisory` + Telegram, shadow
sessions, kb_lessons + notif broker SHADOW, 30-session promotion gate. **Promotion
status NOT_PROMOTED** (1/30 consecutive; useful-rate needs n≥5). Docs index:
`docs/advisory/desk-v1/`. **Autonomy truth:** scheduled factory with LLM brains on
timer-fired oneshots — not free-running agents, not autonomous traders; fleet
`agent_runtime@*` still SHADOW/failing queue module. See
`docs/advisory/desk-v1/AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md`.

## 2026-08-11 — Storage safeguards: backup storm containment + retention

Health-agent dump auto-remediate loop had left **38×~2.3G local dumps (86GB)**. Contained:
pruned to **1** local dump (~84GB freed); disabled auto-remediate for `db_dump_*` /
`backup_cadence_stale`; `config/backup_policy.yaml` + `backup_enforcer.py` (max_count=1,
20h interval); hourly `tradeai-backup-enforcer.timer`; Drive db `KEEP=1`. DB retention
extended for stream books/quotes + score_history; applied purge **~4.1M rows**. Docs
hygiene pruned 120 generated dryruns. Audit: `docs/audits/STORAGE_SAFEGUARDS_AUDIT_2026-08-11.md`.
Follow-ups: content_embeddings orphan purge (~7.7GB), FK-safe job retention, VACUUM FULL
embeddings, fresh Drive `db_backup` on next cadence.

## 2026-08-11 — Schwab reauth: stop auto-2FA, CC manual page + banner

Browser auto-reauth (`schwab_auto_reauth.py` Chromium + 2FA) was failing on Schwab
authenticator/OTP pages (timeouts, push not completing). **Stopped auto browser path:**
cron `--check` disabled; script default is notify-only (opt-in `--browser` only for
emergency). **Shipped Command Center Ops → Schwab Reauth** (`/v3/system/schwab-reauth`):
request authorize URL → operator logs in on phone → paste `127.0.0.1?code=…` → exchange.
APIs: `GET /api/v2/brokers/schwab/reauth-url`, `POST .../exchange-code`; token-health gains
`show_banner` / true-login clock; site-wide banner on CC shell. Live renew succeeded same
day (true expiry advanced ~7d; live_probe ok). Docs: `docs/SCHWAB_AUTO_REAUTH.md`,
RESTORE_GUIDE §2b. Deployed to portfolio-server CURRENT + CC v3 dist; Telegram paste remains
backup.

## 2026-07-21 — Alpaca multi-account taxonomy R1–R5 + Drive sync

Built and pushed registry/interlock unification, credential slots, label migration to
`tradeai_automated`, DISABLED live scaffolds, TV ingress 503 stub. Tip **`4fa3ba33`**.
Handoff: `docs/sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md`. Audit findings:
`docs/_findings/alpaca_taxonomy_audit_2026-07-21.md` (P0 host-lock remediations). Docs are
canonical **`.md`**; Drive mirror via `scripts/sync-docs-to-drive.sh` (raw markdown parity).
Holdings ~$1.26M / 36. No live Alpaca submit path; no public TV webhook.

## 2026-07-22 — Watch Decision Desk V5 build (branch) + Schwab auto-reauth E2E + .env symlink fix

V5: refresh-vs-rebuild split proven (CECO), canonical orchestrator + tiers + scheduler +
freshness contract + deterministic thesis engine, all E2E-tested from `wt-watch-v5`; NOT yet
merged/deployed. Schwab: 7-day token expiry root-caused (rotation never reset the clock —
fingerprint artifact); TRUE auto-reauth built and proven live in 74s (Xvfb-headed beats Akamai;
consent-modal Accept text-matched); weekly cron armed. P0 side-fix: post-SM-migration `.env`
deletion broke import-time readers in fresh processes — `.env` is now a symlink to the
Bitwarden tmpfs render (serving tree), un-breaking affected crons. Backup scope: Fernet key
into env family + Bitwarden/auto-reauth restore steps in RESTORE_GUIDE §2/§2b.

## 2026-07-15 — Transfer-aware YTD + Fidelity period fills + daily pin

Shipped transfer/rollover-resilient position provenance and performance continuity (Fidelity→Schwab, Trad→Roth, 401k→rollover rename). Postgres transfer history + normalize audit; auto-normalize on holdings write with basis carry-forward and stop-impact flags. Returns: residual YTD (ex-transfers), linked Fidelity economic sleeve restores 1W/1M/…, portfolio = Σ accounts, outlier snap path hygiene, **daily YTD pin** (`ytd_daily_pin.json`) so ≈ market does not wobble intraday (~+$54.2k household pin at ship). Force recompute: `YTD_PIN_FORCE=1` or delete pin file. Docs: `docs/features/transfer-aware-performance.md`. CC v3 Returns/Holdings surfaces notes + transfer history.

## 2026-07-14 — Dynamic stop policy shipped (9 commits) + full advisory re-tier

stop_policy.yaml tiers (vol_low/medium/high by beta/ATR%/yield/sector — zero hardcoded symbols,
pins emptied) + regime adjust (risk-on widens vol_high trail +1 only; risk-off tightens all −1) +
lifecycle/conviction modifiers + portfolio drawdown guard (2.4% current, ok). Daily 06:45 cron:
volatility_tier_refresh → symbol_volatility_tiers + migration-report state. Full advisor batch:
23/25 stoppable holdings re-tiered (12 low / 4 medium / 8 high); 4 gemma sanity WARNs flagged
in-evidence (NOC/BAH/LDOS/CACI); V routed via gpt-4o-mini fallback on the local lane once. CC v3:
VOL badges everywhere, three-line current-vs-advisory comparison (tooltip + on-screen drawer
panel), CURRENT LIVE BROKER STOP vs ADVISORY RECOMMENDATION labels, Apply Fixed/Trailing/
Stop-Limit (2FA) + Keep Current Stop (new audit-only /protective-stop/keep endpoint), editable
stop/limit/trail params (limit_price was never sent by the UI before), Policy sub-tab with ranked
band divergences (10 stops tighter than floor, SCHG largest — all individual 2FA actions, no bulk
control by design). Facts for tomorrow: NO Schwab lot currently holds a live stop — the SCHG and
ANET trailing stops are on Fidelity lots; SPCX unstoppable (no daily bars). Ops: found+killed
another orphaned portfolio_server holding :7777 (systemd crash-loop count 61k) — same failure
mode as the morning; systemd owns the port cleanly now. Playwright sweeps green (13/13 final);
31 policy tests; holdings guard held all session.

## 2026-07-14 — Full-site audit: 17 findings fixed (P0×6, P1×4, P2×7)

Chrome-MCP audit corrective across 6 workstreams. Highlights: broker-proposals endpoint 35-50s
(infinite spinner) → 8s bounded/1.3s warm — root cause is a FAILING SCHWAB OAUTH REFRESH (HTTP 400,
flagged for operator re-auth; quote fallbacks now cached+budgeted). PFLT $829.71/sh phantom basis =
stale cost_basis_anchor (pre-sale $9,746 total ÷ 11.7 residual shares) — anchor corrected to $111.66
(per-share $9.5054 unchanged, stop-fill 1007000082502 documented) + share-count sanity guard in the
consumer. Scanner/header, agent counts, journal stats: all "contradictions" were unlabeled scope
differences (latest-run vs universe; watchlist log vs agent home tables; stale CSV-FIFO journal vs
broker round-trips) — every surface now labels its basis; headers unchanged. RAG 212% = embeddings of
archived rows — honest promoted coverage 100%, >100% structurally impossible now. SPCX 0.00 was
UI-fabricated (?? 0) over honest nulls → "—". Morning brief gets a ticking staleness banner >2h. PM
memo oversight renders live from DB. Cross-tab plan income drift ($28) = reserve yield credited on
unmodeled sweep — fixed. Home race → skeletons. Bonus: journal export SQL-precedence bug bypassing
account/date filters — fixed. FLAG-BACKS for operator: (1) ~~Schwab OAuth re-auth needed~~ CORRECTED — operator confirms an
auto-auth setup exists and the token store shows a fresh seed 2026-07-14 10:15 (expiry 07-21);
the audit's "needs manual re-auth" claim was wrong. Schwab token machinery NOT touched per
operator instruction; the quote lane's fallback-provider slowness is now mitigated by caching
regardless. Residual observation only: schwab_position_sync logs 'degraded_noop (no Schwab login
token)' — left entirely alone. (2) CORRECTED (operator): ALL pipelines are
API-fed — NO CSV imports. The header FIFO journal is a legacy surface (labeled 'legacy FIFO
journal'); trade_closed (broker round-trips, API) is the authoritative, current journal. Verified
flow documented in session memory reference-schwab-api-dataflow.
(3) ~40k orphaned content_embeddings await a retention decision. 112 tests green; holdings guard held
throughout. Known non-issues honored (JEPQ legit, $21 rounding, look-through gap label).

## 2026-07-14 — FINAL ADJUDICATION: APPROVED FOR OPERATOR IMPLEMENTATION REVIEW

Operator's formal ruling recorded in audit lineage (implementation_review_approved, plan 1191 v31):
methodology/destination/staging/capital/accounting/lock APPROVED-VERIFIED; **broker execution
authorization NOT GRANTED** (manual only, as always). Terminology corrected per ruling: lane
dispositions now distinguish "pass by operator adjudication (run 23; lane verdict was needs_review)"
from a direct lane pass — in the reducer, packet and export. Implementation posture on record:
refresh export at ticket time; use current limits + do-not-chase; never convert unfilled limits to
market orders; record actual fills only; XLV stays deferred to stage 2.

## 2026-07-14 — Governance projection: artifact/state mismatch CLOSED (implementation unblocked)

Adjudication finding fixed: oversight runs now carry the full immutable key (plan_id/version/
input_hash/policy — migration 2026_07_22); canonical reducer selects newest valid verdict PER LANE
for exactly the locked snapshot (old Plan-B / unkeyed rows never participate). ChatGPT lane's keyed
needs_review asked the plan "remain at operator review" — operator's written adjudication recorded
as keyed run #23 (pass by operator_adjudication, full provenance + audit row); DB column reconciled
to the keyed aggregate. New `governance_projection()` cross-checks DB plan status / oversight
aggregate / event status / capital reservation / readiness — locked exports FAIL-CLOSED on any
mismatch (force_stale never bypasses it; verified live when XLC aged out). Packet + implementation
JSON regenerated through the projection: both now show F/1191/v31 · destination B · staged ·
ChatGPT PASS · Grok PASS · aggregate PASS · OPERATOR_LOCKED · reviewing · reserved_locked ·
implementation_review_approved TRUE · snapshot 5ae45d89… · quote snapshot 13:26 ET. 6 regression
gates added (test_redeploy_governance_projection.py). Stage-1 orders now suitable for manual entry.

## 2026-07-14 — Plan F v31 LOCKED + approved for operator implementation review

Operator-directed: locked Plan F v31 (staged implementation of the Plan B destination, plan #1191)
via /api/v2/deploy/lock — event #144 → `reviewing`, readiness **OPERATOR LOCKED**, capital ledger
`reserved_locked` ($107,023 reservation, no overclaim). Quotes refreshed (8/8 fresh); implementation
plan exported (docs/audits/FCNTX_144_IMPLEMENTATION_PLAN_F_v31.json — stage-1 ≈ $3.1k limit tranches
across QQQ/XLC/XLF/XLY/XLI/AGG with do-not-chase bounds; XLV stage-1 rounds to 0 sh, enters at
stage 2). Packet regenerated (v31-bound). Audit lineage: plan_locked + export rows. Implementation
itself remains MANUAL — this desk places no orders.

## 2026-07-14 — Stale-event dismissal: capital overclaim CLEARED

Operator-directed cleanup: dismissed 11 stale schwab_rollover_ira events (Apr–Jun sales — V #114/#124,
PFE, FATN, DFSC, PRSO, GOVX, RGNT, CAST, PETS×2 — $123k of claims, zero locks/fills; proceeds long
absorbed into account cash) via /api/v2/deploy/dismiss with audit rows. Ledger now: open claims
$127,825 vs visible cash $149,253 → **OVERCLAIMED: False**; event #144 `claim_within_capital`, red
banners gone (verified on-screen). Packet regenerated (still bound to plan v31). Plan F (staged-B)
remains OPERATOR-READY with cleared capital — ready for operator implementation review.

## 2026-07-14 — Oversight adjudication corrective + OPERATOR-READY reached

All 10 blocking findings closed (deploy-now double-count, 4-field capital semantics, capital
reservation ledger [rollover IRA OVERCLAIMED $53k — #144 awaiting_capital], real overlap flags,
income baselines, destination×cadence two-axis [F = staged Plan B], B tracking-error minimizer
[84.6% capped, $0 over], concentration caps [C diversified], version-bound packet
[FCNTX v31], XLC refresh, tie policy). Oversight RERUN on the bound v31 snapshot: **Plan F
(staged-B) PASSED both lanes → first legitimately OPERATOR-READY plan**; B-immediate stays
pending. Live readiness now recomputed from current oversight status at API read.
Packet: docs/audits/FCNTX_144_DECISION_PACKET_v31_2026-07-14.md.

## 2026-07-14 — Redeploy semantic-integrity release (operator 23-defect corrective)

All 23 review defects closed (map in docs/audits/). Plans reconcile to the cent with explicit
whole-share residual (re-cut after every quote refresh); readiness governed (oversight pending ≠
operator-ready — lanes ran live, Grok passed B/F, ChatGPT lane needs_review → honestly PENDING);
candidate-driven role selection with visible competition; honest archetype labels + gap-capped
tactical sizing; canonical income model; whole-plan vs invested-sleeve; STATISTICAL_BAND scenario
labels; audit lineage table backfilled (25 rows event #144); DECISION tab + persistent decision
header + structured PM memo (no JSON). Cross-tab consistency verified identical across all 7 plans.
97 tests green. Operator packet: docs/audits/FCNTX_144_DECISION_PACKET_2026-07-14.md. Evidence:
artifacts/playwright/redeploy/decision_20260714T152534Z/.

## 2026-07-14 — Redeploy Phase-13 acceptance COMPLETE

Closed every remaining spec gap: 10-scenario matrix (typed, coverage-honest), candidate universe 144
(+mutual funds, catalysts, geo sensitivity), PLAN LAB / PLAN COMPARISON split (12 tabs). Fixed the
4-layer quote-staleness chain that kept every plan NOT OPERATOR-READY (UTC-misparse +4h, snapshot-only
prices, all-versions staleness aggregate, event-wide gating) — FCNTX plans now **OPERATOR-READY** on
14m quotes. 25 new Phase-13 tests (51 green): no-broker-execution proof, fixture-free production,
arithmetic/honesty invariants. Visual matrix 22/22 (4 widths × 200% zoom, zero overflow). #146's
committed screenshots migrated out of Git per artifact policy. Evidence:
`artifacts/playwright/redeploy/acceptance_20260714T141004Z/` + `visual_matrix_20260714T141049Z/`.

## 2026-07-14 — Redeploy institutional rebuild MERGED + fixture cleanup EXECUTED + deployed

Operator approved: merged the full rebuild stack in order — #142 (P0 guards) → #148 (docs truth,
reopened #143 after GitHub auto-closed it on base deletion) → #144 (capital book) → #145 (analytics
engines) → #146 (/redeploy workstation) → #147 (Phase-0 cleanup + ephemeral artifact policy).
Executed the approved fixture cleanup (all 5 pre-counts matched; fills/snapshots/audit/ledger/oversight
rows deleted; event #144 unlocked → `open`, plan 8 reset, `phase_e` metadata stripped; outcome bus
already clean). Applied migrations `2026_07_19` + `2026_07_20`. Built cc-v3, **ended a 56,329-cycle
systemd crash-loop** (orphaned Jul-13 portfolio_server held :7777 outside systemd — killed; unit now
active/running). Installed deploy-redeploy cron (detect 10:10 / recompute 10:15 / monitor 10:20 ET).
Manual recompute: **A–G plans for all 8 material open events** (FCNTX, V×2, HPE, PFE, SMCI, ARKG, ARKQ).
26/26 redeploy tests green. Acceptance captures → `artifacts/playwright/redeploy/` (ephemeral policy).

## 2026-07-14 — Stop replace verified-cancel hardening + Redeploy visual review

Hardened the Schwab protective-stop **Modify** flow: cancel of the old stop is now broker-verified
(polled to terminal/gone) before the new stop is placed, gate moved inside `schwab_transport.place_order`
(web confirm + Telegram `bkapprove` share it), still-live replace target blocks (`replace_cancel_incomplete`),
idempotent repeat-DELETE, `REJECTED` read-back surfaced. Only `pilot_placed` orders replaceable in-app
(`open_trades_intelligence` stamps the flag from `schwab_pilot_orders`). UI submits floor-reconciled
advisory stops; stop badge follows stop-management truth (`KEEP_EXISTING_STOP` ≠ Action). New Hermes
`vehicle_auctions` research domain (advisory, operator-gated). Tests: `test_stop_replace_flow.py`,
`test_schd_advised_order_params.py`. Playwright captured all Redeploy Desk pages/sub-tabs →
`docs/redeploy_review_2026-07-14/`. Docs: `stop-management-architecture.md`, `CHANGELOG.md`. Drive sync post-commit.

## 2026-07-13 — Redeploy Desk P0 audit + reopening

Operator review rejected the shipped Redeploy Desk as a prototype shell (unreadable 780px
drawer, label-level plans, no pro-forma, contextless entries). P0 confirmed: the three
identical JEPQ stage-1 fills on event #144 were written by the Phase E test suite against
the production DB (evidence notes `phase_e test fixture`, keys `test-*`). Quarantine +
permanent record-fill guards shipped (PR wt/redeploy-institutional-p0); transactional
deletion staged for operator approval. Docs resynced to implementation truth — desk is
REOPENED, not complete. Rebuild plan: capital-allocation book → candidate/pro-forma/
performance engines → full-page /redeploy workstation + FCNTX #144 A–G acceptance.

## 2026-07-10 — Ross/Warrior TradeAI alignment + CC v3 scanner polish

Deployed Ross-catalog awareness lanes (squeeze, runner, micro-float, low-price, top gainer, catalyst
exception) with DB persist + Jul 6–10 backfill (6641 rows). Weekly warrior audit cron installed
(Mon 8:30 AM ET); pilot recall **52%** (25 sym-days). CC v3 Trade AI: default **Actionable** filter,
Manual tab consolidation, sort dropdown, LOW pill, Vol column, `CountryFlag` PNGs. Doc:
`docs/WARRIOR_ROSS_TRADEAI_ALIGNMENT.md`. Drive sync post-commit.

## 2026-07-07 — Options paper lifecycle monitor + docs sync

Deployed Alpaca paper position lifecycle monitor (registry, Schwab marks, UI/Telegram alerts, **Open Options**
tab). Cron installed via `scripts/install_options_paper_monitor_cron.sh` (fixed `bad hour` parse — job-lines-only
block + `crontab -T` validation). Migration `2026_07_07_options_monitored_positions.sql` pending until
`DATABASE_URL` set. Card semantics: paper rows **NO LIVE PATH** + **Review Paper Guards**; true blocks unchanged.
Docs: `OPTIONS_STRATEGY_PIPELINE.md`, `ARCHITECTURE.md`, `OPERATIONS.md`, `CHANGELOG.md`. Drive sync post-commit.

## 2026-06-27 — AI Trade Critique persistence + batch (UI 3.9)

Made AI Trade Critique a persistent, queryable journal asset: `journal_ai_critiques` index,
version history, tag-fingerprint staleness, search/insights APIs, trade-log chips, report
readiness gate. Batch-generated **87 critiques** for 6M range (56 new). Doc:
`docs/AI_TRADE_CRITIQUE.md`. Commits `65a48983`–`96be9bce`.

## 2026-06-27 — Universal replay backfill (all past + future trades)

`replay_backfill.py` pipeline deployed: `build_trade_execution_quality` → `replay_chart_audit`.
`buildReplayTrade()` unified all replay entry points. Fill-time resolution: EQ → srt dedupe → schwab
match → symbol/date. Chained after Schwab journal ingest (health agent); cron installer:
`scripts/install_replay_backfill_cron.sh`. Full backfill: **66 ok / 24 warn / 0 fail** (90 trades).
Drive sync + commit `35986713`.

## 2026-06-27 — Replay marker fix (GOVX) + AI Trade Critique (UI 3.5)

Final replay alignment: fill times from `trade_execution_quality` when queue passes dates only;
price-aware marker snap. Re-audit: **65 ok / 25 warn / 0 fail** (marker warns −3). Added **AI Trade
Critique** (`journal_ai_critique.py`, `/api/v2/journal/ai-critique`, TradeInView Overview tab).

## 2026-06-27 — Replay price-scale fix + 90-trade integrity audit

Fixed systemic replay Y-axis misalignment (volume polluted candle price scale). UI **3.4**:
`replayChartScale.ts`, isolated volume overlay, per-step scale sync, Re-sync scale button.
Ran `scripts/replay_chart_audit.py` across all 90 deduped closed trades — backfilled
`journal_trade_reviews.payload.replay_chart`; **62 ok / 28 warn / 0 fail** (warns = Finviz fallback or
marker outside split-adjusted bar range). Audit: `docs/audits/REPLAY_INTEGRITY_2026-06-27.md`.

## 2026-06-22 — Fidelity monitored stops approved + server restart

Operator approved Fidelity monitor-only stops: `snaptrade_pilot_arm.py --approve --confirm
"APPROVE FIDELITY STOPS 2026-06-22"` → `fidelity_stops_enabled=true`, `armed_for_ui=true`. Schwab pilot
still armed (all 3 accounts, standing unlock, per-order 2FA). Restarted portfolio server (`restart_server.sh`,
port 7777); API checks OK.

## 2026-06-22 — Schwab canary: all 3 accounts, standing unlock (2FA retained)

Pilot allowlist expanded to `schwab_taxable` + both IRAs; `schwab_pilot_standing_unlock` (no session
expiry, armed_until 2099); `CANARY_SESSION_DATE=2099-12-31`; cap 9999. Per-order 2FA unchanged.

## 2026-07-21 — Alpaca paper due diligence + trading-env taxonomy (docs + Drive)

Full audit of Alpaca/paper usage; freeze taxonomy `paper` | `paca_personal` | `paca_ira` before any
live Alpaca keys. Docs: `docs/brokers/ALPACA_DUE_DILIGENCE_AUDIT_2026-07-21.md`,
`trading-environments.md`, `paper-trading.md`, `paca-accounts.md`. No code path to live Alpaca opened.
Synced to Drive with index/changelog.

## 2026-07-21 — Operator decision card + RTH plan refresh (docs + Drive)

Shipped compact watchlist **operator card** (one state/CTA, timestamps) and fixed
**should_be_stale**: RTH **4h** TTL on action policy + packet invalidation + shadow batch so
star/buy/strong-buy plans re-arm every few trading hours. Canonical doc:
`docs/architecture/DECISION_PACKET_OPERATOR_CARD_AND_RTH_REFRESH.md`. Commit `b2fbcd90`.
Docs index + changelog + watchlist hub updated; synced to Drive via `scripts/sync-docs-to-drive.sh`.

## 2026-06-22 — SnapTrade / Fidelity stops + one-share test (docs sync)

**Fidelity (`fidelity_rollover_ira`):** SnapTrade read-only — monitor-only stops (`fidelity_monitored_stop`),
no broker execution, **no 2FA** on arm/breach (alert + Active Trader ticket). Standing unlock:
`snaptrade_pilot_arm.py --approve`. **Schwab:** live stops unchanged (2FA per order). **One-share test**
(no sandbox): `snaptrade_trade_pilot` + `--arm-test` + `POST /api/v2/snaptrade/trade/preflight|execute`
(when trade-capable broker + `ENABLED=True` commit). Specs: `docs/brokers/snaptrade-fidelity-protective-stops-spec.md`,
`stop-management-architecture.md`. Commits: `e205f53d`, `1494257e`, `7f91fadd`.

## 2026-06-22 — Intelligence engine + Command Center hub (all tabs A-grade)

Hermes→RAG closed loop: `hermes_embedding_enqueue.py` on promote, 2246-row backfill,
`hermes_research` in rag_indexer + library APIs, iris library-status deadlock fixed.
Command Center v3 Intelligence hub rebuilt: News/Research/Sources/Rotation tabs, URL sync,
Hermes/RAG KPIs. `CAP_EMBED` 2→10. Doc: `docs/intelligence_maturity_20260622.md`.

## 2026-06-22 — Docs consolidation (A1A) + full commit

Canonical docs aligned to live system: `LIVE_SYSTEM_FACTS.md`, MASTER/EXECUTIVE/CHEAT_SHEET/COST_MODEL
use live-fact pointers; drift detector hardened. Committed 32 pending files (strategy YAML performance
context, runtime JSON, finviz throttle + scripts). Closeout: `docs/project/DOCS_CONSOLIDATION_2026_06_22.md`.

## 2026-06-22 — Stabilization session + maturity audit (Grok CLI)

Full triage of health-agent findings (score 64): agent queue backlog (36 jobs >2h, drain batch started),
screener duplicate-key spam (fixed `53636262`, 10:00 errors pre-fix), overnight LLM queue root cause
(PHASE102-RETIRED cron — 1,941 pending), SIEM alerts acked (fused_signals + DB SSL transient), KTOS/KBR
stop-outs flagged for operator review. Maturity audit ≈7.1/10. Docs:
`docs/project/STABILIZATION_SESSION_2026_06_22.md`, `docs/project/MATURITY_AUDIT_2026_06_22.md`.

## 2026-06-19 — Defense/BDC rotate-gap directives seeded (audit Task 5)

Seeded 8 `rotate_gap` watch directives for held Schwab-taxable defense/BDC positions flagged in the
Aegis brief: LHX, LMT, NOC, BAH, LDOS, KBR, CACI (defense_thesis sleeve) + PFLT (high_yield_bdc).
Mapped onto the REAL `watch_directives` schema (kind='ticker', label=symbol, spec={symbol,gap_type:
rotate_gap,sleeve,flagged}, created_by='operator_audit', status='active', priority='high'). The
rotation/promotion engine consumes active operator directives on its scheduled cycle to surface
sleeve replacements. Advisory only — no position change, no order writes. Note: these were Aegis-brief
flags, not recorded broker-stop triggers (stop_lifecycle had no rows; risk_stops table does not exist).
