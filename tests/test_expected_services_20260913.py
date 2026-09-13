"""A disabled service must be reported. That is the whole point of this gate.

`systemctl --failed` -- what health_agent.py uses -- reports units that FAILED.
`tradeai-cio-telegram.service` was DISABLED on 2026-09-08, which is not failed,
and for five days every reply the operator sent to a CIO alert landed in a room
with no listener. A disabled unit drops out of every "what is running" view, so
the only way to see it is against a written-down expectation.

`check_unit` is pure -- it takes the two systemctl dictionaries as arguments --
so these run with no systemd and no host state.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_expected_services as ces  # noqa: E402

MANIFEST = json.loads((ROOT / "config" / "expected_services.json").read_text())

# Declares to the C1 alarm gate that this file's send_telegram site is exercised.
COVERS = ["scripts/check_expected_services.py"]


# ── the defect this gate exists for ──────────────────────────────────────────


def test_a_disabled_unit_is_reported():
    """The 2026-09-08 cio-telegram case, reproduced exactly."""
    enablement = {"tradeai-cio-telegram.service": "disabled"}
    activity = {"tradeai-cio-telegram.service": "inactive"}
    assert ces.check_unit("tradeai-cio-telegram.service", enablement, activity) == "DISABLED"


def test_a_disabled_unit_is_not_failed_which_is_why_nothing_saw_it():
    """A disabled unit reports `inactive`, never `failed`.

    So it cannot appear in `systemctl --failed`, and health_agent's check is
    structurally incapable of catching it. This asserts the premise of the gate.
    """
    enablement = {"u.service": "disabled"}
    activity = {"u.service": "inactive"}
    assert ces.check_unit("u.service", enablement, activity) != "FAILED"
    assert ces.check_unit("u.service", enablement, activity) == "DISABLED"


def test_a_masked_unit_is_reported_too():
    assert ces.check_unit("u.service", {"u.service": "masked"}, {"u.service": "inactive"}) == "DISABLED"


# ── states that must NOT alarm ───────────────────────────────────────────────


def test_a_waiting_timer_is_healthy():
    """A timer waiting for its next run is ACTIVE=active, SUB=waiting.

    Reading the SUB column instead reported all 57 healthy units as INACTIVE --
    an alarm generator, caught before this shipped.
    """
    assert ces.check_unit("t.timer", {"t.timer": "enabled"}, {"t.timer": "active"}) == "OK"


def test_a_oneshot_service_between_runs_is_healthy():
    """A timer-driven oneshot is *supposed* to be inactive between runs."""
    enablement = {"job.service": "enabled", "job.timer": "enabled"}
    activity = {"job.service": "inactive", "job.timer": "active"}
    assert ces.check_unit("job.service", enablement, activity) == "OK"


def test_a_long_running_service_that_stopped_is_NOT_excused():
    """No paired timer means nothing will restart it. That is an outage."""
    enablement = {"daemon.service": "enabled"}
    activity = {"daemon.service": "inactive"}
    assert ces.check_unit("daemon.service", enablement, activity) == "INACTIVE"


def test_a_waiting_path_unit_is_healthy_and_a_dead_one_is_not():
    assert ces.check_unit("w.path", {"w.path": "enabled"}, {"w.path": "active"}) == "OK"
    assert ces.check_unit("w.path", {"w.path": "enabled"}, {"w.path": "inactive"}) == "INACTIVE"


def test_failed_is_reported():
    assert ces.check_unit("m.service", {"m.service": "enabled"}, {"m.service": "failed"}) == "FAILED"


def test_a_unit_systemd_has_never_heard_of_is_missing():
    assert ces.check_unit("gone.service", {}, {}) == "MISSING"


# ── the manifest itself ──────────────────────────────────────────────────────


def test_manifest_is_non_empty_and_well_formed():
    units = MANIFEST["units"]
    assert units, "an empty manifest checks nothing"
    names = [u["unit"] for u in units]
    assert len(names) == len(set(names)), "duplicate unit entries"
    for n in names:
        assert n.endswith((".service", ".timer", ".path", ".socket")), n


def test_the_unit_this_gate_exists_for_is_declared():
    names = {u["unit"] for u in MANIFEST["units"]}
    assert "tradeai-cio-telegram.service" in names


def test_declared_flags_carry_an_expected_value_and_a_reason():
    flags = MANIFEST.get("flags", [])
    assert flags, "the CIO_REPLY_ENABLED=0 case needs flag coverage"
    for f in flags:
        assert f["expected"], f
        assert f["source"], f
        assert f.get("_why"), f"{f['name']} needs a reason"


def test_cio_reply_enabled_is_declared_because_it_sat_at_zero_for_two_days():
    flags = {f["name"]: f for f in MANIFEST["flags"]}
    assert flags["CIO_REPLY_ENABLED"]["expected"] == "1"


# ── flag reading ─────────────────────────────────────────────────────────────


def test_flag_is_read_from_its_source_file(tmp_path):
    f = tmp_path / "x.env"
    f.write_text("# comment\nOTHER=9\nCIO_REPLY_ENABLED=1\n")
    assert ces._flag_value("CIO_REPLY_ENABLED", str(f)) == "1"


def test_a_flag_set_to_zero_is_read_as_zero_not_as_absent(tmp_path):
    """The actual 09-11 state: present, and set to 0."""
    f = tmp_path / "x.env"
    f.write_text("CIO_REPLY_ENABLED=0\n")
    assert ces._flag_value("CIO_REPLY_ENABLED", str(f)) == "0"


def test_an_exported_flag_is_read(tmp_path):
    f = tmp_path / "x.env"
    f.write_text('export CIO_TELEGRAM_CONVERSE="1"\n')
    assert ces._flag_value("CIO_TELEGRAM_CONVERSE", str(f)) == "1"


def test_a_missing_file_or_key_reads_as_absent(tmp_path):
    assert ces._flag_value("NOPE", str(tmp_path / "nofile.env")) is None
    f = tmp_path / "x.env"
    f.write_text("SOMETHING_ELSE=1\n")
    assert ces._flag_value("NOPE", str(f)) is None


def test_a_prefix_collision_does_not_match(tmp_path):
    f = tmp_path / "x.env"
    f.write_text("CIO_REPLY_ENABLED_EXTRA=0\n")
    assert ces._flag_value("CIO_REPLY_ENABLED", str(f)) is None


@pytest.mark.parametrize("unit", [u["unit"] for u in MANIFEST["units"]])
def test_every_declared_unit_classifies_without_raising(unit):
    ces.check_unit(unit, {}, {})


# ── the alarm itself ─────────────────────────────────────────────────────────


class _Captured:
    def __init__(self):
        self.sent = []

    def send_telegram(self, message, **kwargs):
        self.sent.append(message)
        return True


@pytest.fixture
def wired(monkeypatch, tmp_path):
    cap = _Captured()
    mod = type(sys)("telegram_alert")
    mod.send_telegram = cap.send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    monkeypatch.setattr(ces, "STATE_PATH", tmp_path / "state.json")
    return cap


def test_alarm_fires_and_names_the_disabled_unit(wired):
    ces._alert([{"name": "tradeai-cio-telegram.service", "status": "DISABLED"}])
    assert len(wired.sent) == 1
    body = wired.sent[0]
    assert "tradeai-cio-telegram.service" in body
    assert "DISABLED" in body


def test_a_newly_off_service_escalates_to_an_interrupt(wired):
    """A service going down is not digest material."""
    ces._alert([{"name": "tradeai-sm-render.timer", "status": "INACTIVE"}])
    assert "CRITICAL" in wired.sent[0], (
        "telegram_alert_router routes on CRITICAL; without it a service outage waits up to four hours in a digest."
    )


def test_an_unchanged_off_set_stays_silent(wired):
    ces.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ces.STATE_PATH.write_text(json.dumps({"fingerprint": {"a.service": "FAILED"}}))
    ces._alert([{"name": "a.service", "status": "FAILED"}])
    assert wired.sent == []


def test_recovery_is_reported_once(wired):
    ces.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ces.STATE_PATH.write_text(json.dumps({"fingerprint": {"a.service": "FAILED"}}))
    ces._alert([])
    assert len(wired.sent) == 1 and "\u2705" in wired.sent[0]
    ces._alert([])
    assert len(wired.sent) == 1


def test_a_send_failure_does_not_advance_state(monkeypatch, tmp_path, capsys):
    mod = type(sys)("telegram_alert")

    def _boom(message, **kwargs):
        raise RuntimeError("unreachable")

    mod.send_telegram = _boom
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    monkeypatch.setattr(ces, "STATE_PATH", tmp_path / "s.json")
    ces._alert([{"name": "a.service", "status": "FAILED"}])
    assert "FAILED to send" in capsys.readouterr().err
    assert not ces.STATE_PATH.exists()
