# Schema & Contract Matrix — Stage 1

**Run ID:** 20260722-01 · Migrations: `migrations/active_trader/000{1..5}_*.{up,down}.sql`
Runner: `scripts/active_trader/migrate.py` (tracked in `active_trader_schema_migrations`;
refuses DB name `trade_ai`, localhost:5432, missing/sentinel DSN; up/down/status/reapply;
sha256 drift detection). Contracts: `scripts/active_trader/contracts.py`.

| # | Table | Migration | Key invariants (DB-enforced) | Contract type |
|---|---|---|---|---|
| 1 | active_trader_session_drafts | 0001 | append-only trigger; UNIQUE draft_hash; env CHECK, no default | SessionDraft (frozen; canonical-JSON sha256 `.hash`) |
| 2 | active_trader_session_authorizations | 0001 | FK to exact draft version; status CHECK; cutoff ≤ expiry; REVOKED⇒revoked_at | SessionAuthorization (hash binds draft+operator+bounds; check_valid/check_account/check_quantity fail closed) |
| 3 | active_trader_session_accounts | 0001 | broker CHECK (v1 scope); role PRIMARY/FALLBACK/DISABLED; non-negative caps | SessionAccount |
| 4 | active_trader_order_intents | 0002 | env CHECK no default; **LIVE ⇒ session_authorization_id + authorization_hash (CHECK)**; **SHADOW ⇒ only DRAFT/VALIDATED/EXPIRED states**; idempotency_key globally UNIQUE (no sim/live reuse) | OrderIntent (LIVE requires valid+unrevoked+unexpired auth and in-envelope account; SHADOW may not carry auth) |
| 5 | active_trader_position_states | 0002 | env CHECK; LIVE ⇒ session FK; protection_state CHECK incl. UNCERTAIN | (Stage 4 read model; row contract only) |
| 6 | active_trader_journal_events | 0003 | append-only trigger; occurred_at required | (event-name set per §16D.1; runtime later) |
| 7 | active_trader_score_snapshots | 0003 | subject_type CHECK; scoring_version required | — |
| 8 | active_trader_parity_checks | 0003 | matched boolean required | — |
| 9 | broker_account_capabilities | 0004 | PK(broker,account,env,capability); state CHECK; **SUPPORTED ⇒ verified_at**; source CHECK | BrokerCapability (`effective_state`: past expiry ⇒ UNKNOWN, never silently SUPPORTED) |
| 10 | broker_rejection_events | 0004 | retryable default FALSE; requires_operator default TRUE | NormalizedRejection (20-code registry; unknown ⇒ UNKNOWN_BROKER_REJECTION, non-retryable, operator-required; broker-assist ⇒ requires_broker_call) |
| 11 | active_trader_feature_flags | 0005 | append-only versioned rows PK(flag,scope,version); mode CHECK (OFF/READ_ONLY/SHADOW/SIMULATION/LIVE_CANARY); reason+changed_by required; rollback_mode | FeatureFlag + FLAG_REGISTRY (22 flags) + DEFAULTS (prod/test all OFF; dev visible=READ_ONLY) + `authorize_order` (flags restrict, NEVER grant) |
| 12 | active_trader_notification_events | 0005 | severity/category CHECKs; requires_operator_action | — |
| 13 | active_trader_drive_sync_manifest | 0005 | UNIQUE(run,stage,path); upload_state CHECK | DriveManifestEntry (verified ⇒ UPLOADED + file id) |
| 14 | active_trader_run_checkpoints | 0005 | state CHECK (6 states); version ≥ 1 | RunCheckpoint (optimistic version; FAILED advances only via explicit resume=True; GREEN_CLOSED requires all Drive artifacts verified) |

Also: LitmusReport contract per §16J.3 (extended fields per Stage 1 ruling); verdicts
PASS/CONDITIONAL_PASS/FAIL; READ_ONLY + write_attempted=false enforced.

Environment discipline everywhere: `Environment.parse` rejects absent/blank/unknown —
**no implicit LIVE default exists in any code path or column.**
