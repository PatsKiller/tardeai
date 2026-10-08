"""2026-10-08: five user timers (governance-pipeline, portfolio daily/weekly/monthly/lookthrough cadence) ran
`/usr/bin/bash <dev tree>/scripts/pipelines/run_*.sh --apply` from host-only unit copies with NO repo unit text,
and tradeai-operator-answer-quality.service was the sixth --alert monitor whose repo file still named the dev
tree. The repo now carries all eleven unit files pinned to the served CURRENT tree, with the measured
OnCalendar preserved exactly. Hermetic: parses repo files only; nothing here touches systemd or the host.
The operator installs the files under a config-write grant; merging this installs nothing."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "config" / "systemd" / "user"
CURRENT = "%h/trade-ai-releases/portfolio-server/CURRENT"
DEV_TREE_NAME = "trade-ai-v12-rebuild"
# Built from parts so this file never carries the live-host literal it forbids (check_test_host_paths).
HOST_LITERAL = "/home/" + "johnclaw"

# unit stem -> (ExecStart exactly as measured on the host 2026-10-08 but re-rooted, measured OnCalendar lines)
CADENCE = {
    "tradeai-governance-pipeline": (
        f"/usr/bin/bash {CURRENT}/scripts/pipelines/run_governance_pipeline.sh --apply",
        ["Mon-Fri 07:40", "Sun 18:00"],
    ),
    "tradeai-portfolio-daily-cadence": (
        f"/usr/bin/bash {CURRENT}/scripts/pipelines/run_portfolio_maintenance_pipeline.sh --cadence daily --apply",
        ["Mon-Fri *-*-* 07:30:00"],
    ),
    "tradeai-portfolio-weekly-cadence": (
        f"/usr/bin/bash {CURRENT}/scripts/pipelines/run_portfolio_maintenance_pipeline.sh --cadence weekly --apply",
        ["Sun *-*-* 20:30:00"],
    ),
    "tradeai-portfolio-monthly-cadence": (
        f"/usr/bin/bash {CURRENT}/scripts/pipelines/run_portfolio_maintenance_pipeline.sh --cadence monthly --apply",
        ["*-*-01 07:35:00"],
    ),
    "tradeai-portfolio-lookthrough-cadence": (
        f"/usr/bin/bash {CURRENT}/scripts/pipelines/run_portfolio_maintenance_pipeline.sh --cadence lookthrough --apply",
        ["Sun *-*-01..07 06:30:00"],
    ),
}
OAQ = "tradeai-operator-answer-quality"
ALL_FILES = [f"{u}.service" for u in CADENCE] + [f"{u}.timer" for u in CADENCE] + [f"{OAQ}.service"]


def parse_unit(path: Path) -> dict[str, dict[str, list[str]]]:
    """Minimal systemd unit parser: sections of repeatable key=value, `#` comments, `\\` line continuation."""
    out: dict[str, dict[str, list[str]]] = {}
    section = None
    pending = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = pending + raw.strip()
        pending = ""
        if not line or line.startswith(("#", ";")):
            continue
        if line.endswith("\\"):
            pending = line[:-1] + " "
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            out.setdefault(section, {})
            continue
        assert section is not None, f"{path.name}: directive before any section: {line}"
        key, sep, value = line.partition("=")
        assert sep, f"{path.name}: not key=value: {line}"
        out[section].setdefault(key.strip(), []).append(" ".join(value.split()))
    assert not pending, f"{path.name}: dangling continuation"
    return out


def test_all_eleven_unit_files_exist_and_parse():
    for name in ALL_FILES:
        unit = parse_unit(UNITS / name)
        assert "Unit" in unit and unit["Unit"].get("Description"), name
        if name.endswith(".service"):
            assert unit["Service"]["Type"] == ["oneshot"], name
        else:
            assert "Timer" in unit and unit["Install"]["WantedBy"] == ["timers.target"], name


def test_services_execute_the_served_tree_not_the_dev_tree():
    for stem, (exec_start, _) in CADENCE.items():
        svc = parse_unit(UNITS / f"{stem}.service")["Service"]
        assert svc["WorkingDirectory"] == [CURRENT], stem
        assert svc["ExecStart"] == [exec_start], stem
        for directive in ("WorkingDirectory", "ExecStart"):
            assert DEV_TREE_NAME not in svc[directive][0], (stem, directive)
        # The served tree has no .venv: the interpreter is named explicitly for every step that honours PY.
        assert svc["Environment"] == [f"PY=%h/{DEV_TREE_NAME}/{DEV_TREE_NAME}/.venv/bin/python"], stem
        assert "-%t/tradeai/env" in svc["EnvironmentFile"], stem


def test_timers_preserve_the_measured_schedule():
    for stem, (_, on_calendar) in CADENCE.items():
        tmr = parse_unit(UNITS / f"{stem}.timer")["Timer"]
        assert tmr["OnCalendar"] == on_calendar, stem
        assert tmr["Persistent"] == ["true"], stem
        assert "RandomizedDelaySec" not in tmr, stem   # none measured; adding one silently shifts the cadence


def test_operator_answer_quality_runs_the_served_tree():
    svc = parse_unit(UNITS / f"{OAQ}.service")["Service"]
    assert svc["WorkingDirectory"] == [CURRENT]
    exec_start = svc["ExecStart"][0]
    assert exec_start.endswith(f"{CURRENT}/scripts/check_operator_answer_quality.py --alert")
    assert ".venv/bin/python" in exec_start          # interpreter stays the shared venv (CURRENT has none)
    assert not re.search(r"^WorkingDirectory=.*" + DEV_TREE_NAME, (UNITS / f"{OAQ}.service").read_text(), re.M)
    baseline = (ROOT / "config" / "dev_tree_units_baseline.txt").read_text().splitlines()
    assert f"{OAQ}.service" not in {l.strip() for l in baseline}


def test_no_unit_file_carries_a_live_host_literal():
    for name in ALL_FILES:
        text = (UNITS / name).read_text(encoding="utf-8")
        if name == f"{OAQ}.service":
            # Pre-existing file: its Documentation= URI predates the host-path rule (as in the five alert
            # units fixed the same day); the directives that execute must not name the host.
            svc = parse_unit(UNITS / name)["Service"]
            assert HOST_LITERAL not in svc["WorkingDirectory"][0] + svc["ExecStart"][0], name
            continue
        assert HOST_LITERAL not in text, name   # new files: not even in comments
        # Header contract: operator install under a config-write grant; the ten new files also cite the
        # measured host source (comments may wrap, so only phrases that cannot wrap are checked).
        assert "config-write grant" in text, name
        if name != f"{OAQ}.service":
            assert "Measured 2026-10-08" in text, name


def test_governance_controller_takes_py_from_the_environment_and_fails_loudly(tmp_path):
    """The unit exports PY because CURRENT has no .venv; the dev-tree default keeps cron/manual runs unchanged."""
    text = (ROOT / "scripts" / "pipelines" / "run_governance_pipeline.sh").read_text()
    assert 'PY="${PY:-$PROJ/.venv/bin/python}"' in text
    assert "exit 78" in text
    head = "\n".join(l for l in text.splitlines() if l.startswith(("PY=", '[ -x "$PY" ]')))
    probe = tmp_path / "probe.sh"
    probe.write_text("#!/usr/bin/env bash\nPROJ=\"$1\"\n" + head + "\necho \"$PY\"\n")
    env = {"PATH": "/usr/bin:/bin"}
    missing = subprocess.run(["bash", str(probe), str(tmp_path)], capture_output=True, text=True, env=env)
    assert missing.returncode == 78 and "PY not executable" in missing.stderr
    forced = subprocess.run(["bash", str(probe), str(tmp_path)], capture_output=True, text=True,
                            env={**env, "PY": "/bin/true"})
    assert forced.returncode == 0 and forced.stdout.strip() == "/bin/true"
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("#!/bin/sh\n")
    (venv / "python").chmod(0o755)
    default = subprocess.run(["bash", str(probe), str(tmp_path)], capture_output=True, text=True, env=env)
    assert default.returncode == 0 and default.stdout.strip() == str(venv / "python")
