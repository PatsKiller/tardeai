"""Hermetic tests for the n8n run relay; no 172.x bind and no live gateway."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
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


_RUN_DDL = (
    "CREATE TABLE runs(run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_by TEXT, "
    "caller_id TEXT, requested_at TEXT, started_at TEXT, finished_at TEXT, exit_code INTEGER, "
    "duration_s REAL, receipt_json TEXT)"
)


def _ledger(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _insert_runs(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(_RUN_DDL)
    conn.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def _run_row(run_id, lane, mode, state, finished):
    return (
        run_id,
        lane,
        mode,
        state,
        "n8n-relay",
        "n8n-relay",
        "2026-10-08T12:00:00+00:00",
        "2026-10-08T12:00:01+00:00",
        finished,
        0,
        1.0,
        "{}",
    )


@contextmanager
def _http(relay_obj):
    server = R.ThreadingHTTPServer(("127.0.0.1", 0), R.handler_for(relay_obj))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def _get(port: int, path: str, bearer: str | None = None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="GET")
    if bearer is not None:
        req.add_header("Authorization", bearer)
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read()
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_last_run_requires_bearer_rejects_bad_paths_and_returns_newest_row(tmp_path):
    calls = []

    def transport(*_args, **_kwargs):
        calls.append(1)
        return 200, {"state": "REQUESTED"}

    lane = "after-close-pipeline-close-capture"
    other = "premarket-data-pipeline"
    _insert_runs(
        _ledger(tmp_path),
        [
            _run_row("run-old", lane, "dry_run", "RUN_FAILED", "2026-10-08T15:00:00+00:00"),
            _run_row("run-new", lane, "live", "RUN_DONE", "2026-10-08T21:00:00+00:00"),
            _run_row("run-other", other, "live", "RUN_DONE", "2026-10-08T22:00:00+00:00"),
        ],
    )
    running = relay(tmp_path, transport=transport)
    with _http(running) as port:
        status, body = _get(port, f"/runs/{lane}/last")
        assert status == 401 and json.loads(body)["reason"] == "relay_bad_bearer"
        status, body = _get(port, f"/runs/{lane}/last", "Bearer wrong")
        assert status == 401 and json.loads(body)["reason"] == "relay_bad_bearer"
        for path in (
            f"/runs/{lane}/last/extra",
            f"/runs/{lane}",
            "/runs//last",
            "/nope",
            f"/runs/{lane}/Last",
            "/runs/bad%20lane/last",
        ):
            status, body = _get(port, path, f"Bearer {BEARER}")
            assert status == 404 and json.loads(body)["reason"] == "relay_bad_path", path
        assert R.parse_last_path("/runs/not a lane/last") is None
        assert R.parse_last_path(f"/runs/{lane}/last") == lane
        status, body = _get(port, f"/runs/{lane}/last", f"Bearer {BEARER}")
        assert status == 200 and len(body) <= R.MAX_BODY
        payload = json.loads(body)
        assert payload["schema"] == R.LAST_SCHEMA
        assert payload["lane_id"] == lane and payload["status"] == "OK"
        assert payload["last"]["run_id"] == "run-new"
        assert payload["last"]["state"] == "RUN_DONE"
        assert payload["last"]["mode"] == "live"
        assert payload["last"]["lane_id"] == lane
        assert payload["last"]["finished_at"] == "2026-10-08T21:00:00+00:00"
        assert "run-other" not in body.decode()
    assert calls == []


def test_last_run_empty_ledger_is_null_and_body_stays_within_cap(tmp_path):
    running = relay(tmp_path, transport=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("gateway")))
    with _http(running) as port:
        status, body = _get(port, "/runs/premarket-data-pipeline/last", f"Bearer {BEARER}")
    assert status == 200 and len(body) <= R.MAX_BODY
    payload = json.loads(body)
    assert payload["last"] is None and payload["status"] == "NO_LEDGER"
    huge = "r" * 1500
    _insert_runs(
        _ledger(tmp_path),
        [_run_row(huge, "premarket-data-pipeline", "dry_run", "RUN_DONE", "2026-10-08T21:00:00+00:00")],
    )
    running = relay(tmp_path)
    with _http(running) as port:
        status, body = _get(port, "/runs/premarket-data-pipeline/last", f"Bearer {BEARER}")
    assert status == 200 and len(body) <= R.MAX_BODY
    assert huge not in body.decode()
    assert json.loads(body)["last"]["state"] == "RUN_DONE"


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
