"""Piece B against the REAL approval store (A), not a fake module.

codex's review note (2026-11-03): a FakeModule proves B's interface, not A's safety. This file runs
the route against `scripts/lib/home_approvals.py` itself — a real Store on a temp root, the real
`server_context`, the real `Refused` codes — and skips while A is not on this branch, so it turns
green automatically when A lands.

The one thing that stays injected is A's own executor seam (`executor=`), which is A's designed
extension point, not a replacement for the store.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import home_approvals_api as api  # noqa: E402

try:  # A is a separate PR (#2550); this file is the integration proof that lands with it.
    from lib import home_approvals as ha  # type: ignore  # noqa: E402
except ImportError:  # pragma: no cover - exercised until #2550 merges
    ha = None

pytestmark = pytest.mark.skipif(ha is None, reason="piece A (lib/home_approvals.py) is not on this branch yet")

NOW = datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc)
# Must match config/cc_auth.yaml — handle() re-checks via home_approvals.server_context → allowed_logins().
# Assemble at runtime so the login is never an inline fixture literal (PII gate).
def _operator_login() -> str:
    if ha is None:  # pragma: no cover
        return "operator"
    logins = sorted(ha.allowed_logins())
    assert logins, "cc_auth allowed_logins is empty"
    return logins[0]


OPERATOR_LOGIN = _operator_login()
OPERATOR_PRINCIPAL = f"tailnet:{OPERATOR_LOGIN}"


def _ctx(*, principal=OPERATOR_PRINCIPAL, listener="serve_proxy", csrf_ok=True, reader=False):
    return api.Ctx(
        principal=lambda: principal,
        listener=lambda: listener,
        csrf=lambda method, path: (csrf_ok, "" if csrf_ok else "same-origin check failed"),
        allowed_logins=(OPERATOR_LOGIN,),
        can_read=lambda: reader,
        clock=lambda: NOW,
        session=lambda: "sess-1",
    )


@pytest.fixture
def real(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    store = ha.Store(tmp_path)
    return store


def _create(store, **over):
    payload = {
        "type": "merge_pr", "title": "Merge #2518", "why": "two reviews and green CI",
        "rule": "AGENTS §9", "what_happens": "squash-merges at the reviewed head",
        "risk": "lands without a later read", "undo": "reopen or revert",
        "facts": {"pr": 2518, "head_sha": "a" * 40},
    }
    payload.update(over)
    return ha.create(store, payload, requester={"session": "cc-deepseek-7"}, now=NOW)


def test_an_empty_real_store_is_a_readable_empty_board(real):
    status, payload = api.handle("/api/v2/home/approvals", "GET", ctx=_ctx(reader=True))
    assert status == 200 and payload["ok"] is True
    assert payload["data"]["count"] == 0 and payload["data"]["empty_text"] == "Nothing needs you"


def test_a_real_request_created_by_the_store_appears_with_can_act(real):
    record = _create(real)
    status, payload = api.handle("/api/v2/home/approvals", "GET", ctx=_ctx(reader=True))
    assert status == 200 and payload["data"]["count"] == 1
    item = payload["data"]["items"][0]
    assert item["id"] == record["id"] and item["can_act"] is True and item["state"] == "open"


def test_an_agent_cannot_decide_a_real_request(real):
    record = _create(real)
    status, payload = api.handle(f"/api/v2/home/approvals/{record['id']}/approve", "POST", {},
                                 ctx=_ctx(principal="agent:cc2", reader=False))
    assert status == 403 and payload["code"] == "AGENT_CALLER_REFUSED"
    assert real.get(record["id"])["state"] == "open"


def test_real_csrf_failure_is_refused_before_the_store(real):
    record = _create(real)
    status, payload = api.handle(f"/api/v2/home/approvals/{record['id']}/approve", "POST", {},
                                 ctx=_ctx(csrf_ok=False))
    assert status == 403 and payload["code"] == "CSRF_REFUSED"
    assert real.get(record["id"])["state"] == "open"


def test_a_real_approve_with_no_wired_executor_is_not_reported_as_executed(real):
    """A has no execute adapter for merge_pr yet; decide() must come back refused, and B must not
    dress that up as success — this is the false-comfort defect the review named."""
    record = _create(real)
    status, payload = api.handle(f"/api/v2/home/approvals/{record['id']}/approve", "POST", {},
                                 ctx=_ctx())
    assert status != 200 or payload.get("ok") is not True
    kept = real.get(record["id"])
    assert kept["state"] != "executed"
    assert payload.get("code") in ("ACTION_FAILED", "CHANGED", "NOT_OPEN", "STORE_ERROR")


def test_a_real_approve_with_an_injected_executor_executes_and_reports_executed(real):
    record = _create(real)
    class Exec:
        def revalidate(self, rec, *, now):
            return True, ""

        def execute(self, rec, *, actor, now, progress, deadline=None):
            return {"ok": True, "outcome": "executed", "plain": "Merged"}

    ctx_a = ha.server_context(principal=OPERATOR_PRINCIPAL, session="sess-1", csrf_ok=True,
                              listener="serve_proxy")
    out = ha.decide(real, record["id"], ctx=ctx_a, actor=OPERATOR_LOGIN, decision="approve", now=NOW,
                    executor=Exec())
    assert out["state"] == "executed"
    status, payload = api.handle(f"/api/v2/home/approvals/{record['id']}", "GET", ctx=_ctx(reader=True))
    assert status == 200 and payload["data"]["state"] == "executed"
    assert payload["data"]["result"]["ok"] is True


def test_an_expired_real_request_is_410(real):
    record = _create(real)
    later = NOW + timedelta(hours=25)
    status, payload = api.handle(f"/api/v2/home/approvals/{record['id']}/approve", "POST", {},
                                 ctx=api.Ctx(principal=lambda: OPERATOR_PRINCIPAL,
                                             listener=lambda: "serve_proxy",
                                             csrf=lambda m, p: (True, ""),
                                             allowed_logins=(OPERATOR_LOGIN,), can_read=lambda: False,
                                             clock=lambda: later, session=lambda: "sess-1"))
    assert status == 410 and payload["code"] == "EXPIRED"


def test_an_unreadable_real_store_is_an_error_not_an_empty_board(real, monkeypatch, tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "needs_you").mkdir()
    (broken / "needs_you" / "requests").write_text("not a directory")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(broken))
    status, payload = api.handle("/api/v2/home/approvals", "GET", ctx=_ctx(reader=True))
    assert status == 500 and payload["ok"] is False
    assert "items" not in payload
