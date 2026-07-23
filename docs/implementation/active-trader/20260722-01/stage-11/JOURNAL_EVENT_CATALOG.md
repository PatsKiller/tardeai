# Journal Event Catalog — Stage 11
`scripts/active_trader/governance.py` JOURNAL_EVENT_CATALOG (22 events): session_draft_saved,
session_authorized_test, candidate_observed, market_reference, prime/fire_evaluated, res/rrs_scored,
runner_evaluated, sim_order_submitted/filled/cancelled, sim_pnl_snapshot, rejection_classified,
notification_projected, fallback_evaluated, feature_flag_changed, operator_action, drive_synced,
email_sent, darwin_proposal_created, hypothesis_created. All append-only (Stage 1 trigger); explicit
provenance (SHADOW_FIXTURE_OR_REPLAY / SIMULATION / LAB). Replay is REFERENCE-only (replay:// pointer;
raw high-frequency payload never inlined in PostgreSQL — ReplayIndexEntry rejects inlined data).
