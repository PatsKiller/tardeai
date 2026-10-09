#!/usr/bin/env python3
"""Read-only, sanitized independent N1 receipt and source registry inspection."""

import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
STATE = Path.home() / "trade-ai-releases/persistent-state"
PIN = Path.home() / "trade-ai-releases/portfolio-server/CURRENT"
PEER = Path.home() / "tradeai-wt-n1cut-20261008"
LANES = {
    "n8n-pilot-dispatch": "*/15 * * * *",
    "n8n-incident-fanin": "*/5 * * * *",
    "n8n-research-intake-consumer": "*/15 * * * *",
    "crontab-snapshot-for-health-agent": "*/20 * * * *",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_cadence(value):
    text = str(value or "")
    fields = text.split()
    controls = any(ord(c) < 32 for c in text)
    shape = len(fields) == 5 and all(re.fullmatch(r"[0-9*/,-]+", f) for f in fields) and not controls
    return {
        "value": text if shape else None,
        "shape_valid": bool(shape),
        "length": len(text),
        "fields": len(fields),
        "control_characters": controls,
        "sha256": digest(text.encode()),
    }


def file_meta(path):
    if not path.is_file():
        return {"path": str(path), "exists": False}
    raw = path.read_bytes()
    return {
        "path": str(path),
        "exists": True,
        "size": len(raw),
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "sha256": digest(raw),
    }


def call(argv):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    return {"exit": p.returncode, "stdout": p.stdout if not p.returncode else ""}


def main():
    natural = json.loads((OUT / "38-runtime-natural-runs.json").read_text())
    result = {
        "schema": "IndependentN1RuntimeProof@v1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "evidence_class": "OBSERVED_CURRENT",
        "CURRENT_SHA": (PIN.resolve() / "GIT_SHA").read_text().strip(),
        "CURRENT_release": str(PIN.resolve()),
        "natural_artifact": "38-runtime-natural-runs.json",
        "natural_artifact_as_of": natural["as_of"],
        "registry_sources": {},
        "cutover_receipts": [],
        "lanes": {},
        "mutations_performed": False,
    }
    allow = json.loads((PIN / "config/n8n_run_allowlist.json").read_text())
    entries = {row["lane_id"]: row for row in allow["lanes"]}
    for name, root in [("CURRENT", PIN.resolve()), ("peer_SOURCE_ONLY", PEER)]:
        reg = root / "config/lane_registry.json"
        data = json.loads(reg.read_text())
        rows = []
        for row in data["lanes"]:
            if row["lane_id"] not in LANES:
                continue
            sched = row["scheduler"]
            rows.append(
                {
                    "lane_id": row["lane_id"],
                    "owner": row.get("owner"),
                    "state": row.get("state"),
                    "scheduler_kind": sched.get("kind"),
                    "expression": sched.get("expression"),
                    "match": sched.get("match"),
                    "cadence": safe_cadence(sched.get("cadence")),
                    "expected_cadence": LANES[row["lane_id"]],
                    "output_signal": row.get("output_signal"),
                    "consumer": row.get("consumer"),
                }
            )
        result["registry_sources"][name] = {"path": str(reg), "sha256": digest(reg.read_bytes()), "rows": rows}
    cron = call(["crontab", "-l"])
    raw = cron["stdout"]
    result["cron"] = {"exit": cron["exit"], "sha256": digest(raw.encode()), "raw_lines": len(raw.splitlines())}
    cuts = STATE / "data/runtime/n8n_cutover"
    latest = {}
    for path in sorted(cuts.glob("*.json")):
        if path.name == "n8n_cutover_last.json":
            continue
        doc = json.loads(path.read_text())
        if doc.get("lane_id") not in LANES:
            continue
        line = doc.get("line_before") or ""
        entry = entries[doc["lane_id"]]
        row = {
            "file": str(path.relative_to(STATE)),
            "sha256": digest(path.read_bytes()),
            **{
                k: doc.get(k)
                for k in [
                    "schema",
                    "lane_id",
                    "action",
                    "at",
                    "applied",
                    "mode",
                    "code_sha",
                    "registry_path",
                    "workflow_id",
                    "problems",
                ]
            },
            "scheduler_before": doc.get("scheduler_before"),
            "scheduler_after_kind": (doc.get("scheduler_after") or {}).get("kind"),
            "cadence": safe_cadence(doc.get("cadence")),
            "owner_declared": bool(doc.get("owner")),
            "review_date_declared": bool(doc.get("review_by")),
            "line_schedule": " ".join(line.split()[:5]),
            "original_lock": entry["lock"],
            "original_lock_kind": entry["lock_kind"],
            "cron_lock_matches_allowlist": entry["lock"] in line,
            "cron_safe_flock_matches": "scripts/safe_flock.sh" in line and entry["lock_kind"] == "safe_flock",
            "retired_line_present": bool(doc.get("line_after") and doc["line_after"] in raw.splitlines()),
            "live_original_present": bool(line and line in raw.splitlines()),
            "backup": file_meta(Path(doc["crontab_backup"])) if doc.get("crontab_backup") else None,
        }
        result["cutover_receipts"].append(row)
        if doc.get("action") == "cutover" and doc.get("applied"):
            latest[doc["lane_id"]] = max(latest.get(doc["lane_id"], ""), doc["at"])
    for lane in LANES:
        runs = [r for r in natural["host_runs"] if r["lane_id"] == lane]
        cut_at = latest.get(lane)
        grouping = {}
        for mode in ["dry_run", "live"]:
            rows = [r for r in runs if r["mode"] == mode]
            good = [r for r in rows if r["natural_execution_green"] and r["host_completed_current"]]
            post = [r for r in good if cut_at and r["requested_at"] > cut_at]
            pre = [r for r in good if cut_at and r["requested_at"] < cut_at]
            grouping[mode] = {
                "states": dict(Counter(r["state"] for r in rows)),
                "natural_current_done_count": len(good),
                "pre_cutover_natural_current_done_count": len(pre),
                "post_cutover_natural_current_done_count": len(post),
                "all_receipts": [
                    {
                        "run_id": r["run_id"],
                        "requested_at": r["requested_at"],
                        "state": r["state"],
                        "current_sha": r["receipt"].get("code_sha"),
                        "natural_green": r["natural_execution_green"],
                        "host_completed_current": r["host_completed_current"],
                        "output_before": r["receipt"].get("output_signal_mtime_before"),
                        "output_after": r["receipt"].get("output_signal_mtime_after"),
                    }
                    for r in rows
                ],
            }
        signal = STATE / entries[lane]["output_signal"]
        metadata = file_meta(signal)
        if signal.suffix == ".json" and signal.is_file():
            obj = json.loads(signal.read_text())
            metadata["contract"] = {
                k: obj.get(k)
                for k in [
                    "schema",
                    "authority",
                    "as_of",
                    "mode",
                    "served_sha",
                    "state_root",
                    "ok",
                    "listed",
                    "cap",
                    "enqueued_today",
                    "count",
                    "incident_count",
                ]
                if k in obj
            }
            metadata["top_level_keys"] = sorted(obj)
            metadata["row_counts"] = {
                k: len(obj[k])
                for k in ["lanes", "incidents", "requests", "rows", "board_events"]
                if isinstance(obj.get(k), list)
            }
        result["lanes"][lane] = {"cadence": LANES[lane], "cutover_at": cut_at, "runs": grouping, "output": metadata}
    watchdog = call(
        [
            "systemctl",
            "--user",
            "show",
            "tradeai-n8n-lab-watchdog.timer",
            "--property=Id,LoadState,ActiveState,UnitFileState,LastTriggerUSec,NextElapseUSecRealtime,TimersMonotonic",
        ]
    )
    result["independent_watchdog_timer"] = {
        "exit": watchdog["exit"],
        "properties": dict(line.split("=", 1) for line in watchdog["stdout"].splitlines() if "=" in line),
    }
    result["host_ollama"] = call(
        ["systemctl", "show", "ollama.service", "--property=Id,LoadState,ActiveState,UnitFileState"]
    )
    target = OUT / "38-runtime-independent-inspection.json"
    if target.exists():
        raise FileExistsError(target)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "artifact": str(target),
                "as_of": result["as_of"],
                "CURRENT": result["CURRENT_SHA"],
                "cuts": len(result["cutover_receipts"]),
                "lanes": {
                    lane: {mode: r["natural_current_done_count"] for mode, r in doc["runs"].items()}
                    for lane, doc in result["lanes"].items()
                },
            }
        )
    )


if __name__ == "__main__":
    main()
