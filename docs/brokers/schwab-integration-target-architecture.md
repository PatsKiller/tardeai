# Schwab Integration — Target Architecture (Phase 3)

**Status:** ACCEPTED · scaffolding implemented dormant (Phase 4). Live enablement explicitly OUT OF SCOPE.

```mermaid
flowchart LR
  subgraph Product
    UI[Broker Orders surface\n(drafts/preview cards)] --> API[/api/v2/broker-orders/*/]
    PROP[Proposal pipeline\n(PAPER_TRAINING, unchanged)] --> SUB[proposal_paper_submitter]
  end
  API --> INTENT[Canonical OrderIntent\nvalidate()]
  INTENT --> CAP{CapabilityRegistry}
  CAP -->|supported| TR[BrokerOrderTranslator\n(pure, no I/O)]
  CAP -->|degraded/blocked| MSG[validation messages +\nunsupported indicators]
  TR --> GUARD{{BrokerExecutionGuard\nfail-closed}}
  GUARD -->|BROKER_DISABLED (Schwab now)| BLOCKED[ExecutionBlocked + audit]
  GUARD -->|PAPER_TRAINING (Alpaca)| AAD[alpaca_paper_adapter\n(existing, untouched)]
  GUARD -.->|LIVE_ENABLED_FUTURE\n(unreachable)| SAD[SchwabOrderAdapter stub\nraises unconditionally]
  INTENT --> AUDIT[(broker_order_intents +\nintent_state_events)]
  TR --> AUDIT
  GUARD --> AUDIT
  SAD -.-> FENCE[schwab_transport write fence\nNotProvenWrite · 12/12]
```

## Module layout (`scripts/brokers/`)
`interfaces.py` (7 interfaces + error taxonomy) · `order_intent.py` (canonical model + validation +
serde) · `capabilities.py` (registry + ALPACA/SCHWAB tables) · `translators/schwab.py` + `translators/
alpaca.py` (pure) · `execution_guard.py` (modes + fail-closed authorize + audit) · `audit.py` (persistence)
· `schwab_order_adapter.py` (stub: every mutating method raises ExecutionBlocked).
Persistence: `broker_order_intents` (intent/normalized/translation/validation JSONB, state, blocked_reason,
correlation_id) + `intent_state_events` (append-only).

## Data flow decisions
- Drafts and previews are FIRST-CLASS persisted objects (auditable product concepts), not UI state.
- Translation preview returns the EXACT broker payload that would be sent, plus capability annotations —
  reviewable artifact for the future enablement checklist.
- Quote/market-data needs of the Broker Orders surface use the EXISTING read-only wiring (batch quotes,
  market hours) — no new market-data paths.

## Migration posture (Alpaca → Schwab) — see migration-plan doc
No migration occurs in this phase. Paper training remains Alpaca indefinitely; Schwab remains
BROKER_DISABLED; the only shared artifact is the canonical model, which both translators already target.
