"""P2 audit remediation: the cadence reports must not fail silently.

Observed 2026-09-26 (backfill runs after re-enabling the timers):
  * weekly: TypeError: unsupported format string passed to NoneType.__format__
    (portfolio_weekly_report.py prompt line; period JSON carries change_pct None)
    on every run since at least 2026-08-16; launcher printed "report skipped
    (non-fatal)"; pipeline recorded status=ok.
  * monthly: NameError: name 'total_val' is not defined (caption f-string in
    run_monthly_report); same masking.
"""
from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_p2_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_weekly_period_lines_survive_none_and_missing_periods():
    W = _load("portfolio_weekly_report")
    # exact shape from the failing run: 1M/YTD/1Y present with change_pct None
    line = W._period_summary_lines(1_234_567.8, {"change_pct": -0.42, "change": -5200.0},
                                   {"change_pct": None, "change": None}, {"change_pct": None}, {})
    assert "Portfolio: $1,234,568" in line and "1W: -0.42% ($-5,200)" in line
    assert "1M: +0.00%" in line and "YTD: +0.00% ($+0)" in line and "1Y: +0.00%" in line
    assert W._num(None) == 0.0 and W._num("3.5") == 3.5 and W._num(float("nan")) == 0.0
    assert W._num(None, 0.38) == 0.38


def test_weekly_prompt_uses_the_none_safe_lines():
    src = (ROOT / "scripts" / "portfolio_weekly_report.py").read_text(encoding="utf-8")
    assert "{p1m.get('change_pct',0):+.2f}" not in src
    assert "_period_summary_lines(total, p1w, p1m, pytd, p1y)" in src


def test_monthly_total_is_defined_and_none_safe():
    M = _load("portfolio_monthly_report")
    assert M._portfolio_total({"portfolio_totals": {"total_value": 1260915.7}}) == 1260915.7
    assert M._portfolio_total({"portfolio_totals": {"total_value": None}}) == 0.0
    assert M._portfolio_total({}) == 0.0 and M._portfolio_total(None) == 0.0
    src = (ROOT / "scripts" / "portfolio_monthly_report.py").read_text(encoding="utf-8")
    caption_at = src.index('caption = f"📈 Monthly Portfolio Report')
    assert "total_val = _portfolio_total(holdings)" in src[caption_at - 200:caption_at]


def _fake_project(tmp_path: Path, *, report_rc: int) -> Path:
    """A project skeleton whose orchestrator succeeds and whose report exits report_rc."""
    proj = tmp_path / "proj"
    for d in ("scripts", ".venv/bin", "logs", "data/portfolios/reports", "reports"):
        (proj / d).mkdir(parents=True)
    (proj / ".venv/bin/activate").write_text("# stub venv\n")
    fake_bin = tmp_path / "bin"; fake_bin.mkdir()
    for py in ("python", "python3"):
        sh = fake_bin / py
        sh.write_text('#!/usr/bin/env bash\ncase "$1" in\n  *portfolio_weekly_report.py|*portfolio_monthly_report.py) exit '
                      + str(report_rc) + ';;\n  *) exit 0;;\nesac\n')
        sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    (proj / "backfill_acct_periods_v3.py").write_text("")
    return proj


def _run(launcher: str, tmp_path: Path, report_rc: int) -> subprocess.CompletedProcess:
    proj = _fake_project(tmp_path, report_rc=report_rc)
    env = {**os.environ, "PROJECT_ROOT": str(proj), "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "ENABLE_YAML_ADVISOR": "0"}
    return subprocess.run(["bash", str(ROOT / "linux_launchers" / launcher)], env=env, capture_output=True, text=True, timeout=60)


def test_weekly_launcher_exits_nonzero_when_the_report_fails(tmp_path):
    bad = _run("run_portfolio_weekly.sh", tmp_path, report_rc=1)
    assert bad.returncode != 0, bad.stdout + bad.stderr
    assert "report FAILED rc=1" in bad.stdout and "REPORT_FAILED" in bad.stdout
    assert "skipped (non-fatal)" not in bad.stdout
    good = _run("run_portfolio_weekly.sh", tmp_path / "ok", report_rc=0)
    assert good.returncode == 0, good.stdout + good.stderr


def test_monthly_launcher_exits_nonzero_when_the_report_fails(tmp_path):
    bad = _run("run_portfolio_monthly.sh", tmp_path, report_rc=2)
    assert bad.returncode != 0
    assert "monthly report FAILED rc=2" in bad.stdout and "REPORT_FAILED" in bad.stdout
    good = _run("run_portfolio_monthly.sh", tmp_path / "ok", report_rc=0)
    assert good.returncode == 0, good.stdout + good.stderr


def test_pipeline_step_marks_a_failing_launcher_failed():
    """pm_step already turns a non-zero launcher into FAILED(rc=N) and overall=1;
    the launchers were the ones swallowing it. Assert the contract in the pipeline text."""
    src = (ROOT / "scripts" / "pipelines" / "run_portfolio_maintenance_pipeline.sh").read_text(encoding="utf-8")
    assert 'status="FAILED(rc=$rc)"' in src and "overall=1" in src
