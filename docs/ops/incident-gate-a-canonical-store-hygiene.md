# Gate A Canonical Store Hygiene Incident

**Incident ID**: INC-2026-08-09-GATE-A-STORES
**Classification**: Development hygiene violation (not a runtime integrity failure)
**Severity**: LOW (canonical content matched R0.1 baseline after cleanup)
**Status**: CLOSED — evidence preserved

## Affected Gate-A SHA

`443a9c88216bdb7e945894f0756a9fd98d6c090d`

## Affected canonical paths

| Path | Pre lines | Post lines | SHA-256 (post) |
|------|-----------|------------|----------------|
| `data/cio/cio_events.jsonl` | 37 | 37 | `35fd5d6b...f88789` |
| `data/cio/cio_event_cursors.jsonl` | 2 | 0 | `e3b0c442...7852b855` |

## Events written during development

- 2 interactive test events: `evt-6f6e592323e1`, `evt-e702f4c693fa` (source=test)
- 20 heartbeat-test events (source=cio_heartbeat, IDs not catalogued)
- 2 cursor records: test-consumer, testcons

## Mutation

Non-append truncation via open('w') on both files. Violated append-only governance contract.

## Root cause

Heartbeat test used default CIOEventBus path before monkeypatching was applied.
Interactive R1.2 exploration wrote cursor records directly.

## Remediation

All Gate A.1 + Gate A Final tests now use temp stores and monkeypatched bus paths.
The 37 remaining events match R0.1 baseline content. verify_integrity() PASS.

## Permanent limitation

**pre_Gate_A_CIO_event_bus_historical_hash_integrity = NOT_PROVEN**

## Future audit requirement

```
current_event_store_structure = VERIFIED
current_chain_linkage = VERIFIED
Gate_A_new_format_hash_integrity = VERIFIED
pre_Gate_A_historical_hash_integrity = NOT_PROVEN
Gate_A_test_store_hygiene_incident = ACKNOWLEDGED
```

## Post-incident baseline (2026-08-09)

| Store | Lines | SHA-256 |
|-------|-------|---------|
| cio_events.jsonl | 37 | 35fd5d6b4cd77ac0a77371134e87ee30ff518050a26cc3c3b5b2722cb2f88789 |
| cio_action_ledger.jsonl | 104 | f9bae1d0f5ee929aa43886e556cd7d569a9022b96e18cfc191b722ad7da6d477 |
| cio_wake_jobs.jsonl | 3 | 468df188302bacb6374265359f91ccdcda3e8941171c325d0c012397b14b743c |
| agent_handoff_queue.jsonl | 3 | cb476187f0108291f43a6f0740d14c93aaa3ec666d715d07a1ee1258c48b0aa3 |
| hermes_challenge_queue.jsonl | 2 | a17f25e00ef837b4b07ca9294f1da01b94a7431542dc834b4c07f154062d9a66 |
| operator_notification_outbox.jsonl | 4 | 0cb2bdd43f28921c6cef414005c25c4c3832af566a1cba656d1b1d4886e02e94 |
| cio_event_cursors.jsonl | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
