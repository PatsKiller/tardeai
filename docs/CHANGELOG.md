# Changelog

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
SchwabJournal. Daily cron ingest->build->classify. Separate from paper_trades (gate stays paper-only).
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
