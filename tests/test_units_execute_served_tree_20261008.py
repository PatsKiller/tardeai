"""2026-10-08: the five --alert monitor units (expected-services, data-source-health, served-copy-split,
data-plausibility, gap-resolution) had WorkingDirectory=<dev tree> and a relative scripts/ ExecStart, so the
timers executed dev-tree code — the "dev tree is what executes" trap. They now run the served CURRENT tree.
The remaining dev-tree units are recorded in config/dev_tree_units_baseline.txt; that list can only shrink."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "config" / "systemd" / "user"
BASELINE = ROOT / "config" / "dev_tree_units_baseline.txt"
DEV = "WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
FIXED = ["expected-services", "data-source-health", "served-copy-split", "data-plausibility", "gap-resolution"]


def _dev_tree_units() -> set[str]:
    out = set()
    for p in sorted(UNITS.glob("*.service")):
        t = p.read_text()
        if DEV in t and re.search(r"ExecStart=.*\n?.*scripts/", t):
            out.add(p.name)
    return out


def _baseline() -> set[str]:
    return {l.strip() for l in BASELINE.read_text().splitlines() if l.strip() and not l.startswith("#")}


def test_the_five_alert_monitors_run_the_served_tree():
    for u in FIXED:
        t = (UNITS / f"tradeai-{u}.service").read_text()
        assert "WorkingDirectory=%h/trade-ai-releases/portfolio-server/CURRENT" in t, u
        assert "%h/trade-ai-releases/portfolio-server/CURRENT/scripts/" in t, u
        assert DEV not in t, u
        assert ".venv/bin/python" in t, u   # interpreter stays the shared venv (CURRENT has none)


def test_no_unit_gains_a_dev_tree_working_directory():
    new = _dev_tree_units() - _baseline()
    assert not new, f"units executing dev-tree code outside the baseline: {sorted(new)}"


def test_the_baseline_has_no_stale_entries():
    stale = _baseline() - _dev_tree_units()
    assert not stale, f"remove from config/dev_tree_units_baseline.txt: {sorted(stale)}"
