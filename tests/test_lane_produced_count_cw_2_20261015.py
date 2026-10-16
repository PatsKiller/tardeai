"""CW1 lanes (batch 2) write LaneRunReceipt@v2 produced_count and opt into the executor output verdict (2026-10-15).

Lanes: finviz-enrichment, finviz-proactive-research, finviz-screener-runner, finviz-sector-research,
hermes-analyst-signal-discovery, hermes-governance-api, hermes-momentum-catalyst-scalp, hermes-news-bridge.

For each lane the REAL ``main()`` runs inside a fake n8n attempt with its DB / provider / network work stubbed; the
test reads the immutable per-attempt receipt and applies the executor's output verdict with the committed contract
and allowlist entry: ``produced`` for a run that wrote, ``empty_allowed`` for an allowed empty run (where the rule
allows one), RUN_FAILED ``empty_output`` for a fatal skip. Hermetic (tests/support/lane_produced_count.py).
"""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest

from tests.support import lane_produced_count as H

LANES = (
    "finviz-enrichment",
    "finviz-proactive-research",
    "finviz-screener-runner",
    "finviz-sector-research",
    "hermes-analyst-signal-discovery",
    "hermes-governance-api",
    "hermes-momentum-catalyst-scalp",
    "hermes-news-bridge",
)


@pytest.mark.parametrize("lane", LANES)
def test_lane_is_opted_in_with_code_that_writes_produced_count(lane):
    H.assert_opted_in(lane)


class _Cur:
    description = ()

    def __init__(self, rows=()):
        self._rows = list(rows)

    def execute(self, *a, **k):
        return None

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return None


class _Conn:
    def __init__(self, rows=()):
        self._rows = rows

    def cursor(self, *a, **k):
        return _Cur(self._rows)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _boom(*a, **k):
    raise RuntimeError("provider down")


def _no_pipeline_registry(monkeypatch):
    fake = types.ModuleType("pipeline_registry")
    fake.run_start = lambda *a, **k: None
    fake.run_complete = lambda *a, **k: None
    fake.run_fail = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "pipeline_registry", fake)


# ── finviz-enrichment ─────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def fe(monkeypatch):
    import finviz_enrichment as m

    _no_pipeline_registry(monkeypatch)
    monkeypatch.setattr(m, "print_enriched", lambda *a, **k: None)
    m._UNIVERSE_ERRORS.clear()
    return m


def _fe_enrich(m, stale, refreshed):
    def enrich(symbols, project_root="."):
        m._RUN_STATS.clear()
        m._RUN_STATS.update({"symbols": len(symbols), "stale": stale, "views": {111: refreshed},
                             "rejected_non_ticker": 0, "refreshed": refreshed})
        return {s: {} for s in symbols}

    return enrich


@pytest.mark.parametrize("stale,refreshed,expect", [(3, 2, "produced"), (0, 0, "empty_allowed")])
def test_finviz_enrichment(fe, monkeypatch, tmp_path, stale, refreshed, expect):
    run_id = H.attempt_env(monkeypatch, tmp_path, "finviz-enrichment")
    monkeypatch.setattr(fe, "default_universe_symbols", lambda *a, **k: ["NOC", "LMT", "RTX"])
    monkeypatch.setattr(fe, "enrich_tickers", _fe_enrich(fe, stale, refreshed))
    monkeypatch.setattr(sys, "argv", ["finviz_enrichment.py"])
    assert fe.main() == 0
    H.check(tmp_path, "finviz-enrichment", run_id, produced=refreshed, expect=expect)


def test_finviz_enrichment_empty_universe_is_a_fatal_skip(fe, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "finviz-enrichment")
    monkeypatch.setattr(fe, "default_universe_symbols", lambda *a, **k: [])
    monkeypatch.setattr(sys, "argv", ["finviz_enrichment.py"])
    assert fe.main() == 0  # exit unchanged: an empty universe with no read error still exits 0
    out = H.check(tmp_path, "finviz-enrichment", run_id, produced=0, expect="empty_output")
    assert out["output_verdict"]["fatal"] == ["universe_empty_unexpected"]


def test_finviz_enrichment_counts_tickers_with_view_data(fe, monkeypatch, tmp_path):
    """enrich_tickers records ``refreshed`` = stale tickers present in at least one view's result."""
    monkeypatch.setattr(fe, "load_cache", lambda root: {})
    monkeypatch.setattr(fe, "save_cache", lambda cache, root: None)
    monkeypatch.setattr(fe, "_default_views", lambda skip=False: [111, 161])
    monkeypatch.setattr(fe, "_fetch_view", lambda tickers, v, root, **k: {"NOC": {"price": 1.0}} if v == 111 else {})
    monkeypatch.setitem(sys.modules, "intelligence_entity_manager", None)  # IER write-back import fails (non-fatal)
    fe.enrich_tickers(["NOC", "LMT"], project_root=str(tmp_path))
    assert fe._RUN_STATS["stale"] == 2 and fe._RUN_STATS["refreshed"] == 1


# ── finviz-proactive-research ─────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def fpr(monkeypatch, tmp_path):
    import finviz_proactive_research as m

    monkeypatch.setattr(m, "ROOT", tmp_path)  # no holdings.json -> watchlist universe only
    monkeypatch.setattr(m, "_load_env", lambda: None)
    monkeypatch.setattr(m, "_get_conn", lambda: _Conn(rows=[("NOC",), ("LMT",)]))
    news = types.ModuleType("finviz_news")
    news.fetch_finviz_stock_news_all = lambda lookback_hours=72: [
        {"headline": "NOC wins award", "url": "https://x/1", "tickers": ["NOC", "LMT"], "datetime": 1760000000},
    ]
    scoring = types.ModuleType("content_scoring")
    scoring.score_content = lambda **k: {"relevance_score": 0.5}
    scoring.tag_content = lambda **k: {}
    policy = types.ModuleType("hermes_source_policy")
    policy.should_ingest = lambda src: (True, "")
    for name, mod in (("finviz_news", news), ("content_scoring", scoring), ("hermes_source_policy", policy)):
        monkeypatch.setitem(sys.modules, name, mod)
    return m


@pytest.mark.parametrize("dup,expect,produced", [(False, "produced", 2), (True, "empty_allowed", 0)])
def test_finviz_proactive_research(fpr, monkeypatch, tmp_path, dup, expect, produced):
    run_id = H.attempt_env(monkeypatch, tmp_path, "finviz-proactive-research")
    monkeypatch.setattr(fpr, "is_duplicate", lambda *a, **k: dup)
    monkeypatch.setattr(fpr, "write_news_articles", lambda cur, rows, source: SimpleNamespace(rows_written=1))
    assert fpr.main(["--max", "400", "--lookback-hours", "12"]) == 0
    doc = H.attempt_receipt(tmp_path, "finviz-proactive-research", run_id)
    assert doc["attempted_count"] == 2
    H.check(tmp_path, "finviz-proactive-research", run_id, produced=produced, expect=expect)


def test_finviz_proactive_research_crash_is_a_fatal_skip(fpr, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "finviz-proactive-research")
    monkeypatch.setattr(fpr, "_get_conn", _boom)
    with pytest.raises(RuntimeError):
        fpr.main([])
    H.check(tmp_path, "finviz-proactive-research", run_id, produced=0, expect="empty_output")


# ── finviz-screener-runner ────────────────────────────────────────────────────────────────────────────────────────
def _screener_result(n_ok, n_empty):
    rows = [{"screener_id": f"s{i}", "total_found": 5, "new_tickers": 0, "membership_updated": 5, "db_ok": True}
            for i in range(n_ok)]
    rows += [{"screener_id": f"e{i}", "total_found": 0, "new_tickers": 0} for i in range(n_empty)]
    return {"mode": "live", "screeners_run": len(rows), "total_new_tickers": 0, "membership_failures": 0,
            "db_write_failures": 0, "results": rows}


@pytest.mark.parametrize("n_ok,n_empty,expect", [(2, 1, "produced"), (0, 3, "empty_output"), (0, 0, "empty_output")])
def test_finviz_screener_runner(monkeypatch, tmp_path, n_ok, n_empty, expect):
    import finviz_screener_runner as m

    _no_pipeline_registry(monkeypatch)
    run_id = H.attempt_env(monkeypatch, tmp_path, "finviz-screener-runner")
    monkeypatch.setattr(m, "run_screener", lambda screener_id=None, dry_run=False: _screener_result(n_ok, n_empty))
    assert m.main(["--run"]) == 0
    out = H.check(tmp_path, "finviz-screener-runner", run_id, produced=n_ok, expect=expect)
    if not (n_ok or n_empty):
        assert out["output_verdict"]["fatal"] == ["unconfigured"]


def test_finviz_screener_runner_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    import finviz_screener_runner as m

    _no_pipeline_registry(monkeypatch)
    run_id = H.attempt_env(monkeypatch, tmp_path, "finviz-screener-runner")
    monkeypatch.setattr(m, "run_screener", _boom)
    with pytest.raises(RuntimeError):
        m.main(["--run"])
    H.check(tmp_path, "finviz-screener-runner", run_id, produced=0, expect="empty_output")


# ── finviz-sector-research ────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def fsr(monkeypatch):
    import finviz_sector_research as m

    monkeypatch.setattr(m, "_load_env", lambda: None)
    monkeypatch.setattr(m, "_get_conn", lambda: _Conn())
    return m


def test_finviz_sector_research_produced(fsr, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "finviz-sector-research")
    monkeypatch.setenv("FINVIZ_API_TOKEN", "not-a-secret")
    monkeypatch.setattr(fsr, "_fetch", lambda g: [{"Name": f"{g}-a"}, {"Name": f"{g}-b"}, {"Name": ""}])
    assert fsr.main([]) == 0
    H.check(tmp_path, "finviz-sector-research", run_id, produced=4, expect="produced")


def test_finviz_sector_research_no_token_is_a_fatal_skip(fsr, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "finviz-sector-research")
    monkeypatch.setenv("FINVIZ_API_TOKEN", "")
    assert fsr.main([]) == 1
    doc = H.attempt_receipt(tmp_path, "finviz-sector-research", run_id)
    assert doc["skipped_reasons"]["no_credentials"] == 1
    H.check(tmp_path, "finviz-sector-research", run_id, produced=0, expect="empty_output")


def test_finviz_sector_research_every_fetch_failing_is_empty_output(fsr, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "finviz-sector-research")
    monkeypatch.setenv("FINVIZ_API_TOKEN", "not-a-secret")
    monkeypatch.setattr(fsr, "_fetch", _boom)
    assert fsr.main([]) == 0  # exit unchanged; the receipt is a failed one with zero rows
    H.check(tmp_path, "finviz-sector-research", run_id, produced=0, expect="empty_output")


# ── hermes-analyst-signal-discovery ───────────────────────────────────────────────────────────────────────────────
def _report(n, *, disabled=False):
    return {"dry_run": False, "effective_dry_run": disabled, "enabled_in_schedule": not disabled,
            "scanned_symbols": 10, "signals_detected": n, "upserted": 0 if disabled else n,
            "would_upsert": n if disabled else None, "thresholds": {}, "by_type": {}, "by_domain": {},
            "skipped_reasons": {}, "notes": [], "candidates": [{"candidate_type": "TICKER_CANDIDATE", "domain": "x",
                                                                 "label": "NOC", "direction": "up"}] * n}


@pytest.mark.parametrize("n,disabled,expect", [(2, False, "produced"), (0, False, "empty_allowed"),
                                               (2, True, "empty_output")])
def test_hermes_analyst_signal_discovery(monkeypatch, tmp_path, n, disabled, expect):
    import hermes_analyst_signal_discovery as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "hermes-analyst-signal-discovery")
    monkeypatch.setattr(m.analyst_signals, "run_discovery", lambda dry_run, limit: _report(n, disabled=disabled))
    monkeypatch.setattr(sys, "argv", ["hermes_analyst_signal_discovery.py", "--run", "--json"])
    assert m.main() == 0
    out = H.check(tmp_path, "hermes-analyst-signal-discovery", run_id, produced=0 if disabled else n, expect=expect)
    if disabled:
        assert out["output_verdict"]["fatal"] == ["disabled"]


# ── hermes-governance-api ─────────────────────────────────────────────────────────────────────────────────────────
def test_hermes_governance_api_warm(monkeypatch, tmp_path):
    import hermes_governance_api as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "hermes-governance-api")
    monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache" / "hermes_governance_cache.json"))
    monkeypatch.setattr(m, "_governance_summary_compute", lambda: {"ok": True, "status": "ok"})
    assert m.main(["--warm"]) == 0
    assert json.loads((tmp_path / "cache" / "hermes_governance_cache.json").read_text())["status"] == "ok"
    H.check(tmp_path, "hermes-governance-api", run_id, produced=1, expect="produced")


def test_hermes_governance_api_failed_warm_is_a_fatal_skip(monkeypatch, tmp_path):
    import hermes_governance_api as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "hermes-governance-api")
    monkeypatch.setattr(m, "_governance_summary_compute", _boom)
    with pytest.raises(RuntimeError):
        m.main(["--warm"])
    H.check(tmp_path, "hermes-governance-api", run_id, produced=0, expect="empty_output")


def test_hermes_governance_api_dry_run_writes_no_receipt(monkeypatch, tmp_path):
    import hermes_governance_api as m

    H.attempt_env(monkeypatch, tmp_path, "hermes-governance-api")
    monkeypatch.setattr(m, "_governance_summary_compute", lambda: {"ok": True})
    assert m.main(["--warm", "--dry-run"]) == 0
    assert not (tmp_path / "data/runtime").exists()


# ── hermes-momentum-catalyst-scalp ────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def hmc(monkeypatch, tmp_path):
    import hermes_momentum_catalyst_researcher as m

    monkeypatch.setattr(m, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(m, "_load_env", lambda: None)
    monkeypatch.setattr(m, "_hot_research_on", lambda: False)
    monkeypatch.setattr(m, "research_ticker", lambda sym, **k: {"symbol": sym, "catalyst_type": "earnings",
                                                                "source_count": 1, "confidence": 0.5})
    return m


@pytest.mark.parametrize("cands,expect", [(["NOC", "LMT"], "produced"), ([], "empty_allowed")])
def test_hermes_momentum_catalyst_scalp(hmc, monkeypatch, tmp_path, cands, expect):
    run_id = H.attempt_env(monkeypatch, tmp_path, "hermes-momentum-catalyst-scalp")
    monkeypatch.setattr(hmc, "get_scalp_candidates", lambda max_tickers=15, read_errors=None: list(cands))
    assert hmc.main(["--source", "scalp", "--apply"]) == 0
    out = H.check(tmp_path, "hermes-momentum-catalyst-scalp", run_id, produced=len(cands), expect=expect)
    if cands:
        lines = list((tmp_path / "data/hermes/momentum_catalysts").glob("*_catalysts.jsonl"))[0].read_text()
        assert len(lines.splitlines()) == 2  # the records the count names were written
    else:
        assert out["output_verdict"]["empty_reason"] == "no_new_input"


def test_hermes_momentum_catalyst_scalp_candidate_read_failure_is_fatal(hmc, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "hermes-momentum-catalyst-scalp")

    def cands(max_tickers=15, read_errors=None):
        read_errors.append("scalp list unreadable")
        return []

    monkeypatch.setattr(hmc, "get_scalp_candidates", cands)
    assert hmc.main(["--source", "scalp", "--apply"]) == 0
    out = H.check(tmp_path, "hermes-momentum-catalyst-scalp", run_id, produced=0, expect="empty_output")
    assert out["output_verdict"]["why"] in ("fatal_skip", "receipt_status_failed")


# ── hermes-news-bridge ────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bridged,expect", [(3, "produced"), (0, "empty_allowed")])
def test_hermes_news_bridge(monkeypatch, tmp_path, bridged, expect):
    import hermes_news_bridge as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "hermes-news-bridge")
    monkeypatch.setattr(m, "run", lambda **k: {"candidates": 4, "bridged": bridged, "skipped_dup": 4 - bridged,
                                               "insert_errors": 0, "rows": []})
    assert m.main([]) == 0
    last = json.loads((tmp_path / "data/runtime/hermes_news_bridge_last.json").read_text())
    assert last["schema"] == "LaneRunReceipt@v1" and last["produced_count"] == bridged  # established path kept
    H.check(tmp_path, "hermes-news-bridge", run_id, produced=bridged, expect=expect)


def test_hermes_news_bridge_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    import hermes_news_bridge as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "hermes-news-bridge")
    monkeypatch.setattr(m, "run", _boom)
    assert m.main([]) == 1
    H.check(tmp_path, "hermes-news-bridge", run_id, produced=0, expect="empty_output")
