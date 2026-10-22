"""Release-train DIGEST / needs-action notices also go to email, through the communications gateway (2026-10-21).

Operator 2026-10-21 ("email yes"). config/comms_email_mirror.json names the two comms-intent kinds; the incident
notifier, after a live Telegram SENT that carries one of their P2 incidents, sends ONE email with those incidents through
scripts/lib/comms/channel_adapters.send_via_gateway (channel "email"). Never P1, never another kind, never SMTP from
new code, never a recipient read here. Hermetic: tmp state root, stub Telegram sender, stub email sender; the gateway
test stubs send_via_gateway itself, so nothing reaches a provider.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import incident_notifier as N  # noqa: E402
from scripts.lib import n8n_comms_intent_consumption as C  # noqa: E402

T0 = datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc)  # 16:00 ET, outside quiet hours
ENV = {"TRADEAI_SERVED_SHA": "test-sha"}
WF = "tradeai-fabric-release-train"
DIGEST_ITEM = f"fabric.release_train_window_digest:{WF}"
NEEDS_ITEM = f"fabric.release_train_needs_action:{WF}"
REMINDER_ITEM = f"fabric.release_train_delegation_reminder:{WF}"


def _row(source: str, item: str, sev: str) -> dict:
    return {"source": source, "item": item, "severity": sev, "detail": f"{item} detail", "detected_at": T0.isoformat(),
            "idempotency_key": "inc-x", "event_id": f"evt-{source}-{item}", "state": "ARTIFACT_WRITTEN"}


def _fanin(root: Path, rows: list[dict]) -> None:
    p = root / N.FANIN_RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    by: dict[str, int] = {}
    for r in rows:
        by[r["severity"]] = by.get(r["severity"], 0) + 1
    p.write_text(json.dumps({"schema": "N8nIncidentFanin@v1", "mode": "apply", "as_of": T0.isoformat(),
                             "open": len(rows), "by_severity": by, "incidents": rows}), encoding="utf-8")


class Tg:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, text, **kw):
        self.calls.append({"text": text, **kw})
        return {"ok": True, "message_id": len(self.calls)}


class Mail:
    def __init__(self, ok: bool = True):
        self.calls: list[dict] = []
        self.ok = ok

    def __call__(self, subject, body, *, identity):
        self.calls.append({"subject": subject, "body": body, "identity": identity})
        return {"ok": self.ok, "gateway_mode": "ACTIVE", "event_id": "evt-1", "error": None if self.ok else "x"}


def _run(tmp_path: Path, *, live: bool = True, sender=None, email_sender=None, previewer=None):
    return N.run(live=live, root=tmp_path, now=T0, env=ENV, sender=sender, previewer=previewer,
                 ledger_path=tmp_path / "no_ledger.sqlite", email_sender=email_sender)


def test_source_constant_and_config_are_the_two_release_train_kinds():
    assert N.COMMS_INTENT_SOURCE == C.INTENT_SOURCE
    m = N.load_email_mirror()
    assert m["status"] == "ok" and m["severities"] == frozenset({"P2"})
    assert set(m["prefixes"]) == {"fabric.release_train_window_digest:", "fabric.release_train_needs_action:"}
    # both kinds are DIGEST routes of the n8n comms-intent table (so they reach the notifier as P2)
    routes = json.loads((ROOT / "config/n8n_comms_intent_routes.json").read_text())["routes"]
    tiers = {(r["domain"], r["kind"]): r["tier"] for r in routes}
    assert tiers[("fabric", "release_train_window_digest")] == "DIGEST"
    assert tiers[("fabric", "release_train_needs_action")] == "DIGEST"


def test_release_train_digest_and_needs_action_go_to_telegram_and_one_email(tmp_path):
    _fanin(tmp_path, [_row(C.INTENT_SOURCE, DIGEST_ITEM, "P2"), _row(C.INTENT_SOURCE, NEEDS_ITEM, "P2"),
                      _row("db_hygiene", "SIZE:x", "P2")])
    tg, mail = Tg(), Mail()
    rec = _run(tmp_path, sender=tg, email_sender=mail)
    assert [m["kind"] for m in rec["messages"]] == ["p2_batch"] and rec["messages"][0]["status"] == "SENT"
    assert len(tg.calls) == 1 and DIGEST_ITEM in tg.calls[0]["text"]  # Telegram unchanged
    assert len(mail.calls) == 1
    body = mail.calls[0]["body"]
    assert DIGEST_ITEM in body and NEEDS_ITEM in body and "db_hygiene" not in body
    assert mail.calls[0]["identity"] == rec["messages"][0]["identity"]
    assert rec["messages"][0]["email_mirror"]["ok"] is True and rec["messages"][0]["email_mirror"]["incidents"] == 2
    assert rec["email_mirror"] == {"config": "ok", "sent": 1, "failed": 0, "would": 0}


def test_other_kinds_and_p1_are_never_mirrored(tmp_path):
    _fanin(tmp_path, [_row(C.INTENT_SOURCE, REMINDER_ITEM, "P2"), _row("db_hygiene", "SIZE:x", "P2"),
                      _row(C.INTENT_SOURCE, DIGEST_ITEM, "P1"), _row("release_window", "rollback:abc", "P1")])
    tg, mail = Tg(), Mail()
    rec = _run(tmp_path, sender=tg, email_sender=mail)
    assert {m["status"] for m in rec["messages"]} == {"SENT"} and tg.calls
    assert mail.calls == [] and rec["email_mirror"]["sent"] == 0


def test_email_failure_is_recorded_and_never_changes_the_telegram_result(tmp_path):
    _fanin(tmp_path, [_row(C.INTENT_SOURCE, DIGEST_ITEM, "P2")])
    rec = _run(tmp_path, sender=Tg(), email_sender=Mail(ok=False))
    assert rec["ok"] and rec["messages"][0]["status"] == "SENT"
    assert rec["messages"][0]["email_mirror"]["ok"] is False and rec["email_mirror"]["failed"] == 1


def test_injected_telegram_sender_without_email_sender_never_reaches_the_gateway(tmp_path, monkeypatch):
    from scripts.lib.comms import channel_adapters as CA

    monkeypatch.setattr(CA, "send_via_gateway", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gateway")))
    _fanin(tmp_path, [_row(C.INTENT_SOURCE, DIGEST_ITEM, "P2")])
    rec = _run(tmp_path, sender=Tg())
    assert rec["messages"][0]["email_mirror"] == {"incidents": 1, "ok": False, "error": "no_email_sender"}


def test_dry_run_previews_and_sends_nothing(tmp_path):
    _fanin(tmp_path, [_row(C.INTENT_SOURCE, NEEDS_ITEM, "P2")])
    mail = Mail()
    rec = _run(tmp_path, live=False, email_sender=mail,
               previewer=lambda text, **kw: {"would_send": True, "reason": None})
    assert rec["messages"][0]["status"] == "DRY_RUN" and rec["messages"][0]["email_mirror"] == {"would_email": 1}
    assert mail.calls == [] and rec["email_mirror"]["would"] == 1


def test_default_email_sender_goes_through_the_gateway_email_channel(monkeypatch):
    from scripts.lib.comms import channel_adapters as CA

    seen: list[tuple] = []

    def fake(channel, **kw):
        seen.append((channel, kw))
        return {"delivered": True, "gateway_mode": "ACTIVE", "event_id": "e1", "error": None}

    monkeypatch.setattr(CA, "send_via_gateway", fake)
    res = N._default_email_sender()("subj", "body", identity="incident-notifier:abc")
    assert res == {"ok": True, "gateway_mode": "ACTIVE", "event_id": "e1", "error": None}
    (channel, kw), = seen
    assert channel == "email" and kw["deliver"] is True and kw["producer"] == "incident_notifier"
    assert kw["subject"] == "subj" and kw["subject_key"] == "incident-notifier:abc:email"


def test_no_new_smtp_or_recipient_read_and_gateway_enforcement_holds():
    src = (ROOT / "scripts/incident_notifier.py").read_text(encoding="utf-8")
    assert "smtp" not in src.lower()
    assert "REPORT_EMAIL" not in src and "send_email" not in src
    out = subprocess.run([sys.executable, str(ROOT / "scripts/check_comms_gateway_enforcement.py")],
                         capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
