"""Stored Watch row facts: pinned clocks, injected reads, no providers/DB/state access."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.data_broker import watch_market_facts as mf  # noqa: E402

NOW = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)


def quote(symbol="AAA", price=10, at=NOW):
    return {"symbol": symbol, "price": price, "fetched_at": at, "source": "schwab", "day_change_pct": 1.5}


class FakeDB:
    def __init__(self, *, quotes=None, master=None, strategy=None, closed=None, failures=(), json_pref=False):
        self.quotes = [quote()] if quotes is None else quotes
        self.master = [{"symbol": "AAA", "support": 9, "resistance": 11}] if master is None else master
        self.strategy = strategy or []
        self.closed = closed or {}
        self.failures = failures
        self.json_pref = json_pref
        self.calls = []

    def __call__(self, sql, params=None):
        name = "quotes" if "FROM market_quotes" in sql else "master" if "watchlist_symbol_master" in sql else \
            "strategy" if "watchlist_strategy_cards" in sql else "closed" if "FROM ui_prefs" in sql else "unexpected"
        self.calls.append((name, params))
        assert name != "unexpected", sql
        if name in self.failures:
            raise RuntimeError("PRIVATE_DB_FAILURE_DETAILS")
        if name == "closed":
            value = {"generated_at": (NOW + timedelta(days=1)).isoformat(), "symbols": self.closed}
            return [{"value": json.dumps(value) if self.json_pref else value}]
        return [dict(r) for r in getattr(self, name) if r["symbol"].upper() in params[0]]


def snapshot(db=None, **kwargs):
    return mf.load_snapshot(db or FakeDB(), [" aaa ", "AAA", "bbb"], now=NOW, **kwargs)


def test_one_batch_per_source_normalizes_symbols_and_never_exposes_errors():
    db = FakeDB()
    raw = snapshot(db)
    assert [name for name, _ in db.calls] == ["quotes", "master", "strategy", "closed"]
    assert all(params == (["AAA", "BBB"],) for name, params in db.calls if name != "closed")
    assert raw["provider_calls"] == 0


@pytest.mark.parametrize("age,stale", [(0, False), (900, False), (901, True), (3600, True)])
def test_stored_price_uses_existing_900_second_bound_and_original_observation(age, stale):
    at = NOW - timedelta(seconds=age)
    facts = mf.view(snapshot(FakeDB(quotes=[quote(at=at)])), "AAA", now=NOW)
    p = facts["price"]
    assert p["value"] == 10 and p["stale"] is stale and p["as_of"] == at.isoformat()
    assert p["source"] == "data_broker.latest_quote:schwab" and p["age_seconds"] == age


@pytest.mark.parametrize("at,reason", [(None, "missing or unknown"), ("2026-10-23", "missing or unknown"),
                                      ("invalid", "missing or unknown"), (NOW + timedelta(seconds=1), "future")])
def test_unknown_or_future_price_timestamp_does_not_become_fresh(at, reason):
    p = mf.view(snapshot(FakeDB(quotes=[quote(at=at)])), "AAA", now=NOW)["price"]
    assert p["value"] == 10 and p["stale"] is True and p["freshness"] == "UNKNOWN"
    assert reason in p["reason"] and p["as_of"] != NOW.isoformat()


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True])
def test_invalid_prices_and_levels_are_missing_not_fabricated(value):
    facts = mf.view(snapshot(FakeDB(quotes=[quote(price=value)], master=[{"symbol": "AAA", "support": value}])), "AAA", now=NOW)
    assert facts["price"]["value"] is None and facts["support"]["value"] is None


def test_primary_source_precedence_is_per_field_and_strategy_time_is_qualified():
    db = FakeDB(master=[{"symbol": "AAA", "support": 8, "resistance": None}],
                strategy=[{"symbol": "AAA", "support": 9, "resistance": 11, "created_at": NOW}])
    facts = mf.view(snapshot(db), "AAA", now=NOW)
    assert facts["support"]["value"] == 8 and facts["support"]["source"] == "watchlist_symbol_master"
    assert facts["support"]["as_of"] is None and facts["support"]["stale"] is None
    assert facts["resistance"]["value"] == 11 and facts["resistance"]["source"] == "watchlist_strategy_cards"
    assert facts["resistance"]["as_of"] == NOW.isoformat() and facts["resistance"]["as_of_basis"] == "strategy card created_at"


@pytest.mark.parametrize("json_pref", [False, True])
def test_crossed_primary_falls_back_and_closed_date_is_never_cache_generation_time(json_pref):
    db = FakeDB(master=[{"symbol": "AAA", "support": 12, "resistance": 8}],
                strategy=[{"symbol": "AAA", "support": 9, "resistance": 9, "created_at": NOW}],
                closed={"aaa": {"resistance": 11, "state": "BELOW", "as_of": "2026-10-22"}}, json_pref=json_pref)
    facts = mf.view(snapshot(db), "AAA", now=NOW)
    assert facts["support"]["value"] == 9 and "above the shown price" in facts["support"]["reason"]
    r = facts["resistance"]
    assert r["value"] == 11 and r["source"] == "ui_prefs:" + mf.RESISTANCE_KEY
    assert r["as_of"] == "2026-10-22" and r["source_state"] == "BELOW" and r["freshness"] == "UNKNOWN"
    assert "below the shown price" in r["reason"]


def test_cache_support_targets_stops_and_averages_never_become_support():
    db = FakeDB(master=[{"symbol": "AAA", "target_price": 14, "stop_loss": 8, "sma20": 9}],
                closed={"AAA": {"support": 9, "resistance": 12, "as_of": "2026-10-22"}})
    facts = mf.view(snapshot(db), "AAA", now=NOW)
    assert facts["support"]["value"] is None and facts["resistance"]["value"] == 12


def test_missing_price_retains_known_levels_with_unknown_nearest_relation():
    facts = mf.view(snapshot(FakeDB(quotes=[])), "AAA", now=NOW)
    assert facts["price"]["value"] is None and facts["price"]["reason"]
    for kind, value in (("support", 9), ("resistance", 11)):
        assert facts[kind]["value"] == value and facts[kind]["compatibility"] == "UNKNOWN"
        assert "nearest-level relation is unknown" in facts[kind]["reason"]


@pytest.mark.parametrize("failed", ["quotes", "master", "strategy", "closed"])
def test_independent_source_failure_keeps_other_evidence_and_sanitizes_reason(failed):
    db = FakeDB(strategy=[{"symbol": "AAA", "support": 8, "resistance": 12, "created_at": NOW}], failures={failed})
    raw = snapshot(db); facts = mf.view(raw, "AAA", now=NOW)
    assert "PRIVATE_DB_FAILURE_DETAILS" not in json.dumps([raw, facts], default=str)
    assert facts["support"]["value"] is not None
    assert facts["price"]["value"] == (None if failed == "quotes" else 10)
    if failed == "master":
        assert facts["support"]["source"] == "watchlist_strategy_cards" and "read unavailable" in facts["support"]["reason"]


def test_complete_canonical_quote_artifact_is_preserved_without_splicing_or_inventing_identity():
    from lib.watch_canonical_quote import compose_quote_artifact

    artifact = compose_quote_artifact(symbol="AAA", mq_id=None, mq_price=None, mq_fetched_at=None,
        mq_source=None, mq_day_change_pct=None, wi_id=41, wi_price=20, wi_last_enriched_at=NOW, wi_change_pct=7, now=NOW)
    raw = snapshot(cards={"AAA": artifact})
    saved = deepcopy(raw)
    p = mf.view(raw, "AAA", now=NOW)["price"]
    assert p["value"] == 20 and p["source"] == "enrichment" and p["quote_artifact"]["quote_id"] == "enrichment:41"
    assert p["quote_artifact"]["source_record_id"] == artifact["source_record_id"]
    assert p["quote_artifact"]["day_change_pct"] == 7 and raw == saved
    old = mf.view(raw, "AAA", now=NOW + timedelta(hours=3))["price"]
    assert old["stale"] is True and old["as_of"] == p["as_of"] and old["quote_artifact"] == p["quote_artifact"]


def test_canonical_identity_failure_is_not_masked_by_projection_fallback():
    from lib.watch_canonical_quote import compose_quote_artifact

    artifact = compose_quote_artifact(symbol="AAA", mq_id=None, mq_price=20, mq_fetched_at=NOW,
        mq_source="alpaca", mq_day_change_pct=7, wi_id=None, wi_price=None, wi_last_enriched_at=None, wi_change_pct=None, now=NOW)
    raw = snapshot(cards={"AAA": artifact})
    p = mf.view(raw, "AAA", now=NOW)["price"]
    assert p["value"] is None and "identity" in p["reason"]


def test_generic_partial_card_provenance_does_not_suppress_stored_quote_fallback():
    raw = snapshot(cards={"AAA": {"last": 2, "price_source": "legacy cache", "freshness_state": "STALE", "quote_id": None}})
    p = mf.view(raw, "AAA", now=NOW)["price"]
    assert p["value"] == 10 and p["source"] == "data_broker.latest_quote:schwab" and p["quote_artifact"] is None


def test_canonical_source_label_exposes_existing_upstream_provider():
    raw = snapshot(cards={"AAA": {"last": 20, "price_source": "market_quotes", "source_record_id": "market_quotes:fixture",
                                  "price_as_of": NOW, "mq_source": "alpaca", "quote_id": 1}})
    p = mf.view(raw, "AAA", now=NOW)["price"]
    assert p["source"] == "market_quotes" and "alpaca" in p["source_label"]


@pytest.mark.parametrize("symbols", [["bad"], "bad", {"AAA": ["bad"]}, {"AAA": "bad"}])
def test_malformed_preference_map_or_record_degrades_without_losing_quote(symbols):
    class Malformed(FakeDB):
        def __call__(self, sql, params=None):
            if "FROM ui_prefs" in sql:
                return [{"value": {"symbols": symbols}}]
            return super().__call__(sql, params)

    facts = mf.view(snapshot(Malformed(master=[])), "AAA", now=NOW)
    assert facts["price"]["value"] == 10 and facts["resistance"]["value"] is None
    assert "data invalid" in facts["resistance"]["reason"]


def test_shared_gather_cache_keeps_observation_and_request_view_recalculates_staleness(monkeypatch):
    from lib.data_broker import watch_curation as wc, watch_domains as wd, watch_position_facts as pf, watch_prospects as wp

    observed = NOW - timedelta(seconds=880)
    db = FakeDB(quotes=[quote(at=observed), quote("NONE", at=observed)])
    record = {"symbol": "AAA", "security_guid": "guid-fixture", "issuer_guid": "issuer-fixture", "stage": "held",
              "conviction": 65, "stance": "HOLD", "evidence_at": NOW.isoformat(), "conflicts": []}
    monkeypatch.setattr(wp, "_cio_prospect_records", lambda: ([record], "store"))
    monkeypatch.setattr(wp, "_operator_membership", lambda: {"names": {s: {"starred": True, "reasons": []} for s in ["AAA", "NONE"]}})
    monkeypatch.setattr(wp, "_curator_projection", lambda: {"items": {"UNRELATED": {"rank": 1}}})
    monkeypatch.setattr(wd, "held_positions", lambda **kw: {})
    monkeypatch.setattr(wd, "held_detail_public", lambda x: x)
    monkeypatch.setattr(pf, "load", lambda **kw: {"facts_for": lambda s: {"position_state": "held"}})
    monkeypatch.setattr(pf, "public", lambda x: {"status": "fixture"})
    monkeypatch.setattr(wp.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(wc, "read_dismissed", lambda: ({}, "ok"))
    wp._CACHE.update(at=0, val=None)
    try:
        g = wp.gather({"fresh": "1"}, db_query=db, now=NOW)
        assert db.calls[0][1] == (["AAA", "NONE"],)  # not the full curator population
        original = deepcopy(g["row_for"]("AAA"))
        early = wc.list_watch_curation(now=NOW)
        monkeypatch.setattr(wp.time, "monotonic", lambda: 130.0)
        late = wc.list_watch_curation(now=NOW + timedelta(seconds=30))
        by = lambda p: {r["symbol"]: r for r in p["my_watchlist"]["rows"]}
        assert not by(early)["AAA"]["market_facts"]["price"]["stale"]
        assert by(late)["AAA"]["market_facts"]["price"]["stale"]
        assert by(late)["AAA"]["market_facts"]["price"]["as_of"] == observed.isoformat()
        assert by(late)["NONE"]["market_facts"]["price"]["value"] == 10
        assert by(late)["AAA"]["security_guid"] == "guid-fixture"
        assert g["row_for"]("AAA") == original and len(db.calls) == 4
        # A cached composition clock must not make a request's current quote appear future/stale.
        g["now"] = NOW - timedelta(days=3)
        current = wc.build_curation(g, now=NOW)
        assert not by(current)["AAA"]["market_facts"]["price"]["stale"]
        assert by(current)["AAA"]["market_facts"]["price"]["as_of"] == observed.isoformat()
    finally:
        wp._CACHE.update(at=0, val=None)
