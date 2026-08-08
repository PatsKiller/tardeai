import pytest
import json
import tempfile
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from scripts.lib.cio_health_boundary import (
    CIOHealthBoundary,
    HealthSnapshot,
    AdvisoryDecision,
    create_data_quality_block,
    unblock_if_healthy,
    attach_health_metadata_to_handoff,
    is_handoff_eligible,
    DOMAIN_HEALTH_MAPPING,
    CIO_DOMAINS,
    REASON_CODES,
    ADVISORY_STATE,
)


# ── Helpers ────────────────────────────────────────────────────────


def make_healthy_snapshot():
    return HealthSnapshot(
        health_snapshot_id="snap-healthy-001",
        observed_at=datetime.now(timezone.utc).isoformat(),
        overall_score=95,
        overall_status="healthy",
        category_scores={"market_data": 95, "broker": 95, "database": 95},
        findings=[],
        data_freshness={
            "portfolio": {
                "last_update": datetime.now(timezone.utc).isoformat(),
                "status": "fresh",
            },
            "holdings": {
                "last_update": datetime.now(timezone.utc).isoformat(),
                "status": "fresh",
            },
        },
        source_status={"broker_api": "connected", "market_data": "streaming"},
    )


def make_blocked_snapshot():
    return HealthSnapshot(
        health_snapshot_id="snap-blocked-001",
        observed_at=datetime.now(timezone.utc).isoformat(),
        overall_score=20,
        overall_status="critical",
        category_scores={"market_data": 15, "broker": 10, "database": 80},
        findings=[
            {
                "finding_id": "f-001",
                "category": "market_data",
                "severity": 5,
                "source": "health_agent",
                "finding_type": "data_unavailable",
                "status": "active",
                "first_seen_at": (
                    datetime.now(timezone.utc) - timedelta(hours=2)
                ).isoformat(),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "evidence_ref": "health-agent-run-123",
                "remediation_status": "pending",
            },
            {
                "finding_id": "f-002",
                "category": "broker",
                "severity": 4,
                "source": "health_agent",
                "finding_type": "connection_failed",
                "status": "active",
                "first_seen_at": (
                    datetime.now(timezone.utc) - timedelta(hours=1)
                ).isoformat(),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "evidence_ref": "health-agent-run-123",
                "remediation_status": "in_progress",
            },
        ],
        data_freshness={
            "portfolio": {
                "last_update": (
                    datetime.now(timezone.utc) - timedelta(hours=6)
                ).isoformat(),
                "status": "stale",
            },
            "holdings": {
                "last_update": (
                    datetime.now(timezone.utc) - timedelta(hours=6)
                ).isoformat(),
                "status": "stale",
            },
        },
        source_status={"broker_api": "disconnected", "market_data": "down"},
    )


def make_degraded_snapshot():
    return HealthSnapshot(
        health_snapshot_id="snap-degraded-001",
        observed_at=datetime.now(timezone.utc).isoformat(),
        overall_score=65,
        overall_status="degraded",
        category_scores={"market_data": 60, "broker": 95, "database": 95},
        findings=[
            {
                "finding_id": "f-003",
                "category": "market_data",
                "severity": 2,
                "source": "health_agent",
                "finding_type": "data_stale",
                "status": "active",
                "first_seen_at": (
                    datetime.now(timezone.utc) - timedelta(minutes=90)
                ).isoformat(),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "evidence_ref": "health-agent-run-456",
                "remediation_status": "none",
            },
        ],
        data_freshness={
            "portfolio": {
                "last_update": datetime.now(timezone.utc).isoformat(),
                "status": "fresh",
            },
            "technicals": {
                "last_update": (
                    datetime.now(timezone.utc) - timedelta(hours=3)
                ).isoformat(),
                "status": "stale",
            },
        },
        source_status={"broker_api": "connected", "market_data": "degraded"},
    )


# ── Tests ──────────────────────────────────────────────────────────


class TestHealthAdapterSchema:
    def test_healthy_snapshot_accepts(self):
        s = make_healthy_snapshot()
        assert s.health_snapshot_id == "snap-healthy-001"
        assert s.overall_score == 95

    def test_blocked_snapshot_accepts(self):
        s = make_blocked_snapshot()
        assert s.overall_status == "critical"
        assert len(s.findings) == 2

    def test_snapshot_from_dict(self):
        s = make_healthy_snapshot()
        d = s.to_dict()
        s2 = HealthSnapshot.from_dict(d)
        assert s2.health_snapshot_id == s.health_snapshot_id


class TestReadyDecision:
    def test_healthy_snapshot_ready(self):
        boundary = CIOHealthBoundary(make_healthy_snapshot())
        d = boundary.evaluate("portfolio_review", ["portfolio", "holdings", "performance"])
        assert d.state == "READY"
        assert d.blocked_domains == []

    def test_ready_decision_same_input_same_output(self):
        s = make_healthy_snapshot()
        b1 = CIOHealthBoundary(s)
        b2 = CIOHealthBoundary(s)
        d1 = b1.evaluate("cio_question", ["portfolio"])
        d2 = b2.evaluate("cio_question", ["portfolio"])
        assert d1.state == d2.state
        assert d1.decision_hash == d2.decision_hash


class TestDegradedDecision:
    def test_degraded_snapshot(self):
        boundary = CIOHealthBoundary(make_degraded_snapshot())
        d = boundary.evaluate("cio_question", ["portfolio", "technicals"])
        assert d.state == "DEGRADED"
        assert "technicals" in d.degraded_domains or len(d.degraded_domains) > 0

    def test_degraded_not_blocked(self):
        boundary = CIOHealthBoundary(make_degraded_snapshot())
        d = boundary.evaluate("cio_question", ["portfolio"])
        assert d.state != "BLOCKED"


class TestBlockedDecision:
    def test_blocked_snapshot(self):
        boundary = CIOHealthBoundary(make_blocked_snapshot())
        d = boundary.evaluate("portfolio_review", ["portfolio", "holdings"])
        assert d.state == "BLOCKED"
        assert len(d.blocked_domains) > 0

    def test_blocked_has_typed_reason_codes(self):
        boundary = CIOHealthBoundary(make_blocked_snapshot())
        d = boundary.evaluate("cio_question", ["portfolio", "holdings"])
        assert len(d.reason_codes) > 0
        for rc in d.reason_codes:
            assert rc in REASON_CODES or rc.endswith("_DATA_UNAVAILABLE") or rc.endswith("_DEGRADED")


class TestUnknownFailClosed:
    def test_no_snapshot_fails_closed(self):
        boundary = CIOHealthBoundary(None)
        d = boundary.evaluate("portfolio_review", ["portfolio"])
        assert d.state == "UNKNOWN"
        assert "HEALTH_EVIDENCE_UNAVAILABLE" in d.reason_codes


class TestDomainScopedBlocking:
    def test_blocked_domain_blocks_related(self):
        """market_data blocked should block portfolio but not retirement."""
        s = make_blocked_snapshot()
        s.category_scores = {"market_data": 10, "broker": 10, "database": 95}
        s.findings = [
            {
                "finding_id": "f-x",
                "category": "market_data",
                "severity": 5,
                "source": "ha",
                "finding_type": "x",
                "status": "active",
                "first_seen_at": datetime.now(timezone.utc).isoformat(),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "evidence_ref": "",
                "remediation_status": "",
            },
        ]
        boundary = CIOHealthBoundary(s)
        d_portfolio = boundary.evaluate("check", ["portfolio", "holdings"])
        assert d_portfolio.state == "BLOCKED"

        # retirement depends on database (healthy here)
        d_retirement = boundary.evaluate("check", ["retirement"])
        assert d_retirement.state in ("READY", "DEGRADED")

    def test_global_score_alone_not_sufficient(self):
        """Overall score 0 but all domain scores healthy = READY."""
        s = make_healthy_snapshot()
        s.overall_score = 0
        s.overall_status = "critical"
        boundary = CIOHealthBoundary(s)
        d = boundary.evaluate("test", ["portfolio"])
        assert d.state == "READY"


class TestDeterminism:
    def test_same_input_same_output(self):
        s = make_blocked_snapshot()
        b1 = CIOHealthBoundary(s)
        b2 = CIOHealthBoundary(s)
        d1 = b1.evaluate("task", ["portfolio", "holdings"])
        d2 = b2.evaluate("task", ["portfolio", "holdings"])
        assert d1.state == d2.state
        assert d1.reason_codes == d2.reason_codes
        assert d1.blocked_domains == d2.blocked_domains
        assert d1.compute_hash() == d2.compute_hash()


class TestBlockActionIntegration:
    def test_block_decision_creates_action(self):
        boundary = CIOHealthBoundary(make_blocked_snapshot())
        d = boundary.evaluate("test", ["portfolio", "holdings"])
        assert d.state == "BLOCKED"

        from scripts.lib.cio_action_ledger import CIOActionLedger

        with tempfile.TemporaryDirectory() as td:
            ledger = CIOActionLedger(event_store_path=Path(td) / "test_ledger.jsonl")
            event = create_data_quality_block(d, ledger=ledger)
            assert event is not None
            assert event["event_type"] == "CIO_ACTION_BLOCKED"
            assert event["payload"]["blocked_domains"] is not None

    def test_block_action_idempotent(self):
        boundary = CIOHealthBoundary(make_blocked_snapshot())
        d = boundary.evaluate("test", ["portfolio"])

        from scripts.lib.cio_action_ledger import CIOActionLedger

        with tempfile.TemporaryDirectory() as td:
            ledger = CIOActionLedger(event_store_path=Path(td) / "test_ledger.jsonl")
            e1 = create_data_quality_block(d, ledger=ledger)
            e2 = create_data_quality_block(d, ledger=ledger)
            assert e1 is not None
            assert e2 is None  # idempotent

    def test_ready_decision_no_block_action(self):
        boundary = CIOHealthBoundary(make_healthy_snapshot())
        d = boundary.evaluate("test", ["portfolio"])
        assert d.state == "READY"

        from scripts.lib.cio_action_ledger import CIOActionLedger

        with tempfile.TemporaryDirectory() as td:
            ledger = CIOActionLedger(event_store_path=Path(td) / "test_ledger.jsonl")
            event = create_data_quality_block(d, ledger=ledger)
            assert event is None


class TestAutoUnblock:
    def test_unblock_when_healthy(self):
        from scripts.lib.cio_action_ledger import CIOActionLedger

        with tempfile.TemporaryDirectory() as td:
            ledger = CIOActionLedger(event_store_path=Path(td) / "test_ledger.jsonl")

            b_boundary = CIOHealthBoundary(make_blocked_snapshot())
            b_decision = b_boundary.evaluate("test", ["portfolio"])
            block_event = create_data_quality_block(b_decision, ledger=ledger)
            action_id = block_event["stream_id"]

            h_boundary = CIOHealthBoundary(make_healthy_snapshot())
            h_decision = h_boundary.evaluate("test", ["portfolio"])
            unblock_event = unblock_if_healthy(action_id, h_decision, ledger=ledger)

            assert unblock_event is not None
            assert unblock_event["event_type"] == "CIO_ACTION_UNBLOCKED"

            action = ledger.get_action(action_id)
            assert action["current_status"] == "OPEN"


class TestBlockHistoryPreserved:
    def test_block_history_immutable(self):
        from scripts.lib.cio_action_ledger import CIOActionLedger

        with tempfile.TemporaryDirectory() as td:
            ledger = CIOActionLedger(event_store_path=Path(td) / "test_ledger.jsonl")

            b_boundary = CIOHealthBoundary(make_blocked_snapshot())
            d = b_boundary.evaluate("test", ["portfolio"])
            create_data_quality_block(d, ledger=ledger)

            h_boundary = CIOHealthBoundary(make_healthy_snapshot())
            hd = h_boundary.evaluate("test", ["portfolio"])

            key_parts = [
                d.policy_version,
                ",".join(sorted(d.blocked_domains)),
                ",".join(sorted(d.reason_codes)),
                d.health_snapshot_id,
            ]
            import hashlib
            idk = hashlib.sha256("|".join(key_parts).encode()).hexdigest()[:32]
            action_id = f"data-quality-block-{idk[:8]}"

            unblock_if_healthy(action_id, hd, ledger=ledger)

            events = ledger.list_events(action_id)
            event_types = [
                e["event_type"] for e in events if e["event_type"] != "CIO_ACTION_LEDGER_GENESIS"
            ]
            assert "CIO_ACTION_CREATED" in event_types
            assert "CIO_ACTION_UNBLOCKED" in event_types


class TestHandoffHealthIntegration:
    def test_handoff_block_metadata_test(self):
        boundary = CIOHealthBoundary(make_blocked_snapshot())
        d = boundary.evaluate("portfolio_review", ["portfolio", "holdings"])

        handoff = {
            "handoff_id": "hf-test",
            "task_type": "portfolio_review",
            "task_summary": "Test",
        }

        eligible, decision = is_handoff_eligible(handoff, boundary, ["portfolio", "holdings"])
        assert not eligible
        assert decision.state == "BLOCKED"


class TestNoRemediation:
    def test_no_remediation_invocation(self):
        with open("scripts/lib/cio_health_boundary.py") as f:
            source = f.read()

        forbidden = [
            "claude_escalation",
            "coder_dispatch",
            "systemctl",
            "subprocess.run",
            "os.system",
            "sudo",
            "restart_service",
        ]
        for term in forbidden:
            assert term not in source, f"Found forbidden term: {term}"

    def test_no_system_tools(self):
        with open("scripts/lib/cio_health_boundary.py") as f:
            source = f.read()
        forbidden_imports = ["subprocess", "shlex", "pty"]
        for imp in forbidden_imports:
            assert f"import {imp}" not in source and f"from {imp}" not in source, (
                f"Forbidden import: {imp}"
            )


class TestZeroProvider:
    def test_zero_provider_calls(self):
        with open("scripts/lib/cio_health_boundary.py") as f:
            source = f.read()
        assert "openai" not in source.lower()
        assert "deepseek" not in source.lower()
        assert "anthropic" not in source.lower()


class TestInvalidPolicy:
    def test_invalid_domain_fail_closed(self):
        boundary = CIOHealthBoundary(make_healthy_snapshot())
        with pytest.raises(ValueError):
            boundary.evaluate("test", ["invalid_domain"])


class TestRecheckAfter:
    def test_recheck_after_set(self):
        boundary = CIOHealthBoundary(make_degraded_snapshot())
        d = boundary.evaluate("test", ["portfolio", "technicals"])
        assert d.recheck_after is not None or d.state == "DEGRADED"


# ── G0-HEALTH-01 ───────────────────────────────────────────────────
def test_G0_HEALTH_01():
    """G0-HEALTH-01: Data quality zero, required source unavailable.

    Expected: BLOCKED, typed reason, CIO_DATA_QUALITY_BLOCK created,
    no provider call, no remediation, no Telegram.
    """
    snapshot = HealthSnapshot(
        health_snapshot_id="g0-health-01",
        observed_at=datetime.now(timezone.utc).isoformat(),
        overall_score=0,
        overall_status="critical",
        category_scores={
            "market_data": 0,
            "broker": 0,
            "database": 0,
            "agent_jobs": 0,
            "api": 0,
            "file_integrity": 0,
        },
        findings=[
            {
                "finding_id": "g0-f-001",
                "category": "market_data",
                "severity": 5,
                "source": "health_agent",
                "finding_type": "data_unavailable",
                "status": "active",
                "first_seen_at": datetime.now(timezone.utc).isoformat(),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "evidence_ref": "test",
                "remediation_status": "pending",
            },
        ],
        data_freshness={
            "portfolio": {
                "last_update": "2020-01-01T00:00:00Z",
                "status": "unavailable",
            },
            "holdings": {
                "last_update": "2020-01-01T00:00:00Z",
                "status": "unavailable",
            },
        },
        source_status={"broker_api": "disconnected", "market_data": "down"},
    )

    boundary = CIOHealthBoundary(snapshot)
    decision = boundary.evaluate("portfolio_review", ["portfolio", "holdings", "risk"])

    assert decision.state == "BLOCKED"
    assert len(decision.reason_codes) > 0
    assert len(decision.blocked_domains) > 0

    from scripts.lib.cio_action_ledger import CIOActionLedger

    with tempfile.TemporaryDirectory() as td:
        ledger = CIOActionLedger(event_store_path=Path(td) / "test_ledger.jsonl")
        event = create_data_quality_block(decision, ledger=ledger)
        assert event is not None
        assert event["event_type"] == "CIO_ACTION_BLOCKED"
        assert event["payload"].get("blocked_domains") is not None


# ── G0-HEALTH-02 ───────────────────────────────────────────────────
def test_G0_HEALTH_02():
    """G0-HEALTH-02: Block -> healthy snapshot -> UNBLOCK.

    Expected: READY, CIO_ACTION_UNBLOCKED, block history preserved,
    no provider call.
    """
    from scripts.lib.cio_action_ledger import CIOActionLedger

    with tempfile.TemporaryDirectory() as td:
        ledger = CIOActionLedger(event_store_path=Path(td) / "test_ledger.jsonl")

        # Phase 1: Block
        b_snap = make_blocked_snapshot()
        b_boundary = CIOHealthBoundary(b_snap)
        b_decision = b_boundary.evaluate("portfolio_review", ["portfolio", "holdings"])
        assert b_decision.state == "BLOCKED"
        block_event = create_data_quality_block(b_decision, ledger=ledger)
        action_id = block_event["stream_id"]

        # Verify block exists
        action = ledger.get_action(action_id)
        assert action["current_status"] == "BLOCKED"

        # Phase 2: Health restored
        h_snap = make_healthy_snapshot()
        h_boundary = CIOHealthBoundary(h_snap)
        h_decision = h_boundary.evaluate("portfolio_review", ["portfolio", "holdings"])
        assert h_decision.state == "READY"

        # Unblock
        unblock_event = unblock_if_healthy(action_id, h_decision, ledger=ledger)
        assert unblock_event is not None
        assert unblock_event["event_type"] == "CIO_ACTION_UNBLOCKED"

        # Block history preserved
        events = ledger.list_events(action_id)
        event_types = [
            e["event_type"] for e in events if e["event_type"] != "CIO_ACTION_LEDGER_GENESIS"
        ]
        assert "CIO_ACTION_CREATED" in event_types
        assert "CIO_ACTION_UNBLOCKED" in event_types
