"""Watch Decision Desk V5 — refresh-semantics tests (Section 12 core).

Pure tests always run; DB-backed tests skip cleanly when PostgreSQL is not
reachable (TRADE_AI_CI=1 source-only CI stays green).
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(1, str(ROOT / "scripts" / "lib"))

import watch_decision_refresh as wdr  # noqa: E402


def _db():
    try:
        c = wdr._conn()
        c.cursor().execute("SELECT 1")
        return c
    except Exception:
        return None


needs_db = pytest.mark.skipif(_db() is None, reason="PostgreSQL not reachable (source-only CI)")


# ── pure: scope / tier / policy invariants ───────────────────────────────────
def test_scopes_and_tiers_are_the_contract():
    assert wdr.SCOPES == ("INPUTS_ONLY", "AFFECTED_DIMENSIONS", "FULL_STRATEGY")
    assert wdr.TIERS == ("LOCAL_QUANT", "STANDARD_BLIND", "PREMIUM_REVIEW")


def test_reason_to_dimension_mapping_is_narrow():
    """A technicals invalidation must NOT drag fundamentals/options rebuild inputs."""
    assert wdr.REASON_TO_DIMENSION["TECHNICALS_STALE"] == "technicals"
    assert wdr.REASON_TO_DIMENSION["FUNDAMENTALS_CHANGED"] == "fundamentals"
    assert wdr.REASON_TO_DIMENSION["EARNINGS_CHANGED"] == "events"
    assert wdr.REASON_TO_DIMENSION["OWNERSHIP_CHANGED"] == "ownership"
    assert "TTL_EXPIRED" not in wdr.REASON_TO_DIMENSION  # TTL → rebuild, not an input refetch


def test_policy_yaml_loads_versioned():
    pol = wdr.load_policy()
    assert pol.get("version"), "refresh policy must be versioned"
    tiers = pol.get("tiers") or {}
    for t in ("P0", "P1", "P2", "P3"):
        assert t in tiers, f"tier {t} missing from policy"
    assert tiers["P0"]["full_local_packet_max_minutes"] <= tiers["P2"]["full_local_packet_max_minutes"]


def test_premium_gate_fails_closed_without_registry():
    g = wdr.premium_gate(3, confirmed=False)
    assert g["allowed"] is False
    assert "PREMIUM_NOT_CONFIGURED" in g["reason"]
    # even a 'confirmed' request cannot run with no enabled provider
    g2 = wdr.premium_gate(3, confirmed=True)
    assert g2["allowed"] is False


def test_premium_never_scheduled(monkeypatch):
    """The scheduler must never plan PREMIUM_REVIEW work."""
    import watch_decision_scheduler as sched
    src = open(ROOT / "scripts" / "watch_decision_scheduler.py").read()
    assert "PREMIUM_REVIEW" not in src.replace("never scheduled", "").replace(
        "PREMIUM is never", ""), "scheduler source must not enqueue PREMIUM_REVIEW"


def test_enqueue_rejects_bad_scope_and_tier():
    assert wdr.enqueue_run(["CECO"], scope="EVERYTHING")["ok"] is False
    assert wdr.enqueue_run(["CECO"], analysis_tier="MEGA")["ok"] is False
    assert wdr.enqueue_run([])["ok"] is False


def test_premium_tier_enqueue_refused_without_provider():
    r = wdr.enqueue_run(["CECO"], analysis_tier="PREMIUM_REVIEW")
    assert r["ok"] is False and "PREMIUM" in r["error"]


# ── DB-backed: idempotency, freshness contract, honest labels ────────────────
@needs_db
def test_enqueue_creates_run_and_job_then_duplicate_skips():
    r1 = wdr.enqueue_run(["ZZV5TEST"], scope="FULL_STRATEGY", analysis_tier="LOCAL_QUANT",
                         requested_by="pytest", spawn_workers=False)
    assert r1["ok"] and r1["queued"] == 1
    r2 = wdr.enqueue_run(["ZZV5TEST"], scope="FULL_STRATEGY", analysis_tier="LOCAL_QUANT",
                         requested_by="pytest", spawn_workers=False)
    assert r2["ok"] and r2["queued"] == 0 and r2["skipped_locked"] == 1
    conn = wdr._conn(); cur = conn.cursor()
    cur.execute("""DELETE FROM watch_decision_refresh_jobs WHERE symbol='ZZV5TEST'""")
    cur.execute("""DELETE FROM watch_decision_refresh_runs
                   WHERE run_id IN (%s,%s)""", (r1["run_id"], r2["run_id"]))
    conn.commit()


@needs_db
def test_freshness_contract_has_timestamps_in_every_state():
    """Section 6D/8: a STALE symbol still exposes last_strategy_build_at; the
    contract never replaces timestamps with a bare needs-refresh marker."""
    conn = wdr._conn(); cur = conn.cursor()
    cur.execute("""SELECT symbol FROM decision_packets WHERE superseded_by IS NULL LIMIT 5""")
    syms = [r[0] for r in cur.fetchall()]
    if not syms:
        pytest.skip("no live packets")
    for s in syms:
        f = wdr.build_freshness(s, conn)["freshness"]
        assert f["overall_state"] in ("CURRENT", "DUE_SOON", "STALE", "REFRESHING", "FAILED", "PARTIAL")
        assert f["last_strategy_build_at"], f"{s}: build timestamp missing in state {f['overall_state']}"
        assert f["valid_until"], f"{s}: valid_until missing"
        assert f["policy_version"]
        assert f["priority_tier"] in ("P0", "P1", "P2", "P3")


@needs_db
def test_local_quant_packets_record_zero_lanes():
    """Every COMPLETE LOCAL_QUANT job must have lane_calls == 0 (no model calls)."""
    conn = wdr._conn(); cur = conn.cursor()
    cur.execute("""SELECT count(*) FROM watch_decision_refresh_jobs
                   WHERE analysis_tier='LOCAL_QUANT' AND state='COMPLETE' AND lane_calls > 0""")
    assert cur.fetchone()[0] == 0


@needs_db
def test_input_refresh_endpoint_separation():
    """The generic watchlist refresh path must not write decision_packets: no
    packet row may carry an origin from the enrichment endpoint."""
    conn = wdr._conn(); cur = conn.cursor()
    cur.execute("""SELECT count(*) FROM decision_runs WHERE origin='wl_refresh'""")
    assert cur.fetchone()[0] == 0


# ── frontend label honesty (source-level guards) ─────────────────────────────
def test_frontend_refresh_labels_are_honest():
    band = (ROOT / "apps/command-center-v3/src/components/DecisionPacketBand.tsx").read_text()
    assert "Refresh Inputs" in band, "generic endpoint must be labelled Refresh Inputs"
    assert "onRefreshStrategy" in band, "strategy CTA must route to the orchestrator"
    hub = (ROOT / "apps/command-center-v3/src/pages/WatchlistHub.tsx").read_text()
    assert "/api/v2/watch/decision/refresh" in (ROOT / "apps/command-center-v3/src/lib/watchV5.ts").read_text()
    assert "watchV5Enabled()" in hub and "server owns" in hub.lower() or "SERVER owns" in hub


def test_stale_card_keeps_build_timestamp():
    pres = (ROOT / "apps/command-center-v3/src/lib/operatorDecisionCard.ts").read_text()
    assert "NEVER hidden" in pres or "stampLine, 'STALE'" in pres, \
        "stale presentation must keep the build timestamp"
    assert "inputsStale ? 'needs refresh' : (stampLine" not in pres, \
        "the old timestamp-suppression branch is back"


def test_legacy_grid_absent_when_packet_leads():
    card = (ROOT / "apps/command-center-v3/src/components/WatchlistCardV4.tsx").read_text()
    assert "!(hasPacket && watchV5Enabled())" in card, \
        "legacy plan/sizing grid must be removed (not dimmed) when a packet exists under V5"


# ── deterministic thesis engine (Section 5A) ─────────────────────────────────
def test_thesis_engine_deterministic_and_stateful():
    import deterministic_thesis as dth
    facts = {"fundamentals": {"eps_past_5y": 20, "sales_past_5y": 15, "profit_margin_pct": 18,
                              "roic_pct": 22, "total_debt_equity": 0.3, "current_ratio": 2.1,
                              "peg": 1.1, "short_float_pct": 2.0, "inst_own_pct": 70},
             "live_price": 100.0, "sma50": 90.0, "rsi": 60, "bars_used": 250}
    a = dth.evaluate(facts, "STOCK"); b = dth.evaluate(dict(facts), "STOCK")
    assert a == b, "engine must be deterministic"
    assert a["thesis_state"] == "CONSTRUCTIVE"
    assert a["evidence_coverage_pct"] >= 80
    assert all("factor" in f and "evidence" in f for f in a["factors"])


def test_thesis_engine_never_reads_verdict_fields():
    src = (ROOT / "scripts" / "deterministic_thesis.py").read_text()
    for banned in ('get("recom', "get('recom", 'get("analyst', "get('analyst",
                   'get("cio_verdict', 'get("grok_verdict', 'get("chatgpt_verdict',
                   '"recom_score"', '"analyst_rating"'):
        assert banned not in src, f"engine must not access pre-chewed field via {banned!r}"


def test_thesis_engine_instrument_awareness():
    import deterministic_thesis as dth
    etf = dth.evaluate({"quote_type": "ETF", "live_price": 50, "sma50": 45, "rsi": 55}, "ETF")
    assert etf["instrument_class"] == "etf_fund"
    pre = dth.evaluate({"fundamentals": {"profit_margin_pct": -30, "ps": 20,
                                         "eps_past_5y": 10, "sales_past_5y": 40},
                        "live_price": 10, "sma50": 12, "rsi": 40, "bars_used": 300}, "STOCK")
    assert pre["instrument_class"] == "pre_profit"
    assert pre["thesis_state"] in ("NEUTRAL", "SPECULATIVE_CONSTRUCTIVE", "FUNDAMENTALLY_UNATTRACTIVE")
    empty = dth.evaluate({}, None)
    assert empty["thesis_state"] == "INSUFFICIENT_EVIDENCE"


def test_thesis_engine_rejects_misparsed_magnitudes():
    import deterministic_thesis as dth
    r = dth.evaluate({"fundamentals": {"sales_qoq": 164877.0, "profit_margin_pct": 5},
                      "live_price": 10, "sma50": 9, "rsi": 55, "bars_used": 300}, "STOCK")
    g = next((x for x in r["factors"] if x["factor"] == "growth"), None)
    assert g is None, "an implausible growth magnitude must be excluded, not averaged"
    assert any("growth" in m for m in r["missing_evidence"])


def test_thesis_engine_confidence_is_coverage_not_prediction():
    import deterministic_thesis as dth
    r = dth.evaluate({}, None)
    assert "not outcome probability" in r["confidence_basis"]
