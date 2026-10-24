# Release train: read-only Command Center API (Phase 1)

```
Status:      DRAFT (branch feat/release-train-queue-20261021; build-only, nothing armed)
as_of:       2026-10-21T19:10:00-04:00 (revision 2)
Measured at: not measured (shape contract; base origin/main 7faa8cddf)
Owner:       platform
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
Plan:        Release Train v2, Phase 1 (queue + read-only Command Center)
Design:      Aiden_Release_Train_Enhanced_Design_2026-10-21 §4, §7, §9
```

This document is the response contract for the five read-only GET routes under
`/api/v2/coordination/release-train`: the summary, `/queue`, `/trains`, `/trains/{id}` and `/events`. The Command Center "Release train" tab (Coordination) and the Home card
build against it. The backend is `scripts/lib/release_train_view.py`, wired in `scripts/api_v2.py`.

Nothing here writes, merges, pushes, releases or arms anything. The STOP command and its read-back
(`GET` / `POST .../release-train/stop`) and every other non-GET under `/release-train` belong to the STOP block of
branch `feat/release-train-cc-20261021` (`scripts/lib/release_train_stop.py`,
`docs/ops/RELEASE_TRAIN_UI_CONTRACT.md`). This view never answers them: its handler returns nothing for them, so the
request falls through to that block.

**Revision 2 (2026-10-21, coordinator request from the frontend build):**

- added `summary.current_train`, `summary.last_verified` and `summary.state_dir`;
- added `GET .../trains` (paginated list);
- `stop.value.state` now uses the `release_window.State.read_latch` vocabulary, `ABSENT` / `SET` / `UNREADABLE`.
  It replaces `CLEAR` / `LATCHED` / `UNREADABLE`;
- non-GET requests no longer get a `405` from this view.

## 1. Rules every consumer must follow

1. **Missing data is never zero and never green.** A count the backend could not read is `null` with
   `freshness: "UNAVAILABLE"`. Render it as UNAVAILABLE with the `reason`. Never coerce `null` to `0`.
2. **Every summary field is a `Field` envelope** (section 2). Collections (`/queue`, `/events`, `/trains/{id}`)
   carry one envelope at the collection level, and every row carries its own `as_of`.
3. **STOP fails closed.** If `stop.freshness` is `UNAVAILABLE`, or `stop.value.effective_stop` is `true`, show
   releases as STOPPED. The release STOP is not the trading kill switch; never label it as one.
4. **`armed` is `false` in Phase 1** and `standing_policy.value.state` is `"NOT_CONFIGURED"`. Show both plainly;
   a window time is a permitted opportunity, not a scheduled deployment.
5. **HTTP status.** `200` with `{"ok": true, "data": ...}` whenever the handler ran, including when every source is
   UNAVAILABLE. `400` bad parameter, `404` train not found (only when the store was readable), `500` handler failure (`error` is an exception type name, never a trace). Error bodies are
   `{"ok": false, "error": "<code>", "detail": "<text or absent>"}`. This view is GET-only. A non-GET request, or
   any request for `.../stop`, is not answered here and falls through to the STOP block (see above).
6. **Timeouts.** Each source is read off the request thread in a worker pool with its own deadline. The whole
   response waits at most `timeout_s` (3.0 s). A source that misses its deadline is `UNAVAILABLE` with
   `reason: "timeout"`. Responses are cached for 15 s per route and query.

## 2. The `Field` envelope

```json
{
  "value": "<any JSON value, or null>",
  "as_of": "2026-10-21T21:30:00+00:00",
  "freshness": "OK",
  "source": "postgres:release_queue",
  "reason": null
}
```

| key | type | meaning |
|---|---|---|
| `value` | any or `null` | The measurement. Always `null` when `freshness` is `UNAVAILABLE`. |
| `as_of` | ISO-8601 string with offset, or `null` | When the value was measured (not when the response was built). `null` only when nothing was ever measured. |
| `freshness` | `"OK"` \| `"STALE"` \| `"UNAVAILABLE"` | `OK`: read now, or within its freshness budget. `STALE`: the last known value, older than its budget; show its age. `UNAVAILABLE`: could not be read. |
| `source` | string | Where the value came from, for example `postgres:release_queue`, `receipt:pr-hygiene-audit`, `file:release_window/STOP.json`, `config/release_train_policy.json`, `clock`. |
| `reason` | string or `null` | Why it is STALE or UNAVAILABLE, or a qualifying note on an OK value (for example `no_outcome_recorded`). |

`reason` codes used for UNAVAILABLE:

| reason | meaning | operator action |
|---|---|---|
| `not_migrated` | `release_queue_events` / `release_queue` do not exist. | Apply `migrations/2026_10_21_release_queue.sql` (operator item). |
| `db_unavailable` | The database did not answer. | Check Postgres; Platform health shows it. |
| `timeout` | The source missed its deadline. | Retry; persistent timeouts are a finding. |
| `no_receipt` | The PR-hygiene lane has not written a receipt (it writes none at SHADOW). | Promote the lane, or run it once. |
| `receipt_unreadable` | The receipt exists but cannot be parsed. | Inspect the receipt file. |
| `error:<Type>` | Unexpected failure in the reader. | A finding; the type name is the evidence. |

## 3. `GET /api/v2/coordination/release-train` — summary (Home card and tab header)

No query parameters.

```json
{
  "ok": true,
  "data": {
    "schema": "ReleaseTrainSummary@v1",
    "authority": "READ_ONLY_ADVISORY",
    "generated_at": "2026-10-21T21:30:00+00:00",
    "status": "DEGRADED",
    "timeout_s": 3.0,
    "armed": {"value": false, "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK",
              "source": "config/release_train_policy.json", "reason": "phase_1_build_only"},
    "standing_policy": {
      "value": {"state": "NOT_CONFIGURED",
                "detail": "No standing delegation record exists (Phase 2, operator-applied)."},
      "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK",
      "source": "config/release_train_delegation.json", "reason": null
    },
    "next_window": {
      "value": {
        "window_id": "2026-10-21T18:00-04:00",
        "local_time": "18:00",
        "timezone": "America/New_York",
        "starts_at": "2026-10-21T18:00:00-04:00",
        "starts_in_seconds": 1800,
        "role": "canary",
        "enable_order": 1,
        "enabled": false,
        "note": "First live canary window."
      },
      "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK", "source": "clock", "reason": null
    },
    "windows": {
      "value": [
        {"window_id": "2026-10-21T18:00-04:00", "local_time": "18:00", "timezone": "America/New_York",
         "starts_at": "2026-10-21T18:00:00-04:00", "starts_in_seconds": 1800, "role": "canary",
         "enable_order": 1, "enabled": false, "note": "First live canary window."},
        {"window_id": "2026-10-22T00:00-04:00", "local_time": "00:00", "...": "..."},
        {"window_id": "2026-10-22T06:00-04:00", "local_time": "06:00", "...": "..."},
        {"window_id": "2026-10-22T08:00-04:00", "local_time": "08:00", "...": "..."}
      ],
      "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK", "source": "clock", "reason": null
    },
    "queue_counts": {
      "value": {"ready": 2, "held": 5, "needs_operator": 3, "blocked": 1, "in_train": 0, "other": 0, "total": 11},
      "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK", "source": "postgres:release_queue", "reason": null
    },
    "current_train": {
      "value": {"train_id": "rt-20261021-1800-a1b2c3", "phase": "integrating", "member_count": 2,
                "window_id": "2026-10-21T18:00-04:00", "started_at": "2026-10-21T20:30:00+00:00"},
      "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK", "source": "postgres:release_queue_events",
      "reason": null
    },
    "last_verified": {
      "value": {"train_id": "rt-20261020-1800-9f8e7d", "served_sha": "<40 hex>",
                "verified_at": "2026-10-20T22:41:07+00:00", "outcome": "RELEASED_VERIFIED",
                "window_id": "2026-10-20T18:00-04:00"},
      "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK", "source": "postgres:release_queue_events",
      "reason": null
    },
    "last_outcome": {
      "value": {
        "train_id": "rt-20261021-1800-a1b2c3",
        "window_id": "2026-10-21T18:00-04:00",
        "outcome": "RELEASED_VERIFIED",
        "finished_at": "2026-10-21T22:41:07+00:00",
        "members": [1901, 1903],
        "candidate_sha": "<40 hex>",
        "main_sha": "<40 hex>",
        "served_sha": "<40 hex>"
      },
      "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK", "source": "postgres:release_queue_events",
      "reason": null
    },
    "stop": {
      "value": {
        "state": "ABSENT",
        "effective_stop": false,
        "latched_at": null,
        "window_id": null,
        "latch_reason": null,
        "reader": "file",
        "path": "<state dir>/STOP.json",
        "state_dir": "<state dir>",
        "state_dir_source": "release_window.STATE_DIR",
        "note": "Release STOP only. The trading kill switch is separate."
      },
      "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK", "source": "file:release_window/STOP.json",
      "reason": null
    },
    "state_dir": {
      "value": {"path": "/home/<user>/trade-ai-releases/persistent-state/data/runtime/release_window",
                "source": "release_window.STATE_DIR"},
      "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK", "source": "release_window.STATE_DIR", "reason": null
    },
    "census": {"value": "<Census, section 4>", "as_of": "2026-10-21T10:30:12+00:00", "freshness": "OK",
               "source": "receipt:pr-hygiene-audit", "reason": null},
    "store": {
      "value": {"state": "NOT_MIGRATED", "tables": {"release_queue_events": false, "release_queue": false}},
      "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK", "source": "postgres:to_regclass", "reason": null
    },
    "policy": {
      "value": {"schema": "ReleaseTrainPolicy@v1", "policy_version": "2026-10-21.1",
                "classifier_version": "release_train_classify/1", "status": "PROPOSED"},
      "as_of": "2026-10-21T21:30:00+00:00", "freshness": "OK", "source": "config/release_train_policy.json",
      "reason": null
    },
    "sources": {
      "store": {"status": "OK", "ms": 12},
      "census": {"status": "OK", "ms": 3},
      "stop": {"status": "OK", "ms": 1}
    }
  }
}
```

Details:

- `status` is `"OK"` when every `Field` is `OK`, else `"DEGRADED"`.
- `stop.value.state` uses the `release_window.State.read_latch` vocabulary, the same one `GET .../stop` returns:
  - `"ABSENT"`: no latch path exists;
  - `"SET"`: a readable latch;
  - `"UNREADABLE"`: the path exists but cannot be read or parsed. This is a STOP, so `effective_stop` is `true`. Any
    other verdict from a reader is also reported as `UNREADABLE`.

  `effective_stop` is `true` for every state except `ABSENT`.

  `reader` is `"release_window.State.read_latch"` when main's `release_window.py` has that method, else `"file"`
  (same fail-closed semantics). `latched_at`, `window_id` and `latch_reason` are copied from the latch body when it
  is readable.
- `state_dir` and `stop.value.state_dir` are the release-window state directory. It is resolved exactly as
  `scripts/release_window.py` and `release_train_stop.state_dir()` resolve it:
  - `TRADEAI_RELEASE_WINDOW_STATE_DIR` when it is set (read at call time);
  - else `release_window.STATE_DIR` (`$TRADEAI_STATE_ROOT/data/runtime/release_window`, default
    `~/trade-ai-releases/persistent-state/data/runtime/release_window`);
  - else the same formula, computed locally when `release_window` cannot be imported.

  `source` names the branch that was used: `env:TRADEAI_RELEASE_WINDOW_STATE_DIR`, `release_window.STATE_DIR` or
  `fallback:release_window formula`. Compare it with the runner's own `status` output.
- `current_train` is the newest train with no outcome recorded yet. Its `value` is `null` with `freshness: "OK"` and
  `reason: "no_train_in_progress"` when no train is running. The value is authoritative, so do not derive it from
  `/queue`.
- `last_verified` is the newest outcome whose immediate acceptance passed, `RELEASED_VERIFIED` or
  `RELEASED_OBSERVING`. `verified_at` is that outcome's `finished_at`. Its `value` is `null` with `freshness: "OK"` and
  `reason: "no_verified_release"` when there is none yet.
- `stop.freshness` is `UNAVAILABLE` (and `value` `null`) only when the read itself timed out or failed. Render that
  as STOPPED (rule 3).
- `queue_counts` groups projection states:
  - `ready` = `ready`;
  - `held` = `held`;
  - `needs_operator` = `needs_operator`;
  - `blocked` = `blocked`;
  - `in_train` = `selected`, `integrating`, `qualified`, `waiting_window`, `merged` or `promoting`;
  - `other` = everything else (`submitted`, `classified`, terminal states).

  `total` is the sum. When the store is not migrated, `value` is `null`, `freshness` is `"UNAVAILABLE"` and `reason`
  is `"not_migrated"`.
- `last_outcome`: when the store is readable and holds no outcome yet, `value` is `null`, `freshness` is `"OK"` and
  `reason` is `"no_outcome_recorded"`. That is a real empty, not a failure.
- `next_window` is the earliest upcoming of the four windows, whether or not it is enabled. The window times come
  from the policy, are computed in `America/New_York` and are DST-safe. `enabled` is `false` for all four in Phase 1.
  `role` is one of:

  | `role` | window | rule |
  |---|---|---|
  | `canary` | 18:00 | First live canary window. |
  | `general` | 00:00 | General eligible changes. |
  | `premarket_drain` | 06:00 | Needs a proven drain or a non-disruptive release path first. |
  | `premarket_last` | 08:00 | Enabled last. Skipped on 08:30 macro days or when calendar data is stale. |

## 4. Census (`census.value`, and `/queue` → `census`)

The census comes from the PR-hygiene lane receipt `<state root>/data/runtime/pr-hygiene-audit_last.json`
(LaneRunReceipt, `summary.schema` = `PrHygieneAudit@v1`). Every open PR lands in **exactly one** bucket. A PR is
placed in the first bucket of the precedence order whose condition it meets.

```json
{
  "status": "COMPLETE",
  "open_prs": 30,
  "bucket_total": 30,
  "invariant": "open_prs == sum(buckets)",
  "invariant_holds": true,
  "incomplete_reasons": [],
  "precedence": ["train_internal", "queued", "draft", "held", "stacked", "conflicting",
                 "mergeability_unknown", "checks_failing", "checks_pending", "checks_unknown", "unqueued_clean"],
  "buckets": [
    {"name": "train_internal", "count": 0, "prs": [], "as_of": "2026-10-21T10:30:12+00:00"},
    {"name": "queued", "count": 0, "prs": [], "as_of": "2026-10-21T10:30:12+00:00"},
    {"name": "draft", "count": 0, "prs": [], "as_of": "2026-10-21T10:30:12+00:00"},
    {"name": "held", "count": 8, "prs": [1629, 1795, 1796, 1797, 1798, 1799, 1800, 1802], "as_of": "..."},
    {"name": "stacked", "count": 3, "prs": [1879, 1880, 1881], "as_of": "..."},
    {"name": "conflicting", "count": 13, "prs": [1417, "..."], "as_of": "..."},
    {"name": "mergeability_unknown", "count": 0, "prs": [], "as_of": "..."},
    {"name": "checks_failing", "count": 1, "prs": [1887], "as_of": "..."},
    {"name": "checks_pending", "count": 0, "prs": [], "as_of": "..."},
    {"name": "checks_unknown", "count": 0, "prs": [], "as_of": "..."},
    {"name": "unqueued_clean", "count": 5, "prs": [1901, "..."], "as_of": "..."}
  ],
  "receipt": {
    "path": "<state root>/data/runtime/pr-hygiene-audit_last.json",
    "lane_id": "pr-hygiene-audit",
    "status": "ok",
    "finished_at": "2026-10-21T10:30:14+00:00",
    "summary_schema": "PrHygieneAudit@v1",
    "queue_membership": "UNAVAILABLE"
  }
}
```

| bucket | condition (PR fields from the receipt's `summary.prs[]`) |
|---|---|
| `train_internal` | head branch starts with `train/` (the train's own batch PRs) |
| `queued` | the PR has a row in `release_queue` (only when the store is readable; otherwise this bucket is always empty and `receipt.queue_membership` says `UNAVAILABLE`) |
| `draft` | `draft` is true |
| `held` | `holds` is non-empty (DO-NOT-MERGE / PROPOSED markers) |
| `stacked` | `base` is not `main` |
| `conflicting` | `conflict` is true |
| `mergeability_unknown` | `conflict` is null or missing (mergeability was not measured) |
| `checks_failing` | `required_checks.status == "FAIL"` |
| `checks_pending` | `required_checks.status == "PENDING"` |
| `checks_unknown` | `required_checks.status` missing, or `"UNKNOWN"` |
| `unqueued_clean` | everything else: open, mergeable, required checks pass, not queued |

`status` is `"INCOMPLETE"` when any of the following holds; the reasons are listed in `incomplete_reasons`:

- `open_prs != bucket_total` (`invariant_mismatch`);
- `len(summary.prs) != summary.open_prs` (`row_count_mismatch`);
- a PR number appears twice (`duplicate_pr_rows`);
- a row has no PR number (`row_without_number`);
- the open count reached the lister's page cap of 500 (`possible_truncation`);
- the receipt reports a failed run but still carries a summary (`last_run_failed`).

An INCOMPLETE census still lists its buckets, but no count from it may be presented as an exact total. The census
`freshness` is `STALE` when the receipt's `summary.as_of` is more than 36 hours old. It is `UNAVAILABLE` with `value`
`null` when there is no receipt or the receipt is unreadable.

## 4a. How a train picks its PRs (D7, census-first; DSN-20261021-release-train-P6-T9, 2026-10-23)

Every train, live, shadow or dry run, reads the census first (`ShadowQueueSource` in
`scripts/lib/release_train_controller.py`, returned by `default_queue_source()` for all three). The store-first
`FallbackQueueSource` is gone. **Why:** nothing submits PRs to `release_queue`; its only writer is the controller's
own event sink, so the store reads OK and empty, and the old live source selected nothing while ~50 PRs were open
(measured 2026-10-23). The `release_queue` store is now metadata only: its row for a PR the census lists is attached
to that entry as `census.store`, and it never adds a PR. The controller still writes its events there
(`Q.append_event`), so `/queue`, `/trains` and `/events` are unchanged.

The census order is shaped by the Work pipeline's batch queue, `<claims dir>/tasks/batch_queue.json`
(`BatchQueue@v1`). The Work pipeline's operator actions (hold / unhold, Add to next batch / remove) write it, and
`scripts/batch_queue.py show` prints it. Selection then works like this:

1. **Held PRs never ride.** A PR in `held_prs` is excluded as `HELD_BY_OPERATOR`, even if it is also listed next.
2. **"Next batch" PRs go first,** in the operator's list order.
3. **Then every other PR, oldest (lowest number) first.**
4. **Every rider must be green on its exact head.** The census must have seen `required_checks.status == "PASS"`
   with `required_checks.head` equal to the PR's current head. Otherwise the PR is excluded:
   - `CHECKS_FAILING:<checks>` for a red check on that head;
   - `NOT_GREEN_ON_HEAD:PENDING` or `NOT_GREEN_ON_HEAD:UNKNOWN`;
   - `NOT_GREEN_ON_HEAD:HEAD_MOVED:<sha>` when the verdict is for an older head;
   - `NOT_GREEN_ON_HEAD:NO_CENSUS_ROW` when the PR opened after the census ran.

   This applies to next-batch PRs too.
5. **Dependencies still come first.** A PR is placed after the PRs it depends on. `max_prs` (12) then truncates the
   ordered list, so next-batch PRs keep their place, and the rest are excluded as `OVER_TRAIN_LIMIT`.
6. **No batch queue file means census-only** (no holds, no priority). A file that exists but is unreadable, not
   JSON, or not `BatchQueue@v1` fails closed. The snapshot is then incomplete (`batch_queue_unreadable:<why>`), and
   the train ends `NO_OP / QUEUE_INCOMPLETE`, because riding a PR the operator held is worse than skipping a
   window.

Eligibility is otherwise unchanged. These exclusions still apply:

- `TRAIN_INTERNAL` and `DRAFT`;
- `HELD_BY_HYGIENE` (DO-NOT-MERGE / PROPOSED markers);
- `CONFLICTING` (census);
- `BLOCKED_SELF_MODIFICATION` (the train's protected surfaces, including AGENTS.md, guards and workflows);
- the risk classifier (`config/release_train_policy.json`; broker and Active Trader paths are always held).

A PR that conflicts or fails at integration is ejected from that train only (`MERGE_CONFLICT`, bisect). The census
still lists it, so the next train considers it again on its new head.

The controller records the choice in `rec["selection"]`: `members` (in merge order), `excluded` (PR → reason) and
`next_batch`. The queue source string ends with `batch_queue <ok|absent|unreadable>: next [...], held [...]`.
The tests are `tests/test_release_train_census_live_p6_t9_20261023.py`, gate
`release_train_census_live_p6_t9_20261023`.

## 5. `GET /api/v2/coordination/release-train/queue`

Query parameters:

| parameter | type | default | rule |
|---|---|---|---|
| `state` | string | (all) | Must be one of the queue states (section 8); otherwise `400 bad_state`. |
| `limit` | integer | 200 | 1 to 500; otherwise `400 bad_limit`. |

```json
{
  "ok": true,
  "data": {
    "schema": "ReleaseTrainQueue@v1",
    "authority": "READ_ONLY_ADVISORY",
    "generated_at": "2026-10-21T21:30:00+00:00",
    "as_of": "2026-10-21T21:30:00+00:00",
    "freshness": "OK",
    "source": "postgres:release_queue",
    "reason": null,
    "store_state": "OK",
    "total": 1,
    "rows": [
      {
        "pr_number": 1901,
        "repo": "PatsKiller/tardeai",
        "title": "fix(x): ...",
        "agent": "claude:session_01Q...",
        "head_sha": "<40 hex>",
        "state": "held",
        "risk_class": "held",
        "risk_reasons": [
          {"rule": "broker_active_trader", "class": "held", "path": "scripts/active_trader/foo.py",
           "detail": "Broker / Active Trader code is always held."}
        ],
        "depends_on": [1899],
        "intended_window": "18:00",
        "blocker": "broker_active_trader",
        "next_action": "Needs an execution-engineering grant and a manual release; the train never carries it.",
        "train_id": null,
        "submitted_at": "2026-10-21T19:02:11+00:00",
        "as_of": "2026-10-21T19:02:13+00:00",
        "age_seconds": 8867,
        "last_event_seq": 42,
        "census_bucket": "queued"
      }
    ],
    "census": "<Field<Census>, exactly as in the summary>"
  }
}
```

When the store is not readable, `rows` and `total` are `null`, `freshness` is `"UNAVAILABLE"`, `reason` is one of
the section 2 codes, and `store_state` is one of `"NOT_MIGRATED"`, `"DB_UNAVAILABLE"`, `"TIMEOUT"` or `"ERROR"`. The
`census` envelope is still filled independently, so the tab can list open PRs even before the migration is applied.
Row `as_of` is the time of the PR's last queue event. `title` and `census_bucket` are joined from the census and are
`null` when the census is unavailable or does not list the PR. Rows are ordered by state, most actionable first
(`blocked`, `needs_operator`, `held`, `ready`, the in-train states, the rest), then by PR number.

## 5a. `GET /api/v2/coordination/release-train/trains` — train history (paginated)

Query parameters:

| parameter | type | default | rule |
|---|---|---|---|
| `limit` | integer | 20 | 1 to 100; otherwise `400 bad_limit`. |
| `before_seq` | integer | (newest) | ≥ 1; otherwise `400 bad_before_seq`. Pass the previous page's `next_before_seq`. |

Trains are ordered newest first, by the `seq` of their first event.

```json
{
  "ok": true,
  "data": {
    "schema": "ReleaseTrainList@v1",
    "authority": "READ_ONLY_ADVISORY",
    "generated_at": "2026-10-21T21:30:00+00:00",
    "as_of": "2026-10-21T21:30:00+00:00",
    "freshness": "OK",
    "source": "postgres:release_queue_events",
    "reason": null,
    "trains": [
      {
        "train_id": "rt-20261021-1800-a1b2c3",
        "window_id": "2026-10-21T18:00-04:00",
        "phase": "observing",
        "member_count": 2,
        "outcome": "RELEASED_OBSERVING",
        "history_class": "observing",
        "started_at": "2026-10-21T20:30:00+00:00",
        "finished_at": "2026-10-21T22:41:07+00:00"
      }
    ],
    "next_before_seq": 118
  }
}
```

- `history_class` uses the section 6 vocabulary: `in_progress`, `not_shipped`, `merged_not_live`, `verified`,
  `observing`, `rolled_back` and `rollback_failed`.
- `outcome` is `null` while the train is in progress.
- `next_before_seq` is `null` on the last page.
- When the store is unreadable, `trains` and `next_before_seq` are `null` and `freshness` is `"UNAVAILABLE"`.
- A readable store with no trains returns `"trains": []`. That is a real empty.

## 6. `GET /api/v2/coordination/release-train/trains/{train_id}`

`train_id` must match `^rt-[0-9]{8}-[0-9]{4}-[a-z0-9]{4,12}$`; otherwise `400 bad_train_id`.

```json
{
  "ok": true,
  "data": {
    "schema": "ReleaseTrainDetail@v1",
    "authority": "READ_ONLY_ADVISORY",
    "generated_at": "2026-10-21T21:30:00+00:00",
    "as_of": "2026-10-21T21:30:00+00:00",
    "freshness": "OK",
    "source": "postgres:release_queue_events",
    "reason": null,
    "train": {
      "train_id": "rt-20261021-1800-a1b2c3",
      "window_id": "2026-10-21T18:00-04:00",
      "phase": "observing",
      "history_class": "observing",
      "members": [
        {"pr_number": 1901, "head_sha": "<40 hex>", "risk_class": "eligible", "order": 1},
        {"pr_number": 1903, "head_sha": "<40 hex>", "risk_class": "eligible", "order": 2}
      ],
      "base_sha": "<40 hex>",
      "candidate_sha": "<40 hex or null>",
      "main_sha": "<40 hex or null>",
      "served_sha": "<40 hex or null>",
      "artifact_digest": "sha256:<64 hex> or null",
      "policy_version": "2026-10-21.1",
      "classifier_version": "release_train_classify/1",
      "check_manifest": ["cio-hardening", "agent-governance", "release-readiness", "ci-gate"],
      "frozen_at": "2026-10-21T20:30:00+00:00",
      "started_at": "2026-10-21T20:30:00+00:00",
      "finished_at": null,
      "elapsed_seconds": 3600,
      "rollback_target": "<release dir or sha, or null>",
      "outcome": "<TrainOutcome@v1 object, or null while in progress>",
      "evidence": ["<TrainEvidence@v1 objects recorded for this train>"],
      "events": ["<TrainEvent@v1 rows, oldest first, section 7>"]
    }
  }
}
```

- `phase` is the `state_after` of the train's latest event.
- `history_class` keeps apart the outcomes the design names:

  | `history_class` | when |
  |---|---|
  | `in_progress` | no outcome recorded yet |
  | `not_shipped` | `NO_OP`, `FAILED_PRE_MERGE`, `CANCELLED` or `STOPPED` before merge |
  | `merged_not_live` | `MERGED_NOT_LIVE` |
  | `verified` | `RELEASED_VERIFIED` |
  | `observing` | `RELEASED_OBSERVING` |
  | `rolled_back` | `ROLLED_BACK` |
  | `rollback_failed` | `ROLLBACK_FAILED` |
- `train` is `null` with `freshness: "UNAVAILABLE"` when the store cannot be read.
- A readable store with no event for the id is `404 {"ok": false, "error": "train_not_found"}`.

## 7. `GET /api/v2/coordination/release-train/events`

Query parameters:

| parameter | type | default | rule |
|---|---|---|---|
| `limit` | integer | 100 | 1 to 500; otherwise `400 bad_limit` |
| `after_seq` | integer | 0 | ≥ 0; returns events with `seq > after_seq`, ascending |
| `train_id` | string | (all) | same pattern as section 6; otherwise `400 bad_train_id` |
| `pr` | integer | (all) | ≥ 1; otherwise `400 bad_pr` |

```json
{
  "ok": true,
  "data": {
    "schema": "ReleaseTrainEvents@v1",
    "authority": "READ_ONLY_ADVISORY",
    "generated_at": "2026-10-21T21:30:00+00:00",
    "as_of": "2026-10-21T21:30:00+00:00",
    "freshness": "OK",
    "source": "postgres:release_queue_events",
    "reason": null,
    "events": [
      {
        "schema": "TrainEvent@v1",
        "seq": 41,
        "event_id": "rte-1901-6f0c1d2e3a4b-classified",
        "event_type": "classified",
        "subject_kind": "pr",
        "subject_id": "pr:1901",
        "pr_number": 1901,
        "train_id": null,
        "state_after": "held",
        "actor": "release_train_classify",
        "policy_version": "2026-10-21.1",
        "epoch": null,
        "idempotency_key": "classify:1901:<40 hex>:2026-10-21.1",
        "occurred_at": "2026-10-21T19:02:13+00:00",
        "recorded_at": "2026-10-21T19:02:13+00:00",
        "payload": {"risk_class": "held", "reasons": ["..."]},
        "evidence_refs": []
      }
    ],
    "next_after_seq": 41
  }
}
```

`next_after_seq` is the highest `seq` returned, or the request's `after_seq` when nothing was returned. When the store
is unreadable, `events` and `next_after_seq` are `null` and `freshness` is `"UNAVAILABLE"`.

## 8. Vocabularies

**Queue states** (`release_queue.state`, `TrainEvent@v1.state_after` for PR subjects):
`submitted`, `classified`, `ready`, `held`, `needs_operator`, `blocked`, `selected`, `integrating`, `qualified`,
`waiting_window`, `merged`, `promoting`, `released`, `observing`, `rolled_back`, `rollback_failed`, `superseded`,
`quarantined`, `cancelled`.

**Risk classes** (`risk_class`), from least to most restrictive:

| class | meaning |
|---|---|
| `eligible` | May ride a train once ready. |
| `needs_operator` | Never rides automatically. An operator ride approval bound to the full head SHA may admit it. Covers AGENTS/policy, auth/secrets, guard/CI enforcement, scheduler/workflow/live-list, deletions, migrations and oversized changes. |
| `held` | Does not ride. Covers unknown risk and Broker / Active Trader code, which is always held. |
| `blocked` | Cannot be a train candidate at all: it changes the train's own controller, classifier or policy, or its input is invalid. |

When several rules match, the most restrictive class wins.

**Outcomes** (`TrainOutcome@v1.outcome`): `NO_OP`, `FAILED_PRE_MERGE`, `MERGED_NOT_LIVE`, `RELEASED_VERIFIED`,
`RELEASED_OBSERVING`, `ROLLED_BACK`, `ROLLBACK_FAILED`, `STOPPED`, `CANCELLED`.

**Contracts.** The JSON schemas are in `config/schemas/release_train/`, and the validators are in
`scripts/lib/release_train_contracts.py`:

- `TrainSubmission@v1`
- `TrainCandidate@v1`
- `TrainEvidence@v1`
- `ReleaseControl@v1`
- `TrainEvent@v1`
- `TrainOutcome@v1`

The response wrappers above (`ReleaseTrainSummary@v1`, `ReleaseTrainQueue@v1`, `ReleaseTrainList@v1`,
`ReleaseTrainDetail@v1` and `ReleaseTrainEvents@v1`) are view shapes defined by this document.
