"""Home v008 approvals API (piece B) — trust rails, refusal mapping, and the card contract.

Every test drives the real handler with an injected fake store: no network, no database, no A module
import. The three rails are asserted at the HTTP edge (operator session, CSRF, and A's typed refusals
for requester/approver and moved facts), plus the rule that an unreadable store is never an empty list.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import home_approvals_api as api  # noqa: E402

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)


class Refused(Exception):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code
        self.reason = reason


class FakeStore:
    """Stands in for A's on-disk store handle; A's functions below take it as their first argument."""

    def __init__(self, records):
        self.records = records


class FakeModule:
    """A's module surface B depends on: Store, Refused, server_context, list_open, decide, question."""

    Refused = Refused
    Store = type("Store", (), {"__init__": lambda self, root: setattr(self, "root", root)})

    def __init__(self, records=None):
        self.store = FakeStore(records or {})
        self.calls = []
        self.records = self.store.records

    @staticmethod
    def server_context(*, principal, session="", csrf_ok, listener):
        return {"principal": principal, "session": session, "csrf_ok": csrf_ok, "listener": listener}

    def list_open(self, store, *, now, limit=100):
        return [r for r in store.records.values() if r.get("state") == "open"]

    def decide(self, store, request_id, *, ctx, actor, decision, note="", now=None, executor=None, timeout_s=120.0):
        self.calls.append({"id": request_id, "actor": actor, "decision": decision, "ctx": ctx, "note": note})
        record = store.records.get(request_id)
        if record is None:
            raise Refused("unknown_request", "That request does not exist.")
        if decision == "approve" and record.get("requester", {}).get("session") == actor:
            raise Refused("approver_is_requester", "You asked for this, so you cannot approve it.")
        if record.get("blocked_reason"):
            raise Refused("facts_moved", "This changed. The lead will re-ask.")
        if record.get("state") == "expired":
            raise Refused("request_expired", "This expired; the lead will re-ask rather than approve it for you.")
        record["state"] = "executed" if decision == "approve" else "declined"
        record["result"] = {"ok": True, "plain": "Merged, going live in about 15 min"} if decision == "approve" else None
        return {"state": record["state"], "decision": {"by": actor, "at": (now or NOW).isoformat()},
                "message": "Merged" if decision == "approve" else "Declined", "result": record["result"],
                "receipt": {"ledger": "x", "digest": "y"}}

    def get(self, store, request_id):
        return store.records.get(request_id)

    def revalidate(self, store, record, *, now=None):
        self.calls.append({"id": record.get("id"), "revalidate": True})
        if record.get("moved"):
            return False, "This changed. The lead will re-ask."
        return True, ""

    def question(self, store, request_id, *, actor, note, now=None):
        if not str(note or "").strip():
            raise Refused("question_empty", "A question needs words the lead can answer.")
        self.calls.append({"id": request_id, "actor": actor, "question": note})
        record = store.records.get(request_id) or {"state": "open"}
        return record


def _ctx(*, principal="tailnet:operator", listener="serve_proxy", csrf_ok=True, reader=False):
    return api.Ctx(
        principal=lambda: principal,
        listener=lambda: listener,
        csrf=lambda method, path: (csrf_ok, "" if csrf_ok else "The request did not come from the Command Center page."),
        allowed_logins=("operator",),
        can_read=lambda: reader,
        clock=lambda: NOW,
    )


def _record(**over):
    base = {
        "schema": "HomeApprovalRequest@v1", "id": "apr-1", "type": "merge_pr", "title": "Merge #2518",
        "why": "Two reviews and green CI", "rule": "AGENTS §9", "what_happens": "Squash-merges #2518",
        "risk": "Lands without a later read", "undo": "Reopen or revert", "facts": {"pr": 2518, "head_sha": "a" * 40},
        "requester": {"session": "cc-deepseek-7", "label": "lead", "at": NOW.isoformat()},
        "created_at": NOW.isoformat(), "expires_at": (NOW + timedelta(hours=24)).isoformat(),
        "state": "open", "decided_by": None, "decision": None, "receipt": None,
    }
    base.update(over)
    return base


@pytest.fixture
def store(monkeypatch):
    fake = FakeModule({"apr-1": _record()})
    monkeypatch.setattr(api, "_store_module", lambda: fake)
    monkeypatch.setattr(api, "_store_handle", lambda module: module.store)
    return fake


def test_list_returns_the_card_contract(store):
    status, payload = api.handle("/api/v2/home/approvals", "GET", ctx=_ctx(principal="service-token", reader=True))
    assert status == 200 and payload["ok"] is True
    data = payload["data"]
    assert data["schema"] == "HomeApprovalsQueue@v1" and data["count"] == 1 and data["empty_text"] == "Nothing needs you"
    item = data["items"][0]
    for key in ("id", "type", "title", "why", "rule", "what_happens", "risk", "undo", "facts", "requester",
                "created_at", "expires_at", "state", "can_act", "blocked_reason", "age_seconds",
                "expires_in_seconds", "question", "reask_requested", "result", "decided_at"):
        assert key in item, key
    assert item["can_act"] is True and item["state"] == "open"


def test_summary_is_the_badge_source(store):
    status, payload = api.handle("/api/v2/home/approvals/summary", "GET", ctx=_ctx(reader=True))
    assert status == 200 and payload["data"]["count"] == 1
    assert payload["data"]["urgent_count"] == 0
    assert set(payload["data"]) == {"count", "urgent_count", "as_of"}


def test_read_without_authentication_is_refused(store):
    status, payload = api.handle("/api/v2/home/approvals", "GET", ctx=_ctx(principal="agent:cc2", reader=False))
    assert status == 403 and payload["code"] == "AGENT_CALLER_REFUSED"


def test_an_agent_cannot_approve(store):
    status, payload = api.handle("/api/v2/home/approvals/apr-1/approve", "POST",
                                 {"note": ""}, ctx=_ctx(principal="agent:cc2", reader=False))
    assert status == 403 and payload["code"] == "AGENT_CALLER_REFUSED"
    assert store.calls == [] and store.records["apr-1"]["state"] == "open"


def test_a_tailnet_identity_through_another_listener_is_not_the_operator(store):
    status, payload = api.handle("/api/v2/home/approvals/apr-1/approve", "POST", {},
                                 ctx=_ctx(listener="direct"))
    assert status == 403 and payload["code"] == "AGENT_CALLER_REFUSED"


def test_a_login_outside_allowed_logins_is_not_the_operator(store):
    status, payload = api.handle("/api/v2/home/approvals/apr-1/approve", "POST", {},
                                 ctx=_ctx(principal="tailnet:someone-else"))
    assert status == 403 and payload["code"] == "AGENT_CALLER_REFUSED"


def test_csrf_is_required_and_checked_before_the_store_is_touched(store):
    status, payload = api.handle("/api/v2/home/approvals/apr-1/approve", "POST", {},
                                 ctx=_ctx(csrf_ok=False))
    assert status == 403 and payload["code"] == "CSRF_REFUSED"
    assert store.calls == []


def test_the_operator_decision_passes_only_verified_rails_to_decide(store):
    status, payload = api.handle("/api/v2/home/approvals/apr-1/approve", "POST", {"note": "go"},
                                 ctx=_ctx())
    assert status == 200 and payload["ok"] is True and payload["data"]["state"] == "executed"
    call = store.calls[0]
    assert call["actor"] == "operator" and call["decision"] == "approve"
    assert call["ctx"] == {"principal": "tailnet:operator", "session": "", "csrf_ok": True, "listener": "serve_proxy"}


def test_requester_cannot_approve_its_own_request(store):
    store.records["apr-1"]["requester"]["session"] = "operator"
    status, payload = api.handle("/api/v2/home/approvals/apr-1/approve", "POST", {}, ctx=_ctx())
    assert status == 403 and payload["code"] == "SELF_APPROVAL_REFUSED"
    assert store.records["apr-1"]["state"] == "open"


def test_moved_facts_leave_the_request_open_with_a_plain_reason(store):
    store.records["apr-1"]["blocked_reason"] = "This changed. The lead will re-ask."
    status, payload = api.handle("/api/v2/home/approvals/apr-1/approve", "POST", {}, ctx=_ctx())
    assert status == 409 and payload["code"] == "CHANGED"
    assert payload["reason"] == "This changed. The lead will re-ask."
    assert payload["blocked_reason"] == payload["reason"] and payload["state"] == "open"
    assert store.records["apr-1"]["state"] == "open"


def test_expired_request_is_refused_and_not_auto_approved(store):
    store.records["apr-1"]["state"] = "expired"
    status, payload = api.handle("/api/v2/home/approvals/apr-1/approve", "POST", {}, ctx=_ctx())
    assert status == 410 and payload["code"] == "EXPIRED"


def test_decline_is_the_same_chokepoint(store):
    status, payload = api.handle("/api/v2/home/approvals/apr-1/decline", "POST", {}, ctx=_ctx())
    assert status == 200 and payload["data"]["state"] == "declined"
    assert store.calls[0]["decision"] == "decline"


def test_no_route_accepts_a_type_or_a_fact_override(store):
    # There is no create/execute route on the API: only list, summary, and the three verbs.
    for path, method in (("/api/v2/home/approvals", "POST"),
                         ("/api/v2/home/approvals/apr-1", "POST"),
                         ("/api/v2/home/approvals/apr-1/execute", "POST"),
                         ("/api/v2/home/approvals/apr-1/approve", "GET")):
        status, payload = api.handle(path, method, {"type": "grant", "facts": {"tier": "x"}}, ctx=_ctx())
        assert status in (404, 405), (path, method, status)
    assert store.calls == []


def test_an_unreadable_store_is_never_an_empty_list(monkeypatch):
    class Broken(FakeModule):
        def list_open(self, store, *, now, limit=100):
            raise Refused("store_unreadable", "The store could not be read, so it is an error rather than nothing.")

    monkeypatch.setattr(api, "_store_module", lambda: Broken({}))
    monkeypatch.setattr(api, "_store_handle", lambda module: module.store)
    status, payload = api.handle("/api/v2/home/approvals", "GET", ctx=_ctx(reader=True))
    assert status == 500 and payload["ok"] is False and payload["code"] == "STORE_ERROR"
    assert "items" not in payload


def test_question_is_recorded_and_delivered_without_deciding(store, monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_COORDINATION_ROOT", str(tmp_path))
    status, payload = api.handle("/api/v2/home/approvals/apr-1/question", "POST", {"note": "why now?"}, ctx=_ctx())
    assert status == 200 and payload["data"]["note_recorded"] is True and payload["data"]["delivered"] is True
    assert store.records["apr-1"]["state"] == "open"
    assert any(c.get("question") == "why now?" for c in store.calls)
    delivered = list((tmp_path / "coordinator" / "inbox" / "cc-deepseek-7").glob("*v008-question*"))
    assert len(delivered) == 1 and "why now?" in delivered[0].read_text()


def test_expired_is_derived_from_the_clock_even_when_the_state_says_open(store):
    store.records["apr-1"]["expires_at"] = (NOW - timedelta(minutes=1)).isoformat()
    status, payload = api.handle("/api/v2/home/approvals", "GET", ctx=_ctx(reader=True))
    item = payload["data"]["items"][0]
    assert item["state"] == "expired" and item["can_act"] is False


def test_unknown_paths_and_methods_are_refused(store):
    assert api.handle("/api/v2/other", "GET", ctx=_ctx()) is None
    status, payload = api.handle("/api/v2/home/approvals", "DELETE", ctx=_ctx())
    assert status == 405 and payload["code"] == "METHOD_NOT_ALLOWED"


def test_a_plain_sentence_from_the_store_is_returned_verbatim(monkeypatch):
    """A's Refused carries .plain; the card shows that sentence as written, never a reworded one."""

    class PlainRefused(Exception):
        def __init__(self, code, plain):
            super().__init__(plain)
            self.code = code
            self.plain = plain

    class Module(FakeModule):
        def decide(self, store, request_id, *, ctx, actor, decision, note="", **kw):
            raise PlainRefused("facts_moved", "This changed. The lead will re-ask.")

    fake = Module({"apr-1": _record()})
    monkeypatch.setattr(api, "_store_module", lambda: fake)
    monkeypatch.setattr(api, "_store_handle", lambda module: module.store)
    status, payload = api.handle("/api/v2/home/approvals/apr-1/approve", "POST", {}, ctx=_ctx())
    assert status == 409 and payload["code"] == "CHANGED"
    assert payload["reason"] == "This changed. The lead will re-ask."


def test_a_store_that_cannot_be_read_is_not_an_empty_board(monkeypatch, tmp_path):
    """list_open raises store_unreadable when the store cannot be read; the route must not say ok."""
    class Module(FakeModule):
        def list_open(self, store, *, now=None, limit=100):
            raise Refused("store_unreadable", "The store could not be read, so nothing is shown.")

    fake = Module({})
    monkeypatch.setattr(api, "_store_module", lambda: fake)
    monkeypatch.setattr(api, "_store_handle", lambda module: module.store)
    status, payload = api.handle("/api/v2/home/approvals", "GET", ctx=_ctx(reader=True))
    assert status == 500 and payload["ok"] is False and payload["code"] == "STORE_ERROR"


def test_one_request_endpoint_for_the_confirm_sheet(store):
    status, payload = api.handle("/api/v2/home/approvals/apr-1", "GET", ctx=_ctx(reader=True))
    assert status == 200 and payload["data"]["id"] == "apr-1"
    assert "revalidated" not in payload["data"]
    assert store.calls == []


def test_revalidate_on_one_request_is_one_check_and_shows_the_refusal(store):
    store.records["apr-1"]["moved"] = True
    status, payload = api.handle("/api/v2/home/approvals/apr-1", "GET",
                                 query={"revalidate": "1"}, ctx=_ctx(reader=True))
    assert status == 200 and payload["data"]["revalidated"] is True
    assert payload["data"]["can_act"] is False
    assert payload["data"]["blocked_reason"] == "This changed. The lead will re-ask."
    assert [c for c in store.calls if c.get("revalidate")] == [{"id": "apr-1", "revalidate": True}]


def test_a_missing_request_is_404(store):
    status, payload = api.handle("/api/v2/home/approvals/nope", "GET", ctx=_ctx(reader=True))
    assert status == 404 and payload["code"] == "NOT_FOUND"
