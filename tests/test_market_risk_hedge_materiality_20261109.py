"""LQ-20261107-1578 (page defect 168, /v3/ Home hedge card): two defects the walk caught.

ANCHOR: MARKET_RISK_HEDGE_MATERIALITY_20261109

1. The Home hedge card proposed a PSQ hedge "up to half the stressed dollars" while the book's stressed
   exposure was 0% of the book — far below the Defense desk's 8% ``materiality_exposure_pct``. The proposal
   is now gated on that line: below it (or when the line cannot be read) nothing is proposed, and the
   existing ``gap_to_consider_usd`` says how far the book is from material.

2. Semis counted a few dollars while the book's AI/tech look-through carried the real exposure.
   ``lookthrough.exposure_for`` reads ``prof.get("industry")`` to put a directly held semiconductor stock in
   the ``semis`` theme, but neither profile loader ever selected ``symbol_profiles.industry`` — the branch
   could not fire for any stock. Both loaders now carry the column when the table has it.

Synthetic fixtures only: no DB, no broker, no live file. The book below is round and invented; its symbols
are not holdings of any real book.
"""
import sys
import types
from pathlib import Path

ANCHOR = "MARKET_RISK_HEDGE_MATERIALITY_20261109"
COVERS = ["scripts/lib/home_cio_card.py", "scripts/lib/market_risk/exposure.py",
          "scripts/lib/market_risk/book_precision.py"]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import home_cio_card as h  # noqa: E402
from lib.market_risk import book_precision as bp  # noqa: E402
from lib.market_risk import exposure  # noqa: E402
from lib.market_risk import lookthrough as lt  # noqa: E402

AT = "2031-03-10T02:00:00+00:00"


def _mr(pct=0.0, mat=8.0):
    """The defect shape: verdict WATCH, a round $25,000 stressed (semis $12,000 + energy $13,000), rule half."""
    hedge = {
        "verdict": "WATCH", "as_of": AT, "candidates": ["SH", "PSQ"],
        "thresholds": {"trigger_book_pct": 10.0, "index_trigger_lagging_sectors": 4,
                       "materiality_exposure_pct": mat},
        "stressed_pct_book": pct, "lagging_count": 1, "stressed_usd": 25_000.0,
        "stressed_breakdown": [{"key": "semis", "label": "Semis", "usd": 12_000.0},
                               {"key": "energy", "label": "Energy", "usd": 13_000.0}],
    }
    return {"hedge": hedge, "book_exposure": {"as_of": "2031-03-10", "total_usd": 1_000_000.0, "stressed_usd": 25_000.0}}


class _FakeCursor:
    def __init__(self, results):
        self._results = iter(results)
        self._current = None

    def execute(self, *args, **kwargs):
        self._current = next(self._results)

    def fetchall(self):
        return self._current

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    """Only what the two profile loaders touch; ``set_session`` is what makes it acceptable to ``read_only``."""

    def __init__(self, results):
        self._results = results
        self.closed = False
        self.readonly = False

    def set_session(self, readonly=False):
        self.readonly = readonly

    def cursor(self):
        return _FakeCursor(self._results)

    def close(self):
        self.closed = True


# ── 1. the materiality gate ────────────────────────────────────────────────────────────────────────────────────────
def test_a_dust_hedge_below_materiality_is_not_proposed():
    out = h._hedge(_mr(0.0), True)
    assert out is not None and out["verdict"] == "WATCH"
    assert out.get("if_triggered") is None, "a 0%-of-book stressed exposure must not get a PSQ proposal"
    # the honest number the card keeps: how far the book is from the 8% consider line (8% of $1M - $25,000)
    assert out["gap_to_consider_usd"] == 55_000.0
    assert out["stressed_labels"] == ["Semis", "Energy"]


def test_the_proposal_returns_at_the_materiality_line():
    out = h._hedge(_mr(8.0), True)
    pick = out["if_triggered"]
    assert pick["symbol"] == "PSQ" and pick["proposed"] is True
    assert pick["proposed_size_usd"] == 12_500.0  # half of $25,000, the existing proposed rule
    assert pick["staged"] == [0.3, 0.3, 0.4]


def test_an_unknown_materiality_line_never_proposes():
    mr = _mr(0.0)
    mr["hedge"]["thresholds"].pop("materiality_exposure_pct")
    assert h._hedge(mr, True).get("if_triggered") is None
    assert h._hedge(_mr(8.0), False).get("if_triggered") is None  # advice off: same as before


# ── 2. the semis theme reaches a directly held semiconductor stock ───────────────────────────────────────────────
def test_a_directly_held_semiconductor_stock_carries_the_semis_theme():
    ex = lt.exposure_for("MU", ai_basket=[], profiles={"MU": {"sector": "Technology", "industry": "Semiconductors"}})
    assert ex["groups"]["tech"] == 1.0
    assert ex["groups"]["semis"] == 1.0, "a Semiconductors profile must count toward the semis theme"
    assert ex["basis"] == "stock (symbol_profiles sector)"


def test_a_stock_without_a_semiconductor_industry_is_not_semis():
    ex = lt.exposure_for("CSCO", ai_basket=[],
                         profiles={"CSCO": {"sector": "Technology", "industry": "Communications Equipment"}})
    assert "semis" not in ex["groups"], "networking equipment is not a semiconductor holding"


def test_the_default_profile_loader_carries_industry(monkeypatch):
    have = [("symbol",), ("sector",), ("description_1s",), ("industry",)]
    rows = [("MU", "Technology", "Micron Technology", "Semiconductors")]
    fake = types.ModuleType("db_adapter")
    fake._get_conn = lambda: _FakeConn([have, rows])
    monkeypatch.setitem(sys.modules, "db_adapter", fake)
    profiles, _ = exposure._default_profiles_loader(["MU"])
    assert profiles["MU"] == {"sector": "Technology", "description": "Micron Technology",
                              "industry": "Semiconductors"}


def test_the_default_profile_loader_survives_a_table_without_industry(monkeypatch):
    have = [("symbol",), ("sector",), ("description_1s",)]
    rows = [("MU", "Technology", "Micron Technology")]
    fake = types.ModuleType("db_adapter")
    fake._get_conn = lambda: _FakeConn([have, rows])
    monkeypatch.setitem(sys.modules, "db_adapter", fake)
    profiles, _ = exposure._default_profiles_loader(["MU"])
    assert profiles["MU"]["sector"] == "Technology"
    assert profiles["MU"].get("industry") is None


def test_the_engine_profile_loader_carries_industry():
    conn = _FakeConn([[("symbol",), ("sector",), ("description_1s",), ("industry",)],
                      [("MU", "Technology", "Micron Technology", "Semiconductors")]])
    profiles, _ = bp._ro_profiles_loader(lambda: conn)(["MU"])
    assert profiles["MU"]["industry"] == "Semiconductors"
    assert conn.readonly is True and conn.closed is True
