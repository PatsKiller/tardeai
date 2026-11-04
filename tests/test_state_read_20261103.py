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
                ]
            }
        )
    )
    monkeypatch.setattr(si, "PROJECT_ROOT", tmp_path)
    assert si._get_holdings_symbols() == ["AAA"]


def test_a_blank_symbol_row_is_an_unreadable_book_not_a_row_to_filter(tmp_path, monkeypatch):
    """cc-deepseek-6, #2545 P2-2. This used to be a *filtered* row: ``{"symbol": ""}`` was dropped and the rest of
    the book was returned, so a document whose rows the consumer cannot read produced a confident shorter book.
    A row that names no security is not a holding to skip — it makes the document one this reader cannot read."""
    import social_ingest as si

    state_dir = tmp_path / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "holdings.json").write_text(json.dumps({"holdings": [{"symbol": "AAA"}, {"symbol": ""}]}))
    monkeypatch.setattr(si, "PROJECT_ROOT", tmp_path)
    assert si.holdings_universe() == ([], "invalid_shape")


# ── cx-openai-2 BLOCK at 85a573e6c: consumer shape (F1), unknown not empty (F2), decoder (F3) ──

DAMAGED_RAW = (b"", b"{not json", b"\xff\xfe\x00", b"[1,2]", b"null", b"   \n")
#: Shapes that parse but are not a book this module can read. The last two are cx-deepseek-6's #2545 P2-2: a
#: foreign document (rows keyed by a field the consumers never read) used to read ``ok``, and the analyst prompt
#: then asserted "NOT CURRENTLY HELD" from it — a confident ownership claim derived from rows nobody could read.
WRONG_SHAPE = ('{"holdings": null}', '{"holdings": {"AAA": {}}}', '{"holdings": [1]}',
               '{"holdings": [{"ticker": "AAA"}]}',
               '{"holdings": [{"symbol": "AAA"}, {"ticker": "BBB"}]}',
               '{"holdings": [{"symbol": "   "}]}')


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


def test_a_document_whose_rows_name_no_security_is_invalid_shape(tmp_path):
    """cc-deepseek-6, #2545 P2-2. Measured at 8e44863458f7: ``{"holdings": [{"ticker": "AAA"}]}`` returned ``ok``,
    so ``holdings_known`` was True with an empty position set and the consumer rendered "NOT CURRENTLY HELD (0
    shares in any account)". A row the consumers cannot key a position by is not a holding, and a book is only
    readable when every row in it is."""
    p = tmp_path / "holdings.json"
    cases = {
        '{"holdings": [{"ticker": "AAA"}]}': "invalid_shape",                    # a foreign document
        '{"holdings": [{"symbol": "AAA"}, {"ticker": "BBB"}]}': "invalid_shape",  # one unreadable row poisons the book
        '{"holdings": [{"symbol": ""}]}': "invalid_shape",                        # a blank name is not a name
        '{"holdings": [{"symbol": "  "}]}': "invalid_shape",
        '{"holdings": [{"symbol": 42}]}': "invalid_shape",                         # a number is not a ticker
        '{"holdings": [{"symbol": "AAA"}]}': "ok",
        '{"holdings": [{"symbol": "CASH", "is_cash": true}]}': "ok",               # the live cash-row shape
        '{"holdings": []}': "ok",
    }
    for raw, expected in cases.items():
        p.write_text(raw)
        doc, state = sr.read_holdings_state(p)
        assert state == expected, f"{raw}: got {state!r}, expected {expected!r}"
        assert (doc is not None) == (expected == "ok")


def test_states_is_the_union_and_the_docstring_says_which_reader_owns_invalid_shape():
    """P3: ``STATES`` is the union of this module's readers. ``invalid_shape`` is a consumer-shape verdict from
    ``read_holdings_state``; ``read_json_state`` never returns it, and both docstrings now say so, so a consumer
    switching on ``STATES`` is not surprised by a member the byte reader cannot produce."""
    assert "invalid_shape" in sr.STATES
    reader_doc = sr.read_json_state.__doc__ or ""
    assert "never returned here" in reader_doc and "belongs to ``read_holdings_state``" in reader_doc
    holdings_doc = sr.read_holdings_state.__doc__ or ""
    assert "``invalid_shape``" in holdings_doc


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


def test_social_ingest_carries_the_holdings_state_into_the_lane_receipt(tmp_path, monkeypatch):
    """cc-deepseek-6, #2545 P2-1. The lane discarded the state, so a 0-byte or unparseable store produced a run
    indistinguishable from a healthy one whose book held no qualifying symbol (the header calls an empty symbol
    list a successful poll). The state now travels into the receipt, and the lane still succeeds: the symbol list
    is optional context. Driven through ``main()``, asserted on the summary handed to the receipt writer."""
    import types

    import social_ingest as si

    state_dir = tmp_path / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "holdings.json").write_bytes(b"")
    monkeypatch.setattr(si, "PROJECT_ROOT", tmp_path)

    stubbed = types.ModuleType("pipeline_registry")
    stubbed.run_start = lambda *a, **k: None
    stubbed.run_complete = lambda *a, **k: None
    stubbed.run_fail = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "pipeline_registry", stubbed)

    written = {}

    class _Receipt:
        def now_iso(self):
            return "2026-11-04T00:00:00+00:00"

        def write_lane_receipt(self, lane, **kwargs):
            written["lane"] = lane
            written["summary"] = kwargs.get("summary")
            return "/tmp/receipt.json"

        def dry_run_report(self, *a, **k):  # pragma: no cover - not reached
            raise AssertionError("a real run must not write a dry-run report")

    monkeypatch.setattr(si, "_receipt_lib", lambda: _Receipt())
    monkeypatch.setattr(si, "ingest_stocktwits", lambda syms: {"inserted": 0, "skipped": 0, "errors": []})
    monkeypatch.setattr(si, "ingest_stocktwits_discovery", lambda: {"inserted": 0, "skipped": 0, "errors": []})
    monkeypatch.setattr(si, "ingest_reddit_with_discovery", lambda: {"inserted": 0, "skipped": 0, "errors": []})

    assert si.main(["--source", "all"]) == 0
    assert written["lane"] == "social-ingest-all"
    assert written["summary"]["holdings_state"] == "empty"
    assert written["summary"]["holdings_damaged"] is True
    assert written["summary"]["source"] == "all"
    assert written["summary"]["rows_produced"] == 0


def test_social_ingest_reports_a_healthy_read_as_ok(tmp_path, monkeypatch):
    """The control in the other direction: a healthy store must not be flagged as damaged."""
    import social_ingest as si

    state_dir = tmp_path / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "holdings.json").write_text(json.dumps({"holdings": [{"symbol": "AAA"}]}))
    monkeypatch.setattr(si, "PROJECT_ROOT", tmp_path)
    assert si.holdings_universe() == (["AAA"], "ok")


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


# ── the class guard: no damaged-store path may render a confident claim (lead, 2026-11-03) ──────
# Every individual case above pins one surface. This one fails if ANY damaged path — bad bytes or a
# wrong consumer shape — can render "not held", "0 shares", "zero", or "IN RANGE" without an explicit
# unavailable indicator. It is the assertion the whole PR exists to make.
CONFIDENT_PHRASES = ("NOT CURRENTLY HELD", "0 shares", "IN RANGE", "0.0%", "portfolio_weight")

DAMAGED_CASES = tuple(("bytes:" + repr(raw), raw) for raw in DAMAGED_RAW) + tuple(
    ("shape:" + doc, doc.encode()) for doc in WRONG_SHAPE
)


@pytest.mark.parametrize("label,raw", DAMAGED_CASES, ids=[c[0] for c in DAMAGED_CASES])
def test_no_damaged_path_renders_a_confident_claim(wl, tmp_path, label, raw):
    (tmp_path / "holdings.json").write_bytes(raw)

    ctx = wl._get_context(_Conn(), "AAA")
    port = wl._get_portfolio_context(_Conn(), "AAA")
    layers = wl._build_layer_status(_Conn())

    # 1. The analyst prompt must not assert ownership either way.
    for phrase in ("NOT CURRENTLY HELD", "0 shares"):
        assert phrase not in ctx["text"], f"{label}: prompt asserted {phrase!r} from a damaged store"
    # 2. It must carry an explicit unavailable indicator instead.
    assert ctx["snapshot"]["positions_available"] is False, f"{label}: prompt claims positions are known"
    assert ctx["snapshot"]["holdings_state"] != "ok"
    assert "UNKNOWN" in ctx["text"]

    # 3. The synthesis ground-truth block must not assert zero shares / tiny position.
    assert port["positions_available"] is False
    assert port["position_tiny"] is False and port["position_small"] is False
    assert port["total_shares"] == 0 and port["accounts"] == []  # placeholders, flagged unavailable

    # 4. Layer allocation must not render a range verdict from a file it could not read.
    assert "IN RANGE" not in layers
    assert "UNKNOWN" in layers


def test_within_portfolio_and_layer_status_weights_are_not_confident(wl, tmp_path):
    """A damaged store must not yield a CONCRETE weight string anywhere in the layer block."""
    (tmp_path / "holdings.json").write_bytes(b"")
    layers = wl._build_layer_status(_Conn())
    assert "actual=" not in layers


def test_an_absent_store_does_not_crash_any_consumer(wl, tmp_path):
    """ABSENT means "no snapshot" (an empty book), and an empty book must still not crash a consumer.

    Found at the frozen 6575714b9: `_build_layer_status` iterated `holdings.get(...)` with
    `holdings is None` on this path. The contract stays (absent = no positions); the crash does not.
    """
    out_ctx = wl._get_context(_Conn(), "AAA")
    out_port = wl._get_portfolio_context(_Conn(), "AAA")
    text = wl._build_layer_status(_Conn())
    assert out_ctx["snapshot"]["holdings_state"] == "absent"
    assert out_ctx["snapshot"]["positions_available"] is True
    assert "NOT CURRENTLY HELD" in out_ctx["text"]
    assert out_port["positions_available"] is True and out_port["total_shares"] == 0
    assert isinstance(text, str)  # absent is an empty book, not an unreadable file


def test_a_path_like_store_that_is_a_directory_does_not_crash_any_consumer(wl, tmp_path):
    (tmp_path / "holdings.json").mkdir()
    out_ctx = wl._get_context(_Conn(), "AAA")
    assert out_ctx["snapshot"]["positions_available"] is False
    assert out_ctx["snapshot"]["holdings_state"] == "unreadable"
    assert "NOT CURRENTLY HELD" not in out_ctx["text"]
    assert isinstance(wl._build_layer_status(_Conn()), str)
