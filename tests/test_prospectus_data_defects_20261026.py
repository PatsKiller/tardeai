"""Ticker Prospectus data defects seen in a live report (2026-10-26), fixed at the source.

1. Market cap units: the Finviz cache's ``market_cap_b`` is $M; facts and the peer table print $B.
2. SEC "what changed" is a plain label, never a raw Python dict.
3. Price-series guard: pre-listing / reused-symbol bars are excluded, breaks cut the series, short clean series
   print "not reliable (reason)" instead of a number; correlation to the book leaves the subject out.
4. One canonical CIO conviction (the CIO prospect record); the opportunity screen's score is not a second one.
5. ETF peers come from a category map, never the alphabetical Finviz ETF cohort.
6. Earnings-call transcripts must be real calls for the issuer.
7. The bad-bar quarantine classifier (dry-run detector of scripts/ops/quarantine_bad_price_bars.py).

Synthetic tickers only (ZZ*/ZP*/ZE*); no database, no token store, no network.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import blocks as bk  # noqa: E402
from scripts.lib.prospectus import domains as dm  # noqa: E402
from scripts.lib.prospectus.inputs import Bundle, assemble  # noqa: E402

NOW = datetime(2026, 10, 26, 16, tzinfo=timezone.utc)
QUARANTINE_SCRIPT = "scripts/ops/quarantine_bad_price_bars.py"


def _days(start: date, n: int) -> list[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _bars(closes: list[float], start: date = date(2025, 10, 1)) -> list[dict]:
    return [{"price_date": d, "close": c} for d, c in zip(_days(start, len(closes)), closes)]


def _wiggle(n: int, level: float = 100.0, amp: float = 0.01, phase: int = 0) -> list[float]:
    return [level * (1 + amp * (((i + phase) % 5) - 2) / 2) for i in range(n)]


# ── 1. market cap units ───────────────────────────────────────────────────────────────────────────────────────────
def test_market_cap_is_converted_once_from_finviz_millions():
    assert bk.market_cap_billions({"market_cap_b": 2_345_678.9}) == 2345.68
    assert bk.market_cap_billions({"market_cap_b": 4200.0, "market_cap_usd": 4.2e12}) == 4200.0  # usd preferred
    assert bk.market_cap_billions({}) is None
    rec = {"market_cap_b": 2_000_000.0}
    bk.market_cap_billions(rec)
    assert rec["market_cap_b"] == 2_000_000.0  # never written back, so never normalised twice


def test_peer_table_and_fact_print_billions():
    cache = {"ZZAA": {"industry": "Widgets", "market_cap_b": 2_345_678.9, "forward_pe": 20.0},
             **{f"ZP{i}": {"industry": "Widgets", "market_cap_b": 300_000.0 - i * 10_000, "forward_pe": 15.0 + i}
                for i in range(5)}}
    out = bk.peer_comparison("ZZAA", cache)
    caps = [r["market_cap_b"] for r in out["rows"]]
    assert caps[0] == 2345.68 and all(c < 1000 for c in caps[1:])
    assert out["median"]["market_cap_b"] < 1000


# ── 2. SEC filing labels ──────────────────────────────────────────────────────────────────────────────────────────
def test_filing_what_changed_is_a_plain_label():
    q = {"form": "10-Q", "items": [], "labels": [{"catalyst_type": "filing_quarterly", "item": "10-Q",
                                                   "label": "Quarterly report", "severity": "medium"}]}
    assert dm.filing_change_label(q) == "Quarterly report"
    k8 = {"items": ["2.02", "9.01"], "labels": [{"item": "2.02", "label": "Results of operations"}]}
    assert dm.filing_change_label(k8) == "Item 2.02 Results of operations, Item 9.01"
    raw = {"labels": ["{'catalyst_type': 'filing_quarterly', 'item': '10-Q', 'label': 'Quarterly report'}"]}
    assert dm.filing_change_label(raw) == "Quarterly report"
    assert dm.filing_change_label({}) is None
    for case in (q, k8, raw):
        assert "{" not in (dm.filing_change_label(case) or "") and "catalyst_type" not in (dm.filing_change_label(case) or "")


# ── 3. price-series guard ─────────────────────────────────────────────────────────────────────────────────────────
def test_pre_listing_first_bar_is_excluded():
    closes = [20.0] + _wiggle(120, 160.0)
    q = bk.series_quality(_bars(closes))
    assert [e["close"] for e in q["excluded"]] == [20.0]
    assert "first rows" in q["excluded"][0]["reason"] and q["clean_sessions"] == 120
    assert min(c for _, c in q["series"]) > 100


def test_reverting_bad_print_excluded_but_real_regimes_kept():
    closes = _wiggle(60, 50.0)
    closes[30] = 400.0
    q = bk.series_quality(_bars(closes))
    assert [e["close"] for e in q["excluded"]] == [400.0] and q["break"] is None
    calm = _wiggle(300, 80.0, amp=0.04)
    assert bk.series_quality(_bars(calm))["excluded"] == []


def test_persistent_jump_is_a_break_and_only_the_later_segment_is_used():
    closes = _wiggle(200, 10.0) + _wiggle(80, 90.0)
    q = bk.series_quality(_bars(closes))
    assert q["break"] is not None and q["clean_sessions"] == 80 and q["excluded"] == []


def test_short_clean_series_prints_not_reliable_instead_of_numbers():
    closes = [20.0] + _wiggle(45, 160.0)
    spy = _bars(_wiggle(46, 400.0, amp=0.005, phase=2))
    out = bk.risk_technicals(_bars(closes), spy=spy)
    for metric in ("beta_1y", "vol_annualized_pct", "max_drawdown_1y_pct"):
        assert out[metric] is None
        assert "clean sessions" in out["unreliable"][metric]
    assert "excluded 1 bad bar" in out["unreliable"]["beta_1y"]


def test_ytd_needs_a_prior_year_close():
    s = [(d, c) for d, c in zip(_days(date(2026, 6, 12), 80), _wiggle(80, 160.0))]
    assert bk.window_return(s, "YTD") is None
    s2 = [(d, c) for d, c in zip(_days(date(2025, 12, 1), 120), _wiggle(120, 100.0))]
    assert bk.window_return(s2, "YTD") is not None


def test_book_correlation_leaves_the_subject_out():
    a = _wiggle(260, 100.0, amp=0.03)
    b_ = [100.0 * (1 + 0.02 * ((i * 7 % 11) - 5) / 5) for i in range(260)]
    bars = {"ZZAA": _bars(a), "ZZBB": _bars(b_)}
    book = bk.book_returns({"ZZAA": {"market_value": 9000.0}, "ZZBB": {"market_value": 1000.0}}, lambda s: bars[s])
    out = bk.risk_technicals(bars["ZZAA"], book=book, subject="ZZAA")
    assert out["correlation_to_book"] is not None and out["correlation_to_book"] < 0.99
    assert "leave-one-out" in out["correlation_basis"]
    solo = bk.book_returns({"ZZAA": {"market_value": 1.0}}, lambda s: bars[s])
    out2 = bk.risk_technicals(bars["ZZAA"], book=solo, subject="ZZAA")
    assert out2.get("correlation_to_book") is None and "only this holding" in out2["unreliable"]["correlation_to_book"]


class _Src:
    """Minimal synthetic house sources for inputs.assemble."""

    def __init__(self, closes, cio=None, cache=None):
        self.closes, self._cio, self._cache = closes, cio, cache
        self.state_root = Path("/nonexistent-prospectus-fixture")

    def enrichment_cache(self):
        return self._cache or {"ZZAA": {"industry": "Widgets", "company": "Zeta Widgets Inc", "market_cap_b": 2_345_678.9,
                                        "cached_at": "2026-10-26T06:00:00"}}

    def dossier(self, sym):
        return {"profile": {"sector": "Technology", "industry": "Widgets", "updated_at": "2026-10-25",
                            "last_earnings_date": "2026-10-20"}}

    def bars(self, sym, days=1100):
        if sym == "ZZAA":
            return _bars(self.closes, date(2026, 6, 11))
        return _bars(_wiggle(len(self.closes), 400.0, amp=0.005, phase=1), date(2026, 6, 11))

    def analyst(self, sym):
        return {}

    def consensus(self, syms):
        return {}

    def cio(self, sym):
        return self._cio or {}

    def position_view(self, sym):
        return {}

    def options_theses(self, sym):
        return []

    def lookthrough(self, sym):
        return {}

    def ohlc(self, sym):
        return []


def _labels(b: Bundle) -> dict:
    return {f["label"]: f for f in b.facts}


def test_assemble_never_offers_bad_bar_numbers_to_the_writer():
    closes = [20.0] + _wiggle(95, 160.0)
    b = assemble(_Src(closes), "ZZAA", "watch", now=NOW)
    facts = _labels(b)
    # 95 clean sessions: enough for beta/volatility over the clean segment, not for a 1-year drawdown.
    assert "value" not in facts["Max drawdown 1Y %"] and facts["Max drawdown 1Y %"]["text"].startswith("not reliable")
    assert abs(facts["Beta (1Y vs SPY)"]["value"]) < 5 and facts["Annualized volatility %"]["value"] < 100
    assert "1-year low close" not in facts
    low = next(f for k, f in facts.items() if k.startswith("Low close since"))
    assert low["value"] > 100
    assert "excluded 1 bad bar" in facts["Price history quality"]["text"]
    assert all(c > 100 for _, c in b.series["price_1y"])
    ytd = facts.get("ZZAA return YTD %")
    assert ytd is None  # the clean series starts this year: no YTD figure
    assert facts["Market cap ($B)"]["value"] == 2345.68


# ── 4. one canonical conviction ───────────────────────────────────────────────────────────────────────────────────
def test_one_canonical_conviction_and_verdict_tile_names_its_source():
    src = _Src(_wiggle(300, 50.0), cio={"stance": "ADD", "conviction": 58.1, "evidence_at": "2026-10-26"})
    b = assemble(src, "ZZAA", "watch", now=NOW)
    facts = _labels(b)
    assert facts["CIO conviction (CIO prospect record, 0-100)"]["value"] == 58.1
    assert b.blocks["verdict_tiles"]["verdict"]["sub"] == "CIO conviction 58/100 (CIO prospect record)"


def test_opportunity_screen_is_not_a_second_conviction(tmp_path):
    (tmp_path / "data/cio").mkdir(parents=True)
    (tmp_path / "data/cio/cio_opportunity_projection.json").write_text(json.dumps({"items": [
        {"symbol": "ZZAA", "conviction": 71.3, "upside_pct": 12.0, "stance": "ADD",
         "stance_rationale": "Conviction 71 with R:R 5.1x. Price holds above the invalidation level."}]}))

    class S:
        state_root = tmp_path
    bundle = Bundle(symbol="ZZAA", scope="watch", name="Zeta")
    dm.r_opportunity(dm.Ctx(sources=S(), bundle=bundle, now=NOW))
    text = json.dumps(bundle.facts)
    assert "71.3" not in text and "Conviction 71" not in text and "conviction" not in text.lower().replace(
        "input to the cio prospect record", "")
    assert any(f["label"] == "Opportunity screen: upside pct" for f in bundle.facts)
    assert any("Price holds above" in (f.get("text") or "") for f in bundle.facts)


# ── 5. ETF peers ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_etf_peers_come_from_the_category_map_never_the_alphabetical_cohort():
    etf = {"industry": "Exchange Traded Fund", "forward_pe": 30.0}
    cache = {"ZEGR": etf, "ZEG2": dict(etf), "ZEG3": dict(etf),
             **{f"AA{c}": dict(etf) for c in "ABCDE"}}
    groups = {"_note": "commentary", "growth": ["ZEGR", "ZEG2", "ZEG3", "ZEMISSING"]}
    out = bk.peer_comparison("ZEGR", cache, etf_groups=groups)
    assert [r["symbol"] for r in out["rows"]] == ["ZEGR", "ZEG2", "ZEG3"] and out["peer_group"] == "growth"
    none = bk.peer_comparison("AAA", cache, etf_groups=groups)
    assert [r["symbol"] for r in none["rows"]] == ["AAA"] and none["median"] is None
    assert none["gaps"][0].startswith("peers not available")


def test_config_has_etf_peer_groups():
    from scripts.lib.prospectus import load_config
    groups = load_config().get("etf_peer_groups") or {}
    assert sum(1 for k, v in groups.items() if not k.startswith("_") and isinstance(v, list) and len(v) >= 3) >= 10


# ── 6. transcripts ────────────────────────────────────────────────────────────────────────────────────────────────
def test_only_real_issuer_earnings_calls_are_accepted():
    rej = dm.transcript_rejection
    assert rej({"title": "Trending With Finance ! ZZV 251 #somewealth"}, "ZZV", "Zeta Visa Inc", "2026-10-20")
    assert rej({"title": "Market wrap: earnings call season"}, "ZZV", "Zeta Visa Inc", "2026-10-20") == \
        "title does not name the issuer"
    assert rej({"title": "Zeta Visa Q4 2026 Earnings Call", "publish_date": "2026-10-21"}, "ZZV", "Zeta Visa Inc",
               "2026-10-20") is None
    assert "days from the last report" in rej({"title": "ZZV Q2 earnings call", "publish_date": "2026-05-01"}, "ZZV",
                                              "Zeta Visa Inc", "2026-10-20")


def test_rejected_transcripts_leave_a_named_gap():
    rows = [{"title": "Trending With Finance ! ZZV 251 #x", "channel_name": "c", "publish_date": "2026-10-21",
             "url": "https://example.test/v", "excerpt": "..."}]

    class S:
        state_root = Path("/nonexistent")

        def db(self):
            return lambda sql, params=None, fetch="all": rows
    bundle = Bundle(symbol="ZZV", scope="watch", name="Zeta Visa Inc")
    bundle.context["last_earnings_date"] = "2026-10-20"
    kept, _, _ = dm.r_transcripts(dm.Ctx(sources=S(), bundle=bundle, now=NOW))
    assert kept == [] and not bundle.facts
    block = dm.earnings_call_block(bundle)
    assert block["transcripts"] == [] and "rejected" in block["gaps"][0]


# ── 7. quarantine classifier (dry run) ────────────────────────────────────────────────────────────────────────────
def test_quarantine_classifier_flags_only_the_pre_listing_bar():
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("quarantine_bad_price_bars", ROOT / QUARANTINE_SCRIPT)
    q = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(q)

    days = _days(date(2026, 6, 11), 40)
    rows = [{"id": 1, "price_date": days[0], "close_price": 20.0, "source": "quote_snapshot"}] + [
        {"id": i + 2, "price_date": d, "close_price": c, "source": "daily_bar"}
        for i, (d, c) in enumerate(zip(days[1:], _wiggle(39, 160.0)))]
    out = q.classify(rows)
    assert [r["id"] for r in out["pre_listing"]] == [1] and out["suspect"] == []
    rows2 = [dict(r, source="daily_bar") for r in rows]  # same source → shape only → reported, never quarantined
    out2 = q.classify(rows2)
    assert out2["pre_listing"] == [] and [r["id"] for r in out2["suspect"]] == [1]
    assert q.main(["--symbols", "ZZAA", "--apply"]) == 2  # --apply without a grant is refused before any DB access
