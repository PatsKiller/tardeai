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

Hermetic: fake connection, no DB, no state write, no provider call.
"""

from __future__ import annotations

import json
import sys
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
# Through the writer: the pending upsert and the card payload carry the same answer
# --------------------------------------------------------------------------------------------------

class _Cur:
    def __init__(self, db):
        self.db, self._rows, self._one = db, [], None

    def execute(self, sql, params=None):
        self.db.sql.append(sql)
        if "INSERT" in sql:
            if self.db.readonly:
                raise RuntimeError("cannot execute INSERT in a read-only transaction")
            self.db.inserts.append(params)
        elif "FROM ticker_prices" in sql:
            self._rows = [(c,) for c in self.db.prices.get(params[0], [])]
        elif "FROM ticker_strategy_classifications" in sql:
            self._one = {"strategy_type": "core_index"}
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one

    def close(self):
        pass


class _Conn:
    def __init__(self, prices):
        self.prices, self.sql, self.inserts = prices, [], []
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
    db = {"conn": None, "prices": {}}

    def _get_conn():
        db["conn"] = _Conn(db["prices"])
        return db["conn"]

    monkeypatch.setattr(mat, "_get_conn", _get_conn)
    monkeypatch.setattr(mat, "STATE_DIR", tmp_path / "portfolio_state")  # absent files -> defaults
    return db


def _write_enrichment(tmp_path, payload):
    d = tmp_path / "portfolio_state"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ticker_enrichment_cache.json").write_text(json.dumps(payload))


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
