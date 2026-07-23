# Active Trader Stage 0 — System Baseline

**Run ID:** 20260722-01 · **Date:** 2026-07-22 · **Host:** ms01 (Linux 7.0.0-27-generic)
**Base SHA:** 87c2fa09fa95a8a69233959b04b1144e1297b923 (= origin/main at Stage 0 start)
**Branch:** feat/active-trader-next · **Worktree:** /home/johnclaw/worktrees/active-trader-next

## 1. Git state
- Production checkout `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`: branch `main` at `2b25ad8f` (strict ancestor of base SHA; behind by the docs-staging commits only). Working tree: 22 dirty entries including **2 unresolved UU index entries** (`config/hermes_score_weights.yaml`, `scripts/watchlist_entry_planner.py` — no MERGE_HEAD; wedged conflict state), ~18 modified `config/strategies/*.yaml` + `config/ipo_lockups.json` + `scripts/run_telegram_callback_poller.py`, 1 untracked screenshot dir; 5 stashes. **All preserved untouched.**
- 7 existing worktrees (incl. this one); remote `origin = https://github.com/PatsKiller/tardeai`.
- No AGENTS.md or CLAUDE.md exists anywhere in the repository (program §0 step 2 input absent — litmus NF-3).

## 2. Runtime versions (verified live 2026-07-22)
```text
Python (prod venv):  3.14.4        openai:  2.30.0 (matches architecture §7.9 "repo pin 2.30.0")
Node:                v22.23.1      npm:     10.9.8
Hermes Agent:        0.15.2 (2026.5.29.2)   [architecture §7.9 said "last documented 0.16.0" — actual is OLDER; recorded]
OpenClaw:            2026.6.11 (e085fa1)    [matches architecture's "later evidence reported 2026.6.11"]
PostgreSQL:          17.10 (Ubuntu)         db=trade_ai user=trade_ai · 657 public tables
pgvector:            NOT INSTALLED (pg_extension has no 'vector' row)
Ollama models:       gemma3:27b, gemma3-overnight, gemma3:12b, qwen3:8b, gemma3:12b-ctx4k, gemma3:4b, qwen3-embedding:8b
moomoo/futu SDK:     NOT INSTALLED · OpenD: NOT INSTALLED (no binary, no service)
Clock:               chrony synced (stratum 3)
Disk:                265G free of 468G (41% used)
```

## 3. Services (live)
- System scope: `tradeai-portfolio-server.service` RUNNING (MainPID 853265, `scripts/portfolio_server.py`, WorkingDirectory = production checkout, port 7777+7776), `ollama.service`.
- User scope: `openclaw-gateway.service` (:18789), `grok-oauth-proxy` (:8645), `chatgpt-oauth-proxy` (:8646), `heartbeat-receiver`.
- NOTE: repo docs (OPERATIONS.md) describe user-scoped `portfolio-server.service`; live host runs system-scoped `tradeai-portfolio-server.service` — doc/runtime mismatch recorded.
- Cron: 454 active crontab entries.
- `moomoo-opend.service` / `moomoo-gateway.service`: DO NOT EXIST.

## 4. Repository baseline (summary; details in companion artifacts)
- `/v3` frontend: React 18 + Router 6 + Vite 5 at `apps/command-center-v3`, base `/v3/`, served from `dist/` by `portfolio_server.py`; build-meta version stamping; Playwright e2e exists but is NOT in CI. NO `/v3-next`. → ACTIVE_TRADER_ROUTE_API_DB_MAP.md Part 1.
- Backend: stdlib http.server; ALL internal routes are `/api/v2/*` owned by `scripts/api_v2.py` (~477 GET + ~40 mutating); **zero internal `/api/v3/*` routes; `/api/v3/active-trader` confirmed absent**. Hot-reload = api_v2 + reports_portal only. → Part 2.
- DB: raw-SQL ad-hoc migrations (78 files, no framework, no tracking table, no per-migration rollback); Active-Trader tables absent except `broker_capability_checks`. → Part 3.
- Brokers: Alpaca paper = only auto-executing lane; Schwab reads live/writes fenced (protective-stop + 2FA pilot lane); SnapTrade read-only (gate OFF); tastytrade scaffold (unregistered — scope decision needed); Fidelity monitored-only; **Moomoo nonexistent**. → ACTIVE_TRADER_BROKER_ACCOUNT_INVENTORY.md.
- Guardrails: execution_guard (BROKER_DISABLED default, fail-closed), per-order 2FA (either-channel, TTL 10m, one-order-at-a-time), kill switches (DB + files), write fences + CI proofs. **No session-scoped 2FA exists.** → ACTIVE_TRADER_CURRENT_GUARDRAILS.md.

## 5. External-service prerequisite checks (non-destructive)
| Service | Result |
|---|---|
| GitHub | VERIFIED — gh authenticated as PatsKiller; repo permissions push=true admin=true; `main` NOT protected; branch `feat/active-trader-next` created from base SHA and pushable; draft-PR permitted |
| Google Drive | VERIFIED — canonical folder `Trade_AI_Docs_v2` exists (id `1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR`, owner john@jwwhiting.com, canAddChildren=true); repo sync convention `scripts/sync-docs-to-drive.sh` targets the same folder id; secondary `Trade_AI_Backups` (`1GYbZyM8nTfwuh-h2EsWTxbMpXlEUA6Qi`) for encrypted backups. Write+hash verification performed during Stage 0 sync |
| Gmail | PARTIAL — read access verified via connected claude.ai Gmail integration (operator john@jwwhiting.com). The connected integration supports DRAFT creation but has NO send capability. Existing repo path `scripts/email_notifier.py` sends via `gog gmail send` (available on host; not exercised in Stage 0 to avoid unsolicited sends). GMAIL_SEND_AS / GMAIL_NOTIFICATION_CREDENTIAL_SLOT: NOT CONFIGURED as named env keys — operator TODO |
| Bitwarden SM | PARTIAL — bws CLI 2.1.0 installed; project convention `trade-ai-prod` (secrets_admin.py:135); token files convention `~/.openclaw/credentials/bws_read_token` / `bws_write_token` (`scripts/secrets/bws_env.sh`); render pipeline `tradeai-sm-render.service`. No secret values read. **Lab project `trade-ai-lab`: NOT FOUND configured anywhere — lab placeholder creation NOT attempted (no explicit authorization + no lab project). Operator TODO** |
| Test database | NOT CONFIGURED — no `*test*`/`*lab*` database exists in the cluster; CI uses ephemeral `postgres:17` service in GitHub Actions only. Local migration rollback path = pg_dump restore. Operator TODO for Stage 1 test-DB provisioning |

## 6. Stage 0 findings of record
1. Base-SHA gate initially FAILED against the local checkout (behind + wedged conflict); architecture owner authorized worktree execution from origin/main (Option 1, 2026-07-22).
2. `migrations/` filenames dated 2026-07-23..26 exist at a 2026-07-22 commit (future-dated names; cosmetic but noted).
3. `canary_gate.GATES_REMOVED=True` — numeric BUY envelope is a pass-through; per-order 2FA is the operative gate (matches operator's standing directive; verify intent in Stage 1 design).
4. `pilot_caps.MAX_PILOT_ORDERS_TOTAL=9999` vs docstring "operator cap 5" — authority mismatch, UNVERIFIED.
5. Architecture §7.9 version table vs live host: Hermes actual 0.15.2 (older than "0.16.0 documented"); OpenClaw 2026.6.11 confirmed; openai 2.30.0 confirmed; pgvector assumed by KB design but NOT installed.
6. `.env` `DEFAULT_PAPER_ACCOUNT=alpaca_paper` vs `.env.example`/`portfolio_accounts.yaml` `tradeai_automated` — label discrepancy, UNVERIFIED which the accounts table resolves.
7. Litmus review verdict: CONDITIONAL_PASS (BF-1 Moomoo broker-native protection unproven; BF-2 dual rate-ceiling governor under-specified — both gate Stage 14/P14, not Stages 0–13).

## 7. UNVERIFIED register (carried to OPERATOR_TODO)
- Live `accounts` DB table row inventory and per-broker account IDs (needs Stage 2 probes).
- `config/snaptrade_accounts.json` missing vs runtime-generated.
- Tastytrade runtime wiring; scalp_ws_server port/unit; SSE-absence; peewee scope; Alpaca raw-HTTP detail; offline-safety of ~314 tests (heuristic).
- GMAIL_* named credential slots; `trade-ai-lab` Bitwarden project; test database.
- Moomoo OpenD broker-resident stop capability (litmus BF-1 — external evidence required).
