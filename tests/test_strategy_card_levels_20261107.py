"""LQ-20261107-57 — a strategy card carries a level only when the level is true.

Measured on the live table (2026-11-07, 5,848 rows) before this fix:

* 319 cards served ``support == resistance == latest_price``. A 20-day window whose low equals its
  high (one card had 44 prices and ONE distinct close) is not a range, yet the card claimed both levels and
  derived entry, stop and target from them.
* 20 cards served ``stop_loss >= latest_price``: two-decimal rounding put a penny stop ONTO its price
  (0.0097 -> 0.01 above a 0.0093 close), and 52-week fallbacks put support above the market.
* 2 cards (two cards) served a NEGATIVE risk/reward — the guard checked entry > stop but never
  target > entry, so ``ideal_entry`` sat above ``target_price``.

The rule this file pins: every level is on the correct side of the price and of the level it depends
on, or it is NULL with a named reason and the card is flagged ``needs_iteration``. A blank cell with
a reason is a correct answer; an invented support line is indistinguishable from a real one.

LQ-20261107-110 adds the two other facts the same audit found missing on the served card: **when** a
price is from (measured: 963 of 5,541 card prices were more than 5% off the last session's close, and
the last bar for 4,444 symbols was a day old) and **what** the ``strategy_type`` was mapped from (the
raw class, the source that wrote it, the day, the confidence — a class the map does not know used to
become a silent ``core_holding``, 671 cards today, 556 of them registered as ``recovery_watch``).

Hermetic: fake connection, no DB, no state write, no provider call.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401 -- import-only probe: the module needs it importable, the tests never connect
except ModuleNotFoundError:  # pragma: no cover
    import types as _types

    _pg = _types.ModuleType("psycopg2")
    _pg_extras = _types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import materialize_watchlist_strategy_cards as mat  # noqa: E402

COVERS = ["scripts/materialize_watchlist_strategy_cards.py"]


def test_a_worktree_without_an_env_file_connects_instead_of_raising(tmp_path, monkeypatch):
    """The lane runs from a worktree that has no .env: missing credentials are libpq's refusal."""
    import psycopg2

    seen = {}

    def _connect(**kw):
        seen.update(kw)
        return object()

    monkeypatch.setattr(mat, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.setattr(psycopg2, "connect", _connect)
    mat._get_conn()
    assert seen["password"] == "" and seen["host"] == "localhost"


def test_the_env_file_supplies_the_password_the_executor_did_not(tmp_path, monkeypatch):
    import psycopg2

    (tmp_path / ".env").write_text("SOMETHING=else\nDB_" + "PASSWORD=from-the-file\n")
    seen = {}
    monkeypatch.setattr(mat, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: seen.update(kw) or object())
    mat._get_conn()
    assert seen["password"] == "from-the-file"


# --------------------------------------------------------------------------------------------------
# The rounding rule: 2 dp is right for a $37 stock and destroys a $0.0093 one
# --------------------------------------------------------------------------------------------------

def test_rounding_keeps_a_penny_level_below_its_price():
    price = 0.0093
    assert mat._round_level(0.0086, price) == 0.0086
    assert mat._round_level(0.0097, price) == 0.0097
    # The old behaviour, kept as the documented reason: round(x, 2) puts support ABOVE the price.
    assert round(0.0097, 2) == 0.01 > price


def test_rounding_stays_two_decimals_for_dollar_names():
    assert mat._round_level(27.1234, 27.12) == 27.12
    assert mat._round_level(None, 27.12) is None


# --------------------------------------------------------------------------------------------------
# coherent_levels — each defect, and the coherent card
# --------------------------------------------------------------------------------------------------

def _levels(**kw):
    base = {"latest_price": 10.0, "support": 9.5, "resistance": 10.8,
            "declared_stop": None, "atr": None, "strategy_type": "core_holding"}
    base.update(kw)
    return mat.coherent_levels(**base)


def test_a_flat_window_is_not_support_and_resistance():
    """A 44-price window with one distinct close served support=resistance=price."""
    out = _levels(latest_price=37.12, support=37.12, resistance=37.12)
    assert out["support"] is None and out["resistance"] is None
    assert out["ideal_entry"] is None and out["stop_loss"] is None
    assert out["target_price"] is None and out["risk_reward"] is None
    assert "flat_range" in out["reasons"]


def test_support_above_the_market_is_not_support():
    """The 52-week fallback put support at 25.84 over a 25.465 price."""
    out = _levels(latest_price=25.465, support=25.84, resistance=27.0)
    assert out["support"] is None and out["ideal_entry"] is None
    assert "support_not_below_price" in out["reasons"]
    assert out["risk_reward"] is None


def test_resistance_below_the_market_is_not_resistance():
    out = _levels(latest_price=25.465, support=24.0, resistance=25.08)
    assert out["resistance"] is None and out["target_price"] is None
    assert "resistance_not_above_price" in out["reasons"]
    assert out["risk_reward"] is None


def test_a_declared_stop_at_or_above_the_price_is_replaced_never_served():
    out = _levels(latest_price=25.465, support=24.0, resistance=27.0, declared_stop=25.82)
    assert "declared_stop_not_below_price" in out["reasons"]
    assert out["stop_loss"] is not None and out["stop_loss"] < 25.465


def test_a_penny_card_keeps_a_stop_below_its_price():
    """The 20 rows: round(x, 2) put the stop onto the price."""
    out = _levels(latest_price=0.0093, support=0.0086, resistance=0.0098, atr=None)
    assert out["support"] == 0.0086 and out["stop_loss"] < 0.0093
    assert out["ideal_entry"] < 0.0093
    assert out["risk_reward"] is not None and out["risk_reward"] > 0


def test_the_fltr_card_is_absent_rather_than_negative():
    """The negative-R/R shape, from the live table: price 25.465, support 25.84, resistance 25.08, declared stop 25.82, R/R -1.86.

    Support above resistance is an INVERTED range (the support came from the 52-week fallback, the
    resistance from history), so neither level may be served — and with no entry there is no R/R to
    be negative.
    """
    out = _levels(latest_price=25.465, support=25.84, resistance=25.08, declared_stop=25.82)
    assert (out["support"], out["resistance"], out["stop_loss"], out["target_price"]) == (None, None, None, None)
    assert out["risk_reward"] is None
    assert {"inverted_range", "declared_stop_not_below_price"} <= set(out["reasons"])


def test_a_normal_card_is_ordered_stop_below_entry_below_price_below_target():
    out = _levels(latest_price=100.0, support=95.0, resistance=110.0, atr=2.0)
    assert out["stop_loss"] < out["ideal_entry"] < 100.0 < out["target_price"]
    assert out["risk_reward"] == round((out["target_price"] - out["ideal_entry"])
                                       / (out["ideal_entry"] - out["stop_loss"]), 2)
    assert out["risk_reward"] > 0 and out["reasons"] == []


def test_no_price_is_a_named_state_not_invented_levels():
    out = mat.coherent_levels(latest_price=None, support=None, resistance=None,
                              declared_stop=None, atr=None, strategy_type="core_holding")
    assert out["reasons"] == ["no_price"]
    assert all(out[k] is None for k in ("support", "resistance", "ideal_entry", "stop_loss",
                                        "target_price", "risk_reward"))


def test_a_pullback_entry_is_never_at_or_above_the_market():
    """Support within 1% of the price: 9.95 * 1.01 rounds to 10.05 over a 10.00 price."""
    out = _levels(latest_price=10.0, support=9.95, resistance=11.0)
    assert out["ideal_entry"] is None
    assert "support_at_market" in out["reasons"]


def test_a_price_sitting_on_its_support_keeps_the_support_and_loses_the_entry():
    """A price ON its 20-day low (11.27 = 11.27 — 2,023 names on 2026-11-07).

    A stock at its low has real support AT the market; what it has no pullback entry to. Blanking the
    support would have thrown away the true level along with the invented entry.
    """
    out = _levels(latest_price=11.27, support=11.27, resistance=12.4, atr=0.3)
    assert out["support"] == 11.27 and out["resistance"] == 12.4
    assert out["ideal_entry"] is None and "support_at_market" in out["reasons"]
    assert out["stop_loss"] is not None and out["stop_loss"] < 11.27
    assert out["target_price"] > 11.27


def test_a_price_sitting_on_its_resistance_keeps_the_resistance():
    """906 names had high20 == latest (2026-11-07): a breakout target above the price is still true."""
    out = _levels(latest_price=11.27, support=10.4, resistance=11.27, atr=0.3)
    assert out["resistance"] == 11.27
    assert out["target_price"] is not None and out["target_price"] > 11.27
    assert "resistance_not_above_price" not in out["reasons"]


def test_rounding_never_manufactures_a_level_on_the_wrong_side():
    """Support 0.51475 rounds to 0.515 OVER a 0.5149 price: the raw level is kept, not the lie."""
    out = _levels(latest_price=0.5149, support=0.51475, resistance=0.53)
    assert out["support"] == 0.51475 and out["support"] <= 0.5149
    assert "support_not_below_price" not in out["reasons"]


def test_a_range_narrower_than_the_cards_precision_is_flat():
    """A 0.004-wide range at 10.54 rounds to one number twice — flat, not a range."""
    out = _levels(latest_price=10.54, support=10.5351, resistance=10.5401)
    assert out["support"] is None and out["resistance"] is None
    assert "flat_range" in out["reasons"]


# --------------------------------------------------------------------------------------------------
# The audit counts, computed from the same dicts that are upserted
# --------------------------------------------------------------------------------------------------

def test_the_quality_summary_counts_each_defect_from_the_served_levels():
    legacy = [
        {"symbol": "AAA", "latest_price": 37.12, "support": 37.12, "resistance": 37.12,
         "stop_loss": 36.01, "risk_reward": None, "level_reasons": []},
        {"symbol": "BBB", "latest_price": 0.0173, "support": 0.02, "resistance": 0.03,
         "stop_loss": 0.02, "risk_reward": None, "level_reasons": []},
        {"symbol": "CCC", "latest_price": 25.465, "support": 25.84, "resistance": 25.08,
         "stop_loss": 25.82, "risk_reward": -1.86, "level_reasons": []},
        {"symbol": "NOPX", "latest_price": None, "support": None, "resistance": None,
         "stop_loss": None, "risk_reward": None, "level_reasons": ["no_price"]},
    ]
    q = mat.card_quality_summary(legacy)
    assert q["support_equals_resistance"] == 1
    # BBB (0.02 stop over a 0.0173 price) AND CCC (25.82 over 25.465): two distinct rows.
    assert q["stop_at_or_above_price"] == 2
    assert q["negative_risk_reward"] == 1 and q["not_priceable"] == 1
    assert q["level_reasons"] == {"no_price": 1}


def test_the_quality_summary_cannot_report_a_defect_for_a_coherent_card():
    rows = []
    for price, sup, res in ((100.0, 95.0, 110.0), (0.0093, 0.0086, 0.0098), (37.12, 37.12, 37.12)):
        out = mat.coherent_levels(latest_price=price, support=sup, resistance=res,
                                  declared_stop=None, atr=None, strategy_type="core_holding")
        rows.append({"latest_price": price, **out})
    q = mat.card_quality_summary(rows)
    assert q["support_equals_resistance"] == 0 and q["stop_at_or_above_price"] == 0
    assert q["negative_risk_reward"] == 0 and q["not_priceable"] == 0


# --------------------------------------------------------------------------------------------------
# The price ladder and its date (LQ-20261107-110)
# --------------------------------------------------------------------------------------------------

def test_the_finviz_quote_wins_and_carries_the_cache_date():
    mark = mat.price_mark(series_price=10.0, series_date=date(2026, 11, 5),
                          finviz_row={"price": 10.5}, finviz_as_of="2026-11-07 11:00:02 ET",
                          last_close_date=date(2026, 11, 6))
    assert (mark["price"], mark["source"], mark["date"], mark["is_current"]) == (10.5, "finviz", "2026-11-07", True)


def test_a_db_close_from_an_older_session_is_not_current():
    mark = mat.price_mark(series_price=10.0, series_date=date(2026, 11, 5), last_close_date=date(2026, 11, 6))
    assert (mark["price"], mark["source"], mark["date"], mark["is_current"]) == (10.0, "stored_mark", "2026-11-05", False)


def test_a_db_close_from_the_last_session_is_current():
    mark = mat.price_mark(series_price=10.0, series_date=date(2026, 11, 6), last_close_date=date(2026, 11, 6))
    assert mark["is_current"] is True


def test_an_unknown_date_stays_unknown_and_is_never_called_current():
    mark = mat.price_mark(series_price=None, series_date=None, last_close_date=date(2026, 11, 6))
    assert mark["price"] is None and mark["is_current"] is None
    # No calendar -> unknown, not "stale": the writer must not invent a verdict it cannot support.
    assert mat.price_mark(series_price=10.0, series_date=date(2026, 11, 6), last_close_date=None)["is_current"] is None


def test_the_et_suffix_does_not_defeat_the_date():
    """'2026-11-07 ... ET' — a naive ISO test on the string is fooled by the T in ET."""
    assert mat._date_of("2026-11-07 11:00:02 ET") == date(2026, 11, 7)
    assert mat._date_of(date(2026, 11, 6)) == date(2026, 11, 6)
    assert mat._date_of("not a date") is None


# --------------------------------------------------------------------------------------------------
# Through the writer: the pending upsert and the card payload carry the same answer
# --------------------------------------------------------------------------------------------------

class _Cur:
    def __init__(self, conn):
        self.conn, self._rows, self._one = conn, [], None

    def execute(self, sql, params=None):
        self.conn.sql.append(sql)
        if "INSERT" in sql:
            if self.conn.readonly:
                raise RuntimeError("cannot execute INSERT in a read-only transaction")
            self.conn.inserts.append(params)
        elif "FROM ticker_prices" in sql:
            self._rows = [(c, self.conn.db["price_date"]) for c in self.conn.db["prices"].get(params[0], [])]
        elif "FROM ticker_strategy_classifications" in sql:
            # The class row carries its own provenance; a test may replace it (class_row=None: none).
            self._one = (self.conn.db["class_row"] if "class_row" in self.conn.db
                         else {"strategy_type": "core_index"})
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one

    def close(self):
        pass


class _Conn:
    def __init__(self, db):
        self.db, self.sql, self.inserts = db, [], []
        self.commits, self.readonly = 0, False

    def set_session(self, readonly=False, **_kw):
        self.readonly = readonly

    def cursor(self, cursor_factory=None):
        return _Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def writer(tmp_path, monkeypatch):
    db = {"conn": None, "prices": {}, "price_date": date(2026, 11, 6), "sql": []}

    def _get_conn():
        db["conn"] = _Conn(db)
        return db["conn"]

    monkeypatch.setattr(mat, "_get_conn", _get_conn)
    monkeypatch.setattr(mat, "_last_session_date", lambda: date(2026, 11, 6))
    monkeypatch.setattr(mat, "STATE_DIR", tmp_path / "portfolio_state")  # absent files -> defaults
    return db


def _write_json(path, payload):
    """Write a fixture the way a store must be written: temp file beside it, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)


def _write_enrichment(tmp_path, payload):
    _write_json(tmp_path / "portfolio_state" / "ticker_enrichment_cache.json", payload)


def test_a_flat_history_writes_no_support_and_no_resistance(writer):
    writer["prices"]["AAA"] = [37.12] * 44
    results = mat.materialize(["AAA"], dry_run=True)
    card = results[0]
    assert card["support"] is None and card["resistance"] is None
    assert card["stop_loss"] is None and card["risk_reward"] is None
    assert card["needs_iteration"] is True and card["level_reasons"] == ["flat_range"]


def test_a_symbol_with_no_price_evidence_is_marked_not_priceable(writer):
    results = mat.materialize(["NOPX"], dry_run=True)
    card = results[0]
    assert card["latest_price"] is None and card["status"] == "not_priceable"
    assert card["level_reasons"] == ["no_price"] and card["needs_iteration"] is True


def test_the_upsert_params_and_the_card_payload_agree(writer, tmp_path):
    writer["prices"]["CCC"] = []
    # 52-week fallback with the CURRENT price outside the 52-week range: support lands above the
    # market and resistance below it, which is exactly the row shape the API served.
    _write_enrichment(tmp_path, {"CCC": {"price": 25.465, "week52_low_pct": -2.0, "week52_high_pct": 1.0}})
    results = mat.materialize(["CCC"], dry_run=True)
    card = results[0]
    assert card["support"] is None and card["resistance"] is None
    assert "inverted_range" in card["level_reasons"]


def test_the_written_card_json_states_the_status_and_the_reasons(writer):
    writer["prices"]["AAA"] = [37.12] * 44
    mat.materialize(["AAA"])
    params = writer["conn"].inserts[0]
    payload = json.loads(params[20])
    assert payload["status"] == "ok" and payload["level_reasons"] == ["flat_range"]
    # support/resistance/ideal_entry/stop/target/risk_reward positions in UPSERT_SQL
    assert params[3] is None and params[4] is None and params[9] is None and params[10] is None


def test_the_receipt_summary_carries_the_quality_counts(writer, tmp_path, monkeypatch):
    import lib.lane_last_receipt as llr

    captured = {}
    monkeypatch.setattr(llr, "write_lane_receipt", lambda name, **kw: captured.update(kw))
    writer["prices"]["AAA"] = [37.12] * 44
    monkeypatch.setattr(sys, "argv", ["materialize_watchlist_strategy_cards.py", "--symbols", "AAA"])
    assert mat.cli() == 0
    assert captured["summary"]["quality"]["support_equals_resistance"] == 0
    assert captured["summary"]["quality"]["level_reasons"] == {"flat_range": 1}


def test_a_card_dates_its_price_and_flags_a_close_from_an_older_session(writer):
    """The card said "the price" with no date, so a two-session-old close read as today's (LQ-110)."""
    writer["prices"]["AAA"] = [10.0] * 20
    writer["price_date"] = date(2026, 11, 4)          # last session is 11-06
    card = mat.materialize(["AAA"], dry_run=True)[0]
    assert card["price_source"] == "stored_mark" and card["price_date"] == "2026-11-04"
    assert card["price_is_current"] is False and card["needs_iteration"] is True


def test_a_card_whose_price_is_the_last_session_is_not_flagged_for_its_price(writer):
    writer["prices"]["AAA"] = [10.0] * 20
    card = mat.materialize(["AAA"], dry_run=True)[0]
    assert card["price_is_current"] is True


def test_the_finviz_cache_prices_the_symbol_it_carries(writer, tmp_path):
    """The ladder is Finviz first: the holdings the cache carries are priced from it, not the old close."""
    _write_json(tmp_path / "portfolio_state" / "finviz_quote_cache.json", {
        "_meta": {"last_fetched": "2026-11-07 11:00:02 ET"},
        "AAA": {"price": 12.5},
    })
    writer["prices"]["AAA"] = [10.0] * 20
    card = mat.materialize(["AAA"], dry_run=True)[0]
    assert card["latest_price"] == 12.5 and card["price_source"] == "finviz"
    assert card["price_date"] == "2026-11-07" and card["price_is_current"] is True


def test_an_undated_enrichment_price_is_unknown_not_current(writer, tmp_path):
    _write_enrichment(tmp_path, {"NOPX": {"price": 4.2}})
    card = mat.materialize(["NOPX"], dry_run=True)[0]
    assert card["latest_price"] == 4.2 and card["price_source"] == "enrichment_cache"
    assert card["price_date"] is None and card["price_is_current"] is None


# --------------------------------------------------------------------------------------------------
# Strategy type: the card says which class it was mapped from, and what wrote that class (LQ-110)
# --------------------------------------------------------------------------------------------------

def test_a_card_names_the_class_and_the_source_it_came_from(writer):
    """A served type must be traceable to its row: class, source, day, confidence (LQ-20261107-110)."""
    writer["class_row"] = {"strategy_type": "core_index", "classification_source": "manual",
                           "confidence": 1.0, "updated_at": datetime(2026, 4, 27, 11, 55, 38)}
    writer["prices"]["AAA"] = [10.0] * 20
    card = mat.materialize(["AAA"], dry_run=True)[0]
    assert card["strategy_type"] == "growth_etf"
    assert card["strategy_class"] == "core_index"
    assert card["strategy_class_source"] == "manual"
    assert card["strategy_class_as_of"] == "2026-04-27"
    assert card["strategy_class_confidence"] == 1.0
    assert card["type_reasons"] == []


def test_an_unmapped_class_keeps_its_raw_name_and_says_why(writer):
    """A registered class the map does not know is a gap, not a core holding nobody can see."""
    writer["class_row"] = {"strategy_type": "moon_shot", "classification_source": "screener",
                           "confidence": 0.7, "updated_at": date(2026, 4, 29)}
    writer["prices"]["AAA"] = [10.0] * 20
    card = mat.materialize(["AAA"], dry_run=True)[0]
    assert card["strategy_type"] == "core_holding"
    assert card["strategy_class"] == "moon_shot"
    assert card["type_reasons"] == ["strategy_class_unmapped"]
    assert card["needs_iteration"] is True


def test_a_symbol_with_no_classification_says_so(writer):
    writer["class_row"] = None
    writer["prices"]["AAA"] = [10.0] * 20
    card = mat.materialize(["AAA"], dry_run=True)[0]
    assert card["strategy_type"] == "core_holding" and card["strategy_class"] is None
    assert card["type_reasons"] == ["strategy_class_missing"]


def test_the_quality_summary_counts_the_class_sources(writer):
    writer["class_row"] = {"strategy_type": "swing_trade", "classification_source": "screener",
                           "confidence": 0.7, "updated_at": date(2026, 5, 5)}
    writer["prices"]["AAA"] = [10.0] * 20
    quality = mat.card_quality_summary(mat.materialize(["AAA"], dry_run=True))
    assert quality["strategy_class_source"] == {"screener": 1}
    assert quality["type_reasons"] == {}
