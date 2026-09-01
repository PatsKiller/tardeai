# Multi-Hermes Momentum Scalp Swarm — Architecture

Status:      ACTIVE
as_of:       2026-07-02T18:56:18-04:00
Measured at: efcc51365 / not measured

**Version:** 1.0 · **Date:** 2026-07-02
**Policy:** [`MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md`](../../MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md)
**Phase:** 4.4 → 4.5 paper trading validation
**UI:** Command Center v3 → Hermes → **Momentum Scalp Swarm**

---

## 1. Mission

A hierarchical 7-agent Hermes swarm manages the full lifecycle of Momentum Scalp + Social Route paper trades in Trade AI v12. The system strictly enforces the official 4-layer stop methodology, context-aware trailing (advisory), dynamic regime-based adjustments, and the mandatory breakeven rule.

**Non-negotiable constraints:**
- Layer 2 breakeven at +1.0R–+1.5R is mandatory for all scalps
- Layer 3 trailing execution is **config-OFF** (advisory only until §6 validation passes)
- Long and short positions are handled symmetrically
- All material actions require Telegram approval (paper phase)

---

## 2. Agent Hierarchy

```
                    ★ Hermes Orchestrator (Supervisor)
                   /    |      |       \         \
          Signal Scout  Entry   Live Monitor → Stop Adjustment ← Exit Intelligence
              Validation      (persistent)              |
                                                      Post-Trade Review
```

| # | Agent | Role | Phase |
|---|-------|------|-------|
| 1 | Hermes Orchestrator | State manager, policy gatekeeper, routing, HITL | **Phase 1** |
| 2 | Signal Scout | Detect/qualify momentum + social signals | **Phase 2** (`hermes_scalp_signal_scout.py`) |
| 3 | Entry Validation | Layer 1 validation, sizing, journal entry | **Phase 2** (`hermes_scalp_entry_validation.py`) |
| 4 | Live Monitor | Persistent open-scalp monitoring, regime, stoplight | **Phase 1** |
| 5 | Stop Adjustment | Layer 4 adjustments with audit trail | **Phase 1** |
| 6 | Exit Intelligence | Profit vs Street consensus, partial exits | **Phase 3** (`hermes_scalp_exit_intelligence.py`) |
| 7 | Post-Trade Review | AI Trade Critique, validation tracker | **Phase 3** (`hermes_scalp_post_trade_review.py`) |

---

## 3. Shared State Layer

All agents read/write JSON state under `state/momentum_scalp/` with atomic writes and file locking.

| File | Owner(s) | Purpose |
|------|----------|---------|
| `open_scalps.json` | Live Monitor | Open position snapshot |
| `portfolio_heat.json` | Live Monitor, Orchestrator | Aggregate risk, pause/kill flags |
| `regime_state.json` | Live Monitor | Per-symbol regime + shifts |
| `stoplight_status.json` | Live Monitor | Green/Yellow/Amber/Red per position |
| `stop_adjustment_history.json` | Stop Adjustment | Full stop change audit |
| `validation_tracker.json` | Post-Trade Review | §6 gate metrics |
| `orchestrator_audit.json` | Orchestrator | Decision audit log |
| `pending_approvals.json` | Orchestrator | Telegram HITL queue |

See [`SHARED_STATE_SCHEMA.md`](SHARED_STATE_SCHEMA.md).

---

## 4. Policy Enforcement Gates

The Orchestrator rejects or queues any action that would violate:

| Gate | Policy Ref | Check |
|------|------------|-------|
| Max initial risk | §3 L1 | `initial_risk_r ≤ 1.2` |
| Mandatory breakeven | §3 L2 | Stop must move to BE/+0.3R at +1.0–1.5R |
| Trail too early | §3 L3 | No trail before BE secured + +1.5–2.0R |
| Regime shift tighten | §3 L4 #1 | 0.5× ATR on Trending→Ranging |
| Portfolio heat | §3 L4 #2, §7 | Pause at 3.5%, kill at 4.5% |
| Freshness decay | §3 L4 #3 | BE + tighten if stale + no +0.8R |
| Max concurrent | §7 | ≤ 3 open scalps |

---

## 5. Integration Points

| Trade AI Component | Integration |
|--------------------|-------------|
| Stop Management tab | Live Monitor → `stoplight_status.json` + regime API |
| `scalp_stop_monitor.py` | Live Monitor wraps `run()` |
| `momentum_scalp_regime.py` | Regime detection per symbol |
| Journal / Tagging | Entry Validation + Post-Trade Review |
| AI Trade Critique | Post-Trade Review (4 stop questions) |
| Replay | Post-Trade Review R-left-on-table analysis |
| Telegram / OpenClaw | Orchestrator `pending_approvals.json` |

See [`INTEGRATION_GUIDE.md`](INTEGRATION_GUIDE.md).

---

## 6. Human-in-the-Loop

Paper phase (4.4→4.5): **all** material actions go through Telegram:
- New entries
- Stop adjustments (including breakeven moves)
- Exits / partial profit taking

Flow: Agent proposes → Orchestrator enqueues → OpenClaw Telegram → Operator approves/rejects → Agent executes → Audit log.

---

## 7. Deployment

- **Scripts:** `hermes_scalp_orchestrator.py`, `hermes_scalp_live_monitor.py`
- **Tmux:** `linux_launchers/hermes_scalp_swarm_tmux.sh`
- **API:** `GET /api/v2/hermes/scalp-swarm/status`
- **Hermes profile:** `tradeai12b` with file read/write tools

See [`DEPLOYMENT_OPERATIONS.md`](DEPLOYMENT_OPERATIONS.md) and [`GETTING_STARTED.md`](GETTING_STARTED.md).

---

## 8. Cross-References

| Doc | Path |
|-----|------|
| Stop policy | `docs/MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md` |
| Regime algorithm | `docs/MOMENTUM_SCALP_REGIME_DETECTION_ALGORITHM.md` |
| Monitoring protocol | `docs/MOMENTUM_SCALP_STOP_MONITORING_PROTOCOL.md` |
| Agent prompts | `docs/hermes/momentum_scalp_swarm/agents/` |
| Orchestration | `ORCHESTRATION_ROUTING.md` |
| Validation | `VALIDATION_CHECKLIST.md` |
| Phase 3 dry test | `PHASE_3_DRY_TEST.md` |