"""LQ-20261107-483: the STYLE rows are dated by the SPY session, never by CURRENT_DATE.

The sector rows carry the as_of of the last SPY-aligned bar, but the STYLE:<key> rows were
inserted with ``CURRENT_DATE``. When SPY had no 2026-11-04 or 2026-11-06 bar by 17:25, those dates
got the two STYLE rows and no sector rows. Every ``max(as_of)`` reader
(``cio_sector_opportunity``, ``sector_leaders_service._prior_sector_ranks``) then read a date
with no sector table. A weekend rerun would add a STYLE-only Saturday or Sunday.

Synthetic prices only.
"""

from __future__ import annotations

import sys
import types
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import sector_momentum_engine as sme  # noqa: E402

SPY_LAST = date(2026, 1, 15)  # synthetic: a Thursday, well away from "today"


def _series(last: date, n: int, start: float, step: float):
    return [(last - timedelta(days=n - 1 - k), start + step * k) for k in range(n)]


class PriceCursor:
    """Answers the ticker_prices query in ``_closes``; every other query reads as empty."""

    def __init__(self, px: dict[str, list]):
        self.px = px
        self.rows: list = []
        self.executed: list[tuple[str, tuple | None]] = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "FROM ticker_prices" in sql:
            syms = params[0]
            self.rows = [(s, d, p) for s in sorted(syms) for d, p in self.px.get(s, [])]
        else:
            self.rows = []

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return None

    def close(self):
        pass


def _prices(spy_last: date, others_last: date):
    n = 100
    px = {"SPY": _series(spy_last, n, 500.0, 0.5)}
    for sym in ("QQQ", "IWM", "DIA", "VUG", "VTV", "RSP"):
        px[sym] = _series(others_last, n, 100.0, 0.2)
    return px


def test_market_as_of_is_the_last_spy_session():
    cur = PriceCursor(_prices(SPY_LAST, SPY_LAST))
    assert sme.compute_market(cur)["as_of"] == SPY_LAST


def test_a_later_bar_on_a_pair_symbol_does_not_move_the_date():
    # The 11-06 shape: RSP/IWM had a session bar and SPY did not. The spreads are SPY-aligned,
    # so the date they describe is SPY's last bar.
    cur = PriceCursor(_prices(SPY_LAST, SPY_LAST + timedelta(days=1)))
    assert sme.compute_market(cur)["as_of"] == SPY_LAST


def test_no_spy_bars_gives_no_date():
    px = _prices(SPY_LAST, SPY_LAST)
    px.pop("SPY")
    assert sme.compute_market(PriceCursor(px))["as_of"] is None


# ── main(): the STYLE upsert carries the market as_of ──────────────────────


class RecordingConn:
    def __init__(self):
        self.cur = PriceCursor({})

    def cursor(self, *a, **k):
        return self.cur

    def commit(self):
        pass

    def close(self):
        pass


def _run_main(monkeypatch, tmp_path, market):
    import db_adapter

    conn = RecordingConn()
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    monkeypatch.setattr(sme, "ROOT", tmp_path)
    (tmp_path / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sme, "_book_weights", lambda: {})
    monkeypatch.setattr(sme, "market_state_line", lambda *_a: "")
    monkeypatch.setattr(sme, "_ensure_session_closes", lambda **_kw: {"ok": True})
    monkeypatch.setattr(sme, "compute_states", lambda _cur, **_kw: [])
    monkeypatch.setattr(sme, "compute_market", lambda _cur: market)
    stub = types.ModuleType("industry_momentum")
    stub.decide_sector_notifications = lambda alerts, session=None: {"send": [], "suppressed": []}
    stub.emit_telegram = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "industry_momentum", stub)
    monkeypatch.setattr(sys, "argv", ["sector_momentum_engine.py"])
    assert sme.main() == 0
    return [(sql, p) for sql, p in conn.cur.executed
            if "INSERT INTO sector_momentum_state" in sql]


def _style(key="growth_vs_value"):
    return {"key": key, "pair": "VUG−VTV", "s5": 1.0, "s20": 2.0, "s60": 3.0,
            "slope": 0.5, "state": "LEADING"}


def test_style_upsert_is_dated_by_the_market_session_not_current_date(monkeypatch, tmp_path):
    inserts = _run_main(monkeypatch, tmp_path,
                        {"styles": [_style()], "as_of": SPY_LAST, "indices": [], "internals": {}})
    assert len(inserts) == 1
    sql, params = inserts[0]
    assert "CURRENT_DATE" not in sql
    assert params[0] == SPY_LAST and params[1] == "STYLE:growth_vs_value"


def test_no_session_date_writes_no_style_row(monkeypatch, tmp_path):
    inserts = _run_main(monkeypatch, tmp_path,
                        {"styles": [_style()], "as_of": None, "indices": [], "internals": {}})
    assert inserts == []


def test_no_insert_in_the_engine_uses_current_date():
    src = (ROOT / "scripts" / "sector_momentum_engine.py").read_text()
    for chunk in src.split("INSERT INTO sector_momentum_state")[1:]:
        values = chunk.split("ON CONFLICT")[0]
        assert "CURRENT_DATE" not in values
