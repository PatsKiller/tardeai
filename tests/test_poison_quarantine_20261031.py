"""Poison-item quarantine (coordinator 2026-10-31; operator: "validate all stuck agents and processes fix montior and
make auto healings with claude code"). Example: Ask-the-CIO thread thr_b00c8806cf63a6bf failed cio-ask-lifecycle
three runs in a row on 2026-10-30, opened the n8n breaker and stopped every other thread for a day.

Pins: a success resets the streak; `threshold` consecutive failures quarantine the item (receipt + one P2); a
quarantined thread is skipped and the lane run is ok again; disabled (the default) is inert; dry run writes nothing.
End to end through the real cio_ask_lifecycle.run_once with the hourly fixture. Hermetic: tmp state root,
telegram_alert stubbed, TRADE_AI_CI=1.
"""

from __future__ import annotations

#: C1 firing coverage — this module injects the condition and asserts the message reaches the (stubbed) transport.
COVERS = ["scripts/lib/poison_quarantine.py"]

import json
import sys
import types
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import poison_quarantine as PQ  # noqa: E402

CFG = PQ.load_config()


@pytest.fixture
def sent(monkeypatch):
    box: list[dict] = []
    mod = types.ModuleType("telegram_alert")
    mod.send_telegram = lambda message, **kw: box.append({"message": message, **kw}) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    return box


def _q(tmp_path, **over):
    return PQ.Quarantine("cio-ask-lifecycle", {**CFG, "enabled": True, **over}, tmp_path)


def test_streak_threshold_reset_and_receipt(tmp_path, sent):
    for _ in range(2):
        q = _q(tmp_path)
        assert q.record_run({"thr_a": True, "thr_b": True}) == []
        q.save()
    q = _q(tmp_path)
    q.record_run({"thr_b": False})  # a success resets thr_b only
    q.save()
    q = _q(tmp_path)
    newly = q.record_run({"thr_a": True, "thr_b": True}, reasons={"thr_a": "CHECK_FAILED:ValueError"})
    assert [r["item"] for r in newly] == ["thr_a"] and newly[0]["consecutive_failures"] == 3
    assert q.save() == []
    assert len(sent) == 1 and sent[0]["priority"] == "P2" and "thr_a" in sent[0]["message"]
    rec = [json.loads(x) for x in (tmp_path / CFG["receipts_rel"]).read_text().splitlines()]
    assert rec[0]["item"] == "thr_a" and rec[0]["reason"] == "CHECK_FAILED:ValueError"
    assert _q(tmp_path).is_quarantined("thr_a") and not _q(tmp_path).is_quarantined("thr_b")


def test_disabled_and_dry_run_are_inert(tmp_path, sent):
    q = PQ.Quarantine("lane", CFG, tmp_path)  # CFG.enabled is false
    assert CFG["enabled"] is False
    for _ in range(5):
        assert q.record_run({"x": True}) == []
    assert q.save() == [] and not q.is_quarantined("x") and list(tmp_path.iterdir()) == []
    d = PQ.Quarantine("lane", {**CFG, "enabled": True}, tmp_path, dry_run=True)
    for _ in range(3):
        d.record_run({"x": True})
    assert d.save() == [] and list(tmp_path.iterdir()) == [] and sent == []


def test_send_failure_is_returned(tmp_path, monkeypatch):
    mod = types.ModuleType("telegram_alert")
    mod.send_telegram = lambda message, **kw: False
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    q = _q(tmp_path, threshold=1)
    q.record_run({"x": True})
    assert q.save() == ["send_telegram returned falsy"]


# ---------------------------------------------------------------- end to end: the real Ask-the-CIO lifecycle
def test_lifecycle_quarantines_the_poison_thread_and_runs_on(tmp_path, monkeypatch, sent):
    sys.path.insert(0, str(ROOT / "tests"))
    import test_cio_ask_hourly_20261026 as H

    state = tmp_path / "state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setattr(PQ, "load_config", lambda path=None: {**CFG, "enabled": True})
    d = H.fixture(tmp_path)
    failing = lambda _: {"source_runs": [{"source": "web", "status": "refused", "reason": "SEARCH_CAP"}]}  # noqa: E731
    results = [H.run(d, collect=failing, now=H.NOW + timedelta(hours=i)) for i in range(4)]
    assert [r["ok"] for r in results[:2]] == [False, False]  # failing, not yet poison
    assert results[2].get("quarantined_now") == [H.TID] and results[2]["ok"] is True  # third: quarantined, lane ok
    assert results[3].get("quarantined_skipped") == [H.TID] and results[3]["ok"] is True  # then skipped
    assert len(sent) == 1 and H.TID in sent[0]["message"]
