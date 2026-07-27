# Draft Hash Canonicalization — Stage 7
`SessionDraftV2.hash` = sha256 of canonical JSON (sorted keys, compact) over the AUTHORITY_FIELDS
only: environment, start/end, entry_cutoff, symbol_policy, account_roles (sorted by broker+label),
quantity_policy, gross_notional_cap, per_symbol/account caps, risk/trade-count/daily-loss caps,
fallback_policy, quick_add_config, runner_policy, feature_policy_versions.
Properties (tested): deterministic; account-order-independent; unchanged by session_name/notes/
version; changed by any authority field. Persisted-row uniqueness uses a separate per-version row
hash (draft_id|version|authority_hash) to satisfy the Stage 1 global-unique draft_hash column while
the authority hash is what Stage 8 authorization binds.
