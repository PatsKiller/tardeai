# Overnight Controller Runbook — Stage 11
OvernightController: DISABLED by default (run_stage does nothing until enabled). One-stage
transaction; fail-stop (exception → FAILED, never advances). Prohibited operations raise
HermesGovernanceError: auto_merge, activate_live_flag, submit_broker_order, retry_moomoo_login.
No auto-merge/deploy/live-flag/real-2FA/broker-order/credential-retry loop. This is scaffolding for a
future authorized controller; it starts nothing on its own. Tested (disabled default, fail-stop,
prohibitions).
