# Schwab API — Phase 1 Read-Only Foundation (canonical)

Status:      HISTORICAL
as_of:       2026-06-11T22:24:42-04:00
Measured at: efcc51365 / not measured

## CURRENT STATE (2026-06-10) — single source of truth

| Capability | State |
|---|---|
| Safety guards (Gate A/B, write-fence, wipe-guard) | ✅ **PROVEN** — by failure-injection (empty/401/timeout/near-expiry fed deliberately; that is how fail-closed is proven) |
| Read-only transport (`schwab-py` 1.5.1, boundary-only) | ✅ **BUILT** |
| Live reads (account / positions / orders / transactions / quotes) | ✅ **LIVE + PROVEN** — Developer Portal app approved, credential-in pass complete |
| Writes (orders, place/cancel/replace) | ⛔ **NOT_PROVEN / FENCED** — `NotProvenWrite`, `api_write_enabled=false`, accounts `MANUAL_REVIEW`, validator 12/12 |
| Gate A — 7-day refresh roll-forward | 🔭 **UNDER OBSERVATION** — assumes worst case until a full weekly window is observed live |
| Rate-limit real numbers · CSV-import retirement · `basis_unknown` resolution · Level II / streaming · Stage 2 writes | ⏳ **DEFERRED** (see Deferred section) |

There is **no contradiction between sections below**: reads are live and proven; writes remain fenced; the
"simulated" proofs refer to *deliberately injected failures* used to prove the guards fail closed — not to
the live connection, which is separately proven. Earlier revisions of this doc carried "no live connection /
live reads NOT_PROVEN" language from the fixture build phase; that language has been removed from all active
sections (reads are live).

## The two non-negotiable gates

### GATE A — 7-day manual re-auth assumed (no infinite refresh)
`scripts/schwab_token_manager.py`. Schwab refresh tokens last ~7 days from creation and (per Schwab) cannot
be renewed programmatically. Therefore:
- Refresh-token expiry is **first-class state** (`refresh_expires_at`, `next_reauth_due_at`), not an exception.
- **No background-infinite-refresh** assumption anywhere.
- Tokens stored **Fernet-encrypted** in `broker_oauth_tokens`; the key lives ONLY in
  `config/broker_credentials.env` (0600, gitignored) — **never** in the DB, Drive, logs, or UI.
- `health(account_key)` **fails closed** (degraded) on any doubt (no token, past expiry, undecryptable).
- **Day-5/day-6 alerts** to Telegram (both chat IDs), idempotent per day.
- **One-command re-auth** (`reauth-url`) + atomic `seed_token(...rotated=True)` persistence.
- **Shared token-bucket rate limiter** (`tm.RATE`, one module-global bucket).
- ✅ **LIVE:** the OAuth bootstrap (manual-paste `exchange_code`) and refresh-through-the-manager are proven
  against the approved portal app (credential-in pass).
- 🔭 **Under observation:** the real 7-day refresh roll-forward behaviour — observed over a full weekly
  window before the worst-case assumption is relaxed.

**Proven (failure-injection):** seeded a near-expiry token → day-5/6 alert fired; seeded an expired token →
`health` degraded, `get_access_token` returned `None` (fail closed), no crash.

### GATE B — holdings.json never wiped / basis never silently overwritten
`scripts/schwab_position_sync.py` → `protected_holdings_write()` (universal protected writer):
- **Pre-write sanity:** non-zero positions + total ≥ \$1M, else **NO-OP**.
- **Empty / partial / 401 / timeout / parse-error ⇒ NO-OP** — never overwrites a good snapshot.
- **Backup → atomic write (temp + os.replace) → post-write canonical assert** (`total_value>1M` &
  `position_count>0`) → **restore backup on failure**.
- **Tax-grade basis:** Schwab average price is compared/flagged (`schwab_basis_divergence`) but **never
  silently overwrites** manually-repaired cost basis (material to MFS filing + Roth math).
- Every outcome recorded in `schwab_sync_history`.
- ✅ **LIVE:** the Schwab fetch + Alpaca-preserving merge is proven against live reads (credential-in pass).

**Proven (failure-injection):** bad payloads (`{}`/`None`/zero-pos/low-total) → NO-OP, `holdings.json` byte-
unchanged; a fabricated good payload → post-assert passed; a fabricated divergent average price → flagged,
stored basis preserved.

## Mandatory holdings wipe-guard (behavior change — now in force)
`protected_holdings_write()` is **no longer opt-in**. **Every** code path that writes the holdings/current-
state file routes through it (neutral import home `scripts/holdings_guard.py`). The guard also rejects a
**catastrophic drop** (new total < 50% of last-good) and **alerts** (Telegram both chat IDs) on every
block/restore. A/B split: the **wipe-guard** is mandatory for all; **basis-preservation** is opt-in
(`protect_basis=True`, Schwab sync only) so legitimate basis edits (`patch_holdings_cost_basis`) aren't reverted.

| # | Writer | now |
|---|---|---|
| 1 | `db_adapter.save_holdings` | → guard |
| 2 | `portfolio_loader.save_state` | → guard |
| 3 | `portfolio_server.write_holdings` (×3 callers) | → guard |
| 4 | `holdings_reconcile.py` | → guard |
| 5 | `phase2_sector_resolver.py` | → guard |
| 6 | `phase3_lookthrough_resolver.py` | → guard |
| 7 | `patch_holdings_cost_basis.py` | → guard (`protect_basis=True`) |

**Closes:** programmatic wipes — empty/zeroed/failed/catastrophically-low writes from any script can no
longer overwrite a good `holdings.json`.
**Does NOT close:** the **deploy/zip-extraction vector** (a deploy zip / cleanup / rsync zeroing state files
bypasses Python entirely). Closed separately by the **pre-deploy state-guard** — see
[`PRE_DEPLOY_STATE_GUARD.md`](PRE_DEPLOY_STATE_GUARD.md).

**Proven:** empty payload → `rejected_sanity`, untouched; catastrophic drop (2.5M→1.1M) → `rejected_drop`;
forced post-write failure → prior snapshot restored byte-identical; normal full write → OK
(`total $1.24M / 48 positions`); zero screener/classifier/GO-WAIT/ATM/agent files touched.

## Write lockdown + regression guard
- `scripts/schwab_adapter.py`: `submit_entry`, `cancel_order`, `_api_post` return **`NOT_PROVEN`** (real
  finding: `cancel_order` previously made a live `requests.delete`). Read methods remain for the read path.
- `scripts/validate_schwab_no_writes.py`: **12/12 guards green** — no write path, all write methods
  NOT_PROVEN, position-sync through the protected writer, all 3 Schwab accounts `api_write_enabled=false`,
  `live_trading_interlock` refuses them, **Level II / volume-sweep / Schwab data isolated** from screeners
  (`prime_setups`/`watchlist_setups`), match-minimums, GO/WAIT, and ATM routing (Rule 9), plus the 5
  Stage-1 wrapper-surface guards.

## Stage 1 — read-only transport via `schwab-py` (built)
Adopted **`schwab-py` 1.5.1 (MIT)** as the read-only request/response transport beneath the token manager.
- **`scripts/schwab_transport.py`** — the only place `schwab-py` is imported (boundary-only). `build_client()`
  wires `token_read_func`/`token_write_func` to the manager's `read_oauth_token`/`write_oauth_token`, so a
  refresh persists THROUGH the manager (encrypted, rotation-counted). Without portal creds `build_client()`
  returns NOT_PROVEN (fail closed) — with creds it returns a live client.
- **Pure normalizers** (`normalize_account/positions/orders/transactions/quote`) — reconciled against live
  payloads; match the original fixtures unchanged. Watchlists **NOT_AVAILABLE** via the Trader API (confirmed
  live 404 — ToS-export fallback built; see [`SCHWAB_API_CAPABILITY_MAP.md`](SCHWAB_API_CAPABILITY_MAP.md) §4).
- **WRITE FENCE:** `place_order`/`cancel_order`/`replace_order` **raise `NotProvenWrite`**; the wrapper's
  write methods are never called or exposed; the shared token-bucket rate limiter sits in the transport.
- **5 validator guards:** fence-raises-static, no-wrapper-write-calls, schwab-py-imported-only-at-boundary,
  runtime-fence, Rule-9 transport isolation.

## Stage 1 LIVE — credential-in proof pass COMPLETE (reads live, writes locked)
Developer Portal app approved; creds entered via the Command Center secrets modal. **Reads live + proven;
writes NOT_PROVEN/fenced** (validator 12/12, `api_write_enabled=false`, MANUAL_REVIEW).
- **OAuth bootstrap** — manual-paste (`reauth_url` → browser login → `exchange_code(redirect_url)`) seeds the
  first token THROUGH the manager (Fernet-encrypted, atomic). 127.0.0.1 callback behind Tailscale, no
  listening server. schwab-py token shape = TokenMetadata `{creation_timestamp, token}`.
- **One login covers all accounts** — `canonical_token_key`; the account HASH distinguishes accounts.
- **Account-hash resolver** — `resolve_account_hashes(account_key, expected_last4)`, refuses ambiguity,
  stores the encrypted hash in `schwab_account_links`. 3 accounts linked: taxable ..9469 / **roth ..9415 /
  rollover ..0258** (CORRECTED 2026-06-12 — the original mapping had roth/rollover SWAPPED; Schwab's own
  2026-04-21 CSV proves ..415 = Roth Contributory IRA. Links swapped, 177 API-sourced ledger rows
  relabeled incl. dedupe_key, V IPO-basis override re-keyed, journal rebuilt; backup
  `_backup_acct_swap_20260612`. Lesson: last-4 mapping is operator-supplied — verify against a Schwab
  account-named export before trusting per-account attribution).
- **Live reads** — account/positions/orders/transactions/quotes.
- **Transaction ledger reconciliation** — `schwab_transaction_ingest.py`: API authoritative; replaces lossy
  CSV in-window (older pre-window CSV kept), granular per-order fills (slippage preserved), dividends/interest/
  real transfers, internal sweeps filtered. Backup before apply.
- **Authoritative cost basis** — `schwab_cost_basis_lots` + `ingest_schwab_gainloss.py` ingest the operator's
  Schwab Positions / Realized Gain-Loss exports (Trader API gives average price only, no tax lots). Basis
  hierarchy: **Schwab export → operator-documented (capped by `documented_qty`) → `basis_unknown`** (never an
  extended hand override). 24 held lots ingested.
- **Pre-window basis correction** — opening lots predating the API window (2025-07-19) no longer fabricate
  losses: FIFO seeds from the operator basis (`config/journal_basis_overrides.yaml`) capped at the documented
  quantity; sells beyond it → `basis_unknown`; pre-window lots = `long_term_trim` (realized, excluded from
  active stats). **V reconciled to Schwab authoritative basis:** the held 130 V sh carry $307.32/sh basis
  (NOT $10.75), so the $10.75 IPO lot is capped at the documented 400 sh — **V realized +$168,160 →
  +$117,356**; the 169 excess sh → `basis_unknown` pending the Realized Gain/Loss export.
- **Journal round-trips** — `schwab_journal_builder.py`: 5-minute fill aggregation + FIFO → `schwab_round_trips`,
  the **single Schwab source of truth** (refreshes `trade_closed` for the Trades tab + backs the
  `paired_trade_transactions` view for the backtester). Current aggregates: **active 116 trips +$37,046
  (52.6% win)**, long-term trims 5 = **+$114,938**, `basis_unknown` 13 (pending export). Separate from
  `paper_trades` — the live-trading gate stays paper-only.
- **LLM classification + review** — `schwab_journal_classifier.py`: strategy tag + entry/exit grade + lesson
  per round-trip (free OAuth/local LLM, idempotent; basis_unknown skipped).
- **Surfaces** — System→Brokers `SchwabMonitor` (Gate-A health, links, capabilities, sync) + CSV upload tile;
  Journal→Real Accounts `SchwabJournal`. Daily cron: ingest → build → classify.

## Deferred (sequenced, not built this phase)
- 🔭 **Gate-A real 7-day roll-forward** — observe over a full weekly window.
- ⏳ **Real rate-limit numbers** + split market-data/trading buckets (shared conservative bucket today).
- ⏳ **CSV-import retirement** — gated behind a 10-day clean dual-run.
- ⏳ **`basis_unknown` resolution** — 13 symbols (incl V 169 sh) pending the Schwab Realized Gain/Loss export.
- ⏳ **Level II / streaming** — out of scope by policy (Rule-9 isolation even if added later).
- ⛔ **Stage 2 writes** — any trading write, order endpoints, `broker_confirm_schwab.py` (deliberately absent).
  Hard preconditions: interlock + governance flag flipped, per-capability guard retirement, operator sign-off.

## Schema (additive)
`migrations/2026-06-09_schwab_oauth_foundation.sql` + `2026-06-10_schwab_cost_basis.sql`:
`broker_oauth_tokens` (encrypted), `broker_oauth_token_audit` (append-only fingerprints), `schwab_account_links`,
`schwab_api_raw_snapshots`, `schwab_basis_divergence`, `schwab_sync_history`, `schwab_round_trips`,
`schwab_cost_basis_lots`. Existing `broker_accounts`/`account_automation_policies` reused — no competing registry.

## Architect open-items (NOT for Claude Code to guess)
Schwab Portal: refresh roll-forward behaviour, rate-limit numbers, cost-basis/tax-lot field availability.
OAuth topology (1 app vs 3 = 1 vs 3 weekly logins). Until the portal proves the 7-day window rolls forward,
Gate A assumes the worst case.

## A1A
Additive only; no behaviour change to paper trading, screeners, GO/WAIT, ATM routing, or the live-trading
interlock. The protected holdings writer is **mandatory** (wipe-guard) with opt-in basis-preservation.
Secrets: Fernet key 0600 + gitignored, never in DB/Drive/git/logs. Docs synced to Drive on each change.
