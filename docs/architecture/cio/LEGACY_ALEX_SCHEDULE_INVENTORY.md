# Legacy Alex Schedule Inventory

Discovered: 2026-08-08 during P-1.6 infrastructure discovery.

## Canonical Alex Cron Entries

| # | current_trigger | current_owner | current_state | schedule_id | target_replacement | retirement_prerequisite | duplicate_schedule_risk |
|---|---|---|---|---|---|---|---|---|
| 1 | `0 5 * * 1-5` | Trade AI crontab (johnclaw) | active | alex_daily | P-1.6 detector schedule slot `alex_daily` — daily 05:00 ET, Mon-Fri | P-1.6 wake-enqueue proven stable; legacy cron disabled atomically with P-1.7 activation | None — single cron entry |
| 2 | `0 8 * * 0` | Trade AI crontab (johnclaw) | active | alex_weekly | P-1.6 detector schedule slot `alex_weekly` — weekly Sunday 08:00 ET | Same as above | None |
| 3 | `0 9 1 * *` | Trade AI crontab (johnclaw) | active | alex_monthly | P-1.6 detector schedule slot `alex_monthly` — monthly 1st of month 09:00 ET | Same as above | None |
| 4 | `15 7 * * 1-5` | Trade AI crontab (johnclaw) | active | alex_hygiene | P-1.6 detector schedule slot `alex_hygiene` — daily 07:15 ET, Mon-Fri | Same as above | None |
| 5 | `0 6 * * 1` | Trade AI crontab (johnclaw) | active | alex_gov_research | P-1.6 detector schedule slot `alex_gov_research` — weekly Monday 06:00 ET | Same as above | None |

## CIO-Related Cron Entries (Not Directly Alex, But Adjacent)

| # | current_trigger | current_owner | current_state | what_it_does | notes |
|---|---|---|---|---|---|
| 6 | `0 7 * * 1-5` | Trade AI crontab | active | `cio_decision_engine.py --run` | CIO decision engine — separate from Alex |
| 7 | `20 16 * * 1,3,5` | tradeai-wt-watch-review-automation | active | watch review workers CIO mode | CIO pro synthesis — Mon/Wed/Fri |
| 8 | `30 21 * * *` | Trade AI crontab | active | `rerun_cio_dual_consensus.py` | overnight CIO dual consensus backfill |

## Script Contents Summary

### `scripts/run_alex_daily.py`
- **Modes**: daily, weekly, monthly
- **Daily (5 AM ET Mon-Fri)**: Full portfolio scan, tax, agent activity, intel highlights, alerts. Loads portfolio state, connects to DB for agent stats. Sends Telegram briefing.
- **Weekly (8 AM ET Sunday)**: LLM-generated strategy review (via `get_llm_response` with `agent_narrative` model). Income gap, rebalancing, Roth conversion timing, risk watch. Also runs YAML threshold analysis.
- **Monthly (9 AM ET 1st of month)**: Deep reconciliation — Roth ladder, tax bracket management, Medicaid/IRMAA tradeoff, top 3 actions. Uses `cio_synthesis` model.

### `scripts/alex_hygiene.py`
- **7:15 AM ET Mon-Fri**: Three-tier decision hygiene: Tier 1 (Sonnet, $0.01), Tier 2 (Sonnet+Grok, $0.03), Tier 3 (Sonnet+Grok+GPT-4o+Opus synthesis, $0.15). Classifies decisions into tiers based on keyword matching. Checks DB for recent decisions.

### `scripts/alex_gov_research.py`
- **6 AM ET Monday (weekly)**: Fetches government site data (SSA thresholds, CMS/Medicare, IRS brackets, NY Medicaid). Cached 30 days. No API keys. Populates `agent_intelligence_rules` table.

## Systemd Timer Infrastructure

- `tradeai-agent-runtime@alex.timer` — ACTIVE (systemd user timer)
- Multiple other agent timers present (aegis, argus, atlas, concierge, darwin, hermes, iris, maria, pulse, reflection, risk_agent, sentinel, steph, tax_agent, vega)

## OpenClaw Cron

- `openclaw.json` cron config: **EMPTY** (`{}`)
- No OpenClaw-managed Alex schedules exist.

## Existing Job Queue Infrastructure

- **None found** in `scripts/lib/` (no `*job*`, `*queue*`, `*agent_jobs*` files beyond P-1.3/P-1.4)
- **No `data/agent_jobs/`** directory exists
- **No generic durable job store** exists

## All times: America/New_York (Eastern Time)

Confirmed by crontab comments and script behavior. All legacy cron entries use local ET time.
