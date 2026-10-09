"""N8N Maturity B5.3 — gateway `coordination/due`, the slot-key check in `run`, relay GET /due and the
mode-aware /runs/<lane>/last (design 02 §3.1, §3.3, §4).

Hermetic: tmp_path ledgers and registry/allowlist files, injected loaders, a fixed clock, an in-process
transport from the relay to the gateway's dispatch_http, one loopback HTTP server on an ephemeral port for the
relay routing test. No live ledger, no live port, no secret store, no send.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import n8n_coordination_gateway as SRV
from scripts import n8n_run_relay as R
from scripts.lib import n8n_coordination_gateway as G
from scripts.lib import n8n_due as D
from scripts.lib import n8n_retry_policy as RP
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerNonceStore, LedgerReceiptStore, LedgerRunStore

ROOT = Path(__file__).resolve().parents[1]
KEY = b"dispatch-key-not-a-live-secret-0123456"
N8N = b"k" * 48
BEARER = "b" * 48
SHA = "a" * 40
NOW = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)          # 10:00 America/New_York
LANE = "storage-watch"
KEY_0930 = f"d:{LANE}:dry_run:20261009T0930"
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")


def _registry():
    return [
        {"lane_id": LANE, "scheduler": {"kind": "cron", "expression": "x"},
         "dispatch": {"mode": "dry_run", "cron": ["30 9 * * *"], "class": "monitor", "priority": 3,
                      "retry_policy": "transient-2", "wave": "W1"}},
        {"lane_id": "backup-verify", "scheduler": {"kind": "cron", "expression": "x"},
         "dispatch": {"mode": "live", "cron": ["45 9 * * *"], "class": "hygiene", "priority": 2,
                      "retry_policy": "transient-2", "wave": "W1"}},
        {"lane_id": "maturity-remeasure", "scheduler": {"kind": "cron", "expression": "x"}},
    ]


def _entries():
    return {lane: {"lane_id": lane, "command": ["$PY", "x.py"], "dry_run_arg": ["--dry-run"], "live_arg": ["--write"]}
            for lane in (LANE, "backup-verify", "maturity-remeasure")}


def _sources(registry=None, entries=None, fail=None):
    def loader(name, value):
        def f():
            if fail == name:
                raise D.DueSourceError(f"{name}_unreadable", "test")
            return value, hashlib.sha256(name.encode()).hexdigest()
        return f
    return D.DueSources(loader("registry", registry if registry is not None else _registry()),
                        loader("allowlist", entries if entries is not None else _entries()),
                        loader("policies", POLICIES))


@pytest.fixture
def stores(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield ledger, LedgerNonceStore(ledger), LedgerReceiptStore(ledger), LedgerRunStore(ledger)
    ledger.close()


_NONCE = [0]


def _claim(*, caller="n8n-relay", scope=G.SCOPE_READ, key=N8N):
    _NONCE[0] += 1
    claim = {"v": 1, "caller_id": caller, "project": "trade-ai", "iat": NOW.timestamp(), "exp": NOW.timestamp() + 120,
             "nonce": f"nonce-due-{_NONCE[0]}", "scope": scope}
    return {"claim": claim, "signature": hmac.new(key, G.canonical(claim), hashlib.sha256).hexdigest()}


def _call(stores, body, *, scope=G.SCOPE_READ, caller="n8n-relay", key=N8N, due_sources="default", now=NOW,
          allow=frozenset({LANE, "backup-verify", "maturity-remeasure"})):
    _l, nonces, receipts, runs = stores
    req = {**_claim(caller=caller, scope=scope, key=key), **body}
    return G.handle_request(req, key=KEY, now=now, nonce_store=nonces, idempotency_store=receipts,
                            expected_origin_sha=SHA, caller_keys=G.build_caller_keys(KEY, n8n_key=N8N),
                            run_store=runs, run_allowlist=allow,
                            due_sources=_sources() if due_sources == "default" else due_sources)


def _due(stores, **body):
    return _call(stores, {"route": "coordination/due", "operation": "due", **body})


def _run(stores, key, *, mode="dry_run", lane=LANE, **kw):
    return _call(stores, {"route": "coordination/run", "operation": "run", "lane_id": lane, "mode": mode,
                          "idempotency_key": key, "requested_by": "n8n:dispatcher"}, scope=G.SCOPE_RUN, **kw)


# ── route + read scope ──────────────────────────────────────────────────────────────────────────

def test_due_route_is_allowed_and_carries_no_forbidden_token():
    assert "coordination/due" in G.ALLOWED_ROUTES and G.route_forbidden("coordination/due") is None
    for text in ("due", "coordination/due"):
        tokens = {t for t in re.split(r"[^a-z0-9]+", text) if t}
        assert not tokens & G.FORBIDDEN_ROUTE_TOKENS
        assert not any(tok in text.replace("/", "") for tok in G.FORBIDDEN_ROUTE_TOKENS if tok != "title")


def test_due_answers_a_read_scope_claim_from_either_caller(stores):
    for caller, key in (("n8n-relay", N8N), ("tradeai-dispatch", KEY)):
        out = _call(stores, {"route": "coordination/due", "operation": "due"}, caller=caller, key=key)
        assert out["schema"] == "DueResponse@v1" and out["ok"] is True
        assert [i["idempotency_key"] for i in out["items"]] == ["d:backup-verify:live:20261009T0945", KEY_0930]
        assert out["registry_sha"] == hashlib.sha256(b"registry").hexdigest()


def test_due_refuses_run_scope_and_cross_wired_operations(stores):
    assert _call(stores, {"route": "coordination/due", "operation": "due"}, scope=G.SCOPE_RUN)["reason"] == "bad_scope"
    assert _call(stores, {"route": "coordination/status", "operation": "due"})["reason"] == "unknown_operation"
    assert _call(stores, {"route": "coordination/due", "operation": "status"})["reason"] == "unknown_operation"


def test_due_writes_nothing(stores):
    ledger = stores[0]
    before = [tuple(r) for r in ledger._conn.execute("SELECT * FROM runs")]
    assert _due(stores)["ok"] is True
    assert [tuple(r) for r in ledger._conn.execute("SELECT * FROM runs")] == before == []


@pytest.mark.parametrize("delta,ok", [(89, True), (-89, True), (91, False), (-91, False)])
def test_due_clock_skew(stores, delta, ok):
    out = _due(stores, now=(NOW + timedelta(seconds=delta)).isoformat())
    if ok:
        assert out["ok"] is True
    else:
        assert out["state"] == "REFUSED" and out["reason"] == "due_clock_skew"
        assert out["schema"] != "DueResponse@v1"       # a refusal is the typed receipt, not the closed due schema


@pytest.mark.parametrize("body,code", [
    ({"now": "not-a-time"}, "due_clock_skew"),
    ({"source": "cron"}, "bad_source"),
    ({"lane_filter": ["no-such-lane"]}, "bad_lane_filter"),
    ({"lane_filter": [LANE] * 9}, "bad_lane_filter"),
    ({"lane_filter": LANE}, "bad_lane_filter"),
    ({"lane_filter": []}, "bad_lane_filter"),
])
def test_due_typed_refusals(stores, body, code):
    out = _due(stores, **body)
    assert out["state"] == "REFUSED" and out["reason"] == code and out["schema"] != "DueResponse@v1" and "ok" not in out


@pytest.mark.parametrize("fail,code", [("registry", "registry_unreadable"), ("allowlist", "allowlist_unreadable"),
                                       ("policies", "policies_unreadable")])
def test_due_source_failures_are_typed(stores, fail, code):
    out = _call(stores, {"route": "coordination/due", "operation": "due"}, due_sources=_sources(fail=fail))
    assert out["reason"] == code
    assert _call(stores, {"route": "coordination/due", "operation": "due"},
                 due_sources=None)["reason"] == "registry_unreadable"


def test_due_limit_lane_filter_and_serve_time_allowlist(stores):
    out = _due(stores, limit=1)
    assert out["limit"] == 1 and out["truncated"] == 1 and len(out["items"]) == 1
    assert _due(stores, limit=500)["limit"] == 100
    out = _due(stores, lane_filter=[LANE])
    assert [i["lane_id"] for i in out["items"]] == [LANE] and out["lane_filter"] == [LANE]
    narrowed = _call(stores, {"route": "coordination/due", "operation": "due"}, allow=frozenset({LANE}))
    assert [i["lane_id"] for i in narrowed["items"]] == [LANE]
    assert {e["lane_id"]: e["code"] for e in narrowed["errors"]} == {"backup-verify": "not_allowlisted"}


def test_dispatch_http_returns_the_closed_schema_unchanged(stores):
    _l, nonces, receipts, runs = stores
    body = json.dumps({**_claim(), "route": "coordination/due", "operation": "due"}).encode()
    status, out = SRV.dispatch_http("POST", "/v1/coordination", {}, body, key=KEY, expected_origin_sha=SHA,
                                    nonce_store=nonces, idempotency_store=receipts, now=NOW,
                                    caller_keys=G.build_caller_keys(KEY, n8n_key=N8N), run_store=runs,
                                    run_allowlist=frozenset({LANE}), due_sources=_sources())
    assert status == 200 and "proxy_headers_used_as_auth" not in out and "durable" not in out
    schema = json.loads((ROOT / "docs/implementation/n8n-maturity/schemas/due-response.schema.json").read_text())
    assert set(out) <= set(schema["properties"])


# ── _run with server-minted keys ────────────────────────────────────────────────────────────────

def test_run_accepts_a_due_key_and_records_the_slot_columns(stores):
    out = _run(stores, KEY_0930)
    assert out["schema"] == "RunRequested@v1" and out["state"] == "REQUESTED" and out["duplicate"] is False
    row = stores[3].get(KEY_0930)
    assert (row["slot_key"], row["attempt"], row["parent_run_id"], row["class"], row["priority"]) == \
        (KEY_0930, 1, None, "monitor", 3)
    # the replay of an accepted key is a duplicate, not a refusal (the slot is IN_FLIGHT now)
    again = _run(stores, KEY_0930)
    assert again["duplicate"] is True and again["state"] == "REQUESTED" and again["run_id"] == KEY_0930
    assert _due(stores)["counts"]["IN_FLIGHT"] == 1


@pytest.mark.parametrize("key,mode,state", [
    (f"d:{LANE}:dry_run:20261009T0931", "dry_run", "NOT_A_SLOT"),        # forged minute
    (f"d:{LANE}:dry_run:20261010T0930", "dry_run", "NOT_A_SLOT"),        # future slot
    (f"d:{LANE}:live:20261009T0930", "live", "MODE_MISMATCH"),          # registry dispatches dry_run
    (f"d:{LANE}:dry_run:20261009T0930", "live", "KEY_MISMATCH"),         # key and request disagree
    (f"d:{LANE}:dry_run:20261009T0930:a2", "dry_run", "ATTEMPT_MISMATCH"),
    (f"e:{LANE}:dry_run:20261009T0930", "dry_run", "UNSUPPORTED_SOURCE"),
    (f"g:{LANE}:dry_run:2026", "dry_run", "MALFORMED_KEY"),
])
def test_run_refuses_a_key_that_is_not_currently_due(stores, key, mode, state):
    out = _run(stores, key, mode=mode)
    assert out["state"] == "REFUSED" and out["reason"] == "run_slot_not_due" and out["slot_state"] == state
    assert stores[3].get(key) is None


@pytest.mark.parametrize("key", [
    f"D:{LANE}:dry_run:20261009T0930",                    # upper-case prefix is not a legacy key
    f"E:{LANE}:dry_run:20261009T0930",
    f"g:{LANE}:DRY_RUN:20261009T0930",
    f"d:{LANE.upper()}:dry_run:20261009T0930",
])
def test_run_refuses_case_variants_of_server_minted_prefixes(stores, key):
    out = _run(stores, key)
    assert out["state"] == "REFUSED" and out["reason"] == "run_slot_not_due"
    assert out["slot_state"] in ("MALFORMED_KEY", "KEY_MISMATCH")
    assert stores[3].get(key) is None


def test_run_replay_naming_another_lane_is_refused_not_answered(stores):
    assert _run(stores, KEY_0930)["state"] == "REQUESTED"
    out = _run(stores, KEY_0930, lane="backup-verify")
    assert out["state"] == "REFUSED" and out["slot_state"] == "KEY_MISMATCH" and "run_id" not in out
    out = _run(stores, KEY_0930, mode="live")
    assert out["state"] == "REFUSED" and out["slot_state"] == "KEY_MISMATCH"
    # defence in depth: a stored row whose lane differs from its key is never returned as a duplicate
    odd = f"d:{LANE}:dry_run:20261009T0800"
    stores[3].request(run_id=odd, lane_id="backup-verify", mode="dry_run", requested_by="t", caller_id="t",
                      now=NOW.timestamp())
    out = _run(stores, odd)
    assert out["state"] == "REFUSED" and out["slot_state"] == "KEY_MISMATCH"


def test_run_slot_key_for_an_unknown_lane_keeps_the_allowlist_refusal(stores):
    out = _run(stores, "d:not-a-lane:dry_run:20261009T0930", lane="not-a-lane")
    assert out["reason"] == "run_lane_not_allowlisted"


def test_run_slot_key_without_due_sources_is_refused(stores):
    assert _run(stores, KEY_0930, due_sources=None)["reason"] == "run_slot_not_due"


def test_attempt_two_only_when_retry_due(stores):
    runs = stores[3]
    assert _run(stores, KEY_0930)["state"] == "REQUESTED"
    assert _run(stores, KEY_0930 + ":a2")["slot_state"] == "IN_FLIGHT"
    runs.claim_next(now=NOW.timestamp() - 100)
    runs.finish(KEY_0930, state="RUN_FAILED", receipt={"exit_code": 75, "finished_at": (NOW - timedelta(seconds=10)).isoformat()})
    assert _run(stores, KEY_0930 + ":a2")["slot_state"] == "RETRY_WAIT"           # backoff 30 s not over
    later = NOW + timedelta(seconds=30)
    out = _run(stores, KEY_0930 + ":a2", now=later)
    assert out["state"] == "REQUESTED"
    row = runs.get(KEY_0930 + ":a2")
    assert (row["slot_key"], row["attempt"], row["parent_run_id"]) == (KEY_0930, 2, KEY_0930)


def test_legacy_keys_keep_todays_behaviour(stores):
    legacy = "n8n-wf-abc123-4567"
    out = _run(stores, legacy, due_sources=None)
    assert out["state"] == "REQUESTED" and out["duplicate"] is False
    row = stores[3].get(legacy)
    assert row["slot_key"] is None and row["attempt"] is None and row["class"] is None
    assert _run(stores, legacy, due_sources=None)["duplicate"] is True
    # a legacy key for a lane with no dispatch block at all is still accepted
    assert _run(stores, "run-20261009-remeasure-01", lane="maturity-remeasure", due_sources=None)["state"] == "REQUESTED"


# ── relay ───────────────────────────────────────────────────────────────────────────────────────

def _relay(tmp_path, stores, transport=None):
    _l, nonces, receipts, runs = stores

    def in_process(url, payload):
        assert url.endswith("/v1/coordination")
        return SRV.dispatch_http("POST", "/v1/coordination", {}, json.dumps(payload).encode(), key=KEY,
                                 expected_origin_sha=SHA, nonce_store=nonces, idempotency_store=receipts, now=NOW,
                                 caller_keys=G.build_caller_keys(KEY, n8n_key=N8N), run_store=runs,
                                 run_allowlist=frozenset({LANE, "backup-verify"}), due_sources=_sources())

    env = {"TRADEAI_N8N_RELAY_BEARER": BEARER, "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": N8N.decode(),
           "TRADEAI_STATE_ROOT": str(tmp_path)}
    return R.Relay(environ=env, allowlist=frozenset({LANE}), transport=transport or in_process,
                   clock=lambda: NOW.timestamp())


def _log_lines(tmp_path):
    p = tmp_path / "data" / "runtime" / "n8n_relay" / "relay_log.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_relay_due_passthrough_signs_read_scope_and_logs_one_liveness_line(tmp_path, stores):
    relay = _relay(tmp_path, stores)
    status, body = relay.due(f"Bearer {BEARER}", "source=schedule&limit=40")
    assert status == 200 and body["schema"] == "DueResponse@v1" and len(body["items"]) == 2
    lines = _log_lines(tmp_path)
    assert len(lines) == 1 and lines[0]["op"] == "due" and lines[0]["state"] == "OK" and lines[0]["items"] == 2
    assert relay.counts["due"] == 1


def test_relay_due_forwards_query_caps_limit_and_rejects_bad_queries(tmp_path, stores):
    seen = []

    def transport(url, payload):
        seen.append(payload)
        return 200, {"schema": "DueResponse@v1", "ok": True, "items": [], "truncated": 0}

    relay = _relay(tmp_path, stores, transport=transport)
    assert relay.due(f"Bearer {BEARER}", f"limit=500&lane={LANE},backup-verify")[0] == 200
    p = seen[-1]
    assert p["route"] == "coordination/due" and p["operation"] == "due" and p["claim"]["scope"] == G.SCOPE_READ
    assert p["limit"] == 100 and p["lane_filter"] == [LANE, "backup-verify"] and p["source"] == "schedule"
    assert p["now"].startswith("2026-10-09T14:00:00")
    assert relay.due(f"Bearer {BEARER}", "")[0] == 200 and seen[-1]["limit"] == 40
    for bad in ("limit=0", "limit=x", "foo=1", "lane=bad%20lane", "source=a&source=b"):
        status, body = relay.due(f"Bearer {BEARER}", bad)
        assert status == 400 and body["reason"] == "relay_bad_query", bad
    assert relay.due("Bearer wrong", "")[0] == 401
    assert len(seen) == 2


def test_relay_due_relays_a_gateway_refusal(tmp_path, stores):
    relay = _relay(tmp_path, stores)
    status, body = relay.due(f"Bearer {BEARER}", "lane=no-such-lane")
    assert status == 403 and body["reason"] == "bad_lane_filter"
    assert _log_lines(tmp_path)[-1]["state"] == "REFUSED" and _log_lines(tmp_path)[-1]["reason"] == "bad_lane_filter"


def test_relay_due_limit_accepts_only_short_ascii_digits(tmp_path, stores):
    """Blocker: str.isdigit() accepts Unicode digits ('²' -> int() ValueError, '١٢' -> 12) and arbitrarily long
    digit strings (int() of > 4300 digits raises). Only 1..3 ASCII digits reach int()."""
    seen = []

    def transport(url, payload):
        seen.append(payload)
        return 200, {"schema": "DueResponse@v1", "ok": True, "items": [], "truncated": 0}

    relay = _relay(tmp_path, stores, transport=transport)
    for bad in ("limit=%C2%B2", "limit=%D9%A1%D9%A2", "limit=%EF%BC%91", "limit=" + "1" * 5000, "limit=1000",
                "limit=0100", "limit=-1", "limit=+5", "limit= 5"):
        status, body = relay.due(f"Bearer {BEARER}", bad)
        assert status == 400 and body["reason"] == "relay_bad_query", bad[:40]
    assert seen == []
    assert relay.due(f"Bearer {BEARER}", "limit=999")[0] == 200 and seen[-1]["limit"] == D.MAX_LIMIT
    assert relay.due(f"Bearer {BEARER}", "limit=7")[0] == 200 and seen[-1]["limit"] == 7


def test_relay_due_validates_source_and_lane_count_before_logging(tmp_path, stores):
    seen = []

    def transport(url, payload):
        seen.append(payload)
        return 200, {"schema": "DueResponse@v1", "ok": True, "items": [], "truncated": 0}

    relay = _relay(tmp_path, stores, transport=transport)
    for bad in ("source=cron", "source=" + "x" * 5000, "source=SCHEDULE"):
        status, body = relay.due(f"Bearer {BEARER}", bad)
        assert status == 400 and body["reason"] == "relay_bad_query"
    nine = ",".join(f"lane-{i}" for i in range(D.MAX_LANE_FILTER + 1))
    assert relay.due(f"Bearer {BEARER}", f"lane={nine}")[0] == 400
    assert relay.due(f"Bearer {BEARER}", "lane=" + "a" * 5000)[0] == 400
    assert seen == []
    for line in _log_lines(tmp_path):                    # the raw source never reaches the log
        assert "source" not in line and len(json.dumps(line)) < 512
    eight = ",".join(f"lane-{i}" for i in range(D.MAX_LANE_FILTER))
    assert relay.due(f"Bearer {BEARER}", f"source=event&lane={eight}")[0] == 200
    assert len(seen[-1]["lane_filter"]) == D.MAX_LANE_FILTER


def test_relay_and_gateway_take_the_due_bounds_from_one_config():
    cfg = json.loads((ROOT / "config" / "n8n_due.json").read_text(encoding="utf-8"))
    assert (R.DUE_DEFAULT_LIMIT, R.DUE_MAX_LIMIT, R.DUE_MAX_LANES, R.DUE_SOURCES) == \
        (cfg["default_limit"], cfg["max_limit"], cfg["max_lane_filter"], D.SOURCES)
    assert (D.DEFAULT_LIMIT, D.MAX_LIMIT, D.MAX_LANE_FILTER, D.MAX_HELD, D.DEFAULT_TZ) == \
        (cfg["default_limit"], cfg["max_limit"], cfg["max_lane_filter"], cfg["max_held"], cfg["tz"])
    schema = json.loads((ROOT / "docs/implementation/n8n-maturity/schemas/due-response.schema.json").read_text())
    assert D.MAX_LIMIT <= schema["properties"]["limit"]["maximum"]
    assert D.MAX_LANE_FILTER <= schema["properties"]["lane_filter"]["maxItems"]
    assert D.MAX_HELD <= schema["properties"]["held"]["maxItems"]
    assert G.DUE_MAX_SKEW_S == 90                        # design 02 §3.1 (line 117) and F12


def test_relay_run_with_a_due_key_end_to_end(tmp_path, stores):
    relay = _relay(tmp_path, stores)
    _s, due = relay.due(f"Bearer {BEARER}", f"lane={LANE}")
    key = due["items"][0]["idempotency_key"]
    body = json.dumps({"lane_id": LANE, "mode": "dry_run", "idempotency_key": key}).encode()
    status, out = relay.run(f"Bearer {BEARER}", body)
    assert status == 200 and out["run_id"] == key
    status, out = relay.run(f"Bearer {BEARER}", body)
    assert out["duplicate"] is True
    forged = json.dumps({"lane_id": LANE, "mode": "dry_run", "idempotency_key": key[:-1] + "1"}).encode()
    status, out = relay.run(f"Bearer {BEARER}", forged)
    assert status == 403 and out["reason"] == "run_slot_not_due"


def test_relay_last_run_is_mode_aware(tmp_path, stores):
    ledger_file = tmp_path / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    ledger_file.parent.mkdir(parents=True)
    led = CoordinationLedger(ledger_file)
    runs = LedgerRunStore(led)
    for rid, mode, t in (("run-live-old", "live", 100), ("run-dry-new", "dry_run", 200)):
        runs.request(run_id=rid, lane_id=LANE, mode=mode, requested_by="t", caller_id="t", now=NOW.timestamp() + t)
    led.close()
    relay = _relay(tmp_path, stores)
    auth = f"Bearer {BEARER}"
    assert relay.last_run(auth, LANE)[1]["last"]["run_id"] == "run-dry-new"             # unchanged default
    assert relay.last_run(auth, LANE, "mode=live")[1]["last"]["run_id"] == "run-live-old"
    assert relay.last_run(auth, LANE, "mode=dry_run")[1]["last"]["run_id"] == "run-dry-new"
    for bad, reason in (("mode=paper", "relay_bad_mode"), ("mode=live&mode=dry_run", "relay_bad_mode"),
                        ("mode=", "relay_bad_mode"), ("x=1", "relay_bad_query")):
        status, body = relay.last_run(auth, LANE, bad)
        assert status == 400 and body["reason"] == reason, bad


def test_relay_http_routes_due_and_last_with_query(tmp_path, stores):
    import threading
    import urllib.error
    import urllib.request
    relay = _relay(tmp_path, stores)
    server = R.ThreadingHTTPServer(("127.0.0.1", 0), R.handler_for(relay))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def get(path):
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}{path}",
                                     headers={"Authorization": f"Bearer {BEARER}"})
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        status, body = get("/due?source=schedule&limit=5")
        assert status == 200 and body["schema"] == "DueResponse@v1"
        assert get(f"/runs/{LANE}/last?mode=live")[0] == 200
        assert get(f"/runs/{LANE}/last?mode=bogus")[0] == 400
        assert get("/due/extra")[0] == 404
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
