"""Three operator-approved scheduled jobs (2026-10-03) are declared lanes.

The crontab lines are installed separately under the operator's cron grant; this
pins that the registry declares exactly what will be installed, so the lane gate
stays green after install and the old hygiene line is no longer baseline debt.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.lane_registry import (  # noqa: E402
    discover_cron, find_undeclared, load_registry, validate_registry,
)

CUR = "/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT"
INSTALLED = [
    f"52 6 * * * cd {CUR} && TRADEAI_ROOT={CUR} flock -n /tmp/cio_draft_hygiene.lock $PY "
    "scripts/cio_draft_plan_hygiene.py --apply --expire-stale >> /home/johnclaw/logs/cio_draft_hygiene.log 2>&1",
    f"47 17 * * 1-5 cd {CUR} && flock -n /tmp/cio_portfolio_thesis.lock bash -c \"set -a; . ./.env; set +a; "
    "$PY scripts/materialize_cio_portfolio_thesis.py\" >> logs/cio_portfolio_thesis.log 2>&1",
    f"17 6 * * * cd {CUR} && flock -n /tmp/advisory_maturity_evidence.lock $PY "
    "-m scripts.refresh_advisory_maturity_evidence >> logs/refresh_advisory_maturity_evidence.log 2>&1",
]
OLD_HYGIENE = INSTALLED[0].replace(" --expire-stale", "")


def _lane(reg: dict, lane_id: str) -> dict:
    return next(row for row in reg["lanes"] if row["lane_id"] == lane_id)


def test_registry_is_valid_and_declares_the_three_lanes():
    reg = load_registry()
    assert validate_registry(reg) == []
    assert "--expire-stale" in _lane(reg, "cio-draft-plan-hygiene")["scheduler"]["match"]
    assert _lane(reg, "cio-portfolio-thesis")["active_days"] == [0, 1, 2, 3, 4]
    # A plain `python scripts/refresh_advisory_maturity_evidence.py` fails with
    # "No module named 'scripts'": the lane must run it as a module.
    assert " -m scripts.refresh_advisory_maturity_evidence" in _lane(reg, "advisory-maturity-evidence")["scheduler"]["expression"]


def test_installed_lines_are_all_declared():
    found = {"cron": discover_cron("PY=/x/python\n" + "\n".join(INSTALLED) + "\n"), "systemd": []}
    assert find_undeclared(load_registry(), found) == []


def test_old_hygiene_line_is_no_longer_baseline_debt():
    reg = load_registry()
    baseline = set(reg.get("undeclared_baseline") or [])
    for tranche in reg.get("inherited_tranches") or []:
        baseline.update(tranche.get("lines") or [])
    assert not any("scripts/cio_draft_plan_hygiene.py" in line for line in baseline)
    found = {"cron": discover_cron(OLD_HYGIENE + "\n"), "systemd": []}
    assert len(find_undeclared(reg, found)) == 1
