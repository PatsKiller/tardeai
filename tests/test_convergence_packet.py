#!/usr/bin/env python3
"""Convergence packet — safety-invariant tests (Part F). Proves the packet CANNOT deploy from the
live checkout, CANNOT run CONNECT before MOUNT or without a separate ack, classifies the agent-runtime
contract exactly, and never leaks a secret. Pure — no host mutation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "convergence"))

import convergence_lib as cl  # noqa: E402
from convergence_lib import (validate_build_source, build_meta, can_run_connect, classify_agent_runtime,
                             mount_contract_ok, connect_contract_ok, verify_markers, redact,
                             contains_secret, BuildSourceError, PhaseGateError, SOURCE_MODE_EXACT,
                             SOURCE_MODE_LIVE, AGENT_RUNTIME_CONTRACT)

SHA = "03bbf00d2646a08f63bc9e94f2f35dc406311262"
ZERO_AUTH = {"mutation": False, "provider_call": False, "service_control": False,
             "schedule_change": False, "financial_action": False}


# ── build source: staged exact-ref only ──
def test_build_source_staged_ok():
    validate_build_source(SOURCE_MODE_EXACT)   # no raise

def test_build_source_live_checkout_forbidden():
    with pytest.raises(BuildSourceError):
        validate_build_source(SOURCE_MODE_LIVE)
    with pytest.raises(BuildSourceError):
        validate_build_source("whatever")

def test_build_meta_requires_full_40_char_commit():
    m = build_meta(SHA, {"agent_runtime": "v1"})
    assert m["source_commit"] == SHA and m["frontend_build_source"] == SOURCE_MODE_EXACT
    assert m["live_checkout_build_input"] == "NONE"
    for bad in ("03bbf00d", "", "xyz", SHA[:39]):
        with pytest.raises(BuildSourceError):
            build_meta(bad, {})


# ── two-phase gating ──
def test_connect_blocked_before_mount():
    with pytest.raises(PhaseGateError):
        can_run_connect(mount_passed=False, connect_ack=True)

def test_connect_requires_separate_ack():
    with pytest.raises(PhaseGateError):
        can_run_connect(mount_passed=True, connect_ack=False)

def test_connect_allowed_only_when_both():
    assert can_run_connect(mount_passed=True, connect_ack=True) is True


# ── agent-runtime contract classification ──
def test_classify_404_mount_absent():
    assert classify_agent_runtime(404, None) == "MOUNT_ABSENT"

def test_classify_503_mounted_disconnected():
    body = {"read_only": True, "connected": False, "authority": ZERO_AUTH}
    assert classify_agent_runtime(503, body) == "MOUNTED_DISCONNECTED"
    assert mount_contract_ok(503, body)

def test_classify_200_connected_read_only():
    body = {"read_only": True, "connected": True, "authority": ZERO_AUTH,
            "reader_role": "agentic_runtime_reader", "contract": AGENT_RUNTIME_CONTRACT}
    assert classify_agent_runtime(200, body) == "CONNECTED_READ_ONLY"
    assert connect_contract_ok(200, body, "agentic_runtime_reader")

def test_connect_contract_rejects_wrong_role_or_authority():
    good = {"read_only": True, "connected": True, "authority": ZERO_AUTH, "reader_role": "agentic_runtime_reader"}
    assert not connect_contract_ok(200, {**good, "reader_role": "postgres"}, "agentic_runtime_reader")
    bad_auth = {**good, "authority": {**ZERO_AUTH, "mutation": True}}
    assert classify_agent_runtime(200, bad_auth) == "CONNECTED_MALFORMED"
    assert not connect_contract_ok(200, bad_auth, "agentic_runtime_reader")

def test_mount_contract_rejects_connected_true():
    # a 200/connected must NOT satisfy the MOUNT (disconnected) contract
    assert not mount_contract_ok(200, {"read_only": True, "connected": True, "authority": ZERO_AUTH})


# ── marker verification ──
def test_verify_markers():
    txt = "…ADMITTED…RESEARCH_ONLY…QUARANTINED…ELIGIBLE NOW…"
    r = verify_markers(txt, cl.WATCH_MARKERS)
    assert r["ok"] and not r["missing"]
    r2 = verify_markers("only ADMITTED here", cl.WATCH_MARKERS)
    assert not r2["ok"] and "QUARANTINED" in r2["missing"]


# ── secret redaction ──
def test_redact_dsn_and_secrets():
    samples = [
        "DATABASE_URL=postgresql://agentic_runtime_reader:hunter2@host:5433/db",
        "PGPASSWORD=supersecret123",
        "api_key: sk-abc123def456",
        "APCA-API-KEY-ID=PKABCDEFGH",
    ]
    for s in samples:
        out = redact(s)
        assert "[REDACTED]" in out
        assert not contains_secret(out)          # nothing sensitive survives
        assert "hunter2" not in out and "supersecret123" not in out and "sk-abc123def456" not in out

def test_redact_leaves_clean_text():
    clean = "agent_runtime_api_state|CONNECTED_READ_ONLY connected=true read_only=true"
    assert redact(clean) == clean and not contains_secret(clean)


# ── rollback manifest ──
def test_rollback_manifest_shape():
    m = cl.rollback_manifest(backend_hashes={"scripts/portfolio_server.py": "abc"}, static_backup="/b/x.tgz",
                             static_build_meta={"source_commit": SHA}, reader_env_present=True,
                             reader_env_mode="600", dropin_present=True, service_state="active",
                             watch_packets={"w1": "h1"}, defense_snapshots={"d1": "h2"})
    assert m["manifest_version"] == "convergence-rollback-v1"
    assert m["reader"]["env_mode"] == "600" and m["service_state"] == "active"
    assert m["backend_hashes"] and m["watch_packets"] and m["defense_snapshots"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
