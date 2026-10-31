"""Index-issuer caps for the engine's event category. Hermetic: fake ingest, fake reader rows."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import scripts.index_constituent_caps as icc
from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk import event_calendar, registry
from scripts.lib.market_risk.policy import load_policy

ET = ZoneInfo("America/New_York")


def _ingest(caps):
    def f(symbols, *, limit, dry_run):
        f.called = {"symbols": list(symbols), "dry_run": dry_run}
        return {
            "rows": 0 if dry_run else 9 * len(caps),
            "provider_calls": 0,
            "symbols": {s: {"metrics": ({"MarketCap": caps[s]} if s in caps else {})} for s in symbols},
        }

    return f


def test_runner_uses_the_existing_fundamentals_writer_and_never_market_quotes():
    pol = {"index_universe": ["AAPL", "MSFT", "BRK.B"], "required_issuers": ["AAPL"], "min_cap_coverage": 0.6}
    ing = _ingest({"AAPL": 5e12, "MSFT": 4e12})
    out = icc.run(apply=False, ingest=ing, policy=pol)
    assert ing.called == {"symbols": ["AAPL", "MSFT", "BRK.B"], "dry_run": True}
    assert out["ok"] and out["missing"] == ["BRK.B"] and out["rows_written"] == 0
    src = open(icc.__file__).read()
    assert "write_market_quotes" not in src and "market_quotes_writer" not in src


def test_required_issuer_missing_fails_even_with_count_coverage():
    pol = {"index_universe": ["AAPL", "MSFT", "X", "Y", "Z"], "required_issuers": ["AAPL"], "min_cap_coverage": 0.6}
    out = icc.run(apply=False, ingest=_ingest({"MSFT": 4e12, "X": 1e9, "Y": 1e9, "Z": 1e9}), policy=pol)
    assert out["coverage"] == 0.8 and out["required_missing"] == ["AAPL"] and out["ok"] is False


def test_policy_lists_each_issuer_once():
    ev = load_policy()["event"]
    uni = ev["index_universe"]
    assert "GOOG" not in uni and "GOOGL" in uni and len(uni) == len(set(uni))
    aliased = {ev["issuer_aliases"].get(s, s) for s in uni}
    assert len(aliased) == len(uni)


def test_alphabet_counts_once_when_both_share_classes_report():
    ev = load_policy()["event"]
    now = datetime(2026, 10, 27, 17, 0, tzinfo=ET)
    rows = [
        {"symbol": s, "earnings_date": "2026-10-28", "earnings_timing": "amc", "as_of": "2026-10-20T00:00:00+00:00"}
        for s in ("GOOG", "GOOGL")
    ]
    weights = {"GOOGL": 0.0875, "AAPL": 0.12}
    r = event_calendar.earnings_share(now, rows, weights, 3, ev)
    assert list(r["reporters"]) == ["GOOGL"] and abs(r["share"] - 0.0875) < 1e-9


class _R:
    def __init__(self, w):
        self.w = w

    def index_weights(self, *, end, universe=None):
        return {"weights": {k: v for k, v in self.w.items() if k in (universe or self.w)}}


def test_coverage_withholds_weights_when_a_largest_issuer_is_missing():
    pol = load_policy()
    uni = pol["event"]["index_universe"]
    w = {s: 1.0 / len(uni) for s in uni if s != "NVDA"}  # 33 of 34 by count, but NVDA missing
    ctx = c.EvalContext(now=datetime(2026, 10, 28, 16, 30, tzinfo=ET), reader=_R(w), policy=pol)
    assert registry._covered_weights(ctx, ctx.reader.index_weights) is None
    assert "NVDA" in ctx.extras["index_weights_note"]
    ok = dict(w, NVDA=1.0 / len(uni))
    ctx2 = c.EvalContext(now=ctx.now, reader=_R(ok), policy=pol)
    assert registry._covered_weights(ctx2, ctx2.reader.index_weights) is not None


def test_runner_requests_the_finviz_cache_key_for_brk():
    pol = {
        "index_universe": ["AAPL", "BRK.B"],
        "issuer_aliases": {"BRK-B": "BRK.B"},
        "required_issuers": [],
        "min_cap_coverage": 0.5,
    }
    ing = _ingest({"AAPL": 5e12, "BRK-B": 1e12})
    out = icc.run(apply=False, ingest=ing, policy=pol)
    assert ing.called["symbols"] == ["AAPL", "BRK-B"] and out["missing"] == [] and out["with_cap"] == 2


def test_alias_keys_fold_into_the_issuer_and_reader_filters_finviz():
    pol = load_policy()
    uni = pol["event"]["index_universe"]
    seen = {}

    class R:
        def index_weights(self, *, end, universe=None):
            seen["universe"] = list(universe)
            w = {s: 1.0 for s in uni if s != "BRK.B"}
            w["BRK-B"] = 1.0
            return {"weights": w}

    ctx = c.EvalContext(now=datetime(2026, 10, 28, 16, 30, tzinfo=ET), reader=R(), policy=pol)
    w = registry._covered_weights(ctx, ctx.reader.index_weights)
    assert "BRK-B" in seen["universe"] and "BRK.B" in w["weights"] and "BRK-B" not in w["weights"]
    src = open("scripts/lib/market_risk/reader.py").read()
    assert "source = 'finviz'" in src


def test_non_universe_reporters_never_appear():
    ev = load_policy()["event"]
    now = datetime(2026, 10, 27, 17, 0, tzinfo=ET)
    rows = [
        {"symbol": s, "earnings_date": "2026-10-28", "earnings_timing": "amc", "as_of": "2026-10-20T00:00:00+00:00"}
        for s in ("ABG", "ACGL", "MSFT")
    ]
    r = event_calendar.earnings_share(now, rows, {"MSFT": 0.1}, 3, ev)
    assert list(r["reporters"]) == ["MSFT"]
