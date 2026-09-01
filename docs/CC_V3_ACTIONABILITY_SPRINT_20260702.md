# CC v3 Actionability Sprint — Layered Document

Status:      HISTORICAL
as_of:       2026-07-02T18:42:35-04:00
Measured at: efcc51365 / not measured

**Build marker:** `cc-v3 actionability-sprint 2026-07-02`
**Approved:** 2026-07-02 (all defaults)

---

## Layer 1 — Executive summary

| Before | After |
|--------|-------|
| Home said "snapshot only" but ran full command surface | **Command router** — subtitle + actionable inbox |
| Action Inbox drill-only | CTAs → Risk, Open Trades, Proposals |
| Agents linked `/v2/inbox` (dead) | Home Operator Inbox + Agents Workflow |
| Watch links `/v3/watchlist` | Canonical `/v3/watch?tab=…` |
| Trading Execution blank while loading | Loading / error / empty shells |
| Rotation "Changelog" = engineering docs | **Advisor Guide** tab |
| Intelligence duplicated Rotation nav | Rotation tab removed |
| Strategy Backtest stub tab | Removed — Leaderboard CTA only |
| Health findings text-only in UI | `cta` field on API + Home alert rail |
| System Queue read-only | Link → Health → Coders |

---

## Layer 2 — UI changes by hub

### Home
- Subtitle: `command router`
- **Action Inbox** — per-item CTAs (Risk, Open Trades, Proposals)
- **Operator Inbox** panel (`/api/v2/inbox`)
- Alert rail — health findings with CTA links
- Proposal readiness → Trading Proposals link

### Agents
- Workflow: compact Operator Inbox
- Human Review drawer → `/v3/` + `/v3/agents?tab=workflow`
- Performance / Weekly Learning empty states with cron hints

### Trading
- Execution tab: loading, error, null-empty states
- BrokerProposals: execution readiness banner (blocked / unrouted / link rate)

### Watch
- Embedded Watchlist keeps **+ Add Watch** and ChatGPT (compact bar)

### Risk
- Regime stale banner + CTAs (Reports, Watch sectors, Strategy)
- Correlation empty → Portfolio / sectors links

### Rotation
- Tab renamed **Advisor Guide** (`?tab=advisor-guide`; `changelog` still works)
- `/advisor-changes` redirects to advisor-guide

### Intelligence
- Rotation tab removed; `?tab=rotation` → `/v3/rotation`

### Strategy
- Backtest tab removed

### System
- Queue tab footer → Health → Coders

### Shell
- MetricStrip: health warning badge; approvals tooltip updated

### Reports
- Empty brief copy no longer references removed Home Morning Command

---

## Layer 3 — Data & monitoring

### API
- `GET /api/v2/inbox` — used by OperatorInboxPanel (unchanged schema)
- Health findings now include **`cta: { label, route }`** via `health_agent._attach_cta`

### URL canonicalization
- `notification_url_builder.py` — v2/v3 watch paths → `/v3/watch?tab=…`
- `analyst_report_builder.py` — watch deep links updated
- `InferenceLayersPanel.tsx` — inference CTAs updated

### Self-fix loop
```
Health finding → cta.route → CC v3 hub/tab
System Queue failure → Health → Coders (manual bridge)
Home alert rail → same CTA map (healthCta.ts mirrors backend)
```

---

## Layer 4 — Verification

### Dry test (no browser)
```bash
.venv/bin/python scripts/cc_v3_ui_actionability_dry_test.py
```
Checks: static link conventions, hub contract, inbox API.

### Live probes
```bash
.venv/bin/python scripts/cc_v3_site_health_probe.py   # 94 endpoints
.venv/bin/python tests/test_cc_v3_hub_contract.py     # 19 hubs
```

### Playwright (browser-capable host)
```bash
.venv/bin/python scripts/cc_v3_playwright_audit.py
```
Script updated for consolidated Watch hub and tab removals.

---

## Files touched (primary)

| Area | Files |
|------|-------|
| Home / inbox | `HomeHub.tsx`, `OperatorInboxPanel.tsx` |
| Agents | `AgentsHub.tsx` |
| Trading | `TradingHub.tsx`, `BrokerProposals.tsx` |
| Watch | `WatchlistHub.tsx`, `InferenceLayersPanel.tsx` |
| Hubs | `RotationIntelligence.tsx`, `IntelligenceHub.tsx`, `StrategyHub.tsx`, `RiskHub.tsx`, `SystemHub.tsx`, `HealthHub.tsx`, `ReportsHub.tsx` |
| Shell | `MetricStrip.tsx`, `App.tsx`, `healthCta.ts` |
| Backend | `health_agent.py`, `notification_url_builder.py`, `analyst_report_builder.py` |
| Tests | `cc_v3_ui_actionability_dry_test.py`, `cc_v3_playwright_audit.py` |

---

## Deferred (approved defer)

- System 15-tab regrouping
- Trading 11-tab regrouping
- Nav label TradeInView → Journal (polish)