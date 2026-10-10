"""W0 relay fix (2026-10-10): relay POST /event, the route table, the incident filter lanes, F4, and the
pre-import relay contract check.

Hermetic: the relay runs in-process or as a subprocess on 127.0.0.1 with tmp_path state; the gateway is the
library's handle_request called in-process with a memory store. No n8n, no live relay, gateway or ledger.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts import check_n8n_relay_contract as C
from scripts import n8n_run_relay as R
from scripts import n8n_workflow_templates as gen
from scripts.lib import n8n_coordination_gateway as G

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows"
KEY = "k" * 48
BEARER = "b" * 48
SHA = "a" * 40
AUTH = f"Bearer {BEARER}"
FOUR = ["tradeai-dispatcher", "tradeai-event-router", "tradeai-incident-router", "tradeai-digest-scheduler"]


def _env(tmp_path, **extra):
    return {
        "TRADEAI_N8N_RELAY_BEARER": BEARER,
        "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": KEY,
        "TRADEAI_STATE_ROOT": str(tmp_path),
        "TRADEAI_N8N_RELAY_ORIGIN_SHA": SHA,
        **extra,
    }


def _gateway_transport(lanes=frozenset({R.EVENT_LANE}), store=None, calls=None):
    """The real gateway library, in-process: claim verify, scope, event validation, idempotency."""
    store = {} if store is None else store
    nonces: dict[str, float] = {}

    def transport(url, payload):
        if calls is not None:
            calls.append((url, payload))
        reply = G.handle_request(
            payload, key=b"d" * 48, now=payload["claim"]["iat"], nonce_store=nonces, idempotency_store=store,
            expected_origin_sha=SHA, lane_allowlist=lanes,
            caller_keys=G.build_caller_keys(b"d" * 48, n8n_key=KEY.encode()),
        )
        return (200 if reply.get("state") != "REFUSED" else 403), reply

    return transport


def _relay(tmp_path, transport=None, **extra):
    return R.Relay(environ=_env(tmp_path, **extra), allowlist=frozenset({"n8n-lab-watchdog"}), transport=transport)


def _body(**over):
    body = {"lane_id": R.EVENT_LANE, "workflow_id": "tradeai-dispatcher", "execution_id": "1982",
            "node": "GET relay /due", "message": "Forbidden - perhaps check your credentials?"}
    body.update(over)
    return json.dumps(body).encode()


def _log(tmp_path):
    path = tmp_path / "data" / "runtime" / "n8n_relay" / "relay_log.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


# --------------------------------------------------------------------------- POST /event


def test_event_is_accepted_by_the_real_gateway_and_retry_is_a_duplicate(tmp_path):
    calls = []
    r = _relay(tmp_path, transport=_gateway_transport(calls=calls))
    status, reply = r.event(AUTH, _body())
    assert status == 200 and reply["state"] == "ACCEPTED" and reply["lane_id"] == R.EVENT_LANE
    url, payload = calls[0]
    assert url.endswith("/v1/coordination")
    assert payload["route"] == "coordination/event" and payload["operation"] == "accept_event"
    assert payload["claim"]["scope"] == G.SCOPE_READ and payload["claim"]["caller_id"] == G.RELAY_CALLER
    ev = payload["event"]
    assert set(ev) == G.EVENT_FIELDS and ev["origin_sha"] == SHA
    assert ev["idempotency_key"] == "wferr-tradeai-dispatcher-1982"
    assert "node=GET relay /due" in ev["subject_key"] and len(ev["subject_key"]) <= 200
    # n8n retryOnFail resends the same error: same event bytes, so the gateway replays instead of conflicting
    status2, reply2 = r.event(AUTH, _body())
    assert status2 == 200 and reply2["duplicate"] is True
    assert calls[1][1]["event"] == ev
    rows = [x for x in _log(tmp_path) if x.get("op") == "event"]
    assert [x["state"] for x in rows] == ["ACCEPTED", "ACCEPTED"] and rows[1]["duplicate"] is True
    assert rows[0]["workflow_id"] == "tradeai-dispatcher" and rows[0]["execution_id"] == "1982"


def test_gateway_without_the_lane_refuses_and_relay_passes_it_through(tmp_path):
    r = _relay(tmp_path, transport=_gateway_transport(lanes=frozenset(G.PILOT_LANES)))
    status, reply = r.event(AUTH, _body())
    assert status == 403 and reply["reason"] == "unknown_lane"
    assert _log(tmp_path)[-1]["reason"] == "unknown_lane"


@pytest.mark.parametrize(
    "body,status,reason",
    [
        (b"x" * (R.MAX_BODY + 1), 413, "relay_body_too_large"),
        (b"not-json", 400, "relay_malformed_body"),
        (b"[]", 400, "relay_bad_event"),
        (json.dumps({"lane_id": R.EVENT_LANE}).encode(), 400, "relay_bad_event"),
        (_body()[:-1] + b',"extra":1}', 400, "relay_bad_event"),
        (_body(lane_id="incident-fanin"), 403, "relay_event_lane_refused"),
        (_body(lane_id="n8n-pilot-dispatch"), 403, "relay_event_lane_refused"),
        (_body(workflow_id=""), 400, "relay_bad_event"),
        (_body(workflow_id="a b"), 400, "relay_bad_event"),
        (_body(execution_id="1/2"), 400, "relay_bad_event"),
        (_body(node=7), 400, "relay_bad_event"),
        (_body(message=None), 400, "relay_bad_event"),
    ],
)
def test_event_validation_never_reaches_the_gateway(tmp_path, body, status, reason):
    calls = []
    r = _relay(tmp_path, transport=lambda *a: calls.append(a) or (200, {"state": "ACCEPTED"}))
    got = r.event(AUTH, body)
    assert got == (status, {"state": "REFUSED", "reason": reason})
    assert calls == []


def test_event_needs_bearer_and_origin_sha(tmp_path):
    calls = []
    r = _relay(tmp_path, transport=lambda *a: calls.append(a) or (200, {}))
    assert r.event(None, _body())[0] == 401 and r.event("Bearer nope", _body())[0] == 401
    assert r.counts["auth_failures"] == 2
    bad = _relay(tmp_path / "x", transport=lambda *a: calls.append(a) or (200, {}),
                 TRADEAI_N8N_RELAY_ORIGIN_SHA="not-a-sha")
    assert bad.origin_sha is None   # a malformed override never falls back to another sha
    assert bad.event(AUTH, _body()) == (503, {"state": "REFUSED", "reason": "relay_no_origin_sha"})
    assert calls == []


def test_event_text_is_cleaned_bounded_and_secret_free(tmp_path):
    calls = []
    r = _relay(tmp_path, transport=_gateway_transport(calls=calls))
    msg = "auth Bearer abcdef0123 failed\nat postgres://u:p@h/db token " + "Z" * 40 + " sk-live_123 " + "m" * 300
    status, reply = r.event(AUTH, _body(message=msg, node="Node\x00\x1b with " + "n" * 100))
    assert status == 200, reply
    row = _log(tmp_path)[-1]
    assert len(row["message"]) <= R.EVENT_MESSAGE_MAX and len(row["node"]) <= R.EVENT_NODE_MAX
    for leaked in ("abcdef0123", "postgres://", "Z" * 40, "sk-live", "\n", "\x00"):
        assert leaked not in row["message"] + row["node"]
        assert leaked not in json.dumps(calls[0][1]["event"])
    assert BEARER not in (tmp_path / "data" / "runtime" / "n8n_relay" / "relay_log.jsonl").read_text()


def test_event_gateway_unreachable_is_502(tmp_path):
    def boom(*_):
        raise OSError("refused")

    r = _relay(tmp_path, transport=boom)
    assert r.event(AUTH, _body()) == (502, {"state": "REFUSED", "reason": "relay_gateway_unreachable"})
    assert r.counts["gateway_unreachable"] == 1


def test_event_cache_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "EVENT_CACHE_MAX", 3)
    r = _relay(tmp_path, transport=lambda *_: (200, {"state": "ACCEPTED"}))
    for i in range(6):
        assert r.event(AUTH, _body(execution_id=str(i)))[0] == 200
    assert list(r._events) == [f"wferr-tradeai-dispatcher-{i}" for i in (3, 4, 5)]


def test_new_refusals_are_declared():
    for reason in ("relay_bad_event", "relay_event_lane_refused", "relay_no_origin_sha", "relay_bad_query"):
        assert reason in R.REFUSALS


# --------------------------------------------------------------------------- route table over HTTP


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


def _call(port, method, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method,
                                 headers={"Authorization": AUTH, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_every_declared_route_is_served_and_nothing_else(tmp_path):
    r = _relay(tmp_path, transport=lambda *_: (200, {"state": "ACCEPTED", "schema": "x"}))
    concrete = {"/runs/<lane_id>/last": "/runs/n8n-lab-watchdog/last"}
    with _http(r) as port:
        for method, path in R.ROUTES:
            status, body = _call(port, method, concrete.get(path, path), b"{}" if method == "POST" else None)
            assert body.get("reason") != "relay_bad_path", (method, path, status, body)
            assert R.route_supported(method, concrete.get(path, path))
        for method, path in (("POST", "/events"), ("GET", "/event"), ("POST", "/due"), ("GET", "/run"),
                             ("GET", "/runs/a/b/last"), ("POST", "/status")):
            assert _call(port, method, path, b"{}" if method == "POST" else None)[1]["reason"] == "relay_bad_path"
            assert not R.route_supported(method, path)
        status, body = _call(port, "POST", "/event", _body())
        assert status == 200 and body["state"] == "ACCEPTED"


def test_routes_cli_prints_the_table(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["n8n_run_relay.py", "--routes"])
    assert R.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == R.ROUTES_SCHEMA
    assert {(x["method"], x["path"]) for x in out["routes"]} == set(R.ROUTES)


# --------------------------------------------------------------------------- generated workflows


def test_incident_filter_lanes_are_registry_rows_and_f4_is_closed():
    lanes = C.registry_lane_ids(ROOT / "config" / "lane_registry.json")
    assert set(gen.INCIDENT_FILTER_LANES) <= lanes
    assert gen.GENERIC_KINDS["incident-router"]["lanes"] == list(gen.INCIDENT_FILTER_LANES)
    for kind in gen.GENERIC_KINDS:
        wf = gen.build_generic(kind)
        assert wf["settings"]["saveManualExecutions"] is False
        assert isinstance(wf["settings"]["executionTimeout"], int) and wf["settings"]["executionTimeout"] > 0
        for node in wf["nodes"]:
            if node["type"] == C.HTTP_TYPE:
                assert 0 < node["parameters"]["options"]["timeout"] <= wf["settings"]["executionTimeout"] * 1000


def test_every_generated_relay_call_is_a_declared_route():
    table = C.declared_routes(ROOT / "scripts" / "n8n_run_relay.py")
    assert table == set(R.ROUTES)
    for kind in gen.GENERIC_KINDS:
        for call in C.http_calls(gen.build_generic(kind)):
            assert call["via_relay"] and C.route_in_table(call["method"], call["path"], table), (kind, call)


# --------------------------------------------------------------------------- contract check


def _doc(**settings):
    base = {"executionTimeout": 50, "saveManualExecutions": False}
    base.update(settings)
    return {"id": "w", "settings": base, "nodes": [
        {"name": "due", "type": C.HTTP_TYPE, "parameters": {
            "method": "GET", "url": C.RELAY_EXPR + "/due?source=schedule&lane=known,ghost",
            "options": {"timeout": 10000}}},
        {"name": "ev", "type": C.HTTP_TYPE, "parameters": {"method": "POST", "url": C.RELAY_EXPR + "/event",
                                                           "options": {}}},
        {"name": "slow", "type": C.HTTP_TYPE, "parameters": {"method": "POST", "url": C.RELAY_EXPR + "/run",
                                                             "options": {"timeout": 60000}}},
    ]}


def test_static_findings_cover_every_refusal_code():
    codes = [f["code"] for f in C.static_findings("w", _doc(), {"known"})]
    assert codes == ["lane_filter_unknown", "http_timeout_missing", "http_timeout_exceeds_execution"]
    codes = {f["code"] for f in C.static_findings("w", _doc(executionTimeout=None, saveManualExecutions=True),
                                                  {"known", "ghost"})}
    assert codes == {"execution_timeout_missing", "save_manual_executions_true", "http_timeout_missing"}


def test_check_static_passes_the_four_and_refuses_unregistered_filters():
    ok = C.check(WORKFLOWS, FOUR, registry=ROOT / "config" / "lane_registry.json", relay_root=ROOT)
    assert ok["verdict"] == "PASS" and ok["route_source"] == "static_ROUTES", ok["findings"]
    allsix = C.check(WORKFLOWS, [], registry=ROOT / "config" / "lane_registry.json", relay_root=ROOT)
    lanes = C.registry_lane_ids(ROOT / "config" / "lane_registry.json")
    expected = {lane for lane in ("heartbeat-watch", "approval-escalate") if lane not in lanes}
    got = {f["detail"].split()[0].split("=")[1] for f in allsix["findings"] if f["code"] == "lane_filter_unknown"}
    assert got == expected
    assert {f["code"] for f in allsix["findings"]} <= {"lane_filter_unknown"}


def test_check_fails_closed_on_a_relay_without_routes_and_on_a_404_probe(tmp_path):
    old = tmp_path / "scripts"
    old.mkdir()
    (old / "n8n_run_relay.py").write_text("# a relay that declares no ROUTES\n")
    res = C.check(WORKFLOWS, ["tradeai-incident-router"], registry=ROOT / "config" / "lane_registry.json",
                  relay_root=tmp_path)
    assert res["verdict"] == "REFUSED" and {f["code"] for f in res["findings"]} == {"route_table_unknown"}

    def probe(method, path, query):
        return (False, "404 relay_bad_path") if path == "/event" else (True, "502 relay_gateway_unreachable")

    res = C.check(WORKFLOWS, ["tradeai-incident-router"], registry=ROOT / "config" / "lane_registry.json",
                  relay_root=ROOT, probe=probe)
    assert [f["code"] for f in res["findings"]] == ["unsupported_route"]
    assert "POST /event -> 404 relay_bad_path" in res["findings"][0]["detail"]


def test_scratch_relay_probe_end_to_end(tmp_path, capsys):
    """Spawns this tree's relay on loopback with scratch state; nothing outside tmp_path is written."""
    rc = C.main(["--relay-root", str(ROOT), "--ids", ",".join(FOUR), "--scratch", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    summary = json.loads(out.strip().splitlines()[-1])
    assert summary["verdict"] == "PASS" and summary["route_source"] == "probe"
    assert "POST /event" in out and "relay_bad_path" not in out
    log = (tmp_path / "state" / "data" / "runtime" / "n8n_relay" / "relay_log.jsonl").read_text()
    assert '"op":"event"' in log and "relay_gateway_unreachable" in log
