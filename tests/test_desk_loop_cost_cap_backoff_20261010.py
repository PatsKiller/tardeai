"""Pending-reply pass backs off on COST_CAP_EXCEEDED (API_OVERLAP_CONSOLIDATION Q6, operator-approved 2026-10-10).

Measured: cio_governed_bridge.log holds ~16,800 "reservation refused for cio_operator_reply:
COST_CAP_EXCEEDED: daily request cap" lines a week, in bursts of 6 every ~1.4 min, which is the cadence of
try_fulfill_pending_replies (every third Telegram poll). After a cost-cap refusal inside that background
pass, the pass stops calling the bridge until the cap resets (next midnight America/New_York). Under the
cap, and on interactive asks, nothing changes. Fakes only: no network, no bridge, no database.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import cio_operator_desk_loop as desk  # noqa: E402
from scripts.lib import cio_plan_enrichment as enrich  # noqa: E402

REFUSED = {"ok": False, "error": "RESERVATION_FAILED: COST_CAP_EXCEEDED: daily request cap",
           "governance_refused": True, "governance_code": "RESERVATION_FAILED"}
OK = {"ok": True, "content": "fine"}


@pytest.fixture
def wired(monkeypatch, tmp_path):
    pending = tmp_path / "pending.jsonl"
    pending.write_text("".join(json.dumps({
        "pending_id": f"opr_{i}", "status": "open", "chat_id": "1", "message_id": i,
        "operator_text": f"perspective on SYM{i}", "intent": {"intent": "freeform", "symbols": [f"SYM{i}"]},
    }) + "\n" for i in range(3)))
    monkeypatch.setattr(desk, "PENDING_PATH", pending)
    monkeypatch.setattr(desk, "_cost_cap_backoff_until", None, raising=False)  # raising=False: runs on the pre-fix module too
    monkeypatch.setattr(desk, "gather_tradeai_evidence", lambda intent: {"complete": True, "available": {}})

    def curate(text, evidence):
        res = desk._subject_flash_call([{"role": "user", "content": text}])
        return {"text": res.get("content") or "fail-soft facts"}

    monkeypatch.setattr(desk, "_curate_from_evidence", curate)
    monkeypatch.setattr(desk, "_finalize_operator_reply", lambda body, prov: (body, prov))
    monkeypatch.setattr(desk, "_with_sources_footer", lambda text, *a, **k: text)
    monkeypatch.setattr(desk, "_pending_reply_provenance", lambda *a, **k: {})
    monkeypatch.setattr(enrich, "load_llm_policy", lambda: {})
    calls = []

    def bridge(answer):
        def call(messages, policy, *, use_pro=False, task_type=None):
            calls.append(task_type)
            return dict(answer)
        monkeypatch.setattr(enrich, "call_governed_llm", call)

    # the send keeps failing, so the rows stay open and every pass retries them (the measured loop)
    def send(chat_id, body, reply_to=None):
        return {"ok": False, "error": "send_failed"}

    return bridge, calls, send


def test_refused_pass_stops_calling_until_cap_reset(wired):
    bridge, calls, send = wired
    bridge(REFUSED)
    for _ in range(5):
        desk.try_fulfill_pending_replies(send)
    assert calls == ["operator_reply"], f"one refusal, then no bridge call until reset; got {len(calls)}"


def test_under_cap_every_row_is_still_curated(wired):
    bridge, calls, send = wired
    bridge(OK)
    desk.try_fulfill_pending_replies(send)
    desk.try_fulfill_pending_replies(send)
    assert len(calls) == 6  # 3 rows x 2 passes: no behaviour change under the cap


def test_backoff_clears_at_next_new_york_midnight(monkeypatch):
    t = datetime(2026, 10, 10, 21, 0, tzinfo=timezone.utc)  # 17:00 ET
    assert desk._next_cap_reset(t) == datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(desk, "_cost_cap_backoff_until", desk._next_cap_reset(t))
    calls = []
    monkeypatch.setattr(enrich, "load_llm_policy", lambda: {})
    monkeypatch.setattr(enrich, "call_governed_llm", lambda *a, **k: calls.append(1) or dict(OK))
    desk._pass_state.background = True
    try:
        assert desk._operator_reply_llm([], now=datetime(2026, 10, 11, 3, 59, tzinfo=timezone.utc))["backoff"]
        assert desk._operator_reply_llm([], now=datetime(2026, 10, 11, 4, 0, 1, tzinfo=timezone.utc))["ok"]
    finally:
        desk._pass_state.background = False
    assert calls == [1]


def test_interactive_ask_is_never_latched(monkeypatch):
    monkeypatch.setattr(desk, "_cost_cap_backoff_until", datetime(2099, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(enrich, "load_llm_policy", lambda: {})
    monkeypatch.setattr(enrich, "call_governed_llm", lambda *a, **k: dict(OK))
    assert desk._operator_reply_llm([])["ok"] is True


def test_cost_cap_detection_covers_both_bridge_shapes():
    assert desk._is_cost_cap_refusal(REFUSED)
    assert desk._is_cost_cap_refusal({"ok": False, "governance_code": "COST_CAP_EXCEEDED", "error": "429"})
    assert not desk._is_cost_cap_refusal({"ok": False, "governance_code": "PROVIDER_ERROR", "error": "timeout"})
    assert not desk._is_cost_cap_refusal(OK)
