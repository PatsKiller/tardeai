# PHASE 190D — Health-Agent Protection Alert Routing Fix

Status:      HISTORICAL
as_of:       2026-06-02T10:33:34-04:00
Measured at: efcc51365 / not measured

**Files:** `scripts/protection_alerts.py` (new), `scripts/unified_stop_supervisor.py` (hook)
**Alpaca paper only.**

---

## Root cause (from 189D)
`unified_stop_supervisor` detected CRITICAL protection findings but only `log.warning`'d them —
no SIEM, no Telegram. The alert-capable health agents read brokerage `risk_management.json`, not
`paper_trades`, so paper positions were structurally invisible.

## Fix
### New detector + router: `scripts/protection_alerts.py`
- Queries **`paper_trades`** open positions (not brokerage JSON) + broker-verified protection
  metadata.
- Detects: `OPEN_POSITION_NO_BROKER_STOP` (P0), `BROKER_STOP_EXISTS_DB_UNTRACKED` (P1),
  `LARGE_GAIN_NO_TAKE_PROFIT` (P1, ≥ $250), `STOP_NOTE_UNVERIFIED` (P2).
- **SIEM:** inserts into `alert_events` using the curated `alert_type='data_integrity'` (the
  precise defect carried in `parsed_payload.defect_type`), severity mapped P0/P1/P2 →
  critical/urgent/warning. **Deduped** by `alert_uid=protect:<type>:<trade_id>` within 6h to
  avoid alert fatigue.
- **Telegram:** P0/P1 routed only when `--send` / `PROTECTION_ALERTS_TELEGRAM=true` — **off by
  default** (no routine noise).

### Supervisor hook (`unified_stop_supervisor.py`)
Best-effort call after reconciliation (wrapped in try/except so it can never break the
supervisor); records `protection_alerts` summary in the health report and logs emitted count.
Telegram gated by `PROTECTION_ALERTS_TELEGRAM`.

## Runtime proof
First run emitted **SIEM event id 162** — `data_integrity` / `LARGE_GAIN_NO_TAKE_PROFIT` / ANY /
urgent (ANY was +$535 at the time). Re-runs dedupe. Brokerage-JSON dependency bypassed: detection
now sources `paper_trades` directly.

## Why no auto-Telegram fired from the hook
Telegram routing is **opt-in** (`PROTECTION_ALERTS_TELEGRAM` unset) to honor "no routine noise."
To enable actionable auto-alerts: `update-config` to set that env var (operator decision). The
SIEM record is always written regardless.

## Remaining (190I/follow-up)
- Add `protection_alerts.py` to cron (or rely on the supervisor's `*/3` hook).
- Optionally enable `PROTECTION_ALERTS_TELEGRAM=true` after a noise check.
