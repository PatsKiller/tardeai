"""OperatorTickerFeedback@v1 store + continuity + API (Phase B)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_stance_from_intent():
    from scripts.lib.cio_operator_ticker_feedback import stance_from_intent

    assert stance_from_intent("AGREE") == "bullish"
    assert stance_from_intent("interested") == "bullish"
    assert stance_from_intent("DISAGREE") == "bearish"
    assert stance_from_intent("DISMISS") == "bearish"
    assert stance_from_intent("DEFER") == "monitoring"
    assert stance_from_intent("ACK") == "monitoring"
    assert stance_from_intent("NEED_DATA") == "cautious"
    assert stance_from_intent("need-data") == "cautious"
    assert stance_from_intent("UNKNOWN_X") == "monitoring"


def test_append_latest_journal(tmp_path: Path):
    from scripts.lib.cio_operator_ticker_feedback import (
        SCHEMA,
        AUTHORITY,
        append_feedback,
        journal_for_symbol,
        latest_feedback,
    )

    r1 = append_feedback(
        {"symbol": "uber", "intent": "AGREE", "free_text": "zone looks right"},
        root=tmp_path,
    )
    assert r1["schema"] == SCHEMA
    assert r1["authority"] == AUTHORITY
    assert r1["symbol"] == "UBER"
    assert r1["intent"] == "AGREE"
    assert r1["stance"] == "bullish"
    assert r1["feedback_id"]

    append_feedback(
        {"symbol": "UBER", "intent": "DEFER", "channel": "telegram"},
        root=tmp_path,
    )
    append_feedback(
        {"symbol": "ANET", "intent": "INTERESTED"},
        root=tmp_path,
    )
    latest = latest_feedback("UBER", root=tmp_path)
    assert latest is not None
    assert latest["intent"] == "DEFER"
    assert latest["stance"] == "monitoring"

    journal = journal_for_symbol("UBER", limit=10, root=tmp_path)
    assert len(journal) == 2
    assert journal[0]["intent"] == "DEFER"  # newest first
    assert journal[1]["intent"] == "AGREE"

    path = tmp_path / "data" / "cio" / "operator_ticker_feedback.jsonl"
    assert path.is_file()
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 3


def test_invalid_intent_rejected(tmp_path: Path):
    from scripts.lib.cio_operator_ticker_feedback import append_feedback
    import pytest

    with pytest.raises(ValueError):
        append_feedback({"symbol": "UBER", "intent": "BUY_NOW"}, root=tmp_path)


def test_continuity_loads_from_store(tmp_path: Path):
    from scripts.lib.cio_operator_ticker_feedback import append_feedback
    from scripts.lib.cio_symbol_intelligence import assemble_symbol_intelligence

    append_feedback(
        {"symbol": "UBER", "intent": "AGREE", "free_text": "like the setup"},
        root=tmp_path,
    )

    obj = assemble_symbol_intelligence(
        "UBER",
        change_item={"kind": "reentry_added", "symbol": "UBER", "to": "NEAR", "material": True},
        product={"trigger": "RESEARCH_COMPLETED", "reentry_book": {"names": []}},
        parent={"symbol": "SPCX"},
        prior_feedback=None,
        root=tmp_path,
    )
    cont = ((obj.get("memory") or {}).get("continuity") or {})
    assert cont.get("prior_intent") == "AGREE"
    assert cont.get("prior_stance") == "bullish"
    assert "like the setup" in str(cont.get("summary") or "")

    # Explicit prior_feedback still wins (store not consulted when provided).
    obj2 = assemble_symbol_intelligence(
        "UBER",
        change_item={"kind": "reentry_added", "to": "NEAR"},
        prior_feedback={
            "intent": "DISAGREE",
            "stance": "bearish",
            "ts": "2026-01-01",
            "free_text": "no",
        },
        root=tmp_path,
    )
    cont2 = ((obj2.get("memory") or {}).get("continuity") or {})
    assert cont2.get("prior_intent") == "DISAGREE"


def test_maybe_enqueue_need_data_fail_soft(tmp_path: Path, monkeypatch):
    from scripts.lib import cio_operator_ticker_feedback as fb

    calls: list[dict] = []

    class _FakeHermes:
        def __init__(self, event_store_path=None):
            self.path = event_store_path

        def enqueue(self, **kwargs):
            return {
                "event_type": "HERMES_CHALLENGE_ENQUEUED",
                "stream_id": "hermes-challenge-test",
                "payload": kwargs,
            }

    import types

    held_mod = types.ModuleType("scripts.lib.cio_held_thesis_coverage")

    def _acquire(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "mode": "dry", "targets": kwargs.get("symbols") or []}

    held_mod.run_held_coverage_acquire = _acquire
    hermes_mod = types.ModuleType("scripts.lib.cio_hermes_challenge_queue")
    hermes_mod.HermesChallengeQueue = _FakeHermes
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_held_thesis_coverage", held_mod)
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_hermes_challenge_queue", hermes_mod)

    out = fb.maybe_enqueue_need_data("UBER", root=tmp_path, apply=False)
    assert out["symbol"] == "UBER"
    assert out["held_coverage"]["ok"] is True
    assert out["hermes"]["ok"] is True
    assert calls and calls[0].get("apply") is False


def test_api_get_and_post_feedback(tmp_path: Path, monkeypatch):
    import scripts.lib.cio_operator_ticker_feedback as fb
    import scripts.api_v3_cio as api

    store = tmp_path / "data" / "cio" / "operator_ticker_feedback.jsonl"
    monkeypatch.setattr(fb, "feedback_path", lambda root=None: store)
    monkeypatch.setattr(fb, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(
        fb,
        "maybe_enqueue_need_data",
        lambda symbol, root=None, apply=False: {
            "ok": True,
            "symbol": symbol,
            "held_coverage": {"ok": True, "mode": "dry"},
            "hermes": {"ok": True, "challenge_id": "hermes-challenge-x"},
        },
    )
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_operator_ticker_feedback", fb)

    def _fake_assemble(symbol, **kwargs):
        return {
            "schema": "SymbolIntelligenceObject@v1",
            "symbol": str(symbol).upper(),
            "authority": "READ_ONLY_ADVISORY",
            "memory": {"continuity": None},
        }

    import types

    sio = types.ModuleType("scripts.lib.cio_symbol_intelligence")
    sio.assemble_symbol_intelligence = _fake_assemble
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_symbol_intelligence", sio)

    post = api.post_symbol_intelligence_feedback(
        "uber",
        {"intent": "NEED_DATA", "free_text": "want catalyst detail", "channel": "cc"},
    )
    assert post["ok"] is True
    assert post["feedback"]["intent"] == "NEED_DATA"
    assert post["feedback"]["stance"] == "cautious"
    assert post["financial_action"] is False
    assert post.get("need_data", {}).get("ok") is True

    got = api.get_symbol_intelligence("UBER")
    assert got["ok"] is True
    assert got["symbol"] == "UBER"
    assert got["latest_feedback"]["intent"] == "NEED_DATA"
    assert len(got["journal"]) >= 1
    assert got["authority"] == "READ_ONLY_ADVISORY"
    assert got["intelligence"]["symbol"] == "UBER"


def test_api_rejects_bad_intent(tmp_path: Path, monkeypatch):
    import scripts.lib.cio_operator_ticker_feedback as fb
    import scripts.api_v3_cio as api

    monkeypatch.setattr(fb, "feedback_path", lambda root=None: tmp_path / "otf.jsonl")
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_operator_ticker_feedback", fb)

    res = api.post_symbol_intelligence_feedback("UBER", {"intent": "EXECUTE"})
    assert res["ok"] is False
    assert res["error"] == "invalid_intent"
