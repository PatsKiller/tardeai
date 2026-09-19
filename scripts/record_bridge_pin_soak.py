#!/usr/bin/env python3
"""Record governed-bridge vs portfolio-server pin equality (soak ledger).

Remediation I2 / control-3 soak: require N≥3 consecutive matching observations
across real promotes before claiming Production Ready on pin consistency.

Usage:
  python3 scripts/record_bridge_pin_soak.py              # live measure + append
  python3 scripts/record_bridge_pin_soak.py --dry-run    # print only, no write
  python3 scripts/record_bridge_pin_soak.py --status     # summarize ledger

Writes: data/runtime/bridge_pin_soak.jsonl (or TRADEAI_BRIDGE_PIN_SOAK path)
AUTHORITY: READ_ONLY_ADVISORY — no restart, no promote.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "BridgePinSoakObservation@v1"
DEFAULT_SOAK_N = 3


def _run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return (r.stdout or "").strip()


def _unit_cwd(unit: str) -> tuple[str, str]:
    pid = _run(["systemctl", "--user", "show", "-p", "MainPID", "--value", unit])
    active = _run(["systemctl", "--user", "is-active", unit])
    cwd = ""
    if pid and pid != "0":
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            cwd = ""
    return active, cwd


def _current_resolved() -> str:
    link = Path.home() / "trade-ai-releases/portfolio-server/CURRENT"
    try:
        return str(link.resolve())
    except OSError:
        return ""


def measure() -> dict:
    s_active, s_cwd = _unit_cwd("portfolio-server.service")
    b_active, b_cwd = _unit_cwd("cio-governed-bridge.service")
    current = _current_resolved()
    match = bool(s_cwd and b_cwd and current and s_cwd == b_cwd == current)
    return {
        "schema": SCHEMA,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "portfolio_server_active": s_active,
        "bridge_active": b_active,
        "portfolio_server_cwd": s_cwd,
        "bridge_cwd": b_cwd,
        "current_resolved": current,
        "pins_match": match,
        "note": "observation only — promote count increments when cwd basename changes vs prior row",
    }


def ledger_path() -> Path:
    env = os.environ.get("TRADEAI_BRIDGE_PIN_SOAK")
    if env:
        return Path(env)
    # Prefer persistent runtime if present; else cwd-relative for worktrees
    persistent = Path.home() / "trade-ai-releases/persistent-state/data/runtime/bridge_pin_soak.jsonl"
    if persistent.parent.is_dir():
        return persistent
    return Path("data/runtime/bridge_pin_soak.jsonl")


def read_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def consecutive_matches(rows: list[dict]) -> int:
    n = 0
    for row in reversed(rows):
        if row.get("pins_match"):
            n += 1
        else:
            break
    return n


def status_report(rows: list[dict], need: int = DEFAULT_SOAK_N) -> str:
    streak = consecutive_matches(rows)
    last = rows[-1] if rows else None
    lines = [
        f"ledger_rows={len(rows)} consecutive_match_streak={streak} need={need}",
        f"soak_ready={'YES' if streak >= need else 'NO'}",
    ]
    if last:
        lines.append(
            f"last as_of={last.get('as_of')} match={last.get('pins_match')} "
            f"server={last.get('portfolio_server_cwd')} bridge={last.get('bridge_cwd')}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--need", type=int, default=DEFAULT_SOAK_N)
    args = ap.parse_args()
    path = ledger_path()

    if args.status:
        rows = read_rows(path)
        print(status_report(rows, args.need))
        print(f"ledger={path}")
        return 0

    obs = measure()
    print(json.dumps(obs, indent=2))
    print(f"pins_match={obs['pins_match']}")

    if args.dry_run:
        print("DRY_RUN no write")
        return 0 if obs["pins_match"] else 2

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obs, sort_keys=True) + "\n")
    rows = read_rows(path)
    print(status_report(rows, args.need))
    print(f"wrote {path}")
    return 0 if obs["pins_match"] else 2


if __name__ == "__main__":
    sys.exit(main())
