# Release train: Command Center UI contract and the STOP RELEASES endpoint

```
Status:      DRAFT (branch feat/release-train-cc-20261021; build-only, nothing armed)
as_of:       2026-10-21
Owner:       platform
Authority:   READ_ONLY_ADVISORY for every read · the one write is the set-only release STOP latch · MBI_BEHAVIOR = 0
Plan:        Release Train v2, Phase 1 (read-only CC view) + Phase 2 STOP pulled forward on purpose
Design:      Aiden_Release_Train_Enhanced_Design_2026-10-21 §7 (Command Center and the kill switch)
Read API:    docs/ops/RELEASE_TRAIN_API.md (feat/release-train-queue-20261021, 67f83711a)
```

The **Release train** tab (`/v3/coordination?tab=release`) and the Home card read the four routes in
`RELEASE_TRAIN_API.md` and the STOP route defined here. This document defines the STOP route, says how the UI maps
each read field, and lists what the read API still needs to reconcile.

## 1. STOP RELEASES: `/api/v2/coordination/release-train/stop`

The route writes the **same latch** that `scripts/release_window.py` obeys: `State(STATE_DIR).latch`, which is
`<TRADEAI_RELEASE_WINDOW_STATE_DIR or ~/trade-ai-releases/persistent-state/data/runtime/release_window>/STOP.json`.
`Runner._preconditions` refuses every window with `REFUSED_STOP_LATCHED` while that file holds a non-empty JSON
object. The backend is `scripts/lib/release_train_stop.py`, wired at the top of `api_v2.handle()`.

**It is the release STOP, not the trading kill switch.** It never reads or writes
`/api/v2/execution/kill-switches/*`, and trading containment, stops and monitoring keep running.

### 1.1 `POST` sets a STOP; it never clears one

Request body (`Content-Type: application/json`):

```json
{"reason": "bad batch in flight, hold releases", "idempotency_key": "cc-stop-<uuid>"}
```

| check, in order | refusal (`refusal`) | HTTP |
|---|---|---|
| The actor is the authenticated cc_auth principal, `tailnet:<login>`. A service token, a report-only pass-through or an unauthenticated request is not an operator. A body `actor` is ignored, and the audit row records `body_actor_ignored`. | `NO_OPERATOR_IDENTITY` | 403 |
| CSRF is enforced twice. (1) The gate: the route is a `csrf.hard_routes` entry (`release_train_command`), enforced even with `report_only: true` or `enforce: false`. (2) The handler: `cc_auth.command_csrf_check` re-runs the check from the gate's request context. It needs an allowlisted `Origin`, or `Sec-Fetch-Site: same-origin`, plus a JSON content type. With no gate context it fails closed. | `CSRF` | 403 |
| Set-only. A body `action` other than `"stop"`, or a key such as `clear`, `resume`, `unlatch` or `reset`, is refused. So is any non-GET method on `/stop`, and any non-GET request to another path under `/release-train`. | `SET_ONLY` | 400 |
| `reason` is 8–500 characters after trimming. | `REASON_REQUIRED` | 400 |
| `idempotency_key` matches `^[A-Za-z0-9._:-]{16,128}$`. The UI makes one key per button press, and a retry of that press reuses it. | `IDEMPOTENCY_KEY_REQUIRED` | 400 |
| The same key with a different reason. | `IDEMPOTENCY_KEY_REUSED` | 409 |
| The same key after the latch was cleared on the host. | `IDEMPOTENCY_KEY_SPENT` | 409 |

There is **no step-up**. The operator declined TOTP, and stopping is the safe direction, so the route is in neither
`step_up.routes` nor `always_refuse`.

Effect, under a CC-only lock (`<state dir>/cc_stop/.lock`; the runner's `.lock` is never taken):

- **Latch absent.** The latch body is serialised by the runner's own `State.write` to
  `cc_stop/latches/<stop_id>.json`, then published with `os.link` to `STOP.json`. A link never replaces an existing
  file, so a rollback latch the runner writes in the same instant is never overwritten.
- **Latch readable (SET).** Nothing is written, the latch is kept byte for byte, and the outcome is
  `ALREADY_STOPPED`.
- **Latch present but unreadable.** Main's reader treats this as absent, which is fail-open (Phase 0 item 4). The
  file is archived to `windows/STOP-unreadable-<stamp>-<id>.json.archived` (never deleted) and a readable latch is
  written.

The latch body, which `release_window.py status` and `clear-stop` handle unchanged:

```json
{"latched_at": "<UTC>", "window_id": null, "outcome": "STOP_REQUESTED_OPERATOR", "candidate": null,
 "source": "command_center", "actor": "tailnet:<login>", "reason": "<text>", "stop_id": "rts-<stamp>-<8 hex>",
 "detail": "release windows halted by an operator STOP; resume is host-CLI-only: ..."}
```

Response (`ReleaseTrainStopResult@v1`). The acknowledgement **is** the server reading the latch back after the
write:

```json
{"ok": true, "schema": "ReleaseTrainStopResult@v1", "outcome": "STOP_SET | ALREADY_STOPPED | STOP_NOT_CONFIRMED",
 "phase": "acknowledged", "stop_id": "rts-...", "actor": "tailnet:<login>", "reason": "...",
 "requested_at": "<server UTC>", "acknowledged_at": "<server UTC, set only when the read-back is SET>",
 "latch": {"status": "SET", "body": {"...": "..."}, "path": ".../STOP.json"}, "archived_unreadable_latch": null,
 "replayed": false, "resume": {"policy": "...", "command": "python3 scripts/release_window.py clear-stop --reason ..."},
 "separate_from_trading_kill_switch": true}
```

`STOP_NOT_CONFIRMED` returns HTTP 500. A refusal body is
`{"ok": false, "outcome": "REFUSED", "refusal": "<code>", "error": "<text>", "resume": {...}}`.

**Audit.** Every attempt, whether accepted, replayed or refused, appends one JSON row to
`<state dir>/cc_stop/audit.jsonl`, opened with `O_APPEND` and fsynced. A row holds:

- `at`, `event` (`stop_set`, `already_stopped`, `replayed` or `refused`) and `refusal`;
- `actor`, `source`, `reason`;
- `idempotency_key_sha256` (the key itself is never stored);
- `stop_id`, `latch_status_before` and `latch_status_after`;
- `acknowledged_at` and `existing_latch_outcome`.

### 1.2 `GET` reads the latch back

`ReleaseTrainStopStatus@v1` returns:

- `as_of` and `state_dir`;
- `latch {status: SET | ABSENT | UNREADABLE, body, path, mtime}`;
- `window_run_lock` (`HELD` / `FREE` / `UNKNOWN`), parsed read-only from `/proc/locks` for the runner's
  `<state dir>/.lock`. The lock itself is never taken;
- `phase` (`stopped` / `settling` / `running` / `unknown`);
- `runner_reader` (`fail_closed` once the served `release_window.py` has `State.read_latch`, else
  `main_fail_open`) and `reader_note`;
- `audit_tail` (the last 20 rows), `resume {policy, command}` and `separate_from_trading_kill_switch: true`.

### 1.3 The states the UI shows

| step | meaning | timestamp |
|---|---|---|
| requested | This browser sent the POST. | browser clock |
| acknowledged | The server wrote `STOP.json` and read it back as SET (`ok: true`). | `acknowledged_at` (server) |
| settling | An independent GET reads SET, and a window holds its run lock. That window finishes its bounded verify or rollback; nothing new starts. | that GET's `as_of` |
| stopped | An independent GET, fresh (≤ 120 s) and taken at or after `acknowledged_at`, reads SET, and no window holds the lock. | that GET's `as_of` |

A transport failure is shown as **STOP NOT CONFIRMED**, together with the host fallback
`python3 scripts/lib/release_train_stop.py stop --reason "..."`. That fallback is the same writer, with actor
`host-cli:<user>`. A status that cannot be read shows as "STOP state UNAVAILABLE — treat as STOPPED" (API rule 3).
An unreadable latch under main's fail-open reader shows as "the served runner reads it as NOT SET: press STOP",
never as stopped.

**Resume is host-CLI-only** (operator decision D3): `python3 scripts/release_window.py clear-stop --reason "..."`.
The UI shows this command and has no resume control.

## 2. How the UI maps the read API (RELEASE_TRAIN_API.md)

| UI element | source |
|---|---|
| Next window | `summary.next_window.value`: `local_time`, `role` and `starts_in_seconds`. It shows "not armed" unless both `enabled` and `armed.value` are `true`. |
| Ready / held | `summary.queue_counts.value.ready` / `.held`. When unavailable it shows `UNAVAILABLE (<reason>)`, never 0. |
| Last outcome (Home) | `summary.last_outcome.value`, mapped to its outcome class. |
| Last verified (tab) | The newest `RELEASED_VERIFIED` train in `/events` (newest 500). |
| Current train | The first `/queue` row in an in-train state (`selected`, `integrating`, `qualified`, `waiting_window`, `merged`, `promoting`) that has a `train_id`. |
| Standing policy | `summary.standing_policy.value.state` plus `armed.value`. `NOT_CONFIGURED`, `PAUSED` and unknown states are a warning, never success. |
| Census gauge | `summary.census` (or `queue.census`). The gauge shows INCOMPLETE unless `status == COMPLETE`, `invariant_holds === true`, `incomplete_reasons` is empty, every bucket count is measured and `open_prs == sum(counts)`. |
| Queue table | `/queue.rows`: `pr_number`, `title`, `agent`, `state`, `risk_class` (with `risk_reasons` as the hover text), `depends_on`, `age_seconds` (falling back to `submitted_at`), `blocker`, `next_action` and `intended_window`. `store_state != OK` is shown. |
| Train detail | `/trains/{id}.train`: `members` in `order`, then base, candidate, main and served SHAs, artifact, rollback target, check manifest, `elapsed_seconds`, and `events` as the timeline. A served SHA that differs from the candidate is flagged. |
| History | `/events`, grouped by `train_id`. The outcome comes from `payload.outcome`, then `payload.history_class`, then `state_after`. `MERGED_NOT_LIVE`, `RELEASED_VERIFIED`, `RELEASED_OBSERVING`, `ROLLED_BACK` and `ROLLBACK_FAILED` stay five separate categories. `NO_OP`, `FAILED_PRE_MERGE`, `CANCELLED` and `STOPPED` map to "not shipped". |

Freshness: each `Field` keeps its own `freshness`, and an OK field inside a response kept after a failed poll is
STALE. A response whose `generated_at` is more than 15 minutes old is STALE. Every path is in
`RELEASE_TRAIN_PATHS` (`apps/command-center-v3/src/lib/releaseTrain.ts`).

## 3. Reconciliation items for the read API

1. **No current-train field in the summary.** The UI derives it from `/queue`. A
   `summary.current_train: Field<{train_id, phase, window_id}>` would be authoritative and would save the Home card
   one request.
2. **No last-verified field.** `last_outcome` can hold a non-verified outcome. Either add
   `summary.last_verified: Field<LastOutcome>`, or accept that the Home card shows "last outcome", which it does
   today.
3. **No trains list.** History is rebuilt from `/events?limit=500`. Trains older than the newest 500 events drop out,
   and the window id and member count are only present when an event payload carries them. A `GET /trains` returning
   `{train_id, window_id, history_class, outcome, started_at, finished_at, candidate_sha, served_sha, members}` would
   replace the grouping.
4. **Method handling.** `RELEASE_TRAIN_API.md` §1.5 says that any non-GET request returns `405`. On this branch, a
   non-GET request to any path under `/release-train` is intercepted first and refused by the STOP handler: 403
   without operator identity or same-origin, otherwise 400 `SET_ONLY`. Nothing is ever written. Merge order: either
   order works, because the STOP block sits above the read routes in `handle()`.
5. **Two STOP reads.** `summary.stop` (`CLEAR` / `LATCHED` / `UNREADABLE`) and `GET /stop` (`ABSENT` / `SET` /
   `UNREADABLE`, plus lock and audit) read the same file with different vocabularies. The STOP control uses `GET /stop`.
   The summary chip uses `summary.stop`.
6. **State dir.** The server process and the host runner resolve the state dir from the same env and default (`HOME`
   is the same). Before arming, the operator confirms that `GET /stop`'s `state_dir` equals the path
   `release_window.py status` reads.
