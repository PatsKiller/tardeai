# Account Role & Allocation Matrix — Stage 7
Roles: PRIMARY / FALLBACK / DISABLED. A required-write capability that is UNSUPPORTED or UNKNOWN
CANNOT be PRIMARY/FALLBACK (ContractViolation) — only DISABLED. **Moomoo can never be selected for
LIVE activity** (data-only; credential-gate blocked) — rejected at construction.
Allocation: per-account explicit shares/notional/risk + allocation weights. Sizing modes: SHARES,
DOLLAR_NOTIONAL (notional/price), RISK_BASED (risk/per-share-risk). Floor to whole shares unless
fractions allowed; remainder surfaced. All tested.
