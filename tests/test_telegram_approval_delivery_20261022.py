"""Telegram approvals must reach the ledger, or say plainly why not (2026-10-22).

Operator decision 2026-10-22: sensitive Command Center actions will be confirmed by a Telegram
Approve tap, so the tap -> poller -> request store -> `bin/guard grant` path has to work, and when
it does not the operator and the agent must be able to see where it stopped.

Diagnosis (read-only, 2026-10-22) found the settle path itself working on the served release, and
these defects around it, each pinned here:

1. A request was settled APPROVED *before* `bin/guard grant` ran. When the grant then failed (a
   corrupt or locked ledger, a refused tier, a timeout), the request stayed APPROVED with no grant
   behind it: the button and the code were spent, and the only way left was the keyboard.
   Now a failed grant re-opens the request (PENDING, with the failure recorded) so a second tap or
   `/approve` works once the cause is fixed.
2. The poller logged `callback: gapprove:<id>` whether the tap granted, was refused, or hit an
   unknown request. The outcome is now returned and logged.
3. `bin/guard request` printed `accepted for interrupt delivery` with no message id, so nobody could
   tell a delivered prompt from one that never arrived (request 6ffaff13, 2026-10-21, never got a
   tap). The provider message id is now recorded on the request row and printed.
4. `telegram_reply_processor.poll_updates` (run by recovery-watch.timer at 07:30) is a second
   `getUpdates` consumer for the same bot: the HTTP 409s in the poller log at 07:30:01/07:30:07 on
   2026-10-21 and 2026-10-22, and it re-dispatches callback queries (including gapprove) outside
   the inbound checkpoint. It no longer polls unless explicitly enabled.

COVERS = ["scripts/lib/guard_remote_approval.py", "scripts/telegram_callback_handler.py",
          "scripts/run_telegram_callback_poller.py", "scripts/guard_request_approval.py",
          "scripts/telegram_reply_processor.py"]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib import guard_remote_approval as gra  # noqa: E402

COVERS = ["scripts/lib/guard_remote_approval.py", "scripts/telegram_callback_handler.py",
          "scripts/run_telegram_callback_poller.py", "scripts/guard_request_approval.py",
          "scripts/telegram_reply_processor.py"]


@pytest.fixture
def adir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "approvals"
    d.mkdir(mode=0o700)
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(d))
    monkeypatch.setenv("GUARD_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.delenv("TRADEAI_PROPOSAL_ALERT_CHAT_ID", raising=False)
    return d


def _row(rid: str) -> dict:
    return next(r for r in gra._load()["requests"] if r["request_id"] == rid)


def _failed_grant(*a, **k):
    return SimpleNamespace(returncode=2, stdout="APPROVAL_LEDGER_CORRUPT  state=ZERO_BYTE", stderr="")


def _ok_grant(*a, **k):
    return SimpleNamespace(returncode=0, stdout="grant id: " + "b" * 32 + "\ngranted.", stderr="")


def _tap(handler, rid: str, *, cb_id: str = "cb1"):
    return handler.handle_callback_query({"id": cb_id, "data": f"gapprove:{rid}",
                                          "from": {"id": 42, "username": "op"},
                                          "message": {"chat": {"id": 42}, "message_id": 77}})


# ── 1. a failed grant re-opens the request instead of spending it ──────────────────────────────


def test_a_tap_whose_grant_fails_leaves_the_request_answerable(adir, monkeypatch):
    import telegram_callback_handler as handler
    alerts = []
    monkeypatch.setattr(handler, "answer_callback", lambda cb_id, text, show_alert=False: alerts.append(text))
    monkeypatch.setattr(handler, "send_reply", lambda *a, **k: None)
    req = gra.mint_request("telegram", seconds=600, uses=1, reason="fixture")

    monkeypatch.setattr(subprocess, "run", _failed_grant)
    _tap(handler, req["request_id"])
    row = _row(req["request_id"])
    assert row["status"] == "PENDING", "a grant that failed must not spend the request"
    assert row["last_refusal"]["reason"] == "GRANT_FAILED"
    assert "APPROVAL_LEDGER_CORRUPT" in row["last_refusal"]["detail"]
    assert alerts and "grant failed" in alerts[-1].lower() and "tap approve again" in alerts[-1].lower()

    # The cause is fixed; the same button now works.
    monkeypatch.setattr(subprocess, "run", _ok_grant)
    _tap(handler, req["request_id"], cb_id="cb2")
    assert _row(req["request_id"])["status"] == "APPROVED"
    assert alerts[-1].startswith("Granted telegram")


def test_a_code_whose_grant_fails_leaves_the_code_usable(adir, monkeypatch):
    import run_telegram_callback_poller as poller
    sent = []
    monkeypatch.setattr(poller, "_send_reply", lambda chat, reply_to, text: sent.append(text))
    req = gra.mint_request("telegram", seconds=600, uses=1, reason="fixture")

    monkeypatch.setattr(subprocess, "run", _failed_grant)
    poller._handle_guard_approval({"message_id": 9, "from": {"id": 42}}, f"/approve {req['code']}", "42")
    assert _row(req["request_id"])["status"] == "PENDING"
    assert "grant failed" in sent[-1].lower() and "/approve" in sent[-1]

    monkeypatch.setattr(subprocess, "run", _ok_grant)
    poller._handle_guard_approval({"message_id": 10, "from": {"id": 42}}, f"/approve {req['code']}", "42")
    assert _row(req["request_id"])["status"] == "APPROVED"
    assert sent[-1].startswith("✅ Granted `telegram`")


def test_reopen_is_refused_once_the_request_has_expired(adir, monkeypatch):
    req = gra.mint_request("telegram", seconds=600, uses=1, reason="fixture", ttl=60)
    assert gra.settle_by_request_id(req["request_id"], approve=True, chat_id="42", allowed_chats={"42"})["ok"]
    monkeypatch.setattr(gra, "_now", lambda: req["expires_at"] + 1)
    out = gra.reopen_after_grant_failure(req["request_id"], detail="boom")
    assert out["ok"] is False and out["reason"] == "REQUEST_EXPIRED"
    assert _row(req["request_id"])["status"] == "GRANT_FAILED"


def test_reopen_only_touches_an_approved_request(adir):
    req = gra.mint_request("telegram", seconds=600, uses=1, reason="fixture")
    out = gra.reopen_after_grant_failure(req["request_id"], detail="boom")
    assert out["ok"] is False and out["reason"] == "REQUEST_NOT_APPROVED"
    assert gra.reopen_after_grant_failure("nope", detail="x")["reason"] == "UNKNOWN_REQUEST"


# ── 2. the outcome of a tap is returned (and so loggable), not swallowed ───────────────────────


def test_the_handler_returns_the_outcome_of_a_guard_tap(adir, monkeypatch):
    import telegram_callback_handler as handler
    monkeypatch.setattr(handler, "answer_callback", lambda *a, **k: None)
    monkeypatch.setattr(handler, "send_reply", lambda *a, **k: None)
    monkeypatch.setattr(subprocess, "run", _ok_grant)
    req = gra.mint_request("telegram", seconds=600, uses=1, reason="fixture")
    out = _tap(handler, req["request_id"])
    assert out == {"kind": "guard", "action": "gapprove", "request_id": req["request_id"],
                   "outcome": "GRANTED", "scope": "telegram"}
    again = _tap(handler, req["request_id"], cb_id="cb2")
    assert again["outcome"] == "REFUSED" and again["reason"] == "REQUEST_ALREADY_APPROVED"
    assert _tap(handler, "feedfacefeedface")["reason"] == "UNKNOWN_REQUEST"


def test_the_poller_logs_the_tap_outcome(adir):
    import run_telegram_callback_poller as poller
    line = poller._callback_log_line("gapprove:abc", "42", {"kind": "guard", "outcome": "REFUSED",
                                                             "reason": "ACTIVE_GRANT_EXISTS"})
    assert line == "callback: gapprove:abc from chat=42 -> REFUSED (ACTIVE_GRANT_EXISTS)"
    assert poller._callback_log_line("ptapprove:1", "42", None) == "callback: ptapprove:1 from chat=42"


# ── 3. the request records whether the prompt reached Telegram ─────────────────────────────────


def _run_request(monkeypatch, *argv):
    import guard_request_approval as g
    monkeypatch.setattr(sys, "argv", ["guard_request_approval.py", *argv])
    return g.main()


def test_a_delivered_prompt_records_its_message_id(adir, monkeypatch, capsys):
    import telegram_alert
    monkeypatch.setattr(telegram_alert, "send_telegram", lambda msg, *a, **k: True)
    monkeypatch.setattr(telegram_alert, "last_message_ids", lambda: ["59917"])
    assert _run_request(monkeypatch, "telegram", "--for", "10m", "--uses", "1", "--reason", "probe") == 0
    out = capsys.readouterr().out
    assert "delivered message_id=59917" in out and "accepted" in out.lower()
    row = gra._load()["requests"][-1]
    assert row["delivery"]["message_ids"] == ["59917"] and row["delivery"]["accepted"] is True


def test_an_accepted_but_unconfirmed_prompt_says_so(adir, monkeypatch, capsys):
    import telegram_alert
    monkeypatch.setattr(telegram_alert, "send_telegram", lambda msg, *a, **k: True)
    monkeypatch.setattr(telegram_alert, "last_message_ids", lambda: [])
    assert _run_request(monkeypatch, "telegram", "--for", "10m", "--uses", "1", "--reason", "probe") == 0
    captured = capsys.readouterr()
    assert "UNCONFIRMED" in captured.out
    assert "no Telegram message id" in captured.err
    assert gra._load()["requests"][-1]["delivery"]["message_ids"] == []


# ── 4. one getUpdates consumer ─────────────────────────────────────────────────────────────────


def test_the_reply_processor_does_not_poll_telegram_by_default(monkeypatch):
    import telegram_reply_processor as trp
    monkeypatch.delenv("TELEGRAM_REPLY_PROCESSOR_POLL", raising=False)
    monkeypatch.setattr(trp, "_token", lambda: "fixture-not-a-token")
    monkeypatch.setattr(trp.requests, "get", lambda *a, **k: pytest.fail("a second getUpdates consumer"))
    assert trp.poll_updates() == []


def test_the_reply_processor_polls_only_when_explicitly_enabled(monkeypatch, tmp_path):
    import telegram_reply_processor as trp
    monkeypatch.setenv("TELEGRAM_REPLY_PROCESSOR_POLL", "1")
    monkeypatch.setattr(trp, "_token", lambda: "fixture-not-a-token")
    monkeypatch.setattr(trp, "OFFSET_FILE", tmp_path / ".telegram_offset")
    called = []

    class _Resp:
        def json(self):
            return {"ok": True, "result": []}

    monkeypatch.setattr(trp.requests, "get", lambda *a, **k: called.append(1) or _Resp())
    assert trp.poll_updates() == [] and called == [1]
