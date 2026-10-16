"""CW1/CW2 lanes (batch 4) write LaneRunReceipt@v2 produced_count and opt into the executor output verdict
(2026-10-15).

Lanes: watchlist-enrichment-sweep (CW1), aegis-social-sentiment, aegis-transcript-discovery, agent-outcome-scorer,
commitment-outcome-sweep, daily-incubator-refresh, hermes-social-sentiment, instrument-belief-writer (CW2).

For each lane the REAL entry point runs inside a fake n8n attempt with its DB / provider / network work stubbed; the
test reads the immutable per-attempt receipt and applies the executor's output verdict with the committed contract
and allowlist entry: ``produced`` for a run that wrote, ``empty_allowed`` for an allowed empty run (where the rule
allows one), RUN_FAILED ``empty_output`` for a fatal skip. Hermetic (tests/support/lane_produced_count.py).
"""

from __future__ import annotations

import sys
import types

import pytest

from tests.support import lane_produced_count as H

LANES = (
    "watchlist-enrichment-sweep",
    "aegis-social-sentiment",
    "aegis-transcript-discovery",
    "agent-outcome-scorer",
    "commitment-outcome-sweep",
    "daily-incubator-refresh",
    "hermes-social-sentiment",
    "instrument-belief-writer",
)


@pytest.mark.parametrize("lane", LANES)
def test_lane_is_opted_in_with_code_that_writes_produced_count(lane):
    H.assert_opted_in(lane)


def _boom(*a, **k):
    raise RuntimeError("provider down")


def _driver_stub(monkeypatch):
    """CI has no psycopg2; the lane modules import it at module level. Stub it only when it is absent (no test here
    opens a connection: every _db/_get_conn is replaced)."""
    try:
        import psycopg2  # noqa: F401
        import psycopg2.extras  # noqa: F401
    except ImportError:
        fake = types.ModuleType("psycopg2")
        extras = types.ModuleType("psycopg2.extras")
        extras.RealDictCursor = object
        fake.extras = extras
        fake.connect = _boom
        monkeypatch.setitem(sys.modules, "psycopg2", fake)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)


def _universe_module(monkeypatch, symbols):
    fake = types.ModuleType("aegis_nightly_ingestion")
    fake.resolve_universe = lambda: [{"symbol": s, "reasons": ["watchlist"]} for s in symbols]
    monkeypatch.setitem(sys.modules, "aegis_nightly_ingestion", fake)


# ── watchlist-enrichment-sweep ────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("total,enriched,expect", [(10, 8, "produced"), (0, 0, "empty_output")])
def test_watchlist_enrichment_sweep(monkeypatch, tmp_path, total, enriched, expect):
    import watchlist_enrichment_sweep as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "watchlist-enrichment-sweep")
    monkeypatch.setattr(m, "sweep", lambda limit=None, dry=False: {"total": total, "enriched": enriched})
    assert m.main(["--once"]) == 0
    out = H.check(tmp_path, "watchlist-enrichment-sweep", run_id, produced=enriched, expect=expect)
    if not total:
        assert out["output_verdict"]["fatal"] == ["universe_empty_unexpected"]


def test_watchlist_enrichment_sweep_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    import watchlist_enrichment_sweep as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "watchlist-enrichment-sweep")
    monkeypatch.setattr(m, "sweep", _boom)
    with pytest.raises(RuntimeError):
        m.main(["--once"])
    H.check(tmp_path, "watchlist-enrichment-sweep", run_id, produced=0, expect="empty_output")


# ── aegis-social-sentiment ────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def ass(monkeypatch):
    import aegis_social_sentiment as m

    monkeypatch.setattr(m, "_load_env", lambda: None)
    monkeypatch.setattr(m, "_db_available", lambda: True)
    monkeypatch.setattr(m, "fetch_reddit_mentions", lambda syms: {})
    monkeypatch.setattr(m, "fetch_brave_social", lambda syms, max_queries=10: {})
    monkeypatch.setattr(m, "persist_sentiment", lambda sym, s, fam: True)
    return m


def _stocktwits(m, hits):
    def fetch(symbols, max_symbols=50):
        m.FETCH_OK["stocktwits"] = 1
        return {s: {"mentions": 3} for s in symbols[:hits]}

    return fetch


@pytest.mark.parametrize("universe,hits,expect", [(("NOC", "LMT"), 2, "produced"), (("NOC",), 0, "empty_allowed"),
                                                  ((), 0, "empty_output")])
def test_aegis_social_sentiment(ass, monkeypatch, tmp_path, universe, hits, expect):
    run_id = H.attempt_env(monkeypatch, tmp_path, "aegis-social-sentiment")
    _universe_module(monkeypatch, universe)
    monkeypatch.setattr(ass, "fetch_stocktwits_mentions", _stocktwits(ass, hits))
    monkeypatch.setattr(ass, "normalize_sentiment", lambda sym, r, b, st: {"x": 1} if st.get("mentions") else None)
    assert ass.cli([]) == 0
    out = H.check(tmp_path, "aegis-social-sentiment", run_id, produced=hits, expect=expect)
    if not universe:
        assert out["output_verdict"]["fatal"] == ["universe_empty_unexpected"]


def test_aegis_social_sentiment_db_down_is_a_fatal_skip(ass, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "aegis-social-sentiment")
    monkeypatch.setattr(ass, "_db_available", lambda: False)
    assert ass.cli([]) == 1
    H.check(tmp_path, "aegis-social-sentiment", run_id, produced=0, expect="empty_output")


# ── aegis-transcript-discovery ────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def atd(monkeypatch):
    import aegis_transcript_discovery as m

    monkeypatch.setattr(m, "_load_env", lambda: None)
    monkeypatch.setattr(m, "_db_available", lambda: True)
    monkeypatch.setattr(m, "fetch_brave_discovery", lambda prio, themes: [])
    monkeypatch.setattr(m, "persist_discovery", lambda recs: len(recs))
    monkeypatch.setattr(m, "persist_transcripts", lambda recs: len(recs))
    return m


@pytest.mark.parametrize("universe,n,expect", [(("NOC",), 3, "produced"), (("NOC",), 0, "empty_allowed"),
                                               ((), 0, "empty_output")])
def test_aegis_transcript_discovery(atd, monkeypatch, tmp_path, universe, n, expect):
    run_id = H.attempt_env(monkeypatch, tmp_path, "aegis-transcript-discovery")
    _universe_module(monkeypatch, universe)
    monkeypatch.setattr(atd, "fetch_youtube_transcripts", lambda prio, network=True: [{"source_family": "yt"}] * n)
    monkeypatch.setattr(atd, "enrich_from_article_index", lambda syms: [])
    assert atd.cli([]) == 0
    H.check(tmp_path, "aegis-transcript-discovery", run_id, produced=n, expect=expect)


def test_aegis_transcript_discovery_db_down_is_a_fatal_skip(atd, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "aegis-transcript-discovery")
    monkeypatch.setattr(atd, "_db_available", lambda: False)
    assert atd.cli([]) == 1
    H.check(tmp_path, "aegis-transcript-discovery", run_id, produced=0, expect="empty_output")


# ── agent-outcome-scorer ──────────────────────────────────────────────────────────────────────────────────────────
class _PipelineRun:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def rows(self, n):
        pass


@pytest.mark.parametrize("saved,expect", [(4, "produced"), (0, "empty_allowed")])
def test_agent_outcome_scorer(monkeypatch, tmp_path, saved, expect):
    _driver_stub(monkeypatch)
    import agent_outcome_scorer as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "agent-outcome-scorer")
    monkeypatch.setattr(m, "PipelineRun", _PipelineRun)
    monkeypatch.setattr(m, "run_scoring", lambda: {"unscored_pairs": saved, "saved": saved, "save_failed": 0,
                                                   "rule_write_failed": 0, "source_performance_ok": True})
    assert m.main(["--apply"]) == 0
    H.check(tmp_path, "agent-outcome-scorer", run_id, produced=saved, expect=expect)


def test_agent_outcome_scorer_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    _driver_stub(monkeypatch)
    import agent_outcome_scorer as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "agent-outcome-scorer")
    monkeypatch.setattr(m, "PipelineRun", _PipelineRun)
    monkeypatch.setattr(m, "run_scoring", _boom)
    with pytest.raises(RuntimeError):
        m.main(["--apply"])
    H.check(tmp_path, "agent-outcome-scorer", run_id, produced=0, expect="empty_output")


# ── commitment-outcome-sweep ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("outcomes,expect", [(2, "produced"), (0, "empty_allowed")])
def test_commitment_outcome_sweep(monkeypatch, tmp_path, outcomes, expect):
    import sweep_commitment_outcomes as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "commitment-outcome-sweep")

    def fake_run(args):
        m.LAST_SUMMARY.update(outcomes=outcomes, lessons=0, due=outcomes, already_settled=1)
        return 0

    monkeypatch.setattr(m, "_run", fake_run)
    assert m.main(["--apply", "--state-root", str(tmp_path / "wake")]) == 0
    out = H.check(tmp_path, "commitment-outcome-sweep", run_id, produced=outcomes, expect=expect)
    if not outcomes:
        assert out["output_verdict"]["empty_reason"] == "nothing_due"


def test_commitment_outcome_sweep_missing_store_is_a_fatal_skip(monkeypatch, tmp_path):
    """The real _run: no commitments.jsonl under --state-root exits 2 before any provider import."""
    import sweep_commitment_outcomes as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "commitment-outcome-sweep")
    assert m.main(["--apply", "--state-root", str(tmp_path / "wake")]) == 2
    doc = H.attempt_receipt(tmp_path, "commitment-outcome-sweep", run_id)
    assert doc["skipped_reasons"]["no_input_unexpected"] == 1
    H.check(tmp_path, "commitment-outcome-sweep", run_id, produced=0, expect="empty_output")


def test_commitment_outcome_sweep_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    import sweep_commitment_outcomes as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "commitment-outcome-sweep")
    monkeypatch.setattr(m, "_run", _boom)
    with pytest.raises(RuntimeError):
        m.main(["--apply", "--state-root", str(tmp_path / "wake")])
    H.check(tmp_path, "commitment-outcome-sweep", run_id, produced=0, expect="empty_output")


# ── daily-incubator-refresh ───────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("counts,produced,expect", [
    ({"improved": 1, "degraded": 1, "stayed_active": 2, "no_data": 1, "processed": 5}, 4, "produced"),
    ({"improved": 0, "degraded": 0, "stayed_active": 0, "no_data": 3, "processed": 3}, 0, "empty_allowed"),
])
def test_daily_incubator_refresh(monkeypatch, tmp_path, counts, produced, expect):
    import daily_incubator_refresh as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "daily-incubator-refresh")
    monkeypatch.setattr(m, "_run", lambda args: {**counts, "catalyst_refreshed": 0})
    assert m.main(["--apply"]) == 0
    H.check(tmp_path, "daily-incubator-refresh", run_id, produced=produced, expect=expect)


def test_daily_incubator_refresh_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    import daily_incubator_refresh as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "daily-incubator-refresh")
    monkeypatch.setattr(m, "_run", _boom)
    with pytest.raises(RuntimeError):
        m.main(["--apply"])
    H.check(tmp_path, "daily-incubator-refresh", run_id, produced=0, expect="empty_output")


# ── hermes-social-sentiment ───────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def hss(monkeypatch):
    import hermes_social_sentiment as m

    monkeypatch.setattr(m, "_load_env", lambda: None)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    monkeypatch.setattr(m, "normalize", lambda sym, mentions: {"x": 1})
    monkeypatch.setattr(m, "persist", lambda sym, s: True)
    report = types.ModuleType("lib.data_source_report")
    report.report_source = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "lib.data_source_report", report)
    m._UNIVERSE_ERROR.clear()
    return m


def _forum(m, hit_symbols):
    def search(sym, limit=6):
        m._FETCH_STATS["ok"] += 1
        return [{"title": "x"}] if sym in hit_symbols else []

    return search


@pytest.mark.parametrize("universe,hits,expect", [(["NOC", "LMT"], {"NOC"}, "produced"), (["NOC"], set(), "empty_allowed"),
                                                  ([], set(), "empty_output")])
def test_hermes_social_sentiment(hss, monkeypatch, tmp_path, universe, hits, expect):
    run_id = H.attempt_env(monkeypatch, tmp_path, "hermes-social-sentiment")
    monkeypatch.setattr(hss, "_resolve", lambda args: list(universe))
    monkeypatch.setattr(hss, "search_forum", _forum(hss, hits))
    assert hss.main(["--apply"]) == 0
    out = H.check(tmp_path, "hermes-social-sentiment", run_id, produced=len(hits), expect=expect)
    if not universe:
        assert out["output_verdict"]["fatal"] == ["universe_empty_unexpected"]


def test_hermes_social_sentiment_universe_error_is_a_fatal_skip(hss, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "hermes-social-sentiment")
    monkeypatch.setattr(hss, "_resolve", _boom)
    with pytest.raises(RuntimeError):
        hss.main(["--apply"])
    H.check(tmp_path, "hermes-social-sentiment", run_id, produced=0, expect="empty_output")


# ── instrument-belief-writer ──────────────────────────────────────────────────────────────────────────────────────
def _beliefs(written):
    return {"settled_rows": 5, "groups": max(written, 2), "written_beliefs": written, "would_write_beliefs": 0,
            "noop": 2 - min(written, 2), "refused": 0, "subjects_written": written, "skipped": 0, "store": "x"}


@pytest.mark.parametrize("written,expect", [(3, "produced"), (0, "empty_allowed")])
def test_instrument_belief_writer(monkeypatch, tmp_path, written, expect):
    import write_instrument_beliefs as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "instrument-belief-writer")
    monkeypatch.setattr(m, "update_beliefs_from_settled", lambda root, wake_root, apply: _beliefs(written))
    assert m.main(["--apply", "--root", str(tmp_path / "state"), "--wake-root", str(tmp_path / "wake")]) == 0
    H.check(tmp_path, "instrument-belief-writer", run_id, produced=written, expect=expect)


def test_instrument_belief_writer_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    import write_instrument_beliefs as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "instrument-belief-writer")
    monkeypatch.setattr(m, "update_beliefs_from_settled", _boom)
    with pytest.raises(RuntimeError):
        m.main(["--apply", "--root", str(tmp_path / "state"), "--wake-root", str(tmp_path / "wake")])
    H.check(tmp_path, "instrument-belief-writer", run_id, produced=0, expect="empty_output")
