# Stage 12 — Security and Boundary Evidence

Deterministic checks run by the main agent at HEAD ea0d6110 (reproducible). The reviewer
independently re-verified these; results agreed.

## 1. Regression
- Prod venv (`/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv`): `pytest -k active_trader`
  → **162 passed, 0 failed, 52 skipped**. Skips are all env-gated: `ACTIVE_TRADER_TEST_DATABASE_DSN
  not set (lab DB required; never runs on production)` and moomoo-SDK absent in prod venv.
- Lab venv (`~/.local/venvs/trade-ai-lab/moomoo-api/current`): moomoo SDK tests (stage5) → **30 passed,
  1 skipped, 0 failed**.
- Net: 192 unique passing across venvs, 0 failures.

## 2. Builds
- `apps/command-center-v3-next`: vitest **9 passed**; `vite build` OK (35 modules; `dist/assets/index-*.js`
  176.63 kB; base `/v3-next/`).
- `apps/command-center-v3`: `vite build` OK (1252 modules; 3.51 MB bundle — pre-existing chunk-size
  advisory, not a failure). **0 files changed vs origin/main** (`git diff --name-only origin/main..HEAD --
  apps/command-center-v3` empty).

## 3. Secret scan
- Pre-commit hook: "no secrets or hardcoded values in staged change (4 files scanned)".
- Pre-push hook: "no secrets or hardcoded values in tree (5854 files scanned)".
- Reviewer secret-value regex scan of active_trader tree → 0 hits.

## 4. Trade-API AST prohibition scan
- `active_trader/moomoo/ast_guard.py::scan_source` over `scripts/active_trader/**.py` → **30 files, 0
  findings**. FORBIDDEN_NAMES cover `OpenSecTradeContext`/`OpenUSTradeContext`/`unlock_trade`/
  `place_order`/`modify_order`/`cancel_order`/`close_position` + `TrdEnv.REAL`/`TrdEnv.SIMULATE`.
- Direct grep for trade-method CALLS in shadow_engine/simulation/governance/session_builder/
  authorization → 0.

## 5. Network-call scan (shadow / simulation)
- `shadow_engine.py`, `simulation.py`: **0** imports of requests/socket/urllib/http.client/OpenQuoteContext.
  Both are deterministic, in-process, fixtures/replay only (enforced also by
  `test_no_network_no_broker_write_symbols`, `test_no_order_or_broker_field`).

## 6. Migration target scan
- `migrate.py`: `PRODUCTION_DB_NAMES={'trade_ai'}`, `PRODUCTION_PORTS={'5432'}`. Refuses on db name,
  port 5432, sentinel DSN, and re-checks `SELECT current_database()` at connect time. All active_trader
  migrations target `trade_ai_test`.
- Cautious note (per controller §12.6): production tables were NOT independently measured (must not query
  production). The guard makes creation of any active_trader/`md_*` table in production impossible via this
  runner, and the production checkout is untouched by this worktree.

## 7. Feature-flag scan
- `contracts.FLAG_REGISTRY`: 22 flags. `DEFAULTS['production']` → **all 22 OFF**, including
  `active_trader_live_canary_enabled=OFF`. `DEFAULTS['development']` raises only
  `active_trader_next_visible` to READ_ONLY. `DEFAULTS['test']` all OFF.

## 8. User-unit enabled-state scan
- `systemctl --user`: `trade-ai-lab-moomoo-{opend,gateway,replay-writer,feature-engine,health-monitor}
  .service` all `enabled=static` (no `[Install]` → cannot be enabled) and `active=inactive`.

## 9. PR draft state
- PR #150: `draft=true`, `state=OPEN`. Not marked ready; not merged.

## Boundary summary
/v3 unchanged · production DB isolated (guarded) · dev-write plane loopback/default-off/SHADOW-SIMULATION/
test-identity · read API caps+CORS+rate+pagination · identifiers masked · all live flags OFF · trade API
statically unreachable · quote-right auto-grab off · rate governors with reserves · governance proposal-only ·
Bitwarden metadata-only · units disabled · Stage 14 unreachable.
