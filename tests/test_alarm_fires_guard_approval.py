"""The guard approval request must actually reach the operator's transport.

This is a FIRING test, not a routing test: it injects the condition (an agent
asks for a scope), and observes the message arrive at `send_telegram`.

Why that matters more than usual here. The message is the only channel by which
the operator learns a code exists, and the code is deliberately never printed to
stdout and never written to disk. So if this send silently fails, the request is
minted, nothing is approved, and *nobody is told* — the operator sees no prompt
and the agent sees a request id that will simply expire. A quiet failure here is
indistinguishable from an operator who chose not to answer, which is the one
ambiguity this mechanism must not have.

COVERS = ["scripts/guard_request_approval.py"]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["scripts/guard_request_approval.py"]


@pytest.fixture
def sent(tmp_path, monkeypatch):
    """Isolate the approvals store and capture the transport."""
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(tmp_path))
    captured: list[str] = []

    import telegram_alert
    monkeypatch.setattr(telegram_alert, "send_telegram",
                        lambda msg, *a, **k: captured.append(msg) or True)
    return captured


def _run(monkeypatch, *argv):
    import guard_request_approval as g
    monkeypatch.setattr(sys, "argv", ["guard_request_approval.py", *argv])
    return g.main()


def test_the_request_reaches_the_transport(sent, monkeypatch, capsys):
    rc = _run(monkeypatch, "git-push", "--for", "30m", "--uses", "8",
              "--reason", "merge the header work, CI green")
    assert rc == 0
    assert len(sent) == 1, "the operator was never told a code exists"

    msg = sent[0]
    # Everything the operator needs to decide, in the message itself.
    assert "git-push" in msg
    assert "30 min" in msg
    assert "merge the header work, CI green" in msg
    assert "/approve" in msg and "/deny" in msg


def test_the_code_in_the_message_is_the_one_that_works(sent, monkeypatch):
    """A message carrying a code that does not match the stored fingerprint
    would be an approval prompt nobody can answer."""
    from scripts.lib import guard_remote_approval as gra

    _run(monkeypatch, "git-push", "--for", "10m", "--reason", "proof")
    msg = sent[0]

    # Recover the code the operator was shown, exactly as they would read it.
    import re
    m = re.search(r"/approve ([A-Z0-9]{6})", msg)
    assert m, f"no approval code in the message: {msg!r}"
    code = m.group(1)

    assert gra.find_pending(code) is not None, (
        "the code sent to the operator does not match any pending request")
    out = gra.verify_and_consume(code, chat_id="1", allowed_chats={"1"})
    assert out["ok"] is True


def test_the_code_is_not_printed_to_stdout(sent, monkeypatch, capsys):
    """The agent runs this process. If the code appears in its output, the agent
    can read it and approve itself, which is the whole thing we are preventing."""
    import re

    _run(monkeypatch, "git-push", "--for", "10m", "--reason", "proof")
    out = capsys.readouterr()
    code = re.search(r"/approve ([A-Z0-9]{6})", sent[0]).group(1)
    assert code not in out.out
    assert code not in out.err


def test_a_failed_send_is_reported_not_swallowed(tmp_path, monkeypatch, capsys):
    """A send that fails must be loud. Silence here looks exactly like an
    operator who declined to answer."""
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(tmp_path))
    import telegram_alert
    monkeypatch.setattr(telegram_alert, "send_telegram",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network down")))

    rc = _run(monkeypatch, "git-push", "--for", "10m", "--reason", "proof")
    assert rc != 0, "a failed notification must not exit 0"
    err = capsys.readouterr().err
    assert "TELEGRAM SEND FAILED" in err
    assert "Nothing is approved" in err


def test_a_forbidden_scope_never_reaches_the_transport(sent, monkeypatch, capsys):
    """sudo must not even generate an operator prompt — no message, no code."""
    rc = _run(monkeypatch, "sudo", "--for", "10m", "--reason", "nope")
    assert rc == 2
    assert sent == [], "a forbidden scope was announced to the operator anyway"
    assert "REFUSED" in capsys.readouterr().err


# ── An approval prompt is a question, not a notification ────────────────────
# 2026-09-05, live: the first real `bin/guard request` printed
#     [telegram] Suppressed (P1_DIGEST): 🔐 *Approval requested* ...
#     request_id=43c4ff0b6b4bc005 ... telegram=sent
# The router digested it, the operator never saw the code, and this process
# reported "sent". A question with a 15-minute fuse cannot be summarised later,
# and a truthy send_telegram means ACCEPTED, not delivered.

def test_the_approval_prompt_bypasses_the_digest_router(sent, monkeypatch):
    """It must be interrupt-class, like research_lane_health's own alarms."""
    seen = {}

    import telegram_alert

    def capture(msg, *a, **kw):
        seen.update(kw)
        seen["msg"] = msg
        return True

    monkeypatch.setattr(telegram_alert, "send_telegram", capture)
    _run(monkeypatch, "git-push", "--for", "10m", "--reason", "prompt routing")
    assert seen.get("bypass_router") is True, (
        "the approval prompt went through default routing; the alert router "
        "classifies it P1_DIGEST and the operator never sees the code")


def test_it_does_not_claim_delivered_when_it_only_knows_accepted(sent, monkeypatch, capsys):
    """send_telegram documents that True means ACCEPTED, which includes
    archived-for-digest. Reporting that as 'sent' is the confident-and-untrue
    line this whole session has been removing."""
    _run(monkeypatch, "git-push", "--for", "10m", "--reason", "wording")
    out = capsys.readouterr().out
    assert "telegram=sent" not in out, (
        "still reports 'sent' — a weaker word is the honest one here")
    assert "accepted" in out.lower()
