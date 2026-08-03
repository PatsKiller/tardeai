# Watchlist Health Agent — Autonomous Remediation System

## Overview

The Watchlist Health Agent (`scripts/watchlist_health_agent.py`) is a cron-driven
autonomous remediation system that continuously scans every active watchlist item
for degradation (stale CIO synthesis, missing critic reviews, quality not assessed,
stale street data, missing plans) and auto-fixes what it can, escalating the rest
to the operator via Telegram.

## Hard Boundaries (enforced in code)

The following actions are **permanently prohibited** for the health agent. Any
attempt to call them is blocked by explicit guard clauses:

### No 2FA
- **Never** calls `brokers/approval_service.py` or any 2FA gateway
- **Never** triggers `bkapprove`/`bkreject` callbacks
- **Never** interacts with broker OAuth (Schwab OAuth, SnapTrade OAuth, Moomoo OpenD)

### No Trading
- **Never** places, modifies, or cancels trades
- **Never** calls `paper_execution_sweep.py`, `atm_auto_approver.py`, or any
  order-submission path
- **Never** touches `paper_trade_proposals` with status changes beyond `expired`

### No Broker Account Management
- **Never** reads or writes `holdings.json` (guarded by `holdings_guard`, minimum
  $1M portfolio total — **no accidental writes**)
- **Never** syncs broker positions (Alpaca, Schwab, SnapTrade, Moomoo)
- **Never** calls broker-balance or cost-basis endpoints

### Escalation Only
Any issue that requires broker interaction, trade action, or account changes is
**escalated to the operator via Telegram** with a clear diagnosis and recommended
manual action. The agent logs the finding and moves on.

## Safe Actions (what the agent CAN do)

These are read-only or advisory-only API endpoints that the agent is allowed to call:

| Action | API Endpoint | Method | Advisory Only |
|--------|-------------|--------|---------------|
| Refresh packet data | `POST /api/v2/watch/decision/refresh` | Subprocess curl | Yes |
| CIO synthesis | `POST /api/v2/watchlist/<SYM>/cio-synthesis` | Subprocess curl | Yes |
| Build entry plan | `POST /api/v2/watchlist/<SYM>/plan` | Subprocess curl | Yes |
| Run critic reviews | `POST /api/v2/watch/ticket-review/run` | Subprocess curl | Yes |
| Queue agent reviews | DB insert to `watchlist_agent_jobs` | Direct SQL | Yes |
| Refresh street data | `POST /api/v2/watchlist/refresh-batch` | Subprocess curl | Yes |

## DeepSeek Integration

- **DeepSeek Flash** — used for diagnosis (classification: what is wrong, what
  severity, what actions to take). Fast (~1s), cheap.
- **DeepSeek v4** — used for CIO synthesis (high-reasoning synthesis of multi-agent
  narratives). This happens through the existing synthesis API, not directly.
- **Fallback** — deterministic rule-based diagnosis when DeepSeek is unavailable.

## Telegram Approval Flow

For HIGH-severity actions that require operator judgment:

1. Agent scans watchlist, finds degradation
2. DeepSeek Flash diagnoses root cause + recommends actions
3. For HIGH-severity or actions touching active proposals, sends Telegram message
   with inline keyboard:
   - ✅ Approve All
   - ❌ Deny
   - 🔍 Open Card
4. Callback handler (`telegram_callback_handler.py`) processes the response:
   - Approve → executes the queued actions
   - Deny → logs and moves on
5. All actions logged to `system_health_events` table

## Dashboard Integration

Status available via:
- `python3 scripts/watchlist_health_agent.py --dashboard` (JSON)
- Existing System Hub → Operations page (reads `system_health_events`)
- Telegram inline status updates after remediation

## AGENTS.md Rule Validation

The design was validated against every rule in AGENTS.md:

| AGENTS.md Rule | Impact on Health Agent | Validation |
|---------------|----------------------|------------|
| **Holdings write guard (`MIN_TOTAL = 1_000_000`)** — `holdings_guard.protected_holdings_write` fail-closes below $1M | Agent never writes holdings.json. Guard not triggered. | ✅ Safe |
| **Hot-reload covers only `api_v2.py`/`reports_portal.py`** | New `watchlist_health_agent.py` is a standalone cron script, not a server module. No hot-reload needed. | ✅ Safe |
| **Live server runs from SHA-pinned release directory** | Agent is invoked by cron (not the HTTP server). Deploy by copying to release dir. | ✅ Documented |
| **Bitwarden secrets — never print/echo** | Agent reads secrets only via `os.environ` (tmpfs from `render_env.py`). Never prints values. | ✅ Safe |
| **`psql` alias trap** | Agent uses `db_adapter._get_conn()` not raw `psql`. No alias interference. | ✅ Safe |
| **Migration chain not idempotent** | Agent creates no schema migrations. `watchlist_health_approvals` table must be created separately. | ✅ Documented |
| **Three deployment targets** | Agent runs as a cron job from the SHA-pinned release dir. No agent-runtime involvement. | ✅ Single target |
| **Per-agent timers fail-closed** | Not applicable — agent is an independent cron job, not a systemd timer. | ✅ N/A |
| **`CapabilityBoundingSet=` fails hard** | Agent runs in a plain cron, no systemd unit template with capability drops. | ✅ Safe |
| **Generic SHADOW agents must not self-complete** | Not applicable — health agent is not a SHADOW agent. | ✅ N/A |
| **Data broker rule — all data through canonical stores** | Agent reads from `decision_packets`, `watchlist_final_synthesis`, `watchlist_agent_results` — all canonical stores. New health data written to `system_health_events` — canonical health table. | ✅ Compliant |
| **Authority hierarchy** | Agent never overrides broker data. Never reads broker data. Advisory only. | ✅ Compliant |

## Cron Schedule

```
# Watchlist Health Agent — every 30 min weekdays, every 60 min weekends
*/30 9-16 * * 1-5 /usr/bin/python3 scripts/watchlist_health_agent.py --apply --limit 30
0 */1 * * 0,6 /usr/bin/python3 scripts/watchlist_health_agent.py --apply --limit 30
```

## DB Schema (one-time migration)

```sql
-- Run as migrator role only (see AGENTS.md migration rules)
-- Apply only this file, not the full chain:
-- command psql -d "$LAB_DSN" -v ON_ERROR_STOP=1 -f migrations/watchlist_health_approvals.sql

CREATE TABLE IF NOT EXISTS watchlist_health_approvals (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    diagnosis JSONB,
    actions JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, approved, denied, expired
    message_id VARCHAR(50),
    resolved_by VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolution_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_wl_health_approvals_status ON watchlist_health_approvals(status);
CREATE INDEX IF NOT EXISTS idx_wl_health_approvals_symbol ON watchlist_health_approvals(symbol);
CREATE INDEX IF NOT EXISTS idx_wl_health_approvals_created ON watchlist_health_approvals(created_at DESC);
```
