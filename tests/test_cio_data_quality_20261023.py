"""CIO data quality (operator 2026-10-23). Hermetic: fixtures and tmp_path state roots only; no DB, network or send.

1. Stop ordering. stop_lifecycle ids run backwards in time for one position, so ordering by id read NAVN as
   "raised 1x from 26.02". Rows are ordered by the broker order id (as PR #2008's Watch code does): NAVN's real
   seven rows give 24.59 -> 24.31 -> 24.70 -> 24.97 -> 25.51 -> 25.61 -> 26.02, raised 5x, filled at 26.02.
2. Hermes catalyst identity (lib/hermes_scalp_catalyst_record.verify_identity). A catalyst whose headline or source does not name the company (whole word) or that
   came from a generic index page is UNVERIFIED_IDENTITY, never FOUND: AARD -> an Archrock headline, YMAT / INVE ->
   the nfl.com "ALL NEWS" page.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_prospect_builder as B  # noqa: E402
from scripts.lib import cio_prospect_lifecycle as lcm  # noqa: E402
from scripts.lib import hermes_scalp_catalyst_record as hci  # noqa: E402
from scripts.lib.hermes_scalp_catalyst_record import select_scalp_catalyst  # noqa: E402

FX = json.loads((ROOT / "tests/fixtures/cio_data_quality/cio_data_quality_20261023.json").read_text())
NAMES = {}
for _r in FX["sec_company_tickers"].values():
    NAMES.setdefault(_r["ticker"], []).append(_r["title"])


# ── 1. stop_lifecycle ordering (NAVN) ─────────────────────────────────────────────────────────────────────


def _db(rows):
    def q(sql, params=None):
        return copy.deepcopy(rows) if "FROM stop_lifecycle" in sql else []
    return q


def test_navn_id_order_is_backwards_in_time_the_defect():
    rows = copy.deepcopy(FX["stop_history"])  # id AS seq, as the SQL returns it
    st = lcm.stop_path(rows)
    assert st["initial"] == 26.02 and st["ratchets_up"] == 1  # "raised 1x from 26.02" — what the operator saw


def test_navn_ordered_by_broker_order_id_raised_five_times():
    inputs = B.load_lifecycle_inputs(_db(FX["stop_history"]))
    rows = inputs["stop_history"]["rows"]["NAVN"]
    st = lcm.stop_path(rows)
    assert [p["stop_price_observed"] for p in st["path"]] == FX["expected_stop_path_in_time"]
    assert st["initial"] == 24.59 and st["last"] == 26.02 and st["filled"] == 26.02
    assert st["ratchets_up"] == 5
    assert all(r["seq_basis"] == "broker_order_id" for r in rows)
    assert sorted(r["row_id"] for r in rows) == sorted(r["seq"] for r in FX["stop_history"])  # row id kept


def test_captured_rows_are_reordered_the_same_way():
    inputs = B.load_lifecycle_inputs(None, captured={"stop_history": copy.deepcopy(FX["stop_history"])})
    st = lcm.stop_path(inputs["stop_history"]["rows"]["NAVN"])
    assert st["ratchets_up"] == 5 and st["initial"] == 24.59


def test_exit_cause_names_five_raises():
    inputs = B.load_lifecycle_inputs(_db(FX["stop_history"]))
    st = lcm.stop_path(inputs["stop_history"]["rows"]["NAVN"])
    cause = lcm.classify_exit(26.02, 25.64, st, None)
    assert cause["class"] == "trailing_ratchet"
    assert "raised 5x" in cause["evidence"]


def test_order_ids_not_all_numeric_keep_row_order():
    rows = [{"symbol": "X", "order_id": "x-2", "stop_price": 2.0, "seq": 1},
            {"symbol": "X", "order_id": "100", "stop_price": 1.0, "seq": 2}]
    assert B.order_stops_by_broker_order(rows) == rows
    assert [r["seq"] for r in rows] == [1, 2] and "seq_basis" not in rows[0]


def test_watch_reordering_is_idempotent_with_the_builder():
    """PR #2008's Watch code re-applies seq = int(order_id) after load; the result must not change."""
    inputs = B.load_lifecycle_inputs(_db(FX["stop_history"]))
    rows = inputs["stop_history"]["rows"]["NAVN"]
    before = lcm.stop_path(copy.deepcopy(rows))
    for r in rows:
        r["seq"] = int(r["order_id"])
    assert lcm.stop_path(rows) == before


# ── 2. Hermes catalyst identity ───────────────────────────────────────────────────────────────────────────


def _lines(*recs):
    return [json.dumps(r) for r in recs]


def test_ymat_and_inve_nfl_all_news_page_is_unverified_not_found():
    for sym in ("YMAT", "INVE"):
        rec = select_scalp_catalyst(sym, _lines(FX["catalysts"][sym]), NAMES.get(sym, []))
        assert rec["status"] == "UNVERIFIED_IDENTITY", sym
        assert "generic title 'ALL NEWS'" in rec["identity"]["reason"]


def test_nfl_index_url_rejected_even_with_a_specific_title():
    rec = dict(FX["catalysts"]["YMAT"], catalyst_summary="YMAT soars on contract")
    rec["sources"] = [dict(rec["sources"][0], title="YMAT soars on contract")]
    out = hci.verify_identity("YMAT", rec, NAMES["YMAT"])
    assert out["status"] == hci.UNVERIFIED_IDENTITY and "index URL (/series/)" in out["reason"]


def test_aard_archrock_headline_is_unverified_not_found():
    rec = select_scalp_catalyst("AARD", _lines(FX["catalysts"]["AARD"]), NAMES["AARD"])
    assert rec["status"] == "UNVERIFIED_IDENTITY"
    assert rec["identity"]["names"] == ["aardvark therapeutics", "aardvark"]
    assert "AARD" in rec["identity"]["reason"]


def test_aard_real_aardvark_headline_is_found():
    rec = dict(FX["catalysts"]["AARD"], catalyst_summary="Aardvark Therapeutics Announces Inducement Grant")
    rec["sources"] = [{"title": rec["catalyst_summary"],
                       "url": "https://finance.yahoo.com/healthcare/articles/aardvark-therapeutics-announces-200500686.html",
                       "content": ""}]
    got = select_scalp_catalyst("AARD", _lines(rec), NAMES["AARD"])
    assert got["status"] == "FOUND" and got["identity"]["evidence"] == "headline"


def test_whole_word_only():
    base = {"catalyst_type": "news_momentum", "sources": []}
    # substring is not a match: "AARDVARKS" / "MAARD" do not name AARD; lower-case "aard" in prose does not either
    for text in ("AARDVARKS rally on sector news", "MAARD files 10-K", "aard rally"):
        assert hci.verify_identity("AARD", dict(base, catalyst_summary=text))["status"] == hci.UNVERIFIED_IDENTITY, text
    for text in ("AARD jumps 40%", "Why $AARD is moving", "Shares of (NASDAQ:AARD) gap up"):
        assert hci.verify_identity("AARD", dict(base, catalyst_summary=text))["status"] == hci.VERIFIED, text


def test_ticker_only_when_no_company_names():
    rec = {"catalyst_type": "earnings", "catalyst_summary": "Aardvark Therapeutics beats", "sources": []}
    assert hci.verify_identity("AARD", rec, [])["status"] == hci.UNVERIFIED_IDENTITY
    assert hci.verify_identity("AARD", rec, NAMES["AARD"])["status"] == hci.VERIFIED


def test_source_slug_or_snippet_can_carry_identity():
    rec = {"catalyst_type": "contract", "catalyst_summary": "Wins $40M federal contract",
           "sources": [{"title": "Wins $40M federal contract", "content": "",
                        "url": "https://www.prnewswire.com/news-releases/aardvark-therapeutics-wins-contract-302.html"}]}
    assert hci.verify_identity("AARD", rec, NAMES["AARD"])["evidence"] == "source URL"
    rec["sources"][0]["url"] = "https://www.prnewswire.com/news-releases/aard-wins-contract-302.html"
    assert hci.verify_identity("AARD", rec, [])["status"] == hci.UNVERIFIED_IDENTITY  # a ticker is never case-folded
    rec["sources"][0].update(url="https://www.prnewswire.com/news-releases/x-302.html",
                             content="Aardvark Therapeutics, Inc. today announced ...")
    assert hci.verify_identity("AARD", rec, NAMES["AARD"])["evidence"] == "source snippet"


def test_false_positives_seen_in_the_real_day_files():
    """Read-only replay of 2026-10-16..23 found these; each must stay UNVERIFIED_IDENTITY."""
    betr = {"catalyst_type": "news_momentum",
            "catalyst_summary": "Polizei-News Landkreis Rostock / Rostock, 20.10.26: Betrüger erbeuten Geld",
            "sources": [{"title": "Polizei-News Landkreis Rostock", "content": "",
                         "url": "https://www.news.de/lokales/polizei-news-rostock-betr%C3%BCger-erbeuten-geld/"}]}
    assert hci.verify_identity("BETR", betr, ["Better Home & Finance Holding Co"])["status"] == hci.UNVERIFIED_IDENTITY
    host = {"catalyst_type": "earnings",
            "catalyst_summary": "Flutter Entertainment to Report Third Quarter 2026 Update and Host a Conference Call",
            "sources": [{"title": "Flutter Entertainment to Report Q3", "content": "",
                         "url": "https://www.businesswire.com/news/home/2026/flutter-to-report-and-host-a-conference-call"}]}
    assert hci.verify_identity("HOST", host, ["Host Digital Inc."])["status"] == hci.UNVERIFIED_IDENTITY


def test_legal_suffixes_and_edgar_markers_are_dropped():
    assert hci.name_phrases(["AMERICA MOVIL SAB DE CV/"]) == ["america movil"]
    assert hci.name_phrases(["KEYCORP /NEW/"]) == ["keycorp"]
    assert hci.name_phrases(["J-Star Holding Co., Ltd."]) == ["j-star"]
    rec = {"catalyst_type": "analyst", "catalyst_summary": "UBS Adjusts America Movil SAB de CV Price Target to $31",
           "sources": []}
    assert hci.verify_identity("AMX", rec, ["AMERICA MOVIL SAB DE CV/"])["status"] == hci.VERIFIED


def test_generic_index_pages():
    assert hci.generic_index_page("ALL NEWS", None)
    assert hci.generic_index_page("Latest Headlines", None)
    assert hci.generic_index_page("Top Stories", None)
    assert hci.generic_index_page("x", "https://www.nfl.com/news/series/all-news")
    assert hci.generic_index_page("x", "https://www.cnbc.com/")
    assert hci.generic_index_page("x", "https://www.reuters.com/markets/")
    assert hci.generic_index_page("x", "https://site.com/tag/biotech")
    assert hci.generic_index_page("Aardvark Therapeutics Announces Inducement Grant",
                                  "https://finance.yahoo.com/healthcare/articles/aardvark-therapeutics-1.html") is None


def test_none_found_is_untouched():
    rec = {"symbol": "AARD", "research_timestamp": "2026-10-23T13:25:23", "catalyst_type": "no_clear_catalyst",
           "catalyst_summary": "No clear catalyst found", "sources": []}
    got = select_scalp_catalyst("AARD", _lines(rec), NAMES["AARD"])
    assert got["status"] == "NONE_FOUND" and got["identity"] is None


def test_company_names_reads_the_sec_map_read_only(tmp_path):
    from lib.data_broker import scalp_list

    assert hci.sec_name_index(FX["sec_company_tickers"])["AARD"] == ["Aardvark Therapeutics, Inc."]
    (tmp_path / "data/runtime").mkdir(parents=True)
    p = tmp_path / hci.SEC_TICKERS_REL
    p.write_text(json.dumps(FX["sec_company_tickers"]))
    before = p.read_bytes()
    assert scalp_list._company_names("aard", tmp_path) == ["Aardvark Therapeutics, Inc."]
    assert scalp_list._company_names("NOPE", tmp_path) == []
    assert scalp_list._company_names("AARD", tmp_path / "missing") == []
    assert p.read_bytes() == before


def test_both_readers_return_unverified_for_the_nfl_page(tmp_path):
    from lib import scanner_candidate_projection as proj
    from lib.data_broker import scalp_list

    day = "2026-10-23"
    store = tmp_path / "data/hermes/momentum_catalysts"
    store.mkdir(parents=True)
    (tmp_path / "data/runtime").mkdir(parents=True)
    (tmp_path / "data/runtime/sec_company_tickers.json").write_text(json.dumps(FX["sec_company_tickers"]))
    good = dict(FX["catalysts"]["AARD"], catalyst_summary="Aardvark Therapeutics Announces Inducement Grant",
                sources=[{"title": "Aardvark Therapeutics Announces Inducement Grant",
                          "url": "https://finance.yahoo.com/healthcare/articles/aardvark-1.html"}])
    (store / f"{day}_catalysts.jsonl").write_text("\n".join(_lines(FX["catalysts"]["YMAT"], good)) + "\n")
    broker = scalp_list.get_scalp_catalyst("YMAT", day, root=tmp_path)
    lookup = proj._hermes_catalyst_lookup(tmp_path)
    assert broker["status"] == lookup("YMAT", day)["status"] == "UNVERIFIED_IDENTITY"
    assert scalp_list.get_scalp_catalyst("AARD", day, root=tmp_path)["status"] == "FOUND"
    assert lookup("AARD", day)["status"] == "FOUND"


def test_ci_gate_registered():
    doc = json.loads((ROOT / "config/ci_gates/cio_data_quality_20261023.json").read_text())
    assert doc["anchor"] == "CIO_DATA_QUALITY_20261023"
    assert doc["files"] == ["tests/test_cio_data_quality_20261023.py"]
