"""Operator 2026-09-27: (a) the Defense CC 'queue trade' bubble evaluates queue-time ELIGIBILITY
(mode live), not the fail-closed submit gate, so rows are not born QUEUED_BLOCKED for inputs a
card cannot carry; the fail-closed checks still run at preflight and confirm. (b) a queue row
approved before the approval pin existed is pinned to the proposal_json it stored and to
reviewed_at, so it reads approval_expired (or passes) instead of approval_pin_missing. Hermetic."""
from __future__ import annotations

import ast
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")]

import options_desk_enterprise as ent  # noqa: E402
from test_options_order_gates_20260927 import NOW, PID, _gate, _iso, _proposal, _store  # noqa: E402


def _legacy_row(proposal, *, reviewed_age_min=10, as_json=False, with_proposal=True):
    return {"status": "approved", "live_eligible": True, "blocks_json": [],
            "proposal_json": (json.dumps(proposal) if as_json else dict(proposal)) if with_proposal else None,
            "reviewed_at": _iso(NOW - timedelta(minutes=reviewed_age_min)), "reviewer": "operator",
            "meta": {}, "expires_at": None}


def _codes(res):
    return {r["code"] for r in res["refusals"]}


def test_legacy_approved_row_is_pinned_to_what_it_stored(tmp_path):
    p = _proposal()
    res = _gate(p, _store(tmp_path), row=_legacy_row(p))
    assert res["ok"] is True and res["approval_pin_derived"] is True, res["refusals"]
    res_json = _gate(p, _store(tmp_path), row=_legacy_row(p, as_json=True))
    assert res_json["ok"] is True


def test_legacy_row_still_catches_changed_legs_and_expiry(tmp_path):
    p = _proposal()
    changed = _gate(dict(p, long_strike=485.0), _store(tmp_path), row=_legacy_row(p))
    assert "legs_changed" in _codes(changed) and "approval_pin_missing" not in _codes(changed)
    old = _gate(p, _store(tmp_path), row=_legacy_row(p, reviewed_age_min=300))
    assert "approval_expired" in _codes(old) and "approval_pin_missing" not in _codes(old)
    nothing = _gate(p, _store(tmp_path), row=_legacy_row(p, with_proposal=False))
    assert "approval_pin_missing" in _codes(nothing) and nothing["approval_pin_derived"] is False


def test_pinned_rows_are_unchanged(tmp_path):
    from test_options_order_gates_20260927 import _row
    p = _proposal()
    res = _gate(p, _store(tmp_path), row=_row(p))
    assert res["ok"] is True and res["approval_pin_derived"] is False


def test_defense_cc_queue_evaluates_queue_time_eligibility_not_the_submit_gate():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_defense_cc_queue_trade")
    body = ast.get_source_segment(src, fn)
    calls = [ast.get_source_segment(src, n) for n in ast.walk(fn)
             if isinstance(n, ast.Call) and "evaluate_hard_risk_blocks" in ast.get_source_segment(src, n.func)]
    assert calls and all('mode="live"' in c for c in calls), calls
    assert 'mode="submit"' not in body and 'mode="preflight"' not in body


def test_live_mode_skips_absent_inputs_while_submit_mode_fails_closed():
    p = {k: v for k, v in _proposal().items() if k not in ("buying_power", "market_session", "chain_fetched_at")}
    p["legs_liquidity"] = []
    live = {b["code"] for b in ent.evaluate_hard_risk_blocks(dict(p), mode="live")}
    submit = {b["code"] for b in ent.evaluate_hard_risk_blocks(dict(p), mode="submit")}
    assert not ({"buying_power_unknown", "quote_age_unknown", "chain_age_unknown", "market_session_unknown"} & live)
    assert "buying_power_unknown" in submit
