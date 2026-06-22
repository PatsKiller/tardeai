# SnapTrade Read-Only Aggregation — Spec

**Status:** LIVE (2026-06-14) — Fidelity 401k + Rollover IRA connected; sync scheduled 3×/trading day; real
401k holdings ($566,790) applied to holdings.json. Connect flow uses personal-key secret rotation (not
registerUser). Remaining: rollover-IRA fills on transfer (hands-off via vanished-account auto-zero).
**Owner:** operator (John). **Created:** 2026-06-14.

## Purpose
Add SnapTrade as an **additive, read-only** holdings source — primarily to read accounts that have no clean
direct API today (the **Fidelity 401k**, currently faked with proxy ETF codes in `HOLDING_PROXY_MAP`). It is
NOT a replacement for the direct Schwab integration, and it introduces **no trading capability**.

## Scope today / design rules
- **Read-only sync now; trading deliberately NOT here yet — but NOT hard-blocked.** Operator may add SnapTrade
  trading later (ideally a `snaptrade_trade.py` sibling behind the same canary + 2FA rails as the Schwab write
  pilot). Nothing in this layer prevents that — there is intentionally no CI fence forbidding a write surface.
- **Reads run when configured.** As soon as the client keys + a linked brokerage user are present, reads work
  (no separate enable flag). What's gated is *persisting* to holdings.json — that needs `--apply` (default is
  a dry run).
- **Additive, never destructive.** Writes go through `schwab_position_sync.protected_holdings_write()`
  (sanity-gated, fails closed, never wipes/zeroes, basis-shielded). The sync replaces ONLY the accounts mapped
  in `config/snaptrade_accounts.json`; every other account is preserved verbatim.
- **No hardcoded values.** Client + user secrets in `config/broker_credentials.env`; account→key mapping in
  `config/snaptrade_accounts.json`.
- **`is_unstoppable_fund` still governs.** Real 401k fund symbols read via SnapTrade are still
  mutual-fund/CIT → "no exchange stop — trim/rebalance". Stops only apply to ETFs/stocks held in a brokerage.

## Auth model (two halves)
| Half | What | Where stored |
|------|------|--------------|
| **Client pair** | `clientId` + `consumerKey` (app-level, from the SnapTrade dashboard → API Keys) | `config/broker_credentials.env` (chmod 600, gpg-backed) — set via the UI modal |
| **User secret** | `userId` + `userSecret` (per end-user, minted by `registerUser`) | DB table `snaptrade_users` (encrypted) — created by the connect flow |

## Components
| File | Status | Role |
|------|--------|------|
| `scripts/brokers/snaptrade_credentials.py` | ✅ shipped | read/write/status of the client pair in the env file; write-only (status never returns the consumer key) |
| `scripts/brokers/snaptrade_read.py` | ✅ shipped | read client: `list_accounts / holdings / balances / activities` + `normalize_positions`. Reads when configured. |
| UI: `SnapTradeCredsModal.tsx` + Schwab Accounts "**+ Connect SnapTrade**" button | ✅ shipped | paste keys → `POST /api/v2/snaptrade/credentials`; shows masked status + connection |
| API: `GET /api/v2/snaptrade/status`, `POST /api/v2/snaptrade/credentials` | ✅ shipped | status (masked) + save keys |
| `scripts/brokers/snaptrade_connect.py` | ✅ shipped | `register` (mint userSecret) + `login` (brokerage link URL) + `status` |
| `scripts/snaptrade_sync.py` | ✅ shipped | pull mapped accounts → `normalize_positions` → merge → `protected_holdings_write`. **Dry run unless `--apply`.** |
| `config/snaptrade_accounts.json` | ✅ shipped (empty) | SnapTrade `accountId` → internal `account_key` map (only mapped accounts are synced) |

## Data flow
```
SnapTrade ──GET──▶ snaptrade_read (read-only) ──normalize_positions──▶ protected_holdings_write(src="snaptrade")
                                                                              │ (sanity gate, no-wipe)
                                                                              ▼
                                                                        holdings.json ──▶ rest of pipeline
```
Each holding carries `position_source="snaptrade"` provenance so the merge never double-counts and a stale/
failed sync falls back to the last-good snapshot **+ the existing proxy-map** (the 401k never disappears).

## SDK / API
Python: `pip install snaptrade-python-sdk` (imported lazily in `snaptrade_read._client()` — no hard dep until
opt-in). MCP/CLI/TS SDK also exist but the pipeline path is Python. Requests are signed with the consumerKey;
the SDK handles signing.

## Phased rollout
1. **Keys + connect (Fidelity 401k only).** Save keys (modal, done) → run connect flow → confirm `list_accounts`
   returns the 401k. Write to a **staging** table; diff vs the proxy-map estimate; validate against a statement.
2. **Promote 401k to SnapTrade-sourced** in holdings.json; demote the proxy-map to fallback. Flip
   `snaptrade_read.ENABLED=True` (commit) and schedule `snaptrade_sync.py` daily pre-market.
3. **Optional recon** — pull Schwab via SnapTrade purely to cross-check the direct read (a reconciliation
   signal, not a second source).

## Fidelity 401k → IRA rollover (operator, this week)
SnapTrade links at the **Fidelity login** and enumerates *all* accounts under it, so the new Fidelity IRA
will appear — but the sync will **not** auto-adopt it, by design:
- The new IRA has a **new SnapTrade account id** → add it to `config/snaptrade_accounts.json` (map to a key,
  e.g. `fidelity_ira`). Until mapped, it's ignored (safe — no surprise injection).
- May require **reconnecting** the Fidelity link in SnapTrade so the new account shows in `list_accounts`.
- **Decide the internal key:** reuse `fidelity_401k` (history/journal continuity) or new `fidelity_ira`
  (cleaner; note the rollover in the journal). The old 401k id, once empty/closed, simply stops returning
  data; leave it unmapped so its last snapshot isn't zeroed mid-transit.
- **Rollover transit is protected:** if the 401k briefly reads \$0 before the IRA funds, the
  catastrophic-drop guard in `protected_holdings_write` rejects the wipe and keeps the last-good snapshot.
- **Upside:** an IRA brokerage holds *real* ETFs/stocks → SnapTrade reads them directly (retiring the
  proxy-map guesses), and those become genuinely **stop-eligible**. Fidelity mutual funds kept inside the
  IRA stay `is_unstoppable_fund` (trim/rebalance), correctly.

## Trade-testing framework — Fidelity is READ-ONLY on SnapTrade (confirmed 2026-06-14)
**You cannot canary-test trades on Fidelity via SnapTrade.** Confirmed live: the Fidelity connection
`type = "read"` and, decisively, the brokerage's `allows_trading = False` on SnapTrade. This is a SnapTrade
platform limitation (Fidelity is not a trade-enabled brokerage there), not a config gap. So:
- `brokers/snaptrade_trade.py` stays gated OFF **and** now has a live `broker_allows_trading()` guard that
  refuses `place()` whenever no connected brokerage supports trading — so the scaffold never pretends a
  Fidelity order path exists. It would only ever activate for a *trade-capable* brokerage connected later.
- **The real gated-trade / stop canary test path is the Schwab write pilot (Stage 2b)** — Schwab Trader
  API, taxable account, $4/10-share/$40 envelope, per-order 2FA, dated 2026-06-15. That is independent of
  SnapTrade. SnapTrade's role here is **read-only aggregation only**.

## Data-custody note
Holdings/positions transit SnapTrade's servers. Given the self-hosted, no-external-leakage posture, scope is
deliberately limited to **read-only aggregation of accounts that lack a direct API**. Secrets stay gpg-encrypted;
the user secret is encrypted at rest; nothing trades.

## Protective stops (2026-06-22 addendum)

Fidelity remains **read-only** on SnapTrade — broker API stops are **not** available. A monitored-stop
stack mirroring Schwab Stage 2c 2FA is built but **gated off** until operator approval:

→ [`snaptrade-fidelity-protective-stops-spec.md`](snaptrade-fidelity-protective-stops-spec.md)

```bash
python3 scripts/snaptrade_pilot_arm.py --capability
python3 scripts/snaptrade_pilot_arm.py --approve --confirm "APPROVE FIDELITY STOPS $(date +%Y-%m-%d)"
```

## Open decisions (operator)
- SnapTrade account + which keys (client pair) — paste via the modal.
- Scope: 401k only (recommended) vs all accounts for cross-check.
- Comfortable with third-party data custody for the aggregated accounts?
- **Fidelity monitored stops:** run `--approve` above when ready (monitor-only, no 2FA; manual ticket on breach).
