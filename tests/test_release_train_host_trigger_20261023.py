"""Release-train host trigger packet (ANCHOR RELEASE_TRAIN_HOST_TRIGGER_20261023).

Pins docs/ops/packets/release-train-host-trigger-20261023/ to the code it drives:

* the request service's argv parses with the writer's own CLI (scripts/release_train_window_request.py) as
  ``--window <slot> --append --shadow-only`` for every slot, from CURRENT, with the claimer's state dir and the run-id
  env name the writer actually reads;
* each request timer fires at its slot's window time in America/New_York (config/release_train_n8n.json), which the
  writer classifies on_window (request id ``-win``), Persistent=false;
* the census service runs the allowlist's pr-hygiene-audit argv under the allowlist's flock, 20 minutes before each
  window;
* install.sh: --preview writes nothing; --apply refuses without the typed ACK and without a CURRENT carrying the
  writer with --shadow-only; with both it archives (never deletes), installs, reloads, enables and verifies;
  rollback.sh disables and restores;
* the 8 lane registry rows are valid, systemd, stage shadow, and name the packet's timers.

Hermetic: HOME in tmp_path and a PATH whose systemctl is a recording stub. Nothing touches the real user units.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs/ops/packets/release-train-host-trigger-20261023"
CLAIMER = ROOT / "docs/ops/packets/release-train-20261021"
SLOTS = ("1800", "0000", "0600", "0800")
CENSUS_LEAD_MIN = 20
NY = ZoneInfo("America/New_York")


def _unit(name: str) -> dict[str, list[str]]:
    """{'Section.Key': [values...]} of a *.proposed unit (comments dropped)."""
    out: dict[str, list[str]] = {}
    section = ""
    for line in (PACKET / f"{name}.proposed").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        k, v = line.split("=", 1)
        out.setdefault(f"{section}.{k}", []).append(v)
    return out


def _one(unit: dict, key: str) -> str:
    vals = unit.get(key) or []
    assert len(vals) == 1, f"{key}: {vals}"
    return vals[0]


def _env(unit: dict) -> dict[str, str]:
    return dict(v.split("=", 1) for v in unit.get("Service.Environment", []))


def _cfg() -> dict:
    return json.loads((ROOT / "config/release_train_n8n.json").read_text())


# ── the request lane ─────────────────────────────────────────────────────────────────────────────────────────


CURRENT_PY = "%h/trade-ai-releases/portfolio-server/CURRENT/.venv/bin/python"


def _request_argv(slot: str) -> list[str]:
    svc = _unit("tradeai-release-train-request@.service")
    argv = _one(svc, "Service.ExecStart").replace("%i", slot).split()
    assert argv[0] == CURRENT_PY and argv[1] == "scripts/release_train_window_request.py"
    return argv[2:]


@pytest.mark.parametrize("slot", SLOTS)
def test_request_argv_parses_with_the_writers_cli(slot):
    from scripts import release_train_window_request as R

    args = _request_argv(slot)
    assert args == ["--window", slot, "--append", "--shadow-only"]
    a = R._parser().parse_args(args)
    assert a.window == slot and a.append is True and a.shadow_only is True and a.dry_run is False
    assert a.inject is None and a.state_dir is None


def test_request_service_runs_from_current_with_the_claimers_state_dir_and_run_id():
    from scripts.lib import lane_last_receipt as LR
    from scripts.lib import release_train_window as W

    svc = _unit("tradeai-release-train-request@.service")
    claim = (CLAIMER / "tradeai-release-train-claim.service.proposed").read_text()
    assert _one(svc, "Service.Type") == "oneshot"
    assert _one(svc, "Service.WorkingDirectory") == "%h/trade-ai-releases/portfolio-server/CURRENT"
    assert "WorkingDirectory=%h/trade-ai-releases/portfolio-server/CURRENT" in claim
    env = _env(svc)
    # The claimer sets no state env, so it resolves release_window's default; the writer is pinned to that default.
    assert "TRADEAI_RELEASE_WINDOW_STATE_DIR" not in claim and "TRADEAI_STATE_ROOT" not in claim
    state = env["TRADEAI_RELEASE_WINDOW_STATE_DIR"]
    assert state == "%h/trade-ai-releases/persistent-state/data/runtime/release_window"
    old = {k: os.environ.pop(k, None) for k in ("TRADEAI_RELEASE_WINDOW_STATE_DIR", "TRADEAI_STATE_ROOT")}
    try:
        assert str(W.resolve_state_dir()) == state.replace("%h", str(Path.home()))
    finally:
        os.environ.update({k: v for k, v in old.items() if v is not None})
    watch = (CLAIMER / "tradeai-release-train-claim.path.proposed").read_text()
    assert f"PathChanged={state}/train_requests/pending" in watch
    # The run id the writer actually reads.
    assert LR.RUN_ID_ENV == "TRADEAI_RUN_ID"
    assert env["TRADEAI_RUN_ID"] == "host-timer-%i"
    assert env["TRADEAI_N8N_RUN_ID"] == "host-timer-%i"
    assert W.RUN_ID_RE.fullmatch("host-timer-1800")


@pytest.mark.parametrize("slot", SLOTS)
def test_request_timer_fires_at_the_window_time_and_is_on_window(slot):
    from scripts.lib import release_train_window as W

    cfg = _cfg()
    local = next(s["local_time"] for s in cfg["slots"] if s["slot"] == slot)
    t = _unit(f"tradeai-release-train-request@{slot}.timer")
    assert _one(t, "Timer.OnCalendar") == f"*-*-* {local}:00 America/New_York"
    assert _one(t, "Timer.Persistent") == "false"
    assert _one(t, "Timer.Unit") == f"tradeai-release-train-request@{slot}.service"
    assert _one(t, "Install.WantedBy") == "timers.target"
    hh, mm = int(slot[:2]), int(slot[2:])
    # A winter and a summer day (DST-safe), at the fire time plus the timer's accuracy.
    for day in (datetime(2026, 1, 14, tzinfo=NY), datetime(2026, 7, 14, tzinfo=NY)):
        fire = day.replace(hour=hh, minute=mm) + timedelta(seconds=30)
        start = W.window_start(slot, fire, cfg)
        assert (start.hour, start.minute) == (hh, mm)
        tick = W.tick_kind(start, fire, cfg)
        assert tick == "on_window"
        assert W.request_id_for(slot, start, tick, "host-timer-" + slot).endswith(f"-{slot}-win")


# ── the census lane ──────────────────────────────────────────────────────────────────────────────────────────


def _allowlist_census() -> dict:
    doc = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())
    lanes = doc["lanes"] if isinstance(doc, dict) else doc
    return next(e for e in lanes if e.get("lane_id") == "pr-hygiene-audit")


def test_census_service_uses_the_allowlist_argv_and_lock():
    entry = _allowlist_census()
    svc = _unit("tradeai-pr-census@.service")
    argv = _one(svc, "Service.ExecStart").split()
    assert argv[:5] == ["/usr/bin/flock", "-n", "-E", "75", entry["lock"]]
    assert entry["lock"] == "/tmp/tradeai_pr_hygiene_audit.lock" and entry["lock_kind"] == "flock"
    assert argv[5] == CURRENT_PY
    assert entry["command"][0] == "$PY"
    assert argv[6:] == entry["command"][1:] + entry["live_arg"]
    assert _one(svc, "Service.SuccessExitStatus") == "75"
    assert _one(svc, "Service.WorkingDirectory") == "%h/trade-ai-releases/portfolio-server/CURRENT"
    assert int(_one(svc, "Service.TimeoutStartSec")) >= int(entry["timeout_s"])
    assert set(_env(svc)) <= set(entry["env_names"]) | {"TRADEAI_RUN_ID"}


@pytest.mark.parametrize("slot", SLOTS)
def test_census_timer_fires_20_minutes_before_its_window(slot):
    cfg = _cfg()
    local = next(s["local_time"] for s in cfg["slots"] if s["slot"] == slot)
    w = datetime(2026, 1, 14, int(local[:2]), int(local[3:]))
    c = w - timedelta(minutes=CENSUS_LEAD_MIN)
    t = _unit(f"tradeai-pr-census@{slot}.timer")
    assert _one(t, "Timer.OnCalendar") == f"*-*-* {c:%H:%M}:00 America/New_York"
    assert _one(t, "Timer.Persistent") == "false"
    assert _one(t, "Timer.Unit") == f"tradeai-pr-census@{slot}.service"


def test_packet_ships_exactly_the_ten_units():
    names = sorted(p.name for p in PACKET.glob("*.proposed"))
    want = sorted(
        ["tradeai-release-train-request@.service.proposed", "tradeai-pr-census@.service.proposed"]
        + [f"tradeai-release-train-request@{s}.timer.proposed" for s in SLOTS]
        + [f"tradeai-pr-census@{s}.timer.proposed" for s in SLOTS]
    )
    assert names == want


# ── install.sh / rollback.sh ─────────────────────────────────────────────────────────────────────────────────


def _current(tmp_path: Path, *, shadow_flag: bool = True, writer: bool = True) -> Path:
    cur = tmp_path / "CURRENT"
    (cur / "scripts").mkdir(parents=True)
    (cur / ".venv/bin").mkdir(parents=True)
    py = cur / ".venv/bin/python"
    py.write_text("#!/bin/sh\nexit 0\n")
    py.chmod(0o755)
    if writer:
        (cur / "scripts/release_train_window_request.py").write_text(
            '    ap.add_argument("--shadow-only")\n' if shadow_flag else "# no flag\n"
        )
    (cur / "scripts/pr_hygiene_audit.py").write_text("# census\n")
    return cur


def _run(tmp_path: Path, script: str, *args: str, stdin: str = "", current: Path | None = None):
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "systemctl").write_text(
        f'#!/bin/sh\necho "systemctl $*" >> {tmp_path}/calls.log\n'
        'case "$2" in is-enabled) echo enabled;; is-active) echo active;; esac\nexit 0\n'
    )
    (stub / "systemctl").chmod(0o755)
    env = {
        "PATH": f"{stub}:{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "TRADEAI_CURRENT": str(current or tmp_path / "nope"),
    }
    return subprocess.run(
        ["bash", str(PACKET / script), *args], env=env, input=stdin, capture_output=True, text=True, timeout=60
    )


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def _units_dir(tmp_path: Path) -> Path:
    return tmp_path / "home/.config/systemd/user"


def test_preview_is_the_default_and_writes_nothing(tmp_path):
    cur = _current(tmp_path)
    r = _run(tmp_path, "install.sh", current=cur)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("== PREVIEW: nothing is written")
    assert r.stdout.count(": NEW") == 10 and "PREFLIGHT: OK" in r.stdout
    assert not (tmp_path / "home").exists() and _calls(tmp_path) == []


def test_preview_shows_a_diff_against_an_installed_unit(tmp_path):
    cur = _current(tmp_path)
    units = _units_dir(tmp_path)
    units.mkdir(parents=True)
    (units / "tradeai-pr-census@1800.timer").write_text("[Timer]\nOnCalendar=old\n")
    before = sorted(p.name for p in units.iterdir())
    r = _run(tmp_path, "install.sh", "--preview", current=cur)
    assert r.returncode == 0
    assert "tradeai-pr-census@1800.timer: CHANGED" in r.stdout and "-OnCalendar=old" in r.stdout
    assert sorted(p.name for p in units.iterdir()) == before and _calls(tmp_path) == []


def test_apply_refuses_without_the_typed_ack(tmp_path):
    cur = _current(tmp_path)
    for typed in ("", "yes\n", "ack-train-trigger\n"):
        r = _run(tmp_path, "install.sh", "--apply", stdin=typed, current=cur)
        assert r.returncode == 2 and "acknowledgement not typed" in r.stdout
    assert not _units_dir(tmp_path).exists() and _calls(tmp_path) == []


@pytest.mark.parametrize("kw", [{"writer": False}, {"shadow_flag": False}])
def test_apply_refuses_unless_current_has_the_writer_with_shadow_only(tmp_path, kw):
    cur = _current(tmp_path, **kw)
    r = _run(tmp_path, "install.sh", "--apply", stdin="ACK-TRAIN-TRIGGER\n", current=cur)
    assert r.returncode == 2 and "refused: preflight failed" in r.stdout
    assert "release_train_window_request.py" in r.stdout
    assert not _units_dir(tmp_path).exists() and _calls(tmp_path) == []


def test_apply_archives_installs_enables_verifies_and_rollback_restores(tmp_path):
    cur = _current(tmp_path)
    units = _units_dir(tmp_path)
    units.mkdir(parents=True)
    old = units / "tradeai-pr-census@1800.timer"
    old.write_text("[Timer]\nOnCalendar=old\n")
    r = _run(tmp_path, "install.sh", "--apply", stdin="ACK-TRAIN-TRIGGER\n", current=cur)
    assert r.returncode == 0, r.stdout + r.stderr
    for p in PACKET.glob("*.proposed"):
        assert (units / p.name.removesuffix(".proposed")).read_text() == p.read_text()
    archives = list(units.glob("archived-release-train-host-trigger-*"))
    assert len(archives) == 1
    assert (archives[0] / "tradeai-pr-census@1800.timer").read_text() == "[Timer]\nOnCalendar=old\n"
    manifest = (archives[0] / "MANIFEST").read_text()
    assert "archived tradeai-pr-census@1800.timer enabled" in manifest and manifest.count("\nnew ") == 9
    calls = _calls(tmp_path)
    assert "systemctl --user daemon-reload" in calls
    enable = next(c for c in calls if c.startswith("systemctl --user enable --now"))
    assert sorted(enable.split()[4:]) == sorted(
        [f"tradeai-release-train-request@{s}.timer" for s in SLOTS] + [f"tradeai-pr-census@{s}.timer" for s in SLOTS]
    )
    assert any(c.startswith("systemctl --user list-timers") for c in calls)
    assert r.stdout.count("enabled, active") == 8

    r = _run(tmp_path, "rollback.sh", "--apply", stdin="nope\n", current=cur)
    assert r.returncode == 2 and (units / "tradeai-release-train-request@.service").exists()
    r = _run(tmp_path, "rollback.sh", "--apply", stdin="ACK-TRAIN-TRIGGER-ROLLBACK\n", current=cur)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = _calls(tmp_path)
    assert any(c.startswith("systemctl --user disable --now tradeai-release-train-request@1800.timer") for c in calls)
    assert old.read_text() == "[Timer]\nOnCalendar=old\n"  # restored
    assert not (units / "tradeai-release-train-request@.service").exists()
    rb = list(units.glob("archived-release-train-host-trigger-rollback-*"))
    assert len(rb) == 1 and (rb[0] / "tradeai-release-train-request@.service").exists()  # archived, not deleted
    assert calls[-2:][0].startswith("systemctl --user enable --now tradeai-pr-census@1800.timer")


def test_scripts_never_delete_and_never_touch_crontab():
    for name in ("install.sh", "rollback.sh"):
        text = (PACKET / name).read_text()
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        assert "rm " not in code and "rm -" not in code and "crontab" not in code
        assert "pkill" not in code


# ── registry rows + docs + gate ──────────────────────────────────────────────────────────────────────────────


def test_lane_registry_rows_declare_the_eight_timers_at_shadow():
    from scripts.lib import lane_registry as LRG

    reg = json.loads((ROOT / "config/lane_registry.json").read_text())
    rows = {r["lane_id"]: r for r in reg["lanes"]}
    for slot in SLOTS:
        for lane, timer in (
            (f"release-train-request-timer-{slot}", f"tradeai-release-train-request@{slot}.timer"),
            (f"pr-census-timer-{slot}", f"tradeai-pr-census@{slot}.timer"),
        ):
            row = rows[lane]
            assert LRG.validate_row(row) == []
            assert row["scheduler"]["kind"] == "systemd" and row["scheduler"]["expression"] == timer
            assert row["scheduler"]["stage"] == "shadow"
            assert row["state"] == "NEVER_SCHEDULED"  # until the operator installs; then ACTIVE by a follow-up PR
            assert (PACKET / f"{timer}.proposed").exists()
        assert rows[f"release-train-request-timer-{slot}"]["output_signal"]["path"] == (
            f"data/runtime/release-train-request-{slot}_last.json"
        )
        assert rows[f"pr-census-timer-{slot}"]["output_signal"]["path"] == "data/runtime/pr-hygiene-audit_last.json"


def test_readme_names_the_operator_commands_and_the_proof():
    text = (PACKET / "README.md").read_text(encoding="utf-8")
    for needle in (
        "bash $P/install.sh --preview",
        "bash $P/install.sh --apply",
        "ACK-TRAIN-TRIGGER",
        "bash $P/rollback.sh --apply",
        "-win",
        "journalctl --user -u 'tradeai-release-train-request@1800.service'",
        "train_requests/reports/",
    ):
        assert needle in text, needle
    assert "PROPOSAL ONLY" in (PACKET / "N8N_STEP_F_BOOTSTRAP_EXCEPTION_PROPOSAL.md").read_text(encoding="utf-8")


def test_ci_gate_is_registered():
    from scripts.lib import ci_gates

    names = dict(ci_gates.load_gates(ROOT))
    assert names.get("release_train_host_trigger_20261023") == ["tests/test_release_train_host_trigger_20261023.py"]
    doc = json.loads((ROOT / "config/ci_gates/release_train_host_trigger_20261023.json").read_text())
    assert doc["anchor"] == "RELEASE_TRAIN_HOST_TRIGGER_20261023"
