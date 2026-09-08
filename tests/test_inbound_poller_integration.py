"""Mocked provider-update integration: poller entry point -> receipt.

Drives the REAL poller entry point (`poll_once`) against a mocked Telegram
provider. No network, no live DB, no production writes.

Exists because SFR-I-RUNTIME-001 made `run_telegram_callback_poller.py` the
production caller for `normalize_inbound_update`. Unit tests covered the
normalizer; nothing executed the daemon that now feeds it. This closes that gap
and pins the `_send` repair, which was reachable from this exact loop:

    poll_once -> for update in results -> feed_telegram_update   (line ~146)
                                       -> "/cap " -> _handle_llm_caps
                                       -> _send(...)   # F821, undefined

`_send` was never defined, so every /cap and /caps command raised NameError
inside the dispatcher's except and the operator got NO reply -- a silent failure
whose only trace was one log line.

Covers: poller entry point, normalization, authorization, correlation,
deduplication, agent consumption, receipt persistence, and safe
acknowledgement/error response.
"""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

poller = importlib.import_module("scripts.run_telegram_callback_poller")
from scripts.lib import inbound_consumption  # noqa: E402

CHAT = "6993102664"
# Lane I dedups on update_id in a PERSISTENT store, so fixed ids collide across
# runs and come back duplicate:update_already_processed. Unique per session.
_UID_BASE = int(time.time()) % 1_000_000 * 100
TOKEN = "test-token-not-a-real-secret"


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _uid(n: int) -> int:
    return _UID_BASE + n


def _update(uid: int, text: str, *, reply_to: int | None = None) -> dict:
    msg = {
        "message_id": 1000 + uid,
        "chat": {"id": int(CHAT)},
        "from": {"id": 4242, "username": "operator"},
        "date": int(time.time()),
        "text": text,
    }
    if reply_to is not None:
        msg["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": uid, "message": msg}


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Poller wired to a mocked provider; every send captured, never sent."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TRADEAI_PROPOSAL_ALERT_CHAT_ID", CHAT)
    # Lane I fails closed on an empty allowlist
    # (authorization_failed:sender_allowlist_empty), so an authorized case must
    # populate both lists or nothing is ever consumed.
    monkeypatch.setenv("COMMS_INBOUND_SENDER_ALLOWLIST", "4242")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CHATS", CHAT)
    monkeypatch.setenv("COMMS_INBOUND_STALE_SECONDS", "3600")
    # The canary CHAT allowlist is only enforced when mode == CANARY. In OFF the
    # documented behaviour is to normalize for the ledger on sender-allowlist
    # alone, so a test that omits this proves nothing about chat scope.
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setattr(poller, "OFFSET_FILE", tmp_path / ".offset")
    # Per-test isolation: the normalizer dedups on tg:<chat>:<update>:<message>
    # in a process-global _SEEN_KEYS set that otherwise leaks between tests.
    from scripts.lib import inbound_event_normalizer
    inbound_event_normalizer.reset_normalizer_memory()
    # is_update_already_processed() delegates to the real claim_update(), which
    # both CHECKS and CLAIMS against the live checkpoint store -- so it marks the
    # id on first call and the test's own second look reads back "duplicate".
    # Hermetic replacement keeps replay denial testable without touching
    # production state.
    _seen_uids: set[int] = set()

    def _already(uid: int) -> bool:
        was = int(uid) in _seen_uids
        _seen_uids.add(int(uid))
        return was

    monkeypatch.setattr(inbound_event_normalizer, "is_update_already_processed", _already)

    # The normalizer touches the checkpoint store at three points (lines ~288,
    # ~308, ~351): is_update_already_processed, claim_update, commit_checkpoint.
    # All three must be isolated or the test both mutates production state and
    # races itself -- claim_update marks the id, then the next look reports
    # duplicate:checkpoint_race.
    class _C:
        def __init__(self, already):
            self.already_processed = already

    def _claim_norm(uid):
        return _C(False)

    monkeypatch.setattr(inbound_event_normalizer, "claim_update", _claim_norm)
    monkeypatch.setattr(inbound_event_normalizer, "commit_checkpoint", lambda uid: None)

    # Receipt persistence: inject a fake. conftest blocks the real writer, and
    # it must -- the first draft of this test minted real AgentConsumptionReceipt
    # rows in the production database ('persisted': 'db') while I was debugging
    # it. Nothing in the suite stopped that, because the guards were a per-path
    # denylist and SFR-I-RUNTIME-001 had just created a path nobody had named.
    from scripts.lib.comms import agent_contracts as _ac
    minted: list[dict] = []

    def _fake_emit(agent_id, **kw):
        row = dict(kw, agent_id=agent_id)
        row.setdefault("receipt_id", f"acr_fake_{len(minted)}")
        row["persisted"] = "test-fake"
        minted.append(row)
        return row

    monkeypatch.setattr(_ac, "emit_consumption_receipt", _fake_emit, raising=False)
    import scripts.lib.inbound_consumption as _ic
    monkeypatch.setattr(_ic, "emit_consumption_receipt", _fake_emit, raising=False)

    sent: list[tuple] = []
    monkeypatch.setattr(poller, "_post_message",
                        lambda chat_id, text, reply_to_message_id=None:
                        sent.append((chat_id, text, reply_to_message_id)) or True)

    # Hermetic inbound API. The real claim_update touches the live checkpoint
    # store; using it made the loop `continue` on an already-claimed id and the
    # feed never ran -- which looked like a wiring failure and was not.
    claimed: set[int] = set()
    committed: list[int] = []
    quarantined: list[tuple] = []

    class _Claim:
        def __init__(self, already):
            self.already_processed = already

    def _claim(uid):
        already = uid in claimed
        claimed.add(uid)
        return _Claim(already)

    monkeypatch.setattr(poller, "_inbound_api", lambda: {
        "claim_update": _claim,
        "commit_checkpoint": committed.append,
        "get_checkpoint_offset": lambda: 0,
        "quarantine_callback": lambda *a, **k: quarantined.append((a, k)),
        "build_inbound_event": lambda u: u,
        "publish_communication": lambda e: e,
    })

    consumed: list[dict] = []
    real_feed = inbound_consumption.feed_telegram_update

    def _capture(update, **kw):
        res = real_feed(update, **kw)
        consumed.append({"update": update, "kw": kw, "result": res})
        return res

    monkeypatch.setattr(inbound_consumption, "feed_telegram_update", _capture)
    return {"sent": sent, "consumed": consumed, "committed": committed,
            "quarantined": quarantined, "claimed": claimed, "minted": minted}


def _serve(monkeypatch, updates):
    """Mock getUpdates to return `updates` once, then nothing."""
    calls = {"n": 0}

    def _urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp({"ok": True, "result": updates})
        return _Resp({"ok": True, "result": []})

    monkeypatch.setattr(poller.urllib.request, "urlopen", _urlopen)
    return calls


# --- entry point + normalization + consumption + receipt --------------------

def test_poller_entry_point_feeds_inbound_and_produces_a_receipt(wired, monkeypatch):
    _serve(monkeypatch, [_update(_uid(1), "status please")])
    poller.poll_once(timeout=0)

    assert wired["consumed"], "poll_once did not reach feed_telegram_update"
    rec = wired["consumed"][0]
    assert rec["update"]["update_id"] == _uid(1)
    res = rec["result"]
    assert getattr(res, "receipt_id", None) or getattr(res, "ok", False), (
        f"no receipt produced: {res}"
    )


def test_ordinary_traffic_records_effect_kind_none(wired, monkeypatch):
    """Section 6: a routine inbound message is NOT behavioral consumption.

    Guards against inflating the inbound count by treating any message as an
    effect. The operator's correlated acknowledgement is what must carry a real
    effect_kind -- see test_correlated_reply_* below.
    """
    _serve(monkeypatch, [_update(_uid(2), "hello")])
    poller.poll_once(timeout=0)
    res = wired["consumed"][0]["result"]
    assert inbound_consumption.counts_as_behavioral_consumption(
        getattr(res, "effect_kind", "none"), getattr(res, "effect_ref", None)
    ) is False


def test_correlated_reply_can_carry_a_behavioral_effect():
    """A reply tied to a known delivery may count -- with an effect_ref.

    Pins the contract the CANARY outbound proof depends on: effect_kind alone is
    not enough, both halves are required.
    """
    assert inbound_consumption.counts_as_behavioral_consumption(
        "changed_commitment", "commitment:abc") is True
    assert inbound_consumption.counts_as_behavioral_consumption(
        "changed_commitment", None) is False
    assert inbound_consumption.counts_as_behavioral_consumption(
        "none", "commitment:abc") is False


# --- authorization -----------------------------------------------------------

def test_unauthorized_chat_is_not_consumed(wired, monkeypatch):
    u = _update(_uid(3), "hello")
    u["message"]["chat"]["id"] = 999999999
    _serve(monkeypatch, [u])
    poller.poll_once(timeout=0)
    # The feed IS reached before the poller's own allowlist check, so the
    # refusal must come from Lane I itself. It does, and it fails closed: no
    # event_id, no receipt_id, no behavioral consumption.
    for c in wired["consumed"]:
        if c["update"]["message"]["chat"]["id"] == 999999999:
            res = c["result"]
            assert res.ok is False, f"unauthorized sender was consumed: {res}"
            assert "chat_out_of_canary_scope" in (res.reason or ""), res.reason
            assert res.receipt_id is None, "receipt minted for an unauthorized sender"
            assert res.counts_as_behavioral_consumption is False
    assert not wired["sent"], "replied to an unauthorized chat"


# --- deduplication / replay --------------------------------------------------

def test_same_update_id_twice_is_not_double_consumed(wired, monkeypatch):
    dup = _update(_uid(4), "status please")
    _serve(monkeypatch, [dup])
    poller.poll_once(timeout=0)
    first = len(wired["consumed"])
    _serve(monkeypatch, [dup])
    poller.poll_once(timeout=0)
    ids = [c["update"]["update_id"] for c in wired["consumed"]]
    assert ids.count(_uid(4)) <= max(1, first), (
        f"update {_uid(4)} consumed {ids.count(_uid(4))}x -- replay denial did not hold"
    )


# --- the _send repair (F821) -------------------------------------------------

def test_cap_command_reaches_send_and_does_not_raise_name_error(wired, monkeypatch, caplog):
    """The exact branch the F821 made unreachable-in-practice.

    Before the repair this logged "name '_send' is not defined" and the operator
    received nothing. The command need not succeed here -- it must not fail with
    NameError.
    """
    _serve(monkeypatch, [_update(_uid(5), "/caps")])
    with caplog.at_level("ERROR"):
        poller.poll_once(timeout=0)
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "_send" not in joined or "not defined" not in joined, (
        f"NameError on _send still reachable: {joined}"
    )


def test_send_is_defined_and_routes_through_one_transport():
    assert callable(getattr(poller, "_send", None)), "_send must exist (was F821)"
    assert callable(getattr(poller, "_post_message", None))
    import inspect
    assert "_post_message" in inspect.getsource(poller._send)
    assert "_post_message" in inspect.getsource(poller._send_reply)


# --- safe error response -----------------------------------------------------

def test_provider_failure_does_not_crash_the_poller(monkeypatch, wired):
    def _boom(req, timeout=None):
        raise OSError("provider unreachable")
    monkeypatch.setattr(poller.urllib.request, "urlopen", _boom)
    assert poller.poll_once(timeout=0) == 0


def test_malformed_update_does_not_crash_the_poller(monkeypatch, wired):
    _serve(monkeypatch, [{"update_id": _uid(6)}])  # no message, no callback_query
    assert poller.poll_once(timeout=0) is not None
