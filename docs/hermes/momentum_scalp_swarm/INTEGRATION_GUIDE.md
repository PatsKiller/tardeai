# Integration Guide — Trade AI v12 Components

Status:      ACTIVE
as_of:       2026-07-02T18:53:06-04:00
Measured at: efcc51365 / not measured

---

## Stop Management Tab

**Path:** Portfolio → Stop Management (`StopManagement.tsx`)

| Swarm Output | UI Field |
|--------------|----------|
| `regime_state.json` | Regime column |
| `stoplight_status.json` | Stoplight badge (G/Y/A/R) |
| `momentum_scalp_regime.py` | Regime shift detection |
| `stoplight_regime_thresholds.py` | Dynamic Y/A/R R-thresholds |
| `pro_analyst_pills_latest.json` | Street column (μ, price vs μ) |
| Policy suggestions | Reasons column |

**API:** `GET /api/v2/stops/management` (includes `regime`, `policy_suggestions`, `stoplight_thresholds_used`)

---

## scalp_stop_monitor.py

Live Monitor wraps `run()` which provides:
- Per-trade R metrics, stop distance ATR, trail tightness
- Layer 4 regime shift + heat alerts
- `tighten_all()` for paper trade stop mutations

**No duplication** — swarm state is a snapshot layer on top of existing monitor.

---

## Journal & Tagging

Entry Validation writes (post-approval):
- `initial_stop_method`, `initial_stop_atr`, `dollar_risk`
- `breakeven_trigger_r`, `market_regime`, `signal_grade`

Post-Trade Review writes (on close):
- `stop_quality_score`, `final_r_vs_planned_stop`
- AI critique with 4 stop questions

**Migration:** `scripts/migrate_momentum_scalp_stop_tagging.py`

---

## Replay & Stop Intelligence

- `scripts/scalp_stop_intelligence.py` → Stop Intelligence panel
- Post-Trade Review uses replay for "R left on table" analysis
- `StopIntelligencePanel.tsx` in trade detail view

---

## AI Trade Critique

Journal critique prompt extended with §5 questions. Post-Trade Review Agent ensures every closed scalp gets structured answers.

---

## Regime Detection

- `scripts/lib/momentum_scalp_regime.py`
- `config/momentum_scalp_regime.yaml`
- Runtime: `data/runtime/symbol_regime_state.json`
- Swarm mirror: `state/momentum_scalp/regime_state.json`

---

## Street Consensus

- `scripts/lib/stop_consensus_check.py`
- `scripts/stop_over_consensus_monitor.py`
- Exit Intelligence Agent reads same pills JSON

---

## Telegram / OpenClaw

- `pending_approvals.json` queue
- Operator approves via existing Telegram review flow
- Pattern matches `HERMES_TELEGRAM_REVIEW_ACTIONABILITY_GATE.md`

---

## Command Center Hermes Hub

- Fleet selector: Research Fleet | **Momentum Scalp Swarm**
- API: `GET /api/v2/hermes/scalp-swarm/status`
- Agent prompts: `docs/hermes/momentum_scalp_swarm/agents/*.md`