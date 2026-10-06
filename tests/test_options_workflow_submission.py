"""Real SQL ledger, isolated fake authorization/client: never a production order."""
import copy
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_options_lifecycle_migration import ephemeral_db  # noqa: F401
from test_options_workflow_execution import prepared
from brokers import approval_service, evidence_approval, execution_guard, execution_readiness
from brokers import options_order_pilot as pilot
import schwab_transport as transport


@pytest.fixture(autouse=True)
def isolated_database_only():
    # The shared schema fixture defaults to a live database elsewhere. These tests
    # require an explicit dedicated test database before the fixture can connect.
    if not os.environ.get("DB_NAME", "").endswith("_test"):
        pytest.skip("requires explicitly configured isolated *_test database")


@pytest.fixture()
def harness(monkeypatch, ephemeral_db):
    conn = ephemeral_db
    cur = conn.cursor()
    transport._pilot_ensure_table(cur)
    cur.execute("CREATE TABLE broker_order_intents (intent_id text PRIMARY KEY, intent_json jsonb)")
    conn.commit()
    p = prepared()
    p.update(id="fixture:r:reviewed", source_proposal_id="fixture-source")
    intent = pilot.build_intent("fixture", p)
    at = datetime.now(timezone.utc).isoformat()
    intent.meta.signal_evidence.update(
        final_quote_receipt={"environment": "live", "legs": [{**p["legs"][0], "quote_time": at}]},
        account_resources={"as_of": at})
    sent, consumed = [], []
    def fake_post(account, order):
        sent.append(copy.deepcopy(order))
        raise TimeoutError("isolated lost response")
    monkeypatch.setattr(transport, "_pilot_preconditions", lambda *a: conn)
    monkeypatch.setattr(transport, "build_client", lambda *a: (SimpleNamespace(place_order=fake_post), None))
    monkeypatch.setattr(transport, "_get_hash", lambda *a: "isolated-account")
    monkeypatch.setattr(transport, "_rate_acquire", lambda: None)
    monkeypatch.setattr(execution_guard, "require", lambda *a: None)
    monkeypatch.setattr(execution_readiness, "evaluate_execution_readiness", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(evidence_approval, "revalidate_before_submit", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(approval_service, "is_fully_approved", lambda *a: True)
    monkeypatch.setattr(approval_service, "consume", lambda iid: consumed.append(iid))
    monkeypatch.setattr(approval_service, "request_approval", lambda *a, **k: pytest.fail("production 2FA reached"))
    import schwab_token_manager
    monkeypatch.setattr(schwab_token_manager, "is_auth_failure", lambda *a: False)
    def save(i):
        cur.execute("INSERT INTO broker_order_intents VALUES (%s,%s::jsonb)",
                    (i.intent_id, json.dumps({"meta": {"signal_evidence": i.meta.signal_evidence}})))
        conn.commit()
    save(intent)
    return SimpleNamespace(intent=intent, conn=conn, sent=sent, consumed=consumed, save=save)


def submit(h):
    return transport.place_order("fixture", pilot.order_from_intent(h.intent), h.intent, kind="options")


def test_ambiguous_submit_and_new_intent_cannot_send_second_order(harness):
    h = harness
    first = submit(h)
    assert first["status"] == "submission_status_unknown"
    assert len(h.sent) == 1 and h.consumed == [h.intent.intent_id]
    assert submit(h)["existing"] and len(h.sent) == 1
    h.intent.intent_id = "different-confirmation"
    h.save(h.intent)
    assert submit(h)["existing"] and len(h.sent) == 1
    # Refreshing/revising cannot evade an unresolved response on this source.
    h.intent.intent_id = "different-revision"
    h.intent.meta.signal_evidence["proposal_id"] = "fixture:r:new"
    h.save(h.intent)
    assert submit(h)["existing"] and len(h.sent) == 1


@pytest.mark.parametrize("failure", ["stale_quote", "future_quote", "stale_resources", "expired_approval", "dry_receipt", "order_tamper"])
def test_last_boundary_refuses_without_contact(harness, monkeypatch, failure):
    h = harness
    ev = h.intent.meta.signal_evidence
    old = (datetime.now(timezone.utc) - timedelta(seconds=121)).isoformat()
    if failure == "stale_quote":
        ev["final_quote_receipt"]["legs"][0]["quote_time"] = old
    elif failure == "future_quote":
        ev["final_quote_receipt"]["legs"][0]["quote_time"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    elif failure == "stale_resources":
        ev["account_resources"]["as_of"] = old
    elif failure == "expired_approval":
        monkeypatch.setattr(approval_service, "is_fully_approved", lambda *a: False)
    elif failure == "dry_receipt":
        ev["final_quote_receipt"]["environment"] = "dry_test"
    order = pilot.order_from_intent(h.intent)
    if failure == "order_tamper":
        order["duration"] = "DAY"
    result = transport.place_order("fixture", order, h.intent, kind="options")
    assert result["status"] == "validation_blocked" and not result["broker_submitted"]
    assert h.sent == []


def test_explicit_broker_error_is_unknown_and_consumes_confirmation(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(transport, "build_client", lambda *a: (
        SimpleNamespace(place_order=lambda *a: SimpleNamespace(status_code=503)), None))
    assert submit(h)["status"] == "submission_status_unknown"
    assert h.consumed == [h.intent.intent_id]
