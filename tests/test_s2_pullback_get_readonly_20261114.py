"""S2 producers-perf (WR-05/WR-11): the Pullback/MACD candidates GET is READ-ONLY on every call.

The defect this pins: ``GET /api/v2/pullback-macd/candidates`` ran
``INSERT INTO pullback_trigger_history … ON CONFLICT DO NOTHING`` on every page load and every tab poll. A page read
that writes is a GET doing a producer's job. The writer now lives in ``scripts/pullback_macd_screener.py``
(``_record_trigger_history``), which runs on the daily 16:40 scan and the 35 9-15 monitor.

How the "no write" is proven (operator ruling 2026-11-14): by INSTRUMENTING the statement path, not by comparing a
row count. Every statement the request issues reaches the database through ``db_adapter._execute`` — the single
connection/cursor entry point (``api_v2`` does ``from db_adapter import _execute`` at call time, so this one patch
sees all of them). The recorder captures every statement text of every call; the test issues REPEATED GETs and
asserts that no captured statement is INSERT/UPDATE/DELETE/DDL — zero business writes, not "unchanged".

Hermetic: a fake ``db_adapter._execute`` and a fake ``_held_context``. No DB, no store, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "ALTER", "DROP", "CREATE", "TRUNCATE", "GRANT", "REVOKE", "VACUUM")
ANCHOR = "S2_PRODUCERS_PERF"  # greppable: config/ci_gates/S2_PRODUCERS_PERF_20261114.json


class _Recorder:
    """One recorded statement list per GET call: ``calls[0]`` is the first GET, ``calls[1]`` the second, …"""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, sql, params=None, fetch=None):
        if not self.calls:  # pragma: no cover - only if a caller forgets to open a call
            self.calls.append([])
        text = " ".join(str(sql).split())
        self.calls[-1].append(text)
        s = text.upper()
        if s.startswith("SELECT") and "FROM pullback_macd_runs" in s:
            return {"created_at": "2026-11-13T21:40:20+00:00", "screened": 500, "universe_count": 503}
        if s.startswith("SELECT") and "FROM pullback_trigger_history" in s:
            return {"n": 0, "wins": 0, "evaluated": 0, "median_days": None}
        if s.startswith("SELECT"):
            return []
        return None  # a write would land here too — appended above, so it is visible


def _get(body_calls: int, monkeypatch) -> _Recorder:
    import db_adapter
    import api_v2

    rec = _Recorder()
    monkeypatch.setattr(db_adapter, "_execute", rec)
    monkeypatch.setattr(api_v2, "_held_context", lambda symbols: {})
    for _ in range(body_calls):
        rec.calls.append([])
        body = api_v2._pullback_macd_candidates({})
        assert body.get("ok") is True, body
    return rec


def test_repeated_candidate_gets_issue_no_write_at_all(monkeypatch):
    """Three page loads / tab polls: every statement is a SELECT, and the read really did query."""
    rec = _get(3, monkeypatch)
    assert len(rec.calls) == 3
    for i, statements in enumerate(rec.calls, 1):
        assert statements, f"GET #{i} issued no statement at all — the instrumentation missed the read"
        writes = [s for s in statements if s.upper().startswith(WRITE_VERBS)]
        assert writes == [], f"GET #{i} issued business write(s): {writes[:2]}"
        assert all(s.upper().startswith("SELECT") for s in statements), statements
    flat = [s for call in rec.calls for s in call]
    assert any("FROM pullback_macd_candidates" in s for s in flat), "the page read must still read the candidates"


def test_the_writer_exists_in_the_producer_not_the_router():
    """Removing the router's write only moves the behaviour if the producer owns it: pin that it does."""
    src = (ROOT / "scripts" / "pullback_macd_screener.py").read_text(encoding="utf-8")
    assert "def _record_trigger_history" in src
    assert "INSERT INTO pullback_trigger_history" in src
    assert "_db(_TRIGGER_HISTORY_INSERT)" in src, "the producer must issue the one recorded statement"
    api_src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    start = api_src.index("def _pullback_macd_candidates")
    end = api_src.index("\ndef _pullback_macd_scan", start)
    body = api_src[start:end]
    assert "INSERT INTO pullback_trigger_history" not in body, "the wiring patch to api_v2.py is not applied"
    assert "INSERT INTO" not in body, "no business write belongs in the candidates GET at all"
