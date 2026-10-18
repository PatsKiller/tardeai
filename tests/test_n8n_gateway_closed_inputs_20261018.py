"""Closed gateway inputs: temporary ledgers, fake HMAC keys, no socket or external effect."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from scripts import n8n_coordination_gateway as HTTP
from scripts.lib import n8n_coordination_gateway as G
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

KEY = b"campaign-fake-dispatch-key-0123456789"
RELAY_KEY = b"campaign-fake-relay-key-0123456789"
NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
LANE = "fixture-lane"
RUN_ID = "campaign-fixture-run-0123456789"


@pytest.fixture
def stores(tmp_path):
    ledger = CoordinationLedger(tmp_path / "fixture.sqlite")
    yield {"key": KEY, "expected_origin_sha": "a" * 40, "now": NOW, "nonce_store": {},
           "idempotency_store": {}, "caller_keys": G.build_caller_keys(KEY, n8n_key=RELAY_KEY),
           "run_store": LedgerRunStore(ledger), "run_allowlist": frozenset({LANE})}
    ledger.close()


def request():
    claim = {"v": 1, "caller_id": "n8n-relay", "project": "trade-ai", "iat": NOW.timestamp(),
             "exp": NOW.timestamp() + 120, "nonce": "campaign-nonce-0123456789", "scope": G.SCOPE_RUN}
    return {"route": "coordination/run", "operation": "run", "claim": claim,
            "signature": G.sign_claim(claim, RELAY_KEY), "lane_id": LANE, "mode": "dry_run",
            "idempotency_key": RUN_ID, "requested_by": "n8n:workflow:fixture-workflow"}


def call(req, stores):
    body = req if isinstance(req, bytes) else json.dumps(req).encode()
    return HTTP.dispatch_http("POST", "/v1/coordination", {}, body, **stores)


@pytest.mark.parametrize("field", ["arbitrary_action", "command", "grant_id", "parent_run_id", "workflow_id",
                                   "timeout_s", "schema_version"])
def test_unknown_run_authority_fields_refused_without_admission(field, stores):
    req = request()
    req[field] = "unregistered-value"
    status, result = call(req, stores)
    assert (status, result["state"], result["reason"]) == (403, "REFUSED", "unexpected_field")
    assert stores["run_store"].get(RUN_ID) is None


@pytest.mark.parametrize("location", ["top", "claim", "nested", "ignored_proxy"])
def test_duplicate_json_members_refused_before_authentication(location, stores):
    req = request()
    if location == "top":
        raw = json.dumps(req)[:-1] + ',"lane_id":"fixture-lane"}'
    elif location == "claim":
        claim = json.dumps(req["claim"])[:-1] + ',"nonce":"campaign-nonce-0123456789"}'
        raw = json.dumps(req).replace(json.dumps(req["claim"]), claim)
    elif location == "ignored_proxy":
        raw = json.dumps(req)[:-1] + ',"peer":"loopback","peer":"loopback"}'
    else:
        raw = json.dumps(req)[:-1] + ',"extension":{"same":1,"same":1}}'
    status, result = call(raw.encode(), stores)
    assert (status, result["state"], result["reason"]) == (400, "REFUSED", "malformed_event")
    assert stores["nonce_store"] == {} and stores["run_store"].get(RUN_ID) is None


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e309", "-1e309"])
def test_nonfinite_json_numbers_refused_before_authentication(literal, stores):
    raw = json.dumps(request())[:-1] + ',"extension":{"number":' + literal + '}}'
    status, result = call(raw.encode(), stores)
    assert (status, result["state"], result["reason"]) == (400, "REFUSED", "malformed_event")
    assert stores["nonce_store"] == {} and stores["run_store"].get(RUN_ID) is None


@pytest.mark.parametrize("iat,exp", [(float("nan"), float("nan")), (float("nan"), NOW.timestamp() + 120),
                                      (NOW.timestamp(), float("nan")), (float("inf"), float("inf")),
                                      (float("-inf"), float("-inf")), ("NaN", "NaN"),
                                      (NOW.timestamp(), "Infinity")])
def test_nonfinite_claim_lifetime_also_refused_on_in_process_path(iat, exp, stores):
    req = request()
    req["claim"].update(iat=iat, exp=exp)
    req["signature"] = G.sign_claim(req["claim"], RELAY_KEY)
    result = G.handle_request(req, **stores)
    assert result["state"] == "REFUSED" and result["reason"] == "malformed_claim"
    assert stores["nonce_store"] == {} and stores["run_store"].get(RUN_ID) is None


@pytest.mark.parametrize("version", [2, "1", True, 1.0])
def test_only_the_existing_integer_v1_claim_protocol_is_supported(version, stores):
    req = request()
    req["claim"]["v"] = version
    req["signature"] = G.sign_claim(req["claim"], RELAY_KEY)
    status, result = call(req, stores)
    assert status == 403 and result["state"] == "REFUSED" and result["reason"] == "bad_scope"
    assert stores["nonce_store"] == {} and stores["run_store"].get(RUN_ID) is None


@pytest.mark.parametrize("optional_requested_by", [True, False])
def test_existing_v1_producer_is_accepted_without_a_wire_or_persistence_migration(optional_requested_by, stores):
    req = request()
    if not optional_requested_by:
        req.pop("requested_by")
    status, result = call(req, stores)
    assert status == 200 and result["schema"] == "RunRequested@v1" and result["state"] == "REQUESTED"
    row = stores["run_store"].get(RUN_ID)
    assert row["mode"] == "dry_run" and row["requested_by"] == req.get("requested_by")


def test_an_unknown_additive_field_is_not_v1_compatible_even_on_replay(stores):
    req = request()
    assert call(req, stores)[1]["state"] == "REQUESTED"
    second = copy.deepcopy(req)
    second["claim"]["nonce"] += "-second"
    second["signature"] = G.sign_claim(second["claim"], RELAY_KEY)
    second["new_optional_authority"] = {"scope": "future-scope"}
    status, result = call(second, stores)
    assert status == 403 and result["reason"] == "unexpected_field"
    assert len(stores["run_store"].list()) == 1


def test_extra_credentials_keep_the_existing_typed_secret_refusal(stores):
    req = request()
    req["api_key"] = "fixture-not-a-credential"
    status, result = call(req, stores)
    assert status == 403 and result["reason"] == "secret_material"
    assert stores["run_store"].get(RUN_ID) is None


def test_host_catalogue_request_still_uses_the_same_closed_validator(stores):
    result = G.host_run_request(lane_id=LANE, mode="dry_run", run_id=RUN_ID, requested_by="host:fixture",
                                caller_id="fixture-host", run_store=stores["run_store"],
                                run_allowlist=stores["run_allowlist"], now=NOW.timestamp())
    assert result["schema"] == "RunRequested@v1" and result["state"] == "REQUESTED"
