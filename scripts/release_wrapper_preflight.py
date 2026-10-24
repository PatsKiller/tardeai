#!/usr/bin/env python3
"""Source-prepared release gate. Installation/admission remains operator-only.

Fixture mode uses --captured-cron. Native enforcement collects crontab read-only
once; denied/unavailable collection fails closed without any alternative read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.lib.release_wrapper_preflight import inspect  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--captured-cron", type=Path, help="offline/captured proof; no host collection")
    parser.add_argument("--config", type=Path, default=ROOT / "config/release_wrapper_preflight.json")
    parser.add_argument("--enforce", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--notify-failure", choices=["wrapper_preflight_failed"])
    args = parser.parse_args()
    if args.notify_failure:
        sys.path.insert(0, str(ROOT / "scripts"))
        from telegram_alert import send_telegram_outcome
        result = send_telegram_outcome("RELEASE WRAPPER PREFLIGHT FAILED · rollback requested; inspect exact deploy receipt and wrapper coverage. No producer was run by the preflight.",
                                       priority="P1", dedupe_minutes=0, producer="release_wrapper_preflight", message_class="operator_alert")
        print(json.dumps({k: result.get(k) for k in ["status", "accepted", "delivered"]}))
        return 0 if result.get("delivered") is True else 1
    cfg = json.loads(args.config.read_text())
    if args.enforce and (cfg.get("enabled") is not True or cfg.get("review_status") != "REVIEWED"
                         or not isinstance(cfg.get("approved_by"), str) or not cfg["approved_by"].strip()):
        print(json.dumps({"ok": False, "reason": "PENDING_OPERATOR_ADMISSION", "coverage_gaps": cfg.get("pending_protocol_paths")}))
        return 78
    if args.captured_cron:
        text = args.captured_cron.read_text()
        source = "captured_input; host_schedule_freshness_not_measured"
    else:
        try:
            proc = subprocess.run(["crontab", "-l"], text=True, capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            print(json.dumps({"ok": False, "reason": "cron_read_refused_or_unavailable"}))
            return 1
        if proc.returncode:
            print(json.dumps({"ok": False, "reason": "cron_read_refused_or_unavailable"}))
            return 1
        text, source = proc.stdout, "native_read_only_cron_census"
    with tempfile.TemporaryDirectory(prefix="wrapper-preflight-") as directory:
        report = inspect(args.current, Path(directory), text)
    report["schedule_source"] = source
    report["admission"] = "ENFORCED" if args.enforce else "INSPECTION_ONLY"
    report["config_sha256"] = hashlib.sha256(args.config.read_bytes()).hexdigest()
    report["release_sha"] = (args.current / "BUILD_SHA").read_text().strip() if (args.current / "BUILD_SHA").is_file() else None
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
