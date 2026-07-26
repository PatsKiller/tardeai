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


# ── V6 SAFETY: a missed plan is NO trade, never a manufactured one ──────────
def _svc():
    import shadow_decision_service as svc
    return svc


def test_fatn_defect_no_mechanics_at_distant_resistance():
    """$4.75 / zone-high $4.55 / resistance $6.76 must NOT produce current
    mechanics at 6.76 — the exact production defect."""
    svc = _svc()
    a = svc.assess_swing_entry(price=4.75, zone_low=4.30, zone_high=4.55,
                               stop=4.10, atr=0.25)
    assert a["entry_state"] == "MISSED_ENTRY"
    assert a["mechanics_current"] is False
    assert a["family_state"] == "REJECTED"
    bo = svc.assess_breakout_blueprint(symbol="FATN", price=4.75, atr=0.25,
                                       resistance=6.76, conn=None)
    assert bo.get("blueprint") is None, "a 42% trigger must never be a blueprint"
    ws = bo.get("watch_scenario")
    assert ws and ws["actionable"] is False and "FUTURE SCENARIO" in ws["note"]


def test_missed_entry_shows_no_current_mechanics_and_no_proposal():
    svc = _svc()
    a = svc.assess_swing_entry(price=10.0, zone_low=8.0, zone_high=8.5,
                               stop=7.5, atr=0.3)
    assert a["entry_state"] == "MISSED_ENTRY" and a["mechanics_current"] is False
    assert "Do not chase" in a["summary"]
    assert any(w["kind"] == "PULLBACK_REENTRY" and not w["actionable"]
               for w in a["watch_scenarios"])


def test_chase_tolerance_keeps_reference_mechanics():
    svc = _svc()
    a = svc.assess_swing_entry(price=8.58, zone_low=8.0, zone_high=8.5,
                               stop=7.5, atr=0.3)  # 0.9% above / 0.27 ATR
    assert a["entry_state"] == "WAIT_PULLBACK" and a["mechanics_current"] is True


def test_breakout_trigger_distance_limits():
    svc = _svc()
    far_pct = svc.assess_breakout_blueprint(symbol="X", price=100, atr=10,
                                            resistance=109, conn=None)  # 9% > 8%
    assert far_pct.get("blueprint") is None
    far_atr = svc.assess_breakout_blueprint(symbol="X", price=100, atr=2,
                                            resistance=105, conn=None)  # 2.5 ATR > 2
    assert far_atr.get("blueprint") is None


def test_in_zone_is_ready_and_below_stop_invalidated():
    svc = _svc()
    ok = svc.assess_swing_entry(price=8.2, zone_low=8.0, zone_high=8.5,
                                stop=7.5, atr=0.3)
    assert ok["entry_state"] == "READY_PULLBACK" and ok["family_state"] == "ELIGIBLE"
    dead = svc.assess_swing_entry(price=7.0, zone_low=8.0, zone_high=8.5,
                                  stop=7.5, atr=0.3)
    assert dead["entry_state"] == "INVALIDATED" and dead["mechanics_current"] is False


def test_no_auto_conversion_remains_in_source():
    src = (ROOT / "scripts" / "shadow_decision_service.py").read_text()
    assert "DETERMINISTIC_BREAKOUT_RECALC" not in src, \
        "the pullback→breakout auto-conversion must be gone"
    assert "never mutates into a different strategy" in src


# ── OVERSIGHT GATE: validator hard authority + review hierarchy ─────────────
def test_validator_rejects_the_fatn_fabrication():
    """The exact production numbers: $4.75 current, $6.76 entry / $5.94 stop /
    $8.40 target claimed as CURRENT mechanics → HARD FAIL."""
    import strategy_ticket_validator as stv
    r = stv.validate_ticket("FATN", "SWING",
                            {"structure": "TACTICAL_SWING", "entry_mode": "BREAKOUT",
                             "entry_state": "WAIT_BREAKOUT", "mechanics_current": True,
                             "entry_zone": [6.76, 7.03], "limit_price": 6.76,
                             "stop_price": 5.94, "targets": [8.40], "risk_reward": 2.0,
                             "proposal_tag": "old-pullback-tag"},
                            {"live_price": 4.75, "atr": 0.45, "symbol": "FATN"})
    assert r["state"] == "FAIL"
    assert any("FUTURE SCENARIO" in h or "exceeds" in h for h in r["hard_failures"])
    assert any("mutate" in h or "identity" in h or "inherits" in h for h in r["hard_failures"])
    assert r["recomputed"]["risk_reward"] == 2.0  # arithmetic itself was fine — proximity wasn't


def test_validator_recomputes_rr_and_ordering():
    import strategy_ticket_validator as stv
    bad_rr = stv.validate_ticket("X", "SWING",
                                 {"mechanics_current": True, "entry_mode": "PULLBACK",
                                  "entry_zone": [9.9, 10.1], "limit_price": 10.0,
                                  "stop_price": 9.0, "targets": [11.0], "risk_reward": 5.0},
                                 {"live_price": 10.0, "atr": 0.4})
    assert bad_rr["state"] == "FAIL" and any("R:R mismatch" in h for h in bad_rr["hard_failures"])
    bad_order = stv.validate_ticket("X", "SWING",
                                    {"mechanics_current": True, "entry_mode": "PULLBACK",
                                     "entry_zone": [9.9, 10.1], "limit_price": 10.0,
                                     "stop_price": 10.5, "targets": [11.0]},
                                    {"live_price": 10.0, "atr": 0.4})
    assert bad_order["state"] == "FAIL" and any("ordering" in h for h in bad_order["hard_failures"])


def test_coherent_arithmetic_is_never_promoted_past_a_quality_gate():
    # Under watch-quality-governance the quality gate is sovereign over valid
    # arithmetic: an arithmetically coherent, nearby ticket is still withheld
    # when the instrument is not quality-admitted. The arithmetic layer must
    # nonetheless recognise the ticket as coherent — every hard failure here is
    # a quality-admission reason, none is an arithmetic/ordering failure — and
    # the ticket/facts hashes must still be produced.
    import strategy_ticket_validator as stv
    r = stv.validate_ticket("X", "SWING",
                            {"mechanics_current": True, "entry_mode": "PULLBACK",
                             "entry_state": "READY_PULLBACK",
                             "entry_zone": [9.8, 10.2], "limit_price": 10.0,
                             "stop_price": 9.4, "targets": [11.2], "risk_reward": 2.0},
                            {"live_price": 10.0, "atr": 0.4})
    assert r["ticket_hash"] and r["facts_hash"]
    assert all(str(h).startswith("quality admission") for h in r["hard_failures"]), r["hard_failures"]


def test_no_model_can_override_deterministic_fail():
    import strategy_ticket_reconciler as rec
    unanimous = {k: {"verdict": "PASS", "provider_family": f, "ticket_hash_reviewed": "h"}
                 for k, f in (("local", "LOCAL_OLLAMA"), ("grok", "XAI"), ("chatgpt", "OPENAI"))}
    r = rec.reconcile({"state": "FAIL", "hard_failures": ["x"], "ticket_hash": "h"},
                      unanimous, {"verdict": "PASS"})
    assert r["state"] == "DETERMINISTIC_FAIL"
    assert r["proposal_allowed"] is False and r["display_mechanics"] is False


_ADMITTED = {"state": "ADMITTED", "new_entry_allowed": True, "reasons": []}


def test_changed_ticket_hash_voids_reviews():
    import strategy_ticket_reconciler as rec
    r = rec.reconcile({"state": "PASS", "ticket_hash": "NEW", "quality_admission": _ADMITTED},
                      {"local": {"verdict": "PASS", "provider_family": "LOCAL_OLLAMA",
                                 "ticket_hash_reviewed": "OLD"}},
                      current_ticket_hash="CHANGED")
    assert r["state"] == "STALE_AFTER_REVIEW"
    r2 = rec.reconcile({"state": "PASS", "ticket_hash": "h", "quality_admission": _ADMITTED},
                       {"local": {"verdict": "REJECT", "provider_family": "LOCAL_OLLAMA",
                                  "ticket_hash_reviewed": "OTHER"}})
    assert r2["state"] == "REVIEW_UNAVAILABLE", "a stale review must not count"


def test_single_lane_is_never_consensus():
    import strategy_ticket_reconciler as rec
    r = rec.reconcile({"state": "PASS", "ticket_hash": "h", "quality_admission": _ADMITTED},
                      {"grok": {"verdict": "PASS", "provider_family": "XAI",
                                "ticket_hash_reviewed": "h"}})
    assert r["state"] == "VERIFIED_LOCAL_ONLY" and r["proposal_allowed"] is False


def test_local_critic_is_structurally_local_only():
    src = (ROOT / "scripts" / "local_llm.py").read_text()
    fn = src.split("def generate_local_only")[1]
    for banned in ("openai", "anthropic", "fallback", "api.openai", "oauth"):
        assert banned not in fn.lower(), f"local-only path references {banned}"
    rev = (ROOT / "scripts" / "strategy_ticket_review.py").read_text()
    assert "generate_local_only" in rev


def test_action_policy_withholds_ready_without_release_gate():
    src = (ROOT / "scripts" / "decision_action_policy.py").read_text()
    assert "proposal_allowed" in src and "verification release gate" in src


def test_premium_fails_closed_and_needs_typed_confirmation():
    import premium_ticket_review as ptr
    est = ptr.estimate("FATN", "abc")
    assert est["available"] is False and "PREMIUM_NOT_CONFIGURED" in est["reason"]
    r = ptr.run("FATN", "abc", "yes please")
    assert r["ok"] is False


# ── UNIVERSAL RELEASE GATE: presentation invariants ─────────────────────────
def test_presentation_no_verified_ticket_no_mechanics():
    import operator_presentation as op
    legacy = op.build({"plan_families": {}}, {})
    assert legacy["verification_state"] == "UNVERIFIED_LEGACY"
    assert legacy["display_current_mechanics"] is False
    assert all(v is None for v in legacy["mechanics"].values())


def test_presentation_blocked_and_preferred_and_missed_suppress_mechanics():
    import operator_presentation as op
    base_cap = {"ticket_validation": {"state": "PASS", "ticket_hash": "h"},
                "limit_price": 10, "stop_price": 9, "targets": [12]}
    blocked = op.build({"current_actionable_plan": dict(base_cap),
                        "ticket_review": {"reconciled": {"state": "VERIFIED_FREE_REVIEW"}},
                        "event_state": {"earnings": {"state": "EVENT_BLOCKED"}},
                        "plan_families": {}}, {"state": "BLOCKED"})
    assert blocked["display_current_mechanics"] is False and blocked["header_state"] == "BLOCKED"
    ntp = op.build({"current_actionable_plan": dict(base_cap),
                    "ticket_review": {"reconciled": {}},
                    "plan_families": {"no_trade": {"preferred": True}}}, {})
    assert ntp["display_current_mechanics"] is False and ntp["header_state"] == "NO TRADE"
    missed = op.build({"current_actionable_plan": dict(base_cap),
                       "ticket_review": {"reconciled": {}},
                       "plan_families": {"swing": {"structures": [{"entry_state": "MISSED_ENTRY"}]}}}, {})
    assert missed["display_current_mechanics"] is False


def test_presentation_held_requires_position_management():
    import operator_presentation as op
    held = op.build({"current_actionable_plan": {"ticket_validation": {"state": "PASS"}},
                     "ticket_review": {"reconciled": {"proposal_allowed": True}},
                     "ownership": {"held": True}, "plan_families": {}},
                    {"state": "READY", "allowed": True, "action": "PROPOSE_ENTRY"})
    assert held["header_state"] == "MANAGE POSITION"
    assert held["display_current_mechanics"] is False and held["proposal_allowed"] is False


def test_presentation_header_governs_family_tile():
    import operator_presentation as op
    r = op.build({"current_actionable_plan": None,
                  "ticket_review": {"reconciled": {"state": "DETERMINISTIC_FAIL"},
                                    "tickets_validated": [{"state": "FAIL"}]},
                  "plan_families": {"swing": {"state": "ELIGIBLE",
                                              "structures": [{"action_state": "READY"}]}}}, {})
    assert r["header_state"] != "READY"
    assert "swing" in r["tile_overrides"], "READY tile must be overridden when header is not READY"


def test_presentation_verified_path_allows_mechanics():
    import operator_presentation as op
    r = op.build({"current_actionable_plan": {"ticket_validation": {"state": "PASS", "ticket_hash": "h"},
                                              "limit_price": 10, "stop_price": 9.4,
                                              "targets": [11.2], "risk_reward": 2.0},
                  "ticket_review": {"reconciled": {"state": "VERIFIED_FREE_REVIEW",
                                                   "proposal_allowed": True}},
                  "plan_families": {}},
                 {"state": "READY", "allowed": True, "action": "PROPOSE_ENTRY"})
    assert r["verification_state"] == "VERIFIED"
    assert r["display_current_mechanics"] is True and r["proposal_allowed"] is True
    assert r["header_state"] == "READY"
