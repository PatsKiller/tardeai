# Trade AI v12 — Operations Runbook

> **Audience:** the operator. This is the top-level index of how to run the system day to day.
>
> **Deeper runbooks — link, don't duplicate:**
> - [docs/operator/ATM_RUNBOOK.md](docs/operator/ATM_RUNBOOK.md) — Automated Trade Mode: control surfaces,
>   kill switches, morning/EOD/weekly checklists, troubleshooting, key file locations.
> - [docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md](docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md) — LLM fleet model
>   policy, per-script model mapping, verification steps, stop conditions.
> - [docs/runbooks/DB_HANG_PREVENTION.md](docs/runbooks/DB_HANG_PREVENTION.md) — DB-induced dashboard hang:
>   prevention rules + recovery queries.
> - [docs/runbooks/protective-stop-integration-2026-06-30.md](docs/runbooks/protective-stop-integration-2026-06-30.md)
>   — live protective-stop path, evidence-bound 2FA approvals, duplicate-stop guard.
> - [docs/infra/POST_REBOOT_RECOVERY_2026_07_02.md](docs/infra/POST_REBOOT_RECOVERY_2026_07_02.md) — full
>   post-reboot recovery sequence.
>
> **Architecture context:** [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Daily operator workflow

**Morning (market days).** Follow the Morning Checklist in
[docs/operator/ATM_RUNBOOK.md](docs/operator/ATM_RUNBOOK.md) (~5 min). In the Command Center (`/v3`):

1. **Health hub** (`/v3/health`) — overall Health Score and category breakdown; Coder Dispatch ledger,
   queue health, data-source health.
2. **Trading hub → Proposals tab** (`/v3/trading?tab=Proposals`) — the approvals queue for paper
   proposals (data: `/api/v2/paper-proposals`). ATM auto-approves when active; anything PENDING here is
   waiting on you or on gates.
3. **Trading hub → ATM Controls tab** — automated-approval mode, per-account settings, kill switches.
4. **Trading hub → Broker Orders tab** — live-broker order intents and their per-order approvals.
   Telegram approval messages deep-link here (`/v3/trading?tab=Broker+Orders&intent=<id>`).

**End of day / weekly.** EOD (3 min) and Sunday Weekly Review (15 min) checklists are in the ATM runbook.

**Approvals rule of thumb:** per-order approval for anything live-bound is satisfiable via **either**
channel (web typed-ticker **or** Telegram code, `REQUIRED_CHANNELS=1`), single-use, TTL-bound to one
intent. Missing 2FA on a live submit is a hard block — nothing reaches Schwab without it.

## 2. Interpreting the Hermes closed-loop panel

The panel lives in the **Hermes hub** (`/v3/hermes`, component `HermesClosedLoopPanel`). It is
advisory-only — nothing on it touches orders or gates.

- **Hit-rate trends** — Promotions / Research / Trades outcome hit-rates over time. The design law is
  "outcome yield outranks throughput yield": a busy Hermes with a falling hit-rate is a problem, not
  progress.
- **Gate states** — `promote_eligible` (a symbol/tag has earned tier promotion), `demote_pressure` /
  `pause_eligible` (persistent underperformance), `promote_blocked_bad_tag` (blocked by tag-level
  outcomes). The Scope Governor is the sole owner of `scope_tier` (Hot/Warm/Cold = S0+S1 / S2 / S3);
  capital-exposed S0 positions are never auto-demoted by the bus.
- **Alerts** — `hit_rate_declining`, `efficiency_declining`, `scope_creep`, `stop_quality_divergence`.
  These come from `config/hermes_alerts.yaml` and are deliberately conservative and non-spammy.
- **Maturity model** — composite 0–100 (`maturity-v2`) across
  `outcome_yield / scope_discipline / stop_quality / feedback_loop / research_actionability`.
- **Threshold proposals** — adaptive-threshold changes surface as proposals requiring human approval
  (`config/hermes_thresholds.yaml`, `review_mode: true`). Nothing self-activates.
- The loop refreshes nightly: 02:50 outcome grader → 03:05 tag engine → 03:25 feedback agent (writes
  `state/hermes/outcome_bus.json`) → 03:35 outcome learning.

## 3. Health agent score & alerts

`scripts/health_agent.py` produces a 0–100 score across six categories (data quality, execution health,
intelligence quality, risk protection, retirement planning, pipeline freshness). Snapshots go to the
`health_agent_snapshots` table and `data/portfolios/state/health_agent_status.json`; the v3 Health hub
renders them.

**Telegram throttle** (so an unchanged DEGRADED doesn't re-alert every 30-min run). An alert fires only on:

1. **status change**, or
2. **score drop ≥ 5 points** (`realert_on_score_drop`), or
3. **6-hour heartbeat** (`min_realert_minutes` = 360) while still unhealthy/degraded.

If Telegram has gone quiet, that means "no change" — confirm via the Health hub, not by assuming health.

## 4. Common troubleshooting

### Stale data on cards

- The v4 card **STALE** badge uses a **market-aware 1-hour clock** (`marketAwareStale` in
  `apps/command-center-v3/src/lib/watchlistCardV4.ts`): data ≤1h old is never stale; older data is stale
  only if the market has actually moved since enrichment. A Friday-evening enrichment stays fresh all
  weekend and re-arms Monday 09:30 — weekend STALE-free cards are correct behavior, not a bug.
- Server-side pipeline freshness (`scripts/pipeline_freshness_monitor.py`) adds **market-closure grace**:
  thresholds extend by the number of consecutive non-trading days (e.g. Saturday after a Friday holiday →
  +2 days). Don't chase "stale pipeline" alerts that vanish once grace is accounted for.
- To force-refresh one symbol: the card's **Refresh** button ("Refresh Finviz + re-queue synthesis")
  refreshes Finviz data and re-queues the CIO synthesis. A card showing "No CIO synthesis yet" also fixes
  itself this way; a holdings change auto-queues a synthesis refresh.

### Missing DD / prospectus reports

- **On demand:** Reports hub (`/v3/reports`) → analyst panels (`ProspectusBatchPanel`,
  `AnalystReportsPanel`) → **Generate** buttons, which POST to `/api/v2/reports/analyst/generate`
  ("Generate N Holdings" batch, "Generate one", "Force regenerate all"). Eligibility and history come
  from `/api/v2/reports/analyst/eligible` and `/api/v2/reports/analyst/registry`.
- **Scheduled:** the checked-in crontab (`crontab_backup.txt`) runs **Sun 21:15**
  `generate_analyst_reports_autonomous.py --mode weekly` (under flock), and a monthly full refresh on
  day 1 at 21:30 with `REPORT_CLAUDE_OVERSIGHT=1`.
- Caveat: `scripts/generate_analyst_holding_prospectus_weekly.py` exists and documents the same
  Sunday-21:15 slot in its docstring, but it is **not** wired into the checked-in crontab — verify against
  the live `crontab -l` before assuming it runs.

### Sizing looks wrong

- Sizing is **cash-based, never total equity**: `GET /api/v2/proposal-accounts` returns each account's
  `sizing_base` (+ label `cash` or `buying_power`) and the policy block.
- **Retirement accounts (rollover/roth/ira/401k) are cash-only — no margin, no buying-power fallback**
  (`account_policy.sizing_cash_base`).
- Caps: **max risk 2%** of sizing base (`max_risk_pct: 2`; the frontend gate blocks above 2%);
  deployment/concentration cap defaults to **20% of cash per position** (`max_deploy_pct_of_cash`,
  env-overridable), optionally tightened by a per-account `max_position_pct_of_equity` from
  `account_automation_policies`.
- Mind the equity-vs-cash semantics of that per-account cap: mis-applying an equity-% cap to cash once
  capped every card at ~$6.6k (2026-07-03).
- If a card shows no size: check `sizing_ready` / `balances_status` in `/api/v2/proposal-accounts` —
  stale broker balances make sizing fail closed, not guess.

### Dashboard hung / port 7777 alive but blank

See [docs/runbooks/DB_HANG_PREVENTION.md](docs/runbooks/DB_HANG_PREVENTION.md). Fast recovery — kill
idle-in-transaction backends older than 120s:

```sql
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE state = 'idle in transaction' AND now() - state_change > interval '120 seconds';
```

Then restart the server if needed (§6).

## 5. Running backfills, audits, and crons safely

1. **Single-flight everything.** Wrap any manually-run job the same way cron does:

   ```bash
   bash scripts/safe_flock.sh /tmp/<component>.lock <command> [args...]
   ```

   It refuses to double-run (logs `lock_skip` and exits 0 if the prior PID is alive), cleans stale PIDs
   safely, preserves the child exit code, and writes skip/stale/complete events to
   `logs/safe_flock_events.jsonl` — no silent skips.
2. **Gate background LLM work behind the GPU guard.** Before any TIER-3 background/research LLM job, call
   `scripts/llm_priority_guard.sh`: it returns 0 (proceed) outside the market-critical window and 1
   (defer) during **06:00–11:59 ET on trading days**, reserving the single local GPU for
   scalp/proposal/validation work. Override only deliberately with `LLM_GUARD_FORCE=1`.
3. **Never hold a DB transaction through slow work.** Per
   [docs/runbooks/DB_HANG_PREVENTION.md](docs/runbooks/DB_HANG_PREVENTION.md):
   *"Don't hold a DB transaction open across a slow LLM/network call. Read → commit → process → reopen to
   write."* Idle-in-transaction sessions are killed at **120s**; `lock_timeout='3s'` makes lock-waiters
   fail fast instead of queueing the table behind a blocked DDL.
4. **Crontab hygiene.** There is no `cron/` directory; the checked-in reference is `crontab_backup.txt`
   (plus proposal/rollback snapshots). The live schedule is `crontab -l` on the box — treat the repo files
   as snapshots, and keep flock + priority-guard wrappers when adding lines
   (`scripts/apply_llm_priority_guard_to_crontab.py` helps).
5. **Runtime state stays out of git.** `data/`, `state/`, `/reports/`, and
   `data/runtime/*_latest.json` / `*_history.json` are gitignored — never re-commit them after a backfill.

## 6. Server restart

**Hot-reload is NOT a restart.** The server hot-reloads only `scripts/api_v2.py` and
`scripts/reports_portal.py` (mtime-gated, non-blocking). Edits to any other module —
`portfolio_loader.py`, `account_policy.py`, broker code, `inference_api`, the server itself — require a
full restart.

Restart sequence (user-scoped unit; from
[docs/infra/POST_REBOOT_RECOVERY_2026_07_02.md](docs/infra/POST_REBOOT_RECOVERY_2026_07_02.md)):

```bash
systemctl --user stop portfolio-server.service
# if an orphan listener survives (PPID=1, :7777 still up):
pid=$(ss -tlnp | grep 7777 | grep -oP 'pid=\K[0-9]+' | head -1)
[ -n "$pid" ] && kill -TERM "$pid" && sleep 2 && kill -9 "$pid" 2>/dev/null
systemctl --user start portfolio-server.service
systemctl --user is-active portfolio-server.service   # expect: active
ss -tlnp | grep 7777                                  # single listener; PID matches MainPID
```

Notes:

- Known failure mode: overlapping restarts + `SO_REUSEPORT` once produced twin listeners / an orphan with
  `systemctl inactive` but `:7777` still up — hence the explicit "verify single listener matches MainPID"
  step, and the unit deliberately has **no** `fuser -k` in `ExecStartPre`.
- Escalation policy: unresponsive after 3 probes → kill + `systemctl --user start portfolio-server`.
- Unit files live in `config/systemd/` and install to `~/.config/systemd/user/`
  (`systemctl --user daemon-reload` after changes).
