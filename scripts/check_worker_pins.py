#!/usr/bin/env python3
"""Worker pin check: which runtimes execute the served release, and which do not.

A promotion moves CURRENT; long-running units re-exec on restart, and crons
resolve their tree per run. A worker whose cron/launcher hard-codes the dev
tree (measured 2026-09-25: linux_launchers/reconcile_alpaca_paper_options.sh,
425 of 466 crontab lines) serves whatever the dev tree holds — for three days
in September that was 8a95e30c1 WIP while CURRENT moved twice.

Read-only. Inputs may be injected (tests) or read from the host:
  * CURRENT -> served SHA (SOURCE_COMMIT/BUILD_SHA)
  * systemd user units: MainPID cwd resolved to a release dir or the dev tree
  * crontab lines: the tree each job cd's into / invokes
  * dev tree HEAD
Exit 0 when every RELEVANT worker executes the served SHA; exit 3 when one
does not (``--warn`` prints and exits 0: visible degradation for promote).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

NO_CONSUMER_REASON = (
    "operator/promote preflight report; stdout/JSON and the deploy receipt are the consumers until a CC ops surface imports it"
)
SCHEMA = "WorkerPinCheck@v1"
DEV_TREE = Path(os.environ.get("TRADEAI_DEV_TREE", "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"))
CURRENT = Path(os.environ.get("TRADEAI_CURRENT", str(Path.home() / "trade-ai-releases/portfolio-server/CURRENT")))
RELEASES = CURRENT.parent
RELEVANT_UNITS = ("portfolio-server.service", "tradeai-cio-telegram.service", "tradeai-health-agent.service",
                  "cio-governed-bridge.service", "tradeai-aec-command-center-cycle.service", "tradeai-cio-reactive.service")
# Cron jobs whose logic writes advice or outcomes: a dev-tree copy can corrupt them.
RELEVANT_CRON_PATTERNS = ("reconcile_alpaca_paper_options", "cio_wake_dispatch_entrypoint", "sweep_commitment_outcomes",
                          "write_instrument_beliefs", "cio_gate_measurement_bridge", "resolve_due_checkpoints",
                          "run_persistent_wake", "cio_reactive_cycle")
_SHA_DIR = re.compile(r"/portfolio-server/([0-9a-f]{7,40})-")


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def served_sha(current: Path = CURRENT) -> str | None:
    try:
        real = current.resolve()
    except OSError:
        return None
    for name in ("SOURCE_COMMIT", "BUILD_SHA"):
        v = _read(real / name)
        if v:
            return v
    m = _SHA_DIR.search(str(real))
    return m.group(1) if m else None


def tree_of(path_text: str, *, dev_tree: Path = DEV_TREE, current: Path = CURRENT) -> dict[str, Any]:
    """Classify a path/command as served release, dev tree, or other; resolve its SHA when possible."""
    t = str(path_text or "")
    m = _SHA_DIR.search(t)
    if m:
        return {"tree": "release", "sha": m.group(1)}
    if str(current) in t or "/portfolio-server/CURRENT" in t:
        return {"tree": "current", "sha": served_sha(current)}
    if str(dev_tree) in t or "$PROJ" in t or "trade-ai-v12-rebuild/trade-ai-v12-rebuild" in t:
        return {"tree": "dev", "sha": dev_tree_sha(dev_tree)}
    return {"tree": "other", "sha": None}


_DEV_SHA_CACHE: dict[str, str | None] = {}


def dev_tree_sha(dev_tree: Path = DEV_TREE) -> str | None:
    key = str(dev_tree)
    if key in _DEV_SHA_CACHE:
        return _DEV_SHA_CACHE[key]
    try:
        out = subprocess.run(["git", "-C", key, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
        sha = out.stdout.strip() or None
    except Exception:
        sha = None
    _DEV_SHA_CACHE[key] = sha
    return sha


def unit_rows(units: Iterable[str] = RELEVANT_UNITS) -> list[dict[str, Any]]:
    rows = []
    for u in units:
        try:
            pid = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID", "--value", u],
                                 capture_output=True, text=True, timeout=10, check=False).stdout.strip()
            active = subprocess.run(["systemctl", "--user", "is-active", u],
                                    capture_output=True, text=True, timeout=10, check=False).stdout.strip()
        except Exception:
            pid, active = "", "unknown"
        cwd = None
        if pid and pid != "0":
            try:
                cwd = os.readlink(f"/proc/{pid}/cwd")
            except OSError:
                cwd = None
        rows.append({"kind": "unit", "name": u, "active": active, "pid": pid or None, "path": cwd,
                     **tree_of(cwd or "")})
    return rows


def cron_rows(crontab_text: str, *, patterns: Iterable[str] = RELEVANT_CRON_PATTERNS) -> list[dict[str, Any]]:
    rows = []
    for line in crontab_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" in s.split(" ", 1)[0]:
            continue
        for pat in patterns:
            if pat in s:
                rows.append({"kind": "cron", "name": pat, "path": s[:220], **tree_of(s)})
                break
    return rows


def evaluate(*, served: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    mismatches = []
    for r in rows:
        if r.get("kind") == "unit" and r.get("active") not in ("active", None, "unknown"):
            r["verdict"] = "INACTIVE"
            continue
        sha = r.get("sha")
        if r.get("tree") == "other":
            r["verdict"] = "OTHER_TREE"
            continue
        if r.get("tree") == "dev":
            r["verdict"] = "DEV_TREE" + ("_SAME_SHA" if served and sha and sha[:9] == served[:9] else "_DIVERGED")
            if r["verdict"].endswith("DIVERGED"):
                mismatches.append(r)
        elif served and sha and (sha.startswith(served[:9]) or served.startswith(sha[:9])):
            r["verdict"] = "SERVED"
        else:
            r["verdict"] = "MISMATCH"
            mismatches.append(r)
    dev_hazard = [r for r in rows if r.get("tree") == "dev"]
    return {"schema": SCHEMA, "served_sha": served, "rows": rows, "mismatches": mismatches,
            "dev_tree_workers": [r["name"] for r in dev_hazard],
            "ok": not mismatches,
            "note": ("workers on the dev tree are SAME_SHA today but will diverge the moment main moves "
                     "or WIP lands; they should run from CURRENT") if dev_hazard and not mismatches else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--warn", action="store_true", help="exit 0 on mismatch, print it")
    ap.add_argument("--crontab-file", default=None, help="read crontab text from a file (tests)")
    args = ap.parse_args()
    served = served_sha()
    if args.crontab_file:
        cron_text = Path(args.crontab_file).read_text(encoding="utf-8")
    else:
        try:
            cron_text = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10, check=False).stdout
        except Exception:
            cron_text = ""
    rows = unit_rows() + cron_rows(cron_text)
    rep = evaluate(served=served, rows=rows)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(f"served_sha={served}")
        for r in rows:
            print(f"  {r['kind']:<4} {r['name']:<45} {str(r.get('verdict')):<20} sha={str(r.get('sha'))[:12]} {str(r.get('path'))[:90]}")
        if rep["note"]:
            print("  note: " + rep["note"])
    if rep["ok"]:
        return 0
    print(f"WORKER PIN MISMATCH: {[m['name'] for m in rep['mismatches']]}", file=sys.stderr)
    return 0 if args.warn else 3


if __name__ == "__main__":
    raise SystemExit(main())
