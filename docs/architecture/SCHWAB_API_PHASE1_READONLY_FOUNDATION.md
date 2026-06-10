# Schwab API — Phase 1 Read-Only Foundation (canonical)

> **Correction to commit `23f17865`.** That commit's title says "(PROVEN)" — read it as
> **"guards proven by SIMULATION; live Schwab integration NOT_PROVEN."** There is **no live Schwab
> connection** in this phase. The `validate_schwab_no_writes.py` "7/7 green" is a *no-writes / isolation*
> guard, not a connectivity claim. This doc is the authoritative framing.


**Status (2026-06-09): UPDATED — Schwab READS are now LIVE and proven** (Developer Portal app approved,
credential-in pass complete — see **"Stage 1 LIVE"** below). The early sections that say "no live connection
/ NOT_PROVEN" describe the *fixture build phase* and are superseded for READS only. **WRITES remain
NOT_PROVEN and fenced** — no live trading authorization; Schwab accounts stay MANUAL_REVIEW /
`api_write_enabled=false`; `validate_schwab_no_writes.py` 12/12.

> **Scope clarification.** Phase 1 proves safety guards under simulated Schwab failures. It does not prove
> live Schwab connectivity. Live OAuth, real reads, account-hash mapping, true rate limits, token
> roll-forward behavior, and Schwab API payloads remain NOT_PROVEN pending Developer Portal credentials.

> **What "green" means here.** The proofs validate that the *safety machinery fails closed and protects
> holdings when fed simulated Schwab failure* — they do **not** assert a live connection. Per the spec,
> proof artifacts simulate empty/401/timeout responses and near-expiry tokens (you can't get a real
> Schwab 401 without an account; you prove fail-closed by injecting the failure). Every path that needs
> the real Schwab API returns **`NOT_PROVEN`** in code.

## The two non-negotiable gates

### GATE A — 7-day manual re-auth assumed (no infinite refresh)
`scripts/schwab_token_manager.py`. Schwab refresh tokens last ~7 days from creation and (per Schwab)
cannot be renewed programmatically. Therefore:
- Refresh-token expiry is **first-class state** (`refresh_expires_at`, `next_reauth_due_at`), not an exception.
- **No background-infinite-refresh** assumption anywhere.
- Tokens stored **Fernet-encrypted** in `broker_oauth_tokens`; the key lives ONLY in
  `config/broker_credentials.env` (0600, gitignored) — **never** in the DB, Drive, logs, or UI. DB/audit
  hold ciphertext + fingerprints only.
- `health(account_key)` **fails closed** (degraded) on any doubt (no token, past expiry, undecryptable).
- **Day-5/day-6 alerts** to Telegram (both chat IDs), idempotent per day.
- **One-command re-auth** scaffold (`reauth-url`) + atomic `seed_token(...rotated=True)` persistence.
- **Shared token-bucket rate limiter** (`tm.RATE`, one module-global bucket across all accounts/endpoints).
- **NOT_PROVEN:** the live token exchange/refresh HTTP calls — need Schwab portal app creds
  (`SCHWAB_APP_KEY/SECRET/CALLBACK`), an architect open-item.

**Proven (simulated):** seeded a fake near-expiry token → day-5/6 alert fired; seeded an expired token →
`health` degraded, `get_access_token` returned `None` (fail closed), no crash.

### GATE B — holdings.json never wiped / basis never silently overwritten
`scripts/schwab_position_sync.py` → `protected_holdings_write()` (universal protected writer):
- **Pre-write sanity:** non-zero positions + total ≥ \$1M, else **NO-OP**.
- **Empty / partial / 401 / timeout / parse-error ⇒ NO-OP** — never overwrites a good snapshot.
- **Backup → atomic write (temp + os.replace) → post-write canonical assert** (`total_value>1M` &
  `position_count>0`) → **restore backup on failure**.
- **Tax-grade basis:** Schwab average price is compared/flagged (`schwab_basis_divergence`) but **never
  silently overwrites** manually-repaired cost basis (material to MFS filing + Roth math).
- Every outcome recorded in `schwab_sync_history` (ok | degraded_noop | rejected_sanity | rejected_postwrite).
- **NOT_PROVEN:** the live Schwab fetch + Alpaca-preserving merge — needs portal creds + read entitlement.

**Proven (simulated):** bad payloads (`{}`/`None`/zero-pos/low-total) → NO-OP, `holdings.json` byte-
unchanged; a fabricated good payload (temp file) → post-assert passed; a fabricated divergent average
price → flagged, stored basis preserved.

## Mandatory holdings wipe-guard (2026-06-09 — behavior change)
`protected_holdings_write()` is no longer opt-in. **Every** code path that writes the holdings/current-
state file now routes through it (the implementation is reused as-is; neutral import home
`scripts/holdings_guard.py`). The guard now also rejects a **catastrophic drop** (new total < 50% of the
last-good snapshot) and **alerts** (Telegram both chat IDs) on every block/restore. The A/B split: the
**wipe-guard** is mandatory for all; **basis-preservation** is opt-in (`protect_basis=True`, Schwab sync
only) so legitimate basis edits (e.g. `patch_holdings_cost_basis`) are not reverted.

| # | Writer (before: unprotected) | after |
|---|---|---|
| 1 | `db_adapter.save_holdings` | → guard |
| 2 | `portfolio_loader.save_state` | → guard |
| 3 | `portfolio_server.write_holdings` (×3 callers) | → guard |
| 4 | `holdings_reconcile.py` | → guard |
| 5 | `phase2_sector_resolver.py` | → guard |
| 6 | `phase3_lookthrough_resolver.py` | → guard |
| 7 | `patch_holdings_cost_basis.py` | → guard (`protect_basis=False`) |

**Closes:** programmatic wipes — empty/zeroed/failed/catastrophically-low writes from any script can no
longer overwrite a good `holdings.json`; the prior snapshot is kept + a loud alert fires.
**Does NOT close:** the **deploy/zip-extraction vector** (a deploy zip or cleanup step zeroing state files
bypasses Python entirely) — that needs a separate **pre-deploy state-guard** and is a **tracked
follow-up**, intentionally out of scope here.

**Proven:** empty payload via the real-path guard → `rejected_sanity`, file untouched; catastrophic drop
(2.5M→1.1M) → `rejected_drop`; forced post-write failure → prior snapshot restored byte-identical; a
normal full write → OK, `total $1.24M / 48 positions`, `assert v>1M` passes (no false positive); live
`holdings.json` byte-unchanged throughout; changeset touches zero screener/classifier/GO-WAIT/ATM/agent
files. Rollback = revert the routing commit (writers fall back to their prior direct write).

## Write lockdown + regression guard
- `scripts/schwab_adapter.py`: `submit_entry`, `cancel_order`, `_api_post` now return **`NOT_PROVEN`**
  (real finding: `cancel_order` previously made a live `requests.delete`). Read methods (`get_account`,
  `get_positions`, `get_open_orders`, `get_status`) remain for the read-only refactor.
- `scripts/validate_schwab_no_writes.py`: **12/12 guards green** — no write path, all write methods
  NOT_PROVEN, position-sync routes through the protected writer, all 3 Schwab accounts
  `api_write_enabled=false`, `live_trading_interlock` refuses them (live + master flag off), **Level
  II / volume-sweep / Schwab data isolated** from the screeners (`prime_setups`/`watchlist_setups`),
  match-minimums, GO/WAIT, and ATM routing (Rule 9), plus the 5 Stage-1 wrapper-surface guards below.

## Stage 1 — read-only transport via `schwab-py` (2026-06-09; reads now LIVE — see "Stage 1 LIVE" below)
Adopted **`schwab-py` 1.5.1 (MIT)** as the read-only request/response transport beneath the token manager.
Step 0 cleared both flag-back conditions before any build: auth decouples via
`client_from_access_functions(token_read_func, token_write_func)`, and the wrapper's writes are fenceable at
the boundary.
- **`scripts/schwab_transport.py`** — the only place the `schwab-py` library is imported (boundary-only).
  `build_client()` wires `token_read_func`/`token_write_func` to the manager's **`read_oauth_token` /
  `write_oauth_token`**, so a refresh persists THROUGH the manager (encrypted, rotation-counted) — the
  wrapper never owns token storage. Without portal creds `build_client()` returns **NOT_PROVEN** (fail closed).
- **Pure normalizers** (`normalize_account/positions/orders/transactions/quote`) parse recorded fixtures
  (`tests/fixtures/schwab/*.json`) into the existing `schwab_adapter` shapes. `# TODO(cred-in)`: reconcile
  real payload schemas when credentials land. Watchlists are **NOT_AVAILABLE** in 1.5.1 (not fabricated).
- **WRITE FENCE** (the point): `place_order`/`cancel_order`/`replace_order` **raise `NotProvenWrite`**; the
  wrapper client's write methods are never called or exposed; a shared token-bucket rate limiter (manager's
  one `RATE`) sits in the transport.
- **5 new validator guards**: fence-raises-static, no-wrapper-write-calls, schwab-py-imported-only-at-
  boundary, runtime-fence (3/3 raise + `build_client` NOT_PROVEN), and Rule-9 transport isolation.
- **Proven now (fixtures):** normalizers, token refresh-hook (rotation through the manager), write-fence,
  fail-closed client.

## Stage 1 LIVE — credential-in proof pass COMPLETE (2026-06-09; reads live, writes still locked)
Developer Portal app approved; creds entered via the Command Center secrets modal. Reads are now **live and
proven**; **writes stay NOT_PROVEN/fenced** (validator 12/12, `api_write_enabled=false`, MANUAL_REVIEW).
- **OAuth bootstrap** — manual-paste flow (`reauth_url` → browser login → `exchange_code(redirect_url)`)
  seeds the first token THROUGH the manager (Fernet-encrypted, atomic, no wrapper file). 127.0.0.1 callback
  behind Tailscale, no listening server. schwab-py token shape = TokenMetadata `{creation_timestamp, token}`.
- **One login covers all accounts** — `canonical_token_key`; the account HASH distinguishes accounts.
- **Account-hash resolver** — `resolve_account_hashes(account_key, expected_last4)` matches by last-4,
  REFUSES ambiguity (never blind-selects), stores the encrypted hash in `schwab_account_links`. 3 accounts
  linked (taxable ..9469 / roth ..0258 / rollover ..9415).
- **Live reads** — account/positions/orders/transactions/quotes; normalizers match the fixtures unchanged.
  Interlock gotcha: pass `account_mode` a positional-cursor conn (`r[0]`), not a dict-cursor conn.
- **Transaction ledger reconciliation** — `schwab_transaction_ingest.py`: API is authoritative; replaces the
  lossy CSV rows in-window (older pre-window CSV kept), granular per-order TRADE rows (slippage fills
  preserved, not collapsed), dividends with qualified/ordinary subtype, interest, real transfers; internal
  bank-sweep + margin type-journals filtered. 508 CSV → 416 API rows; `$10,553` dividend income. Backup
  before apply. `trade_transactions.trade_time` added.
- **Pre-window basis correction** — opening lots predating the API window (2025-07-19) no longer fabricate swing/day losses: FIFO seeds from operator basis (config/journal_basis_overrides.yaml, e.g. V ~$10.75 IPO) + old CSV buys; no-lot sells flagged `basis_unknown` (never a fabricated loss); pre-window lots = `long_term_trim` (realized but excluded from active stats). V: -$24K phantom -> +$168K long-term gain; active trading +$37K/52.6%.
- **Journal round-trips** — `schwab_journal_builder.py`: 5-minute same-side fill aggregation + FIFO pairing
  → `schwab_round_trips` (131 trips, 48.9% win, **+$17,410.96** net; RGNT scalp +$59.91/1min). Separate from
  `paper_trades` — the live-trading gate stays paper-only.
- **LLM classification + review** — `schwab_journal_classifier.py`: strategy tag + entry/exit letter grade +
  lesson per round-trip (local LLM, idempotent).
- **Surfaces** — System→Brokers `SchwabMonitor` (Gate-A token health, links, capabilities, sync);
  Journal→Real Accounts `SchwabJournal` (round-trips + grades/lessons). Daily cron: ingest → build → classify.
- **Still NOT_PROVEN / deferred:** Gate-A real 7-day roll-forward behaviour (observe over the week), real
  rate-limit numbers, CSV-import retirement (10-day dual-run), watchlists (absent in schwab-py 1.5.1).
- **Architect/Stage-2 (still locked):** any trading write, order endpoints, `broker_confirm_schwab.py`.

## Schema (additive — `migrations/2026-06-09_schwab_oauth_foundation.sql`)
`broker_oauth_tokens` (encrypted, no plaintext), `broker_oauth_token_audit` (append-only, fingerprints
only), `schwab_account_links`, `schwab_api_raw_snapshots`, `schwab_basis_divergence`, `schwab_sync_history`.
Existing `broker_accounts`/`account_automation_policies`/`broker_capability_checks` reused — **no competing
registry**.

## NOT built this phase (sequenced / out of scope)
Live OAuth exchange, account-hash live mapping, the `/api/v2/admin/broker-account/schwab/*` endpoints,
`broker_capability_checks` population (stays NOT_PROVEN), `broker_confirm_schwab.py` (deliberately absent),
Level II / streaming, CSV-import retirement (gated behind a 10-day clean dual-run). _(The read-only
transport that read-routes through the token manager is now built — see "Stage 1" above — but stays
NOT_PROVEN against live until the credential-in proof pass.)_

## Architect open-items (NOT for Claude Code to guess)
Schwab Portal: callback URL, scopes, token TTLs, refresh roll-forward behavior, rate-limit numbers,
account-hash rules, cost-basis/tax-lot field availability. OAuth topology (1 app vs 3 apps = 1 vs 3
weekly manual logins). Until the logged-in portal proves the 7-day window rolls forward, Gate A assumes
the worst case.

## A1A
Additive only; no behavior change to paper trading, screeners, GO/WAIT, ATM routing, or the live-trading
interlock. Holdings pipeline untouched (protected writer is opt-in). Secrets: Fernet key 0600 + gitignored,
never in DB/Drive/git/logs. **Docs-sync reminder:** sync to Drive on each change.
