---
id: DSN-20261029-deploy-console
title: Deploy console — actionable in-flight board + LLM-driven push/merge + Push Live
status: PROPOSED
approval: operator (Push Live reuses the release-write grant + prepare/promote rails; force-promote/rollback remain §17/§27.3 MAJOR)
source: operator 2026-10-29 — "actionable buttons that can be driven by LLM … push, merge, force live" then, same night, "a Push Live button that does in one click what we just did by hand"
phases:
  - id: DSN-20261029-deploy-console-P1
    title: In-flight board + tooltips (read-only)
    status: MERGED
    tasks:
      - id: DSN-20261029-deploy-console-P1-T1
        title: Backend open-PR projection (state · mergeable · CI · why held) + frontend in-flight table + ⓘ tooltips
        status: MERGED
  - id: DSN-20261029-deploy-console-P2
    title: Approve / Hold / Push / Refresh-hints write path
    status: PARTIAL
    tasks:
      - id: DSN-20261029-deploy-console-P2-T1
        title: Operator-session, CSRF-protected POST that adds/removes operator-merge (same authority as the Telegram tap) + refresh-shard-hints
        status: IN_FLIGHT
      - id: DSN-20261029-deploy-console-P2-T2
        title: Push button — operator-session POST that issues a bound git-push grant (branch + head SHA + reason) and executes the fast-forward push, replacing `bin/guard grant git-push` + the command line
        status: PROPOSED
  - id: DSN-20261029-deploy-console-P3
    title: Push Live — prepare → promote in one operator click, streamed + monitored + remediated
    status: PROPOSED
    tasks:
      - id: DSN-20261029-deploy-console-P3-T1
        title: Backend promote runner + state file + poll endpoint (scripts/lib/deploy_console_promote.py)
        status: PROPOSED
      - id: DSN-20261029-deploy-console-P3-T2
        title: Frontend DeployPushLive surface (ahead-of-serving list, Push Live button, monitor, remediation, Fix dirty)
        status: PROPOSED
  - id: DSN-20261029-deploy-console-P4
    title: Force promote / rollback (passkey-gated) — supersedes the original P3
    status: PROPOSED
    tasks:
      - id: DSN-20261029-deploy-console-P4-T1
        title: WebAuthn passkey + typed-phrase force-promote and rollback (§27.3/§25.10) — its own reviewed PR
        status: PROPOSED
---

# Deploy console — design of record

## What it is

The System → Releases & Schedules page becomes a **deploy console**: the in-flight (open) PRs that are not
serving become visible with their state, next state, and actionable buttons. The LLM drives the *pipeline* —
it validates CI, computes the exact head SHA, stages the label/receipt — and the operator drives the
*authority* (tap for safe actions, passkey + typed phrase for the risky direction).

**P3 (this document's focus)** adds the one-click **Push Live**: the operator selects the commit(s) ahead of
serving and clicks once; the console performs the full `prepare → promote` sequence the operator ran by hand
tonight, streams each stage back, and on failure reaches out to a remediation agent that **proposes** a fix
(never applies it). Every hard-won rail from tonight is encoded below as a requirement.

## Authority mapping (nothing new; each button reuses an existing rail)

| Button | Action | Authority | LLM role |
|---|---|---|---|
| Approve | add `operator-merge` bound to head SHA → Mergify queues | operator tap (== today's Telegram Approve) | validate CI green + compute SHA |
| **Push** | issue a bound git-push grant (branch + head SHA + reason) and fast-forward push the already-green local branch | operator tap (replaces `bin/guard grant git-push` + CLI) | stage the exact branch/head/reason; never force-push |
| **Push Live (P3)** | write a bound `release-write` grant naming prepare+promote+full SHA, then run `cio_phase2_exact_main_deploy.sh prepare && promote`, streamed | operator tap + `release-write` grant (== tonight's hand run) | stage the exact SHA + reason; monitor stages; propose remediation |
| Hold | remove label / set held | operator tap | prepare |
| Refresh hints | re-run `ci_shard_duration_hints` refresh from the green ci-gate artifact | operator tap | stage command |
| Fix dirty (P3) | resolve a DIRTY/conflicting PR's branch locally and **propose** the resolution | operator tap to trigger, operator approves the merge | diff + propose the resolution; never merge |
| Resolve conflict | open both-sides sheet; operator picks, LLM writes | operator decides, LLM writes (coordinator path) | diff + propose |
| 🛑 STOP deploy | latch deploy STOP | one click (§27.3 safe direction) | confirm state |
| ⚡ Force promote | `emergency_manual_promote.sh <sha>` | **passkey + typed phrase** (§27.3 / §25.10) | stage SHA + receipt |
| ↻ Rollback | re-point CURRENT at prior known-good SHA | **passkey + typed phrase** | stage SHA + prove rollback target |

## State of record — honest

At design time (2026-10-29/30), the code is **ahead of this document's phase status in one place and behind in
another**, and this is recorded so nobody builds on a false premise:

- **P1 is merged** to `origin/main` — `scripts/lib/deploy_in_flight.py` (`GET /api/v2/ops/in-flight`,
  `DeployInFlight@v1`) and `apps/command-center-v3/src/components/DeployInFlightBoard.tsx` (PR #2284).
- **P2 is PARTIAL.** Only its CSRF hard-route landed: `config/cc_auth.yaml` adds
  `deploy_console_command` on `POST /api/v2/ops/in-flight(/.*)?` (PR #2290). The Approve/Hold/Push/Refresh
  action module (`scripts/lib/deploy_console_actions.py`) **does not exist yet** — the P2-T1/P2-T2 write path
  is still in flight (`wt/deploy-console-p2-20261029`). This document's P3 therefore specifies the
  grant-writing pattern directly rather than "reusing" a P2 module that is not yet written; when P2 lands, P3
  and P2 share one grant-writing helper (see §P3 implementation plan).
- **The original P3** (force promote / rollback behind a WebAuthn passkey) is **renamed P4** and deferred. The
  operator's latest request redefines P3 as **Push Live** — the *normal* prepare→promote of `origin/main`, the
  same authority as tonight's hand run, not the emergency/force path (§25.10).

## Why phases in this order

- **P1 (read-only)** shipped first — no write path, no new authority.
- **P2 (Approve/Hold/Push)** adds a write path on the existing operator-merge label and git-push grant rails.
- **P3 (Push Live)** is the subject of this document: it rides the `release-write` grant + the exact-main
  prepare/promote rails, nothing new, but it moves a host-CLI-only act onto a web surface, so it needs the
  same operator-session + CSRF gate P2 does, plus a streamed monitor.
- **P4 (force promote / rollback)** stays MAJOR (§17/§27.3): passkey + typed phrase, its own reviewed PR.

## Sequencing constraint (honest)

`apps/command-center-v3/src/pages/ReleasesSchedules.tsx` was in conflict in PRs #2113 and #2220. P1 landed the
in-flight board as a separate component (`DeployInFlightBoard`), not an in-place rewrite. P3 does the same:
`DeployPushLive` is a new component mounted beside it, editing none of the lines those PRs touch.

---

# P3 — Push Live: prepare → promote in one operator click

## P3.1 What it does (the operator's exact words, made precise)

1. **A list of what is pushed to `origin/main` but not yet served.** Reused, not reinvented: the data is the
   `next_release` section of `scripts/lib/releases_schedules_view.py` (`GET /api/v2/ops/releases-schedules`).
   When `next_release.is_serving` is `false`, the section already carries `sha` (origin/main HEAD),
   `commits_ahead`, `prs_since_serving`, and the exact-SHA CI verdict in `next_release.ci`. The P3 surface
   renders that section: serving SHA on the left, the bundle of commits/PRs ahead on the right, and the CI
   gate under it. There is **one** candidate — `origin/main` HEAD — because `cio_phase2_exact_main_deploy.sh`
   is exact-main and only ever promotes `origin/main`. "Select an item" means "confirm you want this bundle
   (the N commits/PRs listed) promoted"; the promote itself is the atomic HEAD.
2. **A "Push live" button** that, in one click: (a) pre-flight gates (§P3.4), (b) writes the bound
   `release-write` grant (§P3.3), (c) runs `cio_phase2_exact_main_deploy.sh prepare` then `promote` in a
   background process, and (d) streams stage, ETA and errors back (§P3.5/§P3.6).
3. **A monitor** showing where the sequence is, how long each stage took / ETA, and any error with its exact
   cause (§P3.5).
4. **On error**, a remediation agent (Claude Code on the host, or the governed Anthropic API) **diagnoses and
   proposes** a fix and reports "how long it will take" — **propose-only, operator-approved before it is
   applied** (§P3.7).
5. **A "Fix dirty" button** on DIRTY/conflicting PRs that resolves the dirty state locally and **proposes** the
   resolution; the merge is operator-approved (§P3.8).

## P3.2 Authority — nothing new (the rails we learned the hard way, encoded)

These are requirements, not suggestions. Each names a failure that cost real time tonight.

- **R1 — the grant names BOTH action words AND the full SHA.** A `release-write` grant whose reason lists
  action words only passes `release_grant_binding._allows_action` for *each listed word* and
  `_names_action` for the SHA. A grant that names `prepare` only refuses `promote`; a grant that names no
  SHA refuses the action as "grant names neither this PR, this SHA nor this campaign". The button writes the
  grant with the exact reason format in §P3.3, **never** a generic "release" reason.
- **R2 — the button WRITES the grant** (same shape the P2 Push button writes a `git-push` grant): it invokes
  the guard's own ledger writer `python3 <root>/.cursor/hooks/guard_ledger.py grant --tier release-write …`,
  the same writer `bin/guard` uses, so the one-active-grant-per-tier invariant and the audit trail hold. It
  never hand-edits `~/.cursor/approvals/grants.json`.
- **R3 — CANONICAL_SOURCE HEAD == origin/main before prepare/promote.** `cio_phase2_exact_main_deploy.sh`
  `require_head_is_origin_main` (dies unless `HEAD == origin/main` and the tree is clean) and
  `require_canonical_source_at` (dies unless the primary checkout's HEAD is the exact SHA, because the release
  verifier runs from it). The button detects a feature branch / dirty primary tree **up front** and either
  offers "checkout origin/main" (fetch + `merge --ff-only`, only when the tree is clean) or refuses with the
  exact `git status --porcelain` output. It never force-checks-out, never resets.
- **R4 — a stale `TRADEAI_EMERGENCY_RELEASE_SHA` re-pins the deploy silently.** `git_sha()` returns the
  emergency SHA when that env var is set, and `require_head_is_origin_main` then compares against it — a
  deploy that "succeeds" on an old SHA. The button's subprocess environment is **sanitised**: it unsets
  `TRADEAI_EMERGENCY_RELEASE_SHA` and `TRADEAI_RELEASE_TRAIN_SHA` (and warns loudly in the monitor) before
  spawning prepare/promote, unless the operator explicitly armed an emergency/train release (which is P4, not
  P3).
- **R5 — promote is gated on exact-SHA CI, and the button shows that gate live.** `release_grant_preflight.py`
  `promote_ci_gate` requires green `cio-production-hardening-ci`, `agent-governance` and `release-readiness`
  push/main runs for the exact SHA, read **before** a grant use is consumed. The button surfaces
  `next_release.ci` (from the main-ci-watch receipt / `post_merge_ci.json`) with its state, age and
  `stale` flag, and **disables Push Live** until it is `SUCCESS`/`OK` and fresh — it never fires blindly and
  lets the script refuse after consuming a use.
- **R6 — `MBI_BEHAVIOR = 0`.** No order, size, stop, broker, credential, 2FA anywhere in this path. The button
  writes one grant and runs one deploy script; it touches no broker surface. The deploy script itself is
  broker-free by design (its only broker-adjacent act is symlinking `config/broker_credentials.env`, never
  reading its value).

## P3.3 The grant reason format (exact, non-negotiable)

The button writes **one** `release-write` grant covering both actions, so the format is fixed:

```
Push live <full-40-hex-SHA>: prepare and promote exact origin/main
```

- `<full-40-hex-SHA>` is the `origin/main` HEAD from `next_release.sha` — **full 40 hex**, never a short
  prefix, because `_names_action` matches a `9–40` hex run and a short form is a needless risk.
- `prepare` and `promote` both appear literally, satisfying `_allows_action` for each (`release_grant_binding`
  `_ACTION_RE` matches `\b(prepare|promote)\b`).
- The full SHA appears literally, satisfying `_names_action` (`named_shas` + `_sha_matches` prefix-9 check).

Grant write (the button's authority is the operator-session click, which is what replaces the interactive
`APPROVE` that `bin/guard grant` would otherwise demand):

```
python3 <root>/.cursor/hooks/guard_ledger.py grant \
  --tier release-write \
  --expires "$(( $(date +%s) + 1800 ))" \
  --uses 2 \
  --reason "Push live <full-40-hex-SHA>: prepare and promote exact origin/main"
```

- `--uses 2`: exactly one use is consumed by the consuming `prepare` preflight and one by the consuming
  `promote` preflight (`release_grant_preflight.py` consumes once per action, and only after the
  exact-SHA CI gate passed — the `--no-consume` binding calls consume nothing).
- `--expires` 30 minutes: prepare is frontend-build-bound (minutes), promote is seconds; 30 m is generous
  headroom, not a guess — the operator may tighten it (see §P3.11 decision D6).
- **Existing active grant:** if `release_grant_binding.decide` would see more than one live grant it refuses
  as ambiguous. The button therefore reads the guard state first (`bin/guard show` / `guard_ledger.py list`);
  if a live `release-write` grant exists, it refuses with a clear message and the exact `--replace` or revoke
  instruction — it never silently unions or replaces a grant the operator did not mean to supersede.

## P3.4 Pre-flight gates (the button refuses *before* writing anything)

Ordered, each with its refusal message, run in the button's request handler **before** the grant is written:

1. **Operator identity + CSRF** — same as P2: `cc_auth.command_csrf_check` (the hard route is registered for
   the P3 path, see §P3.9) and the tailnet operator principal on `serve_proxy` (the `_operator` pattern in
   `scripts/lib/ops_controls_api.py`). Anything else → `AGENT_CALLER_REFUSED` / `CSRF_REFUSED`.
2. **Not already running** — one Push Live at a time; a state file with a `RUNNING` stage → `409
   PROMOTE_IN_PROGRESS`.
3. **Ahead of serving** — `next_release.is_serving == true` → refuse "nothing to promote".
4. **Exact-SHA CI green and fresh** (§P3.2 R5) → else refuse with the CI verdict, its age and a "re-run
   `scripts/main_ci_watch.py`" hint.
5. **Primary checkout clean and at origin/main** (§P3.2 R3) — `git -C <CANONICAL_SOURCE> status --porcelain`
   empty and `rev-parse HEAD == origin/main`. Dirty or behind → offer the exact `git fetch origin main && git
   merge --ff-only` (clean tree only) or refuse with the porcelain output.
6. **No stale emergency/train pin** (§P3.2 R4) — if `TRADEAI_EMERGENCY_RELEASE_SHA` / `TRADEAI_RELEASE_TRAIN_SHA`
   is set in the ambient environment, refuse or proceed only after the operator explicitly clears it (P4's
   job, not P3's).
7. **No deploy STOP latch** — `releases_schedules_view.read_stop` shows `effective_stop: true` → refuse.

## P3.5 The state machine

The runner owns a state file (one per run) and advances through these stages. Stage names are stable
identifiers (the frontend renders a human label; the wire carries the id). Error states are terminal until the
operator acts.

```
queued
  → preparing
      → cloning          (rsync PREV release → NEW release dir)
      → overlaying       (overlay_main + link_pipeline_data)
      → building         (build_frontend: npm ci + npm run build)
      → stamping         (stamp_build + render_relay_live_lanes + integrity hook + release venv)
      → pin-check        (run_pin_check: CURRENT pin vs SOURCE_COMMIT)
  → promoting
      → binding          (release_grant_preflight promote --no-consume)
      → ci-gate          (release_grant_preflight --ci-only, exact-SHA re-query)
      → activating       (release_grant_preflight promote [consume] → write_systemd → CURRENT symlink)
  → restarting           (systemctl daemon-reload + restart portfolio-server + restart_root_frozen_units)
  → health-check         (health_check: /api/v2/health ok + /v3/cio == 200)
  → live                 (write_deploy_receipt true promote; ff_dev_tree_after_promote)
```

Error states (terminal, each carries `error = {stage, code, cause, redacted_tail}`):

```
grant_refused        (binding verdict refused; nothing consumed)
head_mismatch        (CANONICAL_SOURCE HEAD != origin/main)
dirty_tree           (primary tree has uncommitted changes)
emergency_sha_stale  (TRADEAI_EMERGENCY_RELEASE_SHA / TRAIN_SHA set)
ci_not_green         (exact-SHA CI not green; promote refused, no use consumed)
prepare_failed       (any prepare sub-step: clone/overlay/build/stamp/pin/venv)
build_failed         (npm build failed even after the vite-only fallback)
pin_mismatch         (current_pin_integrity reported a mismatch)
promote_refused      (conformance or CI re-query refused; no use consumed)
health_failed        (health/wrapper gate failed — the script auto-rolls back to PREV)
rollback_failed      (the automatic rollback also failed)
remediation_proposed (a fix is staged and awaiting the operator — the only non-terminal "error" state)
```

**Health-failure semantics (important, and honest):** `cmd_promote` already auto-rolls back to `PREV_RELEASE`
when health/wrapper fails and writes `deploy_receipt {ok:false, rolled_back:true}`. The monitor must therefore
report `health_failed` **with** `rolled_back: true` and the rollback outcome — it never paints `live` on a
failed promote, and it never hides that CURRENT moved back.

## P3.6 The monitor payload shape

`GET /api/v2/ops/push-live/status` returns one JSON object (the runner's state file, normalised):

```json
{
  "schema": "DeployPushLive@v1",
  "authority": "OPERATOR_ONLY",
  "run_id": "push_20261029T220000Z_<sha8>",
  "candidate": { "sha": "<40hex>", "short": "<9hex>", "commits_ahead": 3, "prs": [2230, 2231, 2232] },
  "serving": { "sha": "<40hex>", "short": "<9hex>", "release_dir": "…", "since": "…" },
  "stage": "building",
  "stage_label": "Frontend build",
  "stage_started_at": "2026-10-29T22:01:15Z",
  "stage_elapsed_s": 84,
  "eta_s": 132,
  "eta_basis": "last_5_deploy_receipts",
  "pct": 62,
  "release_dir": null,
  "ci_gate": { "state": "SUCCESS", "checked_at": "…", "stale": false, "source": "receipt:main-ci-watch" },
  "grant": { "grant_id8": "a1b2c3d4", "uses_left": 2, "written_at": "…" },
  "error": null,
  "remediation": null,
  "health": null,
  "service": null,
  "log_tail": ["…last 20 redacted lines…"]
}
```

Fields, precisely:

| field | meaning |
|---|---|
| `stage` | the stable stage id (§P3.5); `live` only after `write_deploy_receipt true promote` |
| `stage_elapsed_s` / `eta_s` | measured elapsed; ETA from the **last N deploy receipts** in `deploy_receipt_history.jsonl` (never a hard-coded guess presented as fact), falling back to a conservative default labeled `eta_basis: "default"` |
| `ci_gate` | the live exact-SHA CI verdict re-read at poll time (R5), not a copy of the click-time verdict |
| `grant` | the grant the button wrote (id8, uses left), so the operator can see it is bound |
| `error` | `{stage, code, cause, redacted_tail}` — the exact cause, never `exit_1` (same rule as `releases_schedules_view._cause`) |
| `remediation` | `{proposed: bool, summary, eta_s, agent, approved: false|null}` — `null` until the agent ran; `approved` only ever set by the operator |
| `health` | `{ok, http_code, cio_http_code}` after `health-check`; null before |
| `service` | `{active, cwd}` read back after restart — `cwd` is the readback that proves the unit re-resolved (§8) |
| `log_tail` | the last N redacted lines of the deploy script's stdout/stderr (credentials redacted, same `redact_command` rule) |

The frontend polls this endpoint (1–2 s) while `stage` is not terminal; it also re-reads
`releases-schedules` (the `serving` / `next_release` sections) after `live` to confirm the served SHA flipped.

## P3.7 Remediation — diagnose and PROPOSE, never apply

On any terminal error, the runner (or the poll handler, once) invokes a **propose-only** remediation agent:

- **Transport, free-first** (`scripts/lib/llm_escalation.run_with_escalation`, the §12 order of operations):
  local / free cognition → OAuth → DeepSeek Flash → **STOP**. For a host-side diagnosis of a *deploy* failure
  the preferred agent is **Claude Code on the host** (it can read `deploy_receipt_history.jsonl`, the release
  dir, and `journalctl --user -u portfolio-server` — none of which needs a live credential); the **governed
  Anthropic API** (`cc_curl.sh` / the governed bridge) is the fallback when Claude Code is unavailable. Either
  way the prompt is the redacted failure context (§2A: the working set, never a credential or account id).
- **The agent returns** `{summary, proposed_fix, eta_s, confidence}`. The monitor shows it as
  `remediation_proposal`, and the button row flips to "Fix proposed — operator approves". **The application of
  the fix is operator-approved, not autonomous** (§0 rule 9): no hook, no auto-apply, no auto-merge, no
  auto-re-deploy. The operator can accept (which re-enters the normal Push Live flow), reject, or take the
  proposal to the host.
- The proposal is recorded to the run's state file and the deploy receipt history; the agent's output is
  egress-sanitised before it is stored or shown.

## P3.8 "Fix dirty" — resolve DIRTY/conflicting PRs, operator-approved merge

The in-flight board already classifies `merge_state: DIRTY` / `CONFLICTING` / `BEHIND`. The Fix dirty button,
on those rows only:

1. **Trigger** (operator tap) spawns a resolution agent — **Claude Code locally** (it has the working tree) or
   the **governed Anthropic API** — that checks out the PR's head, rebases/merges `origin/main`, resolves the
   conflict, and **produces a diff + a plain-English proposal**.
2. **The proposal is operator-approved.** The surface shows the before/after diff and the agent's explanation;
   the operator approves → the branch is updated (a normal `git-push` grant, the P2 Push rail) → Mergify
   merges under §25.10. The agent **never merges, never pushes, never deletes** a branch on its own. A DIRTY
   state is fixed only through the operator's explicit merge approval.
3. **Failure to propose is a finding, not a silent skip** — the button reports the agent's refusal/error, never
   leaves the row looking "clean".

## P3.9 Backend implementation plan

New module **`scripts/lib/deploy_console_promote.py`** (one module, hermetic-testable, no live broker path):

- **Constants**: `ROUTE = "/api/v2/ops/push-live"`, `SCHEMA = "DeployPushLive@v1"`, the stage ids (§P3.5), the
  grant reason template (§P3.3), the sanitised subprocess env (R4), `AUTHORITY = "OPERATOR_ONLY"`.
- **`preflight(db_query)`** → runs §P3.4 gates in order, returns `(ok, reason_or_refusal)`. Reuses
  `releases_schedules_view.read_next_release` / `read_serving` / `read_stop` for the data (never re-derives
  them), and `release_grant_binding.decide_from_disk` to preview the binding.
- **`write_release_grant(sha)`** → `subprocess.run(["python3", "<root>/.cursor/hooks/guard_ledger.py", "grant",
  "--tier", "release-write", "--expires", …, "--uses", "2", "--reason", f"Push live {sha}: prepare and promote
  exact origin/main"])` — returns the grant id or the exact refusal (R2).
- **`start(sha)`** → writes the `queued` state file, then spawns a **detached background process**
  (`subprocess.Popen`, `start_new_session=True`) that runs the real script:
  `cio_phase2_exact_main_deploy.sh prepare && cio_phase2_exact_main_deploy.sh promote`, in the **primary
  checkout** (`CANONICAL_SOURCE`), with the sanitised env. Each script stage is mapped to the state machine by
  **parsing the script's own `log()` / `PREPARE OK` / `PROMOTE OK` lines and the receipt files it writes**
  (`deploy_receipt.json`, `deploy_receipt_history.jsonl`) — the monitor reads the state file + receipts, it does
  not guess from wall-clock. The process detaches so a server restart does not kill a running promote (the
  state file is the recovery point; on boot the poll handler detects a `RUNNING` file whose pid is gone and
  marks it `remediation_proposed` with "runner died; inspect receipt").
- **`status(run_id)`** → reads the state file + `deploy_receipt.json` + `main-ci-watch` receipt into §P3.6.
- **`remediate(run_id)` / `fix_dirty(pr)`** → spawn the propose-only agent (§P3.7/§P3.8), write the proposal,
  return it. Never apply.
- **`handle(path, method, body, query, db_query)`** — the route dispatcher: `POST /push-live` (operator+CSRF →
  preflight → grant → start), `GET /push-live/status`, `POST /push-live/<run_id>/remediate`, `POST
  /push-live/fix-dirty`. 405 otherwise, `None` for other paths.

**Route registration** (`scripts/api_v2.py`, a block beside the existing `in-flight` and `releases-schedules`
blocks): mount `deploy_console_promote.handle` on `/api/v2/ops/push-live(/.+)?`.

**cc_auth hard route** (`config/cc_auth.yaml`): add `deploy_console_promote` on `POST /api/v2/ops/push-live(/.*)?`
(same shape as the P2 `deploy_console_command` entry), so same-origin is enforced even in `report_only`.

**State file**: `~/.local/state/cio-phase2-exact-main/push_live/<run_id>.json` — the same state dir the deploy
script already owns (`STATE_DIR`), so receipts and the running-promote state live beside each other and survive
a server restart. Written atomically (tmp + `os.replace`), mode 600. **Not** committed; host-local by design
(the deploy is a host act).

**Grant-writing helper shared with P2** (sequencing note): when P2-T2 lands its `git-push` grant writer, extract
the common `guard_ledger.py grant` invocation into one helper (`scripts/lib/guard_grant.py`) and have P2 (git-push)
and P3 (release-write) both call it. Until then P3 calls `guard_ledger.py grant` directly.

## P3.10 Frontend implementation plan

New component **`apps/command-center-v3/src/components/DeployPushLive.tsx`**, mounted in
`ReleasesSchedules.tsx` beside `DeployInFlightBoard` (a new `<DeployPushLive />` line, no edit to the
conflicting tables — §Sequencing).

- **Ahead-of-serving list** — read from the existing `releases-schedules` hook (`useApi`): `serving` vs
  `next_release` (commits_ahead, prs, CI). When `is_serving`, show "serving origin/main, nothing ahead".
- **Push Live button** — disabled until `next_release.ci` is green+fresh (R5) and not already running. On
  click → `POST /api/v2/ops/push-live` with the candidate SHA; the response is the `run_id`.
- **Monitor** — polls `GET /api/v2/ops/push-live/status` at 1–2 s: a stage strip (`queued → … → live`) with the
  current stage highlighted, per-stage elapsed, ETA with its basis, the CI-gate chip, the grant chip, and the
  log tail. On `error`, render `error.cause` (redacted) and, when `remediation` is present, the proposal card
  with **Approve / Reject** (Approve re-enters the flow; neither applies anything automatically).
- **Fix dirty** — a button on `DeployInFlightBoard` rows with `merge_state` DIRTY/CONFLICTING that calls the
  fix-dirty endpoint and renders the proposal diff + **Approve merge (operator) / Reject**.
- Reuses `Chip`, `ChipRow`, `designTokens`, `useApi`, and the `ops-evidence-table` phone-first CSS — no new
  primitives.

## P3.11 Tests and CI gate registration

- **`tests/test_deploy_console_promote_20261029.py`** (hermetic; fixture-only, no network, no gh, no broker):
  - **Grant reason format** — asserts the generated reason contains both `prepare` and `promote` and the full
    40-hex SHA, and that `release_grant_binding.decide` returns `allowed: true` for BOTH `prepare` and
    `promote` with a fixture grant built from that reason, and `allowed: false` when either word or the SHA is
    missing (mutation of the exact rail R1).
  - **State machine** — each script log line / receipt transition maps to the right stage; `health_failed`
    carries `rolled_back: true`; `live` is reachable only from `write_deploy_receipt true promote`.
  - **Pre-flight** — dirty tree, behind origin/main, stale emergency SHA, `is_serving`, CI not green, STOP
    latch each refuse with the right code and write nothing (grant file untouched).
  - **Env sanitisation** — the spawned subprocess env unsets `TRADEAI_EMERGENCY_RELEASE_SHA` /
    `TRADEAI_RELEASE_TRAIN_SHA`.
  - **Propose-only** — `remediate`/`fix_dirty` return a proposal and mutate no merge/push/branch state; the
    runner's grant write is the *only* write.
  - **Monitor payload** — `eta_basis` is `last_N_receipts` or `default`, never a bare number; `error` has a
    `cause`, never `exit_1`.
- **CI gate registration** — add `tests/test_deploy_console_promote_20261029.py` to a new
  `config/ci_gates/deploy_console_promote_20261029.json` (and the coverage gate's baseline may only shrink,
  per §8A).
- **Mutation-test the guard** — the grant-reason test must be shown to fail when the SHA or an action word is
  dropped (§8A: a guard never shown to fail is untested).

## P3.12 Risks and operator decisions

**Risks (must be stated in the PR body):**

- **Long-running subprocess vs server lifecycle.** prepare is minutes (npm build) and promote moves CURRENT.
  A server restart mid-promote is handled by the detached process + state file, but a *host* reboot mid-promote
  needs the runner to resume from the receipt, not re-run (re-run prepare is harmless; re-run promote is not —
  it must detect an already-applied promote via `deploy_receipt_history.jsonl`).
- **The script is `set -euo pipefail` and dies on the first failure.** The monitor must therefore read the
  *receipts* the script writes, not only its exit code — an exit 1 with a receipt says `health_failed
  (rolled_back)`, which is a different truth than "the script crashed".
- **Disk space.** prepare rsyncs the PREV release (large) and builds the frontend; a full disk is a real
  failure mode tonight. The pre-flight can warn on low `df` but must not block on a guess.
- **P2 dependency.** The grant-writing helper is currently P3-only until P2-T2 lands; landing P3 first is safe
  (it calls `guard_ledger.py` directly), but the two must not drift into two writers of the same ledger.
- **One active grant per tier.** An existing live `release-write` grant makes the button refuse (R2 §P3.3)
  until the operator revokes or `--replace`s — by design, not a bug.

**Operator decisions (propose and stop — §17):**

- **D1 — Is remediation propose-only?** (This design says **yes**: the agent diagnoses and proposes; the fix is
  operator-approved. The alternative — an autonomous re-deploy after a failed promote — is a new authority and
  rejected by §0 rule 9.)
- **D2 — Is "Fix dirty" autonomous or operator-approved?** (This design says **operator-approved before
  merge/push**: the agent resolves locally and proposes; the operator approves the branch update. Autonomy here
  would be a merge authority the agent does not have.)
- **D3 — Does Push Live need a passkey, or is operator-session + `release-write` grant sufficient?** (This
  design says the latter: Push Live is the *normal* exact-main promote, the same authority as tonight's hand
  run. **Force** promote / rollback — P4 — keeps the §27.3 passkey + typed phrase. The operator should confirm
  Push Live is not treated as force-promote.)
- **D4 — Grant window/uses.** Default `--for 30m --uses 2`; the operator may tighten to `15m --uses 2` if
  prepares are routinely faster.
- **D5 — Remediation transport.** Claude Code on the host (preferred, can read journals) vs the governed
  Anthropic API (fallback) — confirm the preference and that Claude Code may be invoked for this propose-only
  purpose.
- **D6 — Where the running-promote state lives.** `~/.local/state/cio-phase2-exact-main/push_live/` (beside the
  deploy receipts) vs under `persistent-state` — the former is host-local and tied to the deploy, the latter
  is served-state; the operator picks (this design prefers the host-local deploy state dir).

## Honesty

- "Push Live in one click" means one click *starts* the deploy and streams it — it does not mean the button
  bypasses the rails: it writes the bound `release-write` grant, runs the real prepare/promote script, and
  surfaces the exact-SHA CI gate. The LLM stages; the operator authorises; the script is unchanged.
- Remediation and Fix-dirty are **propose-only**. No agent here merges, pushes, re-deploys or applies a fix
  without the operator's approval.
- `MBI_BEHAVIOR = 0`: no order, size, stop, broker, credential or 2FA in this path.
