# Sunday Night Audit Fixes (2026-05-25)

Status:      HISTORICAL
as_of:       2026-05-23T18:21:30-04:00
Measured at: efcc51365 / not measured

Five findings from visual audit of 65 dashboard screenshots (audit_7777_20260523_1737.tgz).

## B-1: Agent Worker Stuck (BLOCKING → RESOLVED)

**Evidence:** agent_pipeline.png: 5 jobs queued 14h, 0 results 24h, LLM budget $0.00.
**Root cause:** Local LLM (qwen3:14b on Intel Arc B50) became unresponsive — stuck processing old requests. Cron fired every 10 min but the `timeout 12m` killed each attempt. No worker process was running at diagnosis time. Lock file existed but was not held.
**Action:** LLM recovered after stuck requests cleared. Manual single-job test succeeded. Background batch started — 5 completed, 148 remaining. Cron will continue draining at */10 weekends, */15 weekdays.
**Verification:** `tail logs/watchlist_agent_jobs.log` shows active processing at 2026-05-23 18:20.
**Recommendation:** Add LLM health check to pipeline_health_master. If Ollama /api/ps shows model loaded but /api/chat hangs >30s, restart Ollama.

## B-2: Risk Page TRIGGERED=0 Despite Stops Breached (BLOCKING → FIXED)

**Evidence:** risk.png: RTX -2.2%, LHX -3.3%, LMT -10.6%, NOC -9.8% all labeled "Danger" but TRIGGERED tile shows 0.
**Root cause:** `risk_management.json` has `status=TRIGGERED` but `triggered=None` (never set). API line 2560 defaulted `triggered` to `False`. The `distance_pct` correctly shows negative values (price below stop).
**Fix:** Changed `triggered` field to derive from actual data: `True` when `distance_pct < 0`. Now correctly shows 7 triggered positions.
**Note:** These are Schwab taxable positions with stops set in risk_management.json but no broker stop orders (no `stop_order_id`). The stops are tracked positions, not GTC broker orders. The risk page now correctly flags them.

## B-3: 4 ATM Proposals Stale-Blocked (IMPORTANT → ACCEPTED)

**Evidence:** proposal_alerts.png: ARM BLOCKED_SPREAD, MUD BLOCKED_NO_VOLUME, SHMD BLOCKED_NO_VOLUME, BCS NEEDS_REBUILD.
**Decision:** Option B — accept stale queue, let burn-in produce fresh proposals. First-day metrics should reflect autonomous operation, not manually-nursed overnight queue.
**Reasoning:** ATM will generate new proposals during market hours via */15 cron. Stale proposals expire naturally. Pre-market continuous_runner fires at 09:05 ET.

## C-1: Per-Agent Dashboard Last Run Stale (COSMETIC → FIXED)

**Evidence:** agent_dashboard_alex.png: "stale - Last run: 13d ago", "Lifetime Analyses: 25". Actual: 732 cio_decisions, latest 2026-05-20.
**Root cause:** Agent-dashboard endpoint only queried `watchlist_agent_results` for stats. Alex/Aegis write to home tables (cio_decisions, aegis_portfolio_briefs) not watchlist_agent_results.
**Fix:** Added home table enrichment to agent-dashboard endpoint (same pattern as agents/summary fix in commit 5bae51d). Alex now shows 732 analyses, last run 2026-05-20.

## C-2: "Data is 34h old" Banner on Weekend (COSMETIC → FIXED)

**Evidence:** Banner on all 30+ pages. Pipeline shows 30/31 healthy, last run Saturday 5:11 PM. Banner reads `_freshness.json` (Friday 07:12) not pipeline_runs.
**Root cause:** Command API `freshness.last_refresh` reads from `_freshness.json` which only updates on full daily pipeline runs. Weekends don't run the full pipeline, but individual stages run fine.
**Fix:** `_compute_freshness()` now checks both `_freshness.json` and `MAX(run_completed_at) FROM pipeline_runs`, uses the more recent. Weekend + within 48h = status "fresh". Banner suppressed on weekends with recent pipeline activity.
