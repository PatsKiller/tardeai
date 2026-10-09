#!/usr/bin/env python3
"""Read-only source/CURRENT identity refresh; no process controls."""

import json, subprocess
from datetime import datetime, timezone
from pathlib import Path

p = Path(__file__).resolve().parent
current = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT").resolve()


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


pid = subprocess.check_output(
    ["systemctl", "--user", "show", "portfolio-server.service", "--property=MainPID", "--value"], text=True
).strip()


def get(path):
    return json.loads(subprocess.check_output(["curl", "-fsS", "http://127.0.0.1:7777" + path], text=True))


result = {
    "as_of": datetime.now(timezone.utc).isoformat(),
    "evidence_class": "OBSERVED_CURRENT",
    "origin_main": git("rev-parse", "origin/main"),
    "source_head_before_evidence_commit": git("rev-parse", "HEAD"),
    "merge_base": git("merge-base", "HEAD", "origin/main"),
    "CURRENT_release": str(current),
    "CURRENT_SHA": subprocess.check_output(["git", "-C", str(current), "rev-parse", "HEAD"], text=True).strip(),
    "portfolio_server_pid": pid,
    "portfolio_server_cwd": str((Path("/proc") / pid / "cwd").resolve()) if pid != "0" else None,
    "api_health": get("/api/health"),
    "served_build": get("/v3/build-meta.json"),
    "worktree_before_evidence_commit": git("status", "--porcelain=v1"),
    "note": "Final PR head is supplied in PR/final response; this identity refresh precedes the evidence commit. Initial Phase 0 baseline remains separate.",
}
(p / "22-current-reverification.json").write_text(json.dumps(result, indent=2) + "\n")
print({k: v for k, v in result.items() if k not in ["worktree_before_evidence_commit", "api_health", "served_build"]})
