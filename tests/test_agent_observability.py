"""Phase 2 — observability primitives: tool-call trace + notification/follow-up.

No broker, no network. tmp JSONL paths only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_tool_trace import (  # noqa: E402
    CAP_READ,
    CAP_WRITE,
    append_tool_call,
    build_tool_call,
    classify_tool,
    query_tool_calls,
    request_digest,
    response_digest,
)
from scripts.lib.agent_notification_intelligence import (  # noqa: E402
    NEXT_REVIEW_UNAVAILABLE,
    build_next_review,
    dedupe_identity,
    evaluate_notification,
    needs_next_review,
    validate_next_review,
)


# ── Tool-call trace ────────────────────────────────────────────────────────


def test_classify_read_tool():
    assert classify_tool("portfolio.get_verified_snapshot") == (CAP_READ, "read")


def test_classify_write_tool():
    assert classify_tool("broker.place_order") == (CAP_WRITE, "write")


def test_classify_unknown_defaults_read():
    cap, rw = classify_tool("mystery_tool")
    assert cap == "unknown"
    assert rw == "read"


def test_tool_call_digests_are_redacted():
    r = build_tool_call(
        tool_name="portfolio.get_verified_snapshot",
        trace_id="tr_1",
        wake_id="w1",
        agent="alex",
        request={"api_key": "sk-secret", "account": "123"},
        response={"cash": 5000, "token": "xoxp-abc"},
    )
    # request/response are digested, not raw; no secret survives in digest input
    assert "sk-secret" not in json_dump(r)
    assert r["request_digest"].startswith("req_")
    assert r["response_digest"].startswith("rsp_")


def json_dump(o):
    import json

    return json.dumps(o, sort_keys=True, default=str)


def test_tool_call_persist_and_query(tmp_path):
    p = tmp_path / "tools.jsonl"
    rec = build_tool_call(
        tool_name="portfolio.get_cash_snapshot",
        trace_id="tr_1",
        wake_id="w1",
        agent="alex",
        request={"account": "123"},
        response={"cash": 5000},
    )
    assert append_tool_call(rec, path=p)
    rows = query_tool_calls(trace_id="tr_1", path=p)
    assert len(rows) == 1
    assert rows[0]["read_write"] == "read"


def test_tool_call_no_secret_persisted(tmp_path):
    p = tmp_path / "tools.jsonl"
    rec = build_tool_call(
        tool_name="portfolio.get_cash_snapshot",
        trace_id="tr_1",
        wake_id="w1",
        agent="alex",
        request={"authorization": "Bearer abc123"},
    )
    append_tool_call(rec, path=p)
    raw = p.read_text()
    assert "Bearer abc123" not in raw


# ── Notification reasoning ─────────────────────────────────────────────────


def _decision(action="WAIT", act_now=False, evidence="ev1", decision_id="dec_1"):
    return {
        "decision_id": decision_id,
        "decision_input_digest": "in1",
        "decision_evidence_digest": evidence,
        "current_action": action,
        "act_now": act_now,
    }


def test_non_material_suppressed():
    r = evaluate_notification(decision=_decision(action="WAIT"))
    assert r["send"] is False
    assert r["suppressed_reason"] == "non_material"


def test_material_action_sent():
    r = evaluate_notification(decision=_decision(action="ACT_NOW", act_now=True))
    assert r["send"] is True


def test_unchanged_replay_suppressed():
    d = _decision(action="ACT_NOW", act_now=True)
    prev = {"dedupe_key": dedupe_identity(d), "decision_id": "dec_1"}
    r = evaluate_notification(decision=d, previous=prev)
    assert r["send"] is False
    assert r["suppressed_reason"] == "unchanged_replay"


def test_prior_reject_suppresses_unchanged():
    d = _decision(action="ACT_NOW", act_now=True)
    prev = {"dedupe_key": dedupe_identity(d), "disposition": "REJECT"}
    r = evaluate_notification(decision=d, previous=prev)
    assert r["send"] is False
    assert r["suppressed_reason"] == "prior_operator_reject_unchanged"


def test_new_evidence_reopens_prior_reject():
    d = _decision(action="ACT_NOW", act_now=True, evidence="ev2")
    prev = {
        "dedupe_key": dedupe_identity(_decision(evidence="ev1")),
        "decision_id": "dec_1",
        "evidence_digest": "ev1",
        "disposition": "REJECT",
    }
    r = evaluate_notification(decision=d, previous=prev)
    assert r["send"] is True
    assert r["reopen"] is True
    assert r["reopen_label"] == "WHAT CHANGED SINCE YOUR REJECT"


def test_every_suppressed_has_reason():
    for d, prev in [
        (_decision(action="WAIT"), {}),
        (_decision(action="ACT_NOW", act_now=True), {"dedupe_key": dedupe_identity(_decision(action="ACT_NOW", act_now=True))}),
    ]:
        r = evaluate_notification(decision=d, previous=prev)
        if not r["send"]:
            assert r["suppressed_reason"], "suppressed without reason"


# ── Follow-up / next-review binding ────────────────────────────────────────


def test_next_review_time_binding():
    nr = build_next_review(kind="TIME", due_at="2026-08-18T00:00:00Z")
    ok, reason = validate_next_review(nr)
    assert ok, reason
    assert nr["revisit_id"].startswith("rv_")


def test_next_review_condition_binding():
    nr = build_next_review(kind="CONDITION", condition="cash_band_rebalanced")
    ok, reason = validate_next_review(nr)
    assert ok, reason


def test_bare_next_review_is_rejected():
    ok, reason = validate_next_review({})
    assert not ok
    assert "kind missing" in reason


def test_build_next_review_default_is_explicitly_unavailable():
    # build_next_review() with no schedule degrades to an explicit
    # NEXT_REVIEW_UNAVAILABLE + reason, never a silent blank.
    nr = build_next_review()
    assert nr["kind"] == NEXT_REVIEW_UNAVAILABLE
    assert nr["reason"] == "NO_SCHEDULE_PROVIDED"


def test_next_review_unavailable_without_reason_rejected():
    nr = {"kind": NEXT_REVIEW_UNAVAILABLE}
    ok, reason = validate_next_review(nr)
    assert not ok


def test_needs_next_review_non_action():
    assert needs_next_review("WAIT")
    assert needs_next_review("REVALIDATE")
    assert not needs_next_review("ACT_NOW")


def test_unknown_kind_rejected():
    nr = {"kind": "SOMEDAY", "revisit_id": "rv_1"}
    ok, reason = validate_next_review(nr)
    assert not ok
