"""Release train arming finding 9 (ANCHOR RELEASE_TRAIN_REFUSAL_CODES_20261021): the controller's C9 refusal codes
equal contract revision 3 and the shipped receipt schema, and ``train-claim`` validates requests and receipts with the
shipped validator (``release_train_window_view.validate_request`` / ``validate_receipt``), not a private copy.

Hermetic: the controller test world (tmp git repo, fake GitHub, fake deploy host, temp key/delegation/control under
tmp_path). No network, DB, systemd or broker. psycopg2 is stubbed by the imported controller test module.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_release_train_controller_20261021 import World, put, receipt, request  # noqa: E402
from scripts.lib import release_train_controller as T  # noqa: E402
from scripts.lib import release_train_window_view as WV  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _hermetic_git(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _claim(w, *, status=None, factory=None):
    def default(live):
        return w.controller(live=live)

    return T.process_requests(w.state, factory or default, apply=True, now=lambda: w.clock.t, live_status=status)


def test_refusal_codes_equal_the_receipt_schema_enum():
    schema = WV.load_schema(WV.TRAIN_WINDOW_RECEIPT)
    enum = set(schema["properties"]["refusal"]["properties"]["code"]["enum"])
    assert T.REFUSAL_CODES == enum
    assert {"RECONCILE_REQUIRED", "QUARANTINED_LINEAGE", "CONTROLLER_ERROR", "CONTROLLER_FAILED"} <= T.REFUSAL_CODES
    assert set(T.REFUSAL_MAP.values()) <= T.REFUSAL_CODES
    assert T.FAILED_CODES == {"CONTROLLER_ERROR", "CONTROLLER_FAILED"}


@pytest.mark.parametrize(
    "reason,code",
    [
        ("REFUSED_RECONCILE_FIRST", "RECONCILE_REQUIRED"),
        ("REFUSED_QUARANTINED_LINEAGE", "QUARANTINED_LINEAGE"),
        ("REFUSED_CONTROL_CORRUPT", "CONTROLLER_ERROR"),
        ("REFUSED_MAIN_UNREADABLE", "CONTROLLER_ERROR"),
        ("REFUSED_STOP_LATCHED", "STOP_SET"),
        ("REFUSED_STOP_UNREADABLE", "STOP_UNREADABLE"),
        ("REFUSED_DELEGATION_PAUSED", "DELEGATION_NOT_ACTIVE"),
        ("REFUSED_TRAIN_BUSY", "LOCK_HELD"),
        ("SHADOW_LIVE_MISMATCH", "SHADOW_LIVE_MISMATCH"),
        ("SOMETHING_NEW", "NOT_ARMED"),  # unmapped: fail closed
    ],
)
def test_refusal_code_mapping(reason, code):
    assert T.refusal_code(reason) == code


def test_the_temporary_validator_is_gone_and_the_shared_one_is_used():
    src = (ROOT / "scripts/lib/release_train_controller.py").read_text(encoding="utf-8")
    assert "REQUEST_KEYS_REQUIRED" not in src and "REQUEST_KEYS_OPTIONAL" not in src
    assert "WV.validate_request(" in src and "WV.validate_receipt(" in src
    assert T.REQUEST_ID_RE is WV.REQUEST_ID_RE
    assert T.validate_request(request(), "rtw-20261021-1800-win.json") == []
    assert "request_id disagrees with the file name" in T.validate_request(request(), "other.json")


def _live(w, **over):
    req = request(shadow=False, shadow_reason=None, **over)
    put(w, req)
    return req


def test_reconcile_first_is_reconcile_required(tmp_path):
    w = World(tmp_path)
    d = w.state_dir / "trains" / "rt-20261020-1800-abcdef"
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({"train_id": "rt-20261020-1800-abcdef", "outcome": None}))
    req = _live(w)
    _claim(w, status="ACTIVE")
    r = receipt(w, req["request_id"])
    assert r["state"] == "REFUSED" and r["refusal"]["code"] == "RECONCILE_REQUIRED"
    assert "REFUSED_RECONCILE_FIRST" in r["refusal"]["detail"] and WV.validate_receipt(r) == []


def test_quarantined_lineage_is_quarantined_lineage(tmp_path):
    w = World(tmp_path)
    (w.state_dir / "quarantine.jsonl").write_text(json.dumps({"kind": "quarantine", "sha": w.gh.main}) + "\n")
    req = _live(w)
    _claim(w, status="ACTIVE")
    r = receipt(w, req["request_id"])
    assert r["state"] == "REFUSED" and r["refusal"]["code"] == "QUARANTINED_LINEAGE" and WV.validate_receipt(r) == []


def test_corrupt_control_is_a_failed_controller_error(tmp_path):
    w = World(tmp_path)
    (w.state_dir / "control.json").write_text("{corrupt")
    req = _live(w)
    _claim(w, status="ACTIVE")
    r = receipt(w, req["request_id"])
    assert r["state"] == "FAILED" and r["refusal"]["code"] == "CONTROLLER_ERROR" and r["outcome"] is None
    assert WV.validate_receipt(r) == []


def test_controller_exception_is_a_failed_controller_failed(tmp_path):
    w = World(tmp_path)
    req = request()
    put(w, req)

    def boom(live):
        raise RuntimeError("controller construction failed")

    _claim(w, factory=boom)
    r = receipt(w, req["request_id"])
    assert r["state"] == "FAILED" and r["refusal"] == {"code": "CONTROLLER_FAILED", "detail": "RuntimeError"}
    assert WV.validate_receipt(r) == []


def test_every_receipt_for_a_valid_request_passes_the_shipped_validator(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    w = World(tmp_path, now=datetime(2026, 10, 21, 16, 35, tzinfo=ZoneInfo("America/New_York")))
    req = request()
    put(w, req)
    _claim(w)
    r = receipt(w, req["request_id"])
    assert r["state"] == "COMPLETED" and WV.validate_receipt(r) == []


def test_a_receipt_that_fails_the_contract_becomes_a_failed_controller_error():
    req = request()
    bad = T._receipt(
        req,
        state="COMPLETED",
        mode="simulate",
        now=0.0,
        acknowledged_at="2026-10-21T20:00:00Z",
        outcome="NOT_AN_OUTCOME",
    )
    fixed, errs = T.checked_receipt(bad, request_valid=True)
    assert errs and fixed["state"] == "FAILED" and fixed["refusal"]["code"] == "CONTROLLER_ERROR"
    assert WV.validate_receipt(fixed) == []
    garbage, errs2 = T.checked_receipt(
        T._receipt({}, state="REFUSED", mode="simulate", now=0.0, refusal=T._refusal("INVALID_REQUEST", "x")),
        request_valid=False,
    )
    assert errs2 and garbage["refusal"]["code"] == "INVALID_REQUEST"  # written as built, errors reported


def test_old_packet_text_is_no_longer_stale():
    text = (ROOT / "docs/ops/packets/release-train-20261021/README.md").read_text(encoding="utf-8")
    assert "**(a) C9 codes — RESOLVED" in text and "**(b) Schema and validator — RESOLVED" in text
    assert "Schema and validator files are absent" not in text


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_train_refusal_codes_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_TRAIN_REFUSAL_CODES_20261021"
    assert "tests/test_release_train_refusal_codes_20261021.py" in doc["files"]
