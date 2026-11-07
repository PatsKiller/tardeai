"""A synthesis lane must not be fed an empty bundle, and must not stage zero forever.

WORK-QUEUE item 11, 2026-11-07: ``hermes-cross-source-synthesizer`` had failed 4 runs in a row and
its receipt said only ``NO_BRIEFS``. The log said why, in four places:

    Bundle: 0 signals across 6 sources
      entity_spikes: {'error': 'column "extracted_at" does not exist ...'}
      news_themes:   {'error': 'current transaction is aborted, commands ignored until end of
                               transaction block'}
      ... same for discovery_signals / research_themes
      sector_rotation: 0 items        agenda_actions: 0 items      <- silently broken
    Synthesis FAILED: Expecting value: line 1 column 1 (char 0)
    No briefs generated

Two defects, both in this script:

1. ``content_entity_links`` has ``created_at``, not ``extracted_at``. PostgreSQL aborts the whole
   transaction on the first failed statement, so ONE bad column turned the other five sources into
   five fake failures. Every run asked the model to synthesize from nothing; the model either
   answered with non-JSON or wrote briefs about the database errors themselves.
2. Even when it did produce briefs (5 on 2026-11-05), ``hermes_staging_ingest`` rejected every one:
   "limitations array is empty or missing", "source_views is empty or missing" — fields the prompt
   never asked for. This lane could not stage a row, ever.

Hermetic: fake connections and cursors, stubbed ``generate_cloud``; no DB, no model, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hermes_cross_source_synthesizer as hcs   # noqa: E402


# ── 1. one broken source must not zero the other five ───────────────────────

class FlakyCursor:
    """PostgreSQL semantics: the first failed statement aborts the transaction until rollback."""

    def __init__(self, broken_sql_substring, rows_by_source):
        self.aborted = False
        self.calls = []
        self._broken = broken_sql_substring
        self._rows = rows_by_source
        self._current_sample = []

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))
        if self.aborted:
            raise RuntimeError(
                "current transaction is aborted, commands ignored until end of transaction block")
        if self._broken and self._broken in sql:
            self.aborted = True
            raise RuntimeError('column "extracted_at" does not exist\nLINE 4: WHERE extracted_at > ...')
        self._current_sample = next(iter(self._rows.values())) if self._rows else []

    def fetchall(self):
        # Each source reads one row so the count arithmetic is easy to follow.
        return [(f"value-{len(self.calls)}",) + (0,) * 5]

    def close(self):
        pass


class FlakyConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self, *a, **k):
        return self._cur

    def rollback(self):
        self._cur.aborted = False      # what psycopg2 does: ends the aborted transaction

    def commit(self):
        pass

    def close(self):
        pass


def test_one_broken_source_does_not_zero_the_rest():
    cur = FlakyCursor("content_entity_links", rows_by_source={})
    bundle = hcs.collect_signal_bundle(FlakyConn(cur), hours=168)
    assert list(bundle["source_errors"]) == ["entity_spikes"]      # only the real error
    for name in ("news_themes", "discovery_signals", "sector_rotation",
                 "research_themes", "agenda_actions"):
        assert isinstance(bundle["sources"][name], list), f"{name} was poisoned by the first failure"
    assert "aborted" not in json.dumps(bundle["sources"]["news_themes"])


def test_the_entity_query_uses_the_column_the_table_has():
    cur = FlakyCursor(None, rows_by_source={})
    hcs.collect_signal_bundle(FlakyConn(cur), hours=168)
    entity_sql = cur.calls[0][0]
    assert "created_at" in entity_sql and "extracted_at" not in entity_sql


def test_a_silently_broken_source_is_now_recorded():
    """sector_rotation and agenda_actions used to turn any failure into ``[]`` — invisible."""
    cur = FlakyCursor("sector_momentum_state", rows_by_source={})
    bundle = hcs.collect_signal_bundle(FlakyConn(cur), hours=168)
    assert "sector_rotation" in bundle["source_errors"]
    assert bundle["sources"]["sector_rotation"] == {"error": bundle["source_errors"]["sector_rotation"]}
    assert "agenda_actions" not in bundle["source_errors"]         # later sources still work


def test_the_error_message_keeps_the_database_reason():
    cur = FlakyCursor("content_entity_links", rows_by_source={})
    bundle = hcs.collect_signal_bundle(FlakyConn(cur), hours=168)
    assert "extracted_at" in bundle["source_errors"]["entity_spikes"]


# ── 2. the receipt says WHY there were no briefs ────────────────────────────

def test_synthesize_reports_the_reason_it_returned_nothing(monkeypatch):
    from lib import governed_cloud_generation as gcg

    def boom(*a, **k):
        raise RuntimeError("CLOUD_GENERATION_FAILED_CLOSED: hermes_cross_source_synthesizer: "
                           "chatgpt:HTTPError:429 Client Error")
    monkeypatch.setattr(gcg, "generate_cloud", boom)
    diag: dict = {}
    assert hcs.synthesize({"sources": {}}, diagnostics=diag) == []
    assert "CLOUD_GENERATION_FAILED_CLOSED" in diag["error"] and "429" in diag["error"]


def test_the_prompt_asks_for_the_fields_the_validator_requires(monkeypatch):
    from lib import governed_cloud_generation as gcg
    seen = {}

    def fake(prompt, **kw):
        seen["prompt"] = prompt
        return json.dumps([{"topic": "t", "summary": "s", "thesis": "x"}]), "grok"

    monkeypatch.setattr(gcg, "generate_cloud", fake)
    hcs.synthesize({"sources": {}})
    assert '"limitations"' in seen["prompt"] and '"source_views"' in seen["prompt"]
    assert "REQUIRED" in seen["prompt"]


def test_the_no_briefs_receipt_carries_the_cause(monkeypatch, capsys):
    written = {}
    monkeypatch.setattr(hcs, "get_db", lambda: FlakyConn(FlakyCursor(None, {})))
    monkeypatch.setattr(hcs, "KILL_HERMES", Path("/nonexistent/HERMES_DISABLED"))
    monkeypatch.setattr(hcs, "KILL_SYNTH", Path("/nonexistent/HERMES_SYNTHESIZER_DISABLED"))
    monkeypatch.setattr(hcs, "collect_signal_bundle", lambda conn: {
        "sources": {"news_themes": [1, 2]}, "source_errors": {"entity_spikes": "UndefinedColumn: x"}})
    monkeypatch.setattr(hcs, "synthesize", lambda bundle, diagnostics=None: (
        diagnostics.update({"error": "JSONDecodeError: Expecting value: line 1 column 1"}) or []))
    import lib.lane_last_receipt as llr
    monkeypatch.setattr(llr, "write_lane_receipt", lambda lane, **kw: written.update(lane=lane, **kw))

    assert hcs.main(["--apply"]) == 1
    assert written["lane"] == "hermes-cross-source-synthesizer"
    assert written["error"].startswith("NO_BRIEFS: ") and "Expecting value" in written["error"]
    assert written["summary"]["why"].startswith("JSONDecodeError")
    assert written["summary"]["source_unreadable"] == {"entity_spikes": "UndefinedColumn: x"}
    assert written["summary"]["signals"] == 2


# ── 3. a brief this producer can actually stage ─────────────────────────────

BRIEF = {"topic": "Sector rotation into healthcare",
         "summary": "XLV leads on relative strength while entity mentions of healthcare rise.",
         "thesis": "Defensive rotation with momentum behind it.",
         "thesis_type": "bullish", "confidence": 0.6,
         "signals_used": ["entity_spikes", "sector_rotation"],
         "keywords": ["healthcare", "rotation"]}


def _persisted(brief):
    """Run the REAL validator, capturing the payload it was handed."""
    import hermes_staging_ingest as hsi
    captured = {}
    real = hsi.validate_payload

    def spy(payload, table):
        captured.update(payload)
        return real(payload, table)

    hsi.validate_payload = spy
    try:
        out = hcs.persist_briefs(None, [brief], apply=False)
    finally:
        hsi.validate_payload = real
    return out, captured, real(captured, "hermes_research_intelligence")


def test_a_brief_without_limitations_is_still_stageable():
    out, payload, (ok, errors) = _persisted(dict(BRIEF))
    assert out["results"][0]["status"] == "validated"
    ev = payload["evidence_json"]
    assert ev["limitations"] and ev["limitations"][0].startswith("Single-pass synthesis")
    assert ev["source_views"] == [
        {"source": "entity_spikes", "view": "contributing source named by the synthesis"},
        {"source": "sector_rotation", "view": "contributing source named by the synthesis"}]
    assert ok, errors


def test_the_models_own_limitations_are_kept():
    brief = dict(BRIEF, limitations=["bundle has no price data"],
                 source_views=[{"source": "news_themes", "view": "80 CAVA articles"}])
    _, payload, (ok, errors) = _persisted(brief)
    assert payload["evidence_json"]["limitations"] == ["bundle has no price data"]
    assert payload["evidence_json"]["source_views"] == [
        {"source": "news_themes", "view": "80 CAVA articles"}]
    assert ok, errors


def test_a_brief_with_no_sources_at_all_is_still_rejected():
    """No fabrication: with neither source_views nor signals_used there is nothing to stand on."""
    out, _, (ok, errors) = _persisted(dict(BRIEF, signals_used=[]))
    assert out["results"][0]["status"] == "rejected"
    assert not ok and any("source_views" in e for e in errors)
