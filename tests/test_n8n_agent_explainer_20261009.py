"""First n8n Agent payload: read-only lane-failure explainer. Nothing is imported."""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scripts import n8n_coordination_gateway as SRV
from scripts import n8n_lane_failure_explainer_workflow as GEN
from scripts import n8n_run_relay as RELAY
from scripts.lib import n8n_agent_reads as READS
from scripts.lib import n8n_coordination_gateway as GW
from scripts.lib import n8n_model_job as MJ

ROOT = Path(__file__).resolve().parent.parent
KEY = b"k" * 48
N8N_KEY = b"n" * 48
BEARER = "b" * 48
NOW = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)
LANE = "n8n-lab-watchdog"
BEHAVIOUR = ("size", "qty", "order", "stop", "limit", "weight", "trade")
_RUN_DDL = (
    "CREATE TABLE runs(run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_by TEXT, "
    "caller_id TEXT, requested_at TEXT, started_at TEXT, finished_at TEXT, exit_code INTEGER, "
    "duration_s REAL, receipt_json TEXT)"
)


def _keys():
    return GW.build_caller_keys(KEY, n8n_key=N8N_KEY)


def _claim(nonce: str, scope: str = "coordination_read") -> tuple[dict, str]:
    claim = {
        "v": 1,
        "caller_id": "n8n-relay",
        "project": "trade-ai",
        "iat": int(NOW.timestamp()),
        "exp": int(NOW.timestamp()) + 120,
        "nonce": nonce,
        "scope": scope,
    }
    return claim, GW.sign_claim(claim, N8N_KEY)


def _headers(nonce: str, scope: str = "coordination_read") -> dict[str, str]:
    claim, signature = _claim(nonce, scope)
    return {READS.CLAIM_HEADER: GW.canonical(claim).decode("ascii"), READS.SIGNATURE_HEADER: signature}


def _read(method: str, path: str, headers: dict | None, ledger: Path | None, registry: Path | None, nonce_store=None):
    return SRV.dispatch_http(
        method,
        path,
        headers or {},
        b"",
        key=KEY,
        expected_origin_sha="a" * 40,
        nonce_store=nonce_store if nonce_store is not None else {},
        idempotency_store={},
        now=NOW,
        caller_keys=_keys(),
        ledger_path=ledger,
        registry_path=registry,
    )


def _ledger(tmp_path: Path) -> Path:
    path = tmp_path / "ledger.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(_RUN_DDL)
    tail = "e" * 3000
    receipt = {
        "state": "RUN_FAILED",
        "exit_code": 1,
        "duration_s": 4.5,
        "stderr_tail": tail,
        "output_signal_mtime_after": NOW.timestamp() - 100,
        "stdout_tail": "do-not-return",
        "argv": ["do-not-return"],
    }
    older = {
        "state": "RUN_DONE",
        "exit_code": 0,
        "duration_s": 1.0,
        "stderr_tail": None,
        "output_signal_mtime_after": None,
    }
    rows = []
    for i in range(12):
        body = receipt if i == 0 else {**older, "exit_code": i}
        rows.append(
            (
                f"run-{i:02d}-explainer0001",
                LANE,
                "dry_run",
                body["state"],
                "n8n-relay",
                "n8n-relay",
                "2026-10-09T14:00:00+00:00",
                "2026-10-09T14:00:01+00:00",
                "2026-10-09T15:59:00+00:00" if i == 0 else f"2026-10-09T14:{i:02d}:00+00:00",
                body["exit_code"],
                body["duration_s"],
                json.dumps(body),
            )
        )
    conn.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return path


def _registry(tmp_path: Path) -> Path:
    path = tmp_path / "lane_registry.json"
    path.write_text(
        json.dumps(
            {
                "schema": "LaneRegistry@v1",
                "lanes": [
                    {
                        "lane_id": LANE,
                        "owner": "platform",
                        "scheduler": {"kind": "systemd", "expression": "tradeai-n8n-lab-watchdog.timer (5m)"},
                        "expected_cadence_hours": 0.1,
                        "output_signal": {"kind": "file_mtime", "path": "data/runtime/n8n_lab_watchdog_last.json"},
                        "note": "must not be returned",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _good_output() -> dict:
    return {
        "lane_id": LANE,
        "likely_cause": "the receipt exit code is 1",
        "evidence": [{"receipt_field": "exit_code", "detail": "exit_code=1"}],
        "next_check": "read the next receipt",
        "confidence": "low",
        "recommendation": "NONE",
        "authority": "READ_ONLY_ADVISORY",
    }


def test_tool_urls_contain_no_forbidden_route_token():
    workflow = GEN.build_workflow()
    tools = [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.httpRequestTool"]
    assert len(tools) == 3
    urls = [node["parameters"]["url"] for node in tools]
    assert any(url.endswith("/last") for url in urls)
    assert any("/recent?n=10" in url for url in urls)
    assert any("/lanes/" in url for url in urls)
    for url in urls:
        assert READS.forbidden_token(url) is None, url
        assert node_method_is_get(tools, url)
    model = next(node for node in workflow["nodes"] if node["name"] == GEN.NODE_MODEL)
    assert model["parameters"]["options"]["baseURL"] == GEN.BRIDGE_AGENT_PLACEHOLDER
    assert READS.forbidden_token(model["parameters"]["options"]["baseURL"]) is None
    assert "api.openai.com" not in json.dumps(workflow)


def node_method_is_get(tools, url) -> bool:
    node = next(item for item in tools if item["parameters"]["url"] == url)
    return node["parameters"]["method"] == "GET"


def test_output_schema_rejects_behaviour_fields():
    schema = MJ.load_schemas()["lane_failure_explainer/v1"]
    good = _good_output()
    assert MJ.validate(good, schema) == []
    assert schema["properties"]["recommendation"]["enum"] == ["NONE"]
    assert schema["properties"]["authority"]["enum"] == ["READ_ONLY_ADVISORY"]
    forbidden = {key.lower() for key in schema["forbidden_keys"]}
    assert forbidden == set(BEHAVIOUR)
    for field in BEHAVIOUR:
        top = dict(good)
        top[field] = 1
        assert MJ.validate(top, schema), field
        nested = dict(good)
        nested["evidence"] = [{"receipt_field": "state", field: 1}]
        assert MJ.validate(nested, schema) or MJ._forbidden_keys(nested, forbidden), field
    assert MJ.validate(dict(good, recommendation="BUY"), schema)
    assert MJ.validate(dict(good, authority="LIVE"), schema)


def test_read_endpoints_refuse_write_verbs(tmp_path):
    ledger = _ledger(tmp_path)
    registry = _registry(tmp_path)
    headers = _headers("nonce-write-1")
    paths = [f"/runs/{LANE}/last", f"/runs/{LANE}/recent?n=10", f"/lanes/{LANE}"]
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        for path in paths:
            status, body = _read(method, path, headers, ledger, registry)
            assert status == 405 and body["reason"] == "read_method_refused", (method, path, body)
    relay = RELAY.Relay(
        environ={
            "TRADEAI_N8N_RELAY_BEARER": BEARER,
            "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": N8N_KEY.decode(),
            "TRADEAI_STATE_ROOT": str(tmp_path),
            "TRADEAI_N8N_GATEWAY_URL": "http://127.0.0.1:9",
        },
        allowlist=frozenset({LANE}),
        read_transport=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("write reached the gateway")),
    )
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        for path in paths:
            status, body = relay.serve_read(f"Bearer {BEARER}", *READS.classify_read(path, method=method))
            assert status == 405 and body["reason"] == "read_method_refused", (method, path)


def test_recent_returns_receipt_fields_only_and_caps_n(tmp_path):
    ledger = _ledger(tmp_path)
    headers = _headers("nonce-recent-1")
    status, body = _read("GET", f"/runs/{LANE}/recent?n=10", headers, ledger, None)
    assert status == 200 and body["schema"] == READS.RECENT_SCHEMA and body["n"] == 10
    assert len(body["items"]) == 10
    assert set(body["items"][0]) == set(READS.RECEIPT_FIELDS)
    assert body["items"][0]["state"] == "RUN_FAILED"
    assert body["items"][0]["exit_code"] == 1
    assert body["items"][0]["duration_s"] == 4.5
    assert len(body["items"][0]["stderr_tail"].encode()) <= READS.STDERR_TAIL_MAX_BYTES
    assert "do-not-return" not in json.dumps(body["items"])
    assert body["items"][0]["output_signal_age_s"] == 100.0
    status, bad = _read("GET", f"/runs/{LANE}/recent?n=11", _headers("nonce-recent-2"), ledger, None)
    assert status == 400 and bad["reason"] == "read_bad_n"
    status, zero = _read("GET", f"/runs/{LANE}/recent?n=0", _headers("nonce-recent-3"), ledger, None)
    assert status == 400 and zero["reason"] == "read_bad_n"


def test_lane_read_returns_registry_subset(tmp_path):
    registry = _registry(tmp_path)
    status, body = _read("GET", f"/lanes/{LANE}", _headers("nonce-lane-1"), None, registry)
    assert status == 200 and body["schema"] == READS.LANE_SCHEMA
    assert body["owner"] == "platform"
    assert body["cadence"] == 0.1
    assert body["scheduler_kind"] == "systemd"
    assert body["output_signal"]["kind"] == "file_mtime"
    assert "note" not in body and "expression" not in body and "must not be returned" not in json.dumps(body)
    status, missing = _read("GET", "/lanes/no-such-lane", _headers("nonce-lane-2"), None, registry)
    assert status == 404 and missing["reason"] == "unknown_lane"


def test_reads_require_coordination_read_and_refuse_other_paths(tmp_path):
    ledger = _ledger(tmp_path)
    registry = _registry(tmp_path)
    status, body = _read("GET", f"/runs/{LANE}/last", None, ledger, registry)
    assert status == 403 and body["reason"] == "missing_signature"
    status, body = _read("GET", f"/runs/{LANE}/last", _headers("nonce-scope-1", "coordination_run"), ledger, registry)
    assert status == 403 and body["reason"] == "bad_scope"
    status, body = _read("GET", f"/runs/{LANE}/last", {"X-Forwarded-For": "127.0.0.1"}, ledger, registry)
    assert status == 403 and body["reason"] == "missing_signature" and body["proxy_headers_used_as_auth"] is False
    status, body = _read("GET", f"/runs/{LANE}/last", _headers("nonce-last-1"), ledger, registry)
    assert status == 200 and body["schema"] == READS.LAST_SCHEMA and body["last"]["state"] == "RUN_FAILED"
    for path in (f"/runs/{LANE}/stdout", f"/runs/{LANE}/last/extra", "/runs", "/lanes"):
        status, body = _read("GET", path, _headers("nonce-path-" + path[-4:]), ledger, registry)
        assert status == 404 and body["reason"] == "read_path_refused", path
    status, body = _read("GET", "/runs/broker-sync/last", _headers("nonce-forbid-1"), ledger, registry)
    assert status == 403 and body["reason"] == "forbidden_route:broker"
    status, other = _read("GET", "/v1/not-a-read", _headers("nonce-other-1"), ledger, registry)
    assert status == 404 and other["reason"] == "not_found"


def test_relay_reuses_last_and_proxies_recent_with_read_scope(tmp_path):
    seen = []

    def read_transport(url, claim, signature):
        seen.append((url, claim, signature))
        assert GW.sign_claim(claim, N8N_KEY) == signature
        assert claim["scope"] == "coordination_read" and claim["caller_id"] == "n8n-relay"
        return 200, {"schema": READS.RECENT_SCHEMA, "items": []}

    relay = RELAY.Relay(
        environ={
            "TRADEAI_N8N_RELAY_BEARER": BEARER,
            "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": N8N_KEY.decode(),
            "TRADEAI_STATE_ROOT": str(tmp_path),
            "TRADEAI_N8N_GATEWAY_URL": "http://127.0.0.1:9",
        },
        allowlist=frozenset({LANE}),
        transport=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("last must not POST")),
        read_transport=read_transport,
    )
    ledger = tmp_path / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    ledger.parent.mkdir(parents=True)
    conn = sqlite3.connect(ledger)
    conn.execute(_RUN_DDL)
    conn.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "run-new-explainer0001",
            LANE,
            "dry_run",
            "RUN_DONE",
            "n8n-relay",
            "n8n-relay",
            "2026-10-09T14:00:00+00:00",
            "2026-10-09T14:00:01+00:00",
            "2026-10-09T14:05:00+00:00",
            0,
            1.0,
            "{}",
        ),
    )
    conn.commit()
    conn.close()
    status, body = relay.serve_read(f"Bearer {BEARER}", *READS.classify_read(f"/runs/{LANE}/last", method="GET"))
    assert status == 200 and body["last"]["state"] == "RUN_DONE" and seen == []
    status, body = relay.serve_read(f"Bearer {BEARER}", *READS.classify_read(f"/runs/{LANE}/recent?n=4", method="GET"))
    assert status == 200 and seen[0][0].endswith(f"/runs/{LANE}/recent?n=4")
    status, body = relay.serve_read(f"Bearer {BEARER}", *READS.classify_read(f"/lanes/{LANE}", method="GET"))
    assert seen[1][0].endswith(f"/lanes/{LANE}") and seen[1][1]["scope"] == "coordination_read"
    status, body = relay.serve_read(None, *READS.classify_read(f"/runs/{LANE}/recent?n=4", method="GET"))
    assert status == 401 and body["reason"] == "relay_bad_bearer" and len(seen) == 2


def test_gateway_serves_a_relay_proxied_read(tmp_path):
    ledger = _ledger(tmp_path)
    registry = _registry(tmp_path)
    httpd = SRV.serve(
        "127.0.0.1",
        0,
        key=KEY,
        expected_origin_sha="a" * 40,
        ledger_path=ledger,
        n8n_key=N8N_KEY,
        registry_path=registry,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        relay = RELAY.Relay(
            environ={
                "TRADEAI_N8N_RELAY_BEARER": BEARER,
                "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": N8N_KEY.decode(),
                "TRADEAI_STATE_ROOT": str(tmp_path),
                "TRADEAI_N8N_GATEWAY_URL": f"http://127.0.0.1:{port}",
            },
            allowlist=frozenset({LANE}),
        )
        status, body = relay.serve_read(f"Bearer {BEARER}", *READS.classify_read(f"/lanes/{LANE}", method="GET"))
        assert status == 200 and body["scheduler_kind"] == "systemd" and body["owner"] == "platform"
        req = urllib.request.Request(f"http://127.0.0.1:{port}/runs/{LANE}/last", method="POST", data=b"{}")
        try:
            urllib.request.urlopen(req, timeout=3)
            raise AssertionError("POST was accepted")
        except urllib.error.HTTPError as exc:
            refused = json.loads(exc.read().decode())
            assert exc.code == 405 and refused["reason"] == "read_method_refused"
    finally:
        httpd.shutdown()
        thread.join(timeout=3)
        httpd.server_close()
        if getattr(httpd, "coordination_ledger", None) is not None:
            httpd.coordination_ledger.close()


def test_proposed_process_is_not_in_the_live_registry():
    proposed = json.loads((ROOT / "config" / "n8n_agent_processes.proposed.json").read_text(encoding="utf-8"))
    row = proposed["processes"][0]
    assert proposed["status"] == "PROPOSED" and row["status"] == "PROPOSED"
    assert row["id"] == "n8n_lane_failure_explainer"
    assert row["advisory_only"] is True and row["turn_cap"] == 4
    assert row["tools_allowed"] == ["read_runs_last", "read_runs_recent", "read_lane_row"]
    assert [row["routing"][key]["provider"] for key in ("primary", "secondary", "fallback")] == [
        "grok",
        "chatgpt",
        "deepseek",
    ]
    assert row["max_output_tokens"] == 800 and row["cost_ceiling_usd"] == 0.02
    live = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    assert row["id"] not in {item.get("id") for item in live["processes"]}
    assert row["id"] not in MJ.PROCESS_TASK_TYPE
    try:
        MJ.task_type_for(row["id"])
    except MJ.ModelJobRefused as exc:
        assert exc.code == "process_not_registered"
    else:
        raise AssertionError("proposed process was activated")
    templates = MJ.load_templates()
    assert "n8n_lane_failure_explainer@v1" in templates
    assert templates["n8n_lane_failure_explainer@v1"]["process_id"] == row["id"]


def test_shadow_workflow_is_inactive_and_not_an_import():
    workflow = GEN.build_workflow()
    assert workflow["active"] is False and workflow["shadow"] is True
    assert workflow["settings"]["shadow"] is True and workflow["meta"]["imported"] is False
    assert workflow["meta"]["mode"] == "dry_run"
    types = {node["type"] for node in workflow["nodes"]}
    assert "@n8n/n8n-nodes-langchain.agent" in types
    assert "@n8n/n8n-nodes-langchain.lmChatOpenAi" in types
    assert sum(node["type"] == "n8n-nodes-base.httpRequestTool" for node in workflow["nodes"]) == 3
    agent = next(node for node in workflow["nodes"] if node["type"] == "@n8n/n8n-nodes-langchain.agent")
    assert agent["parameters"]["options"]["maxIterations"] == 4
    source = (ROOT / "scripts" / "n8n_lane_failure_explainer_workflow.py").read_text(encoding="utf-8")
    assert "import:workflow" not in source and "docker" not in source
    assert GEN.check(ROOT / "docs" / "implementation" / "n8n-parallel" / "workflows" / "generated") == []
