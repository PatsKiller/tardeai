#!/usr/bin/env python3
"""CLI: Data Broker indicator refresh (health-agent + cron entrypoint).

Default: --operator-desks (Watch MAIN + Re-Entry exit gaps) so weekend and
weekday remediation both feed indicator_confluence_cache and invalidate the
broker snapshot for every consumer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "scripts"))

env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description="Data Broker indicator refresh")
    ap.add_argument("--operator-desks", action="store_true",
                    help="Watch MAIN + Re-Entry exit gaps (default when no other mode set)")
    ap.add_argument("--main-missing-only", action="store_true")
    ap.add_argument("--all-universe", action="store_true", help="Full watchlist/screener/exit universe")
    ap.add_argument("--missing-exits-only", action="store_true")
    ap.add_argument("--symbols", default="", help="Comma-separated override list")
    ap.add_argument("--limit", type=int, default=160)
    ap.add_argument("--sleep-ms", type=int, default=400)
    ap.add_argument("--max-age-hours", type=int, default=36)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from lib.data_broker.indicator_refresh import refresh_indicators

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or None
    if symbols:
        mode = {"operator_desks": False, "main_missing_only": False, "missing_exits_only": False}
    elif args.missing_exits_only:
        mode = {"operator_desks": False, "main_missing_only": False, "missing_exits_only": True}
    elif args.main_missing_only:
        mode = {"operator_desks": False, "main_missing_only": True, "missing_exits_only": False}
    elif args.all_universe:
        # all-universe is producer flag without missing filters — pass via empty modes
        # and let producer load full list (no --operator-desks / missing flags)
        mode = {"operator_desks": False, "main_missing_only": False, "missing_exits_only": False}
    else:
        # Default health/weekend path: both desks
        mode = {"operator_desks": True, "main_missing_only": False, "missing_exits_only": False}
    if args.operator_desks:
        mode = {"operator_desks": True, "main_missing_only": False, "missing_exits_only": False}

    # --all-universe: call producer without missing-only flags (full sorted universe)
    if args.all_universe and not symbols:
        from lib.data_broker.indicator_refresh import PROJECT_ROOT, invalidate_indicator_snapshot
        import subprocess
        from datetime import datetime, timezone
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "indicator_cache_refresh.py"),
            "--profile", "swing",
            "--sleep-ms", str(args.sleep_ms),
            "--limit", str(args.limit),
        ]
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=900)
        out = {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "snapshot_invalidated": invalidate_indicator_snapshot(),
            "mode": "all_universe",
            "log_tail": ((proc.stdout or "") + (proc.stderr or ""))[-500:],
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        out = refresh_indicators(
            symbols=symbols,
            limit=args.limit,
            sleep_ms=args.sleep_ms,
            max_age_hours=args.max_age_hours,
            **mode,
        )
        out["mode"] = (
            "symbols" if symbols else
            "missing_exits" if mode["missing_exits_only"] else
            "main_missing" if mode["main_missing_only"] else
            "operator_desks"
        )

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        status = "OK" if out.get("ok") else "FAIL"
        print(f"[{status}] broker indicator refresh mode={out.get('mode')} "
              f"exit={out.get('exit_code')} invalidated={out.get('snapshot_invalidated')}")
        if out.get("error"):
            print("error:", out["error"])
        if out.get("log_tail"):
            print(out["log_tail"][-500:])
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
