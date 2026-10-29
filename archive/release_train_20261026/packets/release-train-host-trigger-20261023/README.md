# Release train host trigger: request and census timers (2026-10-23)

**Status: PROPOSED, NOT INSTALLED.** The operator installs it (AGENTS §17: a new production systemd entry; the
scheduler freeze). No agent runs `install.sh --apply`, `systemctl enable` or `crontab`.

- Task: `T-20261023-f5213b`. Plan: "Make the release train actually run, with real jobs in its queue", §1
  (operator-approved 2026-10-23).
- Operator, verbatim: "design and execute this right now and give it some test jobs to actually go and do so we can
  start putting real jobs in there. No more excuses."

## 1. Why

The release train has never ticked, not even in shadow. Only the n8n workflow `tradeai-fabric-release-train` writes
window requests, and its import (arming step F, `docs/ops/packets/release-train-arming-20261021/README.md`) is refused
by the §23.24 import gate. The claimer units (`tradeai-release-train-claim.{service,path,timer}`) are installed and
poll every minute, but they find `requests: []`.

This packet adds a trigger on the host that needs no n8n:

- **Request timers.** At each window time (18:00, 00:00, 06:00 and 08:00 ET), a timer runs the request lane's own
  writer, `scripts/release_train_window_request.py --window <slot> --append --shadow-only`. It appends one shadow
  `TrainWindowRequest@v1` for the claimer to answer.
- **Census timers.** Twenty minutes before each window, a timer runs the PR census, `scripts/pr_hygiene_audit.py`.
  The train then selects from a census less than 30 minutes old.

Step F stays the long-term path. `N8N_STEP_F_BOOTSTRAP_EXCEPTION_PROPOSAL.md` proposes how host-timer runs can supply
the runtime evidence that the §23.24 gate asks for. It is a proposal only.

## 2. What it installs (10 units, `~/.config/systemd/user/`)

| Unit | Fires (America/New_York) | Runs (from `~/trade-ai-releases/portfolio-server/CURRENT`) |
|---|---|---|
| `tradeai-release-train-request@.service` | started by its timers | `.venv/bin/python scripts/release_train_window_request.py --window %i --append --shadow-only` |
| `tradeai-release-train-request@1800.timer` | 18:00 | that service, instance `1800` |
| `tradeai-release-train-request@0000.timer` | 00:00 | instance `0000` |
| `tradeai-release-train-request@0600.timer` | 06:00 | instance `0600` |
| `tradeai-release-train-request@0800.timer` | 08:00 | instance `0800` |
| `tradeai-pr-census@.service` | started by its timers | `flock -n -E 75 /tmp/tradeai_pr_hygiene_audit.lock .venv/bin/python scripts/pr_hygiene_audit.py` |
| `tradeai-pr-census@1800.timer` | 17:40 | census before the 18:00 window |
| `tradeai-pr-census@0000.timer` | 23:40 | census before the 00:00 window |
| `tradeai-pr-census@0600.timer` | 05:40 | census before the 06:00 window |
| `tradeai-pr-census@0800.timer` | 07:40 | census before the 08:00 window |

### Timer settings

- Every timer has `OnCalendar=*-*-* HH:MM:00 America/New_York`, so DST is handled by systemd.
- Every timer has `Persistent=false`: a missed window is never replayed late.
- Every timer has `AccuracySec=30s`.

### The request service

- **State directory.** `TRADEAI_RELEASE_WINDOW_STATE_DIR=%h/trade-ai-releases/persistent-state/data/runtime/release_window`.
  - This is the directory the installed claimer resolves. Its unit sets no state env, so it uses
    `release_window.py`'s default, and its `.path` unit watches `<that>/train_requests/pending`.
  - Arming step G proves every reader agrees on it. The request service names it explicitly, so the writer and the
    claimer cannot drift apart.
- **Run identity.** `TRADEAI_RUN_ID=host-timer-%i`.
  - The writer reads `TRADEAI_RUN_ID` (`scripts/lib/lane_last_receipt.py` `RUN_ID_ENV`). It does **not** read
    `TRADEAI_N8N_RUN_ID`.
  - The plan named `TRADEAI_N8N_RUN_ID`. It is set as well, but nothing reads it (finding 1, §7).
  - The run id lands in the request's `requested_by.run_id` and in the lane receipt. That is how a host-timer request
    is told apart from an n8n request.
- **Executable path.** `ExecStart` uses the absolute path `%h/trade-ai-releases/portfolio-server/CURRENT/.venv/bin/python`.
  systemd refuses a relative executable path. This is the same form the installed claimer uses.

### The census service

- **Same argv and lock as n8n.** It uses the n8n allowlist entry `pr-hygiene-audit`'s live argv (no arguments;
  `live_arg []`) and the same lock (`/tmp/tradeai_pr_hygiene_audit.lock`, `flock -n`). It therefore never runs beside
  an n8n fire of that lane.
- **A held lock is a skip.** It exits 75, which is declared in `SuccessExitStatus`.
- **What it touches.** It is read-only on GitHub and git, and writes `data/runtime/pr-hygiene-audit_last.json`.
- **Which clone it reads.** Run from CURRENT (not a clone), it falls back to the canonical clone, the same way an n8n
  run does (`resolve_repo`, `CANONICAL_CLONE`).

### What stays inert

The request service is REQUEST_ONLY and `--shadow-only`. It never requests a live train.

- The claimer simulates shadow requests only.
- While `TRAIN_CONTROLLER_STATUS` is `BUILD_ONLY`, every live request is refused anyway.
- Nothing here merges, pushes, promotes, reads a credential, sends a message or touches a broker. MBI_BEHAVIOR = 0.

## 3. Prerequisites

1. This packet's PR is merged and released, so that CURRENT carries this packet and the writer with `--shadow-only`.
   `install.sh --apply` refuses otherwise.
2. The claimer units are installed and enabled. They have been since 2026-10-22; check with
   `systemctl --user list-timers tradeai-release-train-claim.timer`.
3. **Recommended:** #2033 (shadow P5: census queue, scratch candidate, durable report) is released first. Without it
   the claimer still answers each request with a receipt, but writes no `reports/<id>.json`.

## 4. Operator commands

All of these run on the host as `johnclaw`, from the released packet.

```bash
CUR=~/trade-ai-releases/portfolio-server/CURRENT
P=$CUR/docs/ops/packets/release-train-host-trigger-20261023
SD=~/trade-ai-releases/persistent-state/data/runtime/release_window

# 0. Dry runs (§0 rule 7). Neither writes anything.
cd $CUR && .venv/bin/python scripts/release_train_window_request.py --window 1800 --dry-run --shadow-only
cd $CUR && .venv/bin/python scripts/pr_hygiene_audit.py --dry-run | tail -5

# 1. Preview: a diff against the installed units, plus a read-only preflight. Writes nothing.
bash $P/install.sh --preview

# 2. Install. You type ACK-TRAIN-TRIGGER at the prompt.
bash $P/install.sh --apply
```

Expected output of `--apply`:

- `PREFLIGHT: OK (CURRENT -> …; writer has --shadow-only)`
- the `list-timers` table with all 8 timers
- `VERIFY <timer>: enabled, active`, eight times
- `archive (rollback source): ~/.config/systemd/user/archived-release-train-host-trigger-<stamp>`
- exit code 0

**Rollback.** You type `ACK-TRAIN-TRIGGER-ROLLBACK` at the prompt.

```bash
bash $P/rollback.sh --preview
bash $P/rollback.sh --apply
```

`rollback.sh --apply` does the following:

- disables and stops the 8 timers;
- moves the 10 installed units into `archived-release-train-host-trigger-rollback-<stamp>/`. Nothing is deleted;
- restores whatever the install archived, and re-enables a restored timer that was enabled before;
- runs `daemon-reload`.

Requests and receipts already in the spool stay where they are; they are the record.

## 5. Expected proof

Exit code 0 is not evidence (§0 rule 8). The proof is the following artifacts, at the first window after install.
For an install before 18:00, that is today's 18:00 window.

1. **The census fired at 17:40.**
   - `journalctl --user -u 'tradeai-pr-census@1800.service' --since today --no-pager` shows the run.
   - `jq -r .ok_at ~/trade-ai-releases/persistent-state/data/runtime/pr-hygiene-audit_last.json` is after 17:40 ET.
2. **The request timer fired at 18:00.**
   - `journalctl --user -u 'tradeai-release-train-request@1800.service' --since today --no-pager` shows
     `Starting`/`Finished` near 18:00:00, with the writer's JSON line `"disposition": "request"` and
     `"tick": "on_window"`.
3. **A `-win` request id exists.**
   - `ls $SD/train_requests/journal/rtw-$(date +%Y%m%d)-1800-win.json` exists.
   - `jq '.requested_by.run_id, .shadow' <that file>` prints `"host-timer-1800"` and `true`.
4. **The lane receipt was written.**
   - `jq '.ok_at, .run_id' ~/trade-ai-releases/persistent-state/data/runtime/release-train-request-1800_last.json`
     shows a time just after 18:00 and `host-timer-1800`.
5. **The claimer answered.**
   - `ls $SD/train_requests/receipts/rtw-$(date +%Y%m%d)-1800-win.json` exists (TrainWindowReceipt@v1).
   - With #2033 released, `ls $SD/train_requests/reports/rtw-$(date +%Y%m%d)-1800-win.json` also exists
     (ShadowTrainReport@v1).
   - The Releases page shows the shadow line.
6. **The schedule is armed.** `systemctl --user list-timers --all 'tradeai-release-train-request@*' 'tradeai-pr-census@*'`
   shows each NEXT time at its slot.

A STOP latch that is set makes the writer a `no_op` (`no_op_reason: stop_set`). That is a correct result, not a failure.
Clear the STOP before reading a missing request as a defect.

## 6. Registry, and what changes after the install

- **Registry rows.** `config/lane_registry.json` declares the 8 lanes as `release-train-request-timer-<slot>` and
  `pr-census-timer-<slot>`:
  - `scheduler.kind` is `systemd`, and `rollout_stage` is `shadow`. It is deliberately not `scheduler.stage`: that
    field is the n8n §23.11 stage, and it would make each row an n8n health-contract target;
  - `state` is `NEVER_SCHEDULED` until the install.
  After the install, a follow-up registry PR moves them to `ACTIVE`, citing `list-timers` and the first receipt, the
  same way the claimer rows were done on 2026-10-22. Until then, `check_registry_runtime_truth` reports these 8 rows
  as running while declared NEVER_SCHEDULED. That report is expected and is the cue for the PR.
- **Coexistence with n8n.**
  - **Request lanes.** If step F later publishes `tradeai-fabric-release-train`, both schedulers could fire a window.
    The journal is O_EXCL on the request id, and an on-window id is one per window, so the second request is a
    `duplicate` (exit 0), not a second train. Disable these timers with `rollback.sh` once n8n is proven.
  - **Census.** The census shares a lock and a receipt with the n8n lane `pr-hygiene-audit` (06:30 ET), so the two
    never overlap.
- **AGENTS.md.** It is not edited. The §23.25 cutover directive makes new scheduled lanes n8n lanes. This host
  trigger is the interim path the operator approved in the plan, and n8n step F remains the target.

## 7. Findings (each reported once)

1. **`TRADEAI_N8N_RUN_ID` is read by nothing.**
   - The task named `Environment=TRADEAI_N8N_RUN_ID=host-timer-%i`. The writer and `lane_last_receipt` read
     `TRADEAI_RUN_ID`.
   - Both are set. Without `TRADEAI_RUN_ID`, the run id would fall back to `manual-release-train-request-<slot>-<ts>`
     and lose the host-timer provenance.
2. **Fire time differs from the n8n design.**
   - The n8n design sends its request at W-90 (`request_lead_min: 90`). These timers fire at W itself, as the plan
     specifies.
   - Both are `on_window` (`[W-100 min, W+15 min)`), so the id is `-win` either way. The claimer simply gets the
     request later.
3. **The installed claimer differs from its proposed file.**
   - `~/.config/systemd/user/tradeai-release-train-claim.service` has no `Environment=TRADEAI_RELEASE_CHECKOUT=…`.
   - The proposed file in `docs/ops/packets/release-train-20261021/` added that line on 2026-10-22.
   - It is reported here only. The claimer is outside this packet (§0 rule 5: no remediation by a machine).
4. **Unique host-timer run ids are not possible.**
   - The plan suggested `host-timer-<slot>-<date>`, but systemd specifiers have no date.
   - `host-timer-<slot>` is unique per window in practice: the request id carries the date, and an on-window id is
     one per window.

## 8. Files

- `*.proposed`: the 10 units.
- `install.sh`: `--preview` and `--apply`.
- `rollback.sh`: `--preview` and `--apply`.
- `N8N_STEP_F_BOOTSTRAP_EXCEPTION_PROPOSAL.md`: the §23.24 bootstrap-exception proposal for step F.
- `tests/test_release_train_host_trigger_20261023.py`, CI gate `release_train_host_trigger_20261023`.
