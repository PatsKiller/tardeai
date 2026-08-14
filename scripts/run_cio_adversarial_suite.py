#!/usr/bin/env python3
"""Phase 11 adversarial suite runner (local + CI).

Deliberately attacks units, cash arithmetic, decision hygiene, Telegram
isolation, data-quality abstention, release pins, and AST no-order invariants.

READ_ONLY_ADVISORY. Never contacts brokers or sends Telegram.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    os.chdir(REPO)
    os.environ.setdefault("TRADE_AI_CI", "1")
    os.environ.setdefault("CIO_TELEGRAM_INTERDICT", "1")
    os.environ.setdefault("ENABLE_TELEGRAM", "0")
    path = "tests/test_cio_phase11_adversarial.py"
    print(f"[RUN] adversarial: {path}")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short", path],
        cwd=str(REPO),
    )
    if r.returncode != 0:
        print("[FAIL] Phase 11 adversarial suite")
        return 1
    print("[PASS] Phase 11 adversarial suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
