"""Fixture-only tests: packet never operates on installed units or live services."""

from __future__ import annotations

import copy
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs/ops/packets/continuous-from-current-20261023"
spec = importlib.util.spec_from_file_location("wp27_packet", PACKET / "packet.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
NOW = datetime(2026, 10, 23, 22, tzinfo=timezone.utc)


def sample():
    return {
        "config": {
            "User": "johnclaw",
            "WorkingDirectory": p.CANONICAL,
            "argv": list(p.OLD_ARGV),
            "files": {"/unit": "a" * 64},
        },
        "release": {"path": "/fixture/release", "sha": "1" * 40},
        "runtime": {"active": "active", "sub": "running", "pid": 123},
    }


class FakeHost:
    def __init__(self):
        self.state = sample()
        self.store = {}
        self.calls = []
        self.clock = NOW
        self.bad_cwd = False
        self.bad_effective = False

    def now(self):
        return self.clock

    def snapshot(self):
        self.calls.append("snapshot")
        return copy.deepcopy(self.state)

    def folder(self):
        self.calls.append("folder")
        return Path("/fixture/run-" + str(len(self.calls)))

    def save(self, folder, name, value):
        result = str(folder / name)
        self.store[result] = copy.deepcopy(value)
        return Path(result)

    def load(self, path):
        return copy.deepcopy(self.store[str(path)])

    def install(self, folder):
        self.calls.append("install")
        self.state["config"]["argv"] = list(p.NEW_ARGV) if not self.bad_effective else ["wrong"]
        self.state["config"]["WorkingDirectory"] = str(p.CURRENT)
        return {"existed": False, "sha256": "d" * 64, "managed": str(p.MANAGED)}

    def reload(self):
        self.calls.append("reload")

    def restart(self):
        self.calls.append("restart")

    def proof(self, expected):
        self.calls.append("proof")
        if self.bad_cwd:
            raise ValueError("cwd mismatch")
        return {"passed": True, "pid": 321, "cwd": expected, "start_ticks": "99"}

    def rollback(self, path, receipt):
        self.calls.append("rollback")
        self.state = copy.deepcopy(receipt["before"])


@pytest.mark.parametrize(
    "stamp,blocked",
    [
        ("2026-10-23T07:59:59+00:00", False),
        ("2026-10-23T08:00:00+00:00", True),
        ("2026-10-23T20:14:59+00:00", True),
        ("2026-10-23T20:15:00+00:00", False),
        ("2026-11-02T08:59:59+00:00", False),
        ("2026-11-02T09:00:00+00:00", True),
        ("2026-11-26T17:00:00+00:00", True),  # holidays conservatively blocked
        ("2026-10-24T16:00:00+00:00", False),
    ],
)
def test_dst_window_boundaries(stamp, blocked):
    if blocked:
        with pytest.raises(ValueError, match="refused"):
            p.outside_window(datetime.fromisoformat(stamp))
    else:
        p.outside_window(datetime.fromisoformat(stamp))


def test_naive_clock_refused():
    with pytest.raises(ValueError, match="zoned"):
        p.outside_window(datetime(2026, 10, 23))


def test_blocked_preview_does_not_collect_or_write():
    host = FakeHost()
    with pytest.raises(ValueError):
        p.preview(host, datetime(2026, 10, 23, 15, tzinfo=timezone.utc))
    assert not host.calls and not host.store


def test_preview_only_records_safe_metadata():
    host = FakeHost()
    path = p.preview(host, NOW)
    assert host.load(path)["schema"] == "ContinuousCurrentPreview@v1"
    assert "install" not in host.calls and "restart" not in host.calls
    assert "Environment" not in p.PROPERTIES


@pytest.mark.parametrize("field", ["argv", "User", "WorkingDirectory"])
def test_unreviewed_command_user_or_directory_refused(field):
    state = sample()
    state["config"][field] = ["/usr/bin/flock", "unsafe"] if field == "argv" else "unexpected"
    with pytest.raises(ValueError):
        p.validate_config(state)


@pytest.mark.parametrize("mutation", ["expired", "future", "release", "unit", "payload"])
def test_preview_expiry_and_drift_stop_before_mutation(mutation):
    host = FakeHost()
    path = p.preview(host, NOW)
    if mutation in {"expired", "future"}:
        receipt = host.store[str(path)]
        receipt["at"] = (
            NOW + timedelta(seconds=1) if mutation == "future" else NOW - timedelta(minutes=16)
        ).isoformat()
    elif mutation == "release":
        host.state["release"]["sha"] = "2" * 40
    elif mutation == "unit":
        host.state["config"]["files"]["/unit"] = "b" * 64
    else:
        host.store[str(path)]["payload_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        p.apply(host, NOW, path, restart=True)
    assert "install" not in host.calls and "restart" not in host.calls


def test_apply_without_restart_is_pending_not_runtime_success():
    host = FakeHost()
    result = p.apply(host, NOW, p.preview(host, NOW))
    receipt = host.load(result)
    assert receipt["status"] == "CONFIGURED_PENDING_RESTART_OR_NATURAL_FIRE"
    assert "runtime_proof" not in receipt and "restart" not in host.calls
    assert any(key.endswith("installed-before-reload.json") for key in host.store)


def test_restart_requires_cwd_proof_and_preserves_lock():
    host = FakeHost()
    result = p.apply(host, NOW, p.preview(host, NOW), restart=True)
    receipt = host.load(result)
    assert receipt["status"] == "RUNNING_FROM_VERIFIED_CURRENT"
    assert receipt["runtime_proof"]["cwd"] == host.state["release"]["path"]
    assert p.NEW_ARGV[:5] == p.OLD_ARGV[:5]
    assert "PROJECT_ROOT=" + str(p.CURRENT) in p.NEW_ARGV


def test_failed_proof_has_recovery_receipt_and_never_claims_runtime_success():
    host = FakeHost()
    host.bad_cwd = True
    with pytest.raises(ValueError, match="rollback"):
        p.apply(host, NOW, p.preview(host, NOW), restart=True)
    assert (
        next(value for key, value in host.store.items() if key.endswith("failed.json"))["status"]
        == "RUNTIME_PROOF_FAILED"
    )
    assert "rollback" not in host.calls


def test_wrong_effective_command_is_recorded_and_not_restarted():
    host = FakeHost()
    host.bad_effective = True
    with pytest.raises(ValueError, match="effective"):
        p.apply(host, NOW, p.preview(host, NOW), restart=True)
    assert "restart" not in host.calls
    assert any(key.endswith("failed.json") for key in host.store)


def test_crossing_market_boundary_stops_before_install():
    host = FakeHost()
    before_open = datetime(2026, 10, 23, 7, 59, tzinfo=timezone.utc)
    preview = p.preview(host, before_open)
    host.clock = datetime(2026, 10, 23, 8, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="refused"):
        p.apply(host, before_open, preview, restart=True)
    assert "install" not in host.calls


def test_rollback_preview_never_changes_host():
    host = FakeHost()
    receipt = p.apply(host, NOW, p.preview(host, NOW))
    host.calls.clear()
    result = p.rollback(host, NOW, receipt)
    assert result["status"] == "ROLLBACK_PREVIEW" and host.calls == []


def test_explicit_rollback_calls_only_managed_restore_reload_and_optional_restart():
    host = FakeHost()
    receipt = p.apply(host, NOW, p.preview(host, NOW))
    host.calls.clear()
    result = p.rollback(host, NOW, receipt, apply_change=True)
    assert host.calls == ["rollback", "reload", "folder"]
    assert host.load(result)["proof"] is None


def test_real_file_adapter_archives_then_restores_without_deletion(tmp_path, monkeypatch):
    managed = tmp_path / "unit.d/zzzz-wp27-current.conf"
    monkeypatch.setattr(p, "MANAGED", managed)
    folder = tmp_path / "run-before"
    folder.mkdir()
    host = p.Host()
    installed = host.install(folder)
    assert managed.read_bytes() == (PACKET / "continuous-current.conf").read_bytes()
    host.rollback(folder / "installed.json", {"installed": installed, "before_dropin_sha256": None})
    assert not managed.exists()
    assert (folder / "retired-installed.conf").is_file()
    assert list(managed.parent.glob("*.archived-*"))


def test_actual_dropin_must_parse_to_declared_lock_and_current_command():
    text = (PACKET / "continuous-current.conf").read_text()
    start = next(line for line in text.splitlines() if line.startswith("ExecStart=") and line != "ExecStart=")
    assert shlex_split(start[len("ExecStart=") :]) == p.NEW_ARGV
    assert text.count("ExecStart=") == 2
    assert "EnvironmentFile" not in text and "--user" not in text


def shlex_split(value):
    import shlex

    return shlex.split(value)


def test_systemd_show_argv_parser_rejects_multiple_or_unknown_commands():
    text = "{ path=/usr/bin/flock ; argv[]=" + " ".join(p.OLD_ARGV) + " ; ignore_errors=no ; start_time=[n/a] ; pid=0 }"
    assert p.argv_from_show(text) == p.OLD_ARGV
    with pytest.raises(ValueError):
        p.argv_from_show("incomplete")


def test_cli_has_no_environment_clock_or_production_path_override():
    text = (PACKET / "packet.py").read_text()
    assert "os.environ" not in text
    assert '"--now"' not in text and '"--unit"' not in text
    gate = json.loads((ROOT / "config/ci_gates/continuous_current_packet_20261023.json").read_text())
    assert "tests/test_continuous_current_packet_20261023.py" in gate["files"]


@pytest.mark.parametrize("enabled", [True, False])
def test_registry_proposal_records_distinct_system_scope_without_promoting_user_timer(enabled):
    state = sample()
    state["runtime"]["timer"] = {"UnitFileState": "enabled" if enabled else "disabled", "ActiveState": "active"}
    row = p.registry_proposal(state, NOW)
    assert row["lane_id"] == "tradeai-continuous-system"
    assert row["scheduler"]["scope"] == "system"
    assert row["state"] == ("ACTIVE" if enabled else "PAUSED")
    assert "Preserve the existing PAUSED user-timer row" in row["reason_evidence"]


def test_real_file_adapter_refuses_dropin_drift(tmp_path, monkeypatch):
    managed = tmp_path / "unit.d/zzzz-wp27-current.conf"
    managed.parent.mkdir()
    managed.write_text("different operator configuration\n")
    monkeypatch.setattr(p, "MANAGED", managed)
    folder = tmp_path / "run"
    folder.mkdir()
    with pytest.raises(ValueError, match="differs"):
        p.Host().install(folder)
    assert managed.read_text() == "different operator configuration\n"


def test_real_rollback_refuses_modified_installed_file(tmp_path, monkeypatch):
    managed = tmp_path / "unit.d/zzzz-wp27-current.conf"
    monkeypatch.setattr(p, "MANAGED", managed)
    folder = tmp_path / "run"
    folder.mkdir()
    host = p.Host()
    installed = host.install(folder)
    managed.write_text("intervening operator edit\n")
    with pytest.raises(ValueError, match="drift"):
        host.rollback(folder / "installed.json", {"installed": installed})
    assert managed.read_text() == "intervening operator edit\n"


@pytest.mark.parametrize("bad", [None, "cwd", "pid"])
def test_real_pid_proof_checks_cwd_and_stable_pid_with_proc_fixtures(tmp_path, monkeypatch, bad):
    proc = tmp_path / "proc/321"
    proc.mkdir(parents=True)
    # Fields after comm begin with state (field 3); starttime is field 22.
    (proc / "stat").write_text("321 (launcher) " + " ".join(["S"] + ["0"] * 18 + ["111"] + ["0"] * 8))
    (proc / "cwd").symlink_to(tmp_path / "release")
    original_path = p.Path
    monkeypatch.setattr(p, "Path", lambda value: tmp_path / "proc" if str(value) == "/proc" else original_path(value))
    monkeypatch.setattr(p.time, "sleep", lambda value: None)
    host = p.Host()
    calls = []

    def properties():
        calls.append(True)
        return {"MainPID": "322" if bad == "pid" and len(calls) % 2 == 0 else "321", "ActiveState": "active"}

    monkeypatch.setattr(host, "properties", properties)
    if bad:
        with pytest.raises(ValueError, match="stable active"):
            host.proof(str(tmp_path / ("wrong" if bad == "cwd" else "release")))
    else:
        assert host.proof(str(tmp_path / "release"))["start_ticks"] == "111"


def test_cli_confirmation_cannot_be_piped(monkeypatch):
    monkeypatch.setattr(p.sys.stdin, "isatty", lambda: False)
    with pytest.raises(ValueError, match="operator TTY"):
        p.confirm("INSTALL-CONTINUOUS-CURRENT")


def test_current_change_during_successful_pid_proof_cannot_claim_current_success(monkeypatch):
    host = FakeHost()
    original = host.proof

    def raced_proof(expected):
        result = original(expected)
        host.state["release"]["sha"] = "9" * 40
        return result

    monkeypatch.setattr(host, "proof", raced_proof)
    with pytest.raises(ValueError, match="CURRENT or unit changed"):
        p.apply(host, NOW, p.preview(host, NOW), restart=True)
    assert not any(value.get("status") == "RUNNING_FROM_VERIFIED_CURRENT" for value in host.store.values())
    assert any(value.get("status") == "RUNTIME_PROOF_FAILED" for value in host.store.values())
