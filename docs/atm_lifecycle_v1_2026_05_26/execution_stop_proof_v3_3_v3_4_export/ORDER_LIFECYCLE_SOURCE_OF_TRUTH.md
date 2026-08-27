# Order Lifecycle Source of Truth

```
proposal (paper_trade_proposals)
  → approval (atm_decision_log)
    → order request (proposal_paper_submitter.py)
      → broker order (alpaca_paper_adapter.py → Alpaca API)
        → ack (Alpaca order.status = accepted/new)
          → fill (Alpaca order.status = filled, fill_price)
            → position (paper_trades row with entry_price)
              → stop order (unified_stop_supervisor.py)
                → trailing updates (every 3 min)
                  → exit (stop_hit / target_hit / manual)
                    → TCA (paper_execution_quality_analyzer.py)
```

## Missing Links

| From | To | Status |
|------|-----|--------|
| Proposal → Order request | No explicit "order submitted" timestamp | MISSING |
| Order request → Broker ack | No broker_ack_time stored | MISSING |
| Broker ack → Fill | No fill_time stored | MISSING |
| Position → Stop order | No stop_order_id stored | MISSING |
| Stop order → Broker verification | No verification mechanism | MISSING |
