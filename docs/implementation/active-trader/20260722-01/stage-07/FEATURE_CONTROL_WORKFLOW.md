# Feature Control Workflow — Stage 7
Dev feature-control updates permit OFF / READ_ONLY / SHADOW / SIMULATION only. **LIVE_CANARY is
rejected** (ContractViolation) via both the pure validator and the dev API. Flags are versioned,
append-only, audited (reason + changed_by), and **cannot authorize or enlarge authority** — the
API response explicitly returns authorizes_trading=false. Unknown flag names rejected. Production
effective modes remain OFF (Stage 1 defaults); this plane writes only test-scoped flags in the lab DB.
