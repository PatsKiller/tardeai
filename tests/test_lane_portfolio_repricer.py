"""portfolio-repricer lane: declared, not baseline-exempt.

Follow-up to #831 LITMUS_LANES F7. The money writer (holdings.json / data_as_of)
must appear as a lane row; the gate must go red if the row is dropped while the
cron is still discovered and no longer baselined.

Does not wire evaluate_lane into CI. Does not tighten F3/F5. Does not touch
wake persist or cash_letter.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "config" / "lane_registry.json"
GATE = ROOT / "scripts" / "check_lane_registry.py"


def _gate(registry: Path, *, discovery: Path | None = None) -> int:
    cmd = [sys.executable, str(GATE), "--fail-on-new", "--registry", str(registry)]
    if discovery is not None:
        cmd += ["--discovery-json", str(discovery)]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True).returncode


def test_portfolio_repricer_lane_is_declared_active():
    reg = json.loads(REG.read_text(encoding="utf-8"))
    row = next(r for r in reg["lanes"] if r.get("lane_id") == "portfolio-repricer")
    assert row["state"] == "ACTIVE"
    assert row["scheduler"]["kind"] == "cron"
    assert row["scheduler"]["match"] == "portfolio_repricer.py"
    assert "*/15" in row["scheduler"]["expression"]
    assert float(row["expected_cadence_hours"]) == 0.25
    sig = row["output_signal"]
    assert sig["kind"] == "file_mtime"
    assert sig["path"] == "data/portfolios/state/holdings.json"
    assert "$PROJ" not in sig["path"]
    note = row.get("note") or ""
    assert "F3" in note and "F5" in note
    assert "out of scope" in note.lower() or "stay loose" in note.lower()


def test_repricer_crons_not_in_undeclared_baseline():
    reg = json.loads(REG.read_text(encoding="utf-8"))
    base = reg.get("undeclared_baseline") or []
    leftover = [
        b for b in base
        if "portfolio_repricer.py" in b
        and (
            "portfolio_repricer_intraday.log" in b
            or "portfolio_repricer_postclose.log" in b
        )
    ]
    assert leftover == [], leftover


def test_drop_row_while_cron_discovered_goes_red(tmp_path: Path):
    """Acceptance mutant: drop the new row + keep baseline exempt-free → gate red.

    Baseline already no longer exempts the three repricer crons. Removing the
    lane row must surface them as undeclared NEW.
    """
    reg = json.loads(REG.read_text(encoding="utf-8"))
    reg["lanes"] = [r for r in reg["lanes"] if r.get("lane_id") != "portfolio-repricer"]
    assert not any(r.get("lane_id") == "portfolio-repricer" for r in reg["lanes"])

    cron_line = (
        "*/15 9-16 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild "
        "&& bash …/safe_flock.sh /tmp/portfolio_repricer.lock "
        "…/python scripts/portfolio_repricer.py >> …/portfolio_repricer_intraday.log 2>&1"
    )
    disco = tmp_path / "discovery.json"
    disco.write_text(json.dumps({
        "cron": [{"expression": cron_line}],
        "cron_commented": [],
        "systemd": [],
    }), encoding="utf-8")

    mutated = tmp_path / "registry.json"
    mutated.write_text(json.dumps(reg), encoding="utf-8")
    assert _gate(mutated, discovery=disco) == 1, (
        "dropping portfolio-repricer while its cron is discovered must go red"
    )

    # Restoring the row goes green again.
    full = json.loads(REG.read_text(encoding="utf-8"))
    mutated.write_text(json.dumps(full), encoding="utf-8")
    assert _gate(mutated, discovery=disco) == 0


def test_gate_reports_zero_undeclared_new_on_live_host():
    """check_lane_registry.py 0 undeclared NEW (structure + live discovery)."""
    proc = subprocess.run(
        [sys.executable, str(GATE), "--json"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    payload = json.loads(proc.stdout)
    undeclared = payload.get("undeclared") or []
    # None of the findings may be the portfolio_repricer cron.
    repricer_new = [u for u in undeclared if "portfolio_repricer.py" in str(u.get("expression", ""))]
    assert repricer_new == [], repricer_new
