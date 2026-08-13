"""cio_opportunity_queue.py — dry tests for the Alex desk-suggestion opportunity queue.

Phase 5 increment: one deterministic, hash-pinned "opportunity queue" surface that
Alex consumes instead of a page the operator watches all day. Pure logic is tested
with no live DB/broker/LLM; detector wake creation is tested with an injected
fail-soft opportunity source and an in-memory wake store.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_opportunity_queue as oq  # noqa: E402
from scripts.lib.cio_wake_jobs import CIOWakeJobStore  # noqa: E402
from scripts.lib.cio_event_detector import CIOEventDetector  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Pure logic — normalize / key / rank / digest / material
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_opportunity_happy_path():
    opp = oq.normalize_opportunity({
        "surfaced_by": "reentry",
        "symbol": "nvda",
        "directive_label": "Re-entry READY — NVDA",
        "state": "READY TO REVIEW",
    })
    assert opp is not None
    assert opp["source"] == "reentry"
    assert opp["symbol"] == "NVDA"
    assert opp["state"] == "READY TO REVIEW"
    assert opp["opportunity_key"]


def test_normalize_skips_unknown_source():
    assert oq.normalize_opportunity({"surfaced_by": "hermes", "symbol": "NVDA"}) is None


def test_normalize_skips_missing_symbol():
    assert oq.normalize_opportunity({"surfaced_by": "cio", "symbol": ""}) is None


def test_normalize_skips_non_actionable_verdict():
    assert oq.normalize_opportunity({
        "source": "advisory", "symbol": "NVDA", "verdict": "HOLD",
    }) is None


def test_normalize_skips_non_actionable_state():
    assert oq.normalize_opportunity({
        "source": "reentry", "symbol": "NVDA", "state": "CURRENTLY HELD",
    }) is None


def test_normalize_parses_rs_score():
    opp = oq.normalize_opportunity({
        "source": "rotation", "symbol": "XLK", "rs_score": "82.5",
    })
    assert opp["rs_score"] == 82.5
    bad = oq.normalize_opportunity({"source": "rotation", "symbol": "XLK", "rs_score": "abc"})
    assert bad["rs_score"] is None


def test_opportunity_key_is_deterministic():
    a = oq.opportunity_key("advisory", "nvda", "ADD NVDA", "ADD")
    b = oq.opportunity_key("advisory", "NVDA", "ADD NVDA", "ADD")
    c = oq.opportunity_key("advisory", "nvda", "ADD NVDA", "RE_ENTER")
    assert a == b
    assert a != c


def test_build_queue_dedupes_and_ranks():
    rows = [
        {"surfaced_by": "cio", "symbol": "MSFT", "directive_label": "CIO — MSFT"},
        {"surfaced_by": "reentry", "symbol": "NVDA", "state": "READY TO REVIEW"},
        {"surfaced_by": "rotation", "symbol": "XLK", "rs_score": 90},
        {"surfaced_by": "advisory", "symbol": "MSFT", "verdict": "ADD"},
    ]
    q = oq.build_opportunity_queue(rows)
    assert q["count"] == 4
    # reentry ranks first, rotation second (highest SOURCE_RANK)
    assert q["items"][0]["source"] == "reentry"
    assert q["items"][1]["source"] == "rotation"


def test_build_queue_dedupes_same_key():
    rows = [
        {"surfaced_by": "advisory", "symbol": "NVDA", "directive_label": "ADD NVDA", "verdict": "ADD", "surfaced_at": "2026-08-13T00:00:00Z"},
        {"surfaced_by": "advisory", "symbol": "NVDA", "directive_label": "ADD NVDA", "verdict": "ADD", "surfaced_at": "2026-08-13T01:00:00Z"},
    ]
    q = oq.build_opportunity_queue(rows)
    assert q["count"] == 1


def test_build_queue_material_requires_two_sources():
    one_source = [{"surfaced_by": "advisory", "symbol": "NVDA", "verdict": "ADD"}]
    assert oq.build_opportunity_queue(one_source)["material"] is False

    two_source = [
        {"surfaced_by": "advisory", "symbol": "NVDA", "verdict": "ADD"},
        {"surfaced_by": "rotation", "symbol": "XLK", "rs_score": 90},
    ]
    assert oq.build_opportunity_queue(two_source)["material"] is True


def test_build_queue_digest_deterministic():
    rows = [{"surfaced_by": "rotation", "symbol": "XLK", "rs_score": 90}]
    a = oq.build_opportunity_queue(rows)
    b = oq.build_opportunity_queue(rows)
    assert a["digest"] == b["digest"]


def test_material_new_opportunities():
    assert oq.material_new_opportunities(None, None) is False
    assert oq.material_new_opportunities("abc", None) is True
    assert oq.material_new_opportunities("abc", "abc") is False
    assert oq.material_new_opportunities("abc", "def") is True


# ─────────────────────────────────────────────────────────────────────────────
# Live reader — fetch_desk_suggestions via injectable executor
# ─────────────────────────────────────────────────────────────────────────────

def test_fetch_desk_suggestions_shape():
    calls = {}

    def fake_exec(sql, params=None, fetch=None):
        sql_u = sql.upper()
        if "WATCH_DIRECTIVE_HITS" in sql_u:
            return [{"symbol": "NVDA", "source": "advisory", "directive_label": "ADD NVDA", "surfaced_at": "2026-08-13T00:00:00Z"}]
        if "DIRECTIVE_HITS_STAGING" in sql_u:
            return [{"symbol": "XLK", "source": "rotation", "directive_label": None, "verdict": None,
                     "state": None, "rs_score": "88", "surfaced_at": "2026-08-13T01:00:00Z"}]
        return None

    rows = oq.fetch_desk_suggestions(fake_exec)
    assert len(rows) >= 2
    q = oq.build_opportunity_queue(rows)
    assert q["count"] == 2
    assert q["by_source"]["advisory"] == 1
    assert q["by_source"]["rotation"] == 1


def test_fetch_desk_suggestions_fails_soft():
    def raising_exec(sql, params=None, fetch=None):
        raise RuntimeError("db down")

    rows = oq.fetch_desk_suggestions(raising_exec)
    assert rows == []


# ─────────────────────────────────────────────────────────────────────────────
# Detector integration — wake Alex on material new opportunities
# ─────────────────────────────────────────────────────────────────────────────

def _make_detector(tmp_path, source):
    store = CIOWakeJobStore(event_store_path=tmp_path / "wakes.jsonl")
    detector = CIOEventDetector(
        schedules=[],
        wake_store=store,
        action_ledger=None,
        handoff_queue=None,
        opportunity_source=source,
    )
    # `schedules or LEGACY_SCHEDULES` falls back to the legacy schedule; force an
    # empty schedule list so these tests exercise ONLY the opportunity path.
    detector.schedules = []
    return detector, store


def test_detector_wakes_on_material_queue(tmp_path):
    digest = "d" * 64
    detector, store = _make_detector(tmp_path, lambda: {
        "digest": digest, "material": True, "count": 3,
        "distinct_sources": 2, "by_source": {"advisory": 2, "rotation": 1}, "top": [],
    })
    result = detector.run_once()
    assert result["wakes_created"] == 1
    wake = store.list_wakes()[0]
    assert wake["trigger_type"] == "OPPORTUNITY_QUEUE"
    assert wake["reason_codes"] == ["OPPORTUNITY_QUEUE"]
    assert wake["context"]["opportunity_digest"] == digest


def test_detector_wake_is_idempotent_per_digest(tmp_path):
    digest = "d" * 64
    detector, store = _make_detector(tmp_path, lambda: {
        "digest": digest, "material": True, "count": 2,
        "distinct_sources": 2, "by_source": {}, "top": [],
    })
    detector.run_once()
    detector.run_once()
    # second run is a no-op (same digest → idempotency key exists)
    assert len(store.list_wakes()) == 1


def test_detector_skips_non_material_queue(tmp_path):
    detector, store = _make_detector(tmp_path, lambda: {
        "digest": "d" * 64, "material": False, "count": 1, "distinct_sources": 1, "top": [],
    })
    result = detector.run_once()
    assert result["wakes_created"] == 0
    assert len(store.list_wakes()) == 0


def test_detector_skips_when_source_raises(tmp_path):
    def boom():
        raise RuntimeError("no db")

    detector, store = _make_detector(tmp_path, boom)
    result = detector.run_once()
    assert result["wakes_created"] == 0
    assert len(store.list_wakes()) == 0


def test_detector_skips_when_no_source(tmp_path):
    detector, store = _make_detector(tmp_path, None)
    result = detector.run_once()
    assert result["wakes_created"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Wiring constants + mappings
# ─────────────────────────────────────────────────────────────────────────────

def test_wake_constants_include_opportunity_queue():
    from scripts.lib import cio_wake_jobs as wj
    assert "OPPORTUNITY_QUEUE" in wj.TRIGGER_TYPES
    assert "OPPORTUNITY_QUEUE" in wj.WAKE_REASON_CODES
    assert wj.PRIORITY_MAP.get("OPPORTUNITY_QUEUE") == "normal"


def test_run_trigger_type_includes_opportunity_queue():
    from scripts.lib import cio_run
    assert "OPPORTUNITY_QUEUE" in cio_run.VALID_TRIGGER_TYPES


def test_dispatcher_maps_opportunity_queue():
    from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher
    assert CIOWakeDispatcher._map_wake_to_run_trigger("OPPORTUNITY_QUEUE") == "OPPORTUNITY_QUEUE"


def test_run_worker_maps_opportunity_queue():
    from scripts.lib.cio_run_worker import (
        CIORunWorker,
        resolve_run_budget,
    )
    assert resolve_run_budget("OPPORTUNITY_QUEUE")["name"] == "material_event"
    assert CIORunWorker._classify_run_purpose("OPPORTUNITY_QUEUE", {}) == "WATCH_OR_CATALYST_REVIEW"
