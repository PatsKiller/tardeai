# Stabilization Session — 2026-06-22

**Operator request:** Track 1 — stabilize execution (agent backlog, screener errors, SIEM/stop alerts, LLM queue).
**Session:** Grok CLI · ms01-openclaw · branch `main` @ `e868d7f5`
**Safety:** Paper-only throughout; no broker writes, no strategy YAML changes, no cron mutations.

---

## Summary

| Area | Before | Action | After / status |
|------|--------|--------|----------------|
| Health score | 64 (unhealthy) | Triage + drain batches | 64 — drains still running; expected ~75–80 when complete |
| Agent jobs >2h | 37–40 queued | Background `process_watchlist_agent_jobs --limit 40` | 36 queued >2h (auto-intake adds faster than drain) |
| Screener log errors | 123 lines (10:00 run) | Verified fix `53636262` (upsert on symbol+run_date) | Next orchestrator run should be clean |
| SIEM P0/P1 (24h) | 7 alerts | Acked 4 resolved (fused_signals + DB SSL transient) | 3 unacked: KTOS/KBR stop-outs, BIRD advisory |
| Stop alerts | 2 (KTOS, KBR) | Refreshed `stop_lifecycle_monitor` | Legitimate fresh stop-outs — operator review required |
| Overnight LLM queue | 1,943 pending | Daytime catch-up `--limit 15 --hard-stop ""` | 1,941 pending, 1 running; **root cause: cron RETIRED** |
| `fused_signals` | Stale at midnight | Verified live | Fresh as of 11:03 ET (signal_fusion cron healthy) |

---

## Root Causes

### 1. Agent job backlog (not stuck processing)
- `watchlist_agent_jobs`: 0 stuck in `processing`; throughput **244/24h** (healthy).
- Health agent flags **queued >2h** (38–40), not stuck workers.
- Cron limits (`limit 5–10`) + auto-queue on new symbols outpace drain on weekends/low-limit windows.

### 2. Screener duplicate-key spam (fixed)
- `trade_ai_orchestrator.py` + `continuous_runner.py` INSERTed into `trade_ai_scans` without conflict handling.
- UNIQUE index `idx_trade_ai_scans_symbol_rundate` caused silent row drops; logged as errors in `screener_pm.log`.
- **Fix:** commit `53636262` — `ON CONFLICT (symbol, run_date) DO UPDATE`.
- 10:00 run completed (1002 rows, 1 GO: CRMT) despite errors.

### 3. Overnight LLM queue not draining
- `deep_overnight_llm_queue`: **1,941 pending**, 1,588 done, 254 failed.
- Nightly drain cron is **PHASE102-RETIRED**:
  ```
  # PHASE102-RETIRED 0 23 * * * ... run_deep_overnight_llm_window.sh
  ```
- Jobs accumulate with no scheduled drain → backlog grows indefinitely.
- **Operator decision required:** re-enable `run_deep_overnight_llm_window.sh` at 23:00 ET.

### 4. SIEM alerts triaged

| ID | Severity | Event | Disposition |
|----|----------|-------|-------------|
| 1051, 1052 | urgent | `fused_signals` stale at midnight | **Acked** — table fresh by 11:03 |
| 3391, 3392 | critical | DB SSL connection drop 10:20 | **Acked** — transient; DB healthy |
| 3386 | urgent | KTOS stop FILLED @ schwab_taxable | **Open** — real stop-out; operator review |
| 3394 | urgent | KBR stop FILLED @ schwab_taxable | **Open** — real stop-out; operator review |
| 3384 | urgent | BIRD paper trade large gain, no take-profit | **Open** — advisory |

### 5. Pipeline failure (transient)
- `process_watchlist_agent_jobs` failed at 10:00: `SSL connection has been closed unexpectedly`.
- Recovered; jobs resumed 11:15 (10/10 completed). No recurrence.

---

## Actions Taken (this session)

1. Acknowledged resolved `alert_events` IDs 1051, 1052, 3391, 3392.
2. Ran `stop_lifecycle_monitor.py` — 8 live stops; 2 alert (KTOS/KBR filled today).
3. Started background agent drain: `process_watchlist_agent_jobs.py --limit 40` → `logs/watchlist_agent_jobs_stabilize.log`.
4. Started LLM catch-up: `run_deep_overnight_llm_queue.py --limit 15 --time-budget-min 25 --hard-stop ""` → `logs/deep_llm_catchup.log`.
5. Regenerated `docs/project/SYSTEM_FACTS_LATEST.md` and `docs/project/STATE_OF_REPO_LATEST.md`.

---

## Operator Action Items (unchanged)

1. **Review KTOS + KBR in Schwab** — stops filled 2026-06-22; confirm positions flat.
2. **Review BIRD paper trade #80** — large unrealized gain, no take-profit.
3. **Re-enable overnight LLM cron** — or backlog will continue growing (~100 jobs/night in, 0 out).
4. **P0 API key rotation** (OpenAI + OpenClaw) — still open per `DOCUMENTATION_INDEX.md`; blocks Stage 2a canary.

---

## Ownership

| Component | Script / table |
|-----------|----------------|
| Agent queue | `scripts/process_watchlist_agent_jobs.py`, `watchlist_agent_jobs` |
| Screener persist | `scripts/trade_ai_orchestrator.py`, `trade_ai_scans` |
| Overnight LLM | `scripts/run_deep_overnight_llm_window.sh`, `deep_overnight_llm_queue` |
| Health scoring | `scripts/health_agent.py`, `health_agent_snapshots` |
| Stop lifecycle | `scripts/stop_lifecycle_monitor.py`, `stop_lifecycle` |
| SIEM | `alert_events`, `scripts/stop_health_check.py` |
| Signal fusion | `scripts/signal_fusion.py`, `fused_signals` |