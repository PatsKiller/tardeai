# Paca Accounts (Future) — Personal & IRA

**Status:** ROADMAP ONLY — **not implemented** in Trade AI runtime  
**Taxonomy:** `docs/brokers/trading-environments.md`  
**Do not** point paper adapters at live endpoints.

“Paca” = operator name for **live Alpaca** brokerage accounts (personal taxable + IRA), as distinct
from **paper** and from **Schwab/Fidelity** live books.

## 1. Product facts (Alpaca / public docs — verify before build)

Sources: Alpaca Trading API product docs, support FAQs, and Alpaca’s IRA-for-Trading-API announcement
(API-enabled Traditional/Roth for eligible US tax residents). **Confirm current policy on
alpaca.markets before enabling capital.**

| Topic | Paper | Paca personal (live individual) | Paca IRA |
|-------|-------|----------------------------------|----------|
| Trading host | `paper-api.alpaca.markets` | `api.alpaca.markets` | Same live host; **account id** is IRA |
| Capital | Simulated | Real taxable | Real retirement |
| Auth | Paper key pair | **Separate** live key pair | Separate keys / account association |
| Margin / short | Paper sim | Account-dependent | Typically **restricted** (cash-like retirement rules) |
| Options | Paper options lane | Live options if approved | Product-dependent — often limited |
| Crypto | Varies | Varies | Often **restricted/unavailable** |
| KYC / funding | N/A paper | Full KYC, ACH/wire | IRA onboarding + contribution limits |
| Contributions / distributions | N/A | Brokerage transfers | Portal ACH contributions/distributions; **not** fully automated via trading API |
| Tax | N/A | Taxable events | IRA tax treatment (operator + CPA) |

Deposits, withdrawals, and many IRA admin actions are **portal-side**, not order API.

## 2. Why a new path is required

Paper code is intentionally hostile to live:

- `AlpacaPaperAdapter` **raises** if `ALPACA_BASE_URL` points at live `api.alpaca.markets`.
- Options paper module refuses any `*LIVE*` Alpaca/APCA env var and non-paper hostnames.
- `proposal_paper_submitter` blocks unless `ALPACA_MODE=paper` and paper URL.
- Dozens of scripts `assert ALPACA_MODE == paper`.

**Flipping env to live keys without new modules would either fail closed or (if someone removes
guards) route real money through paper-named code — both unacceptable.**

## 3. Proposed account keys & capabilities

```json
{
  "paca_personal": {
    "env_id": "paca_personal",
    "capital": "real_taxable",
    "can_short_stock": null,
    "options_level": null,
    "inverse_etf_ok": true,
    "note": "operator-fill from Alpaca account settings before arming"
  },
  "paca_ira_roth": {
    "env_id": "paca_ira",
    "capital": "real_retirement",
    "can_short_stock": false,
    "margin": false,
    "options_level": null,
    "inverse_etf_ok": true
  },
  "paca_ira_traditional": {
    "env_id": "paca_ira",
    "capital": "real_retirement",
    "can_short_stock": false,
    "margin": false
  }
}
```

Extend `config/account_capabilities.json` only after operator verification on the real account.

## 4. Gap analysis → required work

| Area | Gap | Required work |
|------|-----|---------------|
| Client | Only paper adapter | Factory: `BrokerEnv` → paper \| personal \| ira client |
| Credentials | Single `ALPACA_API_*` pair | Per-env secrets; never reuse paper keys for live |
| Safety mode | `PAPER_TRAINING` only for Alpaca | New modes + ExecutionGuard grants |
| Path A submitter | Paper-only | **Do not** open Path A to live; use Path-B-like gates + 2FA/Telegram |
| Holdings | Paper book separate | Live Paca positions must not merge into Schwab holdings without explicit multi-broker model |
| Journal | `paper_trades` | New or unified `trade_instances` with `execution_env` |
| IRA rules | None | Block margin/short/crypto if product forbids; contribution tracking off-API |
| UI | “Alpaca Paper” | Explicit Personal / IRA labels; no bare “Alpaca submit” |
| Testing | Paper e2e | Paper regression + live dry-run (no submit) + canary $1 share protocol |
| Compliance | Paper validation narrative | Update six-month paper gate story before any live Alpaca |

## 5. Migration path (phased)

### Phase 0 — Taxonomy (this doc set) ✅
Freeze names: `paper` / `paca_personal` / `paca_ira`. Inventory complete in audit.

### Phase 1 — Config & aliases (no capital)
- Load `config/broker_environments.yaml` (proposed).
- Alias map: `alpaca_paper` → `tradeai_automated` → env `paper`.
- Rename env vars with backward-compatible reads.
- UI glossary + routing labels only.

### Phase 2 — Live client scaffold (writes blocked)
- Implement `AlpacaLiveAdapter` behind ExecutionGuard with `enabled: false`.
- Dry-run order translation only; **no** POST unless canary flag + operator typed phrase.
- Account discovery: list positions/balances read-only.

### Phase 3 — Personal canary
- Small-notional equity canary on `paca_personal` only.
- Reuse Schwab patterns: approval_service, caps, kill file, evidence.
- Separate journal stream.

### Phase 4 — IRA (if product fits strategy)
- Capabilities matrix enforced.
- No strategy that requires margin/short until proven allowed.
- Operator runbook for contributions/RMDs (portal).

### Phase 5 — Strategy promotion
- Strategies that graduated paper → optional paca_personal allowlist.
- IRA allowlist independent (often long-only / covered only).

## 6. Interaction with Schwab/Fidelity IRAs

Household already has **Schwab rollover/Roth** and **Fidelity** sleeves. Paca IRA is **optional
parallel**, not a replacement:

| Book | Role today |
|------|------------|
| Schwab IRAs | Primary retirement capital + covered options tier (operator-verified) |
| Fidelity | Rollover / FA manual |
| Paca IRA | Only if API automation benefit exceeds operational cost |

Do not auto-route retirement strategies to Paca IRA without explicit account_key allowlist.

## 7. Testing strategy (before any live submit)

1. **Paper regression** — existing pytest + options paper host invariants stay green.
2. **Config tests** — live URL never accepted by paper modules.
3. **Factory tests** — wrong env refuses wrong credentials.
4. **Dry-run live** — signed payload logged, no network write.
5. **Canary protocol** — mirror `stage2a-canary-protocol.md` dollar/qty caps.
6. **Kill switch** — global + per-env files.

## 8. Explicit non-goals (now)

- Enabling `api.alpaca.markets` in `alpaca_paper_adapter.py`.
- Sharing one API key across paper and live.
- Treating paper PnL as live performance for IRMAA/tax.
- Auto-IRA contributions via trading bots.

## 9. Operator checklist when ready to open Paca accounts

- [ ] Open live individual / IRA at Alpaca portal; complete KYC.
- [ ] Generate **new** API keys; store outside git.
- [ ] Confirm options/margin/crypto flags in portal → fill capabilities JSON.
- [ ] Confirm funding path (ACH) and, for IRA, contribution year limits with tax advisor.
- [ ] Implement Phase 1–2 code; do not “just change .env”.
- [ ] Paper remains default for ATM until allowlist says otherwise.
