# Proposal Execution Paths

Every signal becomes a **broker-agnostic proposal** first. You choose how to execute — two different methods, same review queue.

## Path A — Paper auto (testing)

**Purpose:** Validate strategy, sizing, stops, and pipeline gates **without real money**.

| Item | Detail |
|------|--------|
| **Where** | Command Center → Trading → **Proposals** |
| **Broker** | Alpaca paper (configured in ATM / `broker_config`) |
| **Automation** | Approve → `proposal_paper_submitter` → Alpaca bracket order |
| **2FA** | None (paper only) |
| **Live blocked** | Yes — P0 readiness / interlock keeps real Schwab/Fidelity submits gated |

### Operator steps

1. Review proposal card (enrichment, Check Execution, AI review).
2. **Approve** on the Proposals tab (or `/ptapprove ID` in Telegram).
3. System creates `paper_trades` row and submits to Alpaca when gates pass.
4. Monitor under **Open Trades** / paper journal — not in live holdings.

### Code touchpoints

- `scripts/paper_trade_logger.py` — `approve_proposal()`
- `scripts/proposal_paper_submitter.py` — Alpaca bracket submit
- `scripts/queue_router.py` — paper branch when route is unset or paper account

---

## Path B — Live real money (Schwab auto or Fidelity FA manual)

**Purpose:** Deploy capital at **Schwab** (API + per-order 2FA) or **Fidelity** (no trading API — **Fidelity Active Trader Pro** ticket + log).

| Broker | Execution | 2FA / manual |
|--------|-----------|----------------|
| **Schwab** | Auto LIMIT/bracket via API **or** manual at Schwab.com | Per-order 2FA when auto path armed |
| **Fidelity** | **Manual only** — place in **Active Trader Pro (FA)** | No API; software stop monitor may alert + ticket on breach |

| Item | Detail |
|------|--------|
| **Where** | Proposals → **Promote to Broker** → **Broker Proposals** tab |
| **Queue table** | `paper_trade_proposals` with `intended_broker` / `target_account` = `schwab_*` or `fidelity_*` |
| **Automation** | Schwab: `queue_router` → `schwab_transport` (gated). Fidelity: record-only + manual log |
| **After fill** | **Executed manually** modal → `POST /api/v2/executions/log-manual` (closed-loop tagging) |

### Operator steps

1. Start from **Proposals** (route badge `Unassigned`).
2. **Promote to Broker** — pick account (`schwab_taxable`, `fidelity_rollover_ira`, etc.), adjust size/risk.
3. Open **Broker Proposals** — run diligence, pick destination, route or log manual fill.
4. **Schwab auto:** Route (when pilot armed) → approve 2FA in Telegram/web → order submits.
5. **Fidelity / manual Schwab:** Place order in **FA** or Schwab UI → **Executed manually** → log execution for journal/rec-intel.

### Code touchpoints

- `scripts/paper_trade_logger.py` — `promote_proposal_to_broker()`
- `scripts/queue_router.py` — Schwab / Fidelity branches
- `scripts/manual_execution_tracker.py` — manual fill tagging
- `scripts/fidelity_monitored_stop.py` — breach → FA ticket (no auto-submit)

---

## Shared upstream (same for both paths)

```
Scan / Incubator GO → paper_trade_proposals (PENDING, routing unassigned)
        ↓
   Enrich + Check Execution + optional AI review
        ↓
    ┌───────────────┴────────────────┐
    │                                │
 Path A: Approve (paper)      Path B: Promote to Broker
    │                                │
 Alpaca auto test              Schwab 2FA auto OR FA manual
```

## Routing fields (`paper_trade_proposals`)

| Field | Meaning |
|-------|---------|
| `routing_state` | `unassigned` → `queued` → `routing` → `routed` / `rejected` |
| `intended_broker` / `target_account` | Set at promote or approve — **not** at incubator create |
| `routing_label` (API) | `unassigned` \| `paper_auto` \| `live_schwab` \| `live_fidelity` |

## Telegram alerts

- New proposals alert as **needs review** until execution readiness is checked.
- Paper approve: `/ptapprove {id}`
- Paper reject: `/ptreject {id} reason`
- Schwab live orders: separate broker-order 2FA flow (not the same as paper approve).

## Related docs

- `docs/OPTIONS_BROKER_EXECUTION_FLOWS.md` — options desk (same auto vs manual split)
- `docs/DAILY_OPS_LOG.md` — Schwab canary / Fidelity monitored stops