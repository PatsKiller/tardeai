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


def test_header_shows_partial_sum_and_a_census_on_canonical_keys():
    p = truth.portfolio_for(_holdings(), now=NOW)
    # The legacy census as it shipped: raw keys, every account "flat".
    prior = {"empty_accounts": ["fidelity_rollover_ira"],
             "zero_change_accounts": ["alpaca_taxable_live", "moomoo_taxable_live", "schwab_rollover_ira",
                                      "schwab_roth", "schwab_taxable"], "contributing_accounts": []}
    out = truth.overview_payload({"today_pnl": prior}, document=_doc(p))
    assert out["today_change"] == 10.5 and out["today_pct"] is not None
    tp = out["today_pnl"]
    assert tp["contributing_accounts"] == ["schwab_rollover_ira", "schwab_roth_ira", "schwab_taxable"]
    assert tp["zero_change_accounts"] == ["alpaca_taxable_live", "moomoo_taxable_live"]
    assert "schwab_roth" not in tp["zero_change_accounts"]
    assert tp["missing_accounts"] == [] and tp["empty_accounts"] == ["fidelity_rollover_ira"]
    assert tp["partial_accounts"] == ["moomoo_taxable_live"] and tp["unknown_rows"] == 1
    assert tp["complete"] is False
    assert tp["funded_account_count"] == 5 and tp["represented_account_count"] == 5
    assert "PARTIAL moomoo_taxable_live" in tp["coverage_reason"]
    # The census keys match the per-account figures it describes.
    assert set(tp["contributing_accounts"] + tp["zero_change_accounts"]) == set(out["today_by_account"])


def test_an_account_with_no_known_row_is_missing_not_flat():
    h = _holdings()
    h["holdings"] = [r for r in h["holdings"] if r["account"] != "schwab_taxable"]
    h["holdings"].append({"symbol": "ZZEE", "account": "schwab_taxable", "shares": 1, "price": 9,
                          "market_value": 9})
    p = truth.portfolio_for(h, now=NOW)
    tp = truth.overview_payload({"today_pnl": {"empty_accounts": []}}, document=_doc(p))["today_pnl"]
    assert tp["missing_accounts"] == ["schwab_taxable"]
    assert "schwab_taxable" not in tp["zero_change_accounts"] and tp["complete"] is False


# New read-model checks load by file path, isolated from earlier import stubs.
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


def test_performance_1d_reads_stored_rows_instead_of_recomputing_a_different_measure():
    from scripts.portfolio_snapshot_sanity import portfolio_market_day
    from copy import deepcopy
    model = _day_truth()
    h = _day_doc()
    # This is the actual legacy read-model output, with its cache explicitly injected.
    legacy = portfolio_market_day({**h, "_finviz_day_pct": {}})
    assert legacy["change"] == 100.0  # stored zero is recomputed from the percent
    prior = {"periods": {"1D": {**legacy, "display_change": 100}, "YTD": {"display_change": 37}},
             "accounts": {"synthetic_alpha": {"periods": {"1D": {"change": 100}, "YTD": {"change": 12}}}}}
    frozen = deepcopy(prior)
    out = model.performance_payload(prior, holdings_doc=h, now=NOW)
    assert model.portfolio_for(h, now=NOW)["day_pl_usd"] == 0
    assert out["periods"]["1D"]["change"] == out["periods"]["1D"]["display_change"] == 0
    assert out["accounts"]["synthetic_alpha"]["periods"]["1D"]["change"] == 0
    header = model.overview_payload({}, document=_doc(model.portfolio_for(h, now=NOW)), now=NOW)
    assert header["today_change"] == out["periods"]["1D"]["change"]
    assert header["today_pnl"] == out["today_pnl"]
    assert out["periods"]["YTD"] == prior["periods"]["YTD"]
    assert out["accounts"]["synthetic_alpha"]["periods"]["YTD"] == {"change": 12}
    assert prior == frozen


def test_performance_unknown_partial_and_nonfinite_are_named_not_flat():
    model = _day_truth()
    h = _day_doc([
        {"account": "synthetic_alpha", "symbol": "ZZAA", "market_value": 100, "day_change": 7},
        {"account": "synthetic_alpha", "symbol": "ZZBB", "market_value": 20},
        {"account": "synthetic_beta", "symbol": "ZZCC", "market_value": 10, "day_change": float("nan")},
    ])
    out = model.performance_payload({"accounts": {}}, holdings_doc=h, now=NOW)
    day = out["periods"]["1D"]
    assert day["change"] == day["display_change"] == 7
    assert day["complete"] is False and day["unknown_rows"] == 2
    assert out["accounts"]["synthetic_beta"]["periods"]["1D"]["change"] is None
    assert out["today_pnl"]["missing_accounts"] == ["synthetic_beta"]
    assert out["today_pnl"]["partial_accounts"] == ["synthetic_alpha"]
    assert "PARTIAL" in day["adjustment_note"]


def test_current_summary_missing_rows_and_history_only_account_survive_with_unknown_day():
    model = _day_truth()
    h = _day_doc()
    h["account_summaries"] = {"synthetic_beta": {"total_value": 500, "holdings_count": 1},
                              "synthetic_empty": {"total_value": 0, "holdings_count": 0}}
    prior = {"accounts": {"synthetic_history": {"current_value": 17, "periods": {"1D": {"change": 99}}}}}
    out = model.performance_payload(prior, holdings_doc=h, now=NOW)
    assert set(out["accounts"]) == {"synthetic_alpha", "synthetic_beta", "synthetic_empty", "synthetic_history"}
    assert out["accounts"]["synthetic_beta"]["periods"]["1D"]["change"] is None
    assert out["accounts"]["synthetic_history"]["periods"]["1D"]["display_change"] is None
    assert out["today_pnl"]["missing_accounts"] == ["synthetic_beta"]
    assert out["today_pnl"]["empty_accounts"] == ["synthetic_empty"]
    assert out["periods"]["1D"]["complete"] is False


def test_absent_holdings_refuses_snapshot_day_and_empty_book_does_not_invent_zero():
    model = _day_truth()
    out = model.performance_payload({"periods": {"1D": {"change": 99, "display_change": 99}}},
                                    holdings_doc={}, now=NOW)
    assert out["periods"]["1D"]["change"] is None
    assert out["periods"]["1D"]["display_change"] is None
    assert out["periods"]["1D"]["complete"] is False
    assert out["today_pnl"]["calculated_at"] is None


def test_same_source_with_different_snapshot_clock_does_not_claim_identical_observations():
    model = _day_truth()
    h = _day_doc()
    early = model.performance_payload({}, holdings_doc=h, now=NOW)
    h["generated_at"] = "2026-10-26T14:46:00Z"
    h["last_repriced"] = "2026-10-26T14:46:00Z"
    h["holdings"][0]["day_change"] = 3
    late = model.performance_payload({}, holdings_doc=h, now=NOW)
    assert early["periods"]["1D"]["change"] == 0 and late["periods"]["1D"]["change"] == 3
    assert early["today_pnl"]["calculated_at"] != late["today_pnl"]["calculated_at"]


def test_actual_performance_handler_emits_shared_1d_after_legacy_adjustments(monkeypatch, tmp_path):
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
    assert out["periods"]["1D"]["change"] == out["periods"]["1D"]["display_change"] == 0
    assert out["periods"]["YTD"]["display_change"] == 42
    assert loaded.count("holdings.json") == 1


def test_day_session_uses_explicit_eastern_date_and_never_position_clock():
    model = _day_truth()
    h = _day_doc()
    h["last_repriced"] = "2026-10-27T00:15:00Z"
    h["positions_built_at"] = "2026-10-01T12:00:00Z"
    out = model.performance_payload({}, holdings_doc=h, now=NOW)
    assert out["today_pnl"]["session_date"] == "2026-10-26"
    assert out["today_pnl"]["observation_clock"]["status"] == "UNKNOWN"
    h["last_repriced"] = "2026-10-27"
    h["generated_at"] = "2026-10-27 10:30:00"
    out = model.performance_payload({}, holdings_doc=h, now=NOW)
    assert out["today_pnl"]["session_date"] is None
    assert out["today_pnl"]["calculated_at"] is None
