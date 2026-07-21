# FINDINGS: Alpaca Paper/Live Taxonomy & Multi-Account Readiness Audit

**Type:** READ-ONLY due diligence — **nothing was changed** (except this findings file).  
**Date:** 2026-07-21  
**Executor:** Grok Code on MS-01  
**Tree:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`  
**HEAD:** `315b646f701c9c6730df54bf9bc106975d4a51ad` (branch `main`, dirty non-audit files present)

---

## 1. Preflight

| Check | Result | Verdict |
|-------|--------|---------|
| Holdings iron rule | `total_value=1259636.03`, `len(holdings)=36` | **FLAG-BACK:** prompt expected ~$1.2M and **~47** positions. Value OK (~$1.26M); **count is 36**, not ~47. Did **not** STOP (value non-zero). |
| `psql -d trade_ai` as shell user | `FATAL: role "johnclaw" does not exist` | **FLAG-BACK:** peer auth as OS user fails. |
| App DB path used instead | `psql -h localhost -p 5432 -U trade_ai -d trade_ai` via `.env` `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD` (password never printed) | `SELECT 1` → OK |
| Git | `main` @ `315b646f` · dirty: `config/ipo_lockups.json`, `docs/diligence/...OPTIONS_RISK_BLOCK_MATRIX.md`, `docs/project/RELEASE_MANIFEST_LATEST.md` | Continue read-only |
| Prompt expected recent history `cc67aace` Defense Desk v9 | **Not in last 15 commits** (HEAD is docs handoff / stop-kind / operator cards) | FLAG-BACK on expected history |

**Env var NAMES present (values never logged):**  
`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_MODE`, `ALPACA_PAPER_BASE_URL`, `ENABLE_ALPACA_PAPER`, `DEFAULT_PAPER_ACCOUNT`, `PAPER_ACCOUNT_SIZE`, `BROKER_LIVE_ENABLED`, `LLM_DISABLE_LIVE_EXECUTION`, `PROTECTION_ATM_AUTO_APPLY_PAPER`, `DB_*`.  
**Absent from `.env` key list:** `LIVE_TRADING_ENABLED` (code still reads it with default `false`).

---

## 2. Phase 1 — “alpaca = paper” conflation census

**Grep corpus:** `*.py|*.tsx|*.ts|*.yaml|*.yml|*.sql|*.json` excluding venv/node_modules/dist/__pycache__/backups.  
**Raw hit count:** **2920** lines in `/tmp/audit/alpaca_refs.txt`.

Classification is of **distinct mechanisms / hotspots**, not every test string. Counts below are **operator-relevant production-ish sites** (scripts + config + apps, not every pytest line).

### Category A — Broker-generic / registry-resolved (safer)

| Site | Evidence | Note |
|------|----------|------|
| `broker_config.get_account_broker` | `scripts/broker_config.py:119-126` | Reads **legacy `accounts`** table for broker name |
| `broker_adapter.adapter_for` | `scripts/broker_adapter.py:50-68` | Imports `broker_confirm_<broker>`; no hardcode of paper URL |
| `broker_accounts` rows | DB dump Phase 2 | `broker='alpaca', environment='paper'` for `tradeai_automated` is data, not code |
| Schwab path | `scripts/schwab_transport.place_order` | Separate broker; not Alpaca |

### Category B — Paper-hardcoded (blocker class) — **count ~25 production hotspots**

| Site | file:line | What if live Alpaca account row added + proposal targeted it? |
|------|-----------|----------------------------------------------------------------|
| Equity adapter forces paper host | `alpaca_paper_adapter.py:20,44` `PAPER_BASE_URL`; `self.base_url = PAPER_BASE_URL` | Orders still hit **paper-api** (ignores live row). Init **raises** if `ALPACA_BASE_URL` is bare live host (`:47-49`). |
| Enable flag | `alpaca_paper_adapter.py:41` `ENABLE_ALPACA_PAPER` | Disabled adapter returns empty / no submit. |
| Paper submitter URL gate | `proposal_paper_submitter.py:478-480` | Blocks if base lacks `paper-api`. |
| Options paper host lock | `lib/options_pipeline/alpaca_paper.py` `PAPER_HOST` + `resolve_paper_base_url` | Refuse non-paper host / LIVE-named env (test-enforced). |
| Monitor hard paper URL | `paper_trade_monitor.py:63-68` | Requires `ALPACA_MODE=paper`; returns hardcoded paper host. |
| Protection apply | `apply_paper_protection_adjustment.py:18,93` | `PAPER_BASE` hardcode + `ALPACA_MODE==paper` assert. |
| Canary / verify scripts | `canary_reconcile_test.py:27`, `verify_paper_trade_broker_stops.py:22` | Paper host constants. |
| Secret validator ping | `secret_validators.py:138` | Hits paper account endpoint. |
| UI copy | `optionsCardSemantics.ts:117,124`, `optionsEducation.ts:447` | Labels any alpaca route “Alpaca paper only”. |
| Broker-admin form | `apps/broker-admin/broker_admin.py:48-55` | Adapter = `AlpacaPaperAdapter` only. |
| **Stop manager (weak host discipline)** | `alpaca_stop_manager.py:40` | `base = env.get("ALPACA_BASE_URL", paper default)` — **no host assert, no ALPACA_MODE assert**. If operator set `ALPACA_BASE_URL=https://api.alpaca.markets` + live keys, **POST /v2/orders can leave the box without code change**. |
| **Reconciler (same pattern)** | `alpaca_paper_reconciler.py:74,86` | Same env base URL pattern. |
| Open trade manager | `open_trade_manager.py:427` | Uses adapter `_api_post` (inherits adapter base = paper). |

### Category C — Global-flag coupling (blocker class) — **~32 scripts files + many api_v2 lines; ~52 py files mention ALPACA_MODE**

Representative consumers (not exhaustive of session validators):

| File:line | Behavior if `ALPACA_MODE≠paper` |
|-----------|----------------------------------|
| `live_trading_gate.py:44-48` | Gate fails `alpaca_mode_not_paper` |
| `proposal_paper_submitter.py:368-369,473-474` | Hard block submit |
| `paper_trade_monitor.py:64-68` | RuntimeError |
| `paper_trade_closer.py:154-155` | Blocked |
| `paper_submit_readiness.py:84-86` | Blocker |
| `unified_stop_supervisor.py:33` | assert dies |
| `open_trade_manager.py:47-50` | Blocked |
| `apply_paper_protection_adjustment.py:93` | assert |
| `paper_broker_reconciler.py:57-61` | Blocked |
| `paper_execution_revalidator.py:75-79` | Errors |
| `catalyst_momentum_engine.py:62-63` | Abort proposal gen |
| `api_v2.py:40948-49,41008-09,41808-09,45418-19` | HTTP 400/403 paper-only APIs |
| `config/claude_escalation_allowlist.yaml:72` | Expects paper |
| `config/atm_config.yaml:5` | Documents global flag dependency |

**One-line multi-account impact:** A single process-wide `ALPACA_MODE` cannot simultaneously mean “paper ATM running” and “live Alpaca IRA armable” — flipping toward live **breaks** paper paths; leaving paper **blocks** any design that used the same flag for live Alpaca.

### Category D — Name-as-mode (semantic debt)

| Pattern | Evidence |
|---------|----------|
| Canonical registry key | DB `broker_accounts.account_key=tradeai_automated`, display “Alpaca Paper” |
| Legacy label still everywhere | Strategies/tests: `alpaca_paper`; ATM log still has 3288+1026 rows with `target_account=alpaca_paper` |
| DB display string | `paper_trades.account` values: `tradeai_automated` (137), `ALPACA_PAPER` (27), `TOS_PAPER` (6) |
| Broker column drift | `paper_trades.broker`: empty (91), `alpaca` (51), `alpaca_paper` (28) |
| Defense twin | `defense_execution_caps.json:21,37` `"alpaca_paper": "Alpaca Paper (shadow)"` |
| Options registry flag | `alpaca_paper_enabled` in strategy YAML |
| Interlock self-test names | `live_trading_interlock.py:98-99` tests `alpaca_paper`, `fidelity_401k` — **not** live keys `tradeai_automated` / `fidelity_rollover_ira` |
| Variable name `alpaca_live` | Local dicts in `api_v2.py:40549+` = **live quotes from paper API**, not a live-broker account |

### Category E — Data inconsistency (verified SQL)

```text
paper_trades.account:  tradeai_automated=137, ALPACA_PAPER=27, TOS_PAPER=6
paper_trades.broker:   ''=91, alpaca=51, alpaca_paper=28
paper_trades execution_* triple: alpaca_paper/alpaca/paper=69; tradeai_automated/alpaca/paper=63; blanks present
atm_decision_log: tradeai_automated/alpaca/paper=36317; alpaca_paper/unknown|alpaca = thousands
```

Same economic account appears under multiple string identities.

### Category F — Credentials

| Fact | Evidence |
|------|----------|
| Single key pair names | `.env` keys: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` only (no PERSONAL/IRA slots) |
| Paper base URL env | `ALPACA_PAPER_BASE_URL` present; adapter still hardcodes `PAPER_BASE_URL` for trading base |
| Second/third account keys today? | **No** first-class representation — would overwrite same env names or require new names + code |
| Broker-admin | `ENABLE_ALPACA_PAPER` + key fields → `AlpacaPaperAdapter` only |
| Secrets policy | Do not print values; no-secrets scan on commits; this report contains **no secret values** |

---

## 3. Phase 2 — Registry ground truth

### 3.1 Live dumps

**`broker_accounts` (canonical-ish):**

| account_key | display_name | broker | environment | api_read | api_write | broker_adapter | connection_status |
|-------------|--------------|--------|-------------|---------|---------|----------------|-------------------|
| tradeai_automated | Alpaca Paper | alpaca | paper | t | **t** | scripts.alpaca_paper_adapter | ok |
| schwab_rollover_ira | Schwab Rollover IRA | schwab | live | f | t | scripts.schwab_adapter | no_trading_api |
| schwab_roth_ira | … | schwab | live | f | t | … | no_trading_api |
| schwab_taxable | … | schwab | live | f | t | … | no_trading_api |
| fidelity_rollover_ira | Fidelity Rollover IRA | fidelity | import | f | f | null | no_trading_api |

**`accounts` (legacy — interlock + broker_config source):**

| account_label | broker | mode | auto_execution_capable | routing_adapter | enabled | api_enabled |
|---------------|--------|------|------------------------|-----------------|---------|-------------|
| tradeai_automated | alpaca | paper | t | scripts.alpaca_paper_adapter | t | t |
| schwab_* ×3 | schwab | live | f | null | f | t |
| **fidelity_401k** | fidelity | live | f | null | f | f |

**`account_automation_policies`:**

| account_key | automation_mode | approval_policy | source |
|-------------|-----------------|-----------------|--------|
| tradeai_automated | AUTO_PAPER | MANUAL_APPROVAL_REQUIRED | database |
| schwab_* | MANUAL_REVIEW | PROPOSAL_ONLY | default_seed |
| fidelity_rollover_ira | DISABLED | PROPOSAL_ONLY | default_seed |

### 3.2 Dual-registry verdict

| Issue | Detail |
|-------|--------|
| Fidelity key mismatch | `broker_accounts`: `fidelity_rollover_ira` · `accounts`: `fidelity_401k` |
| Missing cross-rows | Interlock `account_mode()` only SELECTs **`accounts`**. `assert_writable('fidelity_rollover_ira')` → **unknown → REFUSE**. `assert_writable('alpaca_paper')` → **unknown → REFUSE** (label not in `accounts`). |
| Paper alias | Live ATM uses `tradeai_automated`; many pipelines still emit `alpaca_paper` (unknown to interlock → refuse if interlock called). |
| Schwab api_write | `broker_accounts.api_write_enabled=true` for Schwab while `connection_status=no_trading_api` — Stage 2b still requires pilot arm + other gates (`schwab_transport.py:94-99`). |
| YAML still on path | **Yes.** `atm_config_manager` loads `config/atm_config.yaml`; consumers include `atm_auto_approver.py:368+`, `alpaca_paper_adapter.py:29` max positions, `api_v2` risk config, `auto_proposal_generator`. |

### 3.3 Consumer map (who reads what)

| Consumer | Registry | Evidence |
|----------|----------|----------|
| `live_trading_interlock.account_mode` | **`accounts.mode` only** | `live_trading_interlock.py:31-36` |
| `broker_config.get_all_accounts` / `get_account_broker` | **`accounts`** | `broker_config.py:82-97,119-126` |
| ATM default paper | YAML enabled list → env `DEFAULT_PAPER_ACCOUNT` → DB paper row | `broker_config.py:23-72` |
| ATM auto-approver | YAML via `atm_config_manager` + interlock | `atm_auto_approver.py:368+,506` |
| Schwab place_order | **`broker_accounts.api_write_enabled`** | `schwab_transport.py:94-99` |
| Automation mode ceilings | **`account_automation_policies`** joined to `broker_accounts` | DB dump |
| Defense caps labels | **JSON** `defense_execution_caps.json` / capabilities | not DB |

### 3.4 Enums

| Field | Enforced in DB | Enforced in code |
|-------|----------------|------------------|
| `accounts.mode` | CHECK `paper` \| `live` | Interlock branches on these |
| `broker_accounts.environment` | free text (`paper`/`live`/`import` observed) | **Not** read by interlock |
| `automation_mode` | free text (`AUTO_PAPER`, `MANUAL_REVIEW`, `DISABLED`) | Policy consumers |

**Insert protection:** Nothing in DB CHECK prevents `INSERT broker_accounts (broker='alpaca', environment='live', ...)`. Protection is **downstream**: paper adapter host lock, submitter gates, Schwab-only place_order stack, interlock on **legacy** mode.

### 3.5 `live_trading_interlock.assert_writable` (keystone)

**Full logic** (`live_trading_interlock.py:75-89`):

1. `mode = SELECT mode FROM accounts WHERE account_label=%s`
2. `mode is None` → **InterlockRefused** (fail-closed unknown)
3. `mode == 'paper'` → **ALLOW** always
4. `mode == 'live'` → allow only if `paper_validation_policy.live_trading_allowed` is true (`gate_status` → `passed` == that flag). Live criteria (days/trades/WR/PF) are computed but **`passed` is only the master flag** (`:68-71`).

**Live policy row:** `live_trading_allowed=false`, start 2026-05-08, min 183 days, min 100 closed trades.

**Callers (verified):** `queue_router.py:243`, `atm_auto_approver.py:506`, `api_v2.py` multiple (17144+, 36505+, 36551+, 36620+, 36718+), `generate_max_hold_exit_proposals.py`, Schwab validators.

**Scope:** **Per-account label** via legacy `accounts.mode`, not per `broker_accounts.environment`, not per credential slot.  
**Three-Alpaca implication:** Paper row `mode=paper` always writable. Live Alpaca rows would need `mode=live` in **`accounts`** (not only `broker_accounts`). Even then, interlock only answers “dashboard may arm”; it does **not** select API host or keys. Today **`alpaca_paper` is not in `accounts`**, so interlock treats it as unknown.

---

## 4. Phase 3 — Order-submission path census

| # | Path | Gate chain (verified) | Registry / account | Can reach non-paper Alpaca host **today**? |
|---|------|----------------------|--------------------|--------------------------------------------|
| 1 | **Equity paper entry** `AlpacaPaperAdapter.submit_entry` → `POST /v2/orders` | ENABLE_ALPACA_PAPER; init raises on live `ALPACA_BASE_URL`; `self.base_url` **always** paper (`:20,44,567`); RiskGate inside submit | Implicit paper; DB account strings `ALPACA_PAPER`/`tradeai_automated` | **No** (hardcoded paper base). Proof: `:44` assigns `PAPER_BASE_URL`. |
| 2 | **proposal_paper_submitter** → adapter | ALPACA_MODE=paper; LIVE_TRADING_ENABLED false; paper-api in URL; 11 gates; revalidation | Path A | **No** — blocks non-paper URL (`:478-480`). |
| 3 | **queue_router** alpaca branch | Risk gate; `submit_paper` | Resolves broker via `proposal_routing`; alpaca → paper submitter (`queue_router.py:8-9,116-117`) | **No** — only paper submitter. |
| 4 | **Options paper** `lib/options_pipeline/alpaca_paper.py` | Exact host `paper-api.alpaca.markets`; LIMIT; qty=1; confirm; no LIVE env names | options queue | **No** — host resolve refuses live. |
| 5 | **paper_trade_monitor** trail/replace | ALPACA_MODE=paper; hardcoded paper URL | paper_trades | **No**. |
| 6 | **alpaca_stop_manager** OCO/stop POST | Uses `ALPACA_BASE_URL` env **without** host deny | env keys | **YES — config-only risk** if base URL + keys pointed live. Proof: `:40` no assert. |
| 7 | **alpaca_paper_reconciler** | Same env base | env | **Read/write risk** same as stop mgr if URL live. |
| 8 | **apply_paper_protection_adjustment** | ALPACA_MODE assert + PAPER_BASE constant | paper | **No** under assert; base constant paper. |
| 9 | **open_trade_manager** | ALPACA_MODE paper; adapter | paper | **No**. |
| 10 | **Schwab** `schwab_transport.place_order` | taxable pilot list; api_write_enabled; execution_guard; 2FA; readiness | broker_accounts Schwab | **Not Alpaca** — cannot hit Alpaca hosts. |
| 11 | **ATM auto-approver** | interlock + still paper submit endpoint (comment `:496`) | YAML + accounts | Approves into paper path; not live Alpaca. |
| 12 | **Defense intents / 2FA rail** | `autonomous_live_submit_allowed: False` hardcoded `execution_state.py:198`, `brokers/execution_readiness.py:368` | defense caps | Live = ticket/2FA Schwab path; not Alpaca paper auto. |
| 13 | **canary_reconcile_test** | Hardcoded paper BASE | paper keys | Paper only (ops script). |

### P0 headline (config-only live reachability)

> **`alpaca_stop_manager._alpaca_req` (and reconciler peers) will POST to whatever host is in `ALPACA_BASE_URL` with the single global key pair, without the adapter’s live-host RuntimeError.**  
> Equity `submit_entry` is safe; **stop/OCO automation is not host-locked the same way.**

Adding a `broker_accounts` row for live Alpaca alone does **not** rewire equity submit — but **does not** create a safe multi-account model either: keys, flags, and stop paths remain global.

### ATM approve abstraction

- Live name: **`approve_proposal`** in `paper_trade_logger.py:1489` (not `approve_paper_proposal`).  
- ATM still depends on paper submitter + global Alpaca flags (handoff concern still valid for second Alpaca account).

---

## 5. Phase 4 — Flag semantics matrix

| Flag / control | Scope | What it gates (verified) | Multi-account mark |
|----------------|-------|--------------------------|--------------------|
| `ALPACA_MODE` | **Global process** | Dozens of paper scripts + api_v2 paper endpoints; live_trading_gate Gate 1 | **OBSOLETE-IF-MULTI-ACCOUNT** as single scalar; NEEDS-SCOPING → per env |
| `ENABLE_ALPACA_PAPER` | Global | Adapter enabled (`alpaca_paper_adapter.py:41`) | NEEDS-SCOPING (per account enable) |
| `ALPACA_API_KEY` / `SECRET` | Global single pair | All Alpaca HTTP | **NEEDS-SCOPING** → credential slots |
| `ALPACA_BASE_URL` / `ALPACA_PAPER_BASE_URL` | Global | Mixed: adapter ignores for trading base but **stop mgr uses**; options uses paper var | NEEDS-SCOPING; stop mgr REUSABLE only with host allowlist |
| `LIVE_TRADING_ENABLED` | Global (often unset→false) | paper submitter / closer / readiness | Overlaps ALPACA_MODE; NEEDS-SCOPING |
| `BROKER_LIVE_ENABLED` | Global | Schwab pilot unlock (`execution_state`, `schwab_pilot_arm`) | REUSABLE for Schwab; not Alpaca paper |
| `LLM_DISABLE_LIVE_EXECUTION` | Global | Fleet / maturity / comments with ATM | REUSABLE as global kill |
| `paper_validation_policy.live_trading_allowed` | Global DB | Interlock for **any** `accounts.mode=live` | REUSABLE as master live arm; not per-Alpaca-env |
| `live_trading_interlock` | Per **accounts** label | Paper always; live needs flag | REUSABLE pattern; **schema source wrong for broker_accounts-only keys** |
| `autonomous_live_submit_allowed` | Hardcoded False | execution_state / readiness / defense | REUSABLE invariant until redesigned |
| `CANARY_SESSION_DATE` | Schwab canary_gate | Schwab allowlist session | REUSABLE Schwab; N/A Alpaca multi |
| `account_automation_policies.automation_mode` | Per broker_accounts id | AUTO_PAPER vs MANUAL_REVIEW | REUSABLE ceiling model |
| `broker_accounts.api_write_enabled` | Per account | Schwab pilot preconditions | REUSABLE; paper currently **true** |
| Defense `account_capabilities.json` | Per account_key | short/options matrix at render | REUSABLE pattern for IRA vs taxable |

**Conflict precedence (observed):** Paper path fails closed if **any** of ALPACA_MODE≠paper, LIVE_TRADING_ENABLED true, non-paper URL (submitter), ENABLE false. Interlock is **orthogonal** (account mode + policy flag). Schwab uses BROKER_LIVE_ENABLED + pilot arm, not ALPACA_MODE.

---

## 6. Phase 5 — TradingView ingress (inventory only)

| Expectation | Verified |
|-------------|----------|
| No TV execution integration | **Confirmed.** Only external chart link: `TickerLinks.tsx:9` → `tradingview.com/chart`. Lightweight Charts for replay (`TradeReplayChart.tsx`, `ohlc_charts.py`) — not TV broker bridge. |
| Webhooks | `alerting.py` Slack webhook outbound; no TradingView inbound handler found in api_v2 grep sample. |
| Public HTTPS | Server model is Tailscale + localhost gateway. **No public webhook endpoint inventory found for TV alerts** — architectural gap for any TV→order design (not solved here). |
| Parallel ingress surfaces | Telegram callbacks (`telegram_callback_handler.py` `ptapprove` etc.); proposal APIs in `api_v2`; cron pollers; Hermes discovery. Natural future boundary: land as `paper_trade_proposals` / approval queue **before** `queue_router` / Path B promote — **module boundary only**. |

---

## 7. Phase 6 — Account-type assumptions in code

| Location | Nature | Enforced? |
|----------|--------|-----------|
| `config/account_capabilities.json` | `can_short_stock`, `options_level` per schwab_* and `alpaca_paper` | Loaded by `defense_recommendations.py:31`, `api_v2` exposure; comment says **ENFORCED at render** for Defense menus |
| `defense_recommendations.py:622` | Checks taxable short capability | Code gate for recommendation generation |
| `defense_oversight.py:45` | Prompt text: IRAs no shorts; taxable margin; Alpaca Paper shadow | **Advisory / LLM context** |
| ATM / paper RiskGate | Position $ / max concurrent from ATM yaml | Not IRA vs taxable taxonomy for Alpaca |
| Schwab pilot | Taxable-only allowlist in transport stack | Live equity pilot, not Alpaca |

**Hook points for a future Alpaca IRA:** same class as `account_capabilities` + hard gate before any submit factory — today **no** Alpaca live submit factory exists.

**Compliance product rules (margin in IRA, PDT, etc.):** **REQUIRES EXTERNAL RESEARCH** — not asserted here.

---

## 8. FLAG-BACKS (prompt vs live system)

1. Holdings position count **36**, not ~47; value ~$1.26M OK.  
2. `psql -d trade_ai` as `johnclaw` **fails**; app uses `trade_ai` role + DB_* env.  
3. Expected commit `cc67aace` not in recent history; HEAD is `315b646f`.  
4. Dual registry: **fidelity_401k** (`accounts`) vs **fidelity_rollover_ira** (`broker_accounts`).  
5. Interlock self-test still names `alpaca_paper` / `fidelity_401k` — not live canonical keys.  
6. `atm_config.yaml` is **still read** on execution-adjacent paths (not fully decommissioned).  
7. `approve_proposal` exists; `approve_paper_proposal` not the live symbol.  
8. `LIVE_TRADING_ENABLED` not present as `.env` key (defaults false in code).  
9. `broker_accounts` Schwab rows show `api_write_enabled=true` despite `no_trading_api` — pilot stack still gates writes.  
10. Docs from earlier today (`trading-environments.md` etc.) are **hypotheses + proposals**; this file is **live ground truth**. Taxonomy IDs `paca_*` are **not** in DB.  
11. Variable name `alpaca_live` in api_v2 is **not** a live brokerage account mode.

---

## 9. Proposed target taxonomy (**NOT BUILT** — discussion only)

| account_key (proposed) | broker | environment | credential_slot (env names) | automation_mode ceiling | interlock requirement |
|------------------------|--------|-------------|----------------------------|-------------------------|------------------------|
| `tradeai_automated` / `alpaca_paper` (alias) | alpaca | paper | `ALPACA_PAPER_*` | AUTO_PAPER | mode=paper always writable |
| `alpaca_taxable_live` | alpaca | live | `ALPACA_TAXABLE_*` | DISABLED until armed | mode=live + live_trading_allowed + host allowlist + separate adapter |
| `alpaca_ira_live` | alpaca | live | `ALPACA_IRA_*` | DISABLED | same + capabilities short/options false as configured |
| `schwab_taxable` | schwab | live | Schwab OAuth | MANUAL_REVIEW / pilot | existing Stage 2b |
| `schwab_rollover_ira` | schwab | live | Schwab OAuth | MANUAL_REVIEW | existing |
| `schwab_roth_ira` | schwab | live | Schwab OAuth | MANUAL_REVIEW | existing |
| `fidelity_rollover_ira` | fidelity | import/live-manual | none/API limited | DISABLED | FA manual |

**Must unify:** one registry as interlock source; retire dual fidelity keys; never share one global `ALPACA_MODE` across paper+live.

---

## 10. Sorted gap list

### P0 — safety-structural

| Gap | Evidence | Status |
|-----|----------|--------|
| Stop/reconcile paths honor `ALPACA_BASE_URL` without live-host refuse | was `alpaca_stop_manager.py:40`; reconciler `:74,86` | **REMEDIATED 2026-07-21** — exact host + `ALPACA_MODE=paper` bouncer (`require_paper_trading_base`); tests `tests/test_alpaca_paper_host_lock.py`. Commit: `6085874df70b64b757c2caac746dcc42d839f254` |
| Single global API key pair for all Alpaca | `.env` key names only | open (taxonomy redesign) |
| Global `ALPACA_MODE` couples all paper automation | 32+ scripts; api_v2 | open |
| Interlock ignores `broker_accounts.environment`; unknown labels refuse | `live_trading_interlock.py:31-36,75-81` | open |
| Dual registry fidelity/paper aliases | DB dumps §3.1 | open |

### P1 — semantic debt

| Gap | Evidence |
|-----|----------|
| `tradeai_automated` vs `alpaca_paper` vs `ALPACA_PAPER` strings | paper_trades + atm_decision_log |
| UI/options always “Alpaca paper only” | optionsCardSemantics |
| `atm_config.yaml` still execution-adjacent | atm_config_manager consumers |
| Defense caps label `alpaca_paper` only | defense_execution_caps.json |
| Interlock CLI self-test stale account names | interlock.py:98-99 |

### P2 — cosmetic / docs

| Gap | Evidence |
|-----|----------|
| broker column empty on many paper_trades | SQL §E |
| Prompt/docs position count ~47 lag | holdings=36 |
| Historical docs still say “only paper” without multi-account registry design | prior broker docs |

---

## 11. Direct answer to the mission question

> **Where does the system assume alpaca≡paper, and can the current model safely represent three Alpaca accounts?**

**Assumes alpaca≡paper:** adapter class/name, ENABLE_ALPACA_PAPER, hardcoded paper hosts (equity submit/monitor/options), ALPACA_MODE process flag, UI labels, strategy flags `alpaca_paper_enabled`, ATM AUTO_PAPER row, single key pair.

**Can the current model safely represent three accounts without that assumption?**  
**No.**  
- Registry **can store** extra rows (no DB forbid on `broker=alpaca, environment=live`).  
- **Execution cannot safely distinguish** paper vs live taxable vs IRA: one key pair, one MODE flag, paper-only adapter, stop path that trusts BASE_URL, interlock keyed off a **different** table than `broker_accounts`, and no per-account credential slot.  
- Safest property today: **equity Path A cannot be pointed at live by registry alone** (adapter hardcodes paper). Weakest: **stop/OCO automation + env URL**.

---

## 12. End-of-session handoff fields

| Field | Value |
|-------|--------|
| HEAD | `315b646f701c9c6730df54bf9bc106975d4a51ad` |
| Holdings | **$1,259,636.03** · **36** positions |
| B/C blocker findings | **B ≈ 25 production hotspots** (incl. 1 config-only live-host risk); **C ≈ 32 script files + api_v2** on `ALPACA_MODE` |
| Single most dangerous finding | **`alpaca_stop_manager` (and reconciler) will POST to any `ALPACA_BASE_URL` with the sole global keys — unlike the equity adapter, which hardcodes paper and refuses live hosts.** |
| Findings path | `docs/_findings/alpaca_taxonomy_audit_2026-07-21.md` |

*No migrations, no .env edits, no code changes, no order dry-runs against brokers.*

---

## 13. Addendum (2026-07-21 post-handoff clarifications)

### Docs format / Drive readability

- **Repo convention going forward:** all project documentation is **Markdown (`.md`)** under `docs/`.
- **Drive sync** (`scripts/sync-docs-to-drive.sh` ~L182): `*.md` uploads **raw** (`CONVERT_FLAG=""`) intentionally for byte parity with git (v1.2.3 P0-2 — Docs conversion corrupted punctuation/placeholders). Mime is therefore **not** `application/vnd.google-apps.document`, so some fetch tools that only open Google Docs cannot read the Drive copy.
- **Workaround for chat agents:** paste or attach the `.md` from the repo (or this chat). Do not rely on Drive “Open as Google Doc” conversion unless an operator deliberately re-uploads with convert.

### `cc67aace` / Defense Desk v9 vs audit HEAD

| Fact | Value |
|------|--------|
| Audit ran at | `315b646f701c9c6730cf54bf9bc106975d4a51ad` |
| `cc67aace` | **Exists on this branch:** `cc67aace defense-v9: the adjudication layer — promote console, seat league, governance, governed tuning, weekly loop` — not in `git log -15` tip window (older ancestor) |
| Defense execution rail at HEAD | **Present** in tree: `scripts/defense_execution.py`, `defense_adjudication.py`, `execution_state.py` (`autonomous_live_submit_allowed: False`), options lifecycle tickets |

**Phase 3 row 12** already cites Defense intents / 2FA rail and `autonomous_live_submit_allowed=False`. It is a **census line**, not a full Defense Desk order-path deep dive. A design session should expand Phase 3 with: `defense_order_intents` → approvals UI → 2FA → ticket vs paper ATM (same split-brain: per-account automation policy vs global/submit endpoint). That expansion is **documentation depth**, not “audit ran pre–Defense Desk” — the code was already in the tree at `315b646f`.

### Corroboration (external chat notes)

- Interlock-on-`accounts.mode` is **original June design**, not accidental drift after `broker_accounts`.
- AUTO_LIVE / paper-account edge cases may be enforced in **endpoint handlers** as well as `assert_writable` — multi-account design must centralize both layers.
- ATM reads per-account `automation_mode`; submission still global `ALPACA_MODE` + paper adapter — confirmed seam.

### P0 row 1 REMEDIATED (2026-07-21 host-lock)

- **`scripts/alpaca_stop_manager.py`**: `require_paper_trading_base()` — exact hostname `paper-api.alpaca.markets` via `urllib.parse`, `ALPACA_MODE==paper`, Telegram alert (bypass_router) then `RuntimeError`; called from `_alpaca_req` before any HTTP.
- **`scripts/alpaca_paper_reconciler.py`**: same bouncer on `get_alpaca_positions` / `get_alpaca_orders`.
- **Tests:** `tests/test_alpaca_paper_host_lock.py` (live URL, spoof suffix, mode=live, unset→paper default, no urlopen on block).
- **Not in scope / already gated:** `alpaca_paper_adapter` (unchanged), `proposal_paper_submitter` (paper-api substring gate), options pipeline (exact host), `proposal_execution_readiness` (label only, no HTTP).
- **Holdings post-fix:** unchanged ($~1.26M / 36) — no broker calls.
