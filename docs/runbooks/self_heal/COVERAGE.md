# 14-day failure coverage — every real signature to one catalog entry

Generated from `COVERAGE.json` (`SelfHealRunbookCoverage@v1`), written by `scripts/ops/self_heal_runbook_replay.py` against the catalog v2026-11-08.2. **Do not edit** — re-run the replay.

| | |
| --- | --- |
| Window | 2026-10-25T22:45:00+00:00 .. 2026-11-08T22:45:00+00:00 (14 days) |
| Receipts scanned | 41586 |
| Failures | **1028** (748 receipt failures + 280 dead letters) |
| Signatures | 24 |
| Entries hit | 17 of 50 |
| Catch-all | **0** hit(s), 0 without a written reason |

## The rule

failure = a receipt whose state is not RUN_DONE (RUN_FAILED/RUN_TIMEOUT/RUN_REFUSED/RUN_SKIPPED_LOCK) or a dead letter; signature = state + normalized last stderr line (shortest reader: the receipt reason when there is no stderr); a legacy RUN_DONE with no verdict is a schema gap, not a failure; replay = plan_runbook(dry, fixed as-of, catalog on this commit).

A signature is the failure state plus the normalized last stderr line — timestamps, paths, hex, long tokens, digits and **symbols** are collapsed — or the receipt's `reason` when there is no stderr. The same text is what the fixer keys an incident on, so 'covered' means 'this exact signature plans to an entry', not 'a similar one does'.

## Per signature

`plans` lists what the engine answered for every occurrence of the signature, with its hit count. A signature with more than one plan is not a defect: the *class* is derived from other receipt fields (a dead letter carries only `exit_1`), so ONE short text can be several defects.

| hits | class | signature | source | plans (entry · action · tier) |
| --- | --- | --- | --- | --- |
| 565 | `lock_held` | `RUN_SKIPPED_LOCK: flock_held` | receipts 565 | A01-flock-held · noop_wait_recheck · auto (565) |
| 155 | `code_error` | `RUN_FAILED: exit_<N>` | dead_letters 112, receipts 43 | J01-code-defect · escalate_finding · auto_notify (144); A03-sqlite-database-locked · release_stale_sqlite_wal_lock · auto_notify (9); D02-provider-5xx · none · auto_notify (1); I04-invalid-config-json · escalate_finding · human_only (1) |
| 106 | `executor_lost` | `RUN_TIMEOUT: executor_lost` | dead_letters 54, receipts 52 | F01-executor-lost · noop_wait_recheck · auto (106) |
| 53 | `wall_timeout` | `RUN_TIMEOUT: timeout_exit_<N>` | dead_letters 41, receipts 12 | E01-run-timeout-124 · noop_wait_recheck · auto_notify (53) |
| 42 | `effect_no_owner` | `RUN_REFUSED: effect:effect_no_owner` | dead_letters 21, receipts 21 | F06-effect-no-owner · escalate_finding · auto_notify (42) |
| 38 | `output_unverifiable` | `RUN_FAILED: output_unverifiable` | dead_letters 20, receipts 18 | C06-output-unverifiable · escalate_finding · auto_notify (38) |
| 27 | `empty_output` | `RUN_FAILED: empty_output` | dead_letters 26, receipts 1 | C02-empty-output · rerun_once_via_gateway · auto (27) |
| 9 | `bridge_route_refused` | `RUN_FAILED: <SYM>: model call failed (BridgeRouteRefused: BRIDGE_ROUTE_REFUSED: governed bridge returned no text for process due_diligence_questions)` | receipts 9 | F02-bridge-route-refused · escalate_finding · auto_notify (9) |
| 6 | `config_env` | `RUN_REFUSED: env_allowlist:env_names_missing` | dead_letters 3, receipts 3 | I05-env-names-missing · escalate_finding · human_only (6) |
| 5 | `parse_error` | `RUN_FAILED: json.decoder.JSONDecodeError: Expecting value: line <N> column <N> (char <N>)` | receipts 5 | I04-invalid-config-json · escalate_finding · human_only (5) |
| 4 | `schema` | `RUN_FAILED: [yfinance-info-snapshot] FAILED (unconfigured): table yfinance_info_snapshot does not exist (migration migrations/<TOKEN>.sql not applied)` | receipts 4 | H03-schema-missing · escalate_finding · human_only (4) |
| 3 | `data_defect` | `RUN_FAILED: lib.hermes_discovery.inbox.DiscoveryInboxError: label normalizes to empty key: <SYM>` | receipts 3 | J03-data-defect-in-input · escalate_finding · auto_notify (3) |
| 3 | `effect_claimed` | `RUN_REFUSED: effect:effect_already_claimed` | dead_letters 3 | A06-effect-already-claimed · noop_wait_recheck · auto (3) |
| 2 | `db_connection_closed` | `RUN_FAILED: <TS>,<N> [daily_incubator_refresh] rollback skipped: connection already closed` | receipts 2 | H05-db-connection-closed · noop_wait_recheck · auto (2) |
| 1 | `code_error` | `RUN_FAILED: <TS>,<N> [httpx] HTTP Request: GET https:/<PATH>?symbols=<SYM> "HTTP/<N> <N> OK"` | receipts 1 | J01-code-defect · escalate_finding · auto_notify (1) |
| 1 | `pg_lock` | `RUN_FAILED: CONTEXT: while updating tuple (<N>,<N>) in relation "<TOKEN>"` | receipts 1 | A04-pg-lock-not-available · noop_wait_recheck · auto_notify (1) |
| 1 | `code_error` | `RUN_FAILED: DETAIL: Failing row contains (<N>, <TS>-<N>, <TOKEN>, <N>, <SYM>, null, null, null, subject, <TOKEN>, <N>, company_name, Schwab <SYM> Dividend Equity ETF, DocumentMention@v<N>, READ_ONLY_ADVISORY).` | receipts 1 | J01-code-defect · escalate_finding · auto_notify (1) |
| 1 | `code_error` | `RUN_FAILED: ERROR: <N>/<N> endpoint(s) failed: ['health']` | receipts 1 | J01-code-defect · escalate_finding · auto_notify (1) |
| 1 | `data_defect` | `RUN_FAILED: [exit-outcomes] dependency_unavailable — no exit_intelligence rows exist and Gain Guardian is unpublished (config/<TOKEN>.json published=false): nothing has ever been published to reconcile; promote Gain Guardian or retire this lane` | receipts 1 | J03-data-defect-in-input · escalate_finding · auto_notify (1) |
| 1 | `code_error` | `RUN_FAILED: [hermes-bridge] FAILED: no source=hermes rows in the last <N> h (contract per_window min_produced=<N>): the bridge runs but its input feed produces nothing; <N> candidates this run` | receipts 1 | J01-code-defect · escalate_finding · auto_notify (1) |
| 1 | `data_defect` | `RUN_FAILED: [watch-outcomes] dependency_unavailable — no producer: newest watch_candidate_events.emitted_on is <N>-<N>-<N> (<N> days old, limit <N>) — nothing can be reconciled until a candidate-event producer runs again` | receipts 1 | J03-data-defect-in-input · escalate_finding · auto_notify (1) |
| 1 | `db_connection_closed` | `RUN_FAILED: psycopg<N>.OperationalError: SSL connection has been closed unexpectedly` | receipts 1 | H05-db-connection-closed · noop_wait_recheck · auto (1) |
| 1 | `pg_lock` | `RUN_FAILED: psycopg<N>.errors.LockNotAvailable: canceling statement due to lock timeout` | receipts 1 | A04-pg-lock-not-available · noop_wait_recheck · auto_notify (1) |
| 1 | `wall_timeout` | `RUN_TIMEOUT: Insufficient OHLCV data for <SYM>: <N> rows` | receipts 1 | E01-run-timeout-124 · noop_wait_recheck · auto_notify (1) |

## Per entry

| Entry | hits | lanes | signatures |
| --- | --- | --- | --- |
| [A01-flock-held](A01-flock-held.md) | 565 | 12 | 1 |
| [J01-code-defect](J01-code-defect.md) | 148 | 26 | 5 |
| [F01-executor-lost](F01-executor-lost.md) | 106 | 18 | 1 |
| [E01-run-timeout-124](E01-run-timeout-124.md) | 54 | 6 | 2 |
| [F06-effect-no-owner](F06-effect-no-owner.md) | 42 | 9 | 1 |
| [C06-output-unverifiable](C06-output-unverifiable.md) | 38 | 5 | 1 |
| [C02-empty-output](C02-empty-output.md) | 27 | 2 | 1 |
| [A03-sqlite-database-locked](A03-sqlite-database-locked.md) | 9 | 1 | 1 |
| [F02-bridge-route-refused](F02-bridge-route-refused.md) | 9 | 1 | 1 |
| [I04-invalid-config-json](I04-invalid-config-json.md) | 6 | 2 | 2 |
| [I05-env-names-missing](I05-env-names-missing.md) | 6 | 1 | 1 |
| [J03-data-defect-in-input](J03-data-defect-in-input.md) | 5 | 3 | 3 |
| [H03-schema-missing](H03-schema-missing.md) | 4 | 1 | 1 |
| [A06-effect-already-claimed](A06-effect-already-claimed.md) | 3 | 2 | 1 |
| [H05-db-connection-closed](H05-db-connection-closed.md) | 3 | 2 | 2 |
| [A04-pg-lock-not-available](A04-pg-lock-not-available.md) | 2 | 2 | 2 |
| [D02-provider-5xx](D02-provider-5xx.md) | 1 | 1 | 1 |

## Catch-all

**Zero.** Every failure signature in the window plans to an entry of its own. That is the catalog's hard requirement; `--check-gate` exits 3 if it ever stops being true.

## What this replay cannot see

- **Only what the receipts and dead letters recorded.** A lane that failed before it wrote a receipt is invisible here; the mining taxonomy covers the wider 30-day window.
- **Only the last stderr line.** A failure whose distinguishing text is an earlier line is counted under the last one; the mining taxonomy has the same limit.
- **Classification, not success.** A hit proves an entry answers the signature. It does not prove the entry's action would have worked — only a graded run does that, and none may run while the self-heal freeze holds.
- **Lanes without failures** contribute nothing; an entry at 0 hits is unexercised, not dead.

## Reproduce

```bash
python3 scripts/ops/self_heal_runbook_replay.py --as-of 2026-11-08T22:45:00+00:00 --window-days 14 \
    --out docs/runbooks/self_heal/COVERAGE.json --check-gate
```

[Workbook index](INDEX.md)
