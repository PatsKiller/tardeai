# Release train: n8n coordination contract (Phase 4)

```
Status:      DRAFT (branch feat/release-train-n8n-20261021; build-only, nothing imported, nothing armed)
as_of:       2026-10-22T00:20:00-04:00 (revision 3)
Measured at: not measured (interface contract; base origin/main 8fd1500fc + Phase 1 72d62fddc)
Owner:       platform
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0 · a request is never authority
Plan:        Release Train v2, Phase 4 (n8n coordination)
Design:      Aiden_Release_Train_Enhanced_Design_2026-10-21 §2 (trust boundaries), §6 (windows), §7 (STOP), §9
Consumers:   Phase 3 controller (feat/release-train-controller-20261021) implements §6–§8 against this file
```

**Revision 2 (2026-10-21, same day, while building the workflow against revision 1):** one window per execution
(the manual run picks the window with the oldest shadow coverage instead of looping over all four, so a refusal stays
data and a failure reaches the error route, AGENTS §23.24 FW-A4); a Run Lane `failed` now fails the execution into
`tradeai-fabric-error` (its intent is the P2) instead of a needs-action intent; the spool gained an append-only
`journal/` (the O_EXCL record; `pending/` is a hard link to it); refusal code `CONTROLLER_FAILED` added to C9;
readiness gained `shadow_coverage`; §14 is the runbook (`release-train-n8n`).

**Revision 3 (Phase 3 controller request):** C9 gained `RECONCILE_REQUIRED`, `QUARANTINED_LINEAGE` and
`CONTROLLER_ERROR`; C12 (receipts mode 0600, same-user read) and C13 (controller intents in `train_intents.jsonl`) added.
The schemas are `config/schemas/release_train/train_window_{request,receipt}.v1.schema.json`; the validator is
`scripts/lib/release_train_window_view.py` (`validate_request`, `validate_receipt`; re-exported by
`scripts/lib/release_train_window.py`).

This document is the contract between the n8n workflow `tradeai-fabric-release-train` and the host release
controller. It defines two versioned records, `TrainWindowRequest@v1` (n8n asks for a window) and
`TrainWindowReceipt@v1` (the controller answers), the read-only view n8n uses to decide and to report
(`ReleaseTrainReadiness@v1`), and the obligations on each side. Phase 3 implements the controller half against it.
Where this file and AGENTS.md differ, AGENTS.md wins and the difference is a finding (§20).

## 1. The boundary (what n8n may and may not do)

n8n **coordinates only**: it keeps time, joins readiness, asks, waits, and reports. Everything with authority stays
on the host.

| n8n does | n8n never does |
|---|---|
| fires a schedule tick per window (America/New_York) | holds a deploy, GitHub, signing or messaging credential (AGENTS §23.5) |
| reads `ReleaseTrainReadiness@v1` through the relay (read-only GET) | runs merge, promote, push, rollback, or any `release_window.py` / `release_control_cli.py` command |
| decides **no-op versus request** on that view (advisory; the host re-decides) | calls a controller mutating command directly, or any route other than the relay (§23.3) |
| asks the relay to run one allowlisted lane that **appends one request row** | names a SHA, PR, train id, capability, window time or shadow flag in a request (the host derives all of them) |
| polls the relay for the controller's receipt | treats its own execution status as evidence (§23.1, §0 rail 8) |
| posts send-**intents** (`POST /intent`); the host comms gateway decides delivery | sends Telegram or email itself, or carries any P1 (§24.1; P1 rollback alerts come from the host notifier) |

AGENTS §23.3 and §23.14 keep "release deploy" off the allowlist; the request lane is not a deploy lane: its whole
effect is one JSON file in the request spool (§5), and it imports nothing that can merge, promote, push, roll back,
issue a capability or touch the STOP latch. §24.5 (no push from a scheduled job) binds the request lane in full. Any
push, merge or promotion the controller later performs happens under the controller's own standing delegation and
phase capabilities (Phase 2), never under the request. **A request grants nothing.**

## 2. Flow

```
n8n schedule tick (W-90 request | W+75 report | manual = forced shadow, the least-covered window)
  -> GET relay /release-train-window?view=readiness          ReleaseTrainReadiness@v1   (read-only)
  -> gate (n8n, advisory):  STOP set / unreadable / unknown -> NO_OP;  not armed and shadow disabled -> NO_OP
  -> Run Lane: lane release-train-request-<HHMM>, mode dry_run|live (RunRequested@v1 -> executor)
        host lane re-reads STOP, policy, delegation, clock (authoritative) and either
        appends TrainWindowRequest@v1 to <state_dir>/train_requests/pending/   or records a no-op in its receipt
  -> controller (systemd path unit on pending/) claims pending -> claimed, re-validates everything,
        runs the train (shadow: simulate-only), writes TrainWindowReceipt@v1 to receipts/
  -> GET relay /release-train-window?run_id=<run_id>  (or ?slot=HHMM on the report tick)  until the wanted state
  -> POST relay /intent  (DIGEST per window, P2 needs-action, delegation reminder)    host comms gateway sends
P1 rollback / rollback-failed: host notifier only, from the controller. n8n reports that it happened, after the fact.
```

## 3. Windows, slots and ticks

| slot | window (ET) | role (policy) | request tick (W-90) | report tick (W+75) | request lane |
|---|---|---|---|---|---|
| `1800` | 18:00 | canary | 16:30 | 19:15 | `release-train-request-1800` |
| `0000` | 00:00 | general | 22:30 (previous day) | 01:15 | `release-train-request-0000` |
| `0600` | 06:00 | premarket_drain | 04:30 | 07:15 | `release-train-request-0600` |
| `0800` | 08:00 | premarket_last | 06:30 | 09:15 | `release-train-request-0800` |

- The request tick fires `lead_min` (90) before the window because the controller integrates and tests from
  `start - lead_min` (controller `TrainConfig.lead_min = 90`); a request at the window start would leave no time.
  The values live in `config/release_train_n8n.json` (`ReleaseTrainN8nCoordination@v1`); the generator, the lane and
  the readiness view read that one file.
- **One lane per slot, by design.** A run request names only `lane_id` and `mode` (§23.3); n8n cannot pass the window
  as an argument, and must not. The slot is in the reviewed allowlist argv (`--window 1800`), so a forged or replayed
  request cannot move a release into a different window.
- **Window identity** is computed by the host lane: the occurrence of the slot whose start is the first one at or
  after `now - grace_min`, built as a wall-clock time in America/New_York (`fold=0`, DST-safe; the same rule as
  `release_train_view.upcoming_windows`). `window_id` is `YYYY-MM-DDTHH:MM±HH:MM` (Phase 1 format).
- **Tick kind.** `on_window` when `start - lead_min - skew_min <= now < start + grace_min`
  (90 + 10 minutes before, 15 after); otherwise `off_window`. **An off-window request is always `shadow: true`.**
  A missed window is never caught up (design §6).

## 4. `ReleaseTrainReadiness@v1` (relay `GET /release-train-window?view=readiness`)

Served by the gateway's read-only operation `release_train_window` (route `coordination/status`, read-scope claim),
built by `scripts/lib/release_train_window_view.py:readiness_from_files()` from host files only: the STOP latch
(same fail-closed semantics as Phase 1's reader), `config/release_train_policy.json`, the delegation file, the
PR-hygiene receipt (census) and `config/release_train_n8n.json`. That module is stdlib-only and reads no environment,
because the gateway's import closure is part of other lanes' reviewed env inventories; the gateway passes
`<its state root>/data/runtime/release_window` as the state dir (an operator `TRADEAI_RELEASE_WINDOW_STATE_DIR`
override must equal it). The gateway holds no database credential, so `queue_counts`, `current_train` and
`last_outcome` are `null` with `queue_freshness: UNAVAILABLE`, never zero: the Command Center API (Phase 1) remains
the place for queue detail.

```json
{
  "schema": "ReleaseTrainReadiness@v1",
  "state": "OK",
  "authority": "READ_ONLY_ADVISORY",
  "as_of": "2026-10-21T20:30:00+00:00",
  "stop": {"state": "ABSENT", "effective_stop": false, "freshness": "OK"},
  "armed": false,
  "shadow_enabled": false,
  "delegation": {"state": "NOT_CONFIGURED", "source": "release_train_view.standing_policy"},
  "policy_version": "2026-10-21.1",
  "windows": [{"slot": "1800", "window_id": "2026-10-21T18:00-04:00", "starts_at": "2026-10-21T18:00:00-04:00",
               "enabled": false, "role": "canary"}],
  "queue_counts": null,
  "queue_freshness": "UNAVAILABLE",
  "census": {"status": "COMPLETE", "open_prs": 30},
  "current_train": null,
  "last_outcome": null,
  "shadow_coverage": [{"slot": "1800", "last_requested_at": null, "request_id": null, "receipt_state": null}]
}
```

- `stop.state` is `ABSENT`, `SET`, `UNREADABLE` (the `release_window.State.read_latch` vocabulary) or `UNAVAILABLE`
  (the read failed or timed out). `effective_stop` is `true` for every state except `ABSENT`.
- `delegation.state` is `ACTIVE`, `PAUSED`, `REVOKED`, `NOT_CONFIGURED`, `INVALID` or `UNAVAILABLE`. With Phase 2's
  `release_delegation.load()` importable: `AUTHORIZED` -> `ACTIVE`, `MISSING` -> `NOT_CONFIGURED`, `PAUSED`,
  `REVOKED`, and `INVALID` / `UNREADABLE` / `IN_REPO` -> `INVALID` (the request lane uses this). The gateway view
  reads the delegation file's DECLARED `status` only (`NOT_CONFIGURED` when the file is absent, `INVALID` when it is
  unreadable or names no known status): advisory, like the rest of n8n's gate.
- `shadow_coverage` lists, per slot, the newest `shadow: true` request and its receipt state (read from the spool).
  The manual run uses it to choose the window to force (§10).
- A relay or gateway failure is HTTP non-200 or `state != "OK"`; n8n treats it as STOP (`readiness_unavailable`).

## 5. `TrainWindowRequest@v1`

Schema: `config/schemas/release_train/train_window_request.v1.schema.json`. Validator and builder:
`scripts/lib/release_train_window.py`. Writer: `scripts/release_train_window_request.py` (the request lane), only
with `--append`; `--dry-run` builds and validates the row, prints it, and writes nothing but stdout.

```json
{
  "schema": "TrainWindowRequest@v1",
  "request_id": "rtw-20261021-1800-win",
  "window_slot": "1800",
  "window_id": "2026-10-21T18:00-04:00",
  "window_start": "2026-10-21T18:00:00-04:00",
  "tick": "on_window",
  "shadow": true,
  "shadow_reason": "train_not_armed",
  "requested_at": "2026-10-21T20:30:04+00:00",
  "expires_at": "2026-10-21T22:15:00+00:00",
  "requested_by": {"lane_id": "release-train-request-1800", "run_id": "rtw:release-train-request-1800:live:20261021T1630",
                   "attempt": 1, "run_mode": "live", "code_sha": "<40 hex or null>"},
  "readiness": {"stop_state": "ABSENT", "armed": false, "shadow_enabled": true, "delegation_state": "PAUSED",
                "window_enabled": false, "policy_version": "2026-10-21.1"},
  "authority": "REQUEST_ONLY",
  "note": "A request is not authority. The controller re-validates every gate; shadow=true is simulate-only."
}
```

| field | rule |
|---|---|
| `request_id` | `^rtw-[0-9]{8}-[0-9]{4}-(win\|f[0-9a-f]{6})$`. `win` for an on-window request: **one per window**, so a second on-window request for the same window collides on the file name and is recorded as `duplicate`. `f<6 hex>` (sha256 of `run_id`) for an off-window (forced) request. The date and time are the window's, local. |
| `window_slot` | `0000`, `0600`, `0800` or `1800`; from the lane's argv, never from n8n. |
| `window_id`, `window_start` | §3. |
| `tick` | `on_window` or `off_window` (§3). |
| `shadow` | `false` only when every live condition holds at request time: `tick == on_window`, policy `armed` is `true`, delegation `ACTIVE`, the window `enabled`, STOP `ABSENT`, and the lane was not started with `--shadow-only`. Otherwise `true`. |
| `shadow_reason` | `null` when `shadow` is false; else the first live condition that failed: `off_window`, `shadow_only_lane`, `train_not_armed`, `delegation_not_active`, `window_not_enabled`. |
| `expires_at` | on-window: `window_start + grace_min`; off-window: `requested_at + 60 min`. |
| `requested_by` | the executor's attempt identity (`TRADEAI_RUN_ID`, `TRADEAI_RUN_ATTEMPT`, `TRADEAI_RUN_MODE`, `TRADEAI_CODE_SHA`). `run_id` is how n8n finds the request again (§8). |
| `readiness` | the host's own snapshot when it decided. Informational for the controller, which re-reads everything. |
| `authority` | always `REQUEST_ONLY`. |

**No-op instead of a request.** When STOP is not `ABSENT` (including unreadable), or the train is neither live-able
nor `shadow_enabled`, the lane appends nothing. Its `LaneRunReceipt` records `disposition: no_op` and the reason
(`stop_set`, `stop_unreadable`, `not_armed`); `produced_count` is 0 with `empty_reason: nothing_due`. When n8n's own
gate already said no-op it does not call the lane; the DIGEST intent (§9) is then the durable host record of the
no-op (a `comms_intents` row keyed by workflow and execution).

**Spool** (under the release-window state dir, resolved exactly as `release_train_view.resolve_state_dir`):

```
<state_dir>/train_requests/journal/<request_id>.json     lane: created with O_EXCL, written, fsynced (append-only record)
<state_dir>/train_requests/pending/<request_id>.json     lane: hard link to the journal file, made after the body is durable
<state_dir>/train_requests/claimed/<request_id>.json     controller: os.rename(pending -> claimed); the rename is the claim
<state_dir>/train_requests/receipts/<request_id>.json     controller: TrainWindowReceipt@v1, tmp + fsync + rename
```

Nothing in the spool is ever deleted (§0 rule 6). Retention is an archive with a tripwire, by a later reviewed PR.

## 6. Controller obligations (Phase 3 implements these)

| # | obligation |
|---|---|
| C1 | **Untrusted input.** Validate every pending file against `TrainWindowRequest@v1` before anything else. A file that fails, has the wrong name, or whose `request_id` disagrees with its name is claimed and answered `REFUSED` / `INVALID_REQUEST`. A request carries no SHA, PR list, train id, capability or command; one that does is invalid (`additionalProperties: false`). |
| C2 | **Claim once.** Claim by `os.rename(pending/<id>.json, claimed/<id>.json)`. Only the process whose rename succeeds may act. Process claimed files in `requested_at` order. |
| C3 | **Shadow is simulate-only.** `shadow: true` runs the pipeline in dry-run mode only: the simulated GitHub writer, no capability issued or reserved, no per-day window claim file, no merge, push, promote or rollback, no STOP or epoch write, no service touched. Real reads (queue snapshot, GitHub read-only, CI evidence) are allowed. The receipt says `mode: "simulate"`. A shadow request may never produce `mode: "live"`; if it does, that is `ROLLBACK_FAILED`-class severity for the controller's own tests, not a soft warning. |
| C4 | **Live re-validates everything.** `shadow: false` is a hint, not a permission. Before acting, the controller re-checks STOP, epoch, delegation, window enabled, armed and the window being open (`window_at`, lead/grace), and again at every mutation boundary (its existing `_boundary`). Any failure is `REFUSED` with the code from C9, and nothing runs. |
| C5 | **Acknowledge fast.** Within 120 s of the pending file's creation, write a receipt with `state: ACKNOWLEDGED` (or a terminal `REFUSED`). The systemd path unit (`PathChanged=<state_dir>/train_requests/pending`) plus a 1-minute timer fallback start the claimer; the operator installs both. |
| C6 | **Expiry.** At claim time, `now > expires_at` is `REFUSED` / `EXPIRED`. A late request never starts a train. |
| C7 | **One train per window.** The controller's per-day, per-slot claim file stays the guard; a second live request for the same `window_id` is `REFUSED` / `DUPLICATE_WINDOW`. |
| C8 | **Receipts.** Written atomically (tmp + fsync + rename). `ACKNOWLEDGED` may be replaced by later states; a terminal receipt (`COMPLETED`, `REFUSED`, `EXPIRED`, `FAILED`) is never rewritten. |
| C9 | **Refusal codes** (closed set): `INVALID_REQUEST`, `EXPIRED`, `DUPLICATE_WINDOW`, `STOP_SET`, `STOP_UNREADABLE`, `NOT_ARMED`, `DELEGATION_NOT_ACTIVE`, `WINDOW_NOT_ENABLED`, `OUTSIDE_WINDOW`, `CONTROLLER_BUILD_ONLY`, `LOCK_HELD`, `SHADOW_LIVE_MISMATCH`, `CONTROLLER_FAILED` and `CONTROLLER_ERROR` (with `state: FAILED`), `RECONCILE_REQUIRED` (a non-terminal train or an ambiguous effect must be reconciled first), `QUARANTINED_LINEAGE` (the base or a member descends from a quarantined artifact). Revision 3 added the last three at the Phase 3 controller's request (`feat/release-train-controller-20261021` @ 1b1215270, `train-claim`). |
| C10 | **P1 stays on the host.** A rollback, a failed rollback, or an unacknowledged STOP is paged by the host notifier from the controller at the moment it happens. The receipt records the page (`p1_alert`); n8n only mentions it in the next digest. |
| C11 | **No authority flows back.** Nothing in a receipt is read by the controller later as input. |
| C12 | **File ownership.** The controller writes receipts mode 0600 as the portfolio-server user. The relay's `GET /release-train-window` reads them through the gateway, and the gateway runs as that same user, so no group or world read bit is needed or allowed. A receipt the gateway cannot read is `receipt_problem: receipt_unreadable`, never a missing receipt. |
| C13 | **Intent records.** `TrainEvent@v1` has no intent/effect event type, so the controller keeps its intent-before-effect rows in a local `<state_dir>/train_intents.jsonl` (append-only). This contract does not read that file; it is the controller's own reconciliation record. |

## 7. `TrainWindowReceipt@v1`

Schema: `config/schemas/release_train/train_window_receipt.v1.schema.json`. Written only by the controller.

```json
{
  "schema": "TrainWindowReceipt@v1",
  "request_id": "rtw-20261021-1800-win",
  "window_id": "2026-10-21T18:00-04:00",
  "window_slot": "1800",
  "shadow": true,
  "mode": "simulate",
  "state": "COMPLETED",
  "acknowledged_at": "2026-10-21T20:30:31+00:00",
  "finished_at": "2026-10-21T20:41:02+00:00",
  "controller": {"version": "release_train_controller/1", "code_sha": "<40 hex or null>", "host": "<hostname>"},
  "train_id": "rt-20261021-1800-a1b2c3",
  "outcome": "NO_OP",
  "refusal": null,
  "members": [{"pr": 1901, "head_sha": "<40 hex>"}],
  "candidate_sha": null,
  "main_sha": null,
  "served_sha": null,
  "needs_action": [{"code": "HELD_NEEDS_OPERATOR", "pr": 1903, "text": "scheduler/live-list change; ride approval required"}],
  "simulated_effects": ["publish train ref", "merge", "promote"],
  "injected_failures": [],
  "p1_alert": null,
  "evidence_refs": ["<state_dir>/train_events.jsonl#seq=118"]
}
```

| field | rule |
|---|---|
| `state` | `ACKNOWLEDGED` (claimed, running), then exactly one terminal state: `COMPLETED` (the train reached an outcome), `REFUSED` (with `refusal`), `EXPIRED`, `FAILED` (the controller itself failed; `refusal.detail` names the exception type only). |
| `mode` | `simulate` or `live`. `shadow: true` requires `simulate` (C3). |
| `outcome` | `TrainOutcome@v1` vocabulary (`NO_OP`, `FAILED_PRE_MERGE`, `MERGED_NOT_LIVE`, `RELEASED_VERIFIED`, `RELEASED_OBSERVING`, `ROLLED_BACK`, `ROLLBACK_FAILED`, `STOPPED`, `CANCELLED`) when `state` is `COMPLETED`; else `null`. In `simulate` mode an outcome describes what would have happened and is never a release (no fake release success, design §10). |
| `refusal` | `{"code": <C9 code>, "detail": "<= 200 chars"}` when `state` is `REFUSED`, `EXPIRED` or `FAILED`; else `null`. |
| `members`, SHAs | the frozen membership and the SHAs the controller recorded; `null`/`[]` when none. |
| `needs_action` | items the operator must act on (held rides, conflicts, failed validation, quarantine). Each becomes part of one P2 needs-action intent. At most 20 items, `text` at most 160 chars. |
| `simulated_effects`, `injected_failures` | shadow evidence: what was simulated, and which injected failure (design §10: STOP during each phase, crash recovery, failed validation) was exercised and how it behaved. |
| `p1_alert` | `{"sent_by": "host_notifier", "incident_key": "...", "at": "..."}` when the controller paged; else `null`. |

## 8. Receipt collection (relay `GET /release-train-window?run_id=<run_id>` or `?slot=<HHMM>`)

Exactly one query key: `view=readiness`, `run_id=<id>` (the Run Lane `run_id`, `RUN_ID_RE`), or `slot=<0000|0600|0800|1800>`
(the newest request for that slot whose window started within the last 24 h). Any other query is `400`.
Response `ReleaseTrainWindowView@v1`:

```json
{"schema": "ReleaseTrainWindowView@v1", "state": "OK", "as_of": "...",
 "request_state": "PENDING | CLAIMED | NOT_FOUND",
 "request": "<projection of TrainWindowRequest@v1: request_id, window_slot, window_id, tick, shadow, shadow_reason, requested_at, expires_at>",
 "receipt": "<projection of TrainWindowReceipt@v1 without evidence_refs, or null>"}
```

n8n polls with bounded backoff (5 s doubling to 60 s):

| tick | waits until | budget | when the budget ends |
|---|---|---|---|
| request (W-90) | `receipt.state` is not null (acknowledged or terminal) | 300 s | P2 needs-action `controller_unacknowledged` |
| report (W+75) | terminal | 900 s | digest reports `IN_PROGRESS` (not a failure) |
| manual (forced shadow) | terminal | 600 s | digest reports `IN_PROGRESS` |

A lane run in `dry_run` appends nothing, so its view is `NOT_FOUND`; the digest says `DRY_RUN` and n8n does not wait.

## 9. Reporting (send-intents only)

Through the relay `POST /intent` (domain `fabric`; closed table `config/n8n_comms_intent_routes.json`). The host comms
gateway decides delivery, dedupe, caps and quiet hours (§24.1). n8n holds no bot token and sends nothing.

| kind | tier | when | subject (<= 120) |
|---|---|---|---|
| `release_train_window_digest` | DIGEST | every request, report and forced tick, including no-ops | `release train <window_id> <phase>: <REQUESTED\|NO_OP\|DRY_RUN\|outcome\|IN_PROGRESS> (<reason>)` |
| `release_train_needs_action` | DIGEST (P2) | receipt `needs_action` non-empty; controller unacknowledged; readiness unavailable; receipt invalid | `release train <window_id>: needs action (<n> items)` |
| `release_train_delegation_reminder` | DIGEST | delegation `PAUSED` or `NOT_CONFIGURED`, on the 18:00 report tick and on manual runs | `release train delegation <state>: routine releases are off` |

- DIGEST becomes a P2 fan-in incident and reaches Telegram through `incident_notifier.py`'s P2 batch (held 22:00–07:00
  ET). **Email delivery of these kinds is not wired today:** the incident notifier does not email. Adding email is a
  host comms routing change (operator item O6), not a workflow change.
- **P1 rollback and rollback-failed alerts are never n8n's** (C10). The intent table has no PAGE row.
- A Run Lane `refused_policy` or `skipped_lock` is data: one `release_train_window_digest` naming the refusal, posted
  without an asserting node (§23.23 governance (5)). A Run Lane `failed` fails the execution on purpose, and
  `tradeai-fabric-error` posts its `workflow_error` intent (DIGEST, P2).
- Intents share the table's `max_per_hour: 30` budget with fabric error intents. One execution posts at most 3.

## 10. Shadow mode and forcing ticks

Shadow is the train's simulate-only phase: real queue snapshots, simulated mutations, injected failures (plan Phase 5).
It is on when `config/release_train_n8n.json` has `"shadow": {"enabled": true}` (reviewed PR) **and** the request lanes
are live-able (allowlist `live_arg` set, registry stage `canary`, lanes on the relay live list). Until the train is
armed, every request is `shadow: true`.

Shadow ends when its proof passes, with no calendar wait (operator, 2026-10-21): every window type has run cleanly
once and every injected failure behaved as specified. **Forcing ticks** compresses it to hours:

1. **Through n8n** (preferred: it also proves the coordination path). Each run of the workflow's `Manual run`
   trigger forces one window: the one whose newest shadow request is oldest (never-requested windows first, in the
   order 18:00, 00:00, 06:00, 08:00), read from readiness `shadow_coverage`. Four manual runs cover all four windows;
   each request is `off_window`, therefore `shadow: true`, and is requested, collected and digested in that run.
   On the host, under the import packet's CLI wrapper (a `cron` grant naming `tradeai-fabric-release-train`):
   `n8n execute --id=tradeai-fabric-release-train`, four times.
2. **One window, on the host, without n8n** (for the controller's own tests): `python3 scripts/release_train_window_request.py --window 0600 --dry-run`
   prints the row; with `--append --shadow-only` it appends an `off_window` shadow request (operator, under the same
   grant). This does not exercise n8n.

A forced tick can never produce `shadow: false`: an off-window request is shadow by construction (§3).

## 11. Lanes, stages and what is needed before each step

The four request lanes are fired only by this workflow through Run Lane (registry `scheduler.kind: n8n`,
`expression: tradeai-fabric-release-train`, no `dispatch` block, so the generic dispatcher never emits them).

| step | allowlist `live_arg` | registry stage | key namespace | what it produces |
|---|---|---|---|---|
| build (this PR) | `null` | `shadow` | `rtw:` (accepted for `dry_run` only) | lane receipts: the request it would append |
| train shadow | `["--append", "--shadow-only"]` | `canary` | needs a host-validated namespace (O3) | `shadow: true` requests; simulate-only receipts |
| canary (18:00) | `["--append"]` for `-1800` only | `canary` | as above | live requests for 18:00 once armed |
| expand | `["--append"]` per slot, in order 00:00, 06:00, 08:00 | `canary` | as above | live requests per proven window |

## 12. Failure handling

| failure | n8n behaviour | host behaviour |
|---|---|---|
| relay or gateway down at readiness | NO_OP `readiness_unavailable` + P2 needs-action | none |
| STOP set or unreadable | NO_OP `stop_set` / `stop_unreadable` | lane re-checks and appends nothing |
| Run Lane `refused_policy` / `skipped_lock` | digest naming the refusal (data, no error) | ledger row is the record |
| Run Lane `failed` | the execution fails -> `tradeai-fabric-error` intent (P2) | executor dead letter |
| controller does not acknowledge in 300 s | P2 needs-action `controller_unacknowledged` | the controller's independent watchdog (Phase 3) |
| receipt not terminal at the report deadline | digest `IN_PROGRESS` | the next tick's readiness `current_train` |
| receipt `ROLLED_BACK` / `ROLLBACK_FAILED` | digest mentions it | host notifier paged P1 when it happened (C10) |
| n8n down for a whole window | nothing (n8n is replaceable, §23.6) | no request, no train; the manual release path stays the fallback |
| intent not accepted | the execution fails -> `tradeai-fabric-error` | the host P1 path never depends on it |

## 13. Operator items (propose and stop)

- **O1** Review this contract (C1–C11, the two schemas, the request-tick lead) before Phase 3 builds against it.
- **O2** ~~Review the four DRAFT health contracts~~ DONE 2026-10-21: the operator reviewed all four ("approve the 4
  contracts, email yes, rtw yes, push release 2"); they are `REVIEWED` at shadow (§23.19).
- **O3** A host-validated run-key namespace for these lanes before any `live` request (the gateway refuses a
  free-form key for `live`, audit DD03). Options: a `release-train` entry in `config/n8n_fabric_processes.json`
  validated by `n8n_process_keys.py`, or a dedicated `rtw:` validator.
- **O4** Live list: add the request lanes to `TRADEAI_N8N_RELAY_LIVE_LANES` (config-write grant) when shadow starts.
- **O5** Import and activate `tradeai-fabric-release-train` under a `cron` grant naming it (§23.2), after
  `check_n8n_relay_contract.py` passes against a relay that serves `GET /release-train-window` (relay and gateway
  restart under the operator's unit grant).
- **O6** Email delivery for the DIGEST kinds (host comms routing).
- **O7** Install the controller's systemd path + timer units (Phase 3).

## 14. Runbook (`release-train-n8n`)

Every intent this workflow posts carries runbook id `release-train-n8n`; this section is that runbook.

| symptom (digest subject) | check, read-only | action |
|---|---|---|
| `NO_OP (stop_set)` / `(stop_unreadable)` | `python3 scripts/release_control_cli.py status` on the host (Phase 2), or read `<state_dir>/STOP.json` | intended while STOP is latched; resuming is an operator act (design §7) |
| `NO_OP (readiness_unavailable)` | relay log `data/runtime/n8n_relay/relay_log.jsonl` rows `op: release_train_window`; gateway health | restore the relay/gateway (operator unit); n8n treats it as STOP meanwhile |
| `NO_OP (not_armed)` | `config/release_train_n8n.json` `shadow.enabled`, `config/release_train_policy.json` `armed`, the delegation state | expected until shadow or arming; both are operator acts |
| `DRY_RUN` | the lane receipt `data/runtime/release-train-request-<HHMM>_last.json` is NOT written by a dry run; the DRY-RUN line is in the executor's run receipt | expected while `live_arg` is null (§11) |
| `UNACKNOWLEDGED` / needs action `controller unacknowledged` | `<state_dir>/train_requests/pending/` still holds the request; the controller path unit's journal | start or repair the controller units (operator, O7); never edit the spool by hand |
| `REFUSED (<code>)` | the receipt's `refusal`; C9 | act on the code; `INVALID_REQUEST` is a finding against the lane |
| `REFUSED_POLICY` / `SKIPPED_LOCK` | coordination ledger `runs` row for the run id | a lane not allowlisted / not on the live list, or a second fire holding the lock |
| `workflow_error` intent from `tradeai-fabric-error` | n8n execution (error saved) + ledger row | a Run Lane failure or an unaccepted intent; the error intent itself is the P2 |
| `ROLLED_BACK` / `ROLLBACK_FAILED` in a digest | the P1 already sent by the host notifier (`p1_alert`) | follow the incident runbook (`docs/runbooks/INCIDENT_RESPONSE.md`); n8n does nothing more |

Rollback of this workflow: unpublish it (`docs/ops/ROLLBACK_COMMANDS.md`); nothing host-side needs undoing. The
manual release path (operator grant + `cio_phase2_exact_main_deploy.sh`) is the fallback throughout.
