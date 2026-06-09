# Schwab API — Phase 1 Read-Only Foundation (canonical)

> **Correction to commit `23f17865`.** That commit's title says "(PROVEN)" — read it as
> **"guards proven by SIMULATION; live Schwab integration NOT_PROVEN."** There is **no live Schwab
> connection** in this phase. The `validate_schwab_no_writes.py` "7/7 green" is a *no-writes / isolation*
> guard, not a connectivity claim. This doc is the authoritative framing.


**Status (2026-06-09):** Safety **guards proven by simulation**. **Live Schwab integration is NOT_PROVEN**
and architecturally fenced off — there is **no working Schwab connection** in this phase. No live trading
authorization. Schwab accounts stay MANUAL_REVIEW / read-only / `api_write_enabled=false`.

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
- `scripts/validate_schwab_no_writes.py`: **7/7 guards green** — no write path, all write methods
  NOT_PROVEN, position-sync routes through the protected writer, all 3 Schwab accounts
  `api_write_enabled=false`, `live_trading_interlock` refuses them (live + master flag off), and **Level
  II / volume-sweep / Schwab data isolated** from the screeners (`prime_setups`/`watchlist_setups`),
  match-minimums, GO/WAIT, and ATM routing (Rule 9).

## Schema (additive — `migrations/2026-06-09_schwab_oauth_foundation.sql`)
`broker_oauth_tokens` (encrypted, no plaintext), `broker_oauth_token_audit` (append-only, fingerprints
only), `schwab_account_links`, `schwab_api_raw_snapshots`, `schwab_basis_divergence`, `schwab_sync_history`.
Existing `broker_accounts`/`account_automation_policies`/`broker_capability_checks` reused — **no competing
registry**.

## NOT built this phase (sequenced / out of scope)
Live OAuth exchange, the read-only adapter read-routing through the token manager, account-hash live
mapping, the `/api/v2/admin/broker-account/schwab/*` endpoints, `broker_capability_checks` population
(stays NOT_PROVEN), `broker_confirm_schwab.py` (deliberately absent), Level II / streaming, CSV-import
retirement (gated behind a 10-day clean dual-run).

## Architect open-items (NOT for Claude Code to guess)
Schwab Portal: callback URL, scopes, token TTLs, refresh roll-forward behavior, rate-limit numbers,
account-hash rules, cost-basis/tax-lot field availability. OAuth topology (1 app vs 3 apps = 1 vs 3
weekly manual logins). Until the logged-in portal proves the 7-day window rolls forward, Gate A assumes
the worst case.

## A1A
Additive only; no behavior change to paper trading, screeners, GO/WAIT, ATM routing, or the live-trading
interlock. Holdings pipeline untouched (protected writer is opt-in). Secrets: Fernet key 0600 + gitignored,
never in DB/Drive/git/logs. **Docs-sync reminder:** sync to Drive on each change.
