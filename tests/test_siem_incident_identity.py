"""Saved alert evidence groups repeats without merging independent incidents."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "siem_identity_under_test", Path(__file__).resolve().parents[1] / "scripts/lib/siem_incident_identity.py"
)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
incident_key = _MODULE.incident_key


def _stop(**changes):
    row = {
        "source_script": "stop_health",
        "alert_type": "strategic_alert",
        "id": 11,
        "raw_text": "ALFA stop covers 12 shares; current price 102.50",
        "parsed_payload": {
            "account": "fixture-account-a",
            "order_id": "fixture-order-a",
            "symbol": "ALFA",
            "condition": "OVERSIZED",
            "broker": "fixture-broker",
        },
    }
    row.update(changes)
    return row


def _log(timestamp="2026-10-05 13:45:10,445", message="[atm] ATM protection pass error: connection already closed"):
    return {
        "source_script": "atm.log",
        "alert_type": "system_health",
        "raw_text": f"DB_CONNECTION: {timestamp} {message}",
    }


def test_repeated_stop_observations_keep_identity_despite_economics_and_prose():
    original = _stop()
    repeated = _stop(id=20, raw_text="ALFA stop covers 15 shares; current price 98.25")
    repeated["parsed_payload"].update(qty=15, current_price=98.25)
    assert incident_key(original) == incident_key(repeated)


def test_persisting_key_does_not_split_new_stop_observations_from_legacy():
    original = _stop()
    repeated = _stop(id=20, raw_text="Updated current price")
    repeated["parsed_payload"]["condition_key"] = incident_key(original)
    assert incident_key(original) == incident_key(repeated)


@pytest.mark.parametrize("field", ["account", "order_id", "symbol", "condition"])
def test_independent_stop_conditions_remain_separate(field):
    original = _stop()
    different = _stop()
    different["parsed_payload"][field] += "-different"
    assert incident_key(original) != incident_key(different)


@pytest.mark.parametrize("field", ["source_script", "alert_type"])
def test_stop_identity_is_source_and_type_scoped(field):
    original = _stop()
    different = _stop(**{field: original[field] + "-different"})
    assert incident_key(original) != incident_key(different)


def test_optional_broker_metadata_does_not_split_legacy_stop_identity():
    original = _stop()
    legacy = _stop()
    legacy["parsed_payload"].pop("broker")
    assert incident_key(original) == incident_key(legacy)


def test_json_object_and_json_string_are_equivalent():
    original = _stop()
    encoded = _stop(parsed_payload=json.dumps(original["parsed_payload"]))
    assert incident_key(original) == incident_key(encoded)


def test_condition_key_groups_non_stop_prose_without_exposing_identity():
    row = _stop(source_script="fixture-monitor", parsed_payload={"condition_key": "fixture-account-a:condition"})
    repeated = {**row, "id": 20, "raw_text": "new observation"}
    key = incident_key(row)
    assert key == incident_key(repeated)
    assert key.startswith("siem:v1:") and len(key) == len("siem:v1:") + 64
    assert "fixture-account-a" not in key
    assert "fixture-order-a" not in key
    assert key != incident_key({**row, "source_script": "other-monitor"})
    assert key != incident_key({**row, "alert_type": "other-type"})


@pytest.mark.parametrize("payload", [None, "{broken", "[]", "null", [], {"condition_key": ""}])
def test_unstructured_or_malformed_payload_preserves_full_text_identity(payload):
    first = _stop(parsed_payload=payload)
    second = _stop(parsed_payload=payload, raw_text="ALFA stop covers 13 shares; current price 102.50")
    assert incident_key(first) != incident_key(second)


@pytest.mark.parametrize("field", ["account", "order_id", "symbol", "condition"])
@pytest.mark.parametrize("invalid", [None, "", " ", [], {}, True])
def test_incomplete_or_invalid_stop_identity_falls_back_conservatively(field, invalid):
    first = _stop()
    second = _stop(raw_text="A distinct observation whose identity is incomplete")
    first["parsed_payload"][field] = invalid
    second["parsed_payload"][field] = invalid
    assert incident_key(first) != incident_key(second)


def test_textless_ambiguous_rows_use_durable_row_identity():
    first = _stop(parsed_payload="bad-json", raw_text="", id=11)
    second = _stop(parsed_payload="bad-json", raw_text=None, id=12)
    assert incident_key(first) != incident_key(second)
    assert incident_key({**first, "alert_uid": "fixture-a"}) != incident_key({**first, "alert_uid": "fixture-b"})


def test_unidentifiable_row_is_refused_instead_of_merging_empty_records():
    with pytest.raises(ValueError, match="requires text, alert_uid, or id"):
        incident_key({"source_script": "fixture", "parsed_payload": {}})


def test_identical_log_error_differing_only_in_embedded_timestamp_is_one_incident():
    assert incident_key(_log()) == incident_key(_log("2026-10-05 14:30:11,004"))


@pytest.mark.parametrize(
    "message",
    [
        "[atm] ATM account reconciliation error: connection already closed",
        "[atm] ATM protection pass error: connection refused",
        "[atm] ATM protection pass error: connection already closed\nDifferent traceback",
    ],
)
def test_log_message_and_context_are_preserved(message):
    assert incident_key(_log()) != incident_key(_log(message=message))


@pytest.mark.parametrize(
    "timestamp",
    ["2026-99-05 13:45:10,445", "2026-10-05 99:45:10,445", "2026-10-05 13:45:10", "yesterday"],
)
def test_unrecognized_or_invalid_timestamp_is_not_removed(timestamp):
    assert incident_key(_log()) != incident_key(_log(timestamp))


def test_timestamp_normalization_does_not_generalize_to_other_sources_or_message_numbers():
    first = {**_log(), "source_script": "fixture-monitor"}
    second = {**_log("2026-10-05 14:30:11,004"), "source_script": "fixture-monitor"}
    assert incident_key(first) != incident_key(second)
    assert incident_key(_log(message="[atm] failure on worker 1")) != incident_key(
        _log(message="[atm] failure on worker 2")
    )


def test_source_type_and_identity_components_cannot_collide_through_delimiters():
    first = _stop(source_script="a:b", alert_type="c", parsed_payload={"condition_key": "d"})
    second = _stop(source_script="a", alert_type="b:c", parsed_payload={"condition_key": "d"})
    assert incident_key(first) != incident_key(second)
