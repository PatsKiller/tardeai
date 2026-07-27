# Authorization Envelope Schema — Stage 8
authorization_id · draft_id/version/hash · operator_id · environment(SHADOW/SIMULATION) ·
authorized_accounts((broker,label,role)) · symbols(explicit | (__UNIVERSE__,rule_version)) ·
quantity_envelope · risk_envelope · allowed_actions(frozenset[ActionType]) · fallback_policy ·
feature_policy_versions · issued_at/not_before/expiry · provider · verification_reference · version ·
status(AUTHORIZED/ACTIVE/EXPIRED/REVOKED/CLOSED) · revoked_at. Mutation/account-add/enlargement/
environment-change → reauthorization.
