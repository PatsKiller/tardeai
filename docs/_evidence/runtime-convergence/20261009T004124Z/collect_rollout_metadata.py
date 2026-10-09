#!/usr/bin/env python3
"""Read-only final identity, exact process roots and current cron counters."""

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
sys.path.insert(0, str(ROOT))
from scripts.lib.scheduler_operations import parse_crontab, redact_command  # noqa: E402

PIN = Path.home() / "trade-ai-releases/portfolio-server/CURRENT"


def call(argv):
    run = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    return run.returncode, run.stdout


def main():
    result = {
        "schema": "RolloutMetadataObservation@v1",
        "evidence_class": "OBSERVED_CURRENT",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "CURRENT": str(PIN.resolve()),
        "CURRENT_SHA": (PIN.resolve() / "GIT_SHA").read_text().strip(),
        "units": {},
    }
    for name in [
        "portfolio-server.service",
        "tradeai-n8n-coordination-gateway.service",
        "tradeai-n8n-run-relay.service",
        "tradeai-n8n-run-executor.service",
    ]:
        rc, text = call(
            [
                "systemctl",
                "--user",
                "show",
                name,
                "--property=Id,MainPID,LoadState,ActiveState,FragmentPath,Restart,ActiveEnterTimestamp",
            ]
        )
        row = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
        row["exit"] = rc
        pid = row.get("MainPID", "0")
        if pid.isdigit() and pid != "0":
            cwd = Path("/proc") / pid / "cwd"
            row["process_cwd"] = str(cwd.resolve())
            stamp = cwd / "GIT_SHA"
            row["process_sha"] = stamp.read_text().strip() if stamp.is_file() else None
        result["units"][name] = row
    rc, raw = call(["crontab", "-l"])
    lines = raw.splitlines()
    env = [line for line in lines if re.match(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=", line)]
    entries = parse_crontab(raw)
    result["cron"] = {
        "exit": rc,
        "evidence_class": "OBSERVED_HOST" if rc == 0 else "BLOCKED",
        "raw_lines": len(lines),
        "job_lines": len(entries),
        "comment_lines": sum(line.lstrip().startswith("#") for line in lines),
        "blank_lines": sum(not line.strip() for line in lines),
        "env_lines": len(env),
        "env_names": [line.split("=", 1)[0].strip() for line in env],
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "n1_lines": [
            redact_command(line)
            for line in lines
            if any(
                word in line
                for word in [
                    "n8n_pilot_dispatch.py",
                    "n8n_incident_fanin.py",
                    "n8n_research_intake_consumer.py",
                    "crontab_snapshot.txt",
                ]
            )
        ],
        "entries": entries,
    }
    for name, url in [
        ("api_health", "http://127.0.0.1:7777/api/health"),
        ("cc_build", "http://127.0.0.1:7777/v3/build-meta.json"),
        ("relay_health", "http://127.0.0.1:18092/healthz"),
        ("gateway_health", "http://127.0.0.1:18091/healthz"),
    ]:
        try:
            with urlopen(url, timeout=5) as response:
                result[name] = {"status": response.status, "data": json.loads(response.read(128000))}
        except Exception as exc:
            result[name] = {"evidence_class": "BLOCKED", "error_class": type(exc).__name__}
    target = OUT / sys.argv[1]
    if target.exists():
        raise FileExistsError("Observation artifacts are immutable; choose a new filename")
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "as_of": result["as_of"],
                "CURRENT_SHA": result["CURRENT_SHA"],
                "jobs": len(entries),
                "raw_lines": len(lines),
                "process_sha": {name: row.get("process_sha") for name, row in result["units"].items()},
            }
        )
    )


if __name__ == "__main__":
    main()
