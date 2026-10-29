#!/usr/bin/env python3
"""Run one named repair in its own operator-installed systemd service.

Default / --dry-run is offline: no environment loading, DB, service or provider
calls. Only the named unit uses --apply. Receipts distinguish pending from work.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from lib.pipeline_repair_handoff import independently_owned

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("enrichment", "orchestrator")
NO_CONSUMER_REASON = (
    "External CLI caller: config/systemd/user/tradeai-pipeline-repair@.service, "
    "NOT installed by this PR. PipelineRepairRun@v1 receipts are operator acceptance "
    "evidence described in docs/ops/PIPELINE_SUPERVISION_20261029.md; no automated "
    "receipt consumer yet. Existing monitoring continues to consume pipeline_runs."
)


def command_for(kind: str) -> list[str]:
    if kind == "enrichment":
        return [sys.executable, str(ROOT / "scripts/pipeline_watchdog.py"), "--enrichment-only", "--no-telegram"]
    if kind == "orchestrator":
        # Same safe flags as the existing remediation recipe; label is ET hour.
        from remediate_pipeline_failures import _pick_run_label

        label = _pick_run_label()
        return [
            "flock",
            "-n",
            "-E",
            "75",
            "/tmp/screener_pm.lock",
            sys.executable,
            str(ROOT / "scripts/trade_ai_orchestrator.py"),
            "--run-label",
            label,
            "--skip-market-check",
            "--no-llm",
            "--no-alerts",
            "--allow-underfilled",
        ]
    raise ValueError("unknown repair")


def _receipt(kind: str, data: dict) -> None:
    state = Path(os.environ.get("TRADEAI_STATE_ROOT", str(ROOT)))
    target = state / "data/runtime" / f"pipeline_repair_{kind}_last.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=target.parent, prefix=target.name + ".", delete=False) as out:
        json.dump(data, out, indent=2)
        out.write("\n")
        path = out.name
    os.replace(path, target)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("kind", choices=KINDS)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    command = command_for(args.kind)
    if args.dry_run or not args.apply:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "kind": args.kind,
                    "command": command,
                    "budget_s": 240 if args.kind == "enrichment" else 1800,
                    "writes": False,
                    "calls": False,
                }
            )
        )
        return 0
    if (
        os.environ.get("TRADEAI_PIPELINE_REPAIR_KIND") != args.kind
        or os.environ.get("HEALTH_TICK_STEP_TIMEOUT_S")
        or not independently_owned(args.kind)
    ):
        print("refused: requires independently owned named repair service", file=sys.stderr)
        return 2
    started = datetime.now(timezone.utc).isoformat()
    data = {
        "schema": "PipelineRepairRun@v1",
        "kind": args.kind,
        "started_at": started,
        "status": "running",
        "recovered": False,
        "budget_s": 240 if args.kind == "enrichment" else 1800,
    }
    _receipt(args.kind, data)
    env = {**os.environ, "TRADEAI_DEV_ROOT": str(ROOT)}
    # Unit owns all descendants; the enrichment child owns/reaps its batch. Keep
    # the service's KillMode=control-group backstop, never weaken health-tick.
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            check=False,
            stdout=subprocess.PIPE if args.kind == "enrichment" else None,
            text=True,
        )
        rc = proc.returncode
        if args.kind == "enrichment":
            try:
                report = json.loads(proc.stdout.strip().splitlines()[-1])
                counts = {k: report[k] for k in ("completed", "failed", "deferred")}
                if any(type(value) is not int or value < 0 for value in counts.values()):
                    raise ValueError("invalid completion counts")
                data.update(counts)
                if counts["failed"]:
                    rc = rc if rc not in (0, 75) else 1
                elif counts["deferred"] and rc == 0:
                    rc = 75
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                rc = 1
                data["error"] = "missing enrichment completion counts"
    except OSError:
        rc = 127
    data.update(
        finished_at=datetime.now(timezone.utc).isoformat(),
        exit_code=rc,
        status="completed" if rc == 0 else ("deferred" if rc == 75 else "failed"),
        recovered=False,
        note="check pipeline output and child receipts to verify recovery",
    )
    if rc == 0 and args.kind == "enrichment" and data.get("completed") == 0:
        data["status"] = "deferred" if data.get("deferred") else "no_work"
    _receipt(args.kind, data)
    print(json.dumps(data))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
