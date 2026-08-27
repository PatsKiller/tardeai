# StopChangeAuditPanel Design

## Table
Symbol | Trade # | Old Stop | New Stop | Change Type | Source | Reason | Broker Proof | Changed At | Safe Action

## APPS Reference
APPS | #34 | $6.54 | $6.17 | repair | manual | orphan position reconciliation | accf1640... | 2026-05-27 | Review repair details

## Change Types
- initial_stop — first stop placement
- trailing_update — trailing tier ratchet
- repair — manual/operator audit correction
- manual_operator — explicit operator decision
- broker_reconcile — stop adjusted to match broker
- stop_hit — stop was triggered
- target_hit — target was hit
