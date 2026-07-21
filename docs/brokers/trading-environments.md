# Trading Environments — Taxonomy & Configuration

**Status:** CANONICAL taxonomy (2026-07-21) · **D1 keys:** `tradeai_automated` / `alpaca_taxable_live` / `alpaca_ira_live` (`paca_*` SUPERSEDED) · **Implementation:** paper live; personal/IRA **not** wired  
**Audit:** `docs/brokers/ALPACA_DUE_DILIGENCE_AUDIT_2026-07-21.md`  
**Paper procedures:** `docs/brokers/paper-trading.md` · **Future live Alpaca:** `docs/brokers/paca-accounts.md`

## 1. Why taxonomy matters

Today the system says **“Alpaca”** when it means **“Alpaca paper training.”** That coupling will break
silently when live **Alpaca taxable live** or **Alpaca IRA live** credentials are added if:

- the same env vars (`ALPACA_API_KEY`) are reused for live keys,
- `ALPACA_MODE=paper` checks are the only gate (keys point live while mode string still says paper),
- UI/logs label every Alpaca path as “paper,” or
- account_key `alpaca_paper` is assumed to mean “the only Alpaca account.”

This document freezes names **before** live Alpaca capital.

## 2. Environment IDs (use these everywhere new)

| Env ID | Meaning | Money | API host (Trading) | Status in Trade AI |
|--------|---------|-------|--------------------|--------------------|
| `paper` | Alpaca **paper** sandbox | Simulated | `paper-api.alpaca.markets` | **LIVE path A** |
| `alpaca_taxable_live` | Alpaca **live taxable / personal** brokerage | Real | `api.alpaca.markets` | **NOT IMPLEMENTED** |
| `alpaca_ira_live` | Alpaca **live IRA** (Traditional/Roth) | Real retirement | `api.alpaca.markets` (account-scoped) | **NOT IMPLEMENTED** |

**Vendor name:** Alpaca Markets. **“Paca”** = operator shorthand for live Alpaca accounts only.
**Never** use `paca_*` for paper.

### Related non-Alpaca envs (already in production)

| Env / account family | Money | Notes |
|----------------------|-------|-------|
| `schwab_taxable` / `schwab_*_ira` | Real | Path B + 2FA; not Alpaca |
| `fidelity_*` | Real | Manual FA / SnapTrade read; not Alpaca |

## 3. Account keys (DB / ATM / proposals)

| account_key | Env ID | Notes |
|-------------|--------|-------|
| `tradeai_automated` | `paper` | **Canonical ATM account** (`config/atm_config.yaml`) |
| `alpaca_paper` | `paper` | **Legacy** storage / strategy YAML / defense caps — still widely used |
| `ALPACA_PAPER` | `paper` | **DB display** string in some `paper_trades` rows |
| *(future)* `alpaca_taxable_live` | `alpaca_taxable_live` | Proposed |
| *(future)* `alpaca_ira_live_traditional` / `alpaca_ira_live_roth` | `alpaca_ira_live` | Proposed split if both opened |

Resolution helper today: `scripts/broker_config.py` (`get_default_paper_account()`,
`get_broker_for_account()`). Migrate call sites from `alpaca_paper` → `tradeai_automated` with a
**alias map** until storage is unified.

## 4. Execution modes (safety enum)

From ADR-B1 / `execution-safety-guards.md`:

| Mode | Allowed adapters | Capital |
|------|------------------|---------|
| `PAPER_TRAINING` | Alpaca paper only | Simulated |
| Schwab live modes | Schwab pilot / 2FA | Real |
| *(future)* `PACA_PERSONAL_LIVE` | New live Alpaca adapter | Real taxable |
| *(future)* `PACA_IRA_LIVE` | Same client, IRA account id + restrictions | Real IRA |

**Rule:** Changing mode never re-points the paper adapter’s base URL. Live Alpaca requires a **new
adapter module** (or factory branch) that never shares paper’s default path.

## 5. Credentials & env vars

### Current paper (as-is)

| Variable | Role |
|----------|------|
| `ENABLE_ALPACA_PAPER` | Master enable (default false in code; true in ops `.env`) |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Paper key pair |
| `ALPACA_MODE` | Must be `paper` for paper submitters/monitors |
| `ALPACA_BASE_URL` / `ALPACA_PAPER_BASE_URL` | Must resolve to paper host |
| `DEFAULT_PAPER_ACCOUNT` / ATM default | `alpaca_paper` or `tradeai_automated` |
| `LLM_DISABLE_LIVE_EXECUTION` | Fleet/system live block |
| `LIVE_TRADING_ENABLED` | Must stay false for paper-only submitter |

**Do not** store live keys in these names.

### Proposed multi-env shape (config-driven)

```yaml
# config/broker_environments.yaml  (PROPOSED — not yet loaded by runtime)
version: 1
environments:
  paper:
    vendor: alpaca
    capital: simulated
    trading_base_url: https://paper-api.alpaca.markets
    data_base_url: https://data.alpaca.markets
    account_keys: [tradeai_automated, alpaca_paper]
    credentials_env:
      key_id: ALPACA_PAPER_KEY_ID
      secret: ALPACA_PAPER_SECRET_KEY
    feature_flags:
      auto_submit_equity: true   # Path A gates still apply
      auto_submit_options: false # operator --confirm only
      requires_2fa: false
  alpaca_taxable_live:
    vendor: alpaca
    capital: real_taxable
    trading_base_url: https://api.alpaca.markets
    data_base_url: https://data.alpaca.markets
    account_keys: [alpaca_taxable_live]
    credentials_env:
      key_id: ALPACA_PERSONAL_KEY_ID
      secret: ALPACA_PERSONAL_SECRET_KEY
    feature_flags:
      auto_submit_equity: false  # start operator-gated / 2FA-equivalent
      requires_2fa: true         # map to Trade AI approval_service pattern
      enabled: false
  alpaca_ira_live:
    vendor: alpaca
    capital: real_retirement
    trading_base_url: https://api.alpaca.markets
    account_keys: [alpaca_ira_live_roth, alpaca_ira_live_traditional]
    credentials_env:
      key_id: ALPACA_IRA_KEY_ID
      secret: ALPACA_IRA_SECRET_KEY
    feature_flags:
      margin: false
      short_stock: false
      crypto: false            # verify against current Alpaca IRA policy
      enabled: false
```

Secrets remain in OS env / keyring / broker-admin — **never** in git or Drive docs.

### Migration of env names (recommended)

| Today | Target paper | Target personal | Target IRA |
|-------|--------------|-----------------|------------|
| `ALPACA_API_KEY` | `ALPACA_PAPER_KEY_ID` (alias old) | `ALPACA_PERSONAL_KEY_ID` | `ALPACA_IRA_KEY_ID` |
| `ALPACA_SECRET_KEY` | `ALPACA_PAPER_SECRET_KEY` | `ALPACA_PERSONAL_SECRET_KEY` | `ALPACA_IRA_SECRET_KEY` |
| `ALPACA_MODE=paper` | `BROKER_ENV=paper` | `BROKER_ENV=alpaca_taxable_live` | `BROKER_ENV=alpaca_ira_live` |

Keep reading legacy names during transition; **fail closed** if live URL + paper-only code path.

## 6. Code ownership by env

| Concern | paper | alpaca_taxable_live / alpaca_ira_live (future) |
|---------|-------|-------------------------------------|
| Equity submit | `alpaca_paper_adapter.py` | New `alpaca_live_adapter.py` (or factory) |
| Options | `lib/options_pipeline/alpaca_paper.py` | Separate policy + flags; IRA restrictions |
| Path A gates | `proposal_paper_submitter.py` | Not reused blindly — new live gates + 2FA |
| Path B pattern | N/A | Mirror Schwab: approval + audit + caps |
| Account capabilities | `config/account_capabilities.json` → `alpaca_paper` | New keys + options/margin matrix |
| UI routing labels | `paper_auto` | `live_alpaca_taxable_live` / `live_alpaca_ira_live` |

## 7. Glossary

| Term | Definition |
|------|------------|
| **Paper / Path A** | Simulated Alpaca execution for strategy validation |
| **Alpaca taxable live** | Live Alpaca individual taxable brokerage (API) |
| **Alpaca IRA live** | Live Alpaca Traditional or Roth IRA (API-enabled per Alpaca 2025–2026 product) |
| **PAPER_TRAINING** | Execution-safety mode for paper only |
| **tradeai_automated** | Canonical paper account_key for ATM |
| **alpaca_paper** | Legacy paper account_key still present in YAML/DB |
| **Schwab / Fidelity** | Live capital outside Alpaca; not “paca” |
| **Promote to Broker** | Path B — real money, not paper |

## 8. Naming rules for new code

1. Functions that **only** work on paper: keep `*_paper_*` in the name or take `env_id` and assert `paper`.
2. Never name a live client `AlpacaPaperAdapter`.
3. Logs: `broker=alpaca env=paper account=tradeai_automated` (three fields).
4. DB: store `account_key` + `execution_env` + `capital_type` (`simulated|taxable|ira`).
5. UI: “Alpaca Paper” vs “Alpaca Personal” vs “Alpaca IRA” — never bare “Alpaca” on a submit button for live.

## 9. Related docs

- `docs/PROPOSAL_EXECUTION_PATHS.md` — Path A vs Path B
- `docs/brokers/broker-abstraction-adr.md` — interfaces
- `docs/brokers/execution-safety-guards.md` — mode guards
- `docs/brokers/current-state-alpaca-integration.md` — 2026-06-11 discovery (still accurate core)
- `docs/brokers/ALPACA_DUE_DILIGENCE_AUDIT_2026-07-21.md` — full inventory & gaps
