"""Scenario replay library (DSN-20261031-market-risk-engine §8, plan §5.15, P2-T12).

Two kinds of test live here:
* reader and fixture tests — always run; they prove the replay data is real, complete and look-ahead free;
* scenario expectations — run the real engine; ``xfail`` only while its modules are not importable, and the
  xfail disappears on its own once ``scoring`` and the daily categories exist (non-strict, condition-based).
Offline: no network, no database.
"""

from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scripts import market_risk_backtest as bt
from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk.fixture_reader import ET, FIXTURE_ROOT, FixtureReader, close_instant

ENGINE = bt.load_engine()
PENDING = ENGINE.pending()
needs_engine = pytest.mark.xfail(bool(PENDING), reason=f"engine modules pending: {', '.join(PENDING)}", strict=False)
SCEN = bt.load_scenarios()
SYMBOLS = "SPY QQQ IWM RSP SMH SOXX XLK TLT HYG LQD UUP USO GLD ^VIX ^VVIX ^VIX3M ^VIX9D".split()


@pytest.fixture(scope="module")
def reader() -> FixtureReader:
    return FixtureReader(FIXTURE_ROOT)


def _et(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=ET)


# ── fixture integrity ────────────────────────────────────────────────────────────────────────────
def test_fixture_files_present_and_small():
    total = sum(p.stat().st_size for p in FIXTURE_ROOT.rglob("*") if p.is_file())
    assert (FIXTURE_ROOT / "bars.csv.gz").exists() and (FIXTURE_ROOT / "SOURCES.json").exists()
    assert total < 3_500_000, f"fixture library grew to {total} bytes"


def test_every_symbol_has_history_through_the_window(reader):
    for s in SYMBOLS:
        rows = reader.daily_bars([s], sessions=10**6, end=close_instant(date(2026, 10, 30)))
        assert len(rows) > 2000, s
        assert rows[0]["date"] <= "2016-01-05" and rows[-1]["date"] >= "2026-10-29", s


def test_every_scenario_window_has_sessions(reader):
    for s in SCEN.values():
        days = reader.sessions(start=date.fromisoformat(s["start"]), end=date.fromisoformat(s["end"]))
        assert days, s["id"]


def test_sources_record_refusals_honestly():
    src = json.loads((FIXTURE_ROOT / "SOURCES.json").read_text())
    assert set(src["yahoo"]) | {r["id"] for r in src["refused"] if r["source"] == "yahoo"} >= set(SYMBOLS)
    for s in ("BAMLH0A0HYM2", "DGS10", "T10Y2Y", "DCOILWTICO", "DTWEXBGS", "VIXCLS"):
        assert s in src["fred"] or any(r["id"] == s for r in src["refused"]), s


def test_no_portfolio_data_in_fixtures():
    banned = ("account", "shares", "cost_basis", "qty", "position")
    for p in FIXTURE_ROOT.rglob("*.json"):
        text = p.read_text().lower()
        assert not any(f'"{b}' in text for b in banned), p


# ── the anti-look-ahead guarantee ────────────────────────────────────────────────────────────────
def test_bar_is_invisible_before_its_close(reader):
    before = reader.daily_bars(["SPY"], sessions=1, end=_et(2020, 2, 24, 15, 59))
    at = reader.daily_bars(["SPY"], sessions=1, end=_et(2020, 2, 24, 16, 0))
    assert before[-1]["date"] == "2020-02-21"
    assert at[-1]["date"] == "2020-02-24"


def test_no_row_after_end_anywhere(reader):
    end = _et(2026, 10, 29, 12, 0)
    rows = reader.daily_bars(SYMBOLS, sessions=50, end=end) + reader.fred(["DGS10", "VIXCLS"], observations=50, end=end)
    assert rows and all(datetime.fromisoformat(r["as_of"]) <= end for r in rows)


def test_naive_datetime_refused(reader):
    with pytest.raises(ValueError):
        reader.daily_bars(["SPY"], sessions=1, end=datetime(2020, 2, 24, 16))


def _mini(tmp_path: Path) -> Path:
    with gzip.open(tmp_path / "bars.csv.gz", "wt") as fh:
        fh.write("date,symbol,open,high,low,close,volume\n2026-10-28,QQQ,1,1,1,1,0\n2026-10-29,QQQ,1,1,1,0.97,0\n")
    with gzip.open(tmp_path / "fred.csv.gz", "wt") as fh:
        fh.write("date,series,value\n2026-10-28,DGS10,5.0\n2026-10-28,VIXCLS,17.0\n")
    (tmp_path / "events.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "kind": "earnings",
                        "symbol": "X",
                        "at": "2026-10-29T16:05:00-04:00",
                        "as_of": "2026-10-01T00:00:00+00:00",
                    },
                    {
                        "kind": "earnings",
                        "symbol": "LATE",
                        "at": "2026-10-29T16:05:00-04:00",
                        "as_of": "2026-10-29T12:00:00+00:00",
                    },
                ]
            }
        )
    )
    (tmp_path / "extended_quotes.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "symbol": "QQQ",
                        "session": "afterhours",
                        "change_pct": -1.5,
                        "at": "2026-10-29T18:04:00-04:00",
                        "as_of": "2026-10-29T18:04:00-04:00",
                    }
                ]
            }
        )
    )
    return tmp_path


def test_fred_publication_lag(tmp_path):
    r = FixtureReader(_mini(tmp_path))
    assert r.fred(["DGS10"], observations=5, end=datetime(2026, 10, 29, 19, 59, tzinfo=timezone.utc)) == []
    assert r.fred(["DGS10"], observations=5, end=datetime(2026, 10, 29, 20, 0, tzinfo=timezone.utc))
    assert r.fred(["VIXCLS"], observations=5, end=datetime(2026, 10, 29, 23, 0, tzinfo=timezone.utc)) == []


def test_events_known_only_after_announcement(tmp_path):
    r = FixtureReader(_mini(tmp_path))
    s, e = _et(2026, 10, 29, 0), _et(2026, 10, 30, 0)
    early = r.earnings_calendar(start=s, end=e, now=_et(2026, 10, 20, 9))
    assert [x["symbol"] for x in early] == ["X"]
    assert {x["symbol"] for x in r.earnings_calendar(start=s, end=e, now=_et(2026, 10, 29, 9))} == {"X", "LATE"}


def test_extended_quote_hidden_until_printed(tmp_path):
    r = FixtureReader(_mini(tmp_path))
    s = _et(2026, 10, 29, 0)
    assert not [q for q in r.quotes(["QQQ"], start=s, end=_et(2026, 10, 29, 18, 3)) if q["session"] == "afterhours"]
    assert [q for q in r.quotes(["QQQ"], start=s, end=_et(2026, 10, 29, 18, 4)) if q["session"] == "afterhours"]


def test_missing_optional_store_is_empty_not_error(reader):
    assert reader.option_snapshots(["QQQ"], sessions=20, end=_et(2020, 3, 2, 16)) == []
    assert reader.sector_states(end=_et(2020, 3, 2, 16)) == []


# ── anchors are computed from data, never typed ──────────────────────────────────────────────────
def test_covid_first_three_percent_drop_is_in_window(reader):
    drops = [d for d, r in bt.daily_returns(reader, "SPY", date(2020, 2, 19), date(2020, 3, 23)) if r <= -3.0]
    assert drops and drops[0] <= "2020-02-27"


def test_2026_has_qqq_corrections(reader):
    eps = bt.drawdown_episodes(reader, "QQQ", date(2026, 1, 2), date(2026, 10, 30), -10.0)
    assert eps, "the RCA says 2026 had three Nasdaq-100 corrections; public data must show at least one"


# ── engine expectations (run the real engine) ────────────────────────────────────────────────────
def _check(s: dict, res: dict, reader: FixtureReader) -> None:
    tl, ex = res["timeline"], s["expect"]
    tiers = [t["tier"] for t in tl]
    if "max_tier_at_least" in ex:
        assert any(bt.at_least(t, ex["max_tier_at_least"]) for t in tiers), (s["id"], tiers)
    if "max_tier_at_most" in ex:
        assert all(bt.SEVERITY[t] <= bt.SEVERITY[ex["max_tier_at_most"]] for t in tiers), (s["id"], tiers)
    if "tier_seen" in ex:
        assert ex["tier_seen"] in tiers, (s["id"], tiers)
    if "tier_by" in ex:
        want = ex["tier_by"]
        ok = [t for t in tl if t["date"] <= want["by"]]
        if want["tier"] == "GREEN":
            assert any(t["tier"] == "GREEN" for t in ok), (s["id"], tiers)
        else:
            assert any(bt.at_least(t["tier"], want["tier"]) for t in ok), (s["id"], tiers)
    if "tier_before_first_drop" in ex:
        w = ex["tier_before_first_drop"]
        drops = [
            d
            for d, r in bt.daily_returns(reader, "SPY", date.fromisoformat(s["start"]), date.fromisoformat(s["end"]))
            if r <= w["drop_pct"]
        ]
        lead = bt.lead_sessions(tl, w["tier"], drops[0])
        assert lead is not None and lead >= w["lead_sessions"], (s["id"], drops[0], lead)
    if "max_orange_sessions" in ex:
        assert sum(t == "ORANGE" for t in tiers) <= ex["max_orange_sessions"], (s["id"], tiers)
    if ex.get("no_red"):
        assert "RED" not in tiers, s["id"]
    if "orange_before_each_correction" in ex:
        w = ex["orange_before_each_correction"]
        for ep in bt.drawdown_episodes(
            reader, w["symbol"], date.fromisoformat(s["start"]), date.fromisoformat(s["end"]), w["min_drawdown_pct"]
        ):
            before = [t for t in tl if ep["peak"] <= t["date"] < ep["trough"]]
            assert any(bt.at_least(t["tier"], "ORANGE") for t in before), (s["id"], ep)


@needs_engine
@pytest.mark.parametrize("sid", [k for k, v in SCEN.items() if "acceptance_20261030" not in v["expect"]])
def test_scenario_expectation(sid, reader):
    s = SCEN[sid]
    _check(s, bt.run_scenario(s, engine=ENGINE, reader=reader), reader)


@needs_engine
def test_analogs_never_change_the_score(reader):
    s = SCEN["banks2023"]
    on = bt.run_scenario(s, engine=ENGINE, reader=reader, analogs=True)["timeline"]
    off = bt.run_scenario(s, engine=ENGINE, reader=reader, analogs=False)["timeline"]
    assert [(t["score"], t["tier"]) for t in on] == [(t["score"], t["tier"]) for t in off]


@needs_engine
def test_unknown_categories_degrade_not_blind(reader):
    """Before the system's own history, options flow and institutional data do not exist. Detection of the
    COVID crash must still work with them (and extended hours) UNKNOWN."""
    s = SCEN["covid2020"]
    res = bt.run_scenario(s, engine=ENGINE, reader=reader, drop=("options_flow", "extended_hours"))
    assert any(bt.at_least(t["tier"], "ORANGE") for t in res["timeline"])
    assert all(t["states"]["options_flow"] == "UNKNOWN" for t in res["timeline"])


@needs_engine
def test_every_assessment_is_advisory(reader):
    res = bt.run_scenario(SCEN["carry2024"], engine=ENGINE, reader=reader)
    c.assert_no_behavior_fields(res)


# ── harness plumbing, proven with a stub engine (tests the harness, not the engine) ──────────────
class _StubScoring:
    """Tier from SPY's 5-session return — just enough to exercise the harness end to end."""

    calls: list = []

    @staticmethod
    def compose(obs, policy, *, prior=None, now=None):
        _StubScoring.calls.append(prior)
        tech = next(o for o in obs if o.category == "technical")
        s = tech.score or 0.0
        tier = "RED" if s >= 75 else "ORANGE" if s >= 60 else "YELLOW" if s >= 40 else "NONE"
        return c.RiskAssessment(
            as_of=now.isoformat(),
            score=s,
            market_score=s,
            tier=tier,
            market_tier=tier,
            confirming=1,
            observations=list(obs),
            contributors=[c.Contributor("technical", s, tech.headline, tech.observed_at)],
        )

    @staticmethod
    def apply_uplift(a, portfolio, policy):
        a.tier, a.uplift = "RED", {"vulnerability": portfolio.vulnerability}
        return a


class _StubTechnical:
    @staticmethod
    def evaluate(ctx):
        bars = ctx.reader.daily_bars(["SPY"], sessions=6, end=ctx.now)
        r = (bars[-1]["close"] / bars[0]["close"] - 1) * 100
        score = max(0.0, min(100.0, -r * 10))
        return c.CategoryObservation(
            "technical", "STRESS" if score >= 60 else "CALM", score, bars[-1]["as_of"], f"SPY {r:+.1f}% 5d"
        )


def _stub_engine():
    e = bt.Engine(scoring=_StubScoring, categories={"technical": _StubTechnical})
    e.categories.update({n: _StubTechnical for n in bt.DAILY_CATEGORIES if n != "technical"})
    return e


def test_harness_walks_sessions_chains_prior_and_fills_unknown(reader):
    _StubScoring.calls.clear()
    res = bt.run_scenario(SCEN["covid2020"], engine=_stub_engine(), policy={}, reader=reader)
    tl = res["timeline"]
    assert tl[0]["date"] == "2020-02-19" and tl[-1]["date"] == "2020-03-23"
    assert _StubScoring.calls[0] is None and all(p is not None for p in _StubScoring.calls[1:])
    assert tl[0]["states"]["extended_hours"] == "UNKNOWN"  # absent module -> UNKNOWN, never dropped
    assert any(t["tier"] == "RED" for t in tl)
    lead = bt.lead_sessions(tl, "ORANGE", "2020-03-16")
    assert lead is not None and lead > 0


def test_harness_extra_time_and_uplift(reader):
    s = dict(SCEN["oct2026"], start="2026-10-27")
    r2 = FixtureReader(FIXTURE_ROOT, overlay=FIXTURE_ROOT / "oct2026")
    ev = datetime(2026, 10, 29, 18, 15, tzinfo=ET)
    book = c.PortfolioContext(vulnerability=78.0)
    tl = bt.run_scenario(s, engine=_stub_engine(), policy={}, reader=r2, extra_times=[ev], portfolio=book)["timeline"]
    hit = [t for t in tl if t["at"] == ev.isoformat()]
    assert hit and hit[0]["session"] == "afterhours" and hit[0]["tier"] == "RED"


def test_forward_move_table_counts(reader):
    tl = bt.run_scenario(SCEN["covid2020"], engine=_stub_engine(), policy={}, reader=reader)["timeline"]
    tab = bt.forward_move_table(tl, reader)
    assert sum(v["n"] for v in tab.values()) == len(tl)
    assert all(0 <= x <= 1 for v in tab.values() for k, x in v.items() if k != "n")


def test_harness_refuses_to_invent_results_when_pending():
    e = bt.Engine(missing=["scoring"])
    with pytest.raises(RuntimeError, match="pending"):
        bt.run_scenario(SCEN["covid2020"], engine=e, policy={})
