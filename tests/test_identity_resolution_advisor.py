"""The advisor may propose an identity. It may never establish one.

5,243 of 10,279 entities are UNRESOLVED_WITH_REASON and catalyst_graph skips
35,928 rows as symbol_not_registered — genuine ambiguity, which is the one part
of identity a model is right for.

The failure mode guarded here is the expensive one: a model that sounds certain,
writes a spine, and is believed. A wrong CANDIDATE costs a review. A wrong
CONFIRMED corrupts every downstream join permanently, because GUIDs are supposed
to be stable.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import identity_resolution_advisor as A  # noqa: E402

SRC = (ROOT / "scripts" / "lib" / "identity_resolution_advisor.py").read_text(encoding="utf-8")


def _code_only(text: str) -> str:
    """Strip docstrings — the prompt legitimately names CONFIRMED when telling
    the model what it may NOT emit, and a guard reading prose would flag it."""
    import ast
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


CODE = _code_only(SRC)


def test_it_can_only_ever_emit_candidate():
    assert A.PROPOSAL_STATUS == "CANDIDATE"
    emitted = [ln for ln in CODE.splitlines()
               if "CONFIRMED" in ln and "PROMPT" not in ln and "= '" not in ln]
    assert not emitted, f"CONFIRMED reachable in executable code: {emitted[:2]}"


def test_it_never_writes_the_registry():
    for banned in ("registry_path", "R.save", "save(", "write_text", "INSERT INTO"):
        assert banned not in CODE, f"advisor must not persist: {banned}"


def test_it_never_mints_a_guid():
    for banned in ("uuid5", "uuid4", "issuer_guid =", "security_guid ="):
        assert banned not in CODE


def test_proposals_are_flagged_for_review(monkeypatch):
    monkeypatch.setattr(A, "_free_chain_call",
                        lambda p: '{"match":"NOC","confidence":0.93,"reason":"same issuer"}')
    r = A.propose({"symbol": "NOC.B"}, [{"symbol": "NOC"}])
    assert r["identity_status"] == "CANDIDATE"
    assert r["requires_operator_review"] is True
    assert r["promotes_to_confirmed"] is False
    assert r["financial_action"] is False


def test_low_confidence_is_dropped_not_written_weakly(monkeypatch):
    monkeypatch.setattr(A, "_free_chain_call",
                        lambda p: '{"match":"NOC","confidence":0.4,"reason":"maybe"}')
    assert A.propose({"symbol": "NOC.B"}, [{"symbol": "NOC"}]) is None


def test_a_null_match_is_a_valid_answer(monkeypatch):
    """The prompt says null is preferred over a guess; the code must honour it."""
    monkeypatch.setattr(A, "_free_chain_call",
                        lambda p: '{"match":null,"confidence":0.99,"reason":"cannot distinguish"}')
    assert A.propose({"symbol": "X"}, [{"symbol": "Y"}]) is None


def test_unparseable_output_yields_nothing(monkeypatch):
    for junk in ("", None, "I think it's NOC", "{broken"):
        monkeypatch.setattr(A, "_free_chain_call", lambda p, j=junk: j)
        assert A.propose({"symbol": "X"}, [{"symbol": "Y"}]) is None


def test_a_dead_lane_yields_nothing_rather_than_raising(monkeypatch):
    def boom(p): raise RuntimeError("lane down")
    monkeypatch.setattr(A, "_free_chain_call", boom)
    try:
        A.propose({"symbol": "X"}, [{"symbol": "Y"}])
    except RuntimeError:
        raise AssertionError("a dead lane must not break the batch")


def test_no_candidates_means_no_call(monkeypatch):
    called = []
    monkeypatch.setattr(A, "_free_chain_call", lambda p: called.append(1) or "{}")
    assert A.propose({"symbol": "X"}, []) is None
    assert not called, "must not spend a lane call with nothing to compare against"


def test_the_free_chain_is_pinned():
    body = CODE
    assert "allow_paid=False" in body, "batch reconciliation must not use the paid lane"


def test_the_consumption_gate_is_not_bypassed():
    assert "process_id=" in SRC, "a fallback must not become a way around the gate"


def test_the_batch_is_capped():
    assert 0 < A.MAX_PER_RUN <= 200
