"""Registry / runtime truth: systemd is host evidence too (LQ-20261107-62, 2026-11-07).

`scripts/check_registry_runtime_truth.py` joined the declared registry with the crontab, the n8n workflow table and
the coordination ledger. It never read systemd, so 168 `kind: systemd` rows were unverified in both directions: a
timer the registry called ACTIVE could be disabled, and a timer the registry called PAUSED could be firing. It also
could not see one program under two live schedulers — `data-plausibility-audit` (timer) and
`n8n-data-plausibility-audit` (n8n, whose wrapper imports the same module) both run
`data_plausibility_monitor.lane_main`, and `gap-resolution-audit` / `n8n-gap-resolution-audit` do the same.

This file pins:

* the readers: `systemctl list-unit-files` + `systemctl show` only (no start/stop/enable/edit), BOTH managers
  (user and system) unioned per unit — `systemd-tmpfiles-clean.timer` is disabled/inactive in the user manager and
  static/active in the system manager, and `db-retention.timer` exists only in the user manager;
* the rules: ACTIVE_TIMER_ABSENT / _DISABLED / _INACTIVE, ACTIVE_SERVICE_INACTIVE, DECLARED_OFF_TIMER_ACTIVE /
  _SERVICE_ACTIVE, CRON_ROW_RUNS_UNDER_TIMER (a cron row whose lane a timer runs is named, never reported as
  absent) and DUPLICATE_SCHEDULER (an n8n entry script that imports the module a live timer runs, or a cron line
  beside a live timer);
* NOT_MEASURED: a declaration with no `kind: systemd` row never shells out and adds nothing to not_measured, and a
  declared systemd row with no readable source names every timer rule as NOT_MEASURED, never "clean".

Hermetic: canned systemctl output, tmp repo roots and ledgers; no systemctl, no crontab, no docker, no live state.

ANCHOR: REGISTRY_RUNTIME_TRUTH_SYSTEMD_LQ62_20261107

COVERS = ["scripts/check_registry_runtime_truth.py"]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import check_registry_runtime_truth as RT  # noqa: E402

LANE = "registry-runtime-truth"
ANCHOR = "REGISTRY_RUNTIME_TRUTH_SYSTEMD_LQ62_20261107"
SYSTEMD_CODES = ("ACTIVE_TIMER_ABSENT", "ACTIVE_TIMER_DISABLED", "ACTIVE_TIMER_INACTIVE", "ACTIVE_SERVICE_INACTIVE",
                 "DECLARED_OFF_TIMER_ACTIVE", "DECLARED_OFF_SERVICE_ACTIVE", "CRON_ROW_RUNS_UNDER_TIMER",
                 "DUPLICATE_SCHEDULER")

UNIT_FILES = "unit-a.timer enabled enabled\nunit-b.timer disabled enabled\nunit-c.timer enabled enabled\n"
TIMER_SHOW = (
    "Id=unit-a.timer\nTriggers=unit-a.service\nLoadState=loaded\nActiveState=active\n"
    "UnitFileState=enabled\n\n"
    "Id=unit-b.timer\nTriggers=unit-b.service\nLoadState=loaded\nActiveState=inactive\n"
    "UnitFileState=disabled\n"
)
SERVICE_SHOW = (
    "Id=unit-a.service\nLoadState=loaded\nActiveState=inactive\nUnitFileState=static\n"
    "ExecStart={ path=/usr/bin/python ; argv[]=/usr/bin/python /r/scripts/monitor_a.py --alert ; "
    "ignore_errors=no ; status=0/0 }\n\n"
    "Id=unit-b.service\nLoadState=loaded\nActiveState=inactive\nUnitFileState=static\n"
    "ExecStart={ path=/usr/bin/python ; argv[]=/usr/bin/python /r/scripts/monitor_b.py ; ignore_errors=no }\n"
)


# ── fixtures ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _row(lane, *, state="ACTIVE", kind="systemd", expression="unit-a.timer", match=None, stage=None, dispatch=None):
    sched = {"kind": kind, "expression": expression}
    if match is not None:
        sched["match"] = match
    if stage is not None:
        sched["stage"] = stage
    row = {"lane_id": lane, "owner": "t", "state": state, "scheduler": sched, "output_signal": {"kind": "none"}}
    if dispatch:
        row["dispatch"] = {"mode": dispatch}
    return row


def _decl(rows, *, contracts=(), allow=(), processes=None):
    return {"rows": {r["lane_id"]: r for r in rows}, "contracts": {c["id"]: c for c in contracts},
            "allow": {e["lane_id"]: e for e in allow}, "processes": processes or {}, "grandfathered_draft": []}


def _unit(*, present=True, enabled=True, live=True, scopes=("user",), live_scopes=("user",),
          file_state="enabled", active_state="active", triggers="", commands=()):
    return {"present": present, "enabled": enabled, "live": live, "scopes": list(scopes),
            "live_scopes": list(live_scopes), "unit_file_state": file_state, "active_state": active_state,
            "triggers": triggers, "commands": list(commands)}


def _codes(found):
    return [(c["code"], c["lane_id"]) for c in found]


def _runner(scopes):
    """A systemctl stand-in. ``scopes`` maps "user"/"system" to canned text, or to ``{"rc": 1}`` to fail."""
    calls: list[list[str]] = []

    def run(argv):
        calls.append(argv)
        canned = scopes.get("user" if "--user" in argv else "system") or {}
        if canned.get("rc"):
            return canned["rc"], ""
        if "list-unit-files" in argv:
            return 0, canned.get("files", "")
        props = next((a for a in argv if a.startswith("--property=")), "")
        return 0, canned.get("timers", "") if "Triggers" in props else canned.get("services", "")

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _both(*, user=None, system=None):
    return _runner({"user": user or {"files": UNIT_FILES, "timers": TIMER_SHOW, "services": SERVICE_SHOW},
                    "system": system if system is not None else {}})


def _ledger(path: Path, *, runs=()):
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT);"
        "CREATE TABLE effect_owners (process TEXT PRIMARY KEY, owner TEXT, epoch INTEGER, switched_at TEXT,"
        " switched_by TEXT, note TEXT);"
    )
    for i, (lane, mode, state, at) in enumerate(runs):
        conn.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?)", (f"r{i}", lane, mode, state, at))
    conn.commit()
    conn.close()
    return path


def _fixture_root(tmp_path, rows):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "lane_registry.json").write_text(json.dumps({"lanes": rows}), encoding="utf-8")
    (root / "config" / "n8n_health_contracts.json").write_text(json.dumps({"contracts": []}), encoding="utf-8")
    (root / "config" / "n8n_run_allowlist.json").write_text(json.dumps({"lanes": []}), encoding="utf-8")
    live = tmp_path / "live.env"
    live.write_text("TRADEAI_N8N_RELAY_LIVE_LANES=\n", encoding="utf-8")
    return root, _ledger(tmp_path / "ledger.sqlite"), live


def _report(tmp_path, rows, **kwargs):
    root, ledger, live = _fixture_root(tmp_path, rows)
    return RT.build_report(root=root, ledger_path=ledger, live_lanes_env=live, now=RT.datetime(2026, 11, 7, 12, tzinfo=RT.timezone.utc),
                           window_days=7, **kwargs)


# ── 1. readers and parsers ──────────────────────────────────────────────────────────────────────────────────────


def test_unit_name_reads_the_unit_out_of_an_annotated_expression():
    assert RT.unit_name("tradeai-data-plausibility.timer") == "tradeai-data-plausibility.timer"
    assert RT.unit_name("tradeai-health-tick.timer (*:0/5)") == "tradeai-health-tick.timer"
    assert RT.unit_name("tradeai-telegram-callback-poller.service (Restart=always)") == \
        "tradeai-telegram-callback-poller.service"
    assert RT.unit_name("hermes-external-feedback.timer (04:00, --model deepseek-v4-flash) — DISABLED") == \
        "hermes-external-feedback.timer"
    assert RT.unit_name("PROPOSED - NOT INSTALLED: no unit file") is None


def test_parse_unit_file_list_and_stanzas():
    assert RT.parse_unit_file_list(UNIT_FILES) == {"unit-a.timer": "enabled", "unit-b.timer": "disabled",
                                                   "unit-c.timer": "enabled"}
    joined = RT.parse_stanzas("Id=x.service\nExecStart=one\nExecStart=two\n\n")
    assert joined["x.service"]["ExecStart"] == "one ; two"


def test_exec_start_commands_extract_argv_and_redact_a_credential():
    value = ("{ path=/usr/bin/python ; argv[]=/usr/bin/python /r/scripts/monitor_a.py --alert ; ignore_errors=no }\n"
             "{ path=/usr/bin/python ; argv[]=/usr/bin/python /r/scripts/monitor_a.py --token=abcd1234 ; "
             "ignore_errors=no }")
    got = RT.exec_start_commands(value)
    assert got[0].endswith("/r/scripts/monitor_a.py --alert")
    assert got[1].endswith("--token=[REDACTED]") and "abcd1234" not in got[1]


def test_command_programs_finds_the_script_and_nothing_else():
    assert RT.command_programs("/venv/bin/python /a/b/data_plausibility_monitor.py --alert") == \
        {"data_plausibility_monitor"}
    assert RT.command_programs("flock -n /run/x.lock /a/b/run.sh") == set()


def test_reader_only_ever_asks_list_unit_files_and_show():
    run = _both()
    RT.read_systemd_units(["unit-a.timer"], run)
    verbs = [a for a in run.calls for a in [next((x for x in a if x in
                                                  ("list-unit-files", "show", "start", "stop", "enable", "disable",
                                                   "daemon-reload", "restart", "mask")), None)] if a]
    assert set(verbs) <= {"list-unit-files", "show"}
    assert run.calls[0][:2] == ["systemctl", "--user"]


def test_both_managers_are_unioned_per_unit():
    # systemd-tmpfiles-clean.timer: disabled/inactive for the user, static/active for the system (it does run).
    run = _runner({
        "user": {"files": "systemd-tmpfiles-clean.timer disabled enabled\n",
                 "timers": "Id=systemd-tmpfiles-clean.timer\nTriggers=systemd-tmpfiles-clean.service\n"
                           "LoadState=loaded\nActiveState=inactive\nUnitFileState=disabled\n",
                 "services": ""},
        "system": {"files": "systemd-tmpfiles-clean.timer static -\n",
                   "timers": "Id=systemd-tmpfiles-clean.timer\nTriggers=systemd-tmpfiles-clean.service\n"
                             "LoadState=loaded\nActiveState=active\nUnitFileState=static\n",
                   "services": "Id=systemd-tmpfiles-clean.service\nActiveState=inactive\n"
                               "ExecStart={ path=/usr/bin/systemd-tmpfiles ; argv[]=/usr/bin/systemd-tmpfiles "
                               "--clean ; ignore_errors=no }\n"},
    })
    st, units, _ = RT.read_systemd_units(["systemd-tmpfiles-clean.timer"], run)
    obs = units["systemd-tmpfiles-clean.timer"]
    assert (st, obs["present"], obs["enabled"], obs["live"]) == ("ok", True, True, True)
    assert sorted(obs["scopes"]) == ["system", "user"] and obs["live_scopes"] == ["system"]
    found, nm, _ = RT.evaluate(_decl([_row("tmpfiles", expression="systemd-tmpfiles-clean.timer")]),
                               ledger=None, live_lanes=None, cron_lines=None, n8n_active=None, systemd=units)
    assert found == [] and "ACTIVE_TIMER_ABSENT" not in nm


def test_a_timer_command_is_the_execstart_of_the_service_it_triggers():
    st, units, _ = RT.read_systemd_units(["unit-a.timer"], _both())
    assert st == "ok"
    assert units["unit-a.timer"]["triggers"] == "unit-a.service"
    assert units["unit-a.timer"]["commands"] == ["/usr/bin/python /r/scripts/monitor_a.py --alert"]
    assert units["unit-b.timer"]["commands"] == ["/usr/bin/python /r/scripts/monitor_b.py"]


def test_one_unreadable_manager_is_not_measured_not_clean():
    run = _runner({"user": {"files": UNIT_FILES, "timers": TIMER_SHOW, "services": SERVICE_SHOW},
                   "system": {"rc": 1}})
    st, units, note = RT.read_systemd_units(["unit-b.timer"], run)
    assert st == "unavailable" and "rc 1" in note
    found, nm, _ = RT.evaluate(_decl([_row("lane-b", expression="unit-b.timer")]), ledger=None, live_lanes=None,
                               cron_lines=None, n8n_active=None, systemd=None)
    assert found == []
    assert {"ACTIVE_TIMER_ABSENT", "ACTIVE_TIMER_DISABLED", "ACTIVE_TIMER_INACTIVE",
            "DECLARED_OFF_TIMER_ACTIVE", "DECLARED_OFF_SERVICE_ACTIVE", "ACTIVE_SERVICE_INACTIVE",
            "CRON_ROW_RUNS_UNDER_TIMER", "DUPLICATE_SCHEDULER"} <= set(nm)


def test_script_modules_reads_imports_and_never_executes_the_script(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "n8n_wrapper.py").write_text(
        "import json\nfrom data_plausibility_monitor import LANE_ID, lane_main\nfrom scripts.lib import thing\n",
        encoding="utf-8")
    marker = tmp_path / "executed"
    (root / "scripts" / "bomb.py").write_text(
        f"open({str(marker)!r}, 'w').write('x')\n", encoding="utf-8")
    mods = RT.read_script_modules(root, ["scripts/n8n_wrapper.py", "scripts/bomb.py", "scripts/missing.py"])
    assert "data_plausibility_monitor" in mods["scripts/n8n_wrapper.py"]
    assert "lib" in mods["scripts/n8n_wrapper.py"] and "json" in mods["scripts/n8n_wrapper.py"]
    assert "scripts/missing.py" not in mods
    assert not marker.exists(), "the reader parsed a script and the script ran"


# ── 2. rules ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_active_timer_absent_disabled_and_inactive_are_distinct():
    systemd = {"gone.timer": _unit(present=False, enabled=False, live=False, scopes=()),
               "off.timer": _unit(enabled=False, live=False, file_state="disabled", active_state="inactive"),
               "on.timer": _unit(enabled=True, live=False, active_state="inactive")}
    decl = _decl([_row("gone", expression="gone.timer"), _row("off", expression="off.timer"),
                  _row("on", expression="on.timer")])
    found, nm, _ = RT.evaluate(decl, ledger=None, live_lanes=None, cron_lines=None, n8n_active=None, systemd=systemd)
    assert _codes(found) == [("ACTIVE_TIMER_ABSENT", "gone"), ("ACTIVE_TIMER_DISABLED", "off"),
                             ("ACTIVE_TIMER_INACTIVE", "on")]
    assert not (set(SYSTEMD_CODES) & set(nm)), f"systemd was readable, so it must not be not_measured: {nm}"
    assert found[0]["evidence"]["unit"] == "gone.timer"
    assert found[2]["evidence"]["active_state"] == "inactive"


def test_a_disabled_timer_names_the_cron_lines_that_actually_run_the_lane():
    systemd = {"iris.timer": _unit(enabled=False, live=False, file_state="disabled", active_state="inactive",
                                   commands=["/venv/bin/python /r/scripts/iris_taxonomy_agent.py"])}
    cron = ["30 8 * * * /venv/bin/python /r/scripts/iris_taxonomy_agent.py --apply",
            "30 12 * * * /venv/bin/python /r/scripts/iris_taxonomy_agent.py --apply",
            "0 1 * * * /venv/bin/python /r/scripts/something_else.py"]
    found, _, _ = RT.evaluate(_decl([_row("iris-timer", expression="iris.timer")]), ledger=None, live_lanes=None,
                              cron_lines=cron, n8n_active=None, systemd=systemd)
    assert _codes(found) == [("ACTIVE_TIMER_DISABLED", "iris-timer")]
    assert found[0]["evidence"]["cron_lines_running_program"] == 2
    assert "2 active crontab line(s) run" in found[0]["detail"]


def test_declared_off_timer_and_service_that_are_active():
    systemd = {"paused.timer": _unit(live_scopes=("system",), scopes=("user", "system")),
               "retired.service": _unit(file_state="enabled", active_state="active", live_scopes=("system",),
                                        scopes=("system",))}
    decl = _decl([_row("paused", state="PAUSED", expression="paused.timer"),
                  _row("retired", state="RETIRED", expression="retired.service")])
    found, _, _ = RT.evaluate(decl, ledger=None, live_lanes=None, cron_lines=None, n8n_active=None, systemd=systemd)
    assert _codes(found) == [("DECLARED_OFF_SERVICE_ACTIVE", "retired"),
                             ("DECLARED_OFF_TIMER_ACTIVE", "paused")]
    assert "active in system" in found[1]["detail"] and found[1]["evidence"]["live_scopes"] == ["system"]


def test_an_active_service_row_that_is_not_active():
    systemd = {"api.service": _unit(present=False, enabled=False, live=False, file_state=None, active_state=None,
                                    scopes=())}
    found, _, _ = RT.evaluate(_decl([_row("api", expression="api.service")]), ledger=None, live_lanes=None,
                              cron_lines=None, n8n_active=None, systemd=systemd)
    assert _codes(found) == [("ACTIVE_SERVICE_INACTIVE", "api")]
    assert "not installed" in found[0]["detail"]


def test_a_cron_row_whose_script_a_live_timer_runs_is_named_not_absent():
    systemd = {"sweep.timer": _unit(commands=["/venv/bin/python /r/scripts/sweep.py --apply"])}
    row = _row("sweep", kind="cron", expression="0 7 * * *", match="scripts/sweep.py")
    found, _, _ = RT.evaluate(_decl([row]), ledger=None, live_lanes=None, cron_lines=["0 1 * * * other.py"],
                              n8n_active=None, systemd=systemd)
    assert _codes(found) == [("CRON_ROW_RUNS_UNDER_TIMER", "sweep")]
    assert found[0]["evidence"]["timer_unit"] == "sweep.timer"
    # and with the timer absent the cron rule still fires as before: the report never silently drops the lane
    found, _, _ = RT.evaluate(_decl([row]), ledger=None, live_lanes=None, cron_lines=["0 1 * * * other.py"],
                              n8n_active=None, systemd={})
    assert _codes(found) == [("ACTIVE_CRON_LINE_ABSENT", "sweep")]


def test_one_program_under_two_live_schedulers_is_one_finding_for_the_n8n_lane():
    systemd = {"plaus.timer": _unit(commands=["/venv/bin/python /r/scripts/data_plausibility_monitor.py --alert"])}
    n8n = _row("n8n-plaus", kind="n8n", expression="dispatcher", match="scripts/n8n_plaus.py", stage="canary",
               dispatch="live")
    decl = _decl([n8n])
    found, _, _ = RT.evaluate(decl, ledger=None, live_lanes=None, cron_lines=[], n8n_active=None, systemd=systemd,
                              script_modules={"scripts/n8n_plaus.py": ["data_plausibility_monitor", "json"]})
    assert _codes(found) == [("DUPLICATE_SCHEDULER", "n8n-plaus")]
    assert found[0]["evidence"]["timer_unit"] == "plaus.timer"
    # a shadow lane beside the timer is not a duplicate: two schedulers, one live
    shadow = _row("n8n-plaus", kind="n8n", expression="dispatcher", match="scripts/n8n_plaus.py", stage="shadow")
    found, _, _ = RT.evaluate(_decl([shadow]), ledger=None, live_lanes=None, cron_lines=[], n8n_active=None,
                              systemd=systemd, script_modules={"scripts/n8n_plaus.py": ["data_plausibility_monitor"]})
    assert found == []


def test_one_program_under_two_live_schedulers_is_one_finding_for_the_cron_row():
    systemd = {"sweep.timer": _unit(commands=["/venv/bin/python /r/scripts/sweep.py"])}
    row = _row("sweep", kind="cron", expression="0 7 * * *", match="scripts/sweep.py")
    cron = ["0 7 * * * /venv/bin/python /r/scripts/sweep.py --apply"]
    found, _, _ = RT.evaluate(_decl([row]), ledger=None, live_lanes=None, cron_lines=cron, n8n_active=None,
                              systemd=systemd)
    assert _codes(found) == [("DUPLICATE_SCHEDULER", "sweep")]


# ── 3. NOT_MEASURED and the CLI ────────────────────────────────────────────────────────────────────────────────


def test_a_declaration_with_no_systemd_row_adds_no_not_measured():
    decl = _decl([_row("n8n-lane", kind="n8n", expression="dispatcher", match="scripts/x.py", stage="canary")])
    found, nm, _ = RT.evaluate(decl, ledger=None, live_lanes=None, cron_lines=None, n8n_active=None)
    assert found == []
    assert not (set(SYSTEMD_CODES) & set(nm)), f"no systemd row declared, so systemd must not be not_measured: {nm}"


def test_declared_systemd_rows_without_a_source_are_not_measured():
    found, nm, _ = RT.evaluate(_decl([_row("timer-lane", expression="unit-a.timer")]), ledger=None, live_lanes=None,
                               cron_lines=None, n8n_active=None)
    assert found == []
    assert {"ACTIVE_TIMER_ABSENT", "ACTIVE_TIMER_DISABLED", "ACTIVE_TIMER_INACTIVE", "DECLARED_OFF_TIMER_ACTIVE",
            "DECLARED_OFF_SERVICE_ACTIVE", "ACTIVE_SERVICE_INACTIVE", "DUPLICATE_SCHEDULER"} <= set(nm)
    assert "registry/runtime truth: clean" not in RT.render({"sources": {}, "not_measured": nm,
                                                             "contradiction_count": 0})


def test_a_fixture_repo_without_systemd_rows_never_shells_out(tmp_path):
    def boom(argv):
        raise AssertionError(f"systemctl was called for a declaration with no systemd row: {argv}")

    report = _report(tmp_path, [_row("n8n-lane", kind="n8n", expression="dispatcher", match="scripts/x.py",
                                     stage="canary")], systemd_runner=boom)
    assert "systemd" not in report["sources"]
    assert report["contradictions"] == []


def test_no_systemd_flag_marks_the_source_skipped_and_the_output_not_measured(tmp_path):
    report = _report(tmp_path, [_row("timer-lane", expression="unit-a.timer")], skip_systemd=True)
    assert report["sources"]["systemd"]["status"] == "skipped"
    assert "ACTIVE_TIMER_DISABLED" in report["not_measured"]
    assert RT.lane_output(report)["skipped_reasons"] == {"not_measured_systemd": 1}


def test_the_reader_is_wired_into_the_report(tmp_path):
    report = _report(tmp_path, [_row("timer-lane", expression="unit-a.timer")], systemd_runner=_both())
    assert report["sources"]["systemd"]["status"] == "ok"
    assert report["sources"]["systemd"]["declared_units"] == 1
    assert report["contradictions"] == []


# ── 4. the committed registry ───────────────────────────────────────────────────────────────────────────────────


def test_every_committed_systemd_row_names_a_unit():
    registry = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    rows = [r for r in registry["lanes"] if (r.get("scheduler") or {}).get("kind") == "systemd"]
    assert len(rows) > 100, "the registry's systemd scope shrank unexpectedly"
    unnamed = [r["lane_id"] for r in rows if RT.unit_name(r["scheduler"].get("expression")) is None]
    assert unnamed == [], f"systemd rows with no unit for the checker to join: {unnamed}"
