"""Hermetic tests for the n8n run relay; no 172.x bind and no live gateway."""

from __future__ import annotations

import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from scripts import n8n_run_relay as R

KEY = "k" * 48
BEARER = "b" * 48
LANE = "n8n-lab-watchdog"


def env(tmp_path, **extra):
    return {
        "TRADEAI_N8N_RELAY_BEARER": BEARER,
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": KEY,
        "TRADEAI_STATE_ROOT": str(tmp_path),
        **extra,
    }


def relay(tmp_path, transport=None, **extra):
    return R.Relay(environ=env(tmp_path, **extra), allowlist=frozenset({LANE}), transport=transport)


@pytest.mark.parametrize("host,port", [("127.0.0.1", 18092), ("172.19.0.1", 18092)])
def test_bind_accepts_loopback_and_docker_bridge(host, port):
    R.guard_bind(host, port)


@pytest.mark.parametrize(
    "host,port",
    [
        ("0.0.0.0", 18092),
        ("10.0.0.5", 18092),
        ("8.8.8.8", 18092),
        ("relay", 18092),
        ("127.0.0.1", 80),
        ("127.0.0.1", 7777),
    ],
)
def test_bind_refuses_public_wildcard_hostname_privileged_and_blocked(host, port):
    with pytest.raises(ValueError, match="relay_bad_bind"):
        R.guard_bind(host, port)


@pytest.mark.parametrize(
    "values",
    [{"TRADEAI_N8N_RELAY_BEARER": ""}, {"TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": ""}, {"TRADEAI_N8N_RELAY_BEARER": "short"}],
)
def test_start_refuses_missing_or_short_secret(tmp_path, values):
    with pytest.raises(ValueError, match="relay_missing_secret"):
        R.Relay(environ={**env(tmp_path), **values}, allowlist=frozenset({LANE}))


def test_wrong_bearer_and_body_validation(tmp_path):
    r = relay(tmp_path)
    assert r.status(None)[0] == 401
    assert r.status("Bearer wrong")[0] == 401
    assert r.counts["auth_failures"] == 2
    assert r.run(f"Bearer {BEARER}", b"x" * (R.MAX_BODY + 1))[0] == 413
    assert r.run(f"Bearer {BEARER}", b"not-json")[0] == 400


def test_lane_and_live_gates_do_not_call_transport(tmp_path):
    calls = []
    r = relay(tmp_path, transport=lambda *_: calls.append(1) or (200, {"state": "REQUESTED"}))
    auth = f"Bearer {BEARER}"
    assert (
        r.run(
            auth,
            json.dumps({"lane_id": "not-allowed", "mode": "dry_run", "idempotency_key": "run-20261008-0001"}).encode(),
        )[1]["reason"]
        == "relay_lane_not_allowlisted"
    )
    assert (
        r.run(auth, json.dumps({"lane_id": LANE, "mode": "live", "idempotency_key": "run-20261008-0002"}).encode())[1][
            "reason"
        ]
        == "relay_live_not_enabled"
    )
    assert calls == []


def test_live_lane_forwards_signed_envelope_and_logs_without_secret(tmp_path):
    captured = {}

    def transport(url, payload):
        captured.update(url=url, payload=payload)
        return 200, {"schema": "RunRequested@v1", "state": "REQUESTED", "run_id": payload["idempotency_key"]}

    r = relay(tmp_path, transport=transport, TRADEAI_N8N_RELAY_LIVE_LANES=LANE)
    status, out = r.run(
        f"Bearer {BEARER}",
        json.dumps({"lane_id": LANE, "mode": "live", "workflow_id": "wf/one", "execution_id": "exec-1"}).encode(),
    )
    assert status == 200 and out["state"] == "REQUESTED"
    assert captured["url"].endswith("/v1/coordination")
    payload = captured["payload"]
    assert payload["route"] == "coordination/run" and payload["operation"] == "run"
    assert payload["claim"]["caller_id"] == "n8n-relay" and payload["claim"]["scope"] == "coordination_run"
    log = (tmp_path / "data/runtime/n8n_relay/relay_log.jsonl").read_text()
    assert BEARER not in log and KEY not in log
    assert payload["idempotency_key"].startswith("n8n-wf-wfone-exec-1")


def test_duplicate_reply_passes_through_and_transport_failure_is_502(tmp_path):
    r = relay(tmp_path, transport=lambda *_: (200, {"state": "RUNNING", "duplicate": True}))
    status, out = r.run(
        f"Bearer {BEARER}",
        json.dumps({"lane_id": LANE, "mode": "dry_run", "idempotency_key": "run-20261008-dup1"}).encode(),
    )
    assert status == 403 and out["duplicate"] is True
    failing = relay(tmp_path, transport=lambda *_: (_ for _ in ()).throw(OSError("down")))
    assert (
        failing.run(
            f"Bearer {BEARER}",
            json.dumps({"lane_id": LANE, "mode": "dry_run", "idempotency_key": "run-20261008-down1"}).encode(),
        )[1]["reason"]
        == "relay_gateway_unreachable"
    )


def test_transport_preserves_gateway_http_refusal(tmp_path, monkeypatch):
    body = json.dumps({"state": "REFUSED", "reason": "run_bad_mode"}).encode()

    def refused(*_args, **_kwargs):
        raise HTTPError("http://127.0.0.1:18091/v1/coordination", 403, "refused", {}, BytesIO(body))

    monkeypatch.setattr(R.urllib.request, "urlopen", refused)
    r = relay(tmp_path)
    status, out = r.run(
        f"Bearer {BEARER}",
        json.dumps({"lane_id": LANE, "mode": "dry_run", "idempotency_key": "run-20261008-http1"}).encode(),
    )
    assert status == 403
    assert out["reason"] == "run_bad_mode"
    assert out["gateway_http_status"] == 403
    assert r.counts["gateway_unreachable"] == 0


def test_direct_script_help_works_outside_repo():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/n8n_run_relay.py"), "--help"],
        cwd="/tmp",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--run-allowlist" in result.stdout


def test_status_and_unit_registry_contract():
    root = Path(__file__).resolve().parents[1]
    unit = (root / "config/systemd/user/tradeai-n8n-run-relay.service").read_text()
    assert "172.19.0.1:18092" in unit and "%h/trade-ai-releases/portfolio-server/CURRENT" in unit
    assert "TRADEAI_N8N_RELAY_BEARER" in unit and "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N" in unit
    assert "proposal" not in unit.lower() and "not installed" not in unit.lower()
    services = json.loads((root / "config/expected_services.json").read_text())["units"]
    assert sum(row.get("unit") == "tradeai-n8n-run-relay.service" for row in services) == 1
    assert "tradeai-n8n-run-relay.service" not in (root / "config/dev_tree_units_baseline.txt").read_text()


def test_every_emitted_refusal_is_declared():
    assert R.REFUSALS
    for reason in (
        "relay_bad_path",
        "relay_bad_bearer",
        "relay_body_too_large",
        "relay_malformed_body",
        "relay_lane_not_allowlisted",
        "relay_bad_mode",
        "relay_live_not_enabled",
        "relay_bad_run_id",
        "relay_gateway_unreachable",
    ):
        assert reason in R.REFUSALS
