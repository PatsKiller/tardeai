"""Broker domains + Q1 (operator decisions 2026-10-10 ~17:45 ET, CONSOLIDATION_PLAN.md §D).

(2)/(5)/(13)/(14) registry rows with the operator's grant; (6) quote-only get_best_quote — stored
quote first, providers only on stale, first fresh answer wins, never the fan-out — and the Data
Broker's dead fallback revived without a fan-out; (7) the latest_quote projection; (3) the
enrichment-cache merge tool (dry run read-only, apply through the single writer, archive + alias);
(13) yfinance_info_snapshot single writer and projection; scalp_list / social_feed projections.

Hermetic: fake db_query callables, tmp_path stores, stub providers. No network, no DB.
"""

from __future__ import annotations

import json
import os
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:  # heavy deps may be blocked: market_quote_provider imports session13_db (psycopg2) at module top
    import psycopg2  # noqa: F401
except ImportError:  # pragma: no cover - exercised in the no-deps run
    _stub = types.ModuleType("session13_db")

    def _no_db():  # never called: every test injects db_query
        raise RuntimeError("no DB in tests")

    _stub.get_conn = _no_db
    sys.modules.setdefault("session13_db", _stub)

import market_quote_provider as mqp  # noqa: E402
from lib.data_broker import latest_quote as lq  # noqa: E402
from lib.data_broker import market_quote as mq  # noqa: E402

NOW = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)
AUTH = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
DOMAINS = {d["domain"]: d for d in AUTH["domains"]}


def _iso(minutes_ago: float, ref: datetime | None = None) -> str:
    return ((ref or datetime.now(timezone.utc)) - timedelta(minutes=minutes_ago)).isoformat()


class FakeDB:
    """db_query(sql, params) -> rows; records every call."""

    def __init__(self, rows=None, exc=None):
        self.rows = rows or []
        self.exc = exc
        self.calls = []

    def __call__(self, sql, params=None, fetch="all"):
        self.calls.append((sql, params))
        if self.exc:
            raise self.exc
        wanted = set((params or [[]])[0]) if params else set()
        return [r for r in self.rows if not wanted or r.get("symbol") in wanted]


def _qrow(sym, price, minutes_ago, ref=None, src="alpaca"):
    return {
        "symbol": sym,
        "price": price,
        "prev_close": price - 1,
        "day_change_pct": 1.5,
        "volume": 100,
        "fetched_at": (ref or datetime.now(timezone.utc)) - timedelta(minutes=minutes_ago),
        "source": src,
    }


# ── (7) latest_quote projection ──────────────────────────────────────────────


def test_latest_quote_sql_uses_the_index_not_a_distinct_on_scan():
    sql = lq.LATEST_SQL
    assert "LATERAL" in sql and "LIMIT 1" in sql
    assert "upper(" not in sql.lower(), "upper(symbol) cannot use idx_market_quotes_symbol_fetched_at_desc"
    assert "DISTINCT ON" not in sql


def test_latest_quote_fresh_stale_missing_and_envelope():
    db = FakeDB([_qrow("AAPL", 200.0, 5, NOW), _qrow("MSFT", 400.0, 60, NOW)])
    out = lq.get_latest_quotes(db, ["aapl", "MSFT", "NOPE", "AAPL"], max_age_seconds=900, now=NOW)
    assert out["provider_calls"] == 0 and out["ok"] is True
    assert out["fresh"] == ["AAPL"] and out["stale_or_missing"] == ["MSFT", "NOPE"]
    assert out["symbols"]["MSFT"]["stale"] is True and out["symbols"]["MSFT"]["price"] == 400.0
    assert out["symbols"]["AAPL"]["source"] == "data_broker.latest_quote:alpaca"
    assert out["schema"] == "BrokerReadEnvelope@v1" and out["source"]["projection"] == "latest_quote"
    assert db.calls[0][1] == (["AAPL", "MSFT", "NOPE"],)  # upper-cased, de-duplicated, one query


def test_latest_quote_read_failure_is_reported_not_raised():
    out = lq.get_latest_quotes(FakeDB(exc=RuntimeError("boom")), ["AAPL"], now=NOW)
    assert out["ok"] is False and "boom" in out["error"] and out["stale_or_missing"] == ["AAPL"]
    assert out["gap"]["kind"] == "no_coverage"


# ── get_price_batch: first pass via latest_quote, bounded live fallback ──────


def test_price_batch_reads_through_latest_quote_and_keeps_its_shape(monkeypatch):
    called = []
    monkeypatch.setattr(mq, "_best_quote", lambda s, max_age_s=900: called.append(s))
    db = FakeDB([_qrow("AAPL", 200.0, 30)])
    out = mq.get_price_batch(db, ["AAPL"], max_age_hours=12)
    assert out == {
        "AAPL": {
            "price": 200.0,
            "chg_pct": 1.5,
            "as_of": out["AAPL"]["as_of"],
            "source": "data_broker.market_quotes:alpaca",
        }
    }
    assert called == [] and db.calls[0][0] == lq.LATEST_SQL


def test_price_batch_drops_rows_older_than_the_window_and_skip_live_calls_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(mq, "_best_quote", lambda s, max_age_s=900: called.append(s))
    out = mq.get_price_batch(FakeDB([_qrow("AAPL", 200.0, 13 * 60)]), ["AAPL"], max_age_hours=12, skip_live=True)
    assert out == {} and called == []


def test_price_batch_live_fallback_is_bounded_per_batch(monkeypatch):
    called = []

    def fake(sym, max_age_s=900):
        called.append(sym)
        return {"price": 10.0, "chg_pct": None, "as_of": _iso(1), "provider": "alpaca", "stale": False}

    monkeypatch.setattr(mq, "_best_quote", fake)
    syms = [f"S{i:02d}" for i in range(25)]
    out = mq.get_price_batch(FakeDB([]), syms)
    assert len(called) == mq.LIVE_FALLBACK_MAX_PER_BATCH == 10
    assert set(out) == set(syms[:10])
    assert out["S00"]["source"] == "data_broker.market_quote:get_best_quote:alpaca"


def test_price_batch_does_not_serve_a_stale_fallback_as_current(monkeypatch):
    monkeypatch.setattr(mq, "_best_quote", lambda s, max_age_s=900: {"price": 1.0, "provider": "x", "stale": True})
    assert mq.get_price_batch(FakeDB([]), ["AAPL"]) == {}


def test_broker_fallback_no_longer_dies_on_a_type_error(monkeypatch):
    """The 2026-10-10 finding: _best_quote passed max_age_seconds= to a one-argument function and
    swallowed the TypeError. It now reaches quote-only get_best_quote with skip_stored=True."""
    seen = {}

    def fake_gbq(symbol, *, max_age_seconds=None, db_query=None, skip_stored=False):
        seen.update(symbol=symbol, max_age_seconds=max_age_seconds, skip_stored=skip_stored)
        return {"last_price": 12.5, "quote_timestamp": _iso(1), "provider": "alpaca", "stale": False}

    monkeypatch.setattr(mqp, "get_best_quote", fake_gbq)
    monkeypatch.delenv("QUOTE_ONLY_MODE", raising=False)
    q = mq._best_quote("AAPL", max_age_s=900)
    assert q and q["price"] == 12.5 and q["stale"] is False
    assert seen == {"symbol": "AAPL", "max_age_seconds": 900, "skip_stored": True}


def test_broker_fallback_kill_switch_restores_the_old_zero_call_behaviour(monkeypatch):
    monkeypatch.setattr(mqp, "get_best_quote", lambda *a, **k: pytest.fail("provider path reached"))
    monkeypatch.setenv("QUOTE_ONLY_MODE", "0")
    assert mq._best_quote("AAPL") is None


# ── (6) Q1: quote-only get_best_quote ────────────────────────────────────────


def _chain(monkeypatch, answers):
    """Replace PROVIDER_CHAIN; answers = [(name, minutes_ago | None (no price) | 'raise')]."""
    calls = []

    def mk(name, ans):
        def f(sym):
            calls.append(name)
            if ans == "raise":
                raise RuntimeError("down")
            if ans is None:
                return None
            return mqp._make_result(
                provider=name, priority=1, last_price=50.0, bid=49.9, ask=50.1, quote_timestamp=_iso(ans)
            )

        return f

    monkeypatch.setattr(mqp, "PROVIDER_CHAIN", [(n, mk(n, a)) for n, a in answers])
    return calls


def test_quote_only_fresh_stored_quote_makes_zero_provider_calls(monkeypatch):
    calls = _chain(monkeypatch, [("alpaca", 0), ("schwab", 0)])
    q = mqp.get_best_quote("aapl", max_age_seconds=900, db_query=FakeDB([_qrow("AAPL", 201.0, 2)]))
    assert calls == []
    assert q["provider"] == "market_quotes" and q["last_price"] == 201.0 and q["stale"] is False
    assert q["is_execution_eligible"] is False, "a stored quote is never an executable bid/ask"
    assert q["raw_payload"]["prev_close"] == 200.0 and q["day_change_pct"] == 1.5


def test_quote_only_stale_store_stops_at_the_first_fresh_provider(monkeypatch):
    calls = _chain(monkeypatch, [("alpaca", "raise"), ("schwab", 1), ("yfinance", 0), ("finviz_cache", 0)])
    q = mqp.get_best_quote("AAPL", max_age_seconds=900, db_query=FakeDB([_qrow("AAPL", 201.0, 60)]))
    assert calls == ["alpaca", "schwab"], "no fan-out: yfinance and finviz_cache are never asked"
    assert q["provider"] == "schwab" and q["stale"] is False
    assert q["providers_tried"] == ["alpaca:error", "schwab"]


def test_quote_only_skips_a_stale_provider_answer_and_keeps_going(monkeypatch):
    calls = _chain(monkeypatch, [("alpaca", 300), ("schwab", 2), ("yfinance", 0)])
    q = mqp.get_best_quote("AAPL", max_age_seconds=900, db_query=FakeDB([]))
    assert calls == ["alpaca", "schwab"] and q["provider"] == "schwab"


def test_quote_only_nothing_fresh_returns_the_freshest_labelled_stale(monkeypatch):
    _chain(monkeypatch, [("alpaca", 300), ("schwab", None), ("yfinance", 200), ("finviz_cache", None)])
    q = mqp.get_best_quote("AAPL", max_age_seconds=900, db_query=FakeDB([_qrow("AAPL", 201.0, 120)]))
    assert q["provider"] == "market_quotes" and q["stale"] is True  # stored 120 min beats 200/300 min
    q2 = mqp.get_best_quote("AAPL", max_age_seconds=900, db_query=FakeDB([_qrow("AAPL", 201.0, 999)]))
    assert q2["provider"] == "yfinance" and q2["stale"] is True


def test_quote_only_no_answer_anywhere(monkeypatch):
    _chain(monkeypatch, [("alpaca", None), ("schwab", "raise")])
    q = mqp.get_best_quote("ZZZZ", max_age_seconds=900, db_query=FakeDB([]))
    assert q["provider"] == "none" and q["last_price"] is None and q["stale"] is True


def test_skip_stored_never_reads_the_store(monkeypatch):
    _chain(monkeypatch, [("alpaca", 1)])
    db = FakeDB([_qrow("AAPL", 201.0, 1)])
    q = mqp.get_best_quote("AAPL", max_age_seconds=900, db_query=db, skip_stored=True)
    assert db.calls == [] and q["provider"] == "alpaca"


def test_legacy_mode_is_unchanged_full_chain_freshest_realtime(monkeypatch):
    """Execution-readiness callers (check_fresh_quote, broker_trade_plan_gate) pass no bound and
    keep the pre-Q1 behaviour exactly; broker_trade_plan_gate.py itself is not modified."""
    calls = _chain(monkeypatch, [("alpaca", 10), ("schwab", 1), ("yfinance", 0), ("finviz_cache", 0)])
    q = mqp.get_best_quote("AAPL")
    assert calls == ["alpaca", "schwab", "yfinance", "finviz_cache"]
    assert q["provider"] == "schwab" and "quote_mode" not in q


def test_kill_switch_sends_quote_only_callers_back_to_legacy(monkeypatch):
    calls = _chain(monkeypatch, [("alpaca", 10), ("schwab", 1)])
    monkeypatch.setenv("QUOTE_ONLY_MODE", "0")
    db = FakeDB([_qrow("AAPL", 201.0, 1)])
    q = mqp.get_best_quote("AAPL", max_age_seconds=900, db_query=db)
    assert calls == ["alpaca", "schwab"] and db.calls == [] and "quote_mode" not in q


def test_quote_only_bound_equals_the_registry_window():
    assert mqp.QUOTE_ONLY_MAX_AGE_SECONDS == DOMAINS["quote_price"]["stale_after_hours"] * 3600
    assert lq.DEFAULT_MAX_AGE_SECONDS == DOMAINS["quote_price"]["stale_after_hours"] * 3600


QUOTE_ONLY_CALLERS = {
    "scripts/proposal_enrichment_loop.py": 1,
    "scripts/proposal_technical_snapshot.py": 1,
    "scripts/incubator_proposal_promoter.py": 2,  # price fallback + drift check; the spread gate stays legacy
    "scripts/send_telegram_proposal_alert.py": 1,
    "scripts/lib/data_broker/quote_batch.py": 1,
    "scripts/lib/data_broker/reentry_decision_desk.py": 1,
}


@pytest.mark.parametrize("rel,n", sorted(QUOTE_ONLY_CALLERS.items()))
def test_quote_only_callers_pass_the_bound(rel, n):
    text = (ROOT / rel).read_text()
    assert len(re.findall(r"max_age_seconds=(QUOTE_ONLY_MAX_AGE_SECONDS|_qo_age)", text)) == n


def test_execution_paths_are_untouched_by_q1():
    gate = (ROOT / "scripts" / "broker_trade_plan_gate.py").read_text()
    assert "max_age_seconds" not in gate and "QUOTE_ONLY" not in gate
    promoter = (ROOT / "scripts" / "incubator_proposal_promoter.py").read_text()
    assert "_quote = get_best_quote(symbol)\n" in promoter, "spread gate needs a real bid/ask: legacy mode"


# ── registry rows: operator grant, single writer, projections exist ──────────

NEW = ("finviz_enrichment", "scalp_list", "social_posts", "yfinance_info_snapshot")


@pytest.mark.parametrize("name", NEW)
def test_new_domains_carry_the_operator_grant(name):
    d = DOMAINS[name]
    a = d["approval"]
    assert a["approved_by"] == "operator" and a["approved_on"] == "2026-10-10"
    assert "CONSOLIDATION_PLAN.md §D" in a["reference"] and "17:45 ET" in a["reference"]
    assert len(a["scope"]) > 30
    from lib.data_broker.catalog import PROJECTIONS

    ids = {p["id"]: p for p in PROJECTIONS}
    assert d["projection"] in ids and ids[d["projection"]]["provider_calls"] == 0


def test_store_of_record_for_finviz_enrichment_is_the_data_state_copy():
    d = DOMAINS["finviz_enrichment"]
    assert d["store"]["file"] == "state/ticker_enrichment_cache.json"
    assert d["writer"] == "scripts/finviz_enrichment.py"
    manifest = (ROOT / "scripts" / "generate_integrity_manifest.py").read_text()
    assert '"canonical_path": "data/state/ticker_enrichment_cache.json"' in manifest


def test_social_posts_is_honestly_unconsolidated_with_a_ceiling():
    d = DOMAINS["social_posts"]
    assert d["writer"] is None and d["writer_status"] == "UNCONSOLIDATED"
    assert d["writer_target"] == "scripts/social_ingest.py"
    base = json.loads((ROOT / "config" / "data_source_authority_baseline.json").read_text())
    assert base["writers"]["social_posts"] == 3 and base["writers"]["yfinance_info_snapshot"] == 1


def test_stocktwits_rate_limit_declared():
    rl = AUTH["providers"]["stocktwits"]["rate_limit"]
    assert rl["budget_per_hour"] < rl["provider_ceiling_per_hour"]
    assert "decision (14)" in rl["approval_reference"] and rl["on_429"]
    assert rl["basis"].startswith("[I]")


def test_yfinance_info_snapshot_has_exactly_one_writer_file():
    pat = re.compile(r"\b(INSERT\s+INTO|UPDATE|COPY)\s+yfinance_info_snapshot\b", re.I)
    hits = [
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "scripts").rglob("*.py")
        if "__pycache__" not in p.parts and pat.search(p.read_text(errors="replace"))
    ]
    assert hits == ["scripts/lib/writers/yfinance_info_snapshot_writer.py"]


def test_authority_gate_is_green():
    import subprocess

    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_data_source_authority.py"), "--json"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "TRADE_AI_CI": "1"},
    )
    rep = json.loads(r.stdout)
    assert rep["findings"] == [] and r.returncode == 0
    assert rep["approved"]["domains"] == rep["domains"]


# ── (13) yfinance_info_snapshot writer + projection ──────────────────────────


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.executed.append((sql, params))


def test_yf_writer_rails_and_upsert():
    from lib.writers.yfinance_info_snapshot_writer import write_info_snapshots

    cur = FakeCursor()
    aware = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)
    rec = write_info_snapshots(
        cur,
        [
            {
                "symbol": "aapl",
                "fetched_at": aware,
                "status": "ok",
                "payload": {"quoteType": "EQUITY", "sector": "Tech"},
            },
            {"symbol": "DEAD", "fetched_at": aware.isoformat(), "status": "no_profile", "payload": {}},
            {"symbol": "NAIVE", "fetched_at": datetime(2026, 10, 10, 10, 0), "status": "ok", "payload": {"a": 1}},
            {"symbol": "EMPTY", "fetched_at": aware, "status": "ok", "payload": {}},
            {"symbol": "BAD", "fetched_at": aware, "status": "maybe", "payload": {"a": 1}},
            {"symbol": "", "fetched_at": aware, "status": "ok", "payload": {"a": 1}},
        ],
        run_id="t1",
    )
    assert rec.rows_accepted == 2 and len(rec.rows_rejected) == 4
    reasons = " | ".join(r["reason"] for r in rec.rows_rejected)
    assert "naive" in reasons and "empty for status ok" in reasons and "status" in reasons
    sql, params = cur.executed[0]
    assert "ON CONFLICT (symbol)" in sql and "fetched_at <= EXCLUDED.fetched_at" in sql
    assert params[0] == "AAPL" and params[3] == "EQUITY" and json.loads(params[4])["sector"] == "Tech"


def test_yf_projection_reads_and_reports_missing_table_as_no_coverage():
    from lib.data_broker.yfinance_info import get_info_batch

    rows = [
        {
            "symbol": "AAPL",
            "fetched_at": NOW - timedelta(hours=3),
            "status": "ok",
            "quote_type": "EQUITY",
            "payload": {"sector": "Tech"},
            "payload_keys": 1,
            "error": None,
        }
    ]
    out = get_info_batch(FakeDB(rows), ["AAPL", "MSFT"], now=NOW)
    assert out["fresh"] == ["AAPL"] and out["stale_or_missing"] == ["MSFT"] and out["provider_calls"] == 0
    missing = get_info_batch(
        FakeDB(exc=RuntimeError('relation "yfinance_info_snapshot" does not exist')), ["AAPL"], now=NOW
    )
    assert missing["ok"] is False and missing["gap"]["kind"] == "no_coverage"
    assert missing["gap"]["declared_behaviour"] == "say_so"


def test_yf_projection_module_never_imports_yfinance():
    src = (ROOT / "scripts" / "lib" / "data_broker" / "yfinance_info.py").read_text()
    assert "import yfinance" not in src


# ── (5) scalp_list + social_feed projections ─────────────────────────────────


def _write_universe(tmp_path, as_of, rows):
    p = tmp_path / "data" / "trade_ai" / "scalp_universe_latest.json"
    p.parent.mkdir(parents=True)
    p.write_text(
        json.dumps(
            {
                "schema": "TradeAIScalpUniverse@v1",
                "as_of": as_of,
                "run_label": "scalp",
                "writer": "run_trade_ai_scalp_live",
                "rows": rows,
            }
        )
    )
    return p


def test_scalp_list_passes_market_fields_only(tmp_path):
    from lib.data_broker.scalp_list import get_scalp_list

    _write_universe(
        tmp_path,
        (NOW - timedelta(minutes=3)).isoformat(),
        [
            {"symbol": "abcd", "decision": "GO", "score": 91, "float_m": 4.2, "price": 3.1, "setup_class": "gap"},
            {"symbol": "ABCD", "decision": "GO"},
            {"symbol": ""},
        ],
    )
    out = get_scalp_list(root=tmp_path, now=NOW)
    assert out["symbols"] == ["ABCD"] and out["stale"] is False and out["provider_calls"] == 0
    assert out["rows"][0] == {"symbol": "ABCD", "price": 3.1, "float_m": 4.2, "setup_class": "gap"}
    assert "decision" not in out["rows"][0] and "score" not in out["rows"][0]


def test_scalp_list_stale_and_absent(tmp_path):
    from lib.data_broker.scalp_list import get_scalp_list

    assert get_scalp_list(root=tmp_path, now=NOW)["gap"]["kind"] == "no_coverage"
    _write_universe(tmp_path, (NOW - timedelta(hours=2)).isoformat(), [{"symbol": "X"}])
    assert get_scalp_list(root=tmp_path, now=NOW)["stale"] is True
    assert get_scalp_list(root=tmp_path, now=NOW, market_closed=True)["stale"] is False  # 72 h closed window


def test_social_feed_groups_posts_per_symbol():
    from lib.data_broker.social_feed import FEED_SQL, get_social_posts

    rows = [
        {
            "platform": "stocktwits",
            "post_id": "1",
            "post_date": NOW - timedelta(hours=1),
            "ingested_at": NOW - timedelta(minutes=50),
            "sentiment": "bullish",
            "sentiment_score": 0.7,
            "symbols_mentioned": ["AAPL"],
            "text": "x",
        },
        {
            "platform": "stocktwits",
            "post_id": "2",
            "post_date": NOW - timedelta(hours=2),
            "ingested_at": NOW - timedelta(hours=2),
            "sentiment": "bearish",
            "sentiment_score": -0.7,
            "symbols_mentioned": ["AAPL", "MSFT"],
            "text": "y",
        },
    ]
    out = get_social_posts(lambda sql, params: rows, ["aapl", "MSFT", "NVDA"], now=NOW)
    assert out["symbols"]["AAPL"]["count"] == 2 and out["symbols"]["AAPL"]["bullish"] == 1
    assert out["symbols"]["MSFT"]["bearish"] == 1 and out["symbols"]["NVDA"]["count"] == 0
    assert out["provider_calls"] == 0 and out["source"]["projection"] == "social_feed"
    assert "?|" in FEED_SQL


# ── (3) enrichment-cache merge tool ──────────────────────────────────────────


def _caches(tmp_path, store, copy):
    s = tmp_path / "data" / "state" / "ticker_enrichment_cache.json"
    c = tmp_path / "data" / "portfolios" / "state" / "ticker_enrichment_cache.json"
    s.parent.mkdir(parents=True)
    c.parent.mkdir(parents=True)
    s.write_text(json.dumps(store, indent=2))
    c.write_text(json.dumps(copy, indent=2))
    return s, c


def test_merge_plan_newest_per_symbol_wins_nothing_dropped():
    import merge_enrichment_cache as m

    store = {
        "A": {"cached_at": "2026-10-10T10:00:00", "rsi": 1},
        "B": {"cached_at": "2026-10-09T10:00:00", "rsi": 2},
        "S": {"cached_at": "2026-10-10T10:00:00"},
    }
    copy = {
        "A": {"cached_at": "2026-10-09T10:00:00", "rsi": 9},
        "B": {"cached_at": "2026-10-10T11:00:00", "rsi": 8},
        "C": {"cached_at": "2026-10-01T10:00:00"},
        "U": {"rsi": 5},
        "_meta": {},
    }
    p = m.plan_merge(store, copy)
    assert p["decisions"] == {"ADD": ["C"], "REPLACE": ["B"], "KEEP": ["A"], "ADD_UNDATED": ["U"]}
    assert (
        p["merged"]["A"]["rsi"] == 1 and p["merged"]["B"]["rsi"] == 8 and set(p["merged"]) == {"A", "B", "C", "S", "U"}
    )


def test_merge_dry_run_is_read_only(tmp_path, capsys):
    import merge_enrichment_cache as m

    s, c = _caches(tmp_path, {"A": {"cached_at": "2026-10-10T10:00:00"}}, {"B": {"cached_at": "2026-10-09T10:00:00"}})
    before = {p: (p.read_bytes(), p.stat().st_mtime) for p in (s, c)}
    report = tmp_path / "plan.json"
    assert m.main(["--root", str(tmp_path), "--report", str(report)]) == 0
    assert {p: (p.read_bytes(), p.stat().st_mtime) for p in (s, c)} == before
    plan = json.loads(report.read_text())
    assert plan["counts"]["ADD"] == 1 and plan["after"]["entries"] == 2 and plan["status"] == "DRY_RUN"
    assert json.loads(capsys.readouterr().out)["read_only_verified"] is True
    assert not (tmp_path / "data" / "state" / "ticker_enrichment_cache.json.lock").exists()


def test_merge_refuses_a_report_inside_the_state_tree(tmp_path):
    import merge_enrichment_cache as m

    _caches(tmp_path, {}, {})
    assert m.main(["--root", str(tmp_path), "--report", str(tmp_path / "data" / "x.json")]) == 2


def test_merge_apply_requires_grant_and_refuses_drift(tmp_path, monkeypatch):
    import merge_enrichment_cache as m

    _caches(tmp_path, {"A": {"cached_at": "2026-10-10T10:00:00"}}, {"B": {"cached_at": "2026-10-09T10:00:00"}})
    monkeypatch.setattr(m, "_archive_root", lambda: tmp_path / "archive")
    assert m.main(["--root", str(tmp_path), "--apply"]) == 2
    with pytest.raises(SystemExit, match="drifted"):
        m.apply_merge(tmp_path, "grant-x", "0" * 64)
    assert not (tmp_path / "archive").exists()


def test_merge_apply_archives_merges_through_the_writer_and_aliases(tmp_path, monkeypatch):
    import merge_enrichment_cache as m

    s, c = _caches(
        tmp_path,
        {"A": {"cached_at": "2026-10-10T10:00:00", "rsi": 1}},
        {"A": {"cached_at": "2026-10-09T10:00:00", "rsi": 9}, "B": {"cached_at": "2026-10-09T10:00:00"}},
    )
    monkeypatch.setattr(m, "_archive_root", lambda: tmp_path / "archive")
    sha = m.file_facts(c)["sha256"]
    original = c.read_bytes()
    rec = m.apply_merge(tmp_path, "grant-x", sha)
    merged = json.loads(s.read_text())
    assert set(merged) == {"A", "B"} and merged["A"]["rsi"] == 1
    assert c.is_symlink() and os.readlink(c) == m.ALIAS_TARGET and json.loads(c.read_text()) == merged
    arch = Path(rec["archive"])
    assert arch.read_bytes() == original and rec["archive_sha256"] == sha  # never deleted: archived byte-for-byte
    manifest = json.loads((arch.parent / "MANIFEST.json").read_text())
    assert manifest["items"][0]["origin"] == str(c) and manifest["items"][0]["grant_ref"] == "grant-x"
    assert rec["winners_missing_after"] == []
    assert m.build_plan(tmp_path)["status"] == "ALREADY_ALIASED"


def test_archive_root_is_on_the_tripwire_and_named_nowhere_else():
    import check_served_copy_split as cs

    assert cs.ENRICHMENT_CACHE_ARCHIVE_ROOT in cs.ARCHIVE_ROOTS
    assert cs.archive_tripwire(cs.ENRICHMENT_CACHE_ARCHIVE_ROOT, crontab_text="", unit_dir=ROOT / "nonexistent") == []


def test_orchestrator_does_not_copy_onto_the_alias():
    src = (ROOT / "scripts" / "portfolio_orchestrator.py").read_text()
    assert "if enrich_src.exists() and not enrich_dst.is_symlink():" in src
