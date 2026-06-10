# Changelog

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
