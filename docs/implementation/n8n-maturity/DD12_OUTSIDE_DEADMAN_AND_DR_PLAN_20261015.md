# DD12 / DD10 — outside dead-man, business heartbeat and coordinated-state restore (2026-10-15)

Source: third-party n8n architecture due diligence, 15 October 2026, §13 "Recovery independence and disaster
recovery", gap register DD10 (restore drill false green, P1 new) and DD12 (outside dead-man / full DR incomplete,
P1 known). This document is the design and the plan. What is implemented in this PR is marked **(built)**; the
rest is **(plan)** with an owner and an acceptance test. Activation of anything that runs on a timer, holds a
secret or calls a provider is operator-only (packet: `docs/ops/packets/n8n-dd12-outside-deadman-20261015/`).

## 1. What the audit asked for

| Ask | Audit wording | Status here |
|---|---|---|
| Backup validity | verified hash and age, zero restore errors, critical-table row/content checks, nonzero expected workflow inventory | **(built)** drill v2 |
| Keys and application | decrypt one inert credential with the escrowed key; start an isolated app; published workflow/manifest parity | key decrypt **(built)**; isolated app start **(plan §5.2)** |
| Failure exit | a false verdict must fail | **(built)** exit 1 + FAILED receipt + P1 |
| Outside liveness | detect host/network/power failure without sharing host, storage or the sole delivery dependency | **(built earlier, PR #1751)** `scripts/offbox_deadman.py`; not activated |
| Business heartbeat | detect a running scheduler that produces no useful work | **(built)** second external check, `config/offbox_business_heartbeat.json`; not activated |
| Deadlines, escalation, failure-to-deliver fallback | declared | **(built)** §3 table; fallback = the off-box provider |
| Power/network-loss test | harmless, scheduled | **(plan §4)** operator drill |
| Coordinated authority state | restore SQLite runs/owners/claims, workflow state and approvals consistently; refuse ambiguous live work | **(plan §5)** |
| Replay protection | no duplicate effect or stale approval replay after restore | **(plan §5.4)** |
| Continuity objectives | measured RPO/RTO, protected off-host copy, full-host drill | **(plan §6)** |

## 2. Restore drill v2 (DD10) — built

`scripts/n8n_lab_restore_drill.sh` now collects facts and `scripts/lib/n8n_lab_restore_verdict.py` decides. PASSED
requires all of: `restore_clean` (pg_restore rc 0 and no `pg_restore: error` / `errors ignored on restore` line),
`tables_match_live`, `manifest_present`, `dump_sha_matches`, `workflows_nonzero`, `workflows_match` (inside the
manifest's before/after dump-time counts), `credentials_match`, `required_ids_present` (the fabric workflows,
`config/n8n_lab_restore_drill.json`), `manifest_ids_present`, `executions_restorable`, `credential_key_decrypts`
(one restored credential decrypts inside the n8n app container; `scripts/lib/n8n_credential_key_probe.js` prints one
word and never the key or plaintext) and `drill_db_dropped`. Anything else: receipt `state: FAILED`, exit 1; an abort
mid-drill still writes a FAILED receipt (EXIT trap) and drops the drill database.

`scripts/n8n_lab_backup.sh` writes `<dump>.manifest.json` (sha256, workflow/credential counts before and after the
dump, workflow ids present at both reads) and exits 1 when its receipt is not ok. Fixed on the way: an empty TOC made
`grep -c … || echo 0` print `0\n0`, which crashed `int()` before any receipt was written.

Paging: `scripts/n8n_incident_fanin.py` source `n8n_lab_restore_drill` — FAILED (or a v1 receipt with ok false) is
**P1**, which `scripts/incident_notifier.py` sends at once, uncapped and through quiet hours; a receipt older than
8 days is P2. Off-box: the business heartbeat (§3) also fails on a FAILED drill, so a host whose notifier is down
still surfaces it.

Tests: `tests/test_n8n_lab_restore_drill_verdict_20261015.py` (fake `docker` / `pg_restore` on PATH; 13 negative
fixtures including the audit's exact rc=1 / 157-of-157 / zero-workflow case, bad key, key unavailable, missing
workflow and credential rows; the key probe under node.js with a synthetic key).

First production run after merge: the newest dump must carry a manifest, so the first drill after deploy PASSES only
if a nightly backup ran with the new script first (nightly 03:30 runs before the Sunday drill). A drill that finds an
old dump without a manifest FAILS by design (`manifest_present`) and pages; that is the fail-closed choice.

## 3. Two outside heartbeats, deadlines and escalation

| Signal | Watches | Sender (host) | Watcher (off-host) | Deadline | Escalation | Failure-to-deliver fallback |
|---|---|---|---|---|---|---|
| Alert-path dead-man | notifier ran + delivered (15 min), fan-in fresh (30 min), heartbeat-watch looking (30 min) | `offbox_deadman.py` (default config), own timer | provider check A (pull-on-miss) | provider period 5 min + grace 10 min | provider email (+ phone push if the operator adds it) | none needed: silence IS the alarm |
| Business-output heartbeat | scalp cycle in RTH (15 min), nightly n8n backup (36 h), weekly restore drill PASSED (8 d) | `offbox_deadman.py --config config/offbox_business_heartbeat.json`, own timer | provider check B (separate UUID) | provider period 15 min + grace 15 min | provider email | silence IS the alarm |
| On-host P1 | every fan-in P1, incl. restore drill FAILED | `incident_notifier.py` (Telegram) | operator | immediate | P1 re-notify per dedupe window | the two off-box checks above |

Independence: both senders are stdlib-only, import nothing local (test-pinned), and run from their own systemd timers,
never from n8n or the health tick. A dead host, a dead uplink or a power cut stops both pings; the provider alerts.
The business check cannot be kept green by a healthy alert path (separate URL), and vice versa.

Known false positive: `scalp_cycle_rth` on an exchange holiday (the market-day gate skips the lane). The operator
pauses check B on holidays or accepts one email; the stdlib sender has no market calendar on purpose.

## 4. Power / network-loss drill (plan; operator)

Harmless test, quarterly, outside market hours: (1) note both provider checks green; (2) `systemctl --user stop` both
dead-man timers for 30 minutes (simulates a dead host without touching the host) and confirm two provider emails;
(3) restart, confirm recovery emails; (4) once per year, a real uplink pull for 20 minutes with the same check.
Receipt: the provider's alert log screenshot path recorded in `docs/RESTORE_GUIDE.md` §0. Acceptance: both alerts
arrive within period + grace; nothing on the host is changed by the drill.

## 5. Coordinated authority state restore (plan)

The n8n lab dump restores Postgres (`workflow_entity`, `credentials_entity`, `execution_entity`). The authority
plane is elsewhere and is not in that dump:

| Store | Path | Holds | Restore risk |
|---|---|---|---|
| Coordination ledger | `data/governance/n8n_coordination_ledger.sqlite` | `runs` (REQUESTED/RUNNING/RUN_DONE…), owners/epochs, effect claims, `comms_intents`, dead letters, breakers | a stale copy re-opens claims and re-queues runs |
| Approvals (proposed, TARGET_ARCHITECTURE §5) | not yet built | approval requests / decisions | a restored approval could be replayed |
| Business stores | `trade_ai` Postgres, persistent-state receipts | effects already applied | target state is newer than the ledger |

### 5.1 Snapshot consistency (plan)

Back the ledger up with `sqlite3 .backup` (online, consistent) in the same platform-maintenance-nightly step as the
n8n dump, record both in one manifest with a shared `snapshot_id`, and the ledger's high-water marks (max run id,
max claim id, owner epoch). Acceptance: the drill restores both into throwaway locations and checks the manifest.

### 5.2 Isolated application start (plan)

Start an `n8nio/n8n` container on a throwaway network with the restored DB and the escrowed key, no egress, no relay
route; wait for `/healthz`; compare the published workflow ids and `versionId`s with the manifest; stop and remove.
Needs a `service` grant (it starts a container); not in the hermetic scope of this PR.

### 5.3 Refuse ambiguous live work after restore (plan)

On restore, before any live lane runs: every `RUNNING` / `REQUESTED` row and every open effect claim from the
restored ledger becomes `AMBIGUOUS_AFTER_RESTORE`; the executor refuses live runs for a lane with an ambiguous
claim until its target state is reconciled (DD05); owner epochs are bumped so a pre-restore worker cannot complete
(DD06). Acceptance (hermetic): a restored ledger fixture with RUNNING rows and open claims -> no live admission until
reconcile; a pre-restore owner epoch is refused.

### 5.4 Replay protection (plan)

Approvals (when built, DD13) carry nonce + expiry + single-use consumption recorded in the business store, not only
the ledger; a restored ledger cannot resurrect a consumed approval because consumption is checked against the newer
store. Effect keys already bind business slots (`effect_claim`); after restore, a claim older than the snapshot is
never reopened automatically. Acceptance: stale-restore fixtures for approval replay and claim reopen both fail
before effect.

## 6. Continuity objectives (plan; operator decision)

State RPO/RTO per tier (proposal: n8n lab RPO 24 h / RTO 4 h; coordination ledger RPO 24 h; `trade_ai` per
`docs/RESTORE_GUIDE.md` §0), protect an off-host copy of the n8n dump + manifest + ledger snapshot (encrypted, key
escrow separate), and run one full-host drill on spare hardware. Measured RTO is the drill's wall-clock; measured RPO
is the age of the newest restorable snapshot at drill time.

## 7. Owners

| Item | Owner | Gate |
|---|---|---|
| Drill v2, manifest, fan-in P1 | platform (this PR) | merge |
| Business heartbeat activation | operator | packet `n8n-dd12-outside-deadman-20261015` (provider check B, secret, timer) |
| Power/network drill | operator | quarterly |
| §5 coordinated restore | platform + recovery | DD05/DD06/DD13 land first |
| §6 RPO/RTO | operator | decision |
