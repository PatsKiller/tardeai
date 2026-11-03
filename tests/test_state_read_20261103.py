"""Damaged state files are 'no snapshot', never a crash (2026-11-03).

Hermetic: tmp files only; no DB, no network, no live store.
"""

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# The consumer functions import psycopg2.extras for their RealDictCursor. These tests drive them
# with a fake connection and never touch a real driver, and some CI shards install no psycopg2 at
# all (shard 3), so supply a stub when the driver is absent. The pg shard still exercises the real
# import.
try:  # pragma: no cover - depends on the shard
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg.extras = types.SimpleNamespace(RealDictCursor=object)  # type: ignore[attr-defined]
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _pg.extras

from lib import state_read as sr  # noqa: E402


def test_states_are_distinguished(tmp_path):
    p = tmp_path / "x.json"
    assert sr.read_json_state(p) == (None, "absent")
    p.write_bytes(b"")
    assert sr.read_json_state(p) == (None, "empty")
    p.write_text("   \n")
    assert sr.read_json_state(p) == (None, "empty")
    p.write_text("{not json")
    assert sr.read_json_state(p) == (None, "unparseable")
    p.write_text("[1,2,3]")
    assert sr.read_json_state(p) == (None, "not_object")
    p.write_text('{"holdings": []}')
    doc, state = sr.read_json_state(p)
    assert state == "ok" and doc == {"holdings": []}


def test_read_json_object_never_raises_on_damage(tmp_path):
    p = tmp_path / "x.json"
    for raw in (b"", b"{not json", b"[1]", b"null"):
        p.write_bytes(raw)
        assert sr.read_json_object(p, default={}) == {}
    assert sr.read_json_object(tmp_path / "missing.json", default={"a": 1}) == {"a": 1}
    p.write_text('{"a": 1}')
    assert sr.read_json_object(p, default={}) == {"a": 1}


def test_job_runner_holdings_read_survives_a_zero_byte_store(tmp_path):
    # The exact expression that raised 18 times on 2026-11-03 (now via the helper).
    state = tmp_path / "holdings.json"
    state.write_bytes(b"")
    holdings = sr.read_json_object(state, default={})
    assert holdings == {}
    assert [h for h in holdings.get("holdings", [])] == []


def test_social_ingest_symbols_on_zero_byte_store(tmp_path, monkeypatch):
    import social_ingest as si

    state_dir = tmp_path / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "holdings.json").write_bytes(b"")
    monkeypatch.setattr(si, "PROJECT_ROOT", tmp_path)
    assert si._get_holdings_symbols() == []  # no crash, no invented symbols


def test_social_ingest_symbols_filters_cash_and_funds(tmp_path, monkeypatch):
    import social_ingest as si

    state_dir = tmp_path / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "holdings.json").write_text(
        json.dumps(
            {
                "holdings": [
                    {"symbol": "AAA"},
                    {"symbol": "CASH", "is_cash": True},
                    {"symbol": "FUNDX", "is_fund": True},
                    {"symbol": ""},
                ]
            }
        )
    )
    monkeypatch.setattr(si, "PROJECT_ROOT", tmp_path)
    assert si._get_holdings_symbols() == ["AAA"]


# ── cx-openai-2 BLOCK at 85a573e6c: consumer shape (F1), unknown not empty (F2), decoder (F3) ──

DAMAGED_RAW = (b"", b"{not json", b"\xff\xfe\x00", b"[1,2]", b"null", b"   \n")
WRONG_SHAPE = ('{"holdings": null}', '{"holdings": {"AAA": {}}}', '{"holdings": [1]}')


class _Cursor:
    def __init__(self):
        self._sql = ""

    def execute(self, sql, params=None):
        self._sql = str(sql)

    def fetchone(self):
        s = self._sql
        if "as cnt" in s:
            return {"cnt": 0}
        if "as total" in s:
            return {"total": 0}
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


class _Conn:
    def cursor(self, *a, **k):
        return _Cursor()

    def close(self):
        pass


@pytest.fixture
def wl(monkeypatch, tmp_path):
    """The real watchlist module, pointed at a scratch state directory."""
    import process_watchlist_agent_jobs as wl

    monkeypatch.setattr(wl, "STATE_DIR", tmp_path)
    return wl


def test_holdings_state_distinguishes_damage_from_an_empty_book(tmp_path):
    p = tmp_path / "holdings.json"
    p.write_text('{"holdings": []}')
    assert sr.read_holdings_state(p) == ({"holdings": []}, "ok")  # a real empty book
    p.write_text('{"holdings": null}')
    assert sr.read_holdings_state(p) == (None, "invalid_shape")
    p.write_text('{"holdings": [{"symbol": "AAA"}, 1]}')
    assert sr.read_holdings_state(p) == (None, "invalid_shape")
    p.write_bytes(b"")
    assert sr.read_holdings_state(p) == (None, "empty")


def test_decoder_int_limit_is_unparseable_not_a_crash(tmp_path):
    """F3: a ~5KB object with a 5000-digit integer raises ValueError from the decoder."""
    p = tmp_path / "big.json"
    p.write_text('{"a": ' + "9" * 5000 + "}")
    assert sr.read_json_state(p) == (None, "unparseable")
    assert sr.read_json_object(p, default={"fallback": True}) == {"fallback": True}


def test_social_ingest_survives_the_decoder_limit(tmp_path, monkeypatch):
    import social_ingest as si

    state_dir = tmp_path / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "holdings.json").write_text('{"a": ' + "9" * 5000 + "}")
    monkeypatch.setattr(si, "PROJECT_ROOT", tmp_path)
    assert si._get_holdings_symbols() == []


@pytest.mark.parametrize("raw", DAMAGED_RAW)
def test_context_renders_unknown_never_not_held(wl, tmp_path, raw):
    """F2: a damaged store is UNKNOWN. Asserting 'NOT CURRENTLY HELD' is a fact the file never gave."""
    (tmp_path / "holdings.json").write_bytes(raw)
    out = wl._get_context(_Conn(), "AAA")
    assert "NOT CURRENTLY HELD" not in out["text"]
    assert "UNKNOWN" in out["text"]
    assert out["snapshot"]["positions_available"] is False
    assert out["snapshot"]["holdings_state"] != "ok"


@pytest.mark.parametrize("doc", WRONG_SHAPE)
def test_context_wrong_shape_does_not_crash(wl, tmp_path, doc):
    """F1: holdings null, a mapping, or scalar rows must not raise out of the consumer."""
    (tmp_path / "holdings.json").write_text(doc)
    out = wl._get_context(_Conn(), "AAA")
    assert out["snapshot"]["positions_available"] is False
    assert out["snapshot"]["holdings_state"] == "invalid_shape"
    assert "NOT CURRENTLY HELD" not in out["text"]


def test_absent_store_is_an_empty_book_not_unknown(wl, tmp_path):
    """ABSENT is the one state whose honest answer is 'no positions': there is no snapshot at all."""
    out = wl._get_context(_Conn(), "AAA")
    assert out["snapshot"]["holdings_state"] == "absent"
    assert out["snapshot"]["positions_available"] is True
    assert "NOT CURRENTLY HELD" in out["text"]


def test_context_null_risk_positions_does_not_crash(wl, tmp_path):
    (tmp_path / "holdings.json").write_text(json.dumps({"holdings": [{"symbol": "AAA", "shares": 1}]}))
    (tmp_path / "risk_management.json").write_text('{"positions": null}')
    out = wl._get_context(_Conn(), "AAA")
    assert out["snapshot"]["risk_positions_available"] is False
    assert out["snapshot"]["position"]["symbol"] == "AAA"


def test_context_healthy_store_still_reports_the_position(wl, tmp_path):
    (tmp_path / "holdings.json").write_text(
        json.dumps(
            {
                "holdings": [
                    {
                        "symbol": "AAA",
                        "account": "schwab_taxable",
                        "shares": 10,
                        "market_value": 1200.0,
                        "portfolio_pct": 2.0,
                        "price": 120.0,
                    }
                ]
            }
        )
    )
    out = wl._get_context(_Conn(), "AAA")
    assert out["snapshot"]["positions_available"] is True
    assert out["snapshot"]["holdings_state"] == "ok"
    assert "Position: $1,200" in out["text"]


@pytest.mark.parametrize("raw", DAMAGED_RAW)
def test_portfolio_context_is_unavailable_not_zero_ground_truth(wl, tmp_path, raw):
    """F2: totals must not be published as known zeros; position_tiny must not be asserted."""
    (tmp_path / "holdings.json").write_bytes(raw)
    out = wl._get_portfolio_context(_Conn(), "AAA")
    assert out["positions_available"] is False
    assert out["holdings_state"] != "ok"
    assert out["position_tiny"] is False
    assert out["position_small"] is False


def test_portfolio_context_null_account_summaries_does_not_crash(wl, tmp_path):
    (tmp_path / "holdings.json").write_text('{"holdings": [], "account_summaries": null}')
    out = wl._get_portfolio_context(_Conn(), "AAA")
    assert out["positions_available"] is True
    assert out["total_shares"] == 0


def test_portfolio_context_healthy_store_reports_the_holding(wl, tmp_path):
    (tmp_path / "holdings.json").write_text(
        json.dumps(
            {
                "holdings": [{"symbol": "AAA", "account": "schwab_taxable", "shares": 10, "market_value": 1200.0}],
                "account_summaries": {"schwab_taxable": {"total_value": 50000}},
            }
        )
    )
    out = wl._get_portfolio_context(_Conn(), "AAA")
    assert out["positions_available"] is True
    assert out["total_shares"] == 10
    assert out["portfolio_weight"] == 2.4


@pytest.mark.parametrize("raw", DAMAGED_RAW)
def test_layer_status_says_unknown_not_in_range(wl, tmp_path, raw):
    """F2: zero-against-target is not an allocation fact while the snapshot is unreadable."""
    (tmp_path / "holdings.json").write_bytes(raw)
    text = wl._build_layer_status(_Conn())
    assert "UNKNOWN" in text
    assert "IN RANGE" not in text
