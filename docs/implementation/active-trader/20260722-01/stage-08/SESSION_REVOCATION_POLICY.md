# Session Revocation Policy — Stage 8
status REVOKED/CLOSED or revoked_at set → check_active raises → every action returns BLOCKED.
Expiry (>= expiry) and not-before likewise block. Revocation/expiry/close removes all action
authority (Stage 8 models the contract; the live kill-switch/exit-only behavior lands in later
execution stages). No authority survives revocation.
