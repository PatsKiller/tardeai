"""PR1 Decision Truth & Identity — adversarial acceptance (CDQ).

Covers the PR1-scoped CDQ gates: actionability (stale never ACT NOW),
no-objective trim => $0, exact digest pair 409, canonical re-entry lifecycle,
scenario-only trim $0 (CDQ-27), phase-aware CDQ profile semantics
(NOT_IN_SCOPE never counts as PASS; required gates must PASS), plus the
final-closure invariants: Telegram actionability parity, Command Center
fallback fail-closed, derived ranking, re-entry idempotence, SIZING_UNAVAILABLE
target truth, and topology provenance precision.

No broker, no network. Telegram classify/format are exercised in-process only
(REAL_TELEGRAM_SENDS: 0).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_decision_quality import (  # noqa: E402
    evaluate_cdq27_scenario_only_zero,
    evaluate_pr1_actionability,
    evaluate_pr1_digest_409,
    evaluate_pr1_reentry_canonical,
    evaluate_pr1_sizing_zero,
    evaluate_pr1_standing_current_parity,
    evaluate_profile,
)
from scripts.lib import cio_capital_plan as cp  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# PR1_ACTIONABILITY — stale / risk text can never render ACT NOW
# ─────────────────────────────────────────────────────────────────────────────

def test_actionability_risk_text_never_act_now():
    status, violations = evaluate_pr1_actionability({
        "risk": "concentration > fire",
        "act_now": False,
        "action_label": None,
    })
    assert status == "PASS", violations
    # Even a screaming breach is not ACT NOW unless act_now/label says so.
    status, violations = evaluate_pr1_actionability({
        "risk": "concentration > fire",
        "act_now": False,
        "action_label": "REVIEW",
    })
    assert status == "PASS", violations


def test_actionability_act_now_maps_high():
    status, violations = evaluate_pr1_actionability({"act_now": True})
    assert status == "PASS", violations
    status, violations = evaluate_pr1_actionability({"action_label": "ACT_NOW"})
    assert status == "PASS", violations


def test_actionability_stale_is_not_high():
    status, violations = evaluate_pr1_actionability({
        "risk": "concentration > fire",
        "action_label": "STALE_REFRESH_REQUIRED",
        "act_now": False,
    })
    assert status == "PASS", violations


def test_actionability_stale_overrides_act_now():
    # Contradiction: act_now=True (or ACT_NOW label) must NOT render ACT NOW when
    # the freshness/conflict state blocks it (P0-3 fail-closed).
    status, violations = evaluate_pr1_actionability({
        "act_now": True, "action_label": "STALE_REFRESH_REQUIRED",
    })
    assert status == "PASS", violations
    status, violations = evaluate_pr1_actionability({
        "act_now": True, "freshness": "STALE",
    })
    assert status == "PASS", violations
    status, violations = evaluate_pr1_actionability({
        "act_now": True, "action_label": "DATA_CONFLICT",
    })
    assert status == "PASS", violations
    status, violations = evaluate_pr1_actionability({
        "action_label": "ACT_NOW", "freshness": "EXPIRED",
    })
    assert status == "PASS", violations


# ─────────────────────────────────────────────────────────────────────────────
# PR1_SIZING_ZERO — no objective => $0
# ─────────────────────────────────────────────────────────────────────────────

def test_sizing_zero_below_policy_fire():
    positions = [
        {"symbol": "V", "market_value_usd": 40_000.0},
        {"symbol": "SPCX", "market_value_usd": 11_000.0},
        {"symbol": "DXCM", "market_value_usd": 8_000.0},
        {"symbol": "AMANX", "market_value_usd": 2_000.0},
    ]
    status, violations = evaluate_pr1_sizing_zero(
        positions,
        portfolio_value=500_000.0,
        policy_cap_pct=12.0,
        fire_pct=16.5,
    )
    assert status == "PASS", violations


def test_sizing_zero_above_fire_skipped_not_penalized():
    positions = [
        {"symbol": "BIG", "market_value_usd": 90_000.0},  # 18% > fire 16.5
    ]
    # Above fire has a real objective; the no-objective evaluator must not
    # flag it (it skips) nor crash.
    status, _ = evaluate_pr1_sizing_zero(
        positions, portfolio_value=500_000.0, policy_cap_pct=12.0, fire_pct=16.5,
    )
    assert status == "PASS"


# ─────────────────────────────────────────────────────────────────────────────
# PR1_DIGEST_409 — exact pair required
# ─────────────────────────────────────────────────────────────────────────────

def test_digest_missing_and_wrong_rejected():
    status, violations = evaluate_pr1_digest_409(
        catalog_digest="1e855bdb25f63ceb", supplied_digest=None,
    )
    assert status == "PASS", violations  # missing digest is rejected (fail-closed)

    status, violations = evaluate_pr1_digest_409(
        catalog_digest="1e855bdb25f63ceb", supplied_digest="deadbeef",
    )
    assert status == "PASS", violations  # wrong digest is rejected


def test_digest_exact_pair_accepted():
    # Exact pair is fine — the evaluator only reports when a mismatch is wrongly
    # accepted. Empty catalog digest (LEGACY) must NOT be treated as DIGEST_CAPABLE.
    from scripts.api_v3_cio import _digests_match
    assert _digests_match("1e855bdb25f63ceb", "1e855bdb25f63ceb") is True
    assert _digests_match("", "") is True  # legacy decision-id-only


# ─────────────────────────────────────────────────────────────────────────────
# PR1_REENTRY_CANONICAL — READY_TO_REVIEW != RE_ENTER
# ─────────────────────────────────────────────────────────────────────────────

def test_reentry_readiness_never_reenter():
    status, violations = evaluate_pr1_reentry_canonical()
    assert status == "PASS", violations


def test_reentry_lifecycle_has_terminal_reenter():
    from scripts.lib.cio_decision_semantics import REENTRY_LIFECYCLE
    assert REENTRY_LIFECYCLE[-1] == "RE_ENTER"


def test_reentry_stance_for_ready_to_review_is_review():
    from scripts.lib.cio_decision_semantics import stance_from_queue_item
    assert stance_from_queue_item({"symbol": "NVDA", "state": "READY TO REVIEW"}) == "REVIEW"
    assert stance_from_queue_item({"symbol": "NVDA", "state": "NEAR ENTRY"}) == "REVIEW"


def test_reentry_label_and_why_bypass_never_reenter():
    # P0-1: "Re-enter" in directive_label / note / why_now is non-authoritative
    # below GOVERNED_ELIGIBLE. Only explicit verdict=RE_ENTER grants RE_ENTER.
    from scripts.lib.cio_decision_semantics import (
        resolve_display_stance,
        stance_from_queue_item,
    )
    assert stance_from_queue_item({
        "symbol": "ADBE", "state": "READY TO REVIEW", "directive_label": "Re-enter ADBE",
    }) == "REVIEW"
    assert stance_from_queue_item({
        "symbol": "ADBE", "state": "NEAR ENTRY", "note": "Re-enter",
    }) == "REVIEW"
    assert stance_from_queue_item({
        "symbol": "ADBE", "state": "OVERSOLD REVIEW", "directive_label": "REENTER",
    }) == "REVIEW"
    assert resolve_display_stance("REVIEW", "ready to re-enter ADBE") == "REVIEW"
    assert resolve_display_stance("REVIEW", "consider re-enter on trigger") == "REVIEW"
    # Explicit governed verdict still wins.
    assert stance_from_queue_item({
        "symbol": "ADBE", "state": "READY TO REVIEW", "verdict": "RE_ENTER",
    }) == "RE_ENTER"


def test_standing_current_parity_evaluator():
    status, violations = evaluate_pr1_standing_current_parity()
    assert status == "PASS", violations


# ─────────────────────────────────────────────────────────────────────────────
# CDQ-27 — scenario-only trim contributes $0 to capital sources
# ─────────────────────────────────────────────────────────────────────────────

def test_cdq27_scenario_only_trim_zero_to_sources():
    positions = [
        cp.normalize_position(
            {"symbol": "V", "market_value": 40_000.0, "account": "schwab_rollover_ira"},
            500_000.0,
        ),
    ]
    queue = {"items": [{"symbol": "V", "verdict": "TRIM", "source": "cio"}]}
    status, violations = evaluate_cdq27_scenario_only_zero(positions, queue)
    assert status == "PASS", violations


def test_sizing_exception_fails_closed_no_10pct(monkeypatch):
    """P0-2: a TRIM sizing exception must not resurrect the -10% heuristic."""
    import scripts.lib.cio_institutional_sizing as sizing

    def _boom(**kwargs):
        raise RuntimeError("injected sizing failure")

    monkeypatch.setattr(sizing, "size_decision", _boom)
    plan = cp.build_capital_plan(
        portfolio_value=500_000.0,
        cash_total=100_000.0,
        positions=[{
            "symbol": "V", "market_value": 40_000.0,
            "account": "schwab_rollover_ira", "weight_pct": 8.0,
        }],
        queue={"items": [{"symbol": "V", "verdict": "TRIM", "directive_label": "Advisory TRIM — V"}]},
        redeploy_open_events=[],
    )
    dec = next(d for d in plan["position_decisions"] if d["symbol"] == "V")
    assert dec["recommended_delta_usd"] == 0.0
    assert dec["sizing_method"] == "SIZING_UNAVAILABLE"
    assert dec["stance_code"] == "REVIEW"
    # Scenario amount retained, but not a recommendation.
    scenario = (dec.get("sizing") or {}).get("scenario_trim_usd")
    assert scenario == round(40_000.0 * 0.10, 2)
    # No prospective trim capital from the failed sizing.
    src = plan.get("capital_sources") or {}
    assert float(src.get("trims_usd") or 0.0) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Phase-aware CDQ profile semantics
# ─────────────────────────────────────────────────────────────────────────────

def _all_required_pass():
    return {
        "PR1_STANDING_CURRENT_PARITY": "PASS",
        "PR1_ACTIONABILITY": "PASS",
        "PR1_SIZING_ZERO": "PASS",
        "PR1_DIGEST_409": "PASS",
        "PR1_REENTRY_CANONICAL": "PASS",
        "CDQ-27": "PASS",
        "CDQ-25": "NOT_IN_SCOPE",
        "CDQ-26": "NOT_IN_SCOPE",
        "CAPITAL_ACT_NOW_ZERO": "NOT_IN_SCOPE",
        "CDQ-28": "NOT_IN_SCOPE",
        "CDQ-29": "NOT_IN_SCOPE",
    }


def test_profile_passes_when_required_pass_and_rest_not_in_scope():
    r = evaluate_profile("PR1_DECISION_TRUTH", _all_required_pass())
    assert r["pass"] is True
    assert r["required_fail"] == []
    assert r["contract_fail"] == []


def test_not_in_scope_does_not_satisfy_required_gate():
    results = _all_required_pass()
    results["PR1_SIZING_ZERO"] = "NOT_IN_SCOPE"
    r = evaluate_profile("PR1_DECISION_TRUTH", results)
    assert r["pass"] is False
    assert "PR1_SIZING_ZERO:NOT_IN_SCOPE" in r["required_fail"]


def test_contract_only_fail_fails_profile():
    results = _all_required_pass()
    results["CDQ-25"] = "FAIL"
    r = evaluate_profile("PR1_DECISION_TRUTH", results)
    assert r["pass"] is False
    assert "CDQ-25:FAIL" in r["contract_fail"]


def test_not_in_scope_is_never_counted_as_pass():
    r = evaluate_profile("PR1_DECISION_TRUTH", _all_required_pass())
    # NOT_IN_SCOPE gates are explicitly not pass-counted.
    assert r["not_in_scope_counts_as_pass"] is False
    assert r["gates"]["CDQ-28"] == "NOT_IN_SCOPE"


def test_unknown_profile_raises():
    import pytest
    with pytest.raises(ValueError):
        evaluate_profile("NOPE", {})


# ─────────────────────────────────────────────────────────────────────────────
# CDQ-25/26 — topology audit fail-closed offline
# ─────────────────────────────────────────────────────────────────────────────

def test_topology_audit_offline_is_not_run_fail_closed():
    from scripts.lib.cio_topology_audit import audit_topology
    r = audit_topology("6f7009794e5178a7926f5b1c84ae16d0ee7b2bc6", offline=True)
    assert r["ok"] is False
    assert r["status"] == "NOT_RUN"
    assert r["offline"] is True


def test_topology_audit_resolve_checkout_missing_path():
    from scripts.lib.cio_topology_audit import resolve_checkout
    r = resolve_checkout("/nonexistent/path/does/not/exist")
    assert r["exists"] is False
    assert r["head_sha"] == ""


def test_topology_audit_deprecated_markers_present():
    from scripts.lib.cio_topology_audit import DEPRECATED_MARKERS
    assert DEPRECATED_MARKERS
    assert any("agent-jobs/" in m or "/tmp/" in m for m in DEPRECATED_MARKERS)


def test_topology_audit_rebuild_tree_is_deprecated_not_approved():
    from scripts.lib.cio_topology_audit import (
        APPROVED_ROOT_DEFAULT,
        DEPRECATED_MARKERS,
        DEPRECATED_ROOTS,
        _is_deprecated_path,
    )
    assert "/home/johnclaw/trade-ai-v12-rebuild" in DEPRECATED_ROOTS
    assert "/home/johnclaw/trade-ai-v12-rebuild" not in APPROVED_ROOT_DEFAULT
    assert _is_deprecated_path(
        "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild",
        DEPRECATED_ROOTS,
        DEPRECATED_MARKERS,
    ) is True


def test_topology_audit_deprecated_root_flagged_even_on_sha_match():
    from scripts.lib.cio_topology_audit import _classify
    # A deprecated root must be flagged even if its SHA matches the expected one.
    v = _classify(
        path="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild",
        root="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild",
        head="6f7009794e5178a7926f5b1c84ae16d0ee7b2bc6",
        expected="6f7009794e5178a7926f5b1c84ae16d0ee7b2bc6",
        approved_roots=("/home/johnclaw/trade-ai-releases/portfolio-server",),
        deprecated_roots=("/home/johnclaw/trade-ai-v12-rebuild",),
        deprecated_markers=("/tmp/",),
    )
    assert v is not None
    assert v["deprecated"] is True


# ─────────────────────────────────────────────────────────────────────────────
# PR1 final closure — Telegram parity, fallback fail-closed, derived ranking,
# re-entry idempotence, SIZING_UNAVAILABLE target truth, topology provenance
# ─────────────────────────────────────────────────────────────────────────────

def test_telegram_actionability_parity_fixtures():
    """P0-1: Telegram shares the web/backend canonical actionability semantics."""
    from scripts.lib.cio_alex_telegram import (
        classify_actionability,
        format_cio_message,
    )

    # act_now=True + DATA_CONFLICT → DATA CONFLICT / no MY CALL
    c = classify_actionability({"stance_code": "RE_ENTER", "act_now": True,
                                "action_label": "DATA_CONFLICT"})
    assert c["act_now"] is False
    assert c["actionability"] == "DATA_CONFLICT"
    body = format_cio_message({"stance_code": "RE_ENTER", "symbol": "X",
                               "act_now": True, "action_label": "DATA_CONFLICT",
                               "recommended_delta_usd": 0.0})
    assert "MY CALL" not in body

    # act_now=True + REVALIDATE → REVALIDATE / no MY CALL
    c = classify_actionability({"stance_code": "TRIM", "act_now": True,
                                "action_label": "REVALIDATE"})
    assert c["act_now"] is False
    assert c["actionability"] == "STALE_REFRESH_REQUIRED"

    # act_now=True + STALE → REVALIDATE / no MY CALL
    c = classify_actionability({"stance_code": "TRIM", "act_now": True,
                                "freshness": "STALE"})
    assert c["act_now"] is False
    assert c["current_action"] in ("REVALIDATE", "WAIT")

    # RE_ENTER + no explicit act_now → WAIT/REVIEW, not ACT NOW
    c = classify_actionability({"stance_code": "RE_ENTER",
                                "recommended_delta_usd": 5000.0})
    assert c["act_now"] is False
    body = format_cio_message({"stance_code": "RE_ENTER", "symbol": "X",
                               "recommended_delta_usd": 5000.0,
                               "why_now": "standing re-enter"})
    assert "MY CALL" not in body

    # fresh RE_ENTER + act_now=True → ACT NOW
    c = classify_actionability({"stance_code": "RE_ENTER", "act_now": True,
                                "recommended_delta_usd": 5000.0})
    assert c["act_now"] is True
    body = format_cio_message({"stance_code": "RE_ENTER", "symbol": "X",
                               "act_now": True, "recommended_delta_usd": 5000.0,
                               "why_now": "fresh re-enter"})
    assert "MY CALL" in body


def test_command_center_fallback_fail_closed(monkeypatch):
    """P0-2: sanitizer-exception fallback uses the canonical classifier."""
    import scripts.lib.cio_decision_semantics as sem
    import scripts.lib.cio_command_center as cc

    def _boom(*a, **k):
        raise RuntimeError("injected sanitizer failure")

    monkeypatch.setattr(sem, "sanitize_decisions_now", _boom)
    stale_conflict = {
        "symbol": "SCHD",
        "why_now": "Advisory TRIM — SCHD",
        "risk": "concentration > fire",
        "recommended_delta_usd": -44000.0,
        "act_now": True,
        "action_label": "DATA_CONFLICT",
        "freshness": "STALE",
        "stance_code": "TRIM",
    }
    out = cc.build_cio_now(position_decisions=[stale_conflict],
                           portfolio_value=1_000_000.0)
    cards = out["decisions"]
    card = next(c for c in cards if c["symbol"] == "SCHD")
    assert card["urgency"] == "medium"  # blocked, never high
    from scripts.lib.cio_decision_semantics import canonical_act_now
    act_now, blocking = canonical_act_now(card)
    assert act_now is False
    assert blocking == "DATA_CONFLICT"
    assert card.get("freshness") == "STALE"  # freshness preserved through fallback


def test_derived_actionability_owns_priority(monkeypatch):
    """P0-3: sort + Material Today use derived action, not raw act_now."""
    from scripts.lib.cio_command_center import _actionability_urgency, _canonical_action
    for blocked in (
        {"freshness": "STALE"},
        {"freshness": "EXPIRED"},
        {"action_label": "DATA_CONFLICT"},
        {"action_label": "REVALIDATE"},
        {"action_label": "STALE_REFRESH_REQUIRED"},
    ):
        d = {"act_now": True, "action_label": "ACT_NOW", **blocked}
        act_now, state = _canonical_action(d)
        assert act_now is False, d
        assert state is not None
        assert _actionability_urgency(d) == "medium"
    assert _actionability_urgency({"act_now": True}) == "high"
    assert _actionability_urgency({"act_now": True, "action_label": "ACT_NOW"}) == "high"


def test_stale_act_now_ranked_below_fresh(monkeypatch):
    """P0-3: a stale act_now=True record may stay material but not ACT-NOW tier."""
    import scripts.lib.cio_command_center as cc
    stale = {
        "symbol": "STALE1", "stance_code": "TRIM",
        "why_now": "Advisory TRIM — STALE1 concentration fire",
        "risk": "concentration > fire",
        "recommended_delta_usd": 900000.0,
        "act_now": True, "action_label": "ACT_NOW", "freshness": "STALE",
    }
    fresh = {
        "symbol": "FRESH1", "stance_code": "ADD",
        "why_now": "buy signal",
        "recommended_delta_usd": 1.0,
        "act_now": True, "action_label": "ACT_NOW",
    }
    out = cc.build_cio_now(position_decisions=[stale, fresh],
                           portfolio_value=1_000_000.0)
    cards = out["decisions"]
    assert cards
    # Fresh ACT NOW outranks stale ACT NOW (blocked) regardless of |delta|.
    assert cards[0]["symbol"] == "FRESH1", [c["symbol"] for c in cards]
    stale_card = next(c for c in cards if c["symbol"] == "STALE1")
    assert stale_card["urgency"] == "medium"
    # Stale decision stays material (it needs revalidation) — but not ACT-NOW tier.
    assert stale_card["decision_id"] in out["attention"]["material_today_ids"]


def test_reentry_lifecycle_idempotent_on_canonical_states():
    """P1-1: canonical lifecycle states are recognized after normalization."""
    from scripts.lib.cio_decision_semantics import reentry_state_from_desk
    table = {
        "WATCH_REENTRY": "WATCH_REENTRY",
        "DESK_READY_TO_REVIEW": "DESK_READY_TO_REVIEW",
        "NEAR_TRIGGER": "NEAR_TRIGGER",
        "GOVERNED_ELIGIBLE": "GOVERNED_ELIGIBLE",
        # raw desk strings must normalize to the same canonical states
        "READY TO REVIEW": "DESK_READY_TO_REVIEW",
        "READY_TO_REVIEW": "DESK_READY_TO_REVIEW",
        "NEAR ENTRY": "NEAR_TRIGGER",
        "OVERSOLD REVIEW": "NEAR_TRIGGER",
        "WATCH REENTRY": "WATCH_REENTRY",
    }
    for state, expected in table.items():
        got = reentry_state_from_desk(state)
        assert got == expected, f"{state!r} -> {got!r} != {expected!r}"
    # A bare state claiming RE_ENTER is non-authoritative.
    assert reentry_state_from_desk("RE_ENTER") == "GOVERNED_ELIGIBLE"
    # Only explicit governed verdict grants RE_ENTER.
    assert reentry_state_from_desk("GOVERNED_ELIGIBLE", "RE_ENTER") == "RE_ENTER"
    assert reentry_state_from_desk("NEAR_TRIGGER", "RE_ENTER") == "RE_ENTER"


def test_reentry_canonical_states_not_reenter():
    from scripts.lib.cio_decision_semantics import stance_from_queue_item
    for state in ("WATCH_REENTRY", "DESK_READY_TO_REVIEW",
                  "NEAR_TRIGGER", "GOVERNED_ELIGIBLE"):
        assert stance_from_queue_item({"symbol": "X", "state": state}) == "REVIEW", state


def test_sizing_unavailable_target_is_null_not_cap(monkeypatch):
    """P1-2: SIZING_UNAVAILABLE must not masquerade policy cap as target."""
    import scripts.lib.cio_institutional_sizing as sizing

    def _boom(**kwargs):
        raise RuntimeError("injected sizing failure")

    monkeypatch.setattr(sizing, "size_decision", _boom)
    plan = cp.build_capital_plan(
        portfolio_value=500_000.0,
        cash_total=100_000.0,
        positions=[{
            "symbol": "V", "market_value": 40_000.0,
            "account": "schwab_rollover_ira", "weight_pct": 8.0,
        }],
        queue={"items": [{"symbol": "V", "verdict": "TRIM",
                          "directive_label": "Advisory TRIM — V"}]},
        redeploy_open_events=[],
    )
    dec = next(d for d in plan["position_decisions"] if d["symbol"] == "V")
    assert dec["recommended_delta_usd"] == 0.0
    assert dec["target_weight_pct"] is None, dec["target_weight_pct"]
    assert dec.get("target_status") == "UNAVAILABLE"
    assert dec.get("scenario_trim_usd") == round(40_000.0 * 0.10, 2)
    # Policy cap stays as a separate constraint, not the recommended target.
    assert (dec.get("target_range_pct") or {}).get("max") == 12.0


# ─────────────────────────────────────────────────────────────────────────────
# P1-3 — topology audit provenance precision (code vs artifact)
# ─────────────────────────────────────────────────────────────────────────────

def test_topology_artifact_paths_not_code():
    from scripts.lib.cio_topology_audit import (
        _code_paths_from_text,
        _is_artifact_path,
    )
    line = (
        "cd /home/johnclaw/trade-ai-releases/portfolio-server && "
        "python scripts/cio_worker.py >> /tmp/cio_worker.lock 2>&1"
    )
    paths = _code_paths_from_text(line)
    assert "/tmp/cio_worker.lock" not in paths
    assert "/home/johnclaw/trade-ai-releases/portfolio-server" in paths
    assert _is_artifact_path("/tmp/cio_worker.lock") is True
    assert _is_artifact_path("/tmp/cio_worker.log") is True
    assert _is_artifact_path("/tmp/cio_worker.jsonl") is True
    assert _is_artifact_path("/tmp/cio_worker.pid") is True


def test_topology_old_tree_script_approved_cwd_fails():
    from scripts.lib.cio_topology_audit import (
        DEPRECATED_MARKERS,
        DEPRECATED_ROOTS,
        _classify_path,
        _code_paths_from_text,
    )
    approved = ("/home/johnclaw/trade-ai-releases/portfolio-server",)
    # Old-tree script launched from an approved cwd must still fail.
    cmd = "python /home/johnclaw/trade-ai-v12-rebuild/cio_worker.py"
    code = _code_paths_from_text(cmd)
    assert code == ["/home/johnclaw/trade-ai-v12-rebuild/cio_worker.py"]
    v = _classify_path(
        code[0],
        expected="6f7009794e5178a7926f5b1c84ae16d0ee7b2bc6",
        approved_roots=approved,
        deprecated_roots=DEPRECATED_ROOTS,
        deprecated_markers=DEPRECATED_MARKERS,
    )
    assert v is not None
    assert v["deprecated"] is True
    # The approved cwd alone is clean.
    cwd_v = _classify_path(
        "/home/johnclaw/trade-ai-releases/portfolio-server",
        expected="6f7009794e5178a7926f5b1c84ae16d0ee7b2bc6",
        approved_roots=approved,
        deprecated_roots=DEPRECATED_ROOTS,
        deprecated_markers=DEPRECATED_MARKERS,
    )
    assert cwd_v is None


def test_topology_old_tree_cron_one_violation_not_artifact():
    from scripts.lib.cio_topology_audit import (
        DEPRECATED_MARKERS,
        DEPRECATED_ROOTS,
        _validate_scheduled_entries,
    )
    entry = {
        "source": "test",
        "line": "*/5 * * * * cd /home/johnclaw/trade-ai-v12-rebuild && python cio_worker.py >> /tmp/foo.lock 2>&1",
        "checkout": "/home/johnclaw/trade-ai-v12-rebuild",
        "paths": [
            "/home/johnclaw/trade-ai-v12-rebuild",
            "/home/johnclaw/trade-ai-v12-rebuild/cio_worker.py",
        ],
    }
    violations = _validate_scheduled_entries(
        [entry],
        expected="6f7009794e5178a7926f5b1c84ae16d0ee7b2bc6",
        approved_roots=("/home/johnclaw/trade-ai-releases/portfolio-server",),
        deprecated_roots=DEPRECATED_ROOTS,
        deprecated_markers=DEPRECATED_MARKERS,
        key_fn=lambda e: [e["checkout"]] + list(e["paths"]),
    )
    assert len(violations) == 1, violations
    # The violation is the old code, not the /tmp lock artifact.
    assert "/tmp/foo.lock" not in violations[0]["path"]


def test_topology_approved_script_working_dir_pass():
    from scripts.lib.cio_topology_audit import (
        DEPRECATED_MARKERS,
        DEPRECATED_ROOTS,
        _classify_path,
    )
    approved = ("/home/johnclaw/trade-ai-releases/portfolio-server",)
    for p in (
        "/home/johnclaw/trade-ai-releases/portfolio-server",
        "/home/johnclaw/trade-ai-releases/portfolio-server/scripts/cio_worker.py",
    ):
        v = _classify_path(
            p,
            expected="6f7009794e5178a7926f5b1c84ae16d0ee7b2bc6",
            approved_roots=approved,
            deprecated_roots=DEPRECATED_ROOTS,
            deprecated_markers=DEPRECATED_MARKERS,
        )
        assert v is None, (p, v)
