"""Staged reader migration: no real provider, ledger, scheduler, or state files."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts import incident_notifier as N

NOW = datetime(2026, 10, 18, 21, tzinfo=timezone.utc)
KEY = "inc-state-compatibility"


def incident():
    return {"key": KEY, "source": "fixture", "item": "notice", "severity": "P1", "detail": "fixture",
            "generation": 2, "detected_at": NOW.isoformat(), "intent_ids": ["intent-current"]}


def delivered_state(tmp_path, schema):
    state = N.load_state(tmp_path / "missing.json")
    messages, _ = N.plan_messages({KEY: incident()}, state, NOW, N.config_from_env({}),
                                 {"as_of": NOW.isoformat(), "by_severity": {"P1": 1}})
    assert len(messages) == 1
    N.apply_result(state, messages[0], NOW)
    state["schema"] = schema
    # These v2 producer fields are intentionally opaque to this staged reader.
    state["notified"][KEY].update({"generation": 2, "provider_message_id": 841,
                                  "intent_ids": ["intent-current"], "future_detail": {"keep": [1, 2]}})
    state["sends_by_day"] = {"2026-10-18": 3}
    state["p1_sends_by_day"] = {"2026-10-18": 2}
    state["source_triggers_by_day"] = {"2026-10-18": {"fixture": 1}}
    state["recording_pending"] = {}
    state["future_state"] = {"opaque": ["preserved", {"acknowledged": True}]}
    return state


@pytest.mark.parametrize("schema", ["IncidentNotifierState@v1", "IncidentNotifierState@v2"])
def test_supported_state_preserves_identity_counters_schema_and_extensions(tmp_path, schema):
    state = delivered_state(tmp_path, schema)
    path = tmp_path / "state.json"
    N.atomic_write_json(path, state)
    loaded = N.load_state(path)
    assert loaded == state, "compatible reader must preserve the producer version and all durable state"
    messages, _ = N.plan_messages({KEY: incident()}, loaded, NOW + timedelta(seconds=60), N.config_from_env({}),
                                 {"as_of": NOW.isoformat(), "by_severity": {"P1": 1}})
    assert not messages, "preserved delivered notice must not be planned again"
    N.atomic_write_json(path, loaded)
    assert N.load_state(path) == state


def test_missing_state_keeps_v1_writer_default(tmp_path):
    state = N.load_state(tmp_path / "missing.json")
    assert state["schema"] == N.STATE_SCHEMA == "IncidentNotifierState@v1"
    assert state["notified"] == {} and state["sends_by_day"] == {}
    assert "recording_pending" not in state


@pytest.mark.parametrize("raw", [
    "", "{", "null", "[]", "{}", '{"schema":"IncidentNotifierState@v3"}',
    '{"schema":"IncidentNotifierState@v1","schema":"IncidentNotifierState@v2"}',
    '{"schema":"IncidentNotifierState@v1","sends_by_day":{"2026-10-18":NaN}}',
    '{"schema":"IncidentNotifierState@v1","unknown":{"value":1e9999}}',
    '{"schema":"IncidentNotifierState@v1","notified":[]}',
    '{"schema":"IncidentNotifierState@v1","notified":{"key":false}}',
    '{"schema":"IncidentNotifierState@v2","recording_pending":[]}',
    '{"schema":"IncidentNotifierState@v1","sends_by_day":{"2026-10-18":true}}',
    '{"schema":"IncidentNotifierState@v1","p1_sends_by_day":{"2026-10-18":-1}}',
    '{"schema":"IncidentNotifierState@v1","source_triggers_by_day":{"2026-10-18":2}}',
    '{"schema":"IncidentNotifierState@v2","notified":{"key":{"notify_count":"bad"}}}',
    '{"schema":"IncidentNotifierState@v1","last_p2_batch_at":"invalid"}',
    '{"schema":"IncidentNotifierState@v2","notified":{"key":{"last_notified_at":"invalid"}}}',
])
def test_invalid_existing_state_refuses_without_overwriting(tmp_path, raw):
    path = tmp_path / "state.json"
    path.write_text(raw)
    refused = False
    try:
        N.load_state(path)
    except ValueError:
        refused = True
    assert refused, "existing invalid or unsupported state must refuse; resetting dedupe state is unsafe"
    assert path.read_text() == raw


def test_v2_pending_recording_roundtrip_is_lossless(tmp_path):
    state = delivered_state(tmp_path, "IncidentNotifierState@v2")
    state["recording_pending"] = {"pending-identity": {"message_id": 842, "message": {"identity": "pending-identity"},
                                                      "provider_succeeded": True, "future": {"a": [1]}}}
    path = tmp_path / "state.json"
    N.atomic_write_json(path, state)
    loaded = N.load_state(path)
    N.atomic_write_json(path, loaded)
    assert N.load_state(path) == state, "opaque pending provider/recorder evidence must survive a reader roundtrip"


def test_older_v1_fields_default_without_promoting_state_version(tmp_path):
    path = tmp_path / "state.json"
    N.atomic_write_json(path, {"schema": "IncidentNotifierState@v1", "notified": {}, "sends_by_day": {}})
    state = N.load_state(path)
    assert state["schema"] == "IncidentNotifierState@v1"
    assert state["p1_sends_by_day"] == {} and state["source_triggers_by_day"] == {}


def test_actual_v1_delivery_and_save_keeps_v1_default(tmp_path, monkeypatch):
    configure_run(monkeypatch, {KEY: incident()})
    sends = []
    receipt = N.run(live=True, root=tmp_path, now=NOW, env={},
                    sender=lambda *_a, **_k: sends.append(True) or {"ok": True, "message_id": 841})
    saved = N.load_state(tmp_path / N.STATE_REL)
    assert sends == [True] and receipt["messages"][0]["status"] == "SENT"
    assert saved["schema"] == "IncidentNotifierState@v1" and saved["notified"][KEY]["notify_count"] == 1
    assert "recording_pending" not in saved


def configure_run(monkeypatch, open_now):
    monkeypatch.setattr(N, "read_fanin", lambda *_: {"status": "OK", "incidents": [], "as_of": NOW.isoformat()})
    monkeypatch.setattr(N, "read_ledger_acks", lambda *_args, **_kw: {"status": "ok", "acked_event_ids": []})
    monkeypatch.setattr(N, "open_incidents", lambda *_: (copy.deepcopy(open_now), []))
    monkeypatch.setattr(N, "alert_path_rows", lambda *_: ([], "fixture"))


@pytest.mark.parametrize("live", [False, True])
def test_v2_state_holds_legacy_worker_without_effect_preview_or_state_write(tmp_path, monkeypatch, live):
    state = delivered_state(tmp_path, "IncidentNotifierState@v2")
    path = tmp_path / N.STATE_REL
    N.atomic_write_json(path, state)
    before = path.read_bytes()
    configure_run(monkeypatch, {KEY: incident()})
    effects = []
    with pytest.raises(N.NotifierStateUnavailable, match="state_requires_v2_worker"):
        N.run(live=live, root=tmp_path, now=NOW + timedelta(seconds=60), env={},
              sender=lambda *_a, **_k: effects.append("send"),
              previewer=lambda *_a, **_k: effects.append("preview"))
    assert effects == [] and path.read_bytes() == before
    assert N.load_state(path) == state


def test_v2_unreconciled_provider_recording_holds_before_effect_or_state_write(tmp_path, monkeypatch):
    state = delivered_state(tmp_path, "IncidentNotifierState@v2")
    state["notified"] = {}
    state["recording_pending"] = {"pending-identity": {"message_id": 842, "message": {"identity": "pending-identity"}}}
    path = tmp_path / N.STATE_REL
    N.atomic_write_json(path, state)
    before = path.read_bytes()
    configure_run(monkeypatch, {KEY: incident()})
    sends = []
    refused = False
    try:
        N.run(live=True, root=tmp_path, now=NOW, env={}, sender=lambda *_a, **_k: sends.append(True) or {"ok": True})
    except ValueError:
        refused = True
    assert refused, "v1 notifier cannot settle a v2 provider-success/recorder-pending outcome"
    assert sends == [] and path.read_bytes() == before


def test_unknown_state_version_stops_actual_run_before_provider_and_save(tmp_path, monkeypatch):
    path = tmp_path / N.STATE_REL
    N.atomic_write_json(path, {"schema": "IncidentNotifierState@v99", "notified": {}})
    before = path.read_bytes()
    configure_run(monkeypatch, {KEY: incident()})
    sends = []
    refused = False
    try:
        N.run(live=True, root=tmp_path, now=NOW, env={}, sender=lambda *_a, **_k: sends.append(True) or {"ok": True})
    except ValueError:
        refused = True
    assert refused, "unsupported state must stop the actual production send path"
    assert sends == [] and path.read_bytes() == before
