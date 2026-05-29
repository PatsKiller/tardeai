# Proposal Lifecycle Inspector Implementation — 2026-05-29

## Endpoint
`GET /api/v2/paper-proposals/lifecycle-inspector?proposal_id=<id>`

## File
`scripts/api_v2.py` — inserted after `/api/v2/paper-proposals/lifecycle-events`

## Payload Example (BLBD proposal #10 — expired)
```json
{
  "proposal_id": 10,
  "symbol": "BLBD",
  "status_raw": "expired",
  "status_normalized": "EXPIRED",
  "signal_decision": "GO",
  "strategy_id": "earnings_catalyst",
  "source": "unknown",
  "enrichment_status": "",
  "enrichment_failures": 0,
  "age_hours": 531.3,
  "atm_expired": false,
  "atm_expiry_reason": null,
  "linked_paper_trade_id": null,
  "linked_trade": null,
  "extra_trades": [],
  "enrichment_satellites": {
    "technical_snapshots": 0,
    "agent_reviews": 0,
    "research_packets": 1,
    "backtest_snapshots": 1
  },
  "lifecycle_events_count": 14,
  "lifecycle_events": [...],
  "actionable": false,
  "next_action": "None — terminal status",
  "safety": {
    "is_terminal": true,
    "has_linked_trade": false,
    "needs_enrichment": false,
    "requires_operator_approval": false
  }
}
```

## Payload Example (SNOW proposal #138 — approved with trade)
```json
{
  "proposal_id": 138,
  "symbol": "SNOW",
  "status_normalized": "APPROVED_FOR_PAPER_TEST",
  "linked_paper_trade_id": 39,
  "linked_trade": {"id": 39, "status": "pending", "pnl": null},
  "extra_trades": [{"id": 40, "status": "open"}],
  "actionable": false,
  "next_action": "Monitor linked trade",
  "safety": {
    "is_terminal": false,
    "has_linked_trade": true,
    "needs_enrichment": true,
    "requires_operator_approval": false
  }
}
```

## Data Sources Aggregated
| Source | Query |
|--------|-------|
| Core proposal | paper_trade_proposals WHERE id = ? |
| Linked trade | paper_trades WHERE id = proposal.paper_trade_id |
| Extra trades | paper_trades WHERE proposal_id = ? AND id != linked |
| Technical snapshots | proposal_technical_snapshots |
| Agent reviews | proposal_agent_reviews |
| Research packets | proposal_research_packets |
| Backtest snapshots | proposal_backtest_snapshots |
| Lifecycle events | proposal_lifecycle_events |

## Actionability Rules
| Condition | Actionable? | Next Action |
|-----------|------------|-------------|
| Terminal status (EXPIRED/REJECTED/RISK_BLOCKED/CANCELLED) | NO | None — terminal |
| Has linked trade | NO | Monitor linked trade |
| Needs enrichment | NO | Await enrichment |
| PENDING, not enriched, not expired | NO | Review |
| PENDING, enriched, not expired, no trade | YES | Ready for approval |

## Safety Rules
- Read-only endpoint — no DB mutations
- No apply/submit/execute actions exposed
- Exposes `requires_operator_approval` flag but does NOT provide an approval button
- No broker interaction
- No order placement

## UI Component
Not added in this session — API-only. Next step: add "Inspect" button to PaperProposals.tsx rows that opens a side panel or modal with lifecycle inspector data.
