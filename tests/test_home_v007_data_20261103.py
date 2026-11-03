"""Synthetic approved Home v007 stored-data contract; no real holdings or calls.
ANCHOR: HOME_V007_DATA_20261103
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = Path(
    os.environ.get("HOME_V007_MODULE", str(ROOT / "scripts/lib/market_risk_home_context.py"))
)
NOW = datetime(2032, 3, 9, 21, 0, tzinfo=timezone.utc)
ASOF = "2032-03-09T20:59:00Z"


@pytest.fixture
def mod(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real external process or network forbidden")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    spec = importlib.util.spec_from_file_location("home_v007_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def projection():
    return {
        "as_of": ASOF,
        "score": 56,
        "tier": "YELLOW",
        "categories": [],
        "positions": {},
        "history": [{"as_of": "2032-03-09T20:00:00Z", "score": 51, "tier": "YELLOW"}],
        "reentry_watch": {
            "SYNX": {
                "exit_date": "2032-03-01",
                "exit_price": 10,
                "as_of": ASOF,
                "stance": "RE_ENTER_IF",
                "headline": "Two recorded conditions remain",
                "stages": {"sma10": 11, "sma20": 12, "invalidation_level": 9},
                "current_quote": {
                    "price": 12,
                    "prev_close": 11,
                    "volume": 200,
                    "session": "regular_close",
                    "session_date": "2032-03-09",
                    "as_of": ASOF,
                    "source": "synthetic_daily_close",
                },
            }
        },
    }


def test_current_observation_is_separate_from_stage_close_and_inputs_unchanged(mod):
    p = projection()
    p["reentry_watch"]["SYNX"]["stages"]["last_close"] = 7
    before = deepcopy(p)
    result = mod.build(p, {}, now=NOW)
    symbol = result["symbols"]["SYNX"]
    assert symbol["quote"]["value"] == 12 and symbol["quote"]["session"] == "regular_close"
    assert symbol["day_change"]["value"]["price"] == 1
    assert symbol["since_exit"]["value"]["distance_pct"] == 20
    assert symbol["analysis_references"]["value"]["invalidation_level"]["reference_price"] == 9
    assert p == before and result["advisory_only"] is True


def test_missing_values_are_unknown_with_remediation_never_zero_samples(mod):
    p = projection()
    p["reentry_watch"]["SYNX"].pop("current_quote")
    symbol = mod.build(p, {}, now=NOW)["symbols"]["SYNX"]
    for field in ("quote", "day_change", "since_exit", "volume_vs_20d", "headlines", "next_event"):
        assert symbol[field]["value"] is None and symbol[field]["state"] == "unknown"
        assert symbol[field]["remediation"]["action"]


def test_future_or_unzoned_quote_never_becomes_current(mod):
    p = projection()
    p["reentry_watch"]["SYNX"].pop("current_quote")
    rows = [
        {"symbol": "SYNX", "price": 99, "as_of": "2032-03-09T22:00:00Z"},
        {"symbol": "SYNX", "price": 88, "as_of": "2032-03-09T20:50:00"},
    ]
    assert mod.build(p, {}, quotes=rows, now=NOW)["symbols"]["SYNX"]["quote"]["value"] is None


def test_volume_uses_twenty_completed_sessions_and_labels_actual_input(mod):
    p = projection()
    rows = []
    for index in range(20):
        rows.append(
            {
                "symbol": "SYNX",
                "date": (NOW.date() - timedelta(days=index + 1)).isoformat(),
                "volume": 100,
                "close": 10,
                "source": "synthetic_bars",
            }
        )
    rows.append({"symbol": "SYNX", "date": "2032-03-09", "volume": 999999, "close": 12, "provisional": True})
    volume = mod.build(p, {}, daily_bars=rows, now=NOW)["symbols"]["SYNX"]["volume_vs_20d"]
    assert volume["value"]["volume"] == 200 and volume["value"]["average_volume_20d"] == 100
    assert volume["value"]["ratio"] == 2 and volume["value"]["sample_sessions"] == 20
    assert volume["value"]["average_end_date"] < "2032-03-09"
    rows.pop(0)
    assert mod.build(p, {}, daily_bars=rows, now=NOW)["symbols"]["SYNX"]["volume_vs_20d"]["value"] is None


def test_all_nine_category_chips_survive_missing_measurement(mod):
    p = projection()
    p["categories"] = [
        {"category": "technical", "state": "STRESS", "as_of": ASOF, "score": 80},
        {"category": "breadth", "state": "UNKNOWN", "as_of": ASOF, "detail": "collector unavailable"},
    ]
    result = mod.build(p, {}, now=NOW)["risk"]
    assert len(result["categories"]) == 9
    by_key = {row["category"]: row for row in result["categories"]}
    assert by_key["technical"]["chip"] == "STRESS"
    assert by_key["breadth"]["state"] == "unknown" and by_key["breadth"]["remediation"]
    assert result["score_change"] == 5


def test_news_and_event_source_clock_is_not_fabricated_from_render_time(mod):
    p = projection()
    result = mod.build(
        p,
        {},
        headlines={"SYNX": {"rows": [{"title": "SYNX synthetic event"}]}},
        events={"SYNX": {"value": {"date": "2032-03-12"}}},
        now=NOW,
    )
    for field in ("headlines", "next_event"):
        assert result["symbols"]["SYNX"][field]["as_of"] is None
        assert result["symbols"]["SYNX"][field]["state"] == "unknown"


def test_budget_clear_condition_is_description_and_unverified_write_is_unavailable(mod):
    joined = {
        "budgets_detail": [
            {
                "budget": "single_sector_pct",
                "actual": 40,
                "limit": 30,
                "unit": "%",
                "account_label": "Synthetic account",
            }
        ]
    }
    row = mod.build(projection(), joined, now=NOW)["budgets"][0]
    assert row["plain_breach"] == "single sector pct is above its recorded limit"
    assert row["clears_when"] == "single sector pct is at or below 30%"
    assert row["operator_decision"]["state"] == "unavailable" and row["operator_decision"]["requires_operator"]
    assert joined["budgets_detail"][0]["limit"] == 30


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), None, "missing"])
def test_invalid_numeric_values_do_not_become_zero(mod, bad):
    assert mod.number(bad) is None


class StoredReader:
    def __init__(self):
        self.calls = []

    def regular_session_quotes(self, symbols, *, end):
        self.calls.append("regular_session_quotes")
        return {
            "SYNX": {
                "schema": "ReentryRegularQuote@v1",
                "status": "available",
                "price": 12,
                "source": "market_quotes:alpaca",
                "session": "regular",
                "session_date": "2032-03-09",
                "as_of": ASOF,
            }
        }

    def extended_quotes(self, symbols, *, start, end):
        self.calls.append("extended_quotes")
        return []

    def daily_bars(self, symbols, *, sessions, end):
        self.calls.append("daily_bars")
        return [
            {
                "symbol": "SYNX",
                "date": (NOW.date() - timedelta(days=index + 1)).isoformat(),
                "volume": 100,
                "close": 11,
                "source": "synthetic_daily",
            }
            for index in range(20)
        ]


def test_canonical_adapter_joins_exact_observation_fields_and_guarded_news(mod):
    reader = StoredReader()
    queries = []

    def read(sql, params):
        assert sql.startswith("SELECT ") and not any(word in sql for word in ("INSERT ", "UPDATE ", "DELETE "))
        queries.append(sql)
        if "FROM market_quotes " in sql:
            return [{"symbol": "SYNX", "price": 12, "prev_close": 11, "volume": 200, "fetched_at": ASOF}]
        if "FROM news_articles " in sql:
            return [
                {
                    "symbol": "SYNX",
                    "title": "SYNX announces synthetic product update",
                    "published_at": ASOF,
                    "source": "synthetic",
                    "source_url": "https://example.invalid/news",
                },
                {
                    "symbol": "SYNX",
                    "title": "Unrelated issuer reports results",
                    "published_at": ASOF,
                    "source": "synthetic",
                },
            ]
        return [{"symbol": "SYNX", "next_earnings_date": "2032-03-12", "updated_at": ASOF}]

    p = projection()
    p["reentry_watch"]["SYNX"].pop("current_quote")
    result = mod.collect(p, {}, reader=reader, read_rows=read, now=NOW)
    row = result["symbols"]["SYNX"]
    assert row["quote"]["value"] == 12 and row["volume_vs_20d"]["value"]["ratio"] == 2
    assert len(row["headlines"]["value"]) == 1 and row["headlines"]["value"][0]["guarded"] is True
    assert row["next_event"]["value"]["date"] == "2032-03-12"
    assert reader.calls == ["regular_session_quotes", "extended_quotes", "daily_bars"]
    assert len(queries) == 3 and result["read_errors"] == []


def test_different_quote_snapshot_cannot_supply_volume(mod):
    p = projection()
    p["reentry_watch"]["SYNX"].pop("current_quote")

    def read(sql, params):
        if "FROM market_quotes " in sql:
            return [
                {"symbol": "SYNX", "price": 12, "prev_close": 11, "volume": 999, "fetched_at": "2032-03-09T20:58:00Z"}
            ]
        return []

    result = mod.collect(p, {}, reader=StoredReader(), read_rows=read, now=NOW)
    assert result["symbols"]["SYNX"]["volume_vs_20d"]["state"] == "unknown"


def test_each_source_failure_is_typed_and_does_not_echo_private_diagnostic(mod):
    class Broken:
        def regular_session_quotes(self, *args, **kwargs):
            raise RuntimeError("SYNTHETIC_PRIVATE_DIAGNOSTIC")

        extended_quotes = daily_bars = regular_session_quotes

    def read(*args):
        raise RuntimeError("SYNTHETIC_PRIVATE_DIAGNOSTIC")

    result = mod.collect(projection(), {}, reader=Broken(), read_rows=read, now=NOW)
    assert len(result["read_errors"]) == 5 and all(row["reason"] == "RuntimeError" for row in result["read_errors"])
    assert "SYNTHETIC_PRIVATE_DIAGNOSTIC" not in str(result)
    assert result["symbols"]["SYNX"]["quote"]["value"] == 12  # existing snapshot observation survives


def test_next_evaluation_uses_declared_schedule_and_names_its_limit(mod):
    registry = {
        "lanes": [
            {
                "lane_id": "market-risk-evaluate",
                "state": "ACTIVE",
                "scheduler": {"kind": "cron", "expression": "*/10 * * * *", "timezone": "UTC"},
            }
        ]
    }
    assert mod.next_declared_evaluation(registry, now=NOW) == "2032-03-09T21:10:00Z"
    registry["lanes"][0]["state"] = "PAUSED"
    assert mod.next_declared_evaluation(registry, now=NOW) is None


def test_extended_price_day_move_uses_previous_session_close_not_afterhours_reference(mod):
    p = projection()
    p["reentry_watch"]["SYNX"].pop("current_quote")
    quotes = [
        {
            "symbol": "SYNX",
            "price": 13,
            "prev_close": 12,
            "session": "afterhours",
            "session_date": "2032-03-09",
            "as_of": "2032-03-09T21:00:00Z",
            "source": "market_quotes_extended:synthetic",
        }
    ]
    bars = [{"symbol": "SYNX", "date": "2032-03-08", "close": 10}]
    row = mod.build(p, {}, quotes=quotes, daily_bars=bars, now=NOW)["symbols"]["SYNX"]
    assert row["day_change"]["value"]["pct"] == 30 and row["day_change"]["reference_session_date"] == "2032-03-08"


def test_canonical_cio_identity_age_and_source_are_distinct_from_risk_advice(mod):
    p = projection()
    canonical = {
        "SYNX": {
            "identity_status": "CONFIRMED",
            "stance": "WATCH",
            "conviction": 71,
            "as_of": ASOF,
            "inputs_as_of": "2032-03-09T20:00:00Z",
            "stale": True,
            "source": {"kind": "shadow"},
        }
    }
    row = mod.build(p, {}, cio_stances=canonical, now=NOW)["symbols"]["SYNX"]
    assert row["cio"]["value"]["stance"] == "WATCH" and row["cio"]["value"]["stale"] is True
    assert row["cio"]["source"] == "cio_prospect:shadow" and row["cio"]["age_seconds"] == 3600
    assert row["conviction"]["value"] == 71
    assert row["market_risk_stance"]["value"]["stance"] == "RE_ENTER_IF"
    canonical["SYNX"]["identity_status"] = "UNRESOLVED"
    assert mod.build(p, {}, cio_stances=canonical, now=NOW)["symbols"]["SYNX"]["cio"]["state"] == "unknown"


def test_stored_stop_distance_never_creates_or_changes_a_stop(mod):
    joined = {
        "book_exposure": {"rows": [{"symbol": "SYNX", "account_label": "Synthetic account", "pct_account": 8}]},
        "observed_stops": [
            {
                "symbol": "SYNX",
                "account_label": "Synthetic account",
                "price": 9,
                "as_of": ASOF,
                "source": "stored_stop",
                "status": "recorded",
            }
        ],
    }
    before = deepcopy(joined)
    row = mod.build(projection(), joined, now=NOW)["positions"][0]
    assert row["stop"]["value"]["stored_price"] == 9 and row["stop"]["value"]["distance_price"] == 3
    assert row["stop"]["value"]["distance_pct_of_price"] == 25
    assert joined == before
    joined["observed_stops"][0]["price"] = -1
    assert mod.build(projection(), joined, now=NOW)["positions"][0]["stop"]["state"] == "unknown"
    joined["observed_stops"] = None
    assert mod.build(projection(), joined, now=NOW)["positions"][0]["stop"]["state"] == "unknown"
    joined["observed_stops"] = []
    assert mod.build(projection(), joined, now=NOW)["positions"][0]["stop"]["value"]["status"] == "not_recorded"


def test_budget_source_binding_changes_with_measurement_or_source_head(mod):
    p = projection()
    row = {"budget": "synthetic_budget", "account_label": "Synthetic account", "actual": 40, "limit": 30, "unit": "%"}
    first = mod.budget_source_binding(row, p)
    row["actual"] = 41
    assert mod.budget_source_binding(row, p)["sha256"] != first["sha256"]
    row["actual"] = 40
    p["as_of"] = "2032-03-09T20:58:00Z"
    assert mod.budget_source_binding(row, p)["sha256"] != first["sha256"]


def test_fresh_unavailable_quote_does_not_fall_back_to_cached_previous_session_or_old_extended(mod):
    p = projection()
    p["reentry_watch"]["SYNX"]["current_quote"].update(
        session_date="2032-03-08", expected_session_date="2032-03-08", as_of="2032-03-08T20:59:00Z"
    )
    rows = [
        {
            "symbol": "SYNX",
            "status": "unavailable",
            "price": None,
            "session": "regular",
            "expected_session_date": "2032-03-09",
            "observed_at": mod.iso(NOW),
            "source": "market_quotes:alpaca",
            "reason": "Current regular session observation missing",
        },
        {
            "symbol": "SYNX",
            "price": 99,
            "session": "afterhours",
            "session_date": "2032-03-08",
            "as_of": "2032-03-08T21:10:00Z",
            "source": "market_quotes_extended:synthetic",
        },
    ]
    quote = mod.build(p, {}, quotes=rows, now=NOW)["symbols"]["SYNX"]["quote"]
    assert quote["state"] == "unknown" and quote["value"] is None
    assert (
        quote["expected_session_date"] == "2032-03-09"
        and quote["reason"] == "Current regular session observation missing"
    )


def test_hedge_progress_uses_existing_thresholds_and_momentum_source_clock(mod):
    joined = {
        "hedge": {
            "momentum_as_of": ASOF,
            "thresholds": {"index_trigger_lagging_sectors": 4, "trigger_book_pct": 25},
            "lagging_count": 2,
            "largest_weakening": {"label": "Synthetic sector", "pct_invested": 10},
        }
    }
    result = mod.build(projection(), joined, now=NOW)["hedge"]
    assert result["lagging_progress"]["value"]["ratio"] == 0.5
    assert result["exposure_progress"]["value"]["ratio"] == 0.4
    assert result["exposure_progress"]["as_of"] == ASOF
    assert joined["hedge"]["thresholds"]["trigger_book_pct"] == 25


def load_join():
    spec = importlib.util.spec_from_file_location(
        "home_v007_actual_join", ROOT / "scripts/lib/market_risk_book_join.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_actual_join_helper_establishes_readonly_before_using_canonical_reader(mod, monkeypatch):
    from types import SimpleNamespace

    join = load_join()
    events = []

    class Conn:
        readonly = False

        def set_session(self, *, readonly):
            self.readonly = readonly
            events.append("readonly")

        def close(self):
            events.append("closed")

    conn = Conn()

    class Reader(StoredReader):
        def __init__(self, *, conn_factory):
            super().__init__()
            self.conn = conn_factory()
            assert self.conn.readonly

        def _rows(self, sql, params):
            assert self.conn.readonly and sql.startswith("SELECT ")
            return []

        def close(self):
            self.conn.close()

    def stances(symbols, **kwargs):
        assert kwargs["market_closed"] is True and "db_query" in kwargs
        events.append("cio_truth")
        return {}

    modules = {
        "market_risk_home_context": mod,
        "market_risk.reader": SimpleNamespace(PgReader=Reader),
        "cio_truth": SimpleNamespace(stances_for_symbols=stances),
        "market_risk.sessions": mod.sessions,
    }
    monkeypatch.setattr(join, "_import", lambda name: modules[name])

    def get_conn(**kwargs):
        assert kwargs["connect_timeout"] <= 10
        return conn

    result = join.home_context(projection(), {}, policy={}, now=NOW, get_conn=get_conn)
    assert result["schema"] == mod.SCHEMA and result["symbols"]["SYNX"]["quote"]["value"] == 12
    assert events == ["readonly", "cio_truth", "closed"]


def test_join_source_connection_without_readonly_capability_is_refused(mod, monkeypatch):
    join = load_join()
    closed = []

    class Unsafe:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        join,
        "_import",
        lambda name: (
            mod if name == "market_risk_home_context" else pytest.fail("Unsafe reader must not be constructed")
        ),
    )
    result = join.home_context(projection(), {}, policy={}, now=NOW, get_conn=lambda **kwargs: Unsafe())
    assert closed == [True] and result["read_errors"][0]["reason"] == "RuntimeError"


def test_display_only_inverse_funds_do_not_create_false_exit_or_cio_gaps(mod):
    result = mod.build(projection(), {}, now=NOW)
    for symbol in mod.INVERSE_DISPLAY_SYMBOLS:
        for field in ("since_exit", "analysis_references", "volume_vs_20d", "cio", "cio_reason", "conviction"):
            assert result["symbols"][symbol][field]["state"] == "not_applicable"
        assert not any(
            row["symbol"] == symbol and row["field"] in ("since_exit", "cio", "conviction") for row in result["gaps"]
        )


def test_existing_reader_error_marker_is_not_misreported_as_empty_extended_success(mod):
    reader = StoredReader()
    reader.extended_quotes_error = "SYNTHETIC_PRIVATE_SOURCE_DETAIL"
    result = mod.collect(projection(), {}, reader=reader, now=NOW)
    assert len(result["read_errors"]) == 1 and result["read_errors"][0]["source"] == "market_quotes_extended"
    assert "SYNTHETIC_PRIVATE_SOURCE_DETAIL" not in str(result)


def test_rollback_failure_is_retained_separately_without_private_text(mod):
    class Conn:
        def rollback(self):
            raise OSError("SYNTHETIC_PRIVATE_ROLLBACK")

    class Broken(StoredReader):
        _conn = Conn()

        def regular_session_quotes(self, *args, **kwargs):
            raise RuntimeError("SYNTHETIC_PRIVATE_PRIMARY")

    result = mod.collect(projection(), {}, reader=Broken(), now=NOW)
    assert {row["source"] for row in result["read_errors"]} == {
        "regular_session_quotes.transaction_rollback",
        "regular_session_quotes",
    }
    assert "SYNTHETIC_PRIVATE" not in str(result)


class FailedCurrentReader:
    def regular_session_quotes(self, *args, **kwargs):
        raise RuntimeError("synthetic current reader unavailable")

    def extended_quotes(self, *args, **kwargs):
        return []

    def daily_bars(self, *args, **kwargs):
        return []


@pytest.mark.parametrize("mode", ["failed_reader", "missing_reader", "build_fallback"])
def test_calendar_rejects_yesterday_cache_even_when_current_reader_has_no_observation(mod, mode):
    now = datetime(2032, 3, 9, 19, tzinfo=timezone.utc)
    p = projection()
    p["as_of"] = "2032-03-09T18:59:00Z"
    p["reentry_watch"]["SYNX"]["current_quote"].update(
        session="regular_close",
        session_date="2032-03-08",
        expected_session_date="2032-03-08",
        as_of="2032-03-08T21:00:00Z",
    )
    if mode == "build_fallback":
        result = mod.build(p, {}, now=now)
    else:
        reader = FailedCurrentReader()
        if mode == "missing_reader":
            reader.regular_session_quotes = None
        result = mod.collect(p, {}, reader=reader, now=now)
        assert any(error["source"] == "regular_session_quotes" for error in result["read_errors"])
    quote = result["symbols"]["SYNX"]["quote"]
    assert quote["state"] == "unknown" and quote["value"] is None and quote["remediation"]
    assert quote["expected_session_date"] == "2032-03-09"


@pytest.mark.parametrize(
    "now_text,cached_date,clock,expected,available",
    [
        ("2032-03-09T14:29:00Z", "2032-03-08", "2032-03-08T21:00:00Z", "2032-03-08", True),
        ("2032-03-09T14:30:00Z", "2032-03-08", "2032-03-08T21:00:00Z", "2032-03-09", False),
        ("2032-03-09T19:00:00Z", "2032-03-09", "2032-03-09T18:59:00Z", "2032-03-09", True),
        ("2032-03-13T15:00:00Z", "2032-03-12", "2032-03-12T21:00:00Z", "2032-03-12", True),
        ("2026-11-26T19:00:00Z", "2026-11-25", "2026-11-25T21:00:00Z", "2026-11-25", True),
    ],
)
def test_calendar_cache_boundary_preserves_last_regular_context_and_same_session(
    mod, now_text, cached_date, clock, expected, available
):
    now = datetime.fromisoformat(now_text.replace("Z", "+00:00"))
    p = projection()
    p["as_of"] = clock
    p["reentry_watch"]["SYNX"]["current_quote"].update(
        session="regular", session_date=cached_date, expected_session_date=cached_date, as_of=clock
    )
    quote = mod.collect(p, {}, reader=FailedCurrentReader(), now=now)["symbols"]["SYNX"]["quote"]
    assert quote["expected_session_date"] == expected
    assert (quote["state"] == "measured") is available
    assert quote["value"] == (12 if available else None)


@pytest.mark.parametrize("rejection", ["reason", "status", "future", "unclocked"])
def test_rejected_quote_cannot_supply_any_measured_price_derivative(mod, rejection):
    p = projection()
    quote = p["reentry_watch"]["SYNX"]["current_quote"]
    if rejection == "reason":
        quote["reason"] = "synthetic quote source unavailable"
    elif rejection == "status":
        quote["status"] = "unavailable"
    elif rejection == "future":
        quote["as_of"] = "2032-03-09T22:00:00Z"
    else:
        quote["as_of"] = "2032-03-09T20:59:00"
    bars = [
        {"symbol": "SYNX", "date": (NOW.date() - timedelta(days=i + 1)).isoformat(), "volume": 100, "close": 11}
        for i in range(20)
    ]
    joined = {
        "book_exposure": {"rows": [{"symbol": "SYNX", "account_label": "Synthetic account"}]},
        "observed_stops": [
            {"symbol": "SYNX", "account_label": "Synthetic account", "price": 9, "as_of": ASOF, "source": "stored_stop"}
        ],
    }
    result = mod.build(p, joined, daily_bars=bars, now=NOW)
    row = result["symbols"]["SYNX"]
    assert row["quote"]["state"] == "unknown" and row["quote"]["value"] is None
    for field in ("day_change", "since_exit", "analysis_references", "volume_vs_20d"):
        assert row[field]["state"] == "unknown" and row[field]["value"] is None and row[field]["remediation"]
    assert result["positions"][0]["stop"]["state"] == "unknown"


@pytest.mark.parametrize("path", ["build", "failed_reader"])
def test_relabelled_yesterday_clock_never_becomes_current_or_supplies_derivatives(mod, path):
    # Whole-PR reviewer R1: labels claim today, independent observation clock is yesterday.
    now = datetime(2032, 3, 9, 19, tzinfo=timezone.utc)
    p = projection()
    p["reentry_watch"]["SYNX"]["current_quote"].update(
        session="regular", session_date="2032-03-09", expected_session_date="2032-03-09",
        as_of="2032-03-08T21:00:00Z",
    )
    result = mod.build(p, {}, now=now) if path == "build" else mod.collect(
        p, {}, reader=FailedCurrentReader(), now=now
    )
    row = result["symbols"]["SYNX"]
    assert row["quote"]["expected_session_date"] == "2032-03-09"
    for field in ("quote", "day_change", "since_exit", "analysis_references", "volume_vs_20d"):
        assert row[field]["state"] == "unknown" and row[field]["value"] is None
        assert row[field]["reason"] and row[field]["remediation"]


@pytest.mark.parametrize(
    "now_text,session_day,observed,accepted",
    [
        ("2032-03-09T19:00:00Z", "2032-03-09", "2032-03-09T14:30:00Z", True),
        ("2032-03-09T19:00:00Z", "2032-03-09", "2032-03-09T14:29:59Z", False),
        ("2032-03-09T22:00:00Z", "2032-03-09", "2032-03-09T21:00:59.999999Z", True),
        ("2032-03-09T22:00:00Z", "2032-03-09", "2032-03-09T21:01:00Z", False),
        ("2026-11-27T19:00:00Z", "2026-11-27", "2026-11-27T18:00:59.999999Z", True),
        ("2026-11-27T19:00:00Z", "2026-11-27", "2026-11-27T18:01:00Z", False),
        ("2032-03-13T15:00:00Z", "2032-03-12", "2032-03-13T14:00:00Z", False),
    ],
)
def test_regular_quote_observation_clock_matches_actual_calendar_window(
    mod, now_text, session_day, observed, accepted
):
    now = datetime.fromisoformat(now_text.replace("Z", "+00:00"))
    p = projection()
    p["reentry_watch"]["SYNX"]["current_quote"].update(
        session="regular", session_date=session_day, as_of=observed
    )
    result = mod.build(p, {}, now=now)["symbols"]["SYNX"]["quote"]
    assert (result["state"] == "measured") is accepted
    assert result["value"] == (12 if accepted else None)


@pytest.mark.parametrize("clock", [None, "2032-03-09T22:00:00Z", "2032-03-09T20:00:00"])
@pytest.mark.parametrize("category_state", ["CALM", "WARN", "STRESS"])
def test_affirmative_category_chip_requires_accepted_source_clock(mod, clock, category_state):
    p = projection()
    p["categories"] = [{"category": mod.CATEGORIES[0], "state": category_state, "as_of": clock}]
    row = mod.build(p, {}, now=NOW)["risk"]["categories"][0]
    assert row["state"] == "unknown" and row["value"] is None
    assert row["chip"] == "not_measured" and row["remediation"]


@pytest.mark.parametrize("category_state,chip", [("CALM", "OK"), ("WARN", "WARN"), ("STRESS", "STRESS")])
def test_clocked_category_chip_preserves_actual_measured_state(mod, category_state, chip):
    p = projection()
    p["categories"] = [{"category": mod.CATEGORIES[0], "state": category_state, "as_of": ASOF}]
    row = mod.build(p, {}, now=NOW)["risk"]["categories"][0]
    assert row["state"] == "measured" and row["chip"] == chip and row["as_of"] == ASOF


def test_null_or_past_earnings_date_is_unknown_never_a_positive_none_reported_claim(mod):
    def read(sql, params):
        if "FROM symbol_profiles" in sql:
            return [
                {"symbol": "SYNX", "next_earnings_date": None, "updated_at": ASOF},
                {"symbol": "SH", "next_earnings_date": "2032-03-01", "updated_at": ASOF},
                {"symbol": "PSQ", "next_earnings_date": "2032-03-12", "updated_at": ASOF},
            ]
        return []

    result = mod.collect(projection(), {}, reader=FailedCurrentReader(), read_rows=read, now=NOW)
    missing = result["symbols"]["SYNX"]["next_event"]
    assert missing["state"] == "unknown" and missing["value"] is None
    assert missing["reason"] == "Next earnings date not recorded" and missing["remediation"]["action"]
    past = result["symbols"]["SH"]["next_event"]
    assert past["state"] == "unknown" and past["value"] is None
    assert past["reason"] == "Recorded next earnings date is in the past"
    future = result["symbols"]["PSQ"]["next_event"]
    assert future["state"] == "measured" and future["value"] == {"kind": "earnings", "date": "2032-03-12"}


def test_stop_distance_carries_both_clocks_and_uses_the_older_clock(mod):
    joined = {
        "book_exposure": {"rows": [{"symbol": "SYNX", "account_label": "Synthetic account", "pct_account": 8}]},
        "observed_stops": [
            {
                "symbol": "SYNX",
                "account_label": "Synthetic account",
                "price": 9,
                "as_of": "2032-03-09T20:59:30Z",
                "source": "stored_stop",
                "status": "recorded",
            }
        ],
    }
    stop = mod.build(projection(), joined, now=NOW)["positions"][0]["stop"]
    assert stop["value"]["distance_price"] == 3 and stop["value"]["distance_pct_of_price"] == 25
    assert stop["as_of"] == ASOF
    assert stop["price_as_of"] == ASOF and stop["stop_as_of"] == "2032-03-09T20:59:30Z"
    assert "stored_stop" in stop["source"] and "synthetic_daily_close" in stop["source"]
    assert stop["age_seconds"] == 60


def test_book_beyond_symbol_cap_reports_fact_shaped_unknowns_and_a_gap(mod):
    rows = [{"symbol": f"SXN{index:03d}", "account_label": "Synthetic account"} for index in range(1, 82)]
    result = mod.build(projection(), {"book_exposure": {"rows": rows}}, now=NOW)
    capped = [row for row in result["positions"] if row["symbol"] == "SXN081"][0]
    assert capped["quote"]["state"] == "unknown" and capped["quote"]["value"] is None
    assert capped["quote"]["reason"] and capped["quote"]["remediation"]["action"]
    assert capped["day_change"]["state"] == "unknown" and capped["day_change"]["value"] is None
    assert capped["day_change"]["reason"] and capped["day_change"]["remediation"]["action"]
    assert any(
        gap["symbol"] == "SXN081" and gap["field"] == "quote" and "evaluation cap" in gap["reason"]
        for gap in result["gaps"]
    )


def test_future_dated_bar_is_excluded_from_since_exit_history_and_reported(mod):
    bars = [
        {"symbol": "SYNX", "date": "2032-03-05", "close": 10, "source": "synthetic_bars"},
        {"symbol": "SYNX", "date": "2032-03-20", "close": 99, "source": "synthetic_bars"},
    ]
    result = mod.build(projection(), {}, daily_bars=bars, now=NOW)
    dates = [row["date"] for row in result["symbols"]["SYNX"]["since_exit_history"]]
    assert "2032-03-05" in dates and "2032-03-20" not in dates
    gap = [
        row
        for row in result["gaps"]
        if row["symbol"] == "SYNX" and row["field"] == "since_exit_history"
    ]
    assert gap and "excluded from history" in gap[0]["reason"] and gap[0]["remediation"]["action"]


def test_analysis_references_aggregate_is_partial_and_nested_unknowns_are_gaps(mod):
    result = mod.build(projection(), {}, now=NOW)
    references = result["symbols"]["SYNX"]["analysis_references"]
    assert references["state"] == "partial"
    assert references["value"]["sma10"]["state"] == "measured"
    assert references["value"]["anchored_vwap"]["state"] == "unknown"
    assert any(
        gap["symbol"] == "SYNX" and gap["field"] == "analysis_references.anchored_vwap"
        for gap in result["gaps"]
    )


def test_budget_rows_carry_state_and_as_of_or_an_explicit_unknown(mod):
    joined = {
        "budgets_detail": [
            {
                "budget": "single_sector_pct",
                "actual": 40,
                "limit": 30,
                "unit": "%",
                "account_label": "Synthetic account",
            },
            {
                "budget": "unmeasured_pct",
                "actual": None,
                "limit": None,
                "unit": "%",
                "account_label": "Synthetic account",
            },
        ]
    }
    rows = mod.build(projection(), joined, now=NOW)["budgets"]
    measured = rows[0]
    assert measured["state"] == "measured" and measured["as_of"] == ASOF
    assert measured["age_seconds"] == 60 and measured["source"] == "market_risk.budgets_detail"
    unknown = rows[1]
    assert unknown["state"] == "unknown" and unknown["as_of"] == ASOF
    assert unknown["reason"] and unknown["remediation"]["action"]


# --------------------------------------------------------------------------- honesty repairs (cc4 BLOCK)


def test_a_quote_without_a_recorded_source_is_unknown_never_a_provenance_string(mod):
    """A price with no recorded source used to be measured and labelled "canonical_stored_quote"."""
    p = projection()
    del p["reentry_watch"]["SYNX"]["current_quote"]["source"]
    result = mod.build(p, {}, now=NOW)
    quote = result["symbols"]["SYNX"]["quote"]
    assert quote["state"] == "unknown" and quote["value"] is None
    assert quote["source"] == "not_recorded"
    assert "source not recorded" in quote["reason"]
    gap = next(row for row in result["gaps"] if row["symbol"] == "SYNX" and row["field"] == "quote")
    assert gap["remediation"]["key"] == "HOMEV007:not_recorded"


def test_a_category_carried_across_a_closure_never_affirms_ok(mod):
    """The canonical scoring rule: an observation carried across a closure is not measured now."""
    p = projection()
    p["categories"] = [{"category": "technical", "state": "CALM", "as_of": "2032-03-05T20:00:00Z"}]
    chip = next(c for c in mod.build(p, {}, now=NOW)["risk"]["categories"] if c["category"] == "technical")
    assert chip["state"] == "unknown" and chip["chip"] == "not_measured" and chip["carried"] is True
    assert chip["as_of"] == "2032-03-05T20:00:00Z" and chip["age_seconds"] > 72 * 3600
    assert "carried across a closure" in chip["reason"]
    result = mod.build(p, {}, now=NOW)
    assert any(row["field"] == "risk.categories.technical" for row in result["gaps"])
    # the same category observed inside the expected session still renders affirmatively
    p["categories"] = [{"category": "technical", "state": "CALM", "as_of": "2032-03-09T20:00:00Z"}]
    fresh = next(c for c in mod.build(p, {}, now=NOW)["risk"]["categories"] if c["category"] == "technical")
    assert fresh["chip"] == "OK" and fresh["carried"] is False and fresh["state"] == "measured"


def test_headlines_are_clocked_by_the_newest_headline_not_the_query(mod):
    """A 71-hour-old headline used to report age 0, and an empty query read as measured-now."""
    class NewsReader(StoredReader):
        pass

    def read(sql, params):
        if "FROM news_articles " in sql:
            return [{"symbol": "SYNX", "title": "SYNX announces synthetic product update",
                     "published_at": "2032-03-06T22:00:00Z", "source": "synthetic", "source_url": "u"}]
        return []

    p = projection()
    p["reentry_watch"]["SYNX"].pop("current_quote")
    headlines = mod.collect(p, {}, reader=NewsReader(), read_rows=read, now=NOW)["symbols"]["SYNX"]["headlines"]
    assert headlines["as_of"] == "2032-03-06T22:00:00Z"
    assert headlines["age_seconds"] == 255600
    empty = mod.collect(p, {}, reader=NewsReader(), read_rows=lambda sql, params: [], now=NOW)
    missing = empty["symbols"]["SYNX"]["headlines"]
    assert missing["state"] == "unknown" and missing["as_of"] is None and missing["value"] is None
    assert "source clock" in missing["reason"]


def test_two_observations_of_the_same_instant_are_a_conflict_not_a_silent_pick(mod):
    """Same instant, two prices: the same fact stated twice contradicting itself (cio_canonical_quote)."""
    other = {"symbol": "SYNX", "price": 12.5, "session": "regular_close", "session_date": "2032-03-09",
             "as_of": ASOF, "source": "synthetic_second_mark"}
    result = mod.build(projection(), {}, quotes=[other], now=NOW)
    quote = result["symbols"]["SYNX"]["quote"]
    assert quote["state"] == "unknown" and quote["value"] is None
    assert quote["conflict"]["marks"] == [{"price": 12.5, "source": "synthetic_second_mark"},
                                          {"price": 12.0, "source": "synthetic_daily_close"}]
    gaps = [row for row in result["gaps"] if row["symbol"] == "SYNX" and row["field"] == "quote"]
    assert len(gaps) == 1 and gaps[0]["remediation"]["key"] == "HOMEV007:quote.conflict"
    # a second mark that agrees at the same instant is not a conflict
    quote = mod.build(projection(), {}, quotes=[{**other, "price": 12}], now=NOW)["symbols"]["SYNX"]["quote"]
    assert quote["state"] == "measured" and "conflict" not in quote


def test_an_unknown_stop_and_budget_are_indexed_in_gaps(mod):
    joined = {
        "book_exposure": {"rows": [{"symbol": "SYNX", "account_label": "SYN"}]},
        "observed_stops": [{"symbol": "SYNX", "account_label": "SYN", "price": None,
                            "as_of": ASOF, "source": "synthetic_stops"}],
        "budgets_detail": [{"budget": "sector_max", "actual": None, "limit": 25}],
    }
    result = mod.build(projection(), joined, now=NOW)
    fields = {(row["symbol"], row["field"]) for row in result["gaps"]}
    assert ("SYNX", "positions.stop") in fields
    assert (None, "budgets.sector_max") in fields


def test_the_unavailable_context_envelope_can_be_told_apart_from_an_empty_one():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "book_join_under_test", ROOT / "scripts/lib/market_risk_book_join.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    env = module.unavailable_context(RuntimeError("synthetic private diagnostic"), NOW)
    assert env["schema"] == "HomeMarketRiskContext@v1" and env["state"] == "unavailable"
    assert env["symbols"] == {} and env["positions"] == [] and env["budgets"] == []
    assert env["generated_at"] == "2032-03-09T21:00:00Z"
    assert env["gaps"][0]["field"] == "home_v007"
    assert env["gaps"][0]["remediation"]["key"] == "HOMEV007:context"
    assert env["read_errors"][0]["source"] == "home_v007_join"
    assert env["advisory_only"] is True
    assert "synthetic private diagnostic" not in str(env)
    built = module.__dict__.get("unavailable_context")
    assert callable(built)
