# Operator-only capture of the missing reconciliation inputs

Status: DRAFT — commands prepared, not executed; no source or scheduler authority
as_of: 2026-10-24T04:18:00Z
Design-Task: DSN-20261024-registry-reconcile-P1-T31

First prefer the original coordinator command/head, proposed diff and its retained cron/unit capture. A new capture can explain the present host state; it cannot establish exactly what the earlier command observed.

The source task is still blocked by WP-21 claim `20261024T021437Z-codex-8df6cf34`. These commands collect inputs/read-only previews only. They neither grant registry editing nor release that claim. Only the coordinator can announce the source claim's availability after the verified batch-14 merge. Do not retry a refusal or run `--write` as a shortcut.

## Four-hour read-only grant

Operator, in the canonical checkout:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
bin/guard grant cron --for 4h --uses 6 --reason "Registry drift audit: read-only crontab census and reconciliation input capture only; no cron install/replace/remove, no timer/service changes, no --write"
```

This scope technically covers cron replacement/removal; the task authorization above permits reads only. If an active grant conflicts, stop and ask its operator to reconcile the grant rather than automatically replacing it. User-systemd queries below are read-only. If a query encounters a guard or file-read refusal, retain that exact refusal and stop the affected capture; do not elevate or bypass it. No service restart/enable/disable command is part of this packet.

## Capture from the exact reviewed coordinator tree

At this audit the coordinator tree was `/home/johnclaw/wt-batch14-20261024`, HEAD `3693b3d2cdfdb3289ed7c38321f8313c8b517c23`. If that head has changed, the operator/coordinator must select and record the actual intended immutable source head before adapting the binding below.

```bash
cd /home/johnclaw/wt-batch14-20261024
umask 077
capture_dir=$(mktemp -d /home/johnclaw/.cache/rtc/registry-default-inputs-20261024.XXXXXX)
PYTHONPATH=/home/johnclaw/.cache/rtc/nopg \
  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python \
  - "$capture_dir" <<'PY'
import contextlib
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
expected = "3693b3d2cdfdb3289ed7c38321f8313c8b517c23"
actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
if actual != expected:
    raise SystemExit("STOP: source head changed; coordinator must rebind capture")
sys.path[:0] = [str(Path.cwd()), str(Path.cwd() / "scripts")]
from scripts import reconcile_lane_registry as R

files = [
    R.REGISTRY_PATH, R.RATIONALIZATION_PATH, R.EVIDENCE_PATH, R.STAY_TOKENS_PATH,
    Path("scripts/reconcile_lane_registry.py"), Path("scripts/lib/lane_registry.py"),
    Path("scripts/lib/n8n_coordination_gateway.py"), Path("scripts/pipelines/pipeline_manifest.py"),
]
def digests():
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

before = digests()
started = datetime.now(timezone.utc).isoformat()
with (out / "default-preview.json").open("x") as stdout, (out / "capture.stderr").open("x") as stderr:
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        rc = R.main(["--dry-run", "--json", "--snapshot-out", str(out / "scheduler-snapshot.json")])
finished = datetime.now(timezone.utc).isoformat()
after = digests()
if before != after:
    raise SystemExit("STOP: source inputs changed during capture; discard acceptance, retain evidence")
receipt = {
    "schema": "RegistryReconcileInputCapture@v1", "head": actual,
    "started_at_utc": started, "finished_at_utc": finished,
    "input_sha256": before, "source_inputs_unchanged": True,
    "mode": "dry-run; no registry write or scheduler mutation", "exit_code": rc,
    "snapshot_sha256": hashlib.sha256((out / "scheduler-snapshot.json").read_bytes()).hexdigest(),
    "snapshot_fixed_date_warning": "snapshot captured_on is hardcoded2026-10-09; use this receipt's actual UTC times",
}
(out / "capture-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(out)
raise SystemExit(rc)
PY
```

Preserve a nonzero exit and its private summary; do not mark a partial/failed collection accepted. A successful preview never approves its proposed semantic changes. The command reads cron and user units, including unit definitions and calendar cadence. It does not start a workflow/job or query a production database. The capture directory is private; do not publish raw scheduler commands without reviewing their contents.

## Review required after capture

Give the exact capture receipt, snapshot and bound source head to the registry worker. Once the coordinator has released the source claim, that worker must first take the source task, then replay with `--snapshot-in` and compare **in memory**. For every changed lane/JSON leaf, record before/after, source declaration and captured line/unit reference, F ID, token/normalization cause, effect on admission and reviewed retain/change disposition. Include population/order changes and all scheduler/state/dispatch/live invariants. Stop on ambiguity or a changed source binding. Do not mechanically commit a full generated registry.

Run existing relevant fixture gates with psycopg2 hidden and isolated evidence, then prepare an ordinary reviewed PR. Operator source/authority decisions remain distinct from an audit grant. This packet adds no scheduler, live-mode or cutover authorization.
