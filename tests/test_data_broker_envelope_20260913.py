"""One Source of Truth, Phase 4 — the broker read envelope and the new projections.

Defect (measured 2026-09-13): 348 Command Center endpoints, ~335 reading stores
directly; the Sectors and Defense desks served state files 436–454h old as
current; four desks (Watch Discovery, Agents, Reports, Redeploy) rendered rows
42–131 days old with no age at all.

These tests are pure: rows are injected through a fake ``db_query``, the registry
is injected, the clock is fixed. Nothing here touches the database or the state
tree. The negative controls show a stale value is flagged and a dead feed is
declared — the two things the hubs could not say before.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.data_broker import envelope as env_mod  # noqa: E402
from lib.data_broker.envelope import envelope, load_stale_windows, newest, wrap  # noqa: E402

NOW = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)

REGISTRY = {
    "market_regime": {"domain": "market_regime", "class": "derived", "table": "market_regime_snapshots",
                      "writer": "scripts/market_regime_classifier.py", "projection": "market_regime",
                      "primary_provider": "yahoo", "stale_after_hours": 26,
                      "no_coverage": "carry_last_regime_with_date_never_neutral"},
    "technicals": {"domain": "technicals", "class": "derived", "table": "ticker_prices", "writer": None,
                   "writer_status": "UNCONSOLIDATED", "projection": "indicator_snapshot",
                   "primary_provider": "alpaca", "stale_after_hours": 26},
    "research_thesis": {"domain": "research_thesis", "class": "native", "table": "hermes_research_intelligence",
                        "writer": None, "writer_status": "UNCONSOLIDATED", "projection": "research_card",
                        "primary_provider": "internal", "stale_after_hours": 168},
    "options_iv": {"domain": "options_iv", "class": "live_external", "table": "options_iv_history",
                   "writer": "scripts/lib/strategy_research/iv_history.py", "projection": None,
                   "primary_provider": "schwab", "stale_after_hours": 4, "no_coverage": "call_out_at_read_time"},
    "sector_momentum": {"domain": "sector_momentum", "class": "derived", "table": "sector_rs_daily",
                        "file": "runtime/sector_momentum_latest.json", "writer": "scripts/sector_rs_daily.py",
                        "projection": "sector_momentum", "primary_provider": "internal:market_quotes",
                        "stale_after_hours": 26},
    "industry_momentum": {"domain": "industry_momentum", "class": "ingested",
                          "file": "runtime/industry_momentum_latest.json",
                          "writer": "scripts/finviz_industry_groups.py", "projection": "sector_momentum",
                          "primary_provider": "finviz", "stale_after_hours": 26},
    "watch_discovery": {"domain": "watch_discovery", "class": "dead_feed", "table": "watch_candidate_events",
                        "writer": None, "projection": "watch_intelligence", "primary_provider": "internal",
                        "stale_after_hours": 48, "no_coverage": "declared_gap_no_producer"},
    "quote_price": {"domain": "quote_price", "class": "ingested", "table": "market_quotes", "writer": None,
                    "writer_status": "UNCONSOLIDATED", "projection": "market_quote", "primary_provider": "alpaca",
                    "stale_after_hours": 0.25, "stale_after_hours_closed": 72},
}


class FakeDB:
    """Records every SQL it is asked and answers from a list of canned rows."""

    def __init__(self, rows=None, one=None, by_marker=None):
        self.rows = rows or []
        self.one = one
        self.by_marker = by_marker or {}
        self.calls: list[tuple[str, tuple | None, str]] = []

    def __call__(self, sql, params=None, fetch="all"):
        self.calls.append((sql, params, fetch))
        for marker, answer in self.by_marker.items():
            if marker in sql:
                return answer
        return self.one if fetch == "one" else self.rows


# ── envelope: the contract ───────────────────────────────────────────────────


def test_envelope_has_every_required_field_and_reads_the_registry_window():
    e = envelope("market_regime", NOW - timedelta(hours=3), now=NOW, registry=REGISTRY)
    for k in ("as_of", "age_hours", "source", "stale", "stale_after_hours"):
        assert k in e, k
    assert e["schema"] == "BrokerReadEnvelope@v1"
    assert e["age_hours"] == 3.0
    assert e["stale"] is False
    assert e["stale_after_hours"] == 26
    assert e["source"]["table"] == "market_regime_snapshots"
    assert e["source"]["writer"] == "scripts/market_regime_classifier.py"
    assert e["source"]["registry"] == "config/data_source_authority.json"
    assert "gap" not in e


def test_envelope_flags_stale_past_the_registry_window():
    """NEGATIVE CONTROL: the 436h Sectors snapshot must render stale, not current."""
    e = envelope("sector_momentum", NOW - timedelta(hours=436), now=NOW, registry=REGISTRY)
    assert e["stale"] is True
    assert e["age_hours"] == 436.0
    assert "gap" not in e, "436h is stale, not yet a dead feed (30d)"


def test_envelope_declares_no_coverage_when_nothing_was_read():
    e = envelope("market_regime", None, now=NOW, registry=REGISTRY)
    assert e["as_of"] is None and e["age_hours"] is None
    assert e["stale"] is True
    assert e["gap"] == {"kind": "no_coverage", "last_as_of": None,
                        "declared_behaviour": "carry_last_regime_with_date_never_neutral"}


def test_envelope_declares_no_producer_for_a_dead_feed_domain_with_last_as_of():
    """watch_discovery is class dead_feed in the registry: gap regardless of age."""
    last = datetime(2026, 7, 16, tzinfo=timezone.utc)
    e = envelope("watch_discovery", last, now=NOW, registry=REGISTRY)
    assert e["gap"]["kind"] == "no_producer"
    assert e["gap"]["last_as_of"] == "2026-07-16T00:00:00+00:00"
    assert e["stale"] is True


def test_envelope_declares_no_producer_when_silent_longer_than_dead_window():
    """agent_debate_log: 131 days silent → no_producer even though the domain is not dead_feed."""
    e = envelope("agent_debate", NOW - timedelta(days=131), now=NOW, registry=REGISTRY, stale_after_hours=168)
    assert e["stale"] is True
    assert e["gap"]["kind"] == "no_producer"
    assert e["gap"]["dead_after_hours"] == 720.0
    # a feed that comes back clears the gap on its own
    e2 = envelope("agent_debate", NOW - timedelta(hours=2), now=NOW, registry=REGISTRY, stale_after_hours=168)
    assert "gap" not in e2 and e2["stale"] is False


def test_envelope_producer_status_none_forces_the_gap():
    e = envelope("market_regime", NOW - timedelta(hours=1), now=NOW, registry=REGISTRY, producer_status="none")
    assert e["gap"]["kind"] == "no_producer"


def test_envelope_uses_closed_market_window_when_told():
    e_open = envelope("quote_price", NOW - timedelta(hours=10), now=NOW, registry=REGISTRY)
    e_closed = envelope("quote_price", NOW - timedelta(hours=10), now=NOW, registry=REGISTRY, market_closed=True)
    assert e_open["stale"] is True and e_open["stale_after_hours"] == 0.25
    assert e_closed["stale"] is False and e_closed["stale_after_hours"] == 72


def test_envelope_unregistered_domain_without_window_is_not_stale_but_says_so():
    e = envelope("nobody_declared_me", NOW - timedelta(days=400), now=NOW, registry=REGISTRY)
    assert e["stale_after_hours"] is None
    assert e["stale"] is False
    assert e["source"]["registry"] is None
    assert e["gap"]["kind"] == "no_producer"  # 400d silent still trips the dead window


def test_envelope_accepts_date_string_and_epoch():
    assert envelope("technicals", "2026-09-12", now=NOW, registry=REGISTRY)["age_hours"] == 42.0
    assert envelope("technicals", "2026-09-13T17:00:00Z", now=NOW, registry=REGISTRY)["age_hours"] == 1.0
    assert envelope("technicals", NOW.timestamp() - 7200, now=NOW, registry=REGISTRY)["age_hours"] == 2.0


def test_newest_and_wrap():
    assert newest([None, "2026-09-01", datetime(2026, 9, 2, tzinfo=timezone.utc)]) == "2026-09-02T00:00:00+00:00"
    e = envelope("technicals", NOW, now=NOW, registry=REGISTRY)
    out = wrap({"as_of": "engine-said-this", "rows": [1]}, e)
    assert out["rows"] == [1]
    assert out["as_of"] == e["as_of"]
    assert out["payload_as_of"] == "engine-said-this", "a payload's own as_of is kept, not clobbered"


def test_load_stale_windows_reads_the_real_registry():
    reg = load_stale_windows()
    assert "market_regime" in reg and reg["market_regime"]["stale_after_hours"] == 26
    assert reg["watch_discovery"]["class"] == "dead_feed"
    assert reg["options_iv"]["stale_after_hours"] == 4


def test_load_stale_windows_missing_file_is_empty_not_a_crash(tmp_path):
    assert load_stale_windows(tmp_path / "nope.json") == {}


# ── projections ──────────────────────────────────────────────────────────────


def test_market_regime_projection_latest_line_and_envelope():
    from lib.data_broker.market_regime import get_market_regime, regime_line
    rows = [
        {"snapshot_id": "s2", "regime_label": "risk_off", "trend_state": "down", "confidence": Decimal("0.72"),
         "generated_at": NOW - timedelta(hours=2), "created_at": NOW - timedelta(hours=2), "summary": "x"},
        {"snapshot_id": "s1", "regime_label": "neutral", "trend_state": "flat", "confidence": Decimal("0.5"),
         "generated_at": NOW - timedelta(hours=26), "created_at": NOW - timedelta(hours=26), "summary": "y"},
    ]
    db = FakeDB(rows=rows)
    out = get_market_regime(db, history=5, now=NOW, registry=REGISTRY)
    assert out["ok"] and out["provider_calls"] == 0
    assert out["regime"]["snapshot_id"] == "s2"
    assert out["regime"]["confidence"] == 0.72
    assert out["regime_line"] == "risk off down 72%"
    assert out["risk_off"] is True
    assert len(out["history"]) == 2
    assert out["age_hours"] == 2.0 and out["stale"] is False
    assert out["source"]["table"] == "market_regime_snapshots"
    assert "FROM market_regime_snapshots" in db.calls[0][0]
    assert regime_line(None) is None


def test_market_regime_projection_no_rows_is_no_coverage_never_neutral():
    from lib.data_broker.market_regime import get_market_regime
    out = get_market_regime(FakeDB(rows=[]), now=NOW, registry=REGISTRY)
    assert out["regime"] is None and out["regime_line"] is None
    assert out["gap"]["kind"] == "no_coverage"
    assert out["stale"] is True


def test_market_regime_projection_db_error_is_soft():
    from lib.data_broker.market_regime import get_market_regime

    def boom(*a, **k):
        raise RuntimeError("db down")

    out = get_market_regime(boom, now=NOW, registry=REGISTRY)
    assert out["ok"] is False and "db down" in out["error"]
    assert out["gap"]["kind"] == "no_coverage"


def test_daily_bars_last_close_and_series():
    from lib.data_broker.daily_bars import get_daily_bars, get_last_close
    from datetime import date
    db = FakeDB(one={"symbol": "SH", "price_date": date(2026, 9, 12), "close_price": Decimal("41.25"), "source": "alpaca"})
    lc = get_last_close(db, "sh", now=NOW, registry=REGISTRY)
    assert lc["symbol"] == "SH" and lc["close"] == 41.25 and lc["price_date"] == "2026-09-12"
    assert lc["age_hours"] == 42.0 and lc["stale"] is True  # 26h window, date-granular store
    assert lc["source"]["table"] == "ticker_prices" and lc["source"]["row_source"] == "alpaca"
    assert db.calls[0][1] == ("SH",)

    db2 = FakeDB(rows=[{"price_date": date(2026, 9, 10), "close_price": 40}, {"price_date": date(2026, 9, 11), "close_price": 41}])
    s = get_daily_bars(db2, "SH", days=30, now=NOW, registry=REGISTRY)
    assert s["n"] == 2 and s["bars"][-1] == {"price_date": "2026-09-11", "close": 41.0}
    assert s["as_of"] == "2026-09-11T00:00:00+00:00"

    empty = get_last_close(FakeDB(one=None), "ZZZ", now=NOW, registry=REGISTRY)
    assert empty["close"] is None and empty["gap"]["kind"] == "no_coverage"


def test_subject_research_by_symbol_guid_sector_read_only():
    from lib.data_broker.subject_research import get_subject_research
    import uuid
    g = uuid.uuid4()
    rows = [{"id": 1, "symbol": "NVDA", "subject_guid": g, "created_at": NOW - timedelta(hours=5),
             "confidence_score": 0.8, "thesis": "t", "tags": ["a"]}]
    db = FakeDB(rows=rows)
    out = get_subject_research(db, symbol="nvda", now=NOW, registry=REGISTRY)
    assert out["ok"] and out["read_only"] is True and out["n"] == 1
    assert out["items"][0]["subject_guid"] == str(g)
    assert out["key"] == {"symbol": "NVDA"} and out["age_hours"] == 5.0 and out["stale"] is False
    assert "upper(symbol)=%s" in db.calls[0][0]

    db2 = FakeDB(rows=rows)
    out2 = get_subject_research(db2, subject_guid=str(g), now=NOW, registry=REGISTRY)
    assert "subject_guid=%s::uuid" in db2.calls[0][0] and out2["key"] == {"subject_guid": str(g)}

    db3 = FakeDB(rows=[])
    out3 = get_subject_research(db3, sector="Technology", now=NOW, registry=REGISTRY)
    assert out3["gap"]["kind"] == "no_coverage" and db3.calls[0][1][:2] == ("Technology", "Technology")

    bad = get_subject_research(FakeDB(), now=NOW, registry=REGISTRY)
    assert bad["ok"] is False and "required" in bad["error"]
    # a stale thesis is stale even though the table is busy
    old = get_subject_research(FakeDB(rows=[{"created_at": NOW - timedelta(days=10)}]), symbol="X", now=NOW, registry=REGISTRY)
    assert old["stale"] is True


def test_agent_opinion_separates_live_results_from_dead_debates():
    from lib.data_broker.agent_opinion import get_agent_opinion
    roster = [{"agent": "maria", "total": 500, "total_30d": 40, "latest": NOW - timedelta(hours=20)}]
    db = FakeDB(by_marker={
        "FROM watchlist_agent_results\n        GROUP BY agent": roster,
        "WHERE created_at > NOW() - INTERVAL '7 days'": [{"cnt": 0, "avg_consensus": None}],
        "max(created_at) AS latest, count(*) AS n FROM agent_debate_log": {"latest": NOW - timedelta(days=131), "n": 9},
    })
    out = get_agent_opinion(db, now=NOW, registry=REGISTRY)
    assert out["roster"]["agents"] == roster
    assert out["roster"]["stale"] is False and out["roster"]["age_hours"] == 20.0
    assert "gap" not in out["roster"]
    d = out["debates"]
    assert d["count"] == 0
    assert d["gap"]["kind"] == "no_producer"
    assert d["gap"]["last_as_of"] == (NOW - timedelta(days=131)).isoformat()
    assert d["source"]["table"] == "agent_debate_log"
    # the top-level envelope is the live store's
    assert out["as_of"] == out["roster"]["as_of"] and "gap" not in out


def test_agent_opinion_composes_agent_results_for_symbols():
    from lib.data_broker.agent_opinion import get_agent_opinion
    rows = [{"symbol": "AAPL", "agent": "steph", "recommendation": "HOLD", "confidence": 0.6,
             "narrative": None, "evidence": None, "completed_at": NOW}]
    db = FakeDB(by_marker={"FROM watchlist_agent_results\n           WHERE upper(symbol) = ANY(%s)": rows,
                           "GROUP BY agent": [], "INTERVAL '7 days'": [], "count(*) AS n FROM agent_debate_log": {"latest": None}})
    out = get_agent_opinion(db, ["aapl"], now=NOW, registry=REGISTRY)
    assert out["by_symbol"]["AAPL"][0]["recommendation"] == "HOLD"
    assert out["debates"]["gap"]["kind"] == "no_coverage"


def test_option_chain_reads_store_only_and_declares_live_external():
    from lib.data_broker.option_chain import get_option_chain, LIVE_EXTERNAL_NOTE
    rows = [{"symbol": "SPY", "iv_pct": Decimal("18.4"), "atm_strike": 560, "underlying": Decimal("561.2"),
             "source": "schwab", "captured_at": NOW - timedelta(hours=30), "snapshot_date": None, "meta_json": {}}]
    db = FakeDB(rows=rows)
    out = get_option_chain(db, "spy", now=NOW, registry=REGISTRY)
    assert out["latest"]["iv_pct"] == 18.4 and out["latest"]["underlying"] == 561.2
    assert out["live_external"] == {"provider": "schwab", "called": False, "note": LIVE_EXTERNAL_NOTE}
    assert out["provider_calls"] == 0
    assert out["stale"] is True and out["stale_after_hours"] == 4 and out["age_hours"] == 30.0
    assert out["source"]["provider"] == "schwab" and out["source"]["table"] == "options_iv_history"
    assert all("FROM options_iv_history" in c[0] for c in db.calls), "only the store is read"
    none = get_option_chain(FakeDB(rows=[]), "QQQ", now=NOW, registry=REGISTRY)
    assert none["latest"] is None and none["gap"] == {"kind": "no_coverage", "last_as_of": None,
                                                     "declared_behaviour": "call_out_at_read_time"}


def test_watch_discovery_every_read_is_a_declared_dead_feed():
    from lib.data_broker import watch_discovery as wd
    from datetime import date
    db = FakeDB(one={"last_at": None, "last_on": date(2026, 7, 16), "n": 13093})
    env = wd.feed_envelope(db, now=NOW, registry=REGISTRY)
    assert env["gap"]["kind"] == "no_producer"
    assert env["gap"]["last_as_of"] == "2026-07-16T00:00:00+00:00"
    assert env["gap"]["declared_behaviour"] == "declared_gap_no_producer"
    assert env["source"]["rows"] == 13093 and env["source"]["table"] == "watch_candidate_events"
    assert env["stale"] is True and env["provider_calls"] == 0
    # the row readers are verbatim SQL, parameterised
    db2 = FakeDB(rows=[{"did": 7, "events": 3}])
    assert wd.directive_score_meta(db2) == {7: {"did": 7, "events": 3}}
    wd.directive_alpha_events(db2, 7)
    assert db2.calls[-1][1] == ("7",)
    wd.quality_gate_rows(db2, 90)
    assert db2.calls[-1][1] == (90,)


def test_sector_momentum_snapshot_readers_and_rs_history(tmp_path):
    from lib.data_broker.sector_momentum import (
        get_industry_momentum_snapshot, get_sector_momentum_snapshot, get_sector_rs_history,
    )
    from datetime import date
    stale_ts = (NOW - timedelta(hours=454)).isoformat()
    (tmp_path / "sector_momentum_latest.json").write_text(json.dumps(
        {"generated_at": stale_ts, "rows": [{"sector": "Technology", "state": "LAGGING"}]}))
    s = get_sector_momentum_snapshot(runtime_dir=tmp_path, now=NOW, registry=REGISTRY)
    assert s["snapshot"]["rows"][0]["sector"] == "Technology"
    assert s["stale"] is True and s["age_hours"] == 454.0
    assert s["source"]["file"] == "runtime/sector_momentum_latest.json"
    assert s["source"]["writer"] == "scripts/sector_rs_daily.py"
    assert "gap" not in s

    i = get_industry_momentum_snapshot(runtime_dir=tmp_path, now=NOW, registry=REGISTRY)
    assert i["snapshot"] is None and i["gap"]["kind"] == "no_coverage"
    assert i["source"]["writer"] == "scripts/finviz_industry_groups.py"

    db = FakeDB(rows=[{"symbol": "XLK", "rs_date": date(2026, 9, 10), "rs": Decimal("1.01")},
                      {"symbol": "XLK", "rs_date": date(2026, 9, 11), "rs": Decimal("1.02")}])
    h = get_sector_rs_history(db, days=95, now=NOW, registry=REGISTRY)
    assert h["series"] == {"XLK": [1.01, 1.02]}
    assert h["as_of"] == "2026-09-11T00:00:00+00:00" and h["source"]["table"] == "sector_rs_daily"
    assert db.calls[0][1] == (95,)


def test_catalog_advertises_the_phase4_projections_with_envelope():
    from lib.data_broker.catalog import PROJECTIONS
    by_id = {p["id"]: p for p in PROJECTIONS}
    for pid in ("market_regime", "daily_bars", "subject_research", "agent_opinion", "option_chain", "watch_discovery"):
        p = by_id[pid]
        assert p["read_only"] is True and p["provider_calls"] == 0, pid
        assert p["envelope"] == env_mod.SCHEMA, pid
        assert "authority_domain" in p, pid
    assert by_id["watch_discovery"]["status"] == "dead_feed"
    assert "never called" in by_id["option_chain"]["live_external"]
