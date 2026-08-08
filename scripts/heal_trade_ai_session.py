#!/usr/bin/env python3
"""Project-side entry for Ops Agent heal_trade_ai_session (skill implementation)."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

SKILL = (
    Path.home()
    / ".openclaw"
    / "skills"
    / "tradeai-health-inspect"
    / "scripts"
    / "heal_trade_ai_session.py"
)

if not SKILL.is_file():
    print(f"heal_trade_ai_session skill missing: {SKILL}", file=sys.stderr)
    sys.exit(2)

sys.argv[0] = str(SKILL)
runpy.run_path(str(SKILL), run_name="__main__")
