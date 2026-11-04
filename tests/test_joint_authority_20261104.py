"""The joint dispatch-authority invariant (2026-11-04).

Why this file exists: production drifted twice between the two boundaries that must agree before a model call —
the RUNTIME's registry resolution and the PERSISTED parent approval. First the record authorised retired ids the
registry refused (RegistryError, 2026-09-28 … 10-23); then the code moved to the canonical id and the record did not,
so every dispatch refused MODEL_MISMATCH (2026-10-26 …), and by 2026-11-04 the record was also expired while its
``authorization_status`` still read ACTIVE.

What is pinned here:
* a legacy allowed-model list cannot authorise a canonical selection — the refusal is named and typed, never silent;
* an expired record cannot authorise, whatever its status string says, and expiry is reported ahead of everything;
* renaming an allowed model in the record does not widen authority (the approval digest no longer matches);
* every refusal is a named reason and nothing is written or dispatched.

The mutation table is the acceptance criterion (cc5, 2026-11-04). Removing any one property from the implementation
must make tests fail, and the numbers are: delete the `allowed_models` membership check -> 2 failed; delete the expiry
check in `validate_policy` -> 4 failed; delete the approval-digest comparison -> 2 failed. Property B (expiry outranks
the status string) was the one whose removal left every test green, because the expiry rule had been written twice and
one copy masked the other; it now lives in `policy_expiry_verdict`/`validate_policy` only, and
`test_an_expired_record_that_is_otherwise_perfect_cannot_authorise` plus `test_expiry_outranks_the_status_string` are the
two that go red if it is removed or reordered.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import watch_review_policy_ledger as L  # noqa: E402

POLICY_ID = L.CANONICAL_POLICY_ID


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    names = ("LEDGER_ROOT", "POLICIES_DIR", "EXEC_DIR", "JOBS_DIR", "EVENT_STATE_DIR", "NO_CALL_DIR",
             "ARTIFACTS_DIR")
    for name in names:
        if hasattr(L, name):
            monkeypatch.setattr(L, name, tmp_path / name.lower())
    monkeypatch.setattr(L, "containment_required_ok", lambda: (True, "fixture"))
    return L


def _legacy_record(**overrides):
    """The live record as it stands today: legacy ids, PRO instead of PRO_THINK, no approval block."""
    pol = L.build_intended_policy(operator_id="fixture-operator")
    pol.update(allowed_models=["deepseek-v4-flash", "deepseek-v4-pro"], allowed_policies=["FAST", "PRO"])
    pol.pop("authority_approval", None)
    pol.update(overrides)
    return pol


def _write(record):
    (L.POLICIES_DIR).mkdir(parents=True, exist_ok=True)
    (L.POLICIES_DIR / f"{record['authorization_policy_id']}.json").write_text(__import__("json").dumps(record))


def test_an_expired_record_that_is_otherwise_perfect_cannot_authorise(ledger, monkeypatch):
    """Property B, the discriminating case: everything else about this record is valid — canonical model, matching
    policy, a live approval digest — and only the clock refuses it. Delete the expiry check and this test goes red
    (the dispatch would return OK and the child authorization would be written)."""
    ledger.persist_policy(ledger.build_intended_policy(operator_id="operator"))
    later = datetime.now(timezone.utc) + timedelta(days=120)     # past the 90-day expiry
    monkeypatch.setattr(ledger, "_now", lambda: later)
    ok, reason, _ = ledger.dispatch_authority("maria", record=ledger.load_policy(POLICY_ID))
    assert (ok, reason) == (False, "POLICY_EXPIRED")
    with pytest.raises(PermissionError, match="POLICY_EXPIRED"):
        ledger.create_execution_authorization(policy_id=POLICY_ID, symbol="FIXTURE", agent_id="maria",
                                              input_snapshot_id="snap", input_hash="h", trigger_reason="fixture")


def test_expiry_outranks_the_status_string(ledger):
    """Property B, the ordering half: an expired record reports EXPIRY even when its status string says something
    else, while an unexpired record still reports its status. Reorder the check behind the status (the pre-2026-11-04
    order) and the first assertion goes red."""
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    expired = ledger.build_intended_policy(operator_id="fixture")
    expired.update(expires_at=past, authorization_status="REVOKED", revoked_at=past)
    assert ledger.validate_policy(expired) == (False, "POLICY_EXPIRED")
    assert ledger.dispatch_authority("maria", record=expired)[:2] == (False, "POLICY_EXPIRED")
    # Control: the same status on a record that is still inside its window reports the status, so the assertion above
    # is about ORDER, not about the status being ignored.
    live = ledger.build_intended_policy(operator_id="fixture")
    live.update(authorization_status="REVOKED", revoked_at="2026-01-01T00:00:00+00:00")
    assert ledger.validate_policy(live) == (False, "POLICY_STATUS_REVOKED")


def test_a_legacy_allowed_model_list_refuses_with_a_named_reason(ledger):
    ok, reason, _ = ledger.dispatch_authority("maria", record=_legacy_record())
    assert (ok, reason) == (False, "MODEL_MISMATCH"), "a stale list must refuse, not silently pass"
    ok, reason, _ = ledger.dispatch_authority("cio", record=_legacy_record())
    assert (ok, reason) == (False, "MODEL_MISMATCH")


def test_a_canonical_policy_absent_from_allowed_policies_refuses_separately(ledger):
    # The second half of the live defect: even with the model fixed, CIO's PRO_THINK is absent from the record.
    pol = _legacy_record(allowed_models=["deepseek-flash"])
    ok, reason, _ = ledger.dispatch_authority("cio", record=pol)
    assert (ok, reason) == (False, "POLICY_MISMATCH")


def test_an_active_record_that_has_expired_cannot_authorise(ledger):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    pol = ledger.build_intended_policy(operator_id="fixture")
    pol["expires_at"] = past
    assert pol["authorization_status"] == "ACTIVE"          # the string still claims ACTIVE
    ledger.persist_policy(pol)                              # approved, with a VALID digest for this record
    ok, reason, _ = ledger.dispatch_authority("maria", record=ledger.load_policy(POLICY_ID))
    assert (ok, reason) == (False, "POLICY_EXPIRED"), "expiry must outrank the status string"


def test_expiry_is_reported_even_when_the_approval_digest_is_stale(ledger):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    pol = ledger.build_intended_policy(operator_id="fixture")
    ledger.persist_policy(pol)
    pol = ledger.load_policy(POLICY_ID)
    pol["expires_at"] = past                                # edited in place: digest no longer matches
    ok, reason, _ = ledger.dispatch_authority("maria", record=pol)
    assert (ok, reason) == (False, "POLICY_EXPIRED"), "the clock is a fact; the digest mismatch must not mask it"


def test_renaming_an_allowed_model_does_not_widen_authority(ledger):
    pol = _legacy_record()
    ledger.persist_policy(pol)                              # operator approves the LEGACY list
    # A hand edit renames the ids in place — exactly the "silent rename" the invariant must defeat.
    renamed = ledger.load_policy(POLICY_ID)
    renamed["allowed_models"] = ["deepseek-flash"]
    renamed["allowed_policies"] = ["FAST", "PRO_THINK"]
    assert renamed["authority_approval"]["digest"] != ledger.authority_digest(renamed)
    ok, reason, _ = ledger.dispatch_authority("cio", record=renamed)
    assert (ok, reason) == (False, "AUTHORITY_CHANGED_SINCE_APPROVAL")
    # And an explicit re-approval of the same fields is what makes it lawful again.
    ledger.persist_policy(renamed)
    ok, reason, _ = ledger.dispatch_authority("cio", record=ledger.load_policy(POLICY_ID))
    assert (ok, reason) == (True, "OK")


def test_a_record_without_an_approval_block_authorises_nothing(ledger):
    ok, reason, _ = ledger.dispatch_authority("maria", record=_legacy_record(allowed_models=["deepseek-flash"],
                                                                             allowed_policies=["FAST"]))
    assert (ok, reason) == (False, "AUTHORITY_NOT_APPROVED")


def test_a_caller_supplied_model_that_is_not_the_registry_id_refuses(ledger):
    ledger.persist_policy(ledger.build_intended_policy(operator_id="fixture"))
    ok, reason, _ = ledger.dispatch_authority("maria", model="deepseek-v4-pro", record=ledger.load_policy(POLICY_ID))
    assert (ok, reason) == (False, "MODEL_NOT_REGISTRY_CURRENT")


def test_create_execution_authorization_refuses_and_writes_nothing(ledger, monkeypatch):
    _write(_legacy_record())
    write = mock.Mock(side_effect=AssertionError("must refuse before any write"))
    monkeypatch.setattr(L, "_atomic_write", write)
    with pytest.raises(PermissionError, match="MODEL_MISMATCH"):
        L.create_execution_authorization(policy_id=POLICY_ID, symbol="FIXTURE", agent_id="maria",
                                         input_snapshot_id="snap", input_hash="h", trigger_reason="fixture")
    write.assert_not_called()


def test_the_operator_updates_the_record_and_dispatch_then_works_end_to_end(ledger):
    """Once D24 is answered the record change is the only remaining step — prove that path works."""
    ledger.persist_policy(ledger.build_intended_policy(operator_id="operator"))
    for agent, process, policy in (("maria", L.MARIA_PROCESS_ID, "FAST"),
                                   ("cio", L.CIO_PROCESS_ID, "PRO_THINK")):
        ex = L.create_execution_authorization(policy_id=POLICY_ID, symbol="FIXTURE", agent_id=agent,
                                              input_snapshot_id="snap", input_hash="h", trigger_reason="fixture")
        assert ex["authority_digest"] == ledger.authority_digest(ledger.load_policy(POLICY_ID))
        ok, reason, _ = L.validate_execution_authorization(
            ex["execution_authorization_id"], symbol="FIXTURE", agent_id=agent, process_id=process,
            provider="deepseek", model="deepseek-flash", policy=policy, input_hash="h")
        assert (ok, reason) == (True, "OK")


def test_a_child_authorization_dies_if_the_parent_authority_changes_under_it(ledger):
    ledger.persist_policy(ledger.build_intended_policy(operator_id="operator"))
    ex = L.create_execution_authorization(policy_id=POLICY_ID, symbol="FIXTURE", agent_id="maria",
                                          input_snapshot_id="snap", input_hash="h", trigger_reason="fixture")
    pol = ledger.load_policy(POLICY_ID)
    pol["allowed_models"] = ["deepseek-flash", "deepseek-chat"]   # widened in place, unapproved
    ledger._atomic_write(ledger.POLICIES_DIR / f"{POLICY_ID}.json", pol)
    ok, reason, _ = L.validate_execution_authorization(
        ex["execution_authorization_id"], symbol="FIXTURE", agent_id="maria", process_id=L.MARIA_PROCESS_ID,
        provider="deepseek", model="deepseek-flash", policy="FAST", input_hash="h")
    assert (ok, reason) == (False, "AUTHORITY_CHANGED_SINCE_APPROVAL")


def test_authority_digest_tracks_only_authority_fields(ledger):
    pol = ledger.build_intended_policy(operator_id="fixture")
    before = ledger.authority_digest(pol)
    pol["authorization_status"] = "ACTIVE"
    pol["persisted_at"] = "later"
    assert ledger.authority_digest(pol) == before, "a status/timestamp flip is not an authority change"
    pol["allowed_models"] = ["deepseek-flash", "deepseek-v4-pro"]
    assert ledger.authority_digest(pol) != before, "a model list change is"
