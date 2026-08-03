#!/usr/bin/env python3
"""flash_cadence_runner.py — fleet Flash schedules (policy 2026-08-03).

Subcommands map to operator cadence:
  watchlist-daily     MAIN free critics Flash (skip if fresh / data unchanged)
  portfolio-risk      portfolio risk-ish Flash (portfolio_ai + protection)
  llm-intelligence    home LLM intelligence Flash briefings

Never schedules DeepSeek Pro unless --use-pro (operator override).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

PY = sys.executable
LOG_DIR = PROJECT_ROOT / "logs"
RUNTIME = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/runtime")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp(name: str, payload: dict) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    path = RUNTIME / name
    data = {"ok": True, "finished_at": _now(), **payload}
    path.write_text(json.dumps(data, indent=2, default=str))
    print(f"  stamp → {path}")


def _run(cmd: list[str], log_name: str) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / log_name
    print(f"  exec: {' '.join(cmd)}")
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(f"\n--- {_now()} ---\n")
        fh.flush()
        p = subprocess.run(cmd, cwd=str(PROJECT_ROOT), stdout=fh, stderr=subprocess.STDOUT)
    print(f"  exit={p.returncode} log={log_path}")
    return int(p.returncode)


def cmd_watchlist_daily(force: bool = False) -> int:
    """Trading-day MAIN Flash critics (no Pro)."""
    args = [PY, str(PROJECT_ROOT / "scripts" / "main_desk_free_llm_weekly.py"), "--run",
            "--lanes", "deepseek-flash,local,grok,chatgpt", "--cap", "60"]
    if force:
        args.append("--force")
    rc = _run(args, "flash_watchlist_daily.log")
    _stamp("flash_watchlist_daily.json", {"job": "watchlist-daily", "rc": rc, "force": force})
    return rc


def cmd_portfolio_risk(force: bool = False) -> int:
    """Portfolio risk-ish Flash pass."""
    rc = 0
    # Holdings LLM refresh (risk-ish advisory)
    rc |= _run(
        [PY, str(PROJECT_ROOT / "scripts" / "holdings_llm_refresh.py"), "--run", "--limit", "40"],
        "flash_portfolio_risk.log",
    )
    # Protection advisor already defaults deepseek-flash
    rc |= _run(
        [PY, str(PROJECT_ROOT / "scripts" / "holding_protection_advisor.py"),
         "--lane", "deepseek-flash", "--limit", "20"],
        "flash_portfolio_risk.log",
    )
    # Portfolio AI analyst (now Flash by policy)
    if (PROJECT_ROOT / "scripts" / "portfolio_ai_analyst.py").exists():
        rc |= _run(
            [PY, str(PROJECT_ROOT / "scripts" / "portfolio_ai_analyst.py")],
            "flash_portfolio_risk.log",
        )
    _stamp("flash_portfolio_risk.json", {"job": "portfolio-risk", "rc": rc})
    return rc


def cmd_llm_intelligence() -> int:
    """Home / dashboard LLM intelligence via Flash."""
    rc = _run(
        [PY, str(PROJECT_ROOT / "scripts" / "llm_intelligence_enrichment.py")],
        "flash_llm_intelligence.log",
    )
    _stamp("flash_llm_intelligence.json", {"job": "llm-intelligence", "rc": rc})
    return rc


def cmd_policy() -> int:
    from llm_route_policy import policy_summary
    print(json.dumps(policy_summary(), indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Flash cadence runner")
    ap.add_argument(
        "job",
        choices=["watchlist-daily", "portfolio-risk", "llm-intelligence", "policy"],
    )
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.job == "watchlist-daily":
        return cmd_watchlist_daily(force=args.force)
    if args.job == "portfolio-risk":
        return cmd_portfolio_risk(force=args.force)
    if args.job == "llm-intelligence":
        return cmd_llm_intelligence()
    if args.job == "policy":
        return cmd_policy()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
