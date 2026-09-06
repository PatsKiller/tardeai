"""Remote (Telegram) operator approval for guard scopes.

Every test here is a refusal case except the two that prove the happy path
works. That ratio is deliberate: this mechanism exists to let an operator
approve from a phone, and the only thing that makes that safe is that it says
no to everything else.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from scripts.lib import guard_remote_approval as gra

# Deliberately synthetic. These exercise allowlist LOGIC; using the operator's
# real chat ids here would put production identifiers in a fixture, which the
# no-hardcoded-values rule forbids and which would also make the test read as
# though it were bound to one deployment.
ALLOWED_CHAT = "1000000001"
ALLOWED = {ALLOWED_CHAT}
OTHER = "1000000002"


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Never touch the real approvals directory."""
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(tmp_path))
    yield


def _mint(scope="git-push", seconds=600, uses=5, reason="ship the header work", **kw):
    return gra.mint_request(scope, seconds=seconds, uses=uses, reason=reason, **kw)


# ── the plaintext code never lands on disk ───────────────────────────────────

def test_the_code_is_never_written_to_disk():
    """If the code is stored, anything that can read the file can approve."""
    req = _mint()
    raw = gra.requests_path().read_text(encoding="utf-8")
    assert req["code"] not in raw
    assert gra.code_fingerprint(req["code"]) in raw


def test_minting_grants_nothing_on_its_own():
    req = _mint()
    assert req["status"] == "PENDING"
    stored = json.loads(gra.requests_path().read_text())["requests"][-1]
    assert stored["status"] == "PENDING"
    assert "code" not in stored


# ── the happy path ───────────────────────────────────────────────────────────

def test_operator_reply_from_an_allowed_chat_approves():
    req = _mint()
    out = gra.verify_and_consume(req["code"], chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED,
                                 telegram={"update_id": 9, "message_id": 4, "from_id": 77,
                                           "from_username": "john", "text": "/approve"})
    assert out["ok"] is True
    r = out["request"]
    assert r["status"] == "APPROVED"
    assert r["scope"] == "git-push"
    # Provenance is the whole point — a grant must be traceable to a message.
    assert r["telegram"]["update_id"] == 9
    assert r["telegram"]["from_id"] == 77


def test_the_grant_is_bound_to_what_was_requested():
    """An agent must not be able to widen the window after the operator agreed."""
    req = _mint(seconds=300, uses=2)
    out = gra.verify_and_consume(req["code"], chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert out["request"]["seconds"] == 300
    assert out["request"]["uses"] == 2


def test_code_is_case_and_whitespace_insensitive():
    """It gets typed by a human on a phone keyboard."""
    req = _mint()
    out = gra.verify_and_consume(f"  {req['code'].lower()} ",
                                 chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert out["ok"] is True


# ── refusals ─────────────────────────────────────────────────────────────────

def test_a_code_is_single_use():
    req = _mint()
    assert gra.verify_and_consume(req["code"], chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)["ok"]
    again = gra.verify_and_consume(req["code"], chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert again["ok"] is False
    assert again["reason"] == "CODE_ALREADY_APPROVED"


def test_a_reply_from_an_unlisted_chat_is_refused_and_burns_the_code():
    """A code that reached the wrong chat is compromised, not merely misdelivered."""
    req = _mint()
    out = gra.verify_and_consume(req["code"], chat_id=OTHER, allowed_chats=ALLOWED)
    assert out["ok"] is False
    assert out["reason"] == "CHAT_NOT_ALLOWED"
    # And it must not still work from the right chat afterwards.
    retry = gra.verify_and_consume(req["code"], chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert retry["ok"] is False


def test_no_allowlist_configured_denies():
    """Unable to tell who is speaking is not a reason to assume it is the operator."""
    req = _mint()
    out = gra.verify_and_consume(req["code"], chat_id=ALLOWED_CHAT, allowed_chats=set())
    assert out["ok"] is False
    assert out["reason"] == "NO_CHAT_ALLOWLIST_CONFIGURED"


def test_an_expired_code_is_refused():
    req = _mint(ttl=1)
    time.sleep(1.1)
    out = gra.verify_and_consume(req["code"], chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert out["ok"] is False
    assert out["reason"] == "CODE_EXPIRED"


def test_an_unknown_code_is_refused():
    _mint()
    out = gra.verify_and_consume("ZZZZZZ", chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert out["ok"] is False
    assert out["reason"] == "UNKNOWN_CODE"


def test_operator_can_explicitly_deny():
    req = _mint()
    out = gra.deny(req["code"], chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert out["ok"] is True
    assert out["request"]["status"] == "DENIED_BY_OPERATOR"
    after = gra.verify_and_consume(req["code"], chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert after["ok"] is False


# ── scopes and windows this mechanism refuses to carry ───────────────────────

@pytest.mark.parametrize("scope", sorted(gra.REMOTE_FORBIDDEN_SCOPES))
def test_dangerous_scopes_cannot_be_requested_remotely(scope):
    with pytest.raises(ValueError, match="never be approved remotely"):
        _mint(scope=scope)


def test_guard_config_is_forbidden_so_remote_approval_cannot_widen_itself():
    """The recursive case. If a phone can widen who may approve from a phone,
    the ceiling is decorative."""
    assert "guard-config" in gra.REMOTE_FORBIDDEN_SCOPES


def test_a_window_longer_than_the_remote_maximum_is_refused():
    with pytest.raises(ValueError, match="exceeds the remote maximum"):
        _mint(seconds=gra.MAX_GRANT_SECONDS + 1)


def test_zero_or_negative_windows_are_refused():
    for bad in (0, -60):
        with pytest.raises(ValueError, match="must be positive"):
            _mint(seconds=bad)


# ── store integrity ──────────────────────────────────────────────────────────

def test_a_second_request_for_a_scope_supersedes_the_first():
    """Two live codes for one scope means the operator cannot tell which they
    are approving."""
    first = _mint(reason="attempt one")
    second = _mint(reason="attempt two")
    stale = gra.verify_and_consume(first["code"], chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert stale["ok"] is False
    assert stale["reason"] == "CODE_ALREADY_SUPERSEDED"
    fresh = gra.verify_and_consume(second["code"], chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert fresh["ok"] is True


def test_a_corrupt_store_refuses_rather_than_rebuilding_empty():
    _mint()
    gra.requests_path().write_text("{not json", encoding="utf-8")
    out = gra.verify_and_consume("ABC123", chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert out["ok"] is False
    assert out["reason"] == "REQUEST_STORE_CORRUPT"
    with pytest.raises(RuntimeError, match="corrupt"):
        _mint()
    # The evidence is left alone rather than silently replaced.
    assert gra.requests_path().read_text(encoding="utf-8") == "{not json"


def test_the_store_is_not_world_readable():
    _mint()
    assert (gra.requests_path().stat().st_mode & 0o077) == 0


# ── the audit this exists to make possible ───────────────────────────────────

def test_unprovenanced_grants_are_detectable():
    """A grant explained by neither a terminal nor a Telegram approval."""
    req = _mint()
    approved = gra.verify_and_consume(req["code"], chat_id=ALLOWED_CHAT,
                                      allowed_chats=ALLOWED)["request"]
    grants = [
        {"tier": "git-push", "origin": "interactive"},
        {"tier": "git-push", "origin": "remote", "remote_request_id": approved["request_id"]},
        {"tier": "release-write", "origin": "remote", "remote_request_id": "made-up"},
        {"tier": "db-write"},
    ]
    odd = gra.unprovenanced_grants(grants)
    assert len(odd) == 2
    assert {g["tier"] for g in odd} == {"release-write", "db-write"}


# ── Approval by BUTTON: the tap is the authority ────────────────────────────
# Requested 2026-09-05. A callback carries no code, and must not need one: the
# lock moves from "knows a secret" to "is the operator", which is what was
# actually wanted. Telegram delivers callback_query with the sender's user id
# from an allowlisted chat, and callbacks originate at Telegram's servers, so
# the bot token cannot fabricate one.

def test_a_button_tap_settles_without_any_code(_isolated_store):
    req = _mint()
    out = gra.settle_by_request_id(req["request_id"], approve=True,
                                   chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED,
                                   telegram={"from_id": 77, "message_id": 4})
    assert out["ok"] is True
    assert out["request"]["status"] == "APPROVED"
    assert out["request"]["settled_via"] == "telegram_button"
    assert out["request"]["telegram"]["from_id"] == 77


def test_a_tap_from_an_unlisted_chat_settles_nothing(_isolated_store):
    req = _mint()
    out = gra.settle_by_request_id(req["request_id"], approve=True,
                                   chat_id=OTHER, allowed_chats=ALLOWED)
    assert out["ok"] is False and out["reason"] == "CHAT_NOT_ALLOWED"
    # and it must remain answerable by the real operator
    good = gra.settle_by_request_id(req["request_id"], approve=True,
                                    chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert good["ok"] is True


def test_a_button_tap_is_single_use(_isolated_store):
    req = _mint()
    assert gra.settle_by_request_id(req["request_id"], approve=True,
                                    chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)["ok"]
    again = gra.settle_by_request_id(req["request_id"], approve=True,
                                     chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert again["ok"] is False
    assert again["reason"] == "REQUEST_ALREADY_APPROVED"


def test_deny_button_grants_nothing(_isolated_store):
    req = _mint()
    out = gra.settle_by_request_id(req["request_id"], approve=False,
                                   chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert out["request"]["status"] == "DENIED_BY_OPERATOR"


def test_an_expired_request_cannot_be_tapped(_isolated_store):
    req = _mint(ttl=1)
    time.sleep(1.1)
    out = gra.settle_by_request_id(req["request_id"], approve=True,
                                   chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert out["ok"] is False and out["reason"] == "REQUEST_EXPIRED"


def test_an_unknown_request_id_settles_nothing(_isolated_store):
    out = gra.settle_by_request_id("deadbeefdeadbeef", approve=True,
                                   chat_id=ALLOWED_CHAT, allowed_chats=ALLOWED)
    assert out["ok"] is False and out["reason"] == "UNKNOWN_REQUEST"


# ── the tailnet link must never carry authority ─────────────────────────────

def test_the_authority_buttons_are_callbacks_not_urls():
    """A URL that approves is approvable by any holder of the link — a preview
    crawler, a prefetch, a forward. And this agent can read the HMAC key, so a
    signed approve-URL would let it walk through its own front door."""
    import guard_request_approval as g

    kb = g._keyboard("abc123")["inline_keyboard"]
    authority = kb[0]
    assert len(authority) == 2
    for btn in authority:
        assert "callback_data" in btn, f"authority button carries a URL: {btn}"
        assert "url" not in btn
    assert authority[0]["callback_data"] == "gapprove:abc123"
    assert authority[1]["callback_data"] == "gdeny:abc123"


def test_any_url_button_is_read_only_and_tls():
    import guard_request_approval as g

    for row in g._keyboard("abc123")["inline_keyboard"]:
        for btn in row:
            if "url" not in btn:
                continue
            assert btn["url"].startswith("https://"), "plaintext link in a chat message"
            for verb in ("approve", "deny", "grant", "token="):
                assert verb not in btn["url"].lower(), (
                    f"tailnet button looks like an action, not a view: {btn['url']}")


def test_callback_data_fits_telegrams_64_byte_limit():
    """A silently truncated callback_data is a button that settles the wrong
    request, or nothing at all."""
    import guard_request_approval as g

    for row in g._keyboard("a" * 16)["inline_keyboard"]:
        for btn in row:
            if "callback_data" in btn:
                assert len(btn["callback_data"].encode("utf-8")) <= 64
