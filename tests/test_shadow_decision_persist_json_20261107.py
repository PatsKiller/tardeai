"""A bar without a price is not a bar — and a NaN must never lose a packet.

WORK-QUEUE item 6, 2026-11-01: the weekly shadow batch ran 86 symbols, generated 85 and failed
ONE — PARA — with

    InvalidTextRepresentation: invalid input syntax for type json
    LINE 4: ...404,'PARA','LONG_TERM','STAGED_SHARES','REJECTED','{"structu...

The chain, reproduced read-only on 2026-11-07 (``evaluate("PARA", run_models=False)`` returned 9
non-finite floats, all in the LONG_TERM STAGED_SHARES structure):

  1. yfinance returned ONE row of ninety with NaN high/low/close (a halted or absent session).
     ``float(nan)`` does not raise, so ``_bars`` kept it.
  2. ``_tech`` sums over close/high/low, so ATR, RSI and SMA50 all became NaN — while
     ``swing_low``/``swing_high`` stayed finite, so the bars looked usable.
  3. NaN is TRUTHY: ``if not facts.get("atr")`` and ``if not facts.get("support")`` (``[nan]``)
     both passed, and ``trade_blueprints.staged_shares`` built a ladder priced in NaN.
  4. ``json.dumps`` writes NaN as the bare token ``NaN``, which PostgreSQL refuses as json. The
     blueprint insert raised, the transaction rolled back, and PARA's whole packet was lost —
     one bad float cost a symbol its decision.

Fixed at three layers, each tested here hermetically (no DB, no network, no broker, no fixture
from the live store): the bar boundary (``_bar``), the fact gates (``_finite_round`` /
``_any_finite``), and the jsonb boundary (``_pg_json``).
"""
from __future__ import annotations

import json
import math
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import shadow_decision_service as sds   # noqa: E402
import trade_blueprints as tb           # noqa: E402
import watchlist_entry_planner as wep   # noqa: E402

NAN = float("nan")
INF = float("inf")
REQUIRED = ("long_term", "swing", "bearish", "options", "no_trade")


# ── 1. the bar boundary ──────────────────────────────────────────────────────

def test_a_non_finite_bar_is_not_a_bar():
    assert wep._bar(1.0, 0.9, 0.95) == {"high": 1.0, "low": 0.9, "close": 0.95}
    assert wep._bar(NAN, 0.9, 0.95) is None
    assert wep._bar(1.0, NAN, 0.95) is None
    assert wep._bar(1.0, 0.9, INF) is None
    assert wep._bar(None, 0.9, 0.95) is None
    assert wep._bar("", 0.9, 0.95) is None


class _Frame:
    """The two-column-read shape ``_bars`` uses: ``h["High"]`` etc. as plain sequences."""

    def __init__(self, cols):
        self._cols = cols

    def __getitem__(self, key):
        return self._cols[key]


class _Ticker:
    def __init__(self, frame):
        self._frame = frame

    def history(self, period="1y"):
        return self._frame


def _fake_yfinance(highs, lows, closes):
    mod = types.ModuleType("yfinance")
    mod.Ticker = lambda symbol: _Ticker(_Frame({"High": highs, "Low": lows, "Close": closes}))
    return mod


def _series(n=60, bad_at=None):
    """n bars around $1.00 with one deliberately non-finite row, as yfinance returned for PARA."""
    highs, lows, closes = [], [], []
    for i in range(n):
        base = 1.00 + 0.01 * (i % 7)
        h, low, c = base + 0.02, base - 0.02, base
        if i == bad_at:
            h = low = c = NAN
        highs.append(h); lows.append(low); closes.append(c)
    return highs, lows, closes


def test_the_bars_source_drops_the_nan_row(monkeypatch):
    """The defect as it reached production: 60 bars, one of them NaN."""
    highs, lows, closes = _series(60, bad_at=55)
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(highs, lows, closes))
    bars = wep._bars("TEST", days=60)
    assert bars is not None and len(bars) == 59
    assert all(math.isfinite(b["high"]) and math.isfinite(b["low"]) and math.isfinite(b["close"])
               for b in bars)


def test_one_nan_bar_poisons_every_technical_and_the_filter_stops_it(monkeypatch):
    """A NaN leg does not raise anywhere — the sums just become NaN. That is why the row has to
    go before ``_tech`` sees it, not after."""
    highs, lows, closes = _series(60, bad_at=55)
    raw = [{"high": h, "low": lo, "close": c} for h, lo, c in zip(highs, lows, closes)]
    poisoned = wep._tech(raw)
    assert math.isnan(poisoned["atr"]) and math.isnan(poisoned["rsi"])
    assert math.isfinite(poisoned["swing_low"])      # swings stay finite — the bars LOOK usable

    kept = [b for b in (wep._bar(h, lo, c) for h, lo, c in zip(highs, lows, closes)) if b]
    healthy = wep._tech(kept)
    assert math.isfinite(healthy["atr"]) and healthy["atr"] > 0
    assert math.isfinite(healthy["rsi"]) and math.isfinite(healthy["sma50"])


# ── 2. the gates: NaN is truthy and used to pass them ────────────────────────

def _facts(**over):
    base = {"symbol": "TEST", "live_price": 1.0, "enriched_price": 1.0,
            "atr": 0.05, "support": [0.90], "resistance": [1.20]}
    base.update(over)
    return base


def _event():
    return types.SimpleNamespace(date=None)


def test_a_nan_atr_cannot_build_a_staged_ladder():
    """The gate is what a NaN defeated: ``not nan`` is False, so it read as "we have volatility"."""
    fam = sds.build_long_term(_facts(atr=NAN), _event(), {}, "ATTRACTIVE", "READY")
    assert fam["state"] == sds.DATA_UNAVAILABLE
    assert fam["structures"] == []
    assert "insufficient price history" in fam["rejection_reasons"][0]


def test_a_nan_support_list_cannot_build_a_staged_ladder():
    """``[nan]`` is a non-empty list — truthy — but it is not a support level."""
    fam = sds.build_long_term(_facts(support=[NAN]), _event(), {}, "ATTRACTIVE", "READY")
    assert fam["state"] == sds.DATA_UNAVAILABLE
    assert fam["structures"] == []


def test_data_quality_calls_the_nan_an_absence():
    dq = sds.assess_data_quality(_facts(atr=NAN, support=[NAN]), types.SimpleNamespace(
        state="NONE_CONFIRMED", reason=None))
    assert dq["state"] == "INSUFFICIENT"
    assert any("no ATR" in p for p in dq["fields"])
    assert any("no support levels" in p for p in dq["fields"])


def test_the_finite_helpers_state_the_absence_instead_of_a_number():
    assert sds._finite_round(1.23456, 2) == 1.23
    assert sds._finite_round(NAN, 4) is None
    assert sds._finite_round(INF, 4) is None
    assert sds._finite_round(None, 4) is None
    assert sds._finite_round(True, 4) is None
    assert sds._finite_levels(0.111) == [0.11]
    assert sds._finite_levels(NAN) == []
    assert sds._any_finite([NAN, 0.9]) is True
    assert sds._any_finite([NAN]) is False
    assert sds._any_finite([]) is False


def test_a_ladder_with_a_non_positive_level_is_refused():
    """PARA's second face: once the ATR was finite it was 1.31 on an $0.115 price — one ATR
    below spot is NEGATIVE. Finite and persisted is not the same as executable."""
    with pytest.raises(tb.BlueprintRejected) as exc:
        tb.staged_shares(symbol="PARA", current_price=0.115, atr=1.31, support=[0.111],
                         resistance=[8.93], thesis_state="NEUTRAL", timing="EXTENDED",
                         account_equity=1_252_958.0)
    reason = exc.value.reasons[0]
    assert "not executable" in reason and "ATR 1.31" in reason


def test_the_long_term_family_rejects_rather_than_publishing_a_negative_ladder():
    fam = sds.build_long_term({"symbol": "PARA", "live_price": 0.115, "enriched_price": 0.115,
                               "atr": 1.31, "support": [0.111], "resistance": [8.93]},
                              _event(), {}, "NEUTRAL", "EXTENDED")
    assert fam["state"] == sds.REJECTED
    assert fam["structures"] == []
    assert "not executable" in fam["rejection_reasons"][0]


# ── 3. the jsonb boundary: never lose the packet over one float ──────────────
class _Cursor:
    def __init__(self):
        self.calls = []
        self._returns = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "INSERT INTO decision_runs" in sql:
            self._returns.append((101,))
        elif "INSERT INTO decision_packets" in sql:
            self._returns.append((202,))

    def fetchone(self):
        return self._returns.pop(0) if self._returns else None


class _Conn:
    def __init__(self):
        self.cur = _Cursor()
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("persist rolled back — a non-finite value reached PostgreSQL")


def _packet_with_nan():
    structure = {"structure": "STAGED_SHARES", "state": "DATA_UNAVAILABLE",
                 "starter_entry": {"price_or_zone": [NAN, 0.11]},
                 "atr_used": NAN, "risk_reward": INF,
                 "rejection_reasons": ["computed on a non-finite ATR"]}
    fams = {k: {"family": k.upper(), "state": "DATA_UNAVAILABLE", "structures": [structure]}
            for k in REQUIRED}
    return {"symbol": "PARA", "packet_version": "test", "source_commit_sha": "0" * 40,
            "horizons": {"long_term": {"thesis_state": "UNPROVEN"},
                         "swing": {"timing": "WAIT_FOR_PULLBACK"},
                         "tactical": {"timing": "WAIT_FOR_PULLBACK"}},
            "event_state": {"earnings": {"state": "NONE_CONFIRMED"}},
            "data_quality": {"state": "INSUFFICIENT", "actionable": False},
            "no_trade_is_valid": True,
            "model_review": {"mode": "SKIPPED", "lanes_requested": [], "lanes_completed": []},
            "plan_families": fams}


def test_a_non_finite_blueprint_is_stored_as_null_not_rejected():
    conn = _Conn()
    packet_id = sds.persist(_packet_with_nan(), conn)      # would raise on the old json.dumps
    assert packet_id == 202 and conn.committed

    inserts = [(sql, p) for sql, p in conn.cur.calls if "INSERT INTO decision_blueprints" in sql]
    assert len(inserts) == len(REQUIRED)
    for sql, params in inserts:
        mechanics, rejection = params[5], params[6]
        # The exact database failure: these strings must be valid JSON, no NaN/Infinity tokens.
        for token in ("NaN", "Infinity"):
            assert token not in mechanics and token not in rejection
        doc = json.loads(mechanics, parse_constant=_refuse_constant)
        assert doc["starter_entry"]["price_or_zone"] == [None, 0.11]
        assert doc["atr_used"] is None and doc["risk_reward"] is None
        assert json.loads(rejection, parse_constant=_refuse_constant) == [
            "computed on a non-finite ATR"]


def _refuse_constant(name):
    raise AssertionError(f"{name} is not JSON — PostgreSQL would reject the insert")


def test_the_packet_column_stays_valid_json_too():
    conn = _Conn()
    sds.persist(_packet_with_nan(), conn)
    sql, params = next((s, p) for s, p in conn.cur.calls if "INSERT INTO decision_packets" in s)
    assert "::jsonb" in sql
    for token in ("NaN", "Infinity"):
        assert token not in params[22]
    json.loads(params[22], parse_constant=_refuse_constant)


@pytest.mark.parametrize("bad", [NAN, INF, -INF])
def test_no_family_builder_emits_a_non_finite_float(bad):
    """Whatever the family, the structure it hands the writer is JSON-safe."""
    fam = sds.build_long_term(_facts(atr=bad), _event(), {}, "ATTRACTIVE", "READY")
    doc = json.loads(sds._pg_json(fam), parse_constant=_refuse_constant)
    assert doc["state"] == sds.DATA_UNAVAILABLE
