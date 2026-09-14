"""A long desk answer reaches the operator. Offline: no network.

2026-09-14 13:47 ET: the operator asked about AXTI and the desk wrote a 4,571-character answer.
- `telegram_transport.send_message` sent it whole.
- Telegram refused it (400, over 4,096 UTF-16 units).
- The plain-text retry was refused the same way.
- The poller logged "replied".
The operator waited 5 minutes for nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import telegram_transport as tx  # noqa: E402
from scripts.lib import cio_poller_reply as cpr  # noqa: E402

COVERS = ["scripts/telegram_transport.py", "scripts/lib/cio_poller_reply.py", "scripts/lib/cio_telegram_transport.py"]

DOSSIER_LINE = "🟢 Trade-AI data · Analysts (Yahoo targets): Buy · 4 analysts · mean target $96.50 · 🟣 model note\n"
AXTI_ANSWER = "Key: 🟢 green · 🔵 blue · 🟣 purple\n*AXTI — house view first*\n" + DOSSIER_LINE * 60 + "READ_ONLY_ADVISORY"


def test_the_axti_answer_would_have_been_refused_whole():
    assert len(AXTI_ANSWER) > 4096 and tx.utf16_len(AXTI_ANSWER) > tx.TELEGRAM_TEXT_LIMIT


def test_split_parts_fit_telegrams_utf16_limit_and_keep_every_line():
    parts = tx.split_for_telegram(AXTI_ANSWER)
    assert len(parts) >= 2
    assert all(tx.utf16_len(p) <= tx.TELEGRAM_TEXT_LIMIT for p in parts)
    assert "".join(parts).count("mean target $96.50") == 60 and parts[-1].endswith("READ_ONLY_ADVISORY")


def test_an_emoji_dense_part_is_resplit():
    dense = "🟢" * 2500  # 2,500 characters, 5,000 UTF-16 units
    parts = tx.split_for_telegram(dense)
    assert len(parts) >= 2 and all(tx.utf16_len(p) <= tx.TELEGRAM_TEXT_LIMIT for p in parts)


def _record_deliveries(fail_on: int | None = None):
    """A private, unpatched copy of the transport.

    tests/conftest.py replaces `telegram_transport.send_message` with a blocker for the whole suite, so the
    real function is loaded from source under another name and only its HTTP layer is faked.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("telegram_transport_under_test", ROOT / "scripts" / "telegram_transport.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = []

    def fake_deliver_text(**kw):
        calls.append(kw)
        ok = fail_on is None or len(calls) != fail_on
        return {"ok": ok, "status_code": 200 if ok else 400, "message_id": 1000 + len(calls) if ok else None}
    mod._interdicted = lambda: False
    mod.deliver_text = fake_deliver_text
    return mod, calls


def test_send_message_sends_a_long_body_as_ordered_parts():
    mod, calls = _record_deliveries()
    res = mod.send_message(token="T", chat_id="1", text=AXTI_ANSWER, parse_mode=None,
                           reply_to_message_id=51807, reply_markup={"inline_keyboard": []})
    assert res["ok"] is True and res["parts"] == len(calls) >= 2 and res["message_id"] == 1001
    assert calls[0]["reply_to_message_id"] == 51807 and all(c["reply_to_message_id"] is None for c in calls[1:])
    assert calls[-1]["reply_markup"] == {"inline_keyboard": []} and all(c["reply_markup"] is None for c in calls[:-1])


def test_a_failed_part_makes_the_whole_send_not_ok():
    mod, calls = _record_deliveries(fail_on=2)
    res = mod.send_message(token="T", chat_id="1", text=AXTI_ANSWER, parse_mode=None)
    assert res["ok"] is False and res["parts_sent"] == 1 and len(calls) == 2


def test_an_idempotent_send_is_never_split():
    mod, calls = _record_deliveries()
    mod.send_message(token="T", chat_id="1", text=AXTI_ANSWER, parse_mode=None, idempotency_key="k")
    assert len(calls) == 1


def test_the_cio_transport_no_longer_truncates():
    src = (ROOT / "scripts" / "lib" / "cio_telegram_transport.py").read_text(encoding="utf-8")
    assert "text=text[:4000]" not in src


class _Transport:
    def __init__(self, ok: bool):
        self.ok = ok

    def send_message(self, **kw):
        return {"ok": self.ok, "status_code": 200 if self.ok else 400, "message_id": 9 if self.ok else None,
                "plain_fallback_reason": None if self.ok else "first_send_failed_code_400"}


def _answer(ok: bool) -> dict:
    def processor(**kw):
        kw["send_fn"](kw["chat_id"], AXTI_ANSWER)
        return {"handled": True, "reason": "answered"}
    env = {cpr.FEATURE_FLAG: "1", cpr.CHATS_ENV: "6993102664"}
    return cpr.maybe_answer({"message_id": 51807, "from": {"id": 6993102664}}, text="Axti swing day trade opinions?",
                            chat_id="6993102664", token="T", env=env, transport=_Transport(ok),
                            capture=lambda *a, **k: None, processor=processor)


def test_the_poller_is_told_when_a_reply_did_not_deliver():
    failed = _answer(False)
    assert failed["answered"] is True and failed["delivered"] is False and failed["delivery_status"] == 400
    assert _answer(True)["delivered"] is True


def test_the_poller_log_line_distinguishes_undelivered_replies():
    src = (ROOT / "scripts" / "run_telegram_callback_poller.py").read_text(encoding="utf-8")
    assert "reply NOT delivered" in src
