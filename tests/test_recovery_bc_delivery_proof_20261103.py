"""Canonical CI invocation for the B→C recovery delivery proof (piece F).

`scripts/verify_recovery_bc_delivery.py` exits 0 only when every proof holds, but nothing in CI ran it, so its
standalone exit code was not a ratchet (codex, 2026-11-03). This wrapper is the thin, standard-runner invocation:
it runs the SAME existing entrypoint once, reads its JSON document, and asserts the proof set by NAME and
cardinality — a skipped, renamed or silently dropped proof fails here.

No network, no DB, no Telegram, no order path: the script itself redirects every router/publisher store into a
temp directory and fakes only the raw transport.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "scripts" / "verify_recovery_bc_delivery.py"

#: Every proof the entrypoint must report, by name. A new stage must be added here deliberately.
EXPECTED_PROOFS = (
    "P1_one_page_for_recovering_t1",
    "P1b_t2_and_non_recovering_never_page",
    "P2_second_session_does_not_page_again_and_says_why",
    "P3_one_page_per_case_per_day_and_a_distinct_case_still_pages",
    "P3b_counterfactual_day_gate_disabled_repages_so_P3_is_not_vacuous",
    "P4_without_batching_the_transport_refuses_and_records_it",
    "P5_real_A_rows_and_actual_policy_through_the_real_router",
    "P6_repeat_within_the_floor_delivers_nothing_and_says_so",
    "P7_a_failed_delivery_is_retried_by_the_next_scheduled_pass",
    "P8_a_failed_state_write_pages_nothing",
)


@pytest.fixture(scope="module")
def proof_document() -> dict:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env.setdefault("TMPDIR", os.environ.get("TMPDIR", "/tmp"))
    proc = subprocess.run([sys.executable, str(PROOF), "--json"], capture_output=True, text=True,
                          timeout=900, cwd=str(ROOT), env=env)
    assert proc.returncode == 0, f"delivery proof failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}"
    return json.loads(proc.stdout)


def test_the_proof_reports_ok_and_every_expected_stage(proof_document):
    assert proof_document.get("schema") == "RecoveryBcDeliveryProof@v1"
    assert proof_document.get("ok") is True, {
        name: proof.get("pass") for name, proof in proof_document.get("proofs", {}).items()}


def test_the_proof_set_is_exactly_the_expected_names(proof_document):
    got = tuple(proof_document.get("proofs", {}))
    assert set(got) == set(EXPECTED_PROOFS), f"missing={set(EXPECTED_PROOFS) - set(got)} extra={set(got) - set(EXPECTED_PROOFS)}"
    assert len(got) == len(EXPECTED_PROOFS), f"cardinality changed: {len(got)} != {len(EXPECTED_PROOFS)}"


def test_no_stage_is_skipped_or_passing_by_absence(proof_document):
    for name, proof in proof_document["proofs"].items():
        assert proof.get("pass") is True, (name, proof)
        assert proof, f"{name} carries no evidence"
