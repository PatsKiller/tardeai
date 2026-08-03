#!/usr/bin/env python3
"""refresh_reentry_resistance.py — rebuild closed-session resistance cache for Re-Entry desk.

Writes ui_prefs key portfolio.reentry.resistance.v1 via lib.reentry_resistance.
Safe for cron / health-agent auto-remediation. Advisory only — no orders.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))


def main() -> int:
    from env_bootstrap import load_env
    load_env()
    from db_adapter import _execute
    from lib.reentry_resistance import refresh_resistance_cache

    out = refresh_resistance_cache(_execute)
    print(json.dumps({
        "ok": True,
        "generated_at": out.get("generated_at"),
        "symbol_count": out.get("symbol_count"),
        "version": out.get("version"),
    }, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
