"""Numbers truth audit (LQ-20261107-1701) — every displayed number against its truth.

Design: DSN-20261109-numbers-truth-audit.md rev 1 §1-2, REV 2 (DB is the system of record; current nav only;
stop_lifecycle canonical, stop_last_known a retiring copy; never yfinance) and REV 3 (the `authority` family G1-G3).

The three real defects this family exists to catch, each pinned by a fail-before / pass-after pair here:
  * an "unprotected" count that omits a held position with no working stop (the XLV case);
  * a stop card that names the wrong session day (the "Friday" label);
  * a stop the broker already cancelled still shown working (the SPCX case).

Hermetic: the DB, the HTTP surface, the clock and the files are injected. Synthetic ZQ* symbols and round numbers
only — this repository is public. Nothing here writes to a store, a broker or a scheduler.
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import numbers_truth_audit as T  # noqa: E402

#: Wed 2026-10-21, 14:00 ET — a trading day, in session.
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
SESSION_DATE = "2026-10-21"


def _iso(mins_ago: float) -> str:
    return (NOW - timedelta(minutes=mins_ago)).isoformat()


POS_AS_OF = _iso(5)
STOP_AS_OF = _iso(5)
QUOTE_AS_OF = _iso(3)

P_AA = {"account_key": "zz_taxable", "symbol": "ZQAA", "qty": 100, "broker_market_value": 10000.0,
        "is_cash": False, "asset_type": "equity", "as_of": POS_AS_OF}
P_AB = {"account_key": "zz_ira", "symbol": "ZQAB", "qty": 50, "broker_market_value": 5000.0,
        "is_cash": False, "asset_type": "equity", "as_of": POS_AS_OF}
P_CASH = {"account_key": "zz_taxable", "symbol": "ZQCASH", "qty": 1234.5, "broker_market_value": 1234.5,
          "is_cash": True, "asset_type": "cash", "as_of": POS_AS_OF}

S_AA = {"account": "zz_taxable", "symbol": "ZQAA", "lifecycle": "working", "stop_price": 80.0, "qty": 100,
        "snapshot_at": STOP_AS_OF}
S_AB = {"account": "zz_ira", "symbol": "ZQAB", "lifecycle": "working", "stop_price": 90.0, "qty": 50,
        "snapshot_at": STOP_AS_OF}

K_AA = {"account": "zz_taxable", "symbol": "ZQAA", "status": "working", "stop_price": 80.0, "qty": 100,
        "captured_at": STOP_AS_OF}
K_AB = {"account": "zz_ira", "symbol": "ZQAB", "status": "working", "stop_price": 90.0, "qty": 50,
        "captured_at": STOP_AS_OF}

Q_AA = {"symbol": "ZQAA", "source": "finviz", "price": 100.0, "fetched_at": QUOTE_AS_OF}
Q_AB = {"symbol": "ZQAB", "source": "finviz", "price": 100.0, "fetched_at": QUOTE_AS_OF}


def H(account="zz_taxable", symbol="ZQAA", shares=100, market_value=10000.0, price=100.0,
      stop_price=80.0, stop_state="active", stop_qty=100) -> dict:
    return {"account_key": account, "symbol": symbol, "shares": shares, "market_value": market_value,
            "price": price, "stop_price": stop_price, "stop_state": stop_state, "stop_qty": stop_qty,
            "broker_position_as_of_at": POS_AS_OF}


def brief(*, uncovered=1, session_date=SESSION_DATE, close_tag="Wed close", label="Since Wed 4:00 PM",
          holdings=None, stop_advice=None) -> dict:
    return {"generated_at": _iso(30),
            "last_close": {"session_date": session_date},
            "counts": {"uncovered_positions": uncovered},
            "holdings": holdings if holdings is not None else [
                {"symbol": "ZQAA", "price": 100.0, "quote_source": "finviz_elite"},
                {"symbol": "ZQAB", "price": 100.0, "quote_source": "finviz_elite"}],
            "stop_advice": stop_advice if stop_advice is not None else [
                {"account": "zz_taxable", "symbol": "ZQAA", "stop_now": 80.0, "stop_qty": 100},
                {"account": "zz_ira", "symbol": "ZQAB", "stop_now": 90.0, "stop_qty": 50}]}


def since_close(*, close_tag="Wed close", label="Since Wed 4:00 PM", session_date=SESSION_DATE) -> dict:
    return {"generated_at": _iso(30),
            "window": {"close_tag": close_tag, "label": label, "session_date": session_date}}


def write_state(tmp: Path, *, holdings=None, brief_doc=None, since=None) -> Path:
    root = tmp / "state"
    (root / "data/portfolios/state").mkdir(parents=True, exist_ok=True)
    (root / "data/runtime/cio_overnight_brief").mkdir(parents=True, exist_ok=True)
    if holdings is not None:
        (root / "data/portfolios/state/holdings.json").write_text(json.dumps({"holdings": holdings}))
    if brief_doc is not None:
        (root / "data/runtime/cio_overnight_brief/latest.json").write_text(json.dumps(brief_doc))
    if since is not None:
        (root / "data/portfolios/state/since_close_latest.json").write_text(json.dumps(since))
    return root


def bundle(*, positions=None, stops=None, slk=None, quotes=None, pos_as_of=POS_AS_OF,
           stop_as_of=STOP_AS_OF, quote_as_of=QUOTE_AS_OF, quotes_ok=True) -> T.Bundle:
    b = T.Bundle()
    b.put("positions", rows=list(positions if positions is not None else [P_AA, P_AB]),
          as_of=T._ts(pos_as_of))
    b.put("stops", rows=list(stops if stops is not None else [S_AA, S_AB]), as_of=T._ts(stop_as_of))
    b.put("stop_last_known", rows=list(slk if slk is not None else [K_AA, K_AB]))
    if quotes_ok:
        b.put("quotes", rows=list(quotes if quotes is not None else [Q_AA, Q_AB]),
              as_of=T._ts(quote_as_of),
              by_symbol={r["symbol"]: r for r in (quotes if quotes is not None else [Q_AA, Q_AB])})
    else:
        b.put("quotes", reason="quotes_unreadable: OperationalError")
    return b


def catalog(*figure_ids: str) -> dict:
    """The real catalog, restricted to these rows, minus the authority family (that needs a DB/subprocess)."""
    c = T.load_catalog()
    pol = dict(c["policy"])
    pol.pop("authority", None)
    pol.pop("write_watch", None)
    return {"schema": c["schema"], "nav_config": c["nav_config"], "codes": c["codes"], "policy": pol,
            "rows": [dict(r) for r in c["rows"] if r["figure_id"] in figure_ids]}


def run(tmp: Path, *figure_ids: str, b=None, doc=None, http_open=False, now=NOW, deadline=None,
        authority_runners=None) -> dict:
    return T.audit(catalog(*figure_ids), b or bundle(), now=now, state_root=tmp, http_open=http_open,
                   base_url="http://127.0.0.1:7777", fetcher=(lambda _q: doc) if doc is not None else None,
                   deadline=deadline, authority_runners=authority_runners)


def codes(rep: dict) -> list[str]:
    return sorted(f["code"] for f in rep["findings"])


def without(rep: dict, *feature_ids: str) -> list[dict]:
    return [f for f in rep["findings"] if f["figure_id"] not in feature_ids]


# ── the catalog is the contract ────────────────────────────────────────────────────────────────────────────────


def test_catalog_is_valid_and_every_page_is_a_current_nav_route():
    cat = T.load_catalog()
    assert T.validate_catalog(cat) == []
    routes = T.nav_routes(ROOT / cat["nav_config"])
    assert {r["page"] for r in cat["rows"]} <= routes
    assert {r["figure_id"] for r in cat["rows"]} >= {
        "holdings.qty", "holdings.stop_state", "cio.uncovered_count", "sinceclose.session_label"}


def test_a_catalog_row_for_a_route_not_in_navconfig_is_refused():
    cat = T.load_catalog()
    bad = json.loads(json.dumps(cat))
    bad["rows"][0]["page"] = "/retired-classic-page"
    problems = T.validate_catalog(bad)
    assert any("not a route in navConfig" in p for p in problems), problems


def test_a_catalog_row_naming_an_unimplemented_checker_is_refused():
    cat = json.loads(json.dumps(T.load_catalog()))
    cat["rows"][0]["check"] = "vibes"
    assert any("'vibes' is not implemented" in p for p in T.validate_catalog(cat))


def test_every_emitted_code_is_in_the_catalog_closed_set():
    declared = set(T.load_catalog()["codes"])
    found = {"NT_QTY_MISMATCH", "NT_UNPROTECTED", "NT_SESSION_LABEL", "NT_STOP_STATE_MISMATCH",
             "NT_STOP_CROSS_CHECK", "NT_AUTHORITY_WRITE", "NT_AUTHORITY_STATIC", "NT_QUOTE_SOURCE",
             "NT_NOT_MEASURED"}
    # every code this module can emit, as literals in its own source
    src = (ROOT / "scripts/numbers_truth_audit.py").read_text(encoding="utf-8")
    emitted = {n.value for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("NT_")}
    assert emitted <= declared, sorted(emitted - declared)
    assert found <= declared


# ── shares: exact, P0 ─────────────────────────────────────────────────────────────────────────────────────────


def test_a_wrong_share_count_is_a_p0_finding_with_both_sides(tmp_path):
    root = write_state(tmp_path, holdings=[H(shares=99), H(account="zz_ira", symbol="ZQAB", shares=50,
                                                          market_value=5000.0)])
    rep = run(root, "holdings.qty")
    assert codes(rep) == ["NT_QTY_MISMATCH"]
    f = rep["findings"][0]
    assert f["severity"] == "P0"
    assert f["fingerprint"] == "/portfolio|holdings.qty|zz_taxable|ZQAA"
    assert f["shown"]["value"] == 99 and f["truth"]["value"] == 100
    assert f["truth"]["provider"] == "positions_current" and f["truth"]["as_of"] == POS_AS_OF
    assert f["producer_lane"] == "positions-sync"


def test_an_exact_share_match_is_clean(tmp_path):
    root = write_state(tmp_path, holdings=[H(), H(account="zz_ira", symbol="ZQAB", shares=50,
                                                   market_value=5000.0)])
    assert run(root, "holdings.qty")["findings"] == []


def test_a_shown_holding_with_no_truth_row_is_a_mismatch_not_a_pass(tmp_path):
    root = write_state(tmp_path, holdings=[H(), H(account="zz_ira", symbol="ZQAB", shares=50,
                                                   market_value=5000.0),
                                           H(account="zz_ira", symbol="ZQBA", shares=1)])
    rep = run(root, "holdings.qty")
    assert codes(rep) == ["NT_QTY_MISMATCH"]
    assert "has no row" in rep["findings"][0]["detail"]


def test_a_held_position_the_page_omits_is_a_mismatch(tmp_path):
    root = write_state(tmp_path, holdings=[H()])  # ZQAB is held but not shown
    rep = run(root, "holdings.qty")
    assert [f["symbol"] for f in rep["findings"]] == ["ZQAB"]
    assert "does not show it" in rep["findings"][0]["detail"]


def test_a_stale_positions_store_is_not_measured_in_session(tmp_path):
    root = write_state(tmp_path, holdings=[H()])
    rep = run(root, "holdings.qty", b=bundle(pos_as_of=_iso(90)))
    assert codes(rep) == ["NT_NOT_MEASURED"]
    assert rep["findings"][0]["reason"] == "stale_truth"


# ── market value and price ───────────────────────────────────────────────────────────────────────────────────


def test_market_value_within_one_dollar_is_clean_and_beyond_it_is_a_finding(tmp_path):
    root = write_state(tmp_path, holdings=[H(market_value=10000.75),
                                           H(account="zz_ira", symbol="ZQAB", shares=50, market_value=5000.0)])
    assert run(root, "holdings.market_value")["findings"] == []
    root = write_state(tmp_path, holdings=[H(market_value=10005.0),
                                           H(account="zz_ira", symbol="ZQAB", shares=50, market_value=5000.0)])
    rep = run(root, "holdings.market_value")
    assert codes(rep) == ["NT_VALUE_MISMATCH"]
    assert rep["findings"][0]["shown"]["value"] == 10005.0


def test_price_compares_within_half_a_percent_against_an_allowed_quote(tmp_path):
    root = write_state(tmp_path, holdings=[H(price=100.25),
                                           H(account="zz_ira", symbol="ZQAB", shares=50, price=100.0)])
    assert run(root, "holdings.price")["findings"] == []
    root = write_state(tmp_path, holdings=[H(price=102.0),
                                           H(account="zz_ira", symbol="ZQAB", shares=50, price=100.0)])
    rep = run(root, "holdings.price")
    assert codes(rep) == ["NT_PRICE_MISMATCH"]
    assert "2" in rep["findings"][0]["detail"]  # the drift is named


def test_a_price_matching_only_a_retired_provider_is_a_fail_not_a_pass(tmp_path):
    # the bundle's quote filter is what excludes yfinance; with no allowed row the price is NOT_MEASURED
    root = write_state(tmp_path, holdings=[H(price=100.0),
                                           H(account="zz_ira", symbol="ZQAB", shares=50, price=100.0)])
    rep = run(root, "holdings.price", b=bundle(quotes_ok=False))
    assert codes(rep) == ["NT_NOT_MEASURED"]
    assert {f["reason"] for f in rep["findings"]} == {"truth_unreadable"}


def test_a_displayed_price_with_no_allowed_quote_is_not_measured(tmp_path):
    root = write_state(tmp_path, holdings=[H(price=100.0)])  # ZQAA
    rep = run(root, "holdings.price", b=bundle(quotes=[Q_AB]))  # no ZQAA quote at all
    assert codes(rep) == ["NT_NOT_MEASURED"]
    assert rep["findings"][0]["reason"] == "no_rows"


def test_a_displayed_price_backed_only_by_a_retired_provider_is_a_fail(tmp_path):
    root = write_state(tmp_path, holdings=[H(price=100.0)])
    b = bundle(quotes=[])
    b.put("quotes", rows=[], as_of=T._ts(QUOTE_AS_OF), retired_by_symbol={"ZQAA": "yfinance"})
    rep = run(root, "holdings.price", b=b)
    assert codes(rep) == ["NT_QUOTE_SOURCE"]
    assert "retired" in rep["findings"][0]["detail"]


def test_a_quote_stale_past_fifteen_minutes_is_not_measured(tmp_path):
    root = write_state(tmp_path, holdings=[H(), H(account="zz_ira", symbol="ZQAB", shares=50, price=100.0)])
    rep = run(root, "holdings.price", b=bundle(quote_as_of=_iso(40)))
    assert codes(rep) == ["NT_NOT_MEASURED"]
    assert {f["reason"] for f in rep["findings"]} == {"stale_truth"}


# ── stops: state, price, qty (the SPCX case) ─────────────────────────────────────────────────────────────────


def _stop_doc(state_aa="active", price_aa=80.0, qty_aa=100, state_ab="active") -> dict:
    """The /api/v2/portfolio/holdings shape: each row carries the stop_last_known copy merged in."""
    return {"holdings": [
        {"account_key": "zz_taxable", "symbol": "ZQAA", "stop_state": state_aa,
         "stop_price": price_aa, "stop_qty": qty_aa},
        {"account_key": "zz_ira", "symbol": "ZQAB", "stop_state": state_ab,
         "stop_price": 90.0, "stop_qty": 50}]}


def _stop_state(tmp_path, served_state: str, stops) -> dict:
    return run(tmp_path, "holdings.stop_state", b=bundle(stops=stops),
               doc=_stop_doc(state_aa=served_state), http_open=True)


@pytest.mark.parametrize("served,lifecycle,clean", [
    ("active", "working", True), ("active", "near_trigger", True),
    ("none", "cancelled", True), ("none", "expired", True),
    ("none", "filled", True),             # a filled order is history: it defends nothing, so "none" agrees
    ("active", "cancelled", False),       # the SPCX case: expired at the broker, still shown working
    ("active", "filled", False), ("none", "working", False), ("active", "wat", False),
])
def test_stop_state_is_the_lifecycle_mapped_into_the_served_vocabulary(tmp_path, served, lifecycle, clean):
    """Only a LIVE row (working / near_trigger) is the state of a stop: the snapshot also carries the
    cancelled/replaced/filled history of the same (account, symbol), and reading any of those as truth
    is the false positive that made five correct /cio rows look wrong on 2026-11-09."""
    stops = [dict(S_AA, lifecycle=lifecycle), S_AB]
    rep = _stop_state(tmp_path, served, stops)
    mismatch = [f for f in rep["findings"] if f["code"] == "NT_STOP_STATE_MISMATCH"]
    if clean:
        assert mismatch == []
    else:
        assert len(mismatch) == 1 and mismatch[0]["severity"] == "P0"
        assert mismatch[0]["truth"].get("raw") == (lifecycle if lifecycle in ("working", "near_trigger") else None)


def test_a_stop_the_broker_no_longer_has_is_a_p0_while_the_page_shows_it_active(tmp_path):
    rep = run(tmp_path, "holdings.stop_state", b=bundle(stops=[S_AB]),
              doc=_stop_doc(), http_open=True)  # no ZQAA row at all in the canonical snapshot
    assert codes(rep) == ["NT_STOP_STATE_MISMATCH"]
    f = rep["findings"][0]
    assert f["fingerprint"] == "/portfolio|holdings.stop_state|zz_taxable|ZQAA"
    assert "no WORKING stop" in f["detail"]


def test_history_rows_of_the_same_name_are_not_the_served_stop(tmp_path):
    """Live shape (2026-11-09): ANET and rollover V each had a working row AND cancelled/replaced siblings
    in the SAME newest snapshot. Comparing the page against a sibling is how five correct stops were
    reported wrong; the live row must win."""
    stops = [dict(S_AA, lifecycle="working", stop_price=80.0, qty=100, order_id="9"),
             dict(S_AA, lifecycle="cancelled", stop_price=60.0, qty=100, order_id="8"),
             dict(S_AA, lifecycle="replaced", stop_price=75.0, qty=50, order_id="7"), S_AB]
    rep = run(tmp_path, "holdings.stop_price", "holdings.stop_qty",
              b=bundle(stops=stops), doc=_stop_doc(), http_open=True)
    assert rep["findings"] == []


def test_a_stop_the_page_hides_while_the_store_has_one_is_a_p0(tmp_path):
    """The XAR case: the brief said a held name had no working stop while stop_lifecycle held one."""
    stops = [dict(S_AA, lifecycle="working", stop_price=80.0, qty=100), S_AB]
    doc = {"stop_advice": [{"account": "zz_taxable", "symbol": "ZQAA", "stop_now": None, "stop_qty": 0.0}]}
    temp = tmp_path / "data/runtime/cio_overnight_brief"
    temp.mkdir(parents=True)
    (temp / "latest.json").write_text(json.dumps(doc))
    rep = run(tmp_path, "cio.stop_advice.stop_now", "cio.stop_advice.stop_qty", b=bundle(stops=stops))
    assert codes(rep) == ["NT_STOP_PRICE_MISMATCH", "NT_STOP_QTY_MISMATCH"]
    by_code = {f["code"]: f["detail"] for f in rep["findings"]}
    assert "the page shows no stop; truth 80" in by_code["NT_STOP_PRICE_MISMATCH"]
    assert "the page shows 0; truth 100" in by_code["NT_STOP_QTY_MISMATCH"]


def test_stop_price_and_quantity_are_exact(tmp_path):
    doc = _stop_doc()
    assert run(tmp_path, "holdings.stop_price", "holdings.stop_qty", doc=doc, http_open=True)["findings"] == []
    got = codes(run(tmp_path, "holdings.stop_price", "holdings.stop_qty",
                    doc=_stop_doc(price_aa=80.5, qty_aa=99), http_open=True))
    assert got == ["NT_STOP_PRICE_MISMATCH", "NT_STOP_QTY_MISMATCH"]


def test_stop_lifecycle_and_stop_last_known_disagreeing_is_itself_a_p1(tmp_path):
    root = write_state(tmp_path, holdings=[H(), H(account="zz_ira", symbol="ZQAB", shares=50)])
    clean = run(root, "holdings.stop_crosscheck")
    assert clean["findings"] == []
    # stop_last_known still shows a working stop the canonical snapshot calls cancelled
    rep = run(root, "holdings.stop_crosscheck",
              b=bundle(stops=[dict(S_AA, lifecycle="cancelled"), S_AB]))
    assert codes(rep) == ["NT_STOP_CROSS_CHECK"]
    assert rep["findings"][0]["severity"] == "P1"
    # ... or a price disagreement between the two copies
    rep = run(root, "holdings.stop_crosscheck", b=bundle(slk=[dict(K_AA, stop_price=79.0), K_AB]))
    assert codes(rep) == ["NT_STOP_CROSS_CHECK"]
    assert "vs stop_last_known" in rep["findings"][0]["detail"]


# ── the "unprotected" count (the XLV case) ──────────────────────────────────────────────────────────────────


def test_the_unprotected_count_is_held_minus_working_stops_and_names_the_gap(tmp_path):
    positions = [P_AA, P_AB, dict(P_AB, symbol="ZQAD")]
    root = write_state(tmp_path, brief_doc=brief(uncovered=2))
    rep = run(root, "cio.uncovered_count", b=bundle(positions=positions))
    assert codes(rep) == ["NT_UNPROTECTED"]
    f = rep["findings"][0]
    assert f["severity"] == "P0" and f["fingerprint"] == "/cio|cio.uncovered_count||"
    assert f["shown"]["value"] == 2 and f["truth"]["value"] == 1
    assert "zz_ira:ZQAD" in f["detail"]


def test_the_unprotected_count_is_clean_when_the_derived_coverage_agrees(tmp_path):
    positions = [P_AA, P_AB, dict(P_AB, symbol="ZQAD")]
    root = write_state(tmp_path, brief_doc=brief(uncovered=1))
    assert run(root, "cio.uncovered_count", b=bundle(positions=positions))["findings"] == []


def test_a_stale_stop_snapshot_makes_coverage_not_measured_never_unprotected(tmp_path):
    positions = [P_AA, P_AB, dict(P_AB, symbol="ZQAD")]
    root = write_state(tmp_path, brief_doc=brief(uncovered=1))
    stale = [dict(S_AA, snapshot_at=_iso(120)), dict(S_AB, snapshot_at=_iso(120))]
    rep = run(root, "cio.uncovered_count", b=bundle(positions=positions, stops=stale, stop_as_of=_iso(120)))
    assert codes(rep) == ["NT_NOT_MEASURED"]
    assert rep["findings"][0]["reason"] == "stale_truth"
    assert "unprotected" not in rep["findings"][0]["detail"]


# ── totals ───────────────────────────────────────────────────────────────────────────────────────────────────


def _overview(portfolio_value=16234.5, accounts=None, today_change=50.0, by_account=None, vix=15.0):
    return {"portfolio_value": portfolio_value,
            "portfolio_aggregate": {"accounts": accounts if accounts is not None else [
                {"account": "zz_taxable", "display_value": 11234.5},
                {"account": "zz_ira", "display_value": 5000.0}]},
            "today_change": today_change,
            "today_by_account": by_account if by_account is not None else {
                "zz_taxable": {"change": 30.0},
                "zz_ira": {"change": 20.0}},
            "trade_ai": {"vix": vix}}


def test_the_book_total_is_the_sum_of_positions_and_cash_within_one_dollar(tmp_path):
    b = bundle(positions=[P_AA, P_AB, P_CASH])
    assert run(tmp_path, "overview.portfolio_value", b=b, doc=_overview(), http_open=True)["findings"] == []
    rep = run(tmp_path, "overview.portfolio_value", b=b, doc=_overview(portfolio_value=16240.0), http_open=True)
    assert codes(rep) == ["NT_TOTAL_MISMATCH"]
    assert rep["findings"][0]["truth"]["value"] == pytest.approx(16234.5)
    assert "diff 5.5" in rep["findings"][0]["detail"]


def test_the_account_totals_flag_only_the_account_that_disagrees(tmp_path):
    b = bundle(positions=[P_AA, P_AB, P_CASH])
    accounts = [{"account": "zz_taxable", "display_value": 11234.5}, {"account": "zz_ira", "display_value": 4990.0}]
    rep = run(tmp_path, "overview.account_total", b=b, doc=_overview(accounts=accounts), http_open=True)
    assert codes(rep) == ["NT_ACCOUNT_TOTAL_MISMATCH"]
    assert rep["findings"][0]["account"] == "zz_ira"
    assert rep["findings"][0]["shown"]["value"] == 4990.0


def test_the_day_pnl_header_must_equal_its_account_rows(tmp_path):
    b = bundle(positions=[P_AA, P_AB, P_CASH])
    assert run(tmp_path, "overview.day_pnl", b=b, doc=_overview(), http_open=True)["findings"] == []
    rep = run(tmp_path, "overview.day_pnl", b=b, doc=_overview(today_change=60.0), http_open=True)
    assert codes(rep) == ["NT_DAY_PNL_SPLIT"]


def test_the_vix_tile_is_compared_to_a_fresh_allowed_quote(tmp_path):
    doc = _overview(vix=15.05)
    quotes = [dict(Q_AA), {"symbol": "$VIX", "source": "refresh:schwab", "price": 15.0,
                           "fetched_at": QUOTE_AS_OF}]
    assert run(tmp_path, "overview.vix", b=bundle(quotes=quotes), doc=doc, http_open=True)["findings"] == []
    rep = run(tmp_path, "overview.vix", b=bundle(quotes=quotes), doc=_overview(vix=15.5), http_open=True)
    assert codes(rep) == ["NT_VALUE_MISMATCH"]


def test_a_selection_surface_is_not_required_to_list_every_holding(tmp_path):
    """The brief's stop_advice lists the rows it chose to advise; a holding it omits is not a missing figure."""
    root = write_state(tmp_path, brief_doc=brief(stop_advice=[
        {"account": "zz_taxable", "symbol": "ZQAA", "stop_now": 80.0, "stop_qty": 100}]))
    rep = run(root, "cio.stop_advice.stop_now")
    assert rep["findings"] == []


# ── the "Friday" label ──────────────────────────────────────────────────────────────────────────────────────


def test_the_stop_card_names_the_briefs_own_session_day(tmp_path):
    root = write_state(tmp_path, brief_doc=brief(), since=since_close())
    assert run(root, "sinceclose.session_label")["findings"] == []


def test_a_card_naming_the_wrong_weekday_is_a_finding(tmp_path):
    root = write_state(tmp_path, brief_doc=brief(), since=since_close(close_tag="Fri close",
                                                                     label="Since Fri 4:00 PM"))
    rep = run(root, "sinceclose.session_label")
    assert codes(rep) == ["NT_SESSION_LABEL"]
    assert "Fri close" in rep["findings"][0]["detail"]
    assert rep["findings"][0]["truth"]["value"] == SESSION_DATE


def test_a_monday_session_date_is_not_read_as_sunday(tmp_path):
    """Regression: parsing a date-only session_date as UTC midnight and converting to ET yields the previous day."""
    root = write_state(tmp_path, brief_doc=brief(session_date="2026-11-09"),
                       since=since_close(close_tag="Mon close", label="Since Mon 4:00 PM",
                                         session_date="2026-11-09"))
    assert run(root, "sinceclose.session_label")["findings"] == []


def test_the_cards_own_session_date_must_match_the_briefs(tmp_path):
    root = write_state(tmp_path, brief_doc=brief(), since=since_close(session_date="2026-10-20"))
    rep = run(root, "sinceclose.session_label")
    assert codes(rep) == ["NT_SESSION_LABEL"]
    assert "session_date" in rep["findings"][0]["detail"]


# ── the §28.8 window ───────────────────────────────────────────────────────────────────────────────────────


def test_an_api_only_row_inside_the_window_is_not_measured_and_never_requested(tmp_path):
    calls: list[str] = []

    def fetcher(q):
        calls.append(q)
        return _overview()

    cat = catalog("overview.portfolio_value")
    rep = T.audit(cat, bundle(), now=NOW, state_root=tmp_path, http_open=False,
                  base_url="http://127.0.0.1:7777", fetcher=fetcher)
    assert calls == [] and codes(rep) == ["NT_NOT_MEASURED"]
    assert rep["findings"][0]["reason"] == "in_window_artifact_only"


def test_the_http_window_is_weekdays_0400_to_1615_et_only():
    et = T.ET
    assert T.http_window_open(datetime(2026, 10, 21, 10, 0, tzinfo=et)) is False   # Wed 10:00 ET
    assert T.http_window_open(datetime(2026, 10, 21, 3, 59, tzinfo=et)) is True
    assert T.http_window_open(datetime(2026, 10, 21, 16, 16, tzinfo=et)) is True
    assert T.http_window_open(datetime(2026, 10, 24, 10, 0, tzinfo=et)) is True    # Saturday


# ── authority: G3 served, G2 writes, G1 static ──────────────────────────────────────────────────────────────


def test_a_figure_marked_by_a_retired_provider_fails_even_when_the_number_matches(tmp_path):
    for source, clean in (("finviz_elite", True), ("alpaca", True), ("yfinance", False),
                          ("ticker_prices", False), ("mystery_feed", False)):
        root = write_state(tmp_path, brief_doc=brief(holdings=[
            {"symbol": "ZQAA", "price": 100.0, "quote_source": source}]))
        rep = run(root, "cio.holdings.quote_source")
        got = [f for f in rep["findings"] if f["code"] == "NT_QUOTE_SOURCE"]
        assert (got == []) is clean, source


class _Cursor:
    def __init__(self, rows):
        self._rows = rows
        self.description = [("provider",), ("n",), ("newest",)]

    def execute(self, sql, params=()):
        self._sql = sql

    def fetchall(self):
        return [tuple(r) for r in self._rows]


class _Conn:
    """A read-only stand-in: one row set per watched table, chosen by the table named in the SQL."""

    def __init__(self, by_table):
        self._by_table = by_table
        self.closed = False

    def cursor(self):
        c = _Cursor([])
        c.execute = lambda sql, params=(): setattr(c, "_t", next(
            (t for t in self._by_table if t in sql), ""))
        c.fetchall = lambda: [tuple(r) for r in self._by_table.get(getattr(c, "_t", ""), [])]
        return c

    def close(self):
        self.closed = True


def _policy_write_watch() -> dict:
    return {"write_watch": {"quote_price": {"table": "market_quotes", "time_col": "fetched_at",
                                            "provider_col": "source",
                                            "declared_sources": ["alpaca", "finviz", "refresh:schwab"],
                                            "never_sources": ["yfinance"],
                                            "producer_lane": "market-quotes"},
                            "positions_store": {"table": "positions_current", "time_col": "as_of",
                                                "provider_col": "source",
                                                "declared_sources": ["schwab", "schwab_api"],
                                                "never_sources": [],
                                                "producer_lane": "positions-sync"}}}


def test_g2_flags_a_row_written_by_a_retired_provider_and_ignores_a_declared_one():
    conn = _Conn({"market_quotes": [("yfinance", 625, "2026-10-21T17:50:00+00:00")],
                  "positions_current": [("schwab", 12, "2026-10-21T17:52:00+00:00")]})
    out = T.authority_writes(_policy_write_watch(), conn_factory=lambda: conn, now=NOW)
    assert [f["code"] for f in out] == ["NT_AUTHORITY_WRITE"]
    assert out[0]["shown"]["rows"] == 625 and "retired" in out[0]["detail"]
    assert out[0]["fingerprint"] == "*|authority.writes.quote_price||"
    assert conn.closed
    conn = _Conn({"market_quotes": [("finviz", 40, "2026-10-21T17:58:00+00:00")],
                  "positions_current": [("schwab", 12, "2026-10-21T17:52:00+00:00")]})
    assert T.authority_writes(_policy_write_watch(), conn_factory=lambda: conn, now=NOW) == []


def test_g2_reports_an_unreadable_table_as_not_measured():
    class Bad(_Conn):
        def cursor(self):
            c = super().cursor()

            def boom(sql, params=()):
                raise RuntimeError("relation does not exist")

            c.execute = boom
            return c

    out = T.authority_writes(_policy_write_watch(), conn_factory=lambda: Bad({}), now=NOW)
    assert {f["status"] for f in out} == {"NOT_MEASURED"}
    assert {f["reason"] for f in out} == {"truth_unreadable"}


class _Proc:
    def __init__(self, stdout):
        self.stdout = stdout


def test_g1_maps_each_authority_gate_finding_to_one_entry():
    doc = {"findings": [{"check": "UNAPPROVED_READER",
                         "files": ["scripts/numbers_truth_audit.py"],
                         "action": "declare the reader"},
                        {"check": "RETIRED_CALL_SITE", "files": ["scripts/x.py"]}]}
    out = T.authority_static(runner=lambda cmd, cwd: _Proc(json.dumps(doc)))
    assert [f["code"] for f in out] == ["NT_AUTHORITY_STATIC", "NT_AUTHORITY_STATIC"]
    assert out[0]["fingerprint"] == "*|authority.static||"
    assert out[0]["shown"]["file"] == "scripts/numbers_truth_audit.py"
    assert "UNAPPROVED_READER" in out[0]["detail"]


def test_g1_that_cannot_run_is_not_measured_not_clean():
    import subprocess

    def timeout(cmd, cwd):
        raise subprocess.TimeoutExpired(cmd, 90)

    out = T.authority_static(runner=timeout)
    assert codes({"findings": out}) == ["NT_NOT_MEASURED"]
    assert out[0]["reason"] == "authority_gate_unavailable"
    out = T.authority_static(runner=lambda cmd, cwd: _Proc("not json"))
    assert codes({"findings": out}) == ["NT_NOT_MEASURED"]


def test_the_audit_runs_the_authority_family_when_the_policy_declares_it(tmp_path):
    policy = dict(_policy_write_watch())
    policy["authority"] = {"gate": "scripts/check_data_source_authority.py"}
    cat = {"schema": "NumbersTruthCatalog@v1", "policy": policy, "codes": T.load_catalog()["codes"], "rows": []}
    conn = _Conn({"market_quotes": [("yfinance", 3, "2026-10-21T17:50:00+00:00")],
                  "positions_current": []})
    rep = T.audit(cat, bundle(), now=NOW, state_root=tmp_path, http_open=False, base_url="x",
                  authority_runners={"conn_factory": lambda: conn,
                                     "runner": lambda cmd, cwd: _Proc(json.dumps({"findings": []}))})
    assert codes(rep) == ["NT_AUTHORITY_WRITE"]
    assert rep["authority_checks"]["write_watch_domains"] == ["positions_store", "quote_price"]


# ── receipt, bounds, deadline, posture ─────────────────────────────────────────────────────────────────────


def test_findings_are_capped_and_the_overflow_is_counted(tmp_path):
    n = T.MAX_FINDINGS + 5
    positions = [dict(P_AA, symbol=f"ZQ{i:03d}", qty=1) for i in range(n)]
    holdings = [H(symbol=f"ZQ{i:03d}", shares=2) for i in range(n)]
    root = write_state(tmp_path, holdings=holdings)
    rep = run(root, "holdings.qty", b=bundle(positions=positions))
    assert rep["finding_count"] == n
    assert len(rep["findings"]) == T.MAX_FINDINGS and rep["findings_truncated"] == 5


def test_the_receipt_summary_carries_the_list_m_the_next_lane_consumes(tmp_path):
    root = write_state(tmp_path, holdings=[H(shares=99), H(account="zz_ira", symbol="ZQAB", shares=50)])
    rep = run(root, "holdings.qty")
    summary = T.build_summary(rep)
    m = summary["findings"]
    assert len(m) == 1
    for key in ("fingerprint", "page", "figure_id", "account", "symbol", "severity", "status", "code",
                "detail", "shown", "truth", "domain", "producer_lane", "reason"):
        assert key in m[0]
    from scripts.lib import lane_last_receipt as R

    out = tmp_path / "receipts" / "numbers-truth-audit_last.json"
    out.parent.mkdir()
    written = R.write_lane_receipt(T.LANE, ok=True, exit_code=0, started_at=NOW,
                                   script="scripts/numbers_truth_audit.py", summary=summary, error=None,
                                   path=out, output={"produced_count": 1, "attempted_count": 1})
    assert written and Path(written).exists()
    doc = json.loads(Path(written).read_text())
    assert doc["summary"]["findings"][0]["fingerprint"] == "/portfolio|holdings.qty|zz_taxable|ZQAA"


def test_a_dry_run_writes_nothing(tmp_path, capsys):
    root = write_state(tmp_path, brief_doc=brief(), since=since_close())
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps(catalog("overview.portfolio_value", "sinceclose.session_label")))
    before = sorted(p for p in root.rglob("*"))
    rc = T.main(["--catalog", str(cat), "--state-root", str(root), "--no-db", "--no-http", "--json",
                 "--now", NOW.isoformat()])
    assert sorted(p for p in root.rglob("*")) == before
    assert json.loads(capsys.readouterr().out)["lane_id"] == T.LANE
    assert rc in (0, 1)  # the DB-backed rows are NOT_MEASURED, never a crash


def test_the_deadline_turns_the_remaining_rows_into_not_measured(tmp_path):
    root = write_state(tmp_path, holdings=[H()])
    rep = run(root, "holdings.qty", deadline=T._time.monotonic() - 1)
    assert codes(rep) == ["NT_NOT_MEASURED"]
    assert rep["findings"][0]["reason"] == "deadline_exceeded"


def test_the_audit_never_reaches_for_a_broker_a_credential_or_an_llm():
    src = (ROOT / "scripts/numbers_truth_audit.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    assert not (mods & {"yfinance", "alpaca", "data_broker", "schwab", "moomoo", "anthropic", "openai"}), mods
    for banned in ("place_order", "TRADEAI_CLAIM_OVERRIDE", "auth/login", "submit_order"):
        assert banned not in src
