"""The pending-reply pass must not drain the operator's daily model cap (operator-approved 2026-10-10).

Measured 2026-10-10 (read-only): llm_cost_reservations shows 400 settled cio_operator_reply requests on
each of 10-05..10-10, spent between 00:00 and ~03:30 ET by the background pass
try_fulfill_pending_replies (cio_telegram_bot --loop, every third poll). The pending ledger holds 7 open
rows (oldest 2026-10-05). All 7 have chat_id == "" (opened by a caller with no chat, e.g. the Maria
skill path through operator_internal_first, whose chat_id defaults to ""); every row that HAD a chat_id
reached fulfilled or expired. The pass curated each row (a model call) and only then reached
``if not chat_id: continue``, which threw the answer away and left the row open, so the same rows were
re-curated on every pass, forever, until the request cap refused them.

The fix, pinned here:
1. A row with no chat_id is closed (expired, stated reason) before any model call.
2. A row gets a bounded number of answer attempts per day; a row that cannot reach a terminal state in
   that many (send failure, exception) is closed with the reason, never retried forever.
3. The background pass may use at most a share of cio_operator_reply's daily request cap; the rest is
   reserved for operator-initiated questions. The counter survives a service restart.
4. An answerable, deliverable row is answered exactly as before.

Fakes only: no network, no bridge, no database, no Telegram.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import cio_operator_desk_loop as desk  # noqa: E402
from scripts.lib import cio_plan_enrichment as enrich  # noqa: E402

COVERS = ["scripts/lib/cio_operator_desk_loop.py"]

OK = {"ok": True, "content": "model words"}
OPENED = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()


def _row(i: int, chat_id: str = "1") -> dict:
    # Shape of the live stuck rows (freeform_soft_queue, intent present, no eta).
    return {"pending_id": f"opr_{i:012d}", "status": "open", "ts": OPENED, "chat_id": chat_id,
            "message_id": "" if not chat_id else str(i), "channel": "telegram", "kind": "freeform_soft_queue",
            "operator_text": f"perspective on SYM{i}", "intent": {"intent": "freeform", "symbols": [f"SYM{i}"]},
            "blocking_gaps": [], "authority": "READ_ONLY_ADVISORY"}


@pytest.fixture
def wired(monkeypatch, tmp_path):
    pending = tmp_path / "pending.jsonl"
    monkeypatch.setattr(desk, "PENDING_PATH", pending)
    monkeypatch.setattr(desk, "PENDING_BUDGET_PATH", tmp_path / "budget.json", raising=False)
    monkeypatch.setattr(desk, "_cost_cap_backoff_until", None, raising=False)
    monkeypatch.setattr(desk, "gather_tradeai_evidence", lambda intent: {"complete": True, "available": {}})

    def curate(text, evidence):
        res = desk._subject_flash_call([{"role": "user", "content": text}])
        return {"text": res.get("content") or "fail-soft house facts"}

    monkeypatch.setattr(desk, "_curate_from_evidence", curate)
    monkeypatch.setattr(desk, "_finalize_operator_reply", lambda body, prov: (body, prov))
    monkeypatch.setattr(desk, "_with_sources_footer", lambda text, *a, **k: text)
    monkeypatch.setattr(desk, "_pending_reply_provenance", lambda *a, **k: {})
    monkeypatch.setattr(desk, "_retry_advice", lambda row, intent: "Ask again.")
    monkeypatch.setattr(enrich, "load_llm_policy", lambda: {})
    calls: list = []
    monkeypatch.setattr(enrich, "call_governed_llm",
                        lambda messages, policy, *, use_pro=False, task_type=None: calls.append(task_type) or dict(OK))
    sent: list = []

    def send_ok(chat_id, body, reply_to=None):
        sent.append((chat_id, body))
        return {"ok": True}

    def send_fail(chat_id, body, reply_to=None):
        sent.append((chat_id, body))
        return {"ok": False, "error": "telegram_down"}

    def seed(rows):
        pending.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def latest():
        out = {}
        for line in pending.read_text().splitlines():
            r = json.loads(line)
            out[r["pending_id"]] = r
        return out

    return {"seed": seed, "latest": latest, "calls": calls, "sent": sent,
            "send_ok": send_ok, "send_fail": send_fail}


def test_undeliverable_rows_close_before_any_model_call(wired):
    """The measured drain: 7 chat-less rows, re-curated every pass. Before the fix: 7 calls per pass, all open."""
    wired["seed"]([_row(i, chat_id="") for i in range(7)])
    for _ in range(5):
        desk.try_fulfill_pending_replies(wired["send_ok"], limit=8)
    assert wired["calls"] == [], f"no model call for a row that can never be delivered; got {len(wired['calls'])}"
    rows = wired["latest"]()
    assert {r["status"] for r in rows.values()} == {"expired"}
    for r in rows.values():
        assert "no chat id" in r["expiry_reason"]
    assert wired["sent"] == []  # nowhere to send


def test_undeliverable_close_is_written_once(wired):
    wired["seed"]([_row(1, chat_id="")])
    desk.try_fulfill_pending_replies(wired["send_ok"])
    desk.try_fulfill_pending_replies(wired["send_ok"])
    lines = [json.loads(x) for x in desk.PENDING_PATH.read_text().splitlines()]
    assert [r["status"] for r in lines] == ["open", "expired"]


def test_failing_send_is_bounded_then_closed(wired, monkeypatch):
    """A row whose follow-up never delivers used to be re-curated every pass. Now: <= N attempts, then closed."""
    monkeypatch.setenv("CIO_PENDING_MAX_ATTEMPTS_PER_DAY", "3")
    wired["seed"]([_row(1)])
    for _ in range(10):
        desk.try_fulfill_pending_replies(wired["send_fail"])
    assert len(wired["calls"]) == 3, f"3 attempts, then closed; got {len(wired['calls'])} model calls"
    row = wired["latest"]()["opr_000000000001"]
    assert row["status"] == "expired"
    assert "3 answer attempts" in row["expiry_reason"] and "telegram_down" in row["expiry_reason"]


def test_raising_row_is_bounded_then_closed(wired, monkeypatch):
    monkeypatch.setenv("CIO_PENDING_MAX_ATTEMPTS_PER_DAY", "2")

    def boom(intent):
        raise RuntimeError("evidence store down")

    monkeypatch.setattr(desk, "gather_tradeai_evidence", boom)
    wired["seed"]([_row(1)])
    for _ in range(6):
        desk.try_fulfill_pending_replies(wired["send_ok"])
    row = wired["latest"]()["opr_000000000001"]
    assert row["status"] == "expired" and "RuntimeError" in row["expiry_reason"]


def test_answered_row_behaviour_is_unchanged(wired):
    wired["seed"]([_row(1)])
    out = desk.try_fulfill_pending_replies(wired["send_ok"])
    assert out["fulfilled"] == 1 and out["expired"] == 0
    assert wired["calls"] == ["operator_reply"]
    assert len(wired["sent"]) == 1
    chat, body = wired["sent"][0]
    assert chat == "1" and body.startswith("📬 *Follow-up* `opr_000000000001` — Trade-AI data landed")
    assert "model words" in body
    assert wired["latest"]()["opr_000000000001"]["status"] == "fulfilled"
    desk.try_fulfill_pending_replies(wired["send_ok"])
    assert wired["calls"] == ["operator_reply"]  # closed rows are never re-curated


def test_background_cannot_spend_the_operator_reserve(wired, monkeypatch):
    monkeypatch.setattr(desk, "_background_call_ceiling", lambda: 2, raising=False)
    wired["seed"]([_row(i) for i in range(5)])
    out = desk.try_fulfill_pending_replies(wired["send_ok"])
    assert len(wired["calls"]) == 2, "background stops at its share of the cap"
    # Rows past the ceiling are still answered, from house facts (the callers' existing fail-soft).
    assert out["fulfilled"] == 5
    assert sum("fail-soft house facts" in b for _, b in wired["sent"]) == 3
    # An operator-initiated ask (not the background pass) is never held by the reserve.
    assert desk._operator_reply_llm([])["ok"] is True
    assert len(wired["calls"]) == 3


def test_background_share_survives_a_restart(wired, monkeypatch):
    monkeypatch.setattr(desk, "_background_call_ceiling", lambda: 2, raising=False)
    wired["seed"]([_row(1)])
    desk.try_fulfill_pending_replies(wired["send_ok"])
    wired["seed"]([_row(2), _row(3)])
    desk.try_fulfill_pending_replies(wired["send_ok"])  # the counter is read back from disk
    assert len(wired["calls"]) == 2
    saved = json.loads(desk.PENDING_BUDGET_PATH.read_text())
    assert saved["background_calls"] == 2


def test_budget_resets_on_the_new_york_day(wired, tmp_path):
    desk.PENDING_BUDGET_PATH.write_text(json.dumps({"day": "2000-01-01", "background_calls": 999, "rows": {}}))
    b = desk._load_pending_budget(datetime(2026, 10, 11, 4, 0, 1, tzinfo=timezone.utc))  # 00:00:01 ET
    assert b == {"day": "2026-10-11", "background_calls": 0, "rows": {}}
    b = desk._load_pending_budget(datetime(2026, 10, 11, 3, 59, tzinfo=timezone.utc))  # 23:59 ET 10-10
    assert b["day"] == "2026-10-10"


def test_default_reserve_is_three_quarters_of_the_registry_cap(monkeypatch):
    monkeypatch.delenv("CIO_DESK_BACKGROUND_CAP_SHARE", raising=False)
    assert desk._operator_reply_daily_cap() == 400  # config/llm_process_registry.json daily_soft_cap
    assert desk._background_call_ceiling() == 100
    monkeypatch.setenv("CIO_DESK_BACKGROUND_CAP_SHARE", "0")
    assert desk._background_call_ceiling() == 0
    monkeypatch.setenv("CIO_DESK_BACKGROUND_CAP_SHARE", "junk")
    assert desk._background_call_ceiling() == 100
