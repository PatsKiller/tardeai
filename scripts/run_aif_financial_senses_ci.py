#!/usr/bin/env python3
"""Pinned AIF ↔ Financial Senses integration CI runner.

READ_ONLY_ADVISORY. No broker, no Telegram, no production mutation.
Reads the committed manifest and runs pytest on those files.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "aif_financial_senses_ci_manifest.txt"


def load_manifest() -> list[str]:
    lines: list[str] = []
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def main() -> int:
    files = load_manifest()
    missing = [f for f in files if not (ROOT / f).exists()]
    if missing:
        print("MISSING manifest entries:", *missing, sep="\n  ")
        return 2
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short", *files]
    print(" ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
