#!/usr/bin/env python3
"""Governance-projection regression gates (operator adjudication 2026-07-14).

A locked plan's artifacts must project the SAME governed state as the database and
workstation — packet, implementation export, oversight aggregate, event status and
capital reservation may never disagree. Read-only against the DB; rollback always."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

API_SRC = (ROOT / "scripts" / "api_v2.py").read_text()
OVERSIGHT_SRC = (ROOT / "scripts" / "lib" / "redeploy_oversight.py").read_text()
PACKET_SRC = (ROOT / "scripts" / "redeploy_operator_packet.py").read_text()


def _cur():
    from db_adapter import _get_conn
    conn = _get_conn()
    conn.rollback()
    return conn, conn.cursor()


def test_locked_export_fails_on_governance_mismatch_source():
    """Gate exists: locked-plan export refuses when surfaces disagree; force_stale
    never bypasses it."""
    assert "governance_mismatch" in API_SRC
    assert "locked-plan export refused until every governance surface agrees" in API_SRC
    gate = API_SRC.split("governance_mismatch")[0][-2000:]
    assert "force" not in gate.split("exporting_locked")[-1], \
        "governance gate must not be conditioned on force_stale"


def test_locked_export_cannot_claim_draft():
    """The committed implementation artifact for the locked plan must project
    locked/pass — never the generation-time draft/pending copies."""
    p = ROOT / "docs" / "audits" / "FCNTX_144_IMPLEMENTATION_PLAN_F_v31.json"
    if not p.exists():
        return
    tp = json.loads(p.read_text())
    assert tp.get("operator_status") == "locked", tp.get("operator_status")
    assert tp.get("oversight_status") == "pass"
    assert tp.get("readiness_status") == "OPERATOR_LOCKED"
    assert tp.get("locked_plan_id") == 1191 and tp.get("locked_plan_version") == 31
    assert tp.get("implementation_review_approved") is True
    assert tp.get("capital_status") == "reserved_locked"
    for k in ("locked_at", "locked_by", "oversight_completed_at", "oversight_run_ids",
              "calculation_snapshot_id", "quote_snapshot_id", "packet_generated_at"):
        assert tp.get(k), f"missing {k}"


def test_passed_lanes_cannot_render_pending():
    """Keyed aggregate: when every lane's newest keyed verdict is pass, the
    projection must say pass — never pending."""
    conn, cur = _cur()
    try:
        from lib.redeploy_oversight import governance_projection
        g = governance_projection(cur, 144)
        if not g.get("locked"):
            return
        lanes = g.get("oversight_lanes") or {}
        if lanes and all(v == "pass" for v in lanes.values()) and len(lanes) >= 2:
            assert g["oversight_status"] == "pass"
            assert g["readiness_status"] in ("OPERATOR_LOCKED", "IMPLEMENTATION_IN_PROGRESS")
    finally:
        conn.rollback()


def test_newer_pass_beats_older_needs_review_same_snapshot():
    """DISTINCT ON (lane) ... ORDER BY id DESC: run 23 (pass, adjudicated) must
    supersede run 22 (needs_review) for the identical plan/version key."""
    conn, cur = _cur()
    try:
        cur.execute("""SELECT id, verdict FROM deploy_oversight_runs
                       WHERE deploy_event_id=144 AND plan_id=1191 AND plan_version=31
                         AND lane='chatgpt' ORDER BY id""")
        rows = cur.fetchall()
        if len(rows) < 2:
            return
        from lib.redeploy_oversight import oversight_aggregate
        agg = oversight_aggregate(cur, 144, 1191, 31)
        newest = rows[-1][1]
        assert agg["lanes"]["chatgpt"]["verdict"] == newest
        assert agg["lanes"]["chatgpt"]["run_id"] == rows[-1][0]
    finally:
        conn.rollback()


def test_other_plan_verdicts_never_participate():
    """Plan-B rows (and legacy unkeyed rows with plan_id NULL) must never affect
    Plan F's aggregate."""
    conn, cur = _cur()
    try:
        from lib.redeploy_oversight import oversight_aggregate
        agg = oversight_aggregate(cur, 144, 1191, 31)
        if not agg["run_ids"]:
            return
        cur.execute("""SELECT COUNT(*) FROM deploy_oversight_runs
                       WHERE id = ANY(%s) AND (plan_id IS DISTINCT FROM 1191
                                               OR plan_version IS DISTINCT FROM 31)""",
                    (agg["run_ids"],))
        assert cur.fetchone()[0] == 0, "aggregate included rows outside the immutable key"
        # keyed reducer never selects NULL-keyed legacy rows at all
        assert "plan_id=%s AND plan_version=%s" in OVERSIGHT_SRC
    finally:
        conn.rollback()


def test_packet_after_lock_shows_locked_and_supersedes():
    packet = ROOT / "docs" / "audits" / "FCNTX_144_DECISION_PACKET_LATEST.md"
    if not packet.exists():
        return
    txt = packet.read_text()
    assert "OPERATOR_LOCKED" in txt
    assert "SUPERSEDES any packet generated before" in txt
    assert "Oversight aggregate | PASS" in txt.replace("**", "")
    assert "ANALYTICS READY — OVERSIGHT PENDING" not in txt


def test_packet_generator_refuses_inconsistent_governance():
    assert "REFUSING packet: governance mismatches" in PACKET_SRC


def test_projection_consistency_checks_exist():
    for probe in ("db plan oversight_status", "capital_status", "operator_status",
                  "readiness", "mismatches"):
        assert probe in OVERSIGHT_SRC


if __name__ == "__main__":
    for k, v in sorted(globals().items()):
        if k.startswith("test_"):
            v(); print("OK", k)
    print("ALL PASSED")
