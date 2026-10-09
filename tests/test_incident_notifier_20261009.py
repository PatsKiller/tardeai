"""scripts/incident_notifier.py — the fan-in's human end (N8N maturity B2, 2026-10-09).

Every test uses a tmp state root, a stub sender/previewer and a missing or tmp ledger. Nothing here
reaches the transport, the live token store, the watchdog's send ledger or the real runtime state."""

from __future__ import annotations

import ast
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import incident_notifier as N  # noqa: E402

T0 = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)
ENV = {"TRADEAI_SERVED_SHA": "test-sha"}


def _row(source: str, item: str, sev: str, *, state: str = "ARTIFACT_WRITTEN", event_id: str | None = None) -> dict:
    return {"source": source, "item": item, "severity": sev, "detail": f"{source} ran_at x", "detected_at": T0.isoformat(),
            "idempotency_key": "inc-x", "event_id": event_id or f"evt-incident-fanin-{source}-{item}", "state": state}


def _fanin(root: Path, rows: list[dict], *, as_of: datetime = T0, mode: str = "apply") -> None:
    p = root / N.FANIN_RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    by: dict[str, int] = {}
    for r in rows:
        by[r["severity"]] = by.get(r["severity"], 0) + 1
    p.write_text(json.dumps({"schema": "N8nIncidentFanin@v1", "mode": mode, "as_of": as_of.isoformat(), "open": len(rows),
                             "by_severity": by, "incidents": rows}), encoding="utf-8")


class Capture:
    def __init__(self, ok: bool = True):
        self.calls: list[dict] = []
        self.ok = ok

    def __call__(self, text, **kw):
        self.calls.append({"text": text, **kw})
        return {"ok": self.ok, "message_id": len(self.calls) if self.ok else None, "reason": None if self.ok else "boom"}


def _never(*_a, **_k):
    raise AssertionError("the transport must not be reached")


def _run(tmp_path: Path, *, now: datetime = T0, live: bool = True, sender=None, previewer=None, env=None, ledger=None):
    return N.run(live=live, root=tmp_path, now=now, env={**ENV, **(env or {})}, sender=sender, previewer=previewer,
                 ledger_path=ledger or (tmp_path / "no_ledger.sqlite"))


def _state(tmp_path: Path) -> dict:
    return json.loads((tmp_path / N.STATE_REL).read_text(encoding="utf-8"))


def test_p1_is_sent_immediately_first_and_p3_never(tmp_path):
    _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1"), _row("db_hygiene", "SIZE:x", "P2"),
                      _row("gap_resolution", "cat:3", "P3")])
    cap = Capture()
    rec = _run(tmp_path, sender=cap)
    assert [m["kind"] for m in rec["messages"]] == ["p1", "p2_batch"]
    assert cap.calls[0]["text"].startswith("TRADE AI SYSTEM INCIDENT — P1 (1)")
    assert "MISSING:a.service" in cap.calls[0]["text"]
    assert all("gap_resolution" not in c["text"] for c in cap.calls)
    assert rec["status"] == "OK" and rec["ok"] and rec["schema"] == "IncidentNotification@v1"
    st = _state(tmp_path)
    assert {v["severity"] for v in st["notified"].values()} == {"P1", "P2"}


def test_dedupe_per_incident_for_24h_then_one_reminder(tmp_path):
    _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1")])
    cap = Capture()
    _run(tmp_path, sender=cap)
    for minutes in (5, 60, 23 * 60):
        _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1")], as_of=T0 + timedelta(minutes=minutes))
        rec = _run(tmp_path, now=T0 + timedelta(minutes=minutes), sender=cap)
        assert rec["messages"] == [], minutes
    later = T0 + timedelta(hours=24, minutes=1)
    _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1")], as_of=later)
    rec = _run(tmp_path, now=later, sender=cap)
    assert [m["kind"] for m in rec["messages"]] == ["p1"] and len(cap.calls) == 2


def test_dedupe_key_survives_the_fanin_day_rollover(tmp_path):
    """The fan-in's idempotency_key changes per UTC day; the notifier key is source|item only."""
    a = N.incident_key("runs", "lane:RUN_FAILED")
    assert a == N.incident_key("runs", "lane:RUN_FAILED") and a != N.incident_key("runs", "lane:RUN_TIMEOUT")


def test_escalation_p2_to_p1_notifies_at_once(tmp_path):
    _fanin(tmp_path, [_row("relay", "relay:down", "P2")])
    cap = Capture()
    _run(tmp_path, sender=cap)
    t = T0 + timedelta(minutes=5)
    _fanin(tmp_path, [_row("relay", "relay:down", "P1")], as_of=t)
    rec = _run(tmp_path, now=t, sender=cap)
    assert [m["kind"] for m in rec["messages"]] == ["p1"]


def test_p2_batches_once_per_window_in_one_message(tmp_path):
    rows = [_row("db_hygiene", f"T:{i}", "P2") for i in range(3)]
    _fanin(tmp_path, rows)
    cap = Capture()
    rec = _run(tmp_path, sender=cap)
    assert [m["kind"] for m in rec["messages"]] == ["p2_batch"] and len(rec["messages"][0]["incident_keys"]) == 3
    assert cap.calls[0]["text"].startswith("TRADE AI SYSTEM INCIDENTS — P2 batch (3)")
    # a new P2 ten minutes later waits for the window
    t10 = T0 + timedelta(minutes=10)
    _fanin(tmp_path, [*rows, _row("db_hygiene", "T:new", "P2")], as_of=t10)
    rec = _run(tmp_path, now=t10, sender=cap)
    assert rec["messages"] == [] and rec["p2_batch"]["deferred"] is True
    assert rec["p2_batch"]["next_batch_at"] == (T0 + timedelta(minutes=30)).isoformat()
    # after the window: one batch with only the un-notified incident
    t31 = T0 + timedelta(minutes=31)
    _fanin(tmp_path, [*rows, _row("db_hygiene", "T:new", "P2")], as_of=t31)
    rec = _run(tmp_path, now=t31, sender=cap)
    assert [m["kind"] for m in rec["messages"]] == ["p2_batch"]
    assert rec["messages"][0]["incident_keys"] == [N.incident_key("db_hygiene", "T:new")]
    assert len(cap.calls) == 2


def test_p2_window_does_not_delay_p1(tmp_path):
    _fanin(tmp_path, [_row("db_hygiene", "T:1", "P2")])
    cap = Capture()
    _run(tmp_path, sender=cap)
    t = T0 + timedelta(minutes=2)
    _fanin(tmp_path, [_row("db_hygiene", "T:1", "P2"), _row("db_hygiene", "T:2", "P2"), _row("runs", "executor:stalled", "P1")], as_of=t)
    rec = _run(tmp_path, now=t, sender=cap)
    assert [m["kind"] for m in rec["messages"]] == ["p1"] and rec["p2_batch"]["deferred"]


def test_recovery_message_when_a_notified_incident_clears(tmp_path):
    _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1"), _row("db_hygiene", "T:1", "P2")])
    cap = Capture()
    _run(tmp_path, sender=cap)
    t = T0 + timedelta(minutes=5)
    _fanin(tmp_path, [_row("db_hygiene", "T:1", "P2")], as_of=t)
    rec = _run(tmp_path, now=t, sender=cap)
    assert [m["kind"] for m in rec["messages"]] == ["recovery"]
    assert cap.calls[-1]["text"].startswith("TRADE AI SYSTEM RECOVERED — 1 incident(s)")
    assert "MISSING:a.service" in cap.calls[-1]["text"]
    assert N.incident_key("expected_services", "MISSING:a.service") not in _state(tmp_path)["notified"]
    # nothing further on the next run
    t2 = t + timedelta(minutes=5)
    _fanin(tmp_path, [_row("db_hygiene", "T:1", "P2")], as_of=t2)
    assert _run(tmp_path, now=t2, sender=cap)["messages"] == []


@pytest.mark.parametrize("case", ["missing", "stale", "dry_run_receipt"])
def test_no_usable_input_sends_nothing_and_declares_no_recovery(tmp_path, case):
    _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1")])
    cap = Capture()
    _run(tmp_path, sender=cap)
    t = T0 + timedelta(hours=2)
    if case == "missing":
        (tmp_path / N.FANIN_RECEIPT_REL).unlink()
    elif case == "stale":
        _fanin(tmp_path, [], as_of=T0)                      # empty but 2 h old
    else:
        _fanin(tmp_path, [], as_of=t, mode="dry-run")
    rec = _run(tmp_path, now=t, sender=_never)
    assert rec["messages"] == [] and rec["status"].startswith("NO_INPUT:")
    assert N.incident_key("expected_services", "MISSING:a.service") in _state(tmp_path)["notified"]


def test_daily_cap_withholds_and_keeps_incidents_unnotified(tmp_path):
    _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1"), _row("db_hygiene", "T:1", "P2")])
    cap = Capture()
    rec = _run(tmp_path, sender=cap, env={"TRADEAI_INCIDENT_NOTIFIER_DAILY_CAP": "1"})
    assert [(m["kind"], m["status"]) for m in rec["messages"]] == [("p1", "SENT"), ("p2_batch", "CAPPED")]
    assert rec["cap"] == {"day": "2026-10-09", "used": 1, "limit": 1, "capped": 1}
    assert len(cap.calls) == 1
    st = _state(tmp_path)
    assert N.incident_key("db_hygiene", "T:1") not in st["notified"] and st["last_p2_batch_at"] is None
    # next UTC day the budget resets and the withheld batch goes out
    nxt = datetime(2026, 10, 10, 0, 5, tzinfo=timezone.utc)
    _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1"), _row("db_hygiene", "T:1", "P2")], as_of=nxt)
    rec = _run(tmp_path, now=nxt, sender=cap, env={"TRADEAI_INCIDENT_NOTIFIER_DAILY_CAP": "1"})
    assert [(m["kind"], m["status"]) for m in rec["messages"]] == [("p2_batch", "SENT")]


def test_config_comes_from_env_with_constant_defaults():
    assert N.config_from_env({}) == {"daily_cap": N.DEFAULT_DAILY_CAP, "p2_batch_min": N.DEFAULT_P2_BATCH_MIN,
                                     "dedupe_hours": N.DEFAULT_DEDUPE_HOURS, "max_fanin_age_min": N.DEFAULT_MAX_FANIN_AGE_MIN,
                                     "max_lines": N.DEFAULT_MAX_LINES}
    cfg = N.config_from_env({"TRADEAI_INCIDENT_NOTIFIER_DAILY_CAP": "7", "TRADEAI_INCIDENT_NOTIFIER_P2_BATCH_MIN": "junk",
                             "TRADEAI_INCIDENT_NOTIFIER_DEDUPE_HOURS": "-3"})
    assert cfg["daily_cap"] == 7 and cfg["p2_batch_min"] == N.DEFAULT_P2_BATCH_MIN and cfg["dedupe_hours"] == N.DEFAULT_DEDUPE_HOURS


def test_dry_run_sends_nothing_writes_no_state_and_does_not_suppress_the_live_send(tmp_path):
    _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1"), _row("db_hygiene", "T:1", "P2")])
    previews: list[dict] = []

    def previewer(text, **kw):
        previews.append({"text": text, **kw})
        return {"would_send": False, "reason": "ci_or_interdict"}

    rec = _run(tmp_path, live=False, sender=_never, previewer=previewer)
    assert [(m["kind"], m["status"]) for m in rec["messages"]] == [("p1", "DRY_RUN"), ("p2_batch", "DRY_RUN")]
    assert len(previews) == 2 and rec["mode"] == "dry-run"
    assert not (tmp_path / N.STATE_REL).exists()
    N.write_receipt(tmp_path, rec)
    assert (tmp_path / N.DRY_RUN_RECEIPT_REL).exists()
    assert not (tmp_path / N.RECEIPT_REL).exists() and not (tmp_path / N.HISTORY_REL).exists()
    cap = Capture()
    live = _run(tmp_path, sender=cap)
    assert [m["status"] for m in live["messages"]] == ["SENT", "SENT"] and len(cap.calls) == 2


def test_main_dry_run_never_resolves_the_live_sender(tmp_path, monkeypatch, capsys):
    _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1")], as_of=datetime.now(timezone.utc))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_SERVED_SHA", "test-sha")
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(tmp_path / "no_ledger.sqlite"))
    monkeypatch.setattr(N, "_default_sender", _never)
    monkeypatch.setattr(N, "_default_previewer", lambda: (lambda text, **kw: {"would_send": False, "reason": "stub"}))
    assert N.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would send (p1, DRY_RUN)" in out
    assert not (tmp_path / N.STATE_REL).exists()


def test_failed_send_is_not_marked_notified_and_fails_the_run(tmp_path):
    _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1")])
    rec = _run(tmp_path, sender=Capture(ok=False))
    assert rec["messages"][0]["status"] == "FAILED" and rec["ok"] is False and rec["status"] == "FAILED"
    assert _state(tmp_path)["notified"] == {}
    assert rec["cap"]["used"] == 0


def _ledger(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE receipts (receipt_json TEXT, updated_at TEXT, lane_id TEXT, state TEXT)")
    conn.execute("CREATE TABLE artifact_refs (store_key TEXT, store TEXT, ref TEXT, sha256 TEXT, as_of TEXT)")
    for event_id, state, consumer in rows:
        rec = {"event_id": event_id, "lane_id": "incident-fanin", "state": state, "consumer": consumer,
               "source_project": "trade-ai", "idempotency_key": event_id}
        conn.execute("INSERT INTO receipts VALUES (?,?,?,?)", (json.dumps(rec), T0.isoformat(), "incident-fanin", state))
    conn.commit()
    conn.close()
    return path


def test_operator_ack_in_the_ledger_suppresses_notify_and_is_not_a_recovery(tmp_path):
    a = _row("expected_services", "MISSING:a.service", "P1", event_id="evt-a")
    b = _row("expected_services", "MISSING:b.service", "P1", event_id="evt-b")
    _fanin(tmp_path, [a, b])
    cap = Capture()
    _run(tmp_path, sender=cap)
    led = _ledger(tmp_path / "ledger.sqlite", [("evt-a", "CONSUMED", "operator-telegram"), ("evt-b", "CONSUMED", "recovery-observer")])
    t = T0 + timedelta(hours=25)
    _fanin(tmp_path, [a, b], as_of=t)
    rec = _run(tmp_path, now=t, sender=cap, ledger=led)
    assert rec["ledger_source"] == {"status": "OK", "acked": 1}
    assert rec["acked_keys"] == [N.incident_key("expected_services", "MISSING:a.service")]
    assert [m["kind"] for m in rec["messages"]] == ["p1"]                  # b's 24 h reminder only
    assert rec["messages"][0]["incident_keys"] == [N.incident_key("expected_services", "MISSING:b.service")]


def test_structured_details_never_reach_the_operator(tmp_path):
    row = _row("breach_detector", "lane:NO_OUTPUT", "P1")
    row["detail"] = "{'basis': 'cadence', 'observed': {'detail': '/some/host/path'}}"
    _fanin(tmp_path, [row])
    cap = Capture()
    _run(tmp_path, sender=cap)
    assert "{" not in cap.calls[0]["text"] and "/some/host/path" not in cap.calls[0]["text"]


# --- no CIO-family spoofing -------------------------------------------------------------------------------

SRC = (ROOT / "scripts" / "incident_notifier.py").read_text(encoding="utf-8")


def test_the_sender_receives_only_text_identity_and_kind(tmp_path):
    _fanin(tmp_path, [_row("expected_services", "MISSING:a.service", "P1")])
    cap = Capture()
    _run(tmp_path, sender=cap)
    assert set(cap.calls[0]) == {"text", "identity", "kind"}
    assert cap.calls[0]["identity"].startswith(N.IDENTITY_PREFIX + "p1:")
    assert cap.calls[0]["kind"] == "incident_p1"


def test_the_live_sender_is_the_system_ops_module_and_nothing_else():
    tree = ast.parse(SRC)
    imports = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert ("scripts.lib.autonomy_watchdog.telegram_system", "send_system") in imports
    assert ("scripts.lib.autonomy_watchdog.telegram_system", "preview_send") in imports
    for forbidden in ("telegram_transport", "SendFamily", "deliver_text", "send_message", "TELEGRAM_CIO",
                      "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "cio_telegram", "family=", "chat_id", "api.telegram"):
        assert forbidden not in SRC, forbidden


def test_the_transport_does_not_honour_a_system_claim_from_this_module():
    """SYSTEM_FAMILY_CALLERS is read from source (no import of the transport): only the watchdog's sender
    module is on it, so a SYSTEM_OPS claim made from scripts.incident_notifier would be refused and fall
    back to the OPERATOR (CIO-interdicted) family."""
    tree = ast.parse((ROOT / "scripts" / "telegram_transport.py").read_text(encoding="utf-8"))
    callers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "SYSTEM_FAMILY_CALLERS" for t in node.targets):
            callers = {c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    assert callers == {"scripts.lib.autonomy_watchdog.telegram_system", "lib.autonomy_watchdog.telegram_system"}
    assert not {"scripts.incident_notifier", "incident_notifier", "__main__"} & callers
