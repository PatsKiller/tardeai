#!/usr/bin/env python3
"""Closed-loop P0 reconcile — drain / observe / rebuild.

Default is dry-run. Pass --apply to append EXPIRED/CANCELLED / EXPIRED outcomes.
Never deletes Hermes history. Never invents POSITIVE/NEGATIVE P&L.
Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.intelligence_lineage import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
