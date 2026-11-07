"""LQ-20261107-250 — the watchpool Street comparison said the wrong thing for 80% of its rows.

cc-haiku-2's read-only diagnosis (LQ-20261107-243): the pills file had 1,200 names with Street coverage and
981 'unavailable'; in 930 of them the INTERNAL side was missing, while the UI sentence said "no
professional-analyst view is attached". Two facts shared one word, and the dominant one was the false one.

This suite pins the producer side of the repair:
  * `build_pro_analyst_read_model.internal_dir` says WHERE the internal direction came from and WHEN
    (`internal_direction_source`, `internal_direction_at`) — the catalyst fallback covers a 14-day window,
    and `fused_signals.direction` is a column no code writes (measured: 0 non-empty rows in 60 days), so it
    must not be presented as the source;
  * the pill carries `divergence_reason`, so an empty internal side is a producer gap, not a comparison
    failure: 'no_internal_direction' with a Street view, 'no_professional_coverage' without one;
  * `directive_promotion` no longer swallows an unreadable/malformed read model (`except: pass`), which used
    to make a data error indistinguishable from absent coverage; the failure is logged and queryable.

Hermetic: fake DB connections, TRADEAI_STATE_ROOT = tmp, no network, no real data.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Required CI has no psycopg2 (these tests use fake connections only). Same stand-in as
# tests/test_refactor_w2_research_lanes_20261010.py.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = type(sys)("psycopg2")
    _pg_extras = type(sys)("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras
    _pg.connect = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("psycopg2 stub: tests use fake connections"))
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

NOW = datetime.now(timezone.utc)


def _load(name: str):
    """Import scripts/<name>.py privately; serve an empty .env (a checkout has none) for that read."""
    orig = Path.read_text

    def read_text(self, *a, **k):
        if self.name == ".env":
            return ""
        return orig(self, *a, **k)

    Path.read_text = read_text
    try:
        spec = importlib.util.spec_from_file_location(f"_lq250_{name}", SCRIPTS / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        Path.read_text = orig


class FakeConn:
    """Minimal connection: `responder(sql, params)` returns the rows for a flattened query."""

    def __init__(self, responder):
        self.responder = responder
        self.sql: list[str] = []

    def cursor(self, *a, **k):
        conn = self

        class C:
            def execute(self, sql, params=None):
                self._rows = list(conn.responder(" ".join(str(sql).split()), params) or [])

            def fetchall(self):
                return self._rows

            def fetchone(self):
                return self._rows[0] if self._rows else None

        return C()

    def rollback(self):
        pass

    def commit(self):
        pass

    def close(self):
        pass

    def set_session(self, **kw):
        pass


def _build_pills(tmp_path, *, fused=None, catalyst=None, yahoo=True):
    """Run the real read model once for one fixture symbol and return its single pill."""
    fused = fused or []
    catalyst = catalyst or []

    def responder(sql, params):
        if "bool_or(src='held')" in sql:
            return [{"symbol": "AAA", "held": True, "open_paper": False, "open_proposal": False,
                     "scalp": False, "watchlist": True}]
        if "FROM yahoo_analyst_targets_history" in sql:
            if not yahoo:
                return []
            return [{"recommendation_key": "buy", "recommendation_mean": 1.8,
                     "number_of_analyst_opinions": 12, "target_mean_price": 110.0,
                     "target_high_price": None, "target_low_price": None, "target_median_price": None,
                     "current_price": 100.0, "created_at": NOW - timedelta(days=1)}]
        if "source='hermes'" in sql:
            return []
        if "FROM analyst_consensus_history" in sql:  # finviz target
            return []
        if "catalyst_type IN" in sql:  # latest analyst event
            return []
        if "FROM fused_signals" in sql:
            return fused
        if "raw_payload->>'direction'" in sql:
            return catalyst
        raise AssertionError(f"unexpected query in this fixture: {sql}")

    mod = _load("build_pro_analyst_read_model")
    mod._db = lambda: FakeConn(responder)
    mod.OUT = tmp_path / "pro_analyst_pills.json"
    assert mod.main([]) == 0
    doc = json.loads(mod.OUT.read_text())
    assert doc["symbol_count"] == 1
    return doc["pills"][0]


def test_internal_direction_names_the_catalyst_fallback_and_its_window(tmp_path):
    at = NOW - timedelta(hours=6)
    pill = _build_pills(tmp_path, catalyst=[{"dir": "bullish", "n": 3, "as_of": at}])
    assert pill["internal_direction"] == "bullish"
    assert pill["internal_direction_source"] == "catalyst_events_14d", (
        "a direction taken from the 14-day catalyst fallback must say so; fused_signals.direction is a "
        "column no producer writes, so it cannot be presented as the source"
    )
    assert pill["internal_direction_at"] == str(at)
    assert pill["street_direction"] == "bullish"
    assert pill["divergence"] == "aligned"
    assert pill["divergence_reason"] is None


def test_a_missing_internal_side_is_named_as_the_reason(tmp_path):
    pill = _build_pills(tmp_path)  # Street coverage present, no internal direction anywhere
    assert pill["has_professional_coverage"] is True
    assert pill["street_direction"] == "bullish"
    assert pill["internal_direction"] is None
    assert pill["divergence"] == "unavailable"
    assert pill["divergence_reason"] == "no_internal_direction", (
        "the dominant case (930 of 1,200 covered names on 2026-11-07) is a missing INTERNAL side; calling it "
        "absent professional coverage is the false sentence LQ-250 fixes"
    )


def test_no_street_coverage_is_a_different_reason(tmp_path):
    pill = _build_pills(tmp_path, yahoo=False)
    assert pill["has_professional_coverage"] is False
    assert pill["divergence"] == "unavailable"
    assert pill["divergence_reason"] == "no_professional_coverage"


def test_fused_signals_is_still_preferred_when_a_producer_finally_fills_it(tmp_path):
    at = NOW - timedelta(hours=2)
    pill = _build_pills(
        tmp_path,
        fused=[{"direction": "Bearish", "created_at": at}],
        catalyst=[{"dir": "bullish", "n": 9, "as_of": NOW}],
    )
    assert pill["internal_direction"] == "bearish"
    assert pill["internal_direction_source"] == "fused_signals"
    assert pill["internal_direction_at"] == str(at)
    assert pill["divergence"] == "divergent"


def test_an_unreadable_read_model_is_logged_and_queryable(tmp_path, caplog):
    dp = _load("directive_promotion")
    bad = tmp_path / "pills.json"
    bad.write_text("{not json")
    dp._PILLS_JSON = bad
    with caplog.at_level(logging.WARNING, logger="directive_promotion"):
        assert dp.get_divergence_status("AAA") == "unavailable", "the governor's return value is unchanged"
    assert dp.pro_analyst_pills_error(), "an unreadable file must be distinguishable from absent coverage"
    assert "JSONDecodeError" in dp.pro_analyst_pills_error()
    assert any("unreadable" in r.getMessage() for r in caplog.records), (
        "the failure used to be swallowed by `except: pass`; it must reach the log"
    )


def test_a_missing_read_model_file_is_also_an_error_not_an_absence(tmp_path):
    dp = _load("directive_promotion")
    dp._PILLS_JSON = tmp_path / "absent.json"
    assert dp.get_divergence_status("AAA") == "unavailable"
    assert "FileNotFoundError" in (dp.pro_analyst_pills_error() or "")


def test_a_readable_file_clears_the_error_and_answers_from_the_pill(tmp_path):
    dp = _load("directive_promotion")
    good = tmp_path / "pills.json"
    good.write_text(json.dumps({"pills": [
        {"symbol": "AAA", "divergence": "aligned", "has_professional_coverage": True,
         "recommendation_mean": 1.9, "recommendation_key": "buy", "target_mean_price": 120.0,
         "number_of_analyst_opinions": 8},
    ]}))
    dp._PILLS_JSON = good
    assert dp.get_divergence_status("aaa") == "aligned"
    assert dp.pro_analyst_pills_error() is None
    assert dp.get_street_consensus("AAA")["count"] == 8
