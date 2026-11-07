"""The score phase gets a wall-clock cap (2026-11-07).

Why: the 5-min scalp lane runs under `timeout 295` and the score phase was the one phase with no cap. Every
ticker took a yfinance `.info`, up to two `.history` calls, a company-name lookup and — for a headline that
failed relevance — an unbounded Yahoo RSS fetch, all serial. On 2026-11-06, 64 of 78 cycles were SIGTERMed at
295 s inside `score` (one more died in `ingest`), which the scheduler projection then read as stale output and
the monitor as lock skips. Past the cap a row still scores, on the data the ingest and enrich phases already
hold, and the cycle receipt records how many rows that was — a cut cycle must never look like a cold universe.

Fakes only: no network, no database, no Telegram.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import scoring  # noqa: E402

DAY = "2026-11-06"
ROW = {"symbol": "AAA", "price": 5.0, "change_percent": 3.0, "relative_volume": 2.0,
       "gap_percent": 1.0, "float_m": 10.0, "volume": 1000, "avg_volume": 500}
ENRICHMENT = {"AAA": {"top_catalyst": {"title": "AAA wins a large supply deal"},
                      "catalyst_tier": "high", "has_fresh_catalyst": True, "catalysts": []}}


# ── the window itself ───────────────────────────────────────────────────────────────────────────────────────────

def test_no_deadline_means_no_cap():
    """The full-run caller passes nothing: its behaviour must not change."""
    assert scoring.score_network_deadline(None, 60) is None


def test_budget_caps_the_window_short_of_a_distant_deadline():
    before = time.monotonic()
    dl = scoring.score_network_deadline(before + 10_000, budget_s=60)
    assert before + 59 <= dl <= time.monotonic() + 60


def test_the_hard_deadline_wins_when_it_is_sooner_than_the_budget():
    """A late-starting cycle cannot spend its budget into the tail, however generous the budget is."""
    deadline = time.monotonic() + 100
    dl = scoring.score_network_deadline(deadline, budget_s=10_000)
    assert dl == pytest.approx(deadline - scoring.SCORE_NETWORK_TAIL_S)


def test_the_tail_is_reserved_even_when_scoring_starts_late():
    """A cycle already inside its last 30 s does no network at all — persist and the alert own that window."""
    assert scoring.score_network_deadline(time.monotonic() + 10, budget_s=60) < time.monotonic()
    assert scoring._network_spent(scoring.score_network_deadline(time.monotonic() + 10, budget_s=60))


def test_the_lane_config_declares_the_budget():
    import yaml

    cfg = yaml.safe_load((ROOT / "config" / "trade_ai_scalp_lane.yaml").read_text(encoding="utf-8"))
    assert cfg["score_network_budget_s"] == 60
    assert cfg["score_network_budget_s"] < cfg["post_enrich_reserve_s"] + cfg["enrich_budget_s"]


# ── what a closed window does to a row ─────────────────────────────────────────────────────────────────────────

def test_a_closed_window_starts_no_network_call_and_scores_the_row(monkeypatch):
    """No yfinance, no RSS fetch — and the row still comes back scored, not missing."""
    touched: list = []
    yf = types.ModuleType("yfinance")

    class _Ticker:
        def __init__(self, symbol):
            touched.append(("yf", symbol))

        @property
        def info(self):
            touched.append(("yf.info", None))
            return {}

        def history(self, period="1mo"):
            touched.append(("yf.history", None))
            return []

    yf.Ticker = _Ticker
    monkeypatch.setitem(sys.modules, "yfinance", yf)
    import urllib.request

    real_urlopen = urllib.request.urlopen
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: touched.append(("rss", a[0])) or real_urlopen(*a, **k))
    stats: dict = {}
    out = scoring.score_all([dict(ROW)], dict(ENRICHMENT), str(ROOT), use_llm=False,
                            deadline_monotonic=time.monotonic() - 1, network_budget_s=60, stats=stats)
    # Every provider call in the score path: yfinance (industry/sector/confluence) and the Yahoo RSS feed.
    # The loopback weights fetch from the Command Center is not one of them and may still happen.
    provider = [t for t in touched if t[0].startswith("yf") or "feeds.finance.yahoo.com" in str(t[1])]
    assert provider == [], f"a closed window still started provider work: {provider}"
    assert len(out) == 1 and out[0]["symbol"] == "AAA" and out[0]["decision"]
    assert stats["scoring_network_skips"] == 1
    assert stats["budget_skips"] == ["scoring_network"]


def test_an_open_window_still_does_the_lookups(monkeypatch):
    """The cap must not become a permanent downgrade: inside the window the lookups still run."""
    seen: list = []
    monkeypatch.setattr(scoring, "get_sector_context",
                        lambda s, i, deadline_monotonic=None: seen.append(("sector", s, deadline_monotonic)) or {})
    monkeypatch.setattr(scoring, "get_industry_with_fallback",
                        lambda s, r, deadline_monotonic=None: seen.append(("industry", s, deadline_monotonic)) or "Tech")
    monkeypatch.setattr(scoring, "_get_company_name",
                        lambda s, deadline_monotonic=None: seen.append(("name", s, deadline_monotonic)) or "Aaa Inc")
    stats: dict = {}
    scoring.score_all([dict(ROW)], dict(ENRICHMENT), str(ROOT), use_llm=False,
                      deadline_monotonic=time.monotonic() + 600, network_budget_s=60, stats=stats)
    assert {k for k, _, _ in seen} == {"sector", "industry", "name"}
    assert all(dl is not None and dl > time.monotonic() for _, _, dl in seen)
    assert "scoring_network_skips" not in stats and not stats.get("budget_skips")


def test_the_skip_count_names_every_row_it_cut(monkeypatch):
    stats: dict = {}
    rows = [dict(ROW, symbol=s) for s in ("AAA", "BBB", "CCC")]
    scoring.score_all(rows, {}, str(ROOT), use_llm=False,
                      deadline_monotonic=time.monotonic() - 1, network_budget_s=60, stats=stats)
    assert stats["scoring_network_skips"] == 3


# ── the Yahoo fallback: skipped, and bounded when it does run ─────────────────────────────────────────────────

def test_the_yahoo_fallback_returns_nothing_once_the_window_closes(monkeypatch):
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched past the deadline")))
    assert scoring.get_verified_catalyst_fallback("AAA", "Aaa Inc",
                                                  deadline_monotonic=time.monotonic() - 1) == ""


def test_the_yahoo_fallback_is_bounded_by_the_remaining_window(monkeypatch):
    """feedparser.parse(url) has no timeout; the fetch must be opened with one capped by the window."""
    import feedparser
    import urllib.request

    seen: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"<rss></rss>"

    def _urlopen(url, timeout=None):
        seen["url"] = url
        seen["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(feedparser, "parse", lambda data: types.SimpleNamespace(entries=[]))
    out = scoring.get_verified_catalyst_fallback("AAA", "Aaa Inc", deadline_monotonic=time.monotonic() + 2)
    assert out == "No verified catalyst — data quality check failed"
    assert seen["url"].startswith("https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAA")
    assert seen["timeout"] is not None and seen["timeout"] <= 5.0


# ── wiring: the lane config reaches score_all ────────────────────────────────────────────────────────────────

def test_the_runner_passes_its_budget_to_the_cycle(monkeypatch, tmp_path):
    import continuous_runner as cr
    import run_trade_ai_scalp_live as r

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    seen: dict = {}
    monkeypatch.setattr(cr, "run_live_cycle", lambda *a, **k: seen.update(k) or [])
    assert r.main(["--force"]) == 0
    assert seen["score_network_budget_s"] == 60.0


def test_the_cycle_threads_the_budget_into_score_all(monkeypatch, tmp_path):
    """Past the catalyst phase the cycle hands scoring its own amount of network time, not none."""
    import continuous_runner as cr

    seen: dict = {}
    fi = types.ModuleType("finviz_ingestion")

    class _DF:
        def to_dict(self, orient):
            return [{"symbol": "AAA"}]

    fi.load_live_candidates = lambda *a, **k: {"dataframe": _DF()}
    cc = types.ModuleType("catalyst_cache")
    cc.get_bulk = lambda syms, root, day, ttl: ({}, [])
    cc.set_bulk = lambda *a, **k: None
    ce = types.ModuleType("catalyst_enrichment")
    ce.enrich_ticker = lambda *a, **k: {}
    sc = types.ModuleType("scoring")
    sc.filter_candidates = lambda t, root, n: ([], t)

    def _score_all(*a, **k):
        seen.update(k)
        return []

    sc.score_all = _score_all
    si = types.ModuleType("short_interest")
    si.enrich_short_interest = lambda t: t
    si.apply_squeeze_bonus_to_scores = lambda s: s
    db = types.ModuleType("db_adapter")
    db._execute = lambda *a, **k: []
    mc = types.ModuleType("market_context")
    mc.get_market_snapshot = lambda: {}
    uc = types.ModuleType("universe_coverage")
    uc.inject_prime_setup_universe = lambda *a, **k: 0
    rc = types.ModuleType("ross_catalog_universe")
    rc.inject_ross_catalog_universe = lambda *a, **k: 0
    for name, mod in (("finviz_ingestion", fi), ("catalyst_cache", cc), ("catalyst_enrichment", ce),
                      ("scoring", sc), ("short_interest", si), ("db_adapter", db), ("market_context", mc),
                      ("universe_coverage", uc), ("ross_catalog_universe", rc)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setenv("REPORT_OUTPUT_DIR", str(tmp_path / "reports"))
    stats: dict = {}
    deadline = time.monotonic() + 250
    cr.run_live_cycle(tmp_path, "scalp", DAY, cr.CycleState(), "10:00", publish_dashboard=False,
                      cycle_stats=stats, deadline_monotonic=deadline, post_enrich_reserve_s=100,
                      score_network_budget_s=60)
    assert seen["deadline_monotonic"] == deadline
    assert seen["network_budget_s"] == 60
    assert seen["stats"] is stats


def test_a_cycle_with_no_budget_keeps_the_old_unbounded_scoring(monkeypatch, tmp_path):
    """The full run (and any caller that passes nothing) must score exactly as before."""
    import scoring as real_scoring

    assert real_scoring.score_all([dict(ROW)], dict(ENRICHMENT), str(ROOT), use_llm=False)
