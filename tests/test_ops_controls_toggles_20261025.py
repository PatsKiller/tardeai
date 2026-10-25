"""Ops -> Controls toggles (2026-10-25): ANCHOR OPS_CONTROLS_TOGGLES_20261025.

Operator 2026-10-25 (verbatim): "this should have just been a toggle to turn on/off on the control ops."

Hermetic: in-memory store, fake host runner, temp projection / receipt files, a fake test-send transport. No real
send, no real .env, no host file under ~/.config/tradeai is read (the projection and receipt paths are temp files).

Proves: the three env-backed catalog entries (ENABLE_SMS, OPERATOR_SMS_EMAIL, COMMS_GATEWAY_MODE) are managed,
non-secret and risky (passkey + phrase through the host applier, AGENTS.md §27.2-§27.3); the SMS address validator;
the phone number is masked in previews, state, history and notifications; the applier writes the env projection
atomically and reads it back; consumers read projection > environment > default (comms mode, and the SMS keys through
sync_environ, which restores what it changed and never touches names it did not set); unset falls back; drift is
reported; the test-send route is operator-only, CSRF-checked, needs confirm, idempotent, cooldown-limited and audited;
the overlay's environment reads are literal names only.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import test_ops_controls_20261022 as B  # noqa: E402
from test_ops_controls_20261022 import env  # noqa: E402,F401 — the shared hermetic fixture

from scripts.lib import ops_env_overlay as OV  # noqa: E402
from scripts.lib.comms import mode as MODE  # noqa: E402

API, C = B.API, B.C
post, get, idem, risky, run_applier, enroll_passkey = B.post, B.get, B.idem, B.risky, B.run_applier, B.enroll_passkey

PHONE = "5551234567@msg.fi.google.com"
ENV_NAMES = ("COMMS_GATEWAY_MODE", "ENABLE_SMS", "OPERATOR_SMS_EMAIL")


@pytest.fixture()
def tenv(env, tmp_path, monkeypatch):
    proj = tmp_path / "ops" / "operator_settings_env.json"
    receipt = tmp_path / "incident_notifier_last.json"
    e = env
    e.cfg["settings_projection"] = {"file": str(proj)}
    e.cfg["toggles"] = {"test_send_cooldown_s": 60, "notifier_receipt": str(receipt)}
    sent: list = []

    def fake_sender(channel, subject, body, rid):
        sent.append((channel, subject, body, rid))
        return {"ok": True, "delivered": True, "gateway_mode": "CANARY", "event_id": "ev-" + rid}

    e.ctx.test_sender = fake_sender
    e.sent, e.proj, e.receipt = sent, proj, receipt
    monkeypatch.setattr(OV, "PATH_OVERRIDE", proj)
    for n in ENV_NAMES:
        monkeypatch.delenv(n, raising=False)
    OV._applied.clear()
    yield e
    OV._applied.clear()


def _row(state, key):
    return [r for r in state["settings"]["rows"] if r["key"] == key][0]


# ── catalog ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_catalog_env_keys_are_managed_non_secret_and_wired():
    cfg = C.load_config()
    env_rows = [e for e in cfg["settings_catalog"] if e.get("env_key")]
    assert sorted(e["env_key"] for e in env_rows) == sorted(ENV_NAMES)
    for e in env_rows:
        assert e["env_key"] in OV.MANAGED and not OV.is_secret_name(e["env_key"]) and e["wired"] is True
    gm = [e for e in env_rows if e["env_key"] == "COMMS_GATEWAY_MODE"][0]
    assert gm["choices"] == ["OFF", "CANARY", "ACTIVE"]
    assert C.KINDS["setting.set"].direction == C.RISKY and C.KINDS["setting.set"].executor == C.EXEC_APPLIER
    assert cfg["settings_projection"]["file"].endswith("data/ops/operator_settings_env.json")


@pytest.mark.parametrize("name", ["TELEGRAM_BOT_TOKEN", "SMTP_PASSWORD", "TWILIO_AUTH_TOKEN", "OPENAI_API_KEY", "DB_DSN"])
def test_secret_names_are_refused_by_render(name):
    assert OV.is_secret_name(name)
    with pytest.raises(ValueError):
        OV.render({"k": {"active": True, "value": "x"}}, [{"key": "k", "type": "string", "env_key": name}])


def test_unmanaged_name_refused_by_render():
    with pytest.raises(ValueError):
        OV.render({"k": {"active": True, "value": "x"}}, [{"key": "k", "type": "string", "env_key": "PATH"}])


# ── validation and masking ──────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,ok", [
    (PHONE, True), ("5551234567@VTEXT.com", True), (" 5551234567@tmomail.net ", True), ("5551234567@txt.att.net", True),
    ("555123456@vtext.com", False), ("55512345678@vtext.com", False), ("555-123-4567@vtext.com", False),
    ("5551234567@gmail.com", False), ("5551234567@vtext.com.evil.io", False), ("john@vtext.com", False), ("", False),
])
def test_sms_address_validator(raw, ok):
    entry = C.catalog_entry(C.load_config(), "comms.sms.operator_email")
    if ok:
        assert C.coerce_setting(entry, raw) == raw.strip().lower()
    else:
        with pytest.raises(C.OpsError) as ei:
            C.coerce_setting(entry, raw)
        assert ei.value.code == "SETTING_VALUE_INVALID"


def test_gateway_mode_refuses_values_outside_off_canary_active(tenv):
    enroll_passkey(tenv)
    for bad in ("SHADOW", "on", "", None):
        st, b = post(tenv, "/requests", {"kind": "setting.set", "params": {"key": "comms.gateway_mode", "value": bad},
                                        "idempotency_key": idem()})
        assert st == 400 and b["error"] == "SETTING_VALUE_INVALID", (bad, b)


def test_risky_toggle_needs_passkey_and_phrase(tenv):
    enroll_passkey(tenv)
    st, b = post(tenv, "/requests", {"kind": "setting.set", "params": {"key": "comms.sms.enabled", "value": True},
                                    "idempotency_key": idem()})
    assert st == 200 and b["request"]["status"] == "AWAITING_STEP_UP"
    assert b["request"]["phrase"].startswith("SET comms.sms.enabled ")
    rid = b["request"]["request_id"]
    st, b = post(tenv, f"/requests/{rid}/approve", {})
    assert st == 403 and b["error"] == "STEP_UP_REQUIRED"
    st, b = post(tenv, "/requests", {"kind": "setting.set", "params": {"key": "comms.sms.enabled", "value": True},
                                    "idempotency_key": idem(), "one_click": True})
    assert b["request"]["status"] == "AWAITING_STEP_UP" and "one_click ignored" in b["note"]
    assert not tenv.proj.exists()


# ── apply → projection → consumers ──────────────────────────────────────────────────────────────────────────────────


def test_set_sms_address_masks_everywhere_and_projects(tenv):
    enroll_passkey(tenv)
    st, b = post(tenv, "/requests", {"kind": "setting.set", "params": {"key": "comms.sms.operator_email",
                                                                      "value": PHONE}, "idempotency_key": idem()})
    pv = b["request"]["preview"]
    blob = json.dumps(pv)
    assert "5551234567" not in blob and "4567@msg.fi.google.com" in blob
    rid = risky(tenv, "setting.set", {"key": "comms.sms.operator_email", "value": PHONE})
    run_applier(tenv)
    r = tenv.store.get_request(rid)
    assert r["status"] == "APPLIED", r.get("result")
    assert r["result"]["verify"]["projection"]["ok"] is True
    doc = json.loads(tenv.proj.read_text())
    assert doc["schema"] == OV.SCHEMA and doc["values"] == {"OPERATOR_SMS_EMAIL": PHONE}
    assert doc["settings"]["OPERATOR_SMS_EMAIL"]["updated_by"]
    assert oct(tenv.proj.stat().st_mode & 0o777) == "0o600"
    st, state = get(tenv, "/state")
    row = _row(state, "comms.sms.operator_email")
    assert row["effective"] == {"value": "••••••4567@msg.fi.google.com", "source": "operator_setting"}
    assert row["current"] == "••••••4567@msg.fi.google.com" and row["updated_by"] and row["updated_at"]
    assert state["settings"]["projection"]["state"] == "OK" and state["settings"]["projection"]["drift"] == []
    hist = json.dumps(state["settings"]["history"])
    assert "5551234567" not in hist
    assert all("5551234567" not in str(n) for n in tenv.notes)
    audit = json.dumps([a for a in tenv.store.list_audit(500)], default=str)
    assert "5551234567@" not in audit.replace(json.dumps(PHONE), "")  # the value appears only in the params


def test_projection_drives_sms_env_and_restores_on_unset(tenv, monkeypatch):
    monkeypatch.setenv("ENABLE_SMS", "false")
    enroll_passkey(tenv)
    risky(tenv, "setting.set", {"key": "comms.sms.enabled", "value": True})
    run_applier(tenv)
    assert OV.value("ENABLE_SMS") == "true" and OV.value("OPERATOR_SMS_EMAIL") is None
    assert OV.sync_environ() == {"ENABLE_SMS": "true"}
    assert os.environ["ENABLE_SMS"] == "true"
    assert "OPERATOR_SMS_EMAIL" not in os.environ and "COMMS_GATEWAY_MODE" not in os.environ  # untouched
    assert OV.baseline("ENABLE_SMS") == "false"
    st, state = get(tenv, "/state")
    assert _row(state, "comms.sms.enabled")["effective"]["source"] == "operator_setting"
    risky(tenv, "setting.unset", {"key": "comms.sms.enabled"})
    run_applier(tenv)
    assert json.loads(tenv.proj.read_text())["values"] == {}
    OV.sync_environ()
    assert os.environ["ENABLE_SMS"] == "false"      # the environment's own value is back
    st, state = get(tenv, "/state")
    assert _row(state, "comms.sms.enabled")["effective"] == {"value": "false", "source": "environment"}


def test_sync_never_touches_names_it_did_not_set(tenv, monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "SHADOW")
    OV.write_projection(tenv.proj, OV.render({}, []))
    OV.sync_environ()
    assert os.environ["COMMS_GATEWAY_MODE"] == "SHADOW"
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")   # someone else changes it later: still not ours
    OV.sync_environ()
    assert os.environ["COMMS_GATEWAY_MODE"] == "CANARY"


def test_gateway_mode_precedence_projection_env_default(tenv, monkeypatch):
    assert MODE.resolve_mode(refresh=True) == ("OFF", "default_off")
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "SHADOW")
    assert MODE.resolve_mode(refresh=True) == ("SHADOW", "env:COMMS_GATEWAY_MODE")
    enroll_passkey(tenv)
    risky(tenv, "setting.set", {"key": "comms.gateway_mode", "value": "CANARY"})
    run_applier(tenv)
    assert MODE.resolve_mode(refresh=True) == ("CANARY", "ops_setting:comms.gateway_mode")
    risky(tenv, "setting.set", {"key": "comms.gateway_mode", "value": "OFF"})
    run_applier(tenv)
    assert MODE.resolve_mode(refresh=True) == ("OFF", "ops_setting:comms.gateway_mode")   # OFF wins over env SHADOW
    risky(tenv, "setting.unset", {"key": "comms.gateway_mode"})
    run_applier(tenv)
    assert MODE.resolve_mode(refresh=True) == ("SHADOW", "env:COMMS_GATEWAY_MODE")


def test_unreadable_projection_falls_back_to_environment(tenv, monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    tenv.proj.parent.mkdir(parents=True, exist_ok=True)
    tenv.proj.write_text("{not json")
    assert OV.read_projection()["state"] == "INVALID"
    assert MODE.resolve_mode(refresh=True) == ("CANARY", "env:COMMS_GATEWAY_MODE")
    tenv.proj.write_text(json.dumps({"schema": OV.SCHEMA, "values": {"PATH": "/evil", "COMMS_GATEWAY_MODE": "ACTIVE"}}))
    assert OV.read_projection()["values"] == {"COMMS_GATEWAY_MODE": "ACTIVE"}   # unmanaged names are ignored
    assert "PATH" not in OV.sync_environ()


def test_drift_is_reported(tenv):
    enroll_passkey(tenv)
    risky(tenv, "setting.set", {"key": "comms.gateway_mode", "value": "CANARY"})
    run_applier(tenv)
    tenv.proj.write_text(json.dumps(OV.render({}, [])))
    st, state = get(tenv, "/state")
    pj = state["settings"]["projection"]
    assert pj["drift"] == ["COMMS_GATEWAY_MODE"] and "differs" in pj["reason"]


def test_projection_write_failure_is_failed_not_applied(tenv, monkeypatch):
    enroll_passkey(tenv)
    rid = risky(tenv, "setting.set", {"key": "comms.sms.enabled", "value": True})
    monkeypatch.setattr(OV, "write_projection", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    run_applier(tenv)
    r = tenv.store.get_request(rid)
    assert r["status"] == "FAILED" and "projection was not written" in r["result"]["detail"]
    assert tenv.store.setting_get("comms.sms.enabled")["value"] is True   # stored; the page says consumers lag


# ── test send ───────────────────────────────────────────────────────────────────────────────────────────────────────


def _send(e, **body):
    return post(e, "/test-send", {"channel": "sms", "confirm": True, "idempotency_key": idem(), **body})


def test_test_send_is_operator_only_and_csrf_checked(tenv):
    tenv.who["principal"] = "service-token"
    st, b = _send(tenv)
    assert st == 403 and b["error"] == "AGENT_CALLER_REFUSED"
    tenv.who.update(principal=B.OP, listener="loopback")
    st, b = _send(tenv)
    assert st == 403 and b["error"] == "AGENT_CALLER_REFUSED"
    tenv.who.update(listener="serve_proxy", csrf=(False, "origin mismatch"))
    st, b = _send(tenv)
    assert st == 403 and b["error"] == "CSRF_REFUSED"
    assert tenv.sent == []


def test_test_send_needs_confirm_channel_and_key(tenv):
    assert _send(tenv, confirm=False)[1]["error"] == "CONFIRM_REQUIRED"
    assert _send(tenv, confirm="yes")[1]["error"] == "CONFIRM_REQUIRED"
    assert _send(tenv, channel="telegram")[1]["error"] == "CHANNEL_INVALID"
    assert post(tenv, "/test-send", {"channel": "sms", "confirm": True})[1]["error"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert tenv.sent == []


def test_test_send_once_per_cooldown_idempotent_and_audited(tenv):
    key = idem()
    st, b = _send(tenv, idempotency_key=key)
    assert st == 200 and b["result"]["delivered"] is True and b["result"]["gateway_mode"] == "CANARY"
    st, b2 = _send(tenv, idempotency_key=key)
    assert b2.get("replayed") is True and b2["result"] == b["result"]
    st, b3 = _send(tenv)
    assert st == 429 and b3["error"] == "TEST_SEND_COOLDOWN"
    st, b4 = _send(tenv, channel="email")
    assert st == 200
    tenv.clock.advance(61)
    assert _send(tenv)[0] == 200
    assert [s[0] for s in tenv.sent] == ["sms", "email", "sms"]
    actions = [a["action"] for a in tenv.store.list_audit(100)]
    assert actions.count("test_send.sent") == 3 and "refused.test_send_cooldown" in actions
    st, state = get(tenv, "/state")
    assert state["toggles"]["last_test"]["sms"]["delivered"] is True


def test_test_send_failure_is_reported_not_raised(tenv):
    tenv.ctx.test_sender = lambda *a: (_ for _ in ()).throw(RuntimeError("smtp down"))
    st, b = _send(tenv)
    assert st == 200 and b["result"]["delivered"] is False and "smtp down" in b["result"]["error"]
    assert "test_send.not_sent" in [a["action"] for a in tenv.store.list_audit(50)]


def test_default_sender_reports_missing_channel_without_sending(monkeypatch):
    from scripts.lib.comms import channel_adapters as CA

    monkeypatch.setattr(CA, "SUPPORTED_CHANNELS", frozenset({"email", "telegram"}))
    monkeypatch.setattr(CA, "send_via_gateway", lambda *a, **k: pytest.fail("must not send"))
    r = API.gateway_test_send("sms", "s", "b", "opstest_x")
    assert r["delivered"] is False and r["error"].startswith("CHANNEL_NOT_DEPLOYED")


def test_toggles_view_reports_notifier_evidence(tenv):
    tenv.receipt.write_text(json.dumps({"as_of": "2026-10-25T18:00:00Z", "mode": "live",
                                       "email_mirror": {"config": "ok", "sent": 0, "failed": 1, "would": 0},
                                       "messages": [{"email_mirror": {"ok": False, "gateway_mode": "OFF"}}]}))
    st, state = get(tenv, "/state")
    n = state["toggles"]["notifier"]
    assert n["state"] == "OK" and n["gateway_modes_seen"] == ["OFF"] and n["email_mirror"]["failed"] == 1
    tenv.receipt.unlink()
    st, state = get(tenv, "/state")
    assert state["toggles"]["notifier"]["state"] == "UNAVAILABLE"


def test_lane_toggles_reuse_the_governed_live_list_kinds(tenv):
    """Per-lane live/dry is n8n_live_list.add/remove: risky, applied by the host applier with a backup and the relay
    restart (systemctl --user restart tradeai-n8n-run-relay.service) from config live_list.restart_units."""
    assert "tradeai-n8n-run-relay.service" in tenv.cfg["live_list"]["restart_units"]
    enroll_passkey(tenv)
    rid = risky(tenv, "n8n_live_list.add", {"lane_id": "lane-c"})
    run_applier(tenv)
    assert tenv.store.get_request(rid)["status"] == "APPLIED"
    assert "lane-c" in tenv.live.read_text()
    assert ["systemctl", "--user", "restart", "tradeai-n8n-run-relay.service"] in tenv.host.calls


# ── static rails ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_overlay_env_reads_are_literal_managed_names_only():
    import test_n8n_executor_env_allowlist_20261009 as P7

    reads = P7._env_reads(ROOT / "scripts/lib/ops_env_overlay.py", set())
    assert reads == set(ENV_NAMES)
    text = (ROOT / "scripts/lib/ops_env_overlay.py").read_text(encoding="utf-8")
    assert "load_dotenv" not in text and ".tenv" not in text.replace("``.tenv``", "").replace("(.tenv)", "") \
        .replace(". ./.tenv", "").replace("into ``.tenv``", "")
