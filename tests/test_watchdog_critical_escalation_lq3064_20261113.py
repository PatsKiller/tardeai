"""LQ-20261113-3064: a cron-watchdog CRIT reaches text + Telegram + email through the governed hub, and sends nothing here.

Every send in this file is a fake. The one test that omits senders forces the hub's live-release guard to False first,
so a default (real) sender is refused; it can never reach a provider.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests._critical_module_loader import load  # noqa: E402

wce = load("watchdog_critical_escalation")
from scripts.lib import critical_channels, critical_delivery, critical_texts  # noqa: E402

CRIT = {"status": "CRIT", "observed_at": "2026-11-13T00:00:00Z", "missed_lane_ids": ["lane-a"],
        "monitor_incidents": [{"id": "wrapper_journal_unavailable", "kind": "MONITOR_BLINDNESS"}]}
CONTACT = {"critical_email_to": "op@example.invalid",
           "critical_sms_email_gateways": [{"address": "0@sms.example.invalid", "label": "x", "verified": True}]}


@pytest.fixture(autouse=True)
def chat(monkeypatch):
    monkeypatch.setenv(critical_delivery.CRITICAL_CHAT_ENV, "placeholder-chat")


def _fakes(log):
    return dict(
        contact=dict(CONTACT), policy=critical_delivery.load_text_allowlist(),
        email_sender=lambda to, subject, body: log.append(("email", to)) or "e1",
        telegram_sender=lambda chat_id, text: log.append(("telegram_critical", text)) or {"ok": True, "message_id": 7, "status": "DELIVERED"},
        text_sender=lambda event, **k: log.append(("text_gateway", event["event_id"])) or {"sent": True},
    )


def test_event_only_for_crit_and_carries_no_address_or_link():
    assert wce.escalation_event({**CRIT, "status": "OK"}) is None
    assert wce.escalation_event({**CRIT, "status": "WARN"}) is None
    ev = wce.escalation_event(CRIT)
    assert ev["alert_class"] == "B9_monitoring_blind" and ev["event_id"].startswith("watchdog-crit-")
    blob = json.dumps(ev)
    assert "@" not in blob and "http" not in blob and "link" not in ev
    assert "wrapper_journal_unavailable" in ev["what"]


def test_event_key_ignores_the_volatile_timestamp_and_test_gets_its_own_id():
    a = wce.escalation_event(CRIT)["event_id"]
    b = wce.escalation_event({**CRIT, "observed_at": "2030-01-01T00:00:00Z"})["event_id"]
    assert a == b
    t = wce.escalation_event({**CRIT, "status": "OK"}, test=True)
    assert t is not None and t["event_id"].startswith("watchdog-test-") and t["what"].startswith("TEST ONLY")


def test_crit_routes_to_all_three_channels_through_the_real_hub():
    log: list = []
    out = wce.escalate(CRIT, **_fakes(log))
    assert out["delivered"] is True and out["status"] == "SENT"
    assert {r["channel"]: r["status"] for r in out["receipts"]} == {
        "telegram_critical": "sent", "email": "sent", "text_gateway": "sent"}
    assert sorted(c for c, _ in log) == ["email", "telegram_critical", "text_gateway"]


def test_the_real_text_formatter_accepts_the_sentence_within_the_cap():
    policy = critical_delivery.load_text_allowlist()
    assert critical_delivery.text_class_allowed(wce.WATCHDOG_ALERT_CLASS, policy)
    for test in (False, True):
        ev = wce.escalation_event(CRIT, test=test)
        text = critical_texts.format_text(ev, max_chars=critical_texts.class_max_chars(policy, ev["alert_class"]))
        assert len(text) <= critical_texts.class_max_chars(policy, ev["alert_class"])
        assert "check cron wrappers" in text and "http" not in text


def test_a_class_the_operator_has_not_allowed_is_not_texted(monkeypatch):
    log: list = []
    policy = critical_delivery.load_text_allowlist()
    policy = {**policy, "classes": {k: ({**v, "enabled": False} if k == "B9_monitoring_blind" else v) for k, v in policy["classes"].items()}}
    kw = {**_fakes(log), "policy": policy}
    out = wce.escalate(CRIT, **kw)
    by = {r["channel"]: r for r in out["receipts"]}
    assert by["text_gateway"]["status"] == "skipped"
    assert by["telegram_critical"]["status"] == "sent" and by["email"]["status"] == "sent"


def test_real_default_senders_are_refused_off_the_live_release(monkeypatch):
    monkeypatch.setattr(critical_channels, "is_live_code_root", lambda *a, **k: False)
    out = wce.escalate(CRIT, contact=dict(CONTACT), policy=critical_delivery.load_text_allowlist())
    assert out["delivered"] is False
    assert {r["status"] for r in out["receipts"]} == {"refused"}


def test_a_hub_fault_becomes_a_receipt_not_a_watchdog_crash():
    def boom(event, **k):
        raise RuntimeError("hub down")
    out = wce.escalate(CRIT, deliver=boom)
    assert out["status"] == "ESCALATION_ERROR" and out["delivered"] is False and out["reason"] == "RuntimeError"


def _due(cfg, prior, *, now=10_000.0, report=CRIT, log=None):
    log = [] if log is None else log
    return wce.escalate_if_due(report, cfg, prior, now_iso="t", now_epoch=now, **_fakes(log)), log


ON = {"critical_escalation": {"enabled": True}, "reminder_seconds": 1800}


def test_gated_off_by_default_and_by_config_sends_nothing():
    for cfg in ({}, {"critical_escalation": {"enabled": False}}, {"critical_escalation": {"enabled": "true"}}):
        (res, _), log = _due(cfg, {})
        assert res["status"] == "DISABLED" and log == []
    shipped = json.loads((ROOT / "config/cron_outage_watchdog.json").read_text())
    assert shipped["critical_escalation"]["enabled"] is False


def test_not_crit_sends_nothing():
    (res, _), log = _due(ON, {}, report={**CRIT, "status": "OK"})
    assert res["status"] == "NOT_REQUIRED" and log == []


def test_enabled_crit_sends_once_then_waits_out_the_reminder_window():
    (res, state), log = _due(ON, {})
    assert res["delivered"] is True and len(log) == 3 and "event" not in res
    assert state["critical_escalation_key"] == wce.escalation_key(CRIT)
    (res2, _), log2 = _due(ON, state, now=10_000.0 + 100)
    assert res2["reason"] == "reminder_window" and log2 == []
    (res3, _), log3 = _due(ON, state, now=10_000.0 + 1801)
    assert res3["delivered"] is True and len(log3) == 3
    other = {**CRIT, "missed_lane_ids": ["lane-b"]}
    (res4, _), log4 = _due(ON, state, now=10_000.0 + 100, report=other)
    assert res4["delivered"] is True and len(log4) == 3  # a new finding bypasses the window


def test_unconfirmed_escalation_is_not_recorded_so_it_retries():
    bad = {**_fakes([]), "email_sender": lambda *a: None, "telegram_sender": lambda *a: None, "text_sender": lambda e, **k: {"sent": False, "reason": "x"}}
    res, state = wce.escalate_if_due(CRIT, ON, {}, now_iso="t", now_epoch=1.0, **bad)
    assert res["delivered"] is False and "critical_escalation_key" not in state


def _run_main(tmp_path, monkeypatch, *, enabled, snapshot_gaps, hub_calls, tg_ok=True):
    cfg = json.loads((ROOT / "config/cron_outage_watchdog.json").read_text())
    cfg["critical_escalation"] = {"enabled": enabled}
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg))
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"events": [], "successes": {}, "collection_gaps": snapshot_gaps}))
    fake_tg = types.ModuleType("telegram_alert")
    fake_tg.send_telegram_outcome = lambda body, **k: {"status": "DELIVERED" if tg_ok else "FAILED", "accepted": tg_ok, "delivered": tg_ok}
    monkeypatch.setitem(sys.modules, "telegram_alert", fake_tg)
    monkeypatch.setattr(critical_channels, "deliver", lambda event, **k: hub_calls.append(event) or critical_channels.Delivery(
        alert_class=event["alert_class"], receipts=[critical_channels.Receipt(c, "sent") for c in critical_channels.CHANNELS]))
    monkeypatch.setattr(sys, "argv", ["cron_outage_watchdog.py", "--run", "--send-alerts", "--config", str(cfg_path),
                                      "--state-root", str(tmp_path), "--snapshot", str(snap)])
    import importlib
    mod = importlib.import_module("scripts.cron_outage_watchdog")
    return mod.main(), json.loads((tmp_path / mod.LATEST).read_text()), json.loads((tmp_path / mod.STATE).read_text())


def test_watchdog_main_escalates_a_crit_to_the_hub_when_enabled(tmp_path, monkeypatch, capsys):
    calls: list = []
    rc, report, state = _run_main(tmp_path, monkeypatch, enabled=True, snapshot_gaps=["journal_unavailable"], hub_calls=calls)
    assert report["status"] == "CRIT" and rc == 1
    assert len(calls) == 1 and calls[0]["alert_class"] == "B9_monitoring_blind"
    assert report["critical_escalation"]["delivered"] is True
    assert state["critical_escalation_key"]


def test_watchdog_main_does_not_escalate_when_gated_off(tmp_path, monkeypatch, capsys):
    calls: list = []
    rc, report, _ = _run_main(tmp_path, monkeypatch, enabled=False, snapshot_gaps=["journal_unavailable"], hub_calls=calls)
    assert report["status"] == "CRIT" and calls == [] and report["critical_escalation"]["status"] == "DISABLED"


def test_watchdog_main_escalates_even_when_the_telegram_p1_failed(tmp_path, monkeypatch, capsys):
    calls: list = []
    _, report, _ = _run_main(tmp_path, monkeypatch, enabled=True, snapshot_gaps=["journal_unavailable"], hub_calls=calls, tg_ok=False)
    assert report["alert_delivery_status"] == "FAILED_OR_UNCONFIRMED" and len(calls) == 1


def test_watchdog_main_does_not_escalate_a_healthy_report(tmp_path, monkeypatch, capsys):
    calls: list = []
    _, report, _ = _run_main(tmp_path, monkeypatch, enabled=True, snapshot_gaps=[], hub_calls=calls)
    assert report["status"] != "CRIT" and calls == []


def _cli(*args):
    return subprocess.run([sys.executable, "-I", str(ROOT / "scripts/watchdog_critical_escalation.py"), *args],
                          capture_output=True, text=True, cwd=ROOT, timeout=60, env={"PATH": "/usr/bin:/bin"})


def test_cli_dry_run_proves_all_three_channels_and_sends_nothing():
    p = _cli("--dry-run")
    assert p.returncode == 0, p.stderr
    doc = json.loads(p.stdout)
    assert doc["all_three"] is True and doc["sent_anything_real"] is False
    assert doc["would_send_channels"] == ["email", "telegram_critical", "text_gateway"]
    assert "example.invalid" in p.stdout and doc["real_text_format_preview"].startswith("ACT NOW")


def test_cli_live_test_without_the_confirmation_refuses_and_sends_nothing():
    p = _cli("--live-test")
    assert p.returncode == 2 and json.loads(p.stdout)["status"] == "REFUSED"
    p = _cli("--live-test", "--confirm", "yes")
    assert p.returncode == 2
    assert _cli("--live-test", "--dry-run", "--confirm", "SEND-ONE-TEST-NOW").returncode == 2


def test_watchdog_main_retries_the_hub_while_the_telegram_p1_is_in_its_reminder_window(tmp_path, monkeypatch, capsys):
    """Review 3064 F1. Tick 1: Telegram confirms, the hub's legs all fail (nothing recorded). Tick 2: the Telegram P1 is
    NOT_REQUIRED (reminder window), yet the hub is retried; once it confirms, tick 3 stays quiet."""
    calls: list = []
    failing = {"on": True}

    def hub(event, **k):
        calls.append(event)
        status = "failed" if failing["on"] else "sent"
        return critical_channels.Delivery(alert_class=event["alert_class"],
                                          receipts=[critical_channels.Receipt(c, status) for c in critical_channels.CHANNELS])
    _, r1, s1 = _run_main(tmp_path, monkeypatch, enabled=True, snapshot_gaps=["journal_unavailable"], hub_calls=[])
    # _run_main installs its own fake hub; replace it with the failing one and run ticks 2 and 3 on the same state root.
    def tick():
        monkeypatch.setattr(critical_channels, "deliver", hub)
        import importlib
        mod = importlib.import_module("scripts.cron_outage_watchdog")
        assert mod.main() in (0, 1)
        return json.loads((tmp_path / mod.LATEST).read_text()), json.loads((tmp_path / mod.STATE).read_text())
    # reset the escalation memory tick 1 wrote (its fake hub succeeded) so the failing hub is what tick 2 meets
    import importlib
    mod = importlib.import_module("scripts.cron_outage_watchdog")
    st = json.loads((tmp_path / mod.STATE).read_text())
    for k in ("critical_escalation_key", "critical_escalated_epoch", "critical_escalated_at"):
        st.pop(k, None)
    (tmp_path / mod.STATE).write_text(json.dumps(st))
    r2, s2 = tick()
    assert r2["notification"]["status"] == "NOT_REQUIRED" and len(calls) == 1          # Telegram quiet, hub still tried
    assert r2["critical_escalation"]["delivered"] is False and "critical_escalation_key" not in s2
    r3, s3 = tick()
    assert len(calls) == 2                                                              # unconfirmed: retried again
    failing["on"] = False
    r4, s4 = tick()
    assert len(calls) == 3 and r4["critical_escalation"]["delivered"] is True and s4["critical_escalation_key"]
    r5, _ = tick()
    assert len(calls) == 3 and r5["critical_escalation"]["reason"] == "reminder_window"


def test_a_malformed_config_is_a_receipt_not_a_crash():
    bad = {"critical_escalation": {"enabled": True}, "reminder_seconds": "not-a-number"}
    res, state = wce.escalate_if_due(CRIT, bad, {"x": 1}, now_iso="t", now_epoch=1.0, **_fakes([]))
    assert res["status"] == "ESCALATION_ERROR" and res["delivered"] is False and state == {"x": 1}


def test_watchdog_main_survives_a_broken_escalation_module(tmp_path, monkeypatch, capsys):
    calls: list = []
    fake = types.ModuleType("scripts.lib.watchdog_critical_escalation")
    def boom(*a, **k):
        raise RuntimeError("boom")
    fake.escalate_if_due = boom
    monkeypatch.setitem(sys.modules, "scripts.lib.watchdog_critical_escalation", fake)
    rc, report, _ = _run_main(tmp_path, monkeypatch, enabled=True, snapshot_gaps=["journal_unavailable"], hub_calls=calls)
    assert rc == 1 and report["status"] == "CRIT" and report["notification"]["delivered"] is True
    assert report["critical_escalation"] == {"status": "ESCALATION_ERROR", "delivered": False, "reason": "RuntimeError"}


def _cli_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_wce_cli_under_test", ROOT / "scripts/watchdog_critical_escalation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_confirm_alone_is_still_a_dry_run_never_a_live_send(monkeypatch, capsys):
    """Review 3064 S1: only --live-test sends. A bare --confirm must take the dry-run branch."""
    cli = _cli_mod()
    monkeypatch.setattr(cli, "live_test", lambda: (_ for _ in ()).throw(AssertionError("live send reached")))
    assert cli.main(["--confirm", cli.CONFIRM]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "dry_run"


def test_live_test_sends_a_test_event_and_only_with_the_exact_confirmation(monkeypatch, capsys):
    """Review 3064 S2: the real-send path must ask for a TEST event. escalate is faked, so nothing is sent."""
    cli = _cli_mod()
    seen: list = []
    import scripts.lib.watchdog_critical_escalation as lib
    monkeypatch.setattr(lib, "escalate", lambda report, **k: seen.append((report, k)) or {"status": "SENT", "delivered": True, "event": None, "receipts": []})
    assert cli.main(["--live-test", "--confirm", "wrong"]) == 2 and seen == []
    assert cli.main(["--live-test", "--confirm", cli.CONFIRM]) == 0
    assert len(seen) == 1 and seen[0][1].get("test") is True
