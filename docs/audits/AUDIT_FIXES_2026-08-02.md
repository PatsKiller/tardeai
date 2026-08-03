# Audit Fixes Implemented — 2026-08-02

**Scope:** Non–paper-execute fixes from `PLATFORM_AUTONOMY_AUDIT_2026-08-02.md`  
**Tree:** `tradeai-wt-cursor-guardrails`  
**Excluded (per operator):** paper execute funnel / ATM fill / ready_count war room  
**Dry-test:** `scripts/dry_test_audit_fixes_20260802.py` → **35/35 PASS**

---

## What shipped

### 1. DeepSeek process registry cutover

| File | Change |
|------|--------|
| `config/llm_process_registry.json` | **v3** — `default_allowed_lanes`, `lane_policy_map`, explicit DeepSeek lanes on Maria / CIO / cloud_review / portfolio reports / Hermes external |
| `scripts/lib/llm_consumption.py` | Seeds **`allowed_lanes`** into `llm_process_config`; default lane list includes DeepSeek; `gate_and_generate` defaults to `deepseek-flash` with allowed-lane failover; `unregistered` **manual** (no automated free-for-all); `reload_registry()` helper |

**Key process modes after seed:**

| process_id | mode | allowed_lanes |
|------------|------|---------------|
| watchlist_maria_priority | automated | deepseek-flash, grok, chatgpt |
| watchlist_cio_synthesis | automated | deepseek-v4, deepseek-flash, grok, chatgpt |
| cloud_review | automated | deepseek-flash, grok, chatgpt |
| portfolio_weekly_report | automated | deepseek-flash, grok, chatgpt |
| portfolio_monthly_report | automated | deepseek-v4, deepseek-flash, grok, chatgpt |
| oauth_lane_keepalive | automated | grok, chatgpt only |
| unregistered | **manual** | all lanes |

Dry-test proved `should_call(maria, deepseek-flash)` → allow under automated mode, and unregistered blocked without `manual_trigger`.

### 2. Watch quality gate — consequential intake

| File | Change |
|------|--------|
| `config/watch_quality_gate.json` | `enforce_intake: true`, exempt sources list, quarantine metadata |
| `scripts/lib/watch_quality_intake.py` | **NEW** — `admit_source()`, `should_insert_ai_discovered()`, cached low-efficacy set |
| `scripts/finviz_screener_runner.py` | Blocks new `ai_discovered` **active** inserts when source fails gate (still classifies tickers) |
| `scripts/api_v2.py` `_watch_quality_gate` | Loads full cfg incl. enforce flag; docstring updated |

**Live dry-test note (2026-08-02):** 90d median α for `ai_discovered` was **−1.07** (n=765) → above floor (−2.0) → **admit=True** today. Gate is armed; blocks when rolling median drops below floor. All-time α can still be worse — Sunday reconciler drives the 90d window.

### 3. Metric strip STALE truth + remediation CTAs

| File | Change |
|------|--------|
| `apps/.../lib/homeLabels.ts` | `lastSessionDay()`, market-aware `isScanStale` (weekend ≠ false STALE), `isJournalStale` (trading-day age, default 5 sessions) |
| `apps/.../components/MetricStrip.tsx` | **↻ RUN SCAN** / **↻ REFRESH JOURNAL** / **Import →** when stale; posts to `/api/v2/trade-ai/run` or `/api/run-pipeline` (fallback legacy) |

Does **not** invent journal fills — operator may still need Journal → Import for broker CSV.

### 4. Agents page honesty

| File | Change |
|------|--------|
| `scripts/api_v2.py` `_agents_summary` | `hold_rate`, `directional_rate`, `is_hold_factory`, `honesty` block, `catalog_states` from maturity catalog |
| `apps/.../pages/AgentsHub.tsx` | Amber banner: advisory-only / SHADOW; HOLD-factory callout; Hold % column; catalog state chip |

### 5. API path aliases (404 smoke fixes)

Registered in `ROUTES`:

| Alias | Targets |
|-------|---------|
| `/api/v2/health/snapshot` | health dashboard |
| `/api/v2/consumption/summary` | consumption overview |
| `/api/v2/system/llm` | llm health |
| `/api/v2/agents/maturity` | agents summary + honesty |
| `/api/v2/agent-runtime/status` | same maturity/honesty envelope |
| `/api/v2/watch/scoreboard` | quality gate + finds track record |
| `/api/v2/research-intelligence/desk` | research intelligence feed |

**Note:** Live `:7777` process is still the ad-hoc rebuild tree until redeployed. Aliases are in guardrails `api_v2.py` — hot-reload only if that module is what the running server loads. Prefer restart from this tree or release-cut that includes these commits.

---

## Explicitly not done (by request)

- Paper proposal ready_count / ATM throughput / enrichment SLA war room  
- Live Schwab autonomy / 2FA changes  
- MAIN weight unlock / graft_forbidden reverse  
- Defense SHADOW promote exit  
- Multi-tree systemd single-spine deploy (ops action — document only)

---

## Dry-test how to re-run

```bash
cd /home/johnclaw/tradeai-wt-cursor-guardrails
export PYTHONPATH=scripts
# with DB credentials available (e.g. source .env)
python3 scripts/dry_test_audit_fixes_20260802.py
# or:
# /path/to/.venv/bin/python scripts/dry_test_audit_fixes_20260802.py
```

Evidence: `docs/audits/platform-autonomy-2026-08-02/evidence/dry_test_results.json`

---

## Deploy checklist (operator)

1. Ensure `config/llm_process_registry.json` v3 is on the tree that serves `:7777`.  
2. Restart portfolio-server (or rely on first `ensure_schema()` after import of llm_consumption) so `llm_process_config.allowed_lanes` re-seeds.  
3. Rebuild/serve CC v3 for MetricStrip + AgentsHub.  
4. Confirm Consumption hub shows DeepSeek Flash calls after next Maria/CIO automated run.  
5. Optional: set `enforce_intake: false` in `watch_quality_gate.json` if discovery freeze is too aggressive after a bad α window.

---

## Residual risks

| Risk | Mitigation |
|------|------------|
| Live server tree ≠ guardrails | Redeploy; dry-test only proves this worktree + shared DB seed |
| DeepSeek spend rises | daily_soft_cap on Maria (80) / CIO (40); monitor Consumption |
| ai_discovered not blocked today | α above floor in 90d window — gate still active for future dips |
| Metric strip journal still stale after CTA | Needs broker journal import — button cannot fabricate closes |
