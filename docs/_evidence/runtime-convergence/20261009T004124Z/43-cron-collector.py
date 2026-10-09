#!/usr/bin/env python3
"""Reparse live cron read-only; redact values before writing evidence."""

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
sys.path.insert(0, str(ROOT))

from scripts.report_scheduler_inventory import cron_analysis  # noqa: E402


def redact(text):
    text = re.sub(
        r"(?i)((?:[A-Z_]*(?:TOKEN|PASSWORD|SECRET|BEARER|API_KEY|HMAC_KEY|CREDENTIAL)[A-Z_]*)\s*[=:]\s*)([^\s,;]+)",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(r'(?i)(Authorization\s*[:=]\s*|Bearer\s+)[^\s"\']+', r"\1[REDACTED]", text)
    return re.sub(r"(https?://)[^/@\s:]+:[^/@\s]+@", r"\1[REDACTED]@", text)


def main():
    raw = subprocess.check_output(["crontab", "-l"], text=True)
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("America/New_York"))
    result = cron_analysis(redact(raw), start=local + timedelta(days=1))
    result.update(
        as_of=now.isoformat(),
        command=["crontab", "-l"],
        raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        redacted_before_export=True,
        mutations_performed=False,
    )
    path = OUT / "43-current-cron-remeasurement.json"
    if path.exists():
        raise RuntimeError("refusing to overwrite the measured snapshot")
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ["as_of", "counts", "estimated_fires_7d"]}))


if __name__ == "__main__":
    main()
