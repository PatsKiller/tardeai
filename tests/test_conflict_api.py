from datetime import timedelta
from urllib.parse import quote

import pytest

from scripts.lib.cio_ask_api import Ctx
from scripts.lib.conflicts.api import approval_rows, handle
from tests.test_conflict_ledger import NOW, SUBJECT, KEY, conflict, ledger


def ctx(principal="tailnet:operator@example.com", listener="serve_proxy", csrf=True):
    return Ctx(principal=lambda: principal, listener=lambda: listener,
               csrf=lambda *_: (csrf, "fixture"), allowed_logins=frozenset({"operator@example.com"}))


def body(revision=1):
    return {"expected_revision": revision, "chosen_side": "WATCH", "reason": "fixture reviewed",
            "evidence_refs": ["fixture:v2"], "expires_at": (NOW + timedelta(days=7)).isoformat()}


@pytest.mark.parametrize("identity", ["service-token", "n8n", "agent", "tailnet:unknown@example.com", ""])
def test_agents_and_service_tokens_refused_before_mutation(tmp_path, identity):
    status, result = handle("/api/v3/conflicts/key/decision", "POST", body(), ctx=ctx(identity),
                            ledger=ledger(tmp_path), write_enabled=True, now=NOW)
    assert status == 403 and result["error"] == "AGENT_CALLER_REFUSED"
    assert not (tmp_path / "data").exists()


def test_operator_identity_csrf_revision_and_explicit_activation(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    url = "/api/v3/conflicts/" + quote(KEY, safe="") + "/decision"
    assert handle(url, "POST", body(), ctx=ctx(), ledger=st, now=NOW)[0] == 503
    assert handle(url, "POST", body(), ctx=ctx(csrf=False), ledger=st, write_enabled=True, now=NOW)[0] == 403
    assert handle(url, "POST", body(99), ctx=ctx(), ledger=st, write_enabled=True, now=NOW)[0] == 409
    status, result = handle(url, "POST", body(), ctx=ctx(), ledger=st, write_enabled=True, now=NOW)
    assert status == 200 and result["cleared"] is False
    assert result["event"]["decision"]["actor"] == "tailnet:operator@example.com"


def test_read_filters_paging_history_and_approvals_version_binding(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict(kind="NEEDS_OPERATOR", never_auto=True)], at=NOW, apply=True)
    first = approval_rows(tmp_path)["rows"][0]
    status, collection = handle("/api/v3/conflicts", "GET", query={"kind": ["NEEDS_OPERATOR"]}, ledger=st)
    assert status == 200 and collection["total"] == 1
    detail = handle("/api/v3/conflicts/" + KEY, "GET", ledger=st)[1]
    assert detail["history"] and detail["schema"] == "ConflictRecord@v1"
    st.reconcile(SUBJECT, [conflict(kind="NEEDS_OPERATOR", never_auto=True, summary="changed evidence")], at=NOW, apply=True)
    assert approval_rows(tmp_path)["rows"][0]["document"]["version"] != first["document"]["version"]


def test_batch_sections_and_data_error_adapter_preserve_missing_gaps_and_server_order(tmp_path):
    from scripts.lib.conflicts.api import data_error_section, sections_for_guids
    assert data_error_section(tmp_path)["gap"] and approval_rows(tmp_path)["total"] is None
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict(kind="DATA_ERROR", tier=1)], at=NOW, apply=True)
    section = data_error_section(tmp_path)
    assert section["findings"][0]["key"] == KEY and section["headline"]
    assert sections_for_guids(tmp_path, ["guid"])["guid"]["findings"][0]["key"] == KEY
