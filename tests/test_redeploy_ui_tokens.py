#!/usr/bin/env python3
"""Part F readability floor — fails if the workstation's typography regresses
below the operator-approved minimums (body 14 / table 13 / label 12 /
heading 18 / title 26). The 2026-07-13 review rejected 9-10px terminal type."""
from __future__ import annotations

import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "apps" / "command-center-v3" / "src" / "pages" / "RedeployDesk.tsx"
FLOORS = {"title": 26, "heading": 18, "subheading": 16, "body": 14, "table": 13, "label": 12}


def test_font_floor():
    src = PAGE.read_text()
    block = re.search(r"const T = \(d: Density\) => \(\{(.*?)\}\)", src, re.S)
    assert block, "typography token block missing from RedeployDesk"
    for name, floor in FLOORS.items():
        m = re.search(rf"\b{name}:\s*(\d+)", block.group(1))
        assert m, f"token {name} missing"
        assert int(m.group(1)) >= floor, f"{name} {m.group(1)}px is below the {floor}px floor"


def test_no_execution_language():
    src = PAGE.read_text()
    assert "operator may approve plan execution" not in src
    assert "ADVISORY ONLY" in src


def test_entries_require_plan_context():
    src = PAGE.read_text()
    assert "entries are always shown in the context of their plan" in src


if __name__ == "__main__":
    for t in (test_font_floor, test_no_execution_language, test_entries_require_plan_context):
        t()
        print(f"OK {t.__name__}")
    print("ALL 3 PASSED")
