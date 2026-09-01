# Phase 208K — Operator Answer: Why Retired, Is It Safe (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T11:34:47-04:00
Measured at: efcc51365 / not measured

**Why were the old agents retired?** The Trade-AI-gated **sidecar** Hermes install (v0.15.2, its own
gateway + `.hermes` runtime + venv) was superseded by a **global** Hermes install (v0.16.0, `~/.local/bin/
hermes`) with named profiles (default/tradeai/tradeai12b/dev/serverops). The sidecar's always-on gateway
(`--accept-hooks`) was also an unwanted autonomous surface. So the sidecar was rename-retired and its
gateway stopped/disabled.

**Are retired artifacts needed?** No active runtime needs them. Kept only as rollback/audit evidence.

**Do active Hermes jobs depend on them?** No — every scheduled job runs `.venv/bin/python scripts/hermes_*.py`
(208D). Zero jobs call retired wrappers or depend on the retired gateway.

**Does keeping them retired break anything?** No (208F proof). Gateway disabled; all 9 fleet timers succeed.

**Which agents are live now?**
- Global profiles (chat): default, tradeai, tradeai12b (dev/serverops future).
- Research fleet (workflow, /v3/hermes): Coordinator, Source Discovery, Librarian, Embedding Curator,
  Promotion Review, Backlog Manager, Autonomous Research — live via systemd timers, 476 writes/24h.

**Which SOULs are active?** 5 (default/tradeai/tradeai12b/dev/serverops) — all safe (208C: no live-trading,
no broker-mutation, no retired refs).

**Which jobs run them?** 9 hermes-* user timers + the coordinator cron (*/15). All last-result = success.

**Still risky / unknown?** serverops dangerous tools (unconfigured), stale coordinator kill-switch path,
dev's future cloud connection — all flagged in the risk register (208J), none P0.

**What should NOT be touched?** The retired dirs (rollback), the disabled gateway (keep disabled),
tradeai/tradeai12b tool policy (0 tools), trading/proposal/protection/broker code, live trading (zero).

**What to look at in v3:** System → Hermes (profiles, SOUL provenance, legacy read-only inventory) and
/v3/hermes (live research graph + SearXNG health).
