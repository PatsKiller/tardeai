"""Header TODAY after a morning holdings reload (2026-10-26).

Live: TODAY rendered "—" during market hours. A broker reload re-added
delisted $0 CUSIP rows and a fractional row without a day_change, and
cio_truth summed day changes all-or-nothing, so one unknown row nulled the
total and every account but one. The census beside it said "5/5 represented,
all zero change" because it compared raw holdings keys to canonical keys and
treated None as flat. Fixtures are invented symbols and amounts.
"""
from datetime import datetime, timezone

from scripts.lib import cio_truth as truth

NOW = datetime(2026, 10, 26, 14, 45, tzinfo=timezone.utc)


def _holdings():
    return {"last_repriced": "2026-10-26 10:45:02 ET", "generated_at": "2026-10-26 10:45:02 ET",
            "reprice_source": "finviz_live", "holdings": [
                {"symbol": "ZZAA", "account": "schwab_taxable", "shares": 10, "price": 50,
                 "market_value": 500, "day_change": 12.5},
                {"symbol": "ZZBB", "account": "schwab_roth", "shares": 4, "price": 25,
                 "market_value": 100, "day_change": -3.0},
                # delisted CUSIP carried at $0, re-added by the reload without a day change
                {"symbol": "000000ZZ9", "account": "schwab_rollover_ira", "shares": 300, "price": 0.0,
                 "market_value": 0.0, "delisted": True},
                {"symbol": "ZZCC", "account": "schwab_rollover_ira", "shares": 2, "price": 40,
                 "market_value": 80, "day_change": 1.0},
                # fractional row with a mark but no prior close: genuinely unknown
                {"symbol": "ZZDD", "account": "moomoo_taxable_live", "shares": 0.25, "price": 80,
                 "market_value": 20.0},
                {"symbol": "CASH", "account": "moomoo_taxable_live", "shares": 5, "market_value": 5,
                 "is_cash": True},
                {"symbol": "CASH", "account": "alpaca_taxable_live", "shares": 0, "market_value": 0,
                 "is_cash": True},
            ]}


def test_one_unknown_row_no_longer_blanks_the_book():
    p = truth.portfolio_for(_holdings(), now=NOW)
    assert p["day_pl_usd"] == 10.5  # 12.5 - 3.0 + 0 (delisted) + 1.0; ZZDD left out, not guessed
    assert p["day_pl_complete"] is False
    assert p["day_pl_coverage"]["unknown_rows"] == 1
    assert p["day_pl_coverage"]["unknown_value_usd"] == 20.0
    assert p["day_pl_coverage"]["unknown_accounts"] == ["moomoo_taxable_live"]
    assert "partial" in p["gap"]["reason"]
    by = {a["account_id"]: a for a in p["accounts"]}
    assert by["schwab_rollover_ira"]["day_pl_usd"] == 1.0 and by["schwab_rollover_ira"]["day_pl_complete"]
    assert by["schwab_roth_ira"]["day_pl_usd"] == -3.0
    assert by["moomoo_taxable_live"]["day_pl_usd"] == 0.0
    assert by["moomoo_taxable_live"]["day_pl_complete"] is False


def test_delisted_zero_value_row_is_a_known_zero_but_a_live_priced_row_is_not():
    h = _holdings()
    p = truth.portfolio_for(h, now=NOW)
    row = next(r for r in p["holdings"] if r["symbol"] == "000000ZZ9")
    assert row["day_change"] == 0.0 and row["day_change_basis"] == "delisted_zero_value"
    assert "day_change" not in h["holdings"][2]  # input never mutated
    # A delisted flag on a row that still carries value is NOT assumed flat.
    h["holdings"][2].update(price=1.0, market_value=300.0)
    p = truth.portfolio_for(h, now=NOW)
    assert p["day_pl_coverage"]["unknown_rows"] == 2


def test_complete_book_reports_complete():
    h = _holdings()
    h["holdings"][4]["day_change"] = 0.5
    p = truth.portfolio_for(h, now=NOW)
    assert p["day_pl_usd"] == 11.0 and p["day_pl_complete"] is True and p["gap"] is None


def _doc(p):
    return {"portfolio": p, "approvals": {"total": 0}, "paper": {},
            "regime": {"label": None, "vix": None, "vix_as_of": None}}


def test_header_refuses_economic_day_but_preserves_row_sum_and_census():
    p = truth.portfolio_for(_holdings(), now=NOW)
    prior = {"empty_accounts": ["synthetic_legacy_empty"], "total_change": 99}
    out = truth.overview_payload({"today_change": 99, "today_pct": 2, "today_pnl": prior}, document=_doc(p), now=NOW)
    assert out["today_change"] is None and out["today_pct"] is None
    tp = out["today_pnl"]
    assert tp["status"] == "UNKNOWN" and tp["complete"] is False
    assert tp["funded_account_count"] is None and tp["represented_account_count"] is None
    assert tp["gap"]["ticket"] == "OI-044"
    assert tp["legacy_evidence"]["today_change"] == 99
    assert tp["legacy_evidence"]["today_pnl"] == prior
    evidence = tp["stored_row_evidence"]
    assert evidence["known_sum"] == 10.5
    assert evidence["row_values_complete"] is False
    census = evidence["census"]
    assert census["unknown_rows"] == 1
    assert census["partial_accounts"]
    assert all(row["change"] is None and row["complete"] is False for row in out["today_by_account"].values())


def test_missing_row_value_is_visible_without_claiming_economic_coverage():
    h = _holdings()
    h["holdings"][0].pop("day_change")
    p = truth.portfolio_for(h, now=NOW)
    tp = truth.overview_payload({}, document=_doc(p), now=NOW)["today_pnl"]
    assert tp["status"] == "UNKNOWN" and tp["complete"] is False
    assert tp["stored_row_evidence"]["census"]["unknown_rows"] == 2
    assert tp["missing_accounts"] is None and tp["zero_change_accounts"] is None


def _day_truth():
    import importlib.util
    from pathlib import Path
    import sys
    name = "scripts.lib._cio_truth_day_contract"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts/lib/cio_truth.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _day_doc(rows=None):
    return {"generated_at": "2026-10-26T14:45:00Z", "last_repriced": "2026-10-26T14:44:00Z",
            "reprice_source": "synthetic", "account_summaries": {},
            "holdings": rows if rows is not None else [
                {"account": "synthetic_alpha", "symbol": "ZZAA", "shares": 10,
                 "price": 110, "market_value": 1100, "day_change": 0, "day_change_pct": 10}]}


def test_performance_preserves_original_financial_semantics_instead_of_forcing_row_agreement():
    from scripts.portfolio_snapshot_sanity import portfolio_market_day
    from copy import deepcopy
    model = _day_truth()
    h = _day_doc()
    legacy = portfolio_market_day({**h, "_finviz_day_pct": {}})
    assert legacy["change"] == 100.0
    prior = {"current_value": 1100, "snapshot_source": "synthetic legacy",
             "periods": {"1D": {**legacy, "display_change": 100}, "YTD": {"display_change": 37}},
             "accounts": {"synthetic_alpha": {"current_value": 1100,
                          "periods": {"1D": {"change": 100}, "YTD": {"change": 12}}}}}
    frozen = deepcopy(prior)
    out = model.performance_payload(prior, holdings_doc=h, now=NOW)
    assert {key:out[key] for key in prior} == prior == frozen
    assert out["today_pnl"]["total_change"] is None and out["today_pnl"]["complete"] is False
    assert out["today_pnl"]["stored_row_evidence"]["known_sum"] == 0
    assert out["today_pnl"]["legacy_evidence"]["period_1d"] == prior["periods"]["1D"]
    header = model.overview_payload({}, document=_doc(model.portfolio_for(h, now=NOW)), now=NOW)
    assert header["today_change"] is None  # not forced to either unproven monetary source
    assert header["today_pnl"]["market_session"] == out["today_pnl"]["market_session"]


def test_raw_partial_nonfinite_evidence_is_named_without_new_performance_money():
    model = _day_truth()
    h = _day_doc([
        {"account": "synthetic_alpha", "symbol": "ZZAA", "market_value": 100, "day_change": 7},
        {"account": "synthetic_alpha", "symbol": "ZZBB", "market_value": 20},
        {"account": "synthetic_beta", "symbol": "ZZCC", "market_value": 10, "day_change": float("nan")},
    ])
    prior = {"accounts": {}, "periods": {"1D": {"change": 9, "display_change": 9}}}
    out = model.performance_payload(prior, holdings_doc=h, now=NOW)
    assert out["accounts"] == prior["accounts"] and out["periods"] == prior["periods"]
    assert out["today_pnl"]["status"] == "UNKNOWN"
    evidence = out["today_pnl"]["stored_row_evidence"]
    assert evidence["known_sum"] == 7 and evidence["row_values_complete"] is False
    assert evidence["census"]["unknown_rows"] == 2
    assert evidence["census"]["missing_accounts"] == ["synthetic_beta"]


def test_current_summary_gaps_do_not_add_or_remove_legacy_account_money():
    model = _day_truth()
    h = _day_doc()
    h["account_summaries"] = {"synthetic_beta": {"total_value": 500, "holdings_count": 1},
                              "synthetic_empty": {"total_value": 0, "holdings_count": 0}}
    prior = {"accounts": {"synthetic_history": {"current_value": 17, "periods": {"1D": {"change": 99}}}}}
    out = model.performance_payload(prior, holdings_doc=h, now=NOW)
    assert out["accounts"] == prior["accounts"]
    census = out["today_pnl"]["stored_row_evidence"]["census"]
    assert census["missing_accounts"] == ["synthetic_beta"]
    assert census["empty_accounts"] == ["synthetic_empty"]
    assert out["today_pnl"]["complete"] is False


def test_absent_holdings_preserves_original_evidence_and_refuses_economic_claim():
    model = _day_truth()
    prior = {"current_value": 17, "periods": {"1D": {"change": 99, "display_change": 99}}}
    out = model.performance_payload(prior, holdings_doc={}, now=NOW)
    assert out["periods"] == prior["periods"] and out["current_value"] == 17
    assert out["today_pnl"]["total_change"] is None and out["today_pnl"]["complete"] is False
    assert out["today_pnl"]["stored_row_evidence"]["known_sum"] is None
    assert out["today_pnl"]["calculated_at"] is None


def test_snapshot_clocks_and_row_values_do_not_rewrite_original_performance_day():
    model = _day_truth()
    h = _day_doc()
    prior = {"periods": {"1D": {"change": 8, "display_change": 8}}}
    early = model.performance_payload(prior, holdings_doc=h, now=NOW)
    h["generated_at"] = "2026-10-26T14:46:00Z"
    h["last_repriced"] = "2026-10-26T14:46:00Z"
    h["holdings"][0]["day_change"] = 3
    late = model.performance_payload(prior, holdings_doc=h, now=NOW)
    assert early["periods"] == late["periods"] == prior["periods"]
    assert early["today_pnl"]["stored_row_evidence"]["known_sum"] == 0
    assert late["today_pnl"]["stored_row_evidence"]["known_sum"] == 3
    assert early["today_pnl"]["batch_built_at"] != late["today_pnl"]["batch_built_at"]
    assert early["today_pnl"]["total_change"] is None and late["today_pnl"]["total_change"] is None


def test_actual_performance_handler_preserves_legacy_1d_and_adjustments(monkeypatch, tmp_path):
    from copy import deepcopy
    from pathlib import Path
    import sys
    from types import ModuleType
    model = _day_truth()
    h = _day_doc()
    legacy_perf = {"periods": {"1D": {"change": 100}, "YTD": {"change": 37}},
                   "accounts": {"synthetic_alpha": {"current_value": 1100,
                                "periods": {"1D": {"change": 100}, "YTD": {"change": 37}}}}}
    # Run the real handler body without importing the server or its protected adapters.
    source = (Path(__file__).resolve().parents[1] / "scripts/api_v2.py").read_text()
    body = source[source.index("def portfolio_performance():"):source.index("def research_ticker(")]
    sanity = ModuleType("portfolio_snapshot_sanity")
    sanity.apply_market_day_1d = lambda perf, holdings: perf
    sanity.load_snapshots_from_dir = lambda path: []
    sanity.holding_phantom_corrections = lambda rows: {}
    sanity.compute_drawdown_series = lambda rows: []
    quality = ModuleType("portfolio_period_quality")
    def annotate(result, state, holdings):
        result["periods"]["1D"]["display_change"] = 222
        result["periods"]["YTD"]["display_change"] = 42
        return result
    quality.annotate_performance_result = annotate
    benchmarks = ModuleType("lib.portfolio_benchmarks")
    benchmarks.build_benchmarks = lambda periods: {}
    for name, module in [(sanity.__name__, sanity), (quality.__name__, quality), (benchmarks.__name__, benchmarks)]:
        monkeypatch.setitem(sys.modules, name, module)
    loaded = []
    def load(path):
        loaded.append(path.name)
        return deepcopy({"holdings.json": h, "performance_history.json": legacy_perf}.get(path.name, []))
    ns = {"STATE_DIR": tmp_path, "_load_json": load, "_live_portfolio_day_change": lambda rows: 100,
          "_compute_drawdown_series": lambda rows: [], "_cio_truth_readers": lambda: model}
    exec(compile(body, "api_v2.py::portfolio_performance", "exec"), ns)
    out = ns["portfolio_performance"]()
    assert out["periods"]["1D"]["change"] == 100
    assert out["periods"]["1D"]["display_change"] == 222
    assert out["today_pnl"]["total_change"] is None and out["today_pnl"]["status"] == "UNKNOWN"
    assert out["periods"]["YTD"]["display_change"] == 42
    assert loaded.count("holdings.json") == 1


def test_day_session_uses_explicit_eastern_date_and_never_position_clock():
    model = _day_truth()
    h = _day_doc()
    h["last_repriced"] = "2026-10-27T00:15:00Z"
    h["positions_built_at"] = "2026-10-01T12:00:00Z"
    out = model.performance_payload({}, holdings_doc=h, now=NOW)
    assert out["today_pnl"]["session_date"] is None
    assert out["today_pnl"]["mark_session_date"] == "2026-10-26"
    assert out["today_pnl"]["observation_clock"]["status"] == "UNKNOWN"
    h["last_repriced"] = "2026-10-27"
    h["generated_at"] = "2026-10-27 10:30:00"
    out = model.performance_payload({}, holdings_doc=h, now=NOW)
    assert out["today_pnl"]["session_date"] is None
    assert out["today_pnl"]["calculated_at"] is None



def test_alias_and_history_financial_keys_are_preserved_without_claiming_completeness(monkeypatch):
    model = _day_truth()
    monkeypatch.setattr(model, "canonical_key", lambda key: "synthetic_current" if key == "synthetic_legacy" else key)
    h = _day_doc([{"account": "synthetic_current", "symbol": "ZZAA", "market_value": 100, "day_change": 7}])
    prior = {"accounts": {
        "synthetic_legacy": {"current_value": 80, "periods": {"YTD": {"change": 12}}},
        "synthetic_current": {"current_value": 100, "periods": {"YTD": {"change": 20}}}}}
    out = model.performance_payload(prior, holdings_doc=h, now=NOW)
    assert out["accounts"] == prior["accounts"]
    assert "periods" not in out  # no invented 1D financial cell
    assert out["today_pnl"]["complete"] is False
    assert out["today_pnl"]["stored_row_evidence"]["known_sum"] == 7


def test_missing_excluded_value_is_unknown_and_batch_clocks_do_not_date_pnl():
    model = _day_truth()
    h = _day_doc([{"account": "synthetic_alpha", "symbol": "ZZAA", "market_value": 100, "day_change": 7},
                  {"account": "synthetic_alpha", "symbol": "ZZBB", "market_value": None}])
    p = model.portfolio_for(h, now=NOW)
    assert p["day_pl_coverage"]["unknown_value_usd"] is None
    out = model.performance_payload({}, holdings_doc=h, now=NOW)
    tp = out["today_pnl"]
    assert tp["calculated_at"] is None and tp["session_date"] is None
    assert tp["batch_built_at"] == "2026-10-26T14:45:00+00:00"
    assert tp["mark_batch_at"] == "2026-10-26T14:44:00+00:00"
    assert tp["mark_session_date"] == "2026-10-26"
    assert "periods" not in out
    assert out["today_pnl"]["stored_row_evidence"]["known_sum"] == 7



def test_summary_alias_conflict_never_discards_funded_missing_evidence(monkeypatch):
    model = _day_truth()
    monkeypatch.setattr(model, "canonical_key", lambda key: "synthetic_current" if key == "synthetic_legacy" else key)
    for reverse in (False, True):
        pairs = [("synthetic_legacy", {"total_value": 500, "holdings_count": 1}),
                 ("synthetic_current", {"total_value": 0, "holdings_count": 0})]
        if reverse:
            pairs.reverse()
        h = _day_doc()
        h["account_summaries"] = dict(pairs)
        p = model.portfolio_for(h, now=NOW)
        out = model.performance_payload({}, holdings_doc=h, now=NOW)
        row = next(r for r in p["accounts"] if r["account_id"] == "synthetic_current")
        assert row["empty"] is False and row["reported_total_usd"] is None
        assert row["day_pl_usd"] is None and row["summary_alias_conflict"] is True
        assert len(row["summary_alias_evidence"]) == 2
        assert out["today_pnl"]["complete"] is False
        census = out["today_pnl"]["stored_row_evidence"]["census"]
        assert census["missing_accounts"] == ["synthetic_current"]
        assert census["empty_accounts"] == []



def test_holiday_reference_follows_existing_calendar_and_open_boundary():
    from datetime import datetime
    model = _day_truth()
    cases = [
        ("2026-11-26T20:00:00Z", "2026-11-25", "holiday"),
        ("2026-11-27T14:29:59Z", "2026-11-25", "premarket"),
        ("2026-11-27T14:30:00Z", "2026-11-27", "regular"),
        ("2026-11-27T18:00:00Z", "2026-11-27", "afterhours"),
        ("2026-11-28T17:00:00Z", "2026-11-27", "weekend"),
        ("2026-11-30T14:29:59Z", "2026-11-27", "premarket"),
        ("2026-11-30T14:30:00Z", "2026-11-30", "regular"),
        ("2026-11-27T00:30:00Z", "2026-11-25", "holiday"),
        ("2026-11-02T14:29:59Z", "2026-10-30", "premarket"),
        ("2026-11-02T14:30:00Z", "2026-11-02", "regular"),
        ("2026-03-09T13:30:00Z", "2026-03-09", "regular"),
        ("2026-07-03T16:00:00Z", "2026-07-02", "holiday"),
        ("2026-06-19T16:00:00Z", "2026-06-18", "holiday"),
        ("2027-01-01T17:00:00Z", "2026-12-31", "holiday"),
    ]
    for raw, expected, phase in cases:
        now = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        out = model.market_session_reference(now)
        assert out["status"] == "KNOWN", (raw, out)
        assert out["latest_open_session"] == expected
        assert out["phase"] == phase
        assert out["as_of"] == raw
        assert out["latest_open_at"].endswith("Z")
        assert out["gap"] is None


def test_holiday_reference_refuses_unknown_calendar_or_unzoned_evaluation():
    from types import SimpleNamespace
    from datetime import datetime, time
    model = _day_truth()
    for raw in (None, "2026-11-26", datetime(2026, 11, 26, 15)):
        out = model.market_session_reference(raw)
        assert out["status"] == "UNKNOWN" and out["latest_open_session"] is None
        assert out["latest_open_at"] is None and out["gap"]["reason"]
    bad_phase = SimpleNamespace(MARKET_OPEN=time(9, 30), current_market_session=lambda now: "UNKNOWN",
                                is_trading_day=lambda now: True)
    out = model.market_session_reference(NOW, calendar=bad_phase)
    assert out["status"] == "UNKNOWN" and out["latest_open_session"] is None
    def unavailable(now):
        raise RuntimeError("synthetic calendar unavailable")
    broken = SimpleNamespace(MARKET_OPEN=time(9, 30), current_market_session=unavailable)
    out = model.market_session_reference(NOW, calendar=broken)
    assert out["status"] == "UNKNOWN" and "RuntimeError" in out["gap"]["reason"]
    never_open = SimpleNamespace(MARKET_OPEN=time(9, 30), current_market_session=lambda now: "holiday",
                                 is_trading_day=lambda now: False)
    out = model.market_session_reference(NOW, calendar=never_open)
    assert out["status"] == "UNKNOWN" and out["latest_open_session"] is None


def test_overview_today_and_performance_share_calendar_reference_without_dating_pnl():
    from datetime import datetime
    model = _day_truth()
    now = datetime(2026, 11, 26, 20, tzinfo=timezone.utc)
    h = _day_doc()
    p = model.portfolio_for(h, now=now)
    overview = model.overview_payload({}, document=_doc(p), now=now)
    prior = {"periods": {"1D": {"change": 7}}, "current_value": 999}
    perf = model.performance_payload(prior, holdings_doc=h, now=now)
    expected = overview["market_session"]
    assert expected["latest_open_session"] == "2026-11-25"
    assert overview["today_pnl"]["market_session"] == perf["market_session"] == perf["today_pnl"]["market_session"] == expected
    assert overview["today_change"] is None
    assert perf["periods"] == prior["periods"] and perf["current_value"] == 999
    assert overview["position_count"] == p["position_count"]
    assert overview["today_pnl"]["session_date"] is None
    assert overview["today_pnl"]["calculated_at"] is None
    assert set(expected).isdisjoint({"change", "display_change", "total_usd", "position_count", "complete"})



def test_calendar_failure_reaches_real_payload_as_unknown_without_financial_changes(monkeypatch):
    from scripts import market_session
    model = _day_truth()
    h = _day_doc()
    p = model.portfolio_for(h, now=NOW)
    def unavailable(now):
        raise RuntimeError("synthetic unavailable")
    monkeypatch.setattr(market_session, "current_market_session", unavailable)
    overview = model.overview_payload({}, document=_doc(p), now=NOW)
    prior = {"current_value": 999, "periods": {"1D": {"change": 7}}}
    perf = model.performance_payload(prior, holdings_doc=h, now=NOW)
    for out in (overview, perf):
        assert out["market_session"]["status"] == "UNKNOWN"
        assert out["market_session"]["latest_open_session"] is None
        assert "RuntimeError" in out["market_session"]["gap"]["reason"]
        assert out["today_pnl"]["market_session"] == out["market_session"]
        assert out["today_pnl"]["total_change"] is None and out["today_pnl"]["complete"] is False
        assert out["today_pnl"]["stored_row_evidence"]["known_sum"] == p["day_pl_usd"]
        assert out["today_pnl"]["session_date"] is None
    assert overview["portfolio_value"] == p["total_usd"]
    assert perf["current_value"] == 999 and perf["periods"] == prior["periods"]



def test_full_exit_and_loan_exclusion_performance_evidence_is_preserved():
    from scripts.portfolio_snapshot_sanity import portfolio_market_day, account_market_days
    from copy import deepcopy
    model = _day_truth()
    cash = {"holdings": [{"account": "synthetic_alpha", "symbol": "CASH", "is_cash": True, "market_value": 150}],
            "portfolio_totals": {"total_value": 150, "day_change": 7},
            "account_summaries": {"synthetic_alpha": {"total_value": 150, "holdings_count": 1, "day_change": 7}},
            "closed_today": {"synthetic_alpha": [{"symbol": "ZZAA", "day_change": 7}]}, "_finviz_day_pct": {}}
    loan = {"holdings": [{"account": "synthetic_alpha", "symbol": "ZZAA", "market_value": 100, "day_change": 7},
                         {"account": "synthetic_alpha", "symbol": "LOAN", "is_loan": True, "market_value": -200, "day_change": -10},
                         {"account": "synthetic_alpha", "symbol": "CASH", "is_cash": True, "market_value": 20}],
            "portfolio_totals": {"total_value": 120, "day_change": 7}, "_finviz_day_pct": {}}
    for h, expected_value in ((cash, 150), (loan, 120)):
        legacy = portfolio_market_day(h)
        account = account_market_days(h)["synthetic_alpha"]
        assert legacy["change"] == account["change"] == 7
        prior = {"current_value": expected_value, "snapshot_source": "original source",
                 "periods": {"1D": {**legacy, "display_change": 7}, "YTD": {"change": 23}},
                 "accounts": {"synthetic_alpha": {"current_value": expected_value,
                              "periods": {"1D": account, "YTD": {"change": 19}}},
                              "synthetic_history": {"current_value": 0, "periods": {"YTD": {"change": 5}}}},
                 "period_quality_note": "Original legacy note retained as evidence"}
        frozen = deepcopy(prior)
        out = model.performance_payload(prior, holdings_doc=h, now=NOW)
        assert {key:out[key] for key in prior} == frozen == prior
        assert out["today_pnl"]["status"] == "UNKNOWN" and out["today_pnl"]["complete"] is False
        assert out["today_pnl"]["legacy_evidence"]["period_1d"]["change"] == 7
        overview = model.overview_payload({"today_change": 7, "today_pct": 1},
                                          document=_doc(model.portfolio_for(h, now=NOW)), now=NOW)
        assert overview["today_change"] is None
        assert overview["today_pnl"]["legacy_evidence"]["today_change"] == 7
        assert overview["today_pnl"]["gap"]["ticket"] == "OI-044"


def test_zero_percentage_and_basis_do_not_select_an_economic_day_measure():
    model = _day_truth()
    for basis in (None, "intraday_fills"):
        h = _day_doc()
        h["holdings"][0]["day_change_basis"] = basis
        prior = {"current_value": 1100, "periods": {"1D": {"change": 100, "display_change": 100}}}
        out = model.performance_payload(prior, holdings_doc=h, now=NOW)
        assert out["periods"] == prior["periods"]
        tp = out["today_pnl"]
        assert tp["total_change"] is None and tp["complete"] is False and tp["status"] == "UNKNOWN"
        evidence = tp["stored_row_evidence"]
        assert evidence["known_sum"] == 0 and evidence["row_values_complete"] is True
        assert evidence["source_values"][0]["day_change"] == 0
        assert evidence["source_values"][0]["day_change_pct"] == 10
        assert evidence["source_values"][0]["day_change_basis"] == basis
        assert tp["gap"]["owner"] == "portfolio/holdings_accounts"
