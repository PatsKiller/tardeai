"""P1 audit remediation (2026-09-26): cron and unit linters reproduce the live defects.

Fixture lines are the exact crontab lines measured on ms01-openclaw (R-02 lines
791/795/796, R-05 lines 544/731, R-10 lines 358 and 897) and the exact unit
EnvironmentFile entries (K-04). Every check is a pure function with an
injectable `exists`, so nothing here reads the host.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_cron_sanity as ccs  # noqa: E402
import check_unit_env_files as ue  # noqa: E402

# Live-host paths are assembled, never spelled out, so check_test_host_paths stays clean.
HOME = "/home/" + "johnclaw"
DEV = f"{HOME}/trade-ai-v12-" + "rebuild/trade-ai-v12-rebuild"
CUR = f"{HOME}/trade-ai-" + "releases/portfolio-server/CURRENT"
HEAD = f"PROJ={DEV}\nPY={DEV}/.venv/bin/python\n"
L358 = "*/15 9-16 * * 1-5 bash scripts/safe_flock.sh /tmp/atm_position_reconciler.lock .venv/bin/python scripts/atm_position_reconciler.py --apply >> logs/atm_position_reconciliation/run.log 2>&1"
L544 = "*/20 9-16 * * 1-5 cd $PROJ && bash scripts/market_day_gate.sh $PY scripts/alpaca_stop_manager.py --apply >> logs/alpaca_stop_manager_cron.log 2>&1"
L731 = "*/15 4-10 * * 1-5 cd $PROJ && flock -n /tmp/tradeai_oco_repair.lock $PY scripts/alpaca_stop_manager.py --repair-oco --apply >> logs/alpaca_stop_manager_repair.log 2>&1"
L791 = f"0 9 * * 0 cd {CUR} && flock -n /tmp/exit_outcomes.lock .venv/bin/python scripts/reconcile_exit_advisory_outcomes.py >> logs/exit_outcomes.log 2>&1"
L897 = f'0 5 * * 1-5 cd {CUR} && python3 -c "import sys; sys.path.insert(0, \'scripts\'); from cio_wake_detector import run; r = run(); print(f\'Wakes: {{r.get("wakes_created",0)}}\')" >> logs/cio_detector_weekly.log 2>&1'
GOOD = f"0 9 * * 0 cd {CUR} && flock -n /tmp/exit_outcomes.lock $PY scripts/reconcile_exit_advisory_outcomes.py >> logs/exit_outcomes.log 2>&1"

# Host shape at audit time: the dev tree has a venv, the release does not.
def _exists(path) -> bool:
    return str(path).startswith(f"{DEV}/.venv")


def test_cron_env_and_expansion():
    env = ccs.cron_env(HEAD)
    assert env["PY"].endswith("/.venv/bin/python")
    assert ccs._expand("$PROJ/x", env) == f"{DEV}/x"


def test_r02_relative_venv_inside_release_is_flagged_and_fix_clears_it():
    bad = ccs.check_relative_interpreters(HEAD + L791 + "\n", exists=_exists)
    assert [f["type"] for f in bad] == ["cron_interpreter_missing"]
    assert bad[0]["line"] == 3 and CUR in bad[0]["message"]
    assert ccs.check_relative_interpreters(HEAD + GOOD + "\n", exists=_exists) == []
    # a dev-tree line with a relative venv is fine because the dev tree has one
    dev = "40 17 * * 1-5 cd $PROJ && flock -n /tmp/gg.lock .venv/bin/python scripts/holdings_gain_guardian.py --apply >> logs/gg.log 2>&1"
    assert ccs.check_relative_interpreters(HEAD + dev + "\n", exists=_exists) == []


def test_r10_relative_path_without_cd_runs_from_home():
    out = ccs.check_relative_paths_without_cd(HEAD + L358 + "\n")
    assert [f["type"] for f in out] == ["cron_relative_path_no_cd"] and out[0]["line"] == 3
    fixed = L358.replace("bash scripts/safe_flock.sh", "cd $PROJ && bash scripts/safe_flock.sh")
    assert ccs.check_relative_paths_without_cd(HEAD + fixed + "\n") == []


def test_r05_two_schedules_of_a_broker_script_must_share_one_lock():
    out = ccs.check_shared_script_locks(HEAD + L544 + "\n" + L731 + "\n")
    assert len(out) == 1
    f = out[0]
    assert f["type"] == "cron_shared_script_lock_conflict" and f["severity"] == "warning"
    assert f["lines"] == [3, 4] and "alpaca_stop_manager.py" in f["message"]
    fixed544 = L544.replace("*/20 9-16", "7-59/20 9-16").replace(
        "cd $PROJ && bash scripts/market_day_gate.sh",
        "cd $PROJ && flock -n /tmp/tradeai_alpaca_stop_manager.lock bash scripts/market_day_gate.sh")
    fixed731 = L731.replace("/tmp/tradeai_oco_repair.lock", "/tmp/tradeai_alpaca_stop_manager.lock")
    assert ccs.check_shared_script_locks(HEAD + fixed544 + "\n" + fixed731 + "\n") == []


def test_non_broker_lock_fanout_is_info_not_warning():
    a = "0 6 * * * cd $PROJ && flock -n /tmp/a.lock $PY scripts/topic_research_synthesizer.py --apply --type x >> l 2>&1"
    b = "0 7 * * * cd $PROJ && flock -n /tmp/b.lock $PY scripts/topic_research_synthesizer.py --apply --type y >> l 2>&1"
    out = ccs.check_shared_script_locks(HEAD + a + "\n" + b + "\n")
    assert len(out) == 1 and out[0]["severity"] == "info"
    # read-only (no mutating flag) duplicates are not reported at all
    c = "0 6 * * * cd $PROJ && $PY scripts/report_x.py >> l 2>&1"
    assert ccs.check_shared_script_locks(HEAD + c + "\n" + c + "\n") == []


def test_r10_inline_python_quoting_bug():
    out = ccs.check_inline_python_quoting(HEAD + L897 + "\n")
    assert [f["type"] for f in out] == ["cron_inline_python_quoting"] and out[0]["line"] == 3
    ok = f"0 5 * * 1-5 cd {CUR} && python3 scripts/cio_wake_detector_cli.py --period weekly >> logs/x.log 2>&1"
    assert ccs.check_inline_python_quoting(HEAD + ok + "\n") == []


def test_lint_crontab_reproduces_all_seven_findings_then_clears():
    before = HEAD + "\n".join([L358, L544, L731, L791, L897]) + "\n"
    types = sorted(f["type"] for f in ccs.lint_crontab(before, exists=_exists))
    assert types == sorted([
        "cron_interpreter_missing",          # 358 (relative .venv from $HOME)
        "cron_interpreter_missing",          # 791
        "cron_relative_path_no_cd",          # 358
        "cron_shared_script_lock_conflict",  # 544+731
        "cron_inline_python_quoting",        # 897
    ])


def test_check_runs_the_linters_on_the_live_crontab_output(monkeypatch):
    def fake_run(*a, **k):
        return SimpleNamespace(returncode=0, stdout=HEAD + L791 + "\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(ccs.os.path, "exists", _exists)
    types = {f["type"] for f in ccs.check()}
    assert "cron_interpreter_missing" in types


# ── K-04: unit EnvironmentFile linter ──────────────────────────────────────

MOTION = "[Service]\nEnvironmentFile=-/etc/tardeai/active-trader-motion.env\nExecStart=/usr/bin/true\n"
SHADOW = "[Service]\nEnvironmentFile=-%t/tradeai/env\nEnvironmentFile=-%h/.config/tradeai/advisory-shadow.env\n"
STRICT = "[Service]\nEnvironmentFile=%h/.config/tradeai/required.env\n"


def test_unit_env_files_missing_are_reported_with_silent_skip_semantics(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    present = {"/run/user/1000/tradeai/env"}
    out = ue.lint_units([("tradeai-active-trader-motion.service", MOTION),
                         ("tradeai-advisory-shadow-session.service", SHADOW),
                         ("strict.service", STRICT)],
                        exists=lambda p: p in present, home=HOME)
    by = {(f["unit"], f["path"]): f for f in out}
    assert by[("tradeai-active-trader-motion.service", "/etc/tardeai/active-trader-motion.env")]["severity"] == "warning"
    assert "SILENTLY" in by[("tradeai-active-trader-motion.service", "/etc/tardeai/active-trader-motion.env")]["message"]
    assert by[("tradeai-advisory-shadow-session.service", f"{HOME}/.config/tradeai/advisory-shadow.env")]["severity"] == "warning"
    assert ("tradeai-advisory-shadow-session.service", "/run/user/1000/tradeai/env") not in by   # %t expanded, present
    assert by[("strict.service", f"{HOME}/.config/tradeai/required.env")]["severity"] == "critical"
    # the fix: correct path present -> clean
    fixed = MOTION.replace("/etc/tardeai/", f"{HOME}/.config/tradeai/")
    assert ue.lint_units([("m", fixed)], exists=lambda p: p.endswith("active-trader-motion.env"), home=HOME) == []


def test_unit_dir_walk_includes_dropins(tmp_path):
    (tmp_path / "a.service").write_text("[Service]\nEnvironmentFile=-/nope/one.env\n")
    d = tmp_path / "a.service.d"; d.mkdir()
    (d / "10-x.conf").write_text("[Service]\nEnvironmentFile=/nope/two.env\n")
    rows = ue.host_units(tmp_path)
    assert [r[0] for r in rows] == ["a.service", "a.service.d/10-x.conf"]
    out = ue.lint_units(rows, exists=lambda p: False, home="/h")
    assert {f["severity"] for f in out} == {"warning", "critical"}
