# Release Train v2: arming packet for phases 5–7 (shadow, 18:00 canary, expand)

```
Status:      DRAFT, operator runbook. Nothing in it has been run against the host; every step is an operator act.
as_of:       2026-10-21T21:30:00-04:00
Measured at: branch integ/release-2-train-20261021 1ef9bdf8a (Release 2 integration: phases 1-4). The served
             CURRENT is d55da84d0-main-exact-phase2-20261021-200712 (Release 1). It does NOT carry the train code.
Plan:        ~/.claude/plans/joyful-skipping-wilkes.md, "Phases 5-7" (no calendar waits; each phase ends when its
             proof passes)
Authority:   MBI_BEHAVIOR = 0. No broker, order or credential path. The script reads no credential: it generates the
             capability key into its file and reports only its mode, owner and length. psql takes the DB password
             from the operator's own ~/.pgpass.
Tool:        scripts/ops/release_train_arm.sh (steps A-G); tests tests/test_release_train_arming_20261021.py and
             tests/release_train_arm_test.sh (CI gate RELEASE_TRAIN_ARMING_20261021)
```

This packet arms the release train in the order the plan requires, and then runs the proofs for phases 5–7. Sections
A–G are one-time host setup, and the arming script covers each of them. Sections H–J are the three phases. K is the
blocker that keeps every train needing a grant, and L is the fallback.

Every A–G step lists five things:

- **Command:** what the operator runs.
- **Dry run:** the same command without `--apply`. It writes nothing.
- **Expected:** the dry-run or apply output.
- **Verify:** a read-only check whose evidence is a durable artifact (§0 rule 8).
- **Rollback:** how to undo the step. Nothing is deleted; files are archived by rename (§0 rule 6).

Steps H–L are commands for the operator alone, with the expected output for each.

## Conventions

```bash
CUR=~/trade-ai-releases/portfolio-server/CURRENT          # the served release; every step reads its code
PY=$CUR/.venv/bin/python
ARM="bash $CUR/scripts/ops/release_train_arm.sh"          # once this packet is released; before that, run
                                                          # scripts/ops/release_train_arm.sh from a reviewed checkout
SD=~/trade-ai-releases/persistent-state/data/runtime/release_window   # the state dir (step G proves it)
GUARD=~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/guard
```

These rules apply to every run of the script:

- **On the host, as the right user.** The script refuses to run anywhere except host `ms01-openclaw`, and only as
  `johnclaw`, the user whose user units include `portfolio-server.service`. It never runs as root.
- **Dry run by default.** Writing anything needs `--apply` plus `TRADEAI_RELEASE_TRAIN_ARM_ACK=<that step's letter>`.
  Each step has its own acknowledgement, so one exported variable cannot arm everything.
- **Idempotent.** If a step is already in place, the script reports `NOOP`.
- **Never overwrites.** A file that exists and differs is a refusal, not a replacement.
- **Receipts.** Every `--apply` attempt appends one `ReleaseTrainArmReceipt@v1` line to
  `<state root>/data/runtime/release_train_arm/receipts.jsonl`. That includes refusals and NOOPs.
- **Read-only commands.** `$ARM plan` dry-runs A–G in order, and `$ARM status` prints one line per step.

## Ordered checklist

| # | Step | Gate before it | Who / grant | Done when |
|---|---|---|---|---|
| P0 | Release 2 merged and released (CURRENT carries `train-claim`, `/release-train-window`, the request lanes) | Release 2 review | operator, `release-write` naming the PR | `grep -c train-claim $CUR/scripts/release_window.py` ≥ 1 |
| A | Apply the queue migration | P0 | operator, as DB role `trade_ai` | `$ARM A --verify` → `store: APPLIED` |
| B | Create the capability key | — | operator | `$ARM B --verify` → `load_key: KEY_OK` |
| C | Create the delegation record (PAUSED, windows off); check the CLI refuses to arm it | — | operator, TTY for C.3 | `$ARM C --verify` → `PAUSED … none`, control `UNARMED` |
| D | Install the claimer units | P0, G's paths agree | operator (§17 systemd) | `$ARM D --verify` → `SAME; ENABLED` |
| H.0 | Shadow-enable PR (shadow switch, lane `live_arg`, stages) | review | reviewed PR, then released | see H.0 |
| E | Add 5 lanes to the relay live list; restart the relay and gateway; run the relay contract check | P0, H.0 | operator, config-write + unit grants | `$ARM E --verify` exit 0 |
| F | Import and publish `tradeai-fabric-release-train` | §23.24 import gate passes (**it refuses today**) | operator, `cron` grant naming it | `$ARM F --verify` → `ACTIVE` |
| G | Compare the state dirs (CC STOP, runner, CLI, gateway, path unit) | D | operator (read-only) | `verdict: MATCH` |
| H | Phase 5 shadow: four forced ticks plus five injected failures | A–G | operator | §H "done when" |
| I | Phase 6 18:00 canary: prerequisites, arm, enable 18:00, two status flips, proofs | H done; D2, D4, 16.0.0, 17.0.0 | operator | §I "done when" |
| J | Phase 7: 00:00, then 06:00 (with drain proof), then 08:00 (with macro calendar) | I done | operator | one clean train per window |
| K | Standing release without a per-train grant | reviewed protected-surface change | operator | §K |
| L | Fallback: manual release; STOP; revoke | — | operator | always available |

---

## A. Apply the queue migration

Applies `migrations/2026_10_21_release_queue.sql`. It creates two new tables, `release_queue_events` (append-only,
with triggers that refuse UPDATE, DELETE and TRUNCATE) and `release_queue` (a projection), and alters nothing that
already exists. Until it is applied, events go to `train_events.jsonl` and the CC queue reads `not_migrated`.

- **Command:** `RTARM_PSQL_ARGS='-h 127.0.0.1 -U trade_ai -d trade_ai' TRADEAI_RELEASE_TRAIN_ARM_ACK=A $ARM A --apply`
  - The script refuses unless `SELECT current_user` is `trade_ai`. That is the controller's `DB_USER`
    (`scripts/session13_db.py`), so the controller's role owns the tables. Applied as `postgres`, the tables would
    belong to a role the controller does not log in as, and the migration has no GRANT.
  - It skips the apply (`NOOP`) when both tables and both triggers already exist.
- **Dry run:** `$ARM A`. It scans the file for destructive SQL and prints the sha256. It does not connect.
- **Expected (dry run):**
  ```
  migration …/migrations/2026_10_21_release_queue.sql
    sha256 4c81a92c626f4248b53cc06c83099d8efa7c0167888b957982644449848f107d  creates (IF NOT EXISTS): release_queue_events, release_queue_events_pr_seq_idx, release_queue_events_train_seq_idx, release_queue_events_type_seq_idx, release_queue, release_queue_state_idx
    destructive statements: none (additive)
  ```
  Expected (apply): `APPLIED: store migrated (2 tables, 2 append-only triggers)`. A second run prints `NOOP`.
- **Verify:**
  - `RTARM_PSQL_ARGS=… $ARM A --verify` prints `store: APPLIED`.
  - `bash $CUR/scripts/cc_curl.sh -s http://127.0.0.1:7777/api/v2/coordination/release-train | jq .data.store.value.state`
    prints `"OK"` (it was `"NOT_MIGRATED"`).
- **Rollback:** `psql -h 127.0.0.1 -U trade_ai -d trade_ai -v ON_ERROR_STOP=1 -f $CUR/migrations/2026_10_21_release_queue.down.sql`.
  It renames both tables to `*_archived_20261021` and never drops them. The CC then reads `not_migrated`, and the
  controller falls back to JSONL.

## B. Create the capability key

The key is the HMAC key for `release_capability` (`~/.config/tradeai/release_train/capability.key`). `load_key`
accepts it only if it is a regular file (not a symlink), owned by this uid, mode 600, and at least 32 bytes after
strip. The script writes 32 random bytes as 64 hex characters, so the `.strip()` in `load_key` can never shorten it.
It writes the file `O_EXCL` with mode 600 inside a mode-700 directory, then fsyncs it.

- **Command:** `TRADEAI_RELEASE_TRAIN_ARM_ACK=B $ARM B --apply`
- **Dry run:** `$ARM B` prints `key …: ABSENT` and `WOULD: install -d -m 700 …; write 32 random bytes as 64 hex
  chars + newline, O_EXCL, mode 600, fsync`.
- **Expected (apply):** `APPLIED: capability key created at … (mode 600; contents never printed)`.
  - A second run prints `NOOP` and never regenerates the key.
  - A key that is present but bad (wrong mode, wrong owner, a symlink, too short) is refused and never touched.
- **Verify:** `$ARM B --verify` prints `key: OK` and `load_key: KEY_OK`. Then
  `stat -c '%a %U %s' ~/.config/tradeai/release_train/capability.key` prints `600 johnclaw 65`.
- **Rollback:** `mv ~/.config/tradeai/release_train/capability.key{,.archived-$(date -u +%Y%m%dT%H%M%SZ)}`.
  Every capability signed with the old key stops verifying, which fails closed. Never delete the key; agents never read it (§24.7).

## C. Create the delegation record (PAUSED), then check that the host CLI refuses to arm it

`~/.config/tradeai/release_train/delegation.json` is the standing policy record (`ReleaseDelegation@v1`). The script
renders it from `config/release_train_delegation.example.json` and changes only these fields:

- `delegation_id`: `rtd-<YYYYMMDD>-operator`;
- `operator.approved_at`: now, America/New_York;
- `approved_via`: `host_cli`;
- `notes`.

It asserts that `status` is `PAUSED` and that all four windows are `enabled: false`. It validates the record with
`release_delegation.validate`, then writes it `O_EXCL` with mode 600. The file lives outside the repository on
purpose: `release_delegation.load` refuses any path inside the repo, so no train can edit its own authority.

- **Command:** `TRADEAI_RELEASE_TRAIN_ARM_ACK=C $ARM C --apply`
- **Dry run:** `$ARM C` prints the record it would write, the `delegation_id` and a preview digest. `approved_at` is
  stamped at write time, so the applied digest differs from the preview.
- **Expected (apply):** `APPLIED: … written (mode 600): PAUSED <sha256> none`.
  - A second run prints `NOOP: delegation present (PAUSED …); never overwritten`.
  - A record that is present but invalid is refused and kept.
- **C.3, "accept its digest at the host CLI" (operator, at a TTY):**
  ```bash
  cd $CUR && $PY scripts/release_control_cli.py arm --delegation ~/.config/tradeai/release_train/delegation.json \
      --reason "C.3 check" --dry-run
  ```
  Expected: `{"code": "DELEGATION_PAUSED", "outcome": "REFUSED", …}`, exit 2.
  - **The CLI cannot accept a PAUSED record.** `arm` and `change-scope` call `release_delegation.load()` and refuse
    anything that is not `AUTHORIZED`, and only `status: ACTIVE` is authorized.
  - Accepting the digest *is* `arm`, and `arm` immediately writes `control.json` with mode `RUNNING`. So C stops at the
    refusal, which proves that the CLI reads the record and fails closed. The real acceptance is step I.2.
  - This is contradiction 1 in the findings.
- **Verify:** `$ARM C --verify` prints:
  - `delegation: PAUSED <digest> none; mode 600`;
  - from `release_control_cli.py status`: `"mode": "UNARMED"`, `"latch_state": "ABSENT"`.
- **Rollback:** `mv ~/.config/tradeai/release_train/delegation.json{,.archived-$(date -u +%Y%m%dT%H%M%SZ)}`. A missing
  record reads `MISSING`, which means not authorized.

## D. Install the controller claimer units (operator item O7)

This installs the reviewed `docs/ops/packets/release-train-20261021/tradeai-release-train-claim.{service,path,timer}.proposed`
byte for byte into `~/.config/systemd/user/`.

- The service is a oneshot: `CURRENT/.venv/bin/python scripts/release_window.py train-claim --apply`.
- The path unit watches `…/release_window/train_requests/pending`.
- The timer is the 1-minute fallback.
- While `TRAIN_CONTROLLER_STATUS` is `BUILD_ONLY`, a live request is refused `CONTROLLER_BUILD_ONLY`, and a shadow
  request runs simulate-only.

Before installing, the script:

- creates the spool dir, mode 700;
- refuses if the runner's state dir differs from the one the path unit hardcodes
  (`%h/trade-ai-releases/persistent-state/…`);
- refuses if CURRENT lacks `train-claim` or `.venv/bin/python`;
- refuses if an installed unit differs from the reviewed file.

It also runs the claimer's own dry run first.

**Do not install `docs/ops/packets/release-train-20261021/install_release_window_timer.sh`.** It schedules the
12:00/17:30 `release_window.py run` path, and the train windows are 18:00, 00:00, 06:00 and 08:00. See finding 7.

- **Command:** `TRADEAI_RELEASE_TRAIN_ARM_ACK=D $ARM D --apply`
- **Dry run:** `$ARM D`
- **Expected (dry run):**
  ```
    units in ~/.config/systemd/user: ABSENT; path+timer: NOT_ENABLED
    claimer dry run (read-only: lists pending requests, claims nothing):
      { "schema": "ReleaseTrainClaimRun@v1", "mode": "dry_run", "requests": [] }
    WOULD: install -d -m 700 …/release_window/train_requests/pending
    WOULD: install -m 0644 docs/ops/packets/release-train-20261021/tradeai-release-train-claim.service.proposed ~/.config/systemd/user/tradeai-release-train-claim.service
    (… .path, .timer …)
    WOULD: systemctl --user daemon-reload
    WOULD: systemctl --user enable --now tradeai-release-train-claim.path tradeai-release-train-claim.timer
  ```
  Expected (apply): `APPLIED: claimer units installed; path + timer enabled and active`. A second run prints `NOOP`.
- **Verify:**
  - `$ARM D --verify` prints `units: SAME; path+timer: ENABLED`.
  - `systemctl --user list-timers tradeai-release-train-claim.timer` shows the next run.
  - The durable proof that it ran: `systemctl --user show tradeai-release-train-claim.service -p ExecMainExitTimestamp -p Result`
    shows a recent exit with `Result=success`.
- **Rollback:**
  ```bash
  systemctl --user disable --now tradeai-release-train-claim.path tradeai-release-train-claim.timer
  A=~/.config/systemd/user/archived-release-train-claim-$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$A"
  mv ~/.config/systemd/user/tradeai-release-train-claim.{service,path,timer} "$A"/ && systemctl --user daemon-reload
  ```
  Pending requests then wait in the spool. Never edit the spool by hand (contract §14).

## E. Add the request lanes and `pr-hygiene-audit` to the relay live list; restart; run the relay contract check

Adds `release-train-request-1800`, `-0000`, `-0600`, `-0800` and `pr-hygiene-audit` to `TRADEAI_N8N_RELAY_LIVE_LANES`
in `~/.config/tradeai/n8n-live-lanes.env`. The relay and the gateway both read that file (`EnvironmentFile=`).

- The script rewrites only the `TRADEAI_N8N_RELAY_LIVE_LANES=` line. Every other line stays byte for byte. The
  2026-10-15 cutover generator rewrote the whole file; this script does not.
- It first archives the file as `n8n-live-lanes.env.bak-<stamp>-release-train-arm`, then writes the new one mode 600
  (tmp file, then rename) and reads it back.
- It restarts `tradeai-n8n-run-relay.service` and `tradeai-n8n-coordination-gateway.service` and checks both are active.
- It then runs `scripts/check_n8n_relay_contract.py --ids tradeai-fabric-release-train` with the scratch relay probe.
  The probe starts its own relay and never touches the live one.
- It is idempotent:
  - all five lanes listed, and both services started after the last edit: `NOOP`;
  - lanes listed but a service started before the edit: it only restarts.

**Do E after H.0 is released.** Until then each lane has `live_arg: null` and stage `shadow`. The executor's stage
clamp still runs a live-listed lane `--dry-run`, so listing it changes nothing. The dry run prints one `WARN` per lane
until H.0 is in CURRENT.

- **Command:** `TRADEAI_CONFIG_WRITE_GRANT=<grant id> TRADEAI_RELEASE_TRAIN_ARM_ACK=E $ARM E --apply`. The unit
  restarts happen under the same session's unit grant.
- **Dry run:** `$ARM E`
- **Expected (dry run, before H.0):**
  ```
    WARN: release-train-request-1800 live_arg is null in the served release: live-listed, it still runs --dry-run (PR H.0 sets live_arg and stage canary)
    (… one WARN per lane …)
    live list ~/.config/tradeai/n8n-live-lanes.env: present; missing: release-train-request-1800 release-train-request-0000 release-train-request-0600 release-train-request-0800 pr-hygiene-audit
    WOULD: cp -p … n8n-live-lanes.env.bak-<stamp>-release-train-arm (archive; never deleted)
    WOULD: rewrite ONLY the TRADEAI_N8N_RELAY_LIVE_LANES= line, adding: … (mode 600, tmp + rename); read back
    WOULD: systemctl --user restart tradeai-n8n-run-relay.service tradeai-n8n-coordination-gateway.service; is-active both
    WOULD: check_n8n_relay_contract.py --ids tradeai-fabric-release-train (scratch relay probe; never the live relay). Static pass now:
      {"schema":"N8nRelayContractCheck@v1","verdict":"PASS","workflows":["tradeai-fabric-release-train"],…,"findings":[],…}
  ```
  Expected (apply): `APPLIED: 5 lanes on the relay live list; relay + gateway restarted; relay contract PASS`.
- **Verify:**
  - `$ARM E --verify` prints `missing lanes: none; restart pending: 0`, and both services `active`.
  - The relay log `~/trade-ai-releases/persistent-state/data/runtime/n8n_relay/relay_log.jsonl` gains rows with
    `op: release_train_window` once F's workflow runs.
- **Rollback:**
  ```bash
  cp -p ~/.config/tradeai/n8n-live-lanes.env.bak-<stamp>-release-train-arm ~/.config/tradeai/n8n-live-lanes.env
  systemctl --user restart tradeai-n8n-run-relay.service tradeai-n8n-coordination-gateway.service
  ```
  The listed lanes fall back to dry runs. That is also the kill switch for the request lanes.

## F. Import and publish `tradeai-fabric-release-train` (operator item O5)

The script uses the same mechanics as the 2026-10-15 hermes-learning packet:

1. stage the generated file;
2. `n8n import:workflow --separate`, which imports it INACTIVE;
3. export what n8n now holds, and check `n8n_workflow_templates.py build-fabric --verify` against `INDEX.json`
   (graph `4c3a912e283c…`);
4. `n8n publish:workflow`;
5. `docker restart m8m-n8n`, then check that the row is `active` with an `activeVersionId`.

The stage is kept under `release_train_arm/wf-stage-<stamp>`. The script refuses to restart n8n within 10 minutes of
any release-train tick (16:30, 18:00, 19:15, 22:30, 00:00, 01:15, 04:30, 06:00, 06:30, 07:15, 08:00 and 09:15 ET). It
also refuses when the error workflow `tradeai-fabric-error` is not active.

**Blocked today. Do not route around it.** `scripts/check_n8n_import_ready.py`, the mandatory AGENTS §23.24 import
and activation gate, refuses this workflow with `framework_gate`:

- six platform elements fail (FW-P1 to FW-P6);
- every runtime obligation is UNPROVEN;
- exceptions are not accepted either: "exceptions UNVERIFIED: authenticated host approval consumer unavailable".

`--apply` therefore refuses with `check_n8n_import_ready.py refuses tradeai-fabric-release-train (AGENTS §23.24
activation bar); not routed around`, and writes a receipt. Until the operator resolves the §23.24 gate for this
workflow, phase 5 uses the host-only path in H.1(b). That path proves the controller, but not the n8n coordination
path. See finding 2.

- **Command (once the gate passes):** `TRADEAI_FABRIC_GRANT=<cron grant naming tradeai-fabric-release-train> TRADEAI_RELEASE_TRAIN_ARM_ACK=F $ARM F --apply`
- **Dry run:** `$ARM F`
- **Expected (dry run, today):**
  ```
    n8n row tradeai-fabric-release-train: ABSENT; error workflow tradeai-fabric-error: ACTIVE
    REFUSED tradeai-fabric-release-train tradeai-fabric-release-train  framework_gate
    1 checked, 1 refused
    WOULD REFUSE --apply: the mandatory import gate (AGENTS §23.24, check_n8n_import_ready.py) refuses this workflow
    graph check: ok 4c3a912e283c
  ```
- **Verify:**
  - `$ARM F --verify` prints `n8n row tradeai-fabric-release-train: ACTIVE`.
  - The durable proof is the `workflow_entity` row:
    `docker exec m8m-n8n-db psql -U n8n -d n8n -tA -c "SELECT active, \"activeVersionId\" FROM workflow_entity WHERE id='tradeai-fabric-release-train'"`.
  - The lane registry rows for the four request lanes then move `NEVER_SCHEDULED` → `ACTIVE` by the H.0 PR.
    `check_lane_registry` requires that an active workflow has a declaring row.
- **Rollback:**
  - Unpublish: `docker exec -e N8N_RUNNERS_BROKER_PORT=5690 m8m-n8n n8n update:workflow --id=tradeai-fabric-release-train --active=false`,
    then `docker restart m8m-n8n` (`docs/ops/ROLLBACK_COMMANDS.md`).
  - Nothing on the host needs undoing. Archive the row through n8n's own archive, and never delete it.

## G. Compare the CC STOP state_dir with the runner's

The whole design assumes one STOP latch: `<state_dir>/STOP.json`. These must all resolve the same directory:

- the CC (summary `state_dir` and `GET …/release-train/stop`);
- the runner as the claimer unit runs it (`release_window.STATE_DIR`);
- the host CLI (`release_control_cli.py status`);
- the gateway (its inline `TRADEAI_STATE_ROOT`);
- the claimer `.path` unit.

The step is read-only in every mode. A mismatch is reported with both paths and never fixed by the script
(§0 rule 5).

`release_window.py status` prints `latch_state` but **no `state_dir`** (finding 4). The script therefore compares the
CC latch with `release_window.py status`'s `latch_state`, and reads the directory from `release_window.STATE_DIR`
directly.

- **Command:** `TRADEAI_RELEASE_TRAIN_ARM_ACK=G $ARM G --apply`. It is still read-only and only adds a receipt.
- **Dry run:** `$ARM G`. `--verify` runs the same comparison and exits 1 on a mismatch.
- **Expected:**
  ```
    CC summary state_dir                             ~/trade-ai-releases/persistent-state/data/runtime/release_window  [release_window.STATE_DIR]
    CC GET /stop state_dir                           ~/trade-ai-releases/persistent-state/data/runtime/release_window
    runner release_window.STATE_DIR (claimer env)    ~/trade-ai-releases/persistent-state/data/runtime/release_window
    release_control_cli.py status state_dir          ~/trade-ai-releases/persistent-state/data/runtime/release_window
    gateway (inline env) state dir                   ~/trade-ai-releases/persistent-state/data/runtime/release_window
    claimer .path unit watch dir                     ~/trade-ai-releases/persistent-state/data/runtime/release_window
    latch: CC /stop vs release_window.py status      ABSENT vs ABSENT
    verdict: MATCH
  ```
- **Verify:** a STOP round trip proves that both sides read one file. Do it before arming, while nothing is armed:
  1. Press STOP in CC (or run `cd $CUR && $PY scripts/lib/release_train_stop.py stop --reason "G round trip"`).
  2. `cd $CUR && $PY scripts/release_window.py status | jq .latch_state` prints `"SET"`.
  3. `cd $CUR && $PY scripts/release_window.py clear-stop --reason "G round trip done"` archives the latch by rename.
     `resume` refuses while UNARMED (`RESUME_NOT_APPLICABLE`), so use `clear-stop` here.
- **Rollback:** none; the step writes nothing. On a mismatch, stop and report. Choosing which path wins is the
  operator's decision.

---

## H. Phase 5: shadow

**H.0 Shadow-enable PR (reviewed; released before E).** These are the exact diffs:

```diff
# config/release_train_n8n.json
-  "shadow": { "enabled": false,
+  "shadow": { "enabled": true,
# config/n8n_run_allowlist.json — each of release-train-request-1800 / -0000 / -0600 / -0800
-  "live_arg": null,
+  "live_arg": ["--append", "--shadow-only"],
# config/n8n_run_allowlist.json — pr-hygiene-audit (a real run writes data/runtime/pr-hygiene-audit_last.json)
-  "live_arg": null,
+  "live_arg": [],
# config/lane_registry.json — the four request lanes
-  "stage": "shadow"            (scheduler)      -  "state": "NEVER_SCHEDULED"
+  "stage": "canary"                             +  "state": "ACTIVE"      (only once F has published the workflow)
# config/lane_registry.json — pr-hygiene-audit
-  "stage": "shadow"  …  "dispatch": {"mode": "dry_run", …}
+  "stage": "canary"  …  "dispatch": {"mode": "live", …}
```

This PR also needs:

- the operator to mark the `pr-hygiene-audit` health contract REVIEWED (plan, Phase 0 list);
- the registry and allowlist tests to be updated in the same PR.

Without a PR-hygiene receipt, every train stops at select with `NO_OP (QUEUE_INCOMPLETE: no_receipt)`, and shadow
then proves only the tick path. `--shadow-only` makes a request lane write `shadow: true` whatever the delegation says.

**H.1 Force one shadow tick per window.** Run the four windows in the order 18:00, 00:00, 06:00, 08:00.

- **(a) Through n8n (preferred, once F is live).** Four runs of the manual trigger:
  `docker exec -e N8N_RUNNERS_BROKER_PORT=5690 m8m-n8n n8n execute --id=tradeai-fabric-release-train`, four times,
  under the `cron` grant. Each run forces the window with the oldest shadow coverage.
- **(b) On the host, without n8n (works today):**
  - dry run first: `cd $CUR && $PY scripts/release_train_window_request.py --window 1800 --dry-run`;
  - then append: `cd $CUR && $PY scripts/release_train_window_request.py --window 1800 --append --shadow-only`.
  - Repeat for `0000`, `0600` and `0800`. Each request is `off_window`, so it is `shadow: true` with expiry
    `requested_at + 60 min`.
  - The path unit claims it within seconds, or the timer within 60 s.

**Check each window.** Each command below names its durable artifact.

| What | Command | Expected |
|---|---|---|
| receipt | `jq '{state,mode,outcome,refusal,needs_action,simulated_effects}' $SD/train_requests/receipts/rtw-*-<slot>-f*.json` | `state COMPLETED`, `mode simulate`. `outcome NO_OP` for all four: shadow never reports a release. `needs_action` lists `LIVE_WOULD_REFUSE` (control UNARMED, delegation PAUSED, window disabled) and `NOT_RIDING` per excluded PR. 0600 and 0800 stop at the window rules, before select, with `NO_OP`. Their reason (`WINDOW_SKIPPED_NO_DRAIN` / `WINDOW_SKIPPED_MACRO_UNAVAILABLE`) is in the run record and events, not in the receipt, which has no reason field. |
| claim moved | `ls $SD/train_requests/{journal,pending,claimed}/` | each request in `journal/` and `claimed/`, none left in `pending/` |
| events | `tail -n 20 $SD/train_events.jsonl` (store not migrated), or `psql … -c "SELECT seq,event_type,train_id FROM release_queue_events ORDER BY seq DESC LIMIT 20"` (after A) | `classified`/`ready`/`held` rows per PR; no `merged`/`promoted` row |
| CC view | `bash $CUR/scripts/cc_curl.sh -s http://127.0.0.1:7777/api/v2/coordination/release-train \| jq '.data \| {armed,standing_policy,stop,store,census}'` | `armed.value false`, `standing_policy` PAUSED, `stop.value.state ABSENT`, `store` OK after A, `census.status COMPLETE` once the hygiene lane writes |
| reports | `sqlite3 -readonly ~/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite "SELECT kind,tier,subject,state,last_at FROM comms_intents WHERE kind LIKE 'release_train_%' ORDER BY last_at DESC LIMIT 12"` and `jq .email_mirror ~/trade-ai-releases/persistent-state/data/runtime/incident_notifier_last.json` | path (a): one `release_train_window_digest` per run, plus `release_train_delegation_reminder` (PAUSED). The P2 batch reaches Telegram, held 22:00–07:00. The digest and needs-action kinds are emailed (`email_mirror` SENT). Path (b) posts no intents, because n8n posts them. |

**H.2 Injected failures.** The controller never fills `injected_failures` in a receipt (it is hardcoded to `[]`,
finding 5). Each injection is therefore proven by its own artifact.

1. **A red check.**
   - In shadow the dry run does not wait for checks (`WOULD wait …`), so the host cannot show this.
   - Proof: run `TMPDIR=~/.cache/rtc $PY -m pytest -q tests/test_release_train_controller_20261021.py -k "non_success_mandatory_check_is_red or base_red_blames_nobody"`
     on CURRENT's code. Expected: all pass, and neutral, skipped, cancelled and missing all count as RED or PENDING.
   - The live proof is canary proof I.5(2).
2. **A conflicting PR.**
   - Pick one open PR that the census buckets `conflicting`
     (`jq '.summary.prs[] | select(.conflict==true) | .number' ~/trade-ai-releases/persistent-state/data/runtime/pr-hygiene-audit_last.json`).
   - Force one tick (H.1).
   - Expected: the receipt's `needs_action` has `{"code":"NOT_RIDING","pr":N,"text":"CONFLICTING"}`, and the PR is
     not in `members`.
   - For an in-merge conflict, run `cd $CUR && TMPDIR=~/.cache/rtc $PY scripts/release_window.py train-run --integrate --now <window ISO>`.
     It is a dry run, but it really merges in a scratch worktree, and it should print `ejected … conflict` for a PR
     that conflicts with an earlier member.
3. **STOP set mid-run.**
   - Append a request (H.1(b)). While the claimer runs it (`systemctl --user is-active tradeai-release-train-claim.service`
     reads `activating`), run `cd $CUR && $PY scripts/release_control_cli.py stop --reason "H.2 stop drill"`.
   - Expected:
     - the latch is `SET`, and `control_journal.jsonl` gains a `request_stop` row with `STOP_LATCHED` / `UNARMED`;
     - the receipt's `needs_action` carries `LIVE_WOULD_REFUSE … control state STOP…` at the next boundary;
     - the next request lane run appends nothing (`disposition no_op`, `stop_set`);
     - the CC shows STOPPED.
   - Clear it with `$PY scripts/release_window.py clear-stop --reason "H.2 done"`, which archives by rename.
   - Real halting at each boundary is proven by `-k "stop_before_merge or stop_after_merge or stop_during_promotion"`
     and by canary proof I.5(4).
4. **A corrupt latch.**
   - Run `printf '{corrupt' > $SD/STOP.json`.
   - Expected:
     - `release_window.py status` reports `latch_state: UNREADABLE`;
     - CC `stop.value.state` reads `UNREADABLE` with `effective_stop true`;
     - Needs-action shows P1 "Release windows halted: STOP latch unreadable";
     - a request lane run appends nothing (`stop_unreadable`);
     - `release_window.py run` and `plan` refuse with `REFUSED_STOP_UNREADABLE`, exit 2.
   - Clear it with `clear-stop --reason "H.2 corrupt latch drill"`, which archives the corrupt file into `windows/`.
5. **Crash, then reconcile.**
   - A shadow train writes no `trains/<id>/state.json`, so it has nothing to reconcile.
   - Kill the claimer mid-run: `systemctl --user kill -s SIGKILL tradeai-release-train-claim.service`.
   - Expected: the request stays in `claimed/` with an `ACKNOWLEDGED` receipt that is never finished, because the
     claimer re-reads only `pending/` (finding 6).
   - `release_window.py train-reconcile` (dry) prints `nothing to reconcile`.
   - The reconcile logic itself is proven by `-k "reconcile or uncertain_merge or unreadable_train_state"`, and live
     by canary proof I.5(5).

**Done when:** all four windows have a `COMPLETED`/`simulate` receipt, and each of the five injections produced the
artifact above. There is no calendar wait.

## I. Phase 6: 18:00 canary

**I.1 Prerequisites.** Each is an operator act, in this order:

1. **AGENTS 16.0.0, then 17.0.0, ratified** (D5).
   - 16.0.0 is the cutover standard (a local PROPOSED patch). 17.0.0 is the train amendment: agents queue and never
     merge; standing delegation; windows and merge freeze; STOP semantics; additions to the §17 list; AI_WORK_POLICY
     train pushes.
   - Neither text is in this repository, so this packet cannot cite their sections.
2. **The GitHub App and the `train/**` ruleset** (D2, `docs/ops/RELEASE_TRAIN_GITHUB_APP.md` §2–§6):
   - create the App (Contents RW, Pull requests RW, Checks R, Metadata R; webhook off);
   - install it on `tardeai` only;
   - put the key at `~/.config/tradeai/release_train/github-app.pem`, mode 600;
   - create ruleset `release-train-refs` on `refs/heads/train/**` (restrict creations, updates and deletions; bypass:
     the App only).
3. **The App token writer (a reviewed PR; finding 3).** `GhCliWriter` pushes with `git push origin` and merges with
   `gh api` as the host's gh user. Nothing mints an installation token. Flipping `GITHUB_WRITES_STATUS` alone would
   write as the operator's user, which is D2 option (b), not the decided (a). Once the ruleset exists, that user's push
   to `train/*` is refused. So a PR must first mint a 1-hour installation token per reservation (§5 of the App doc)
   and pass it as `GH_TOKEN` to the writer's child processes only. The PR touches a protected surface
   (`release_train_controller.py`), so it ships by the manual path (L.1).
4. **`ci-gate` as a required context on `main`** (D4; a branch-protection change, §17). `ci-gate` is the batch
   qualifier, and capabilities bind it.
5. **The standing-release binding (K), or one grant per train.** Without either, `prepare` refuses, and a train that
   has merged ends `MERGED_NOT_LIVE`.

**I.2 Arm (TTY).**

1. Edit `~/.config/tradeai/release_train/delegation.json`: set `"status": "ACTIVE"`, and keep every window disabled.
2. Run `cd $CUR && $PY scripts/release_control_cli.py arm --delegation ~/.config/tradeai/release_train/delegation.json --reason "canary arm" --dry-run`.
   Expected: `DRY_RUN`, the digest, and `phrase: "ARM EPOCH 1"`.
3. Run the same command without `--dry-run`, and type `ARM EPOCH 1`.
   Expected: `{"outcome": "ARMED", "epoch": 1, "policy_digest": "<sha256>"}`.
4. Verify: `release_control_cli.py status` shows `mode RUNNING`, `epoch 1`, and `accepted_policy_digest` equal to the
   file's digest.
5. Rollback: `release_control_cli.py revoke --reason …` (TTY; `REVOKE EPOCH 2`).

**I.3 Enable 18:00 only.**

1. Edit the 1800 slot to `"enabled": true`. This changes the digest.
2. Run `release_control_cli.py change-scope --delegation … --reason "enable 18:00 canary"`, dry run first, then type
   the `CHANGE_SCOPE EPOCH n` phrase.
3. Then the reviewed allowlist diff for `release-train-request-1800`:
   `-  "live_arg": ["--append", "--shadow-only"],` / `+  "live_arg": ["--append"],`
4. Verify: `$PY scripts/release_window.py train-plan --now <today>T18:00` prints `window … slot 1800 (canary) …
   enabled=True` and no `LIVE WOULD REFUSE: delegation` line.

**I.4 Status flips (two reviewed PRs, each released by the manual path; both files are protected surfaces).**

```diff
# PR 1 — scripts/lib/release_train_controller.py (after I.1 items 1-4)
-TRAIN_CONTROLLER_STATUS = "BUILD_ONLY"
+TRAIN_CONTROLLER_STATUS = "ACTIVE"
# and tests/test_release_train_controller_20261021.py: test_cli_live_is_refused_while_build_only and
# test_live_request_is_refused_while_build_only pin BUILD_ONLY via monkeypatch / live_status="BUILD_ONLY".

# PR 2 — scripts/lib/release_train_controller.py (after the App token writer, I.1 item 3)
-GITHUB_WRITES_STATUS = "PROPOSED"
+GITHUB_WRITES_STATUS = "ACTIVE"
```

**I.5 Proofs.** One live train runs per 18:00 window, so the proofs take one window each (finding 8). Each proof's
evidence is the receipt plus `train_events.jsonl` (or the store) plus the served SHA, never an exit code.

| # | Proof | How | Expected artifact |
|---|---|---|---|
| 1 | Success | A docs-only eligible PR queued; the 18:00 window | `outcome RELEASED_VERIFIED`; `readlink -f $CUR` names the merge SHA; CC `last_verified` is this train; `train_measurements.jsonl` row |
| 2 | Failed validation | A canary PR whose `ci-gate` fails (a deliberately red test in a probe PR), alone in the queue | `FAILED_PRE_MERGE`; batch PR not merged; `main` unchanged; needs-action item |
| 3 | Rollback | First check that the drill page answers non-200: `bash $CUR/scripts/cc_curl.sh -o /dev/null -w '%{http_code}' http://127.0.0.1:7777/api/v2/__rt_rollback_drill`. Then, for one window, add the drop-in `~/.config/systemd/user/tradeai-release-train-claim.service.d/rollback-drill.conf`: `[Service]` / `Environment="TRADEAI_RELEASE_WINDOW_PAGES=/v3/ /v3/system /v3/cio /api/v2/__rt_rollback_drill"`. That makes verification stricter, not weaker. | `ROLLED_BACK`; CURRENT back on the bound target; STOP latched; `quarantine.jsonl` row; P1 from the host notifier. Then archive the drop-in, run `train-quarantine-resolve --live` with evidence, and `resume` (TTY) |
| 4 | STOP in each phase | `release_control_cli.py stop --reason …` (or CC STOP) during: (a) integrate/local test (W-90 to W); (b) qualify (waiting ≤ 600 s for checks); (c) after merge, while waiting for push/main checks; (d) during promote | (a, b) `STOPPED`, nothing merged; (c) `MERGED_NOT_LIVE`, `main` has the batch, CURRENT unchanged; release main by L.1; (d) verification completes, then it settles. Each: `control.json` passes through STOP_REQUESTED → ACKNOWLEDGED → SETTLING → STOPPED with timestamps; `resume` is a new epoch |
| 5 | Crash recovery | During qualify: `systemctl --user kill -s SIGKILL tradeai-release-train-claim.service` | The next run refuses `REFUSED_RECONCILE_FIRST`. `release_window.py train-reconcile` (dry) lists the pending intent. `--live` decides ABSENT, refunds the reservation and closes the train. An effect that cannot be decided latches STOP (AMBIGUOUS) |

**Done when:** all five proofs have their artifacts.

## J. Phase 7: expand

Each window goes live once its own proof passes. Windows can go live in consecutive windows.

1. **00:00.**
   - Set the 0000 slot `enabled: true`, then run `change-scope` (TTY).
   - Allowlist `release-train-request-0000` `live_arg` becomes `["--append"]` (reviewed PR).
   - Proof: one 00:00 train reaches `RELEASED_VERIFIED`. A `NO_OP` with nothing eligible proves only the tick path.
2. **06:00, with its drain proof.**
   - The controller hardcodes `UnprovenDrain`, so 06:00 is always `WINDOW_SKIPPED_NO_DRAIN`.
   - Needed: a reviewed PR that replaces it with a real `DrainProbe`. The controller is a protected surface, so it ships
     by L.1.
   - The probe must show that no lane is running or due inside the promote span. The evidence is the 05:30–07:00
     schedule (crontab, n8n `/due`, user timers), and that every lock the five named services hold is free.
   - Then enable the slot, and change `live_arg` as for 00:00.
   - Proof: a 06:00 train whose receipt records `drain.ok true` and `RELEASED_VERIFIED`.
3. **08:00, with the macro calendar.**
   - `MacroCalendar` reads `~/.config/tradeai/release_train/macro_calendar.json` (`MacroReleaseCalendar@v1`). The
     provider is being built on `feat/macro-calendar-20261021`, which has no commits yet (it is at main `d55da84d0`).
     While the file is absent, 08:00 is always `WINDOW_SKIPPED_MACRO_UNAVAILABLE`.
   - The latest start is 09:00 minus the worst measured promote, verify and rollback time minus 10 minutes. It needs
     measured rows in `train_measurements.jsonl`, and rollback is measured only by I.5(3). The delegation's
     `latest_start_et` (example `08:10`) caps it.
   - Until three durations are measured, 08:00 is `WINDOW_SKIPPED_UNMEASURED` even with a calendar.
   - Proof: a non-macro day releases with `latest_start` recorded, and a macro day records
     `WINDOW_SKIPPED_MACRO_MACRO_DAY`. A stale calendar records `WINDOW_SKIPPED_MACRO_STALE`.

## K. The standing-release blocker

`cio_phase2_exact_main_deploy.sh` `prepare` and `promote` call `release_grant_preflight.py`. That requires a guard
`release-write` grant whose text names this PR, SHA or campaign (`release_grant_binding`). The train runs the deploy
with `TRADEAI_RELEASE_CAMPAIGN=release-train-<train_id>` and `TRADEAI_RELEASE_PR=<batch PR>`.

The train id ends in random hex (`rt-YYYYMMDD-HHMM-xxxxxx`), so an operator cannot name it in advance. **Until K
lands, every train needs an operator grant naming its batch PR**, issued after the batch PR opens and before the
merge:

```bash
"$GUARD" grant release-write --for 2h --uses 3 \
  --reason "release-train <train_id> PR #<batch PR> actions=prepare,promote,verify,rollback"
```

Without the grant, `prepare` refuses after the merge, and the train ends `MERGED_NOT_LIVE`. While the ledger holds
one grant per tier (`guard_ledger.py`), this grant also replaces any other active `release-write` grant (packet
release-train-20261021 §1.2).

**Proposed change (a reviewed PR to protected surfaces; not built here):**

- `release_grant_preflight.py` gains a second binding source, the host capability ledger. It accepts a `prepare` or
  `promote` only when all of these hold:
  - the action runs under campaign `release-train-<train_id>`;
  - the capability ledger at `<state_dir>/capabilities.json` holds a **RESERVED** intent for that train, for action
    `prepare_release` / `promote_release`, whose capability binds this exact `--sha` (the merge commit), the artifact
    digest (promote) and a service set inside the delegation's;
  - the capability's signature verifies with the host key;
  - its delegation digest and epoch equal the accepted ones in `control.json`;
  - the control mode is `RUNNING` and the latch is `ABSENT`.
- Nothing from the environment grants anything: the campaign only *identifies* the train, and the authority is the
  signed reservation that the controller already holds under the global `.lock`.
- The guard ledger is not consumed. The capability's attempt budget is the accounting.
- An expedited per-PR grant keeps working unchanged.
- Tests: forged, expired, wrong-SHA, wrong-phase and replayed reservations; STOP or epoch change between reserve and
  preflight; a reservation for another train.
- It changes `scripts/release_grant_preflight.py` and `scripts/lib/release_grant_binding.py`, which are protected
  surfaces, so it ships by L.1 after 17.0.0 is ratified.

## L. Fallback: the manual release, STOP and revoke

The fallback holds through every phase.

1. **Manual release (the current process):**
   - grant: `"$GUARD" grant release-write --for 75m --uses 3 --reason "PR #<N> sha <sha> …"` (§24.8);
   - then, in `~/tradeai-exact-main-20260827` at origin/main: `TRADEAI_RELEASE_PR=<N> bash scripts/cio_phase2_exact_main_deploy.sh prepare`,
     then `promote <prepared dir>`.
   - The train and a manual release exclude each other on `<state_dir>/.lock`.
2. **STOP (the safe direction; no confirmation).** Use any of these:
   - the CC STOP button (`POST /api/v2/coordination/release-train/stop`);
   - `cd $CUR && $PY scripts/release_control_cli.py stop --reason "…"`;
   - `$PY scripts/lib/release_train_stop.py stop --reason "…"`.

   Each writes `STOP.json` first, then the controller acknowledges at its next boundary. STOP is separate from the
   trading kill switch.
3. **Resume after a STOP:**
   - while armed: `release_control_cli.py resume --reason …` at a TTY, which issues a new epoch;
   - while unarmed: `release_window.py clear-stop --reason …`.

   Don't use `clear-stop` while armed. It archives the latch without a new epoch.
4. **Pause after the current train:** `release_control_cli.py pause --reason …`.
5. **Revoke the delegation:**
   1. `cd $CUR && $PY scripts/release_control_cli.py revoke --reason "…" --dry-run`, then the same command without
      `--dry-run`, typing `REVOKE EPOCH n`. No capability is issued afterwards, and the queue and history stay readable.
   2. Set `"status": "REVOKED"` in `delegation.json`.
   3. Optionally suspend the GitHub App installation, which kills tokens within the hour.
   4. Optionally disable the claimer units (rollback D) and unpublish the workflow (rollback F).

   Re-arming after a revoke is `arm` again.

---

## Findings: contradictions and gaps (each reported once; nothing was changed to resolve them)

1. **C cannot "accept the PAUSED digest".** `release_control_cli.py arm` and `change-scope` refuse any delegation
   that is not ACTIVE (`DELEGATION_PAUSED`), and `arm` itself sets mode `RUNNING`. So "create PAUSED, then accept its
   digest" is not possible. The packet ends C with a refusal check, and accepts the digest at I.2 after setting
   ACTIVE with every window still off. Every later edit (enabling a window) changes the digest and needs `change-scope`.
2. **F is blocked by AGENTS §23.24.** `check_n8n_import_ready.py` refuses `tradeai-fabric-release-train`
   (`framework_gate`: FW-P1–P6 fail, runtime UNPROVEN, exceptions UNVERIFIED). The n8n contract's O5 ("import and
   activate under a cron grant") and §10 ("forcing ticks through n8n is preferred") say nothing about the gate.
   Phase 5 can run host-only (H.1(b)), but the n8n path, its digests and its emails cannot be proven until the gate
   passes.
3. **`GITHUB_WRITES_STATUS` does not deliver D2.** `GhCliWriter` uses `git push origin` and the host `gh` token.
   There is no App token minting anywhere ("Phase 3 code and is not shipped", App doc §5). The `train/**` ruleset
   that bypasses only the App would refuse those pushes.
4. **`release_window.py status` reports no `state_dir`.** UI contract §6 says "the operator confirms that
   `GET /stop`'s `state_dir` equals the path `release_window.py status` reads". `Runner.status()` returns
   `latch_state`, `latch`, `last`, `multi_window_grant_status`, `windows_et`, `grace_min` and `grant_token`, and no
   path. Step G reads `release_window.STATE_DIR` instead.
5. **The `injected_failures` receipt field is always `[]`.** It is hardcoded in `_receipt`, and the controller has no
   injection hook, while contract §7 says it records "which injected failure … was exercised and how it behaved".
   Also, a dry-run (shadow) train never halts on STOP or a corrupt latch. It records `LIVE WOULD REFUSE` and runs on,
   so shadow cannot prove halting; only fixture tests and the canary can.
6. **No watchdog for an orphaned claim.** A claimer killed after `ACKNOWLEDGED` leaves the request in `claimed/`
   forever: `process_requests` reads only `pending/`, and nothing finishes the receipt. Contract §12 cites "the
   controller's independent watchdog (Phase 3)", which does not exist.
7. **Two release schedules.** `docs/ops/packets/release-train-20261021/README.md` §5 and §8, and
   `install_release_window_timer.sh`, schedule `release_window.py run` at 12:00 and 17:30 ET. The plan and the train
   use 18:00, 00:00, 06:00 and 08:00. Installing both would give two release paths. This packet installs only the
   claimer.
8. **"No minimum number of days" versus one train per window.** Live requests are on-window only (an off-window
   request is always shadow), and there is one train per window. With only 18:00 enabled, the canary's 5 proofs (STOP
   in 4 phases) need about 8 separate 18:00 windows. That is a calendar floor the plan says does not exist.
9. **C9 refusal codes are out of date in the controller.** Contract rev 3 and the receipt schema add
   `RECONCILE_REQUIRED`, `QUARANTINED_LINEAGE`, `CONTROLLER_ERROR` and `CONTROLLER_FAILED`. The controller's
   `REFUSAL_CODES` and `REFUSAL_MAP` still map those cases to `STOP_SET`, `NOT_ARMED` or `LOCK_HELD`. The packet
   README §11.6 (b) still says the schemas and the validator are absent, but Release 2 ships both
   (`config/schemas/release_train/train_window_*.v1.schema.json`, `scripts/lib/release_train_window_view.py`).
10. **STOP vocabulary drift.** UI contract item 5 says `summary.stop` uses `CLEAR`/`LATCHED`/`UNREADABLE`. API
    revision 2 replaced that with `ABSENT`/`SET`/`UNREADABLE`.
11. **The served release is Release 1.** CURRENT (`d55da84d0`) has no `train-claim` and no `/release-train-window`.
    Every step refuses until Release 2 is released (P0).
12. **The migration owner.** The migration's own header says "Apply (operator): `psql "$DB" …`" without naming a
    role, and it grants nothing. Applied as a superuser, the controller's `trade_ai` role could not write. Step A
    pins the role.
13. **Possible §23.24 reach into H.0.** §23.24's activation bar reads "no activation or stage promotion without
    passing". H.0 moves `pr-hygiene-audit` and the request lanes from stage `shadow` to `canary` on workflows that do
    not pass the gate. Recent dispatcher lanes (disk-hygiene, 2026-10-20) were promoted in this way. Whether the bar
    covers lane stages is the operator's ruling.

## Dry run (sandbox, quoted)

`scripts/ops/release_train_arm.sh plan` ran on 2026-10-22T01:08Z in a test sandbox under `TMPDIR=~/.cache/rtarm`:

- HOME and every path rebased;
- stub psql, systemctl, docker and curl;
- the code root is a symlink farm onto this branch.

Paths are shortened to `…`.

```
== release train arming PLAN (dry run; nothing is written)
   user johnclaw host ms01-openclaw; code root …/s/code; state dir …/release_window (env:TRADEAI_RELEASE_WINDOW_STATE_DIR)
== A
  sha256 4c81a92c…f107d  creates (IF NOT EXISTS): release_queue_events, …, release_queue, release_queue_state_idx
  destructive statements: none (additive)
  WOULD (apply): psql $RTARM_PSQL_ARGS -X -v ON_ERROR_STOP=1 -f …/migrations/2026_10_21_release_queue.sql
== B
  key …/capability.key: ABSENT
  WOULD: install -d -m 700 …/release_train; write 32 random bytes as 64 hex chars + newline, O_EXCL, mode 600, fsync
== C
  WOULD write …/delegation.json (O_EXCL, mode 600): status PAUSED, windows 1800/0000/0600/0800 all disabled
  rendered delegation_id rtd-20261021-operator, digest 286e4359…d8b2 (approved_at is stamped at write time, …)
    expected while PAUSED: REFUSED DELEGATION_PAUSED (arm accepts only an ACTIVE record; acceptance is step I)
== D
  units in …/systemd/user: ABSENT; path+timer: NOT_ENABLED
    { "schema": "ReleaseTrainClaimRun@v1", "mode": "dry_run", "requests": [] }
  WOULD: systemctl --user enable --now tradeai-release-train-claim.path tradeai-release-train-claim.timer
== E
  WARN: release-train-request-1800 live_arg is null in the served release: … (PR H.0 sets live_arg and stage canary)
  live list …/n8n-live-lanes.env: present; missing: release-train-request-1800 … pr-hygiene-audit
    {"schema":"N8nRelayContractCheck@v1","verdict":"PASS","workflows":["tradeai-fabric-release-train"],…}
== F
  REFUSED tradeai-fabric-release-train tradeai-fabric-release-train  framework_gate
  WOULD REFUSE --apply: the mandatory import gate (AGENTS §23.24, check_n8n_import_ready.py) refuses this workflow
  graph check: ok 4c3a912e283c
== G
  latch: CC /stop vs release_window.py status      ABSENT vs ABSENT
  verdict: MATCH
```

## Not done, deliberately

This packet does none of the following:

- no DB write, unit install, live-list edit, n8n import, key creation, grant or push;
- no AGENTS.md or adapter edit;
- no change to any protected surface of the train.

The H.0, I.4, J and K PRs, and the App token writer, are proposals for the operator.
