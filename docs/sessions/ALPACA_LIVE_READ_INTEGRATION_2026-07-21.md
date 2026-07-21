# Alpaca Live Read-Only Integration — Session Handoff

**Date:** 2026-07-21  
**Machine:** MS-01  
**Constraint:** Absolute no execution — no live orders, no arm, no `is_enabled` / `api_write` flips.

## Scope delivered

| Phase | What |
|-------|------|
| **A** | Secrets labels/badges; `GET /api/v2/broker-accounts` enrichment; `POST …/api-read-toggle` + `…/test-connection`; `AlpacaLiveReadPanel` under System → Admin (Secrets) |
| **B** | `scripts/brokers/alpaca_read_client.py` (GET-only transport); `scripts/alpaca_live_read_sync.py` (merge via `protected_holdings_write`); cron installer (no-op until `api_read_enabled`) |
| **C** | Census labels: `portfolio_accounts.yaml`, CC v3 `holdingsRowModel`, CC v2 PortfolioIntelligence colors/labels |
| **D** | Unit tests (GET refuse non-GET, empty no-op merge); Vite build; this handoff; Drive sync for docs |

## Operator answers locked (Q1–Q7)

1. Telegram: existing helper (`telegram_alert.send_telegram`)
2. Holdings: merge path A — per-account replace via `protected_holdings_write`
3. Paper: path A — live read client separate; paper pipeline unchanged
4. Cron: path B — install marked crontab block (15m market hours)
5. Execute-list: A — do not wire live accounts into submit lists
6. Playwright: dist A — screenshots from production dist after Vite
7. Flags: leave `api_read` / `api_write` / `is_enabled` / `live_arm` **false/null**

## Safety invariants

- Transport allowlist is **GET only** — POST/PUT/PATCH/DELETE raise `MethodNotAllowedError`
- Host from credential **slot** (`ALPACA_TAXABLE` / `ALPACA_IRA` → `api.alpaca.markets`), never `ALPACA_BASE_URL`
- Sync iterates only `broker=alpaca AND environment=live AND api_read_enabled=true`
- Default scaffolds → **zero API calls**
- Empty positions + no prior rows for that account → **pure no-op** (must not zero ~$1.26M book)
- Toggle endpoint refuses smuggled `api_write_enabled` / `is_enabled` / `live_arm_token`
- Factory still raises `NotImplementedError` for live adapters

## Admin UI

- **System → Admin → API Keys & Secrets:** Alpaca TAXABLE/IRA keys show label + badge  
  `READ-ONLY DATA · execution not built`
- **System → Admin → Alpaca Live — Read-Only Data:** per-scaffold  
  `api_read_enabled` checkbox + Test connection (GET `/v2/account` probe)

## Cron

```bash
bash scripts/install_alpaca_live_read_sync_cron.sh
```

Lines: `*/15 9-16 * * 1-5` · flock · `scripts/alpaca_live_read_sync.py`

## Tests

```bash
.venv/bin/python -m pytest tests/test_alpaca_live_read_client.py -q
```

## Explicit non-goals (this session)

- Populating live API keys
- Enabling `api_read_enabled` (operator action later)
- Live order adapter / arm protocol / TradingView live submit
- GitHub token rotation (deferred)

## See also

- `docs/brokers/alpaca-live-accounts.md`
- `docs/sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md`
- R1–R5 taxonomy stack on `main`
