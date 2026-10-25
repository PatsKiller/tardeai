"""EXCEPTIONS_MATRIX rows the 2026-10-25 coverage audit found untested or unwired (operator 2026-10-25, verbatim:
"I need you to fix everything that's missing before deployment."). Fixtures only; no production state."""
from datetime import timedelta

import pytest

from scripts.lib.conflicts.engine import Input
from tests.test_conflict_rulebook import NOW, flags, run


def _decision(by, value, days=3):
    return Input(f"{by} decision", value, NOW - timedelta(hours=1), role="judgment",
                 metadata={"recorded_by": by, "reason": "fixture", "expires_at": NOW + timedelta(days=days)})


def test_t4_operator_decision_outranks_cio_decision():
    """T4: operator recorded decision > CIO recorded decision > curator."""
    fs = run("WATCH", _decision("cio", "AVOID"), _decision("operator", "BUY"), Input("desk", "BUY", NOW))
    # The operator's BUY is the canonical: the desk BUY agrees with it and nothing flags.
    assert flags(fs) == [] or all(f.rule != "U7" for f in flags(fs))
    agreements = [f for f in fs if f.kind == "AGREEMENT" and f.rule == "R6"]
    assert agreements and agreements[0].sides[0]["source"] == "operator decision"


def test_expired_decision_never_becomes_the_canonical():
    fs = run("WATCH", _decision("operator", "BUY", days=-1), Input("desk", "WATCH", NOW))
    assert all(s["source"] != "operator decision" for f in fs for s in f.sides)


def test_r7b_refresh_after_ten_trading_days_even_when_not_positive():
    old = Input("curator", "WATCH", NOW - timedelta(days=30), inputs_as_of=NOW - timedelta(days=30))
    fs = run(None, canonical=old)
    assert any(f.rule == "R7b" and f.action == "queue_refresh" for f in fs)
    recent = Input("curator", "WATCH", NOW - timedelta(days=4), inputs_as_of=NOW - timedelta(days=4))
    assert not any(f.rule == "R7b" for f in run(None, canonical=recent)), "non-positive: 2 trading days is not stale"


def test_r7_missing_stance_says_hold_when_held_and_watch_when_not():
    assert run(None, held=True)[0].summary.endswith("HOLD by default")
    assert run(None, held=False)[0].summary.endswith("WATCH by default")


@pytest.mark.parametrize("flag", ["archived", "expired", "unwatched", "paper"])
def test_expired_archived_and_unwatched_rows_never_flag(flag):
    assert run("ADD", Input("desk", "EXIT", NOW), held=True, context={flag: True}) == []


def test_r13_near_limit_is_an_agreement_note_not_a_flag():
    fs = run("ADD", held=True, context={"concentration_policy": {"instrument_class": "broad_fund", "weight_pct": 23,
                                                                  "limit_pct": 25, "near_limit_pct": 22.5}})
    assert flags(fs) == [] and any(f.rule == "R13" and f.kind == "AGREEMENT" for f in fs)


def test_t1_fact_mismatch_is_a_never_auto_data_error_and_freezes_judgment():
    fs = run("ADD", Input("positions", "12", NOW, role="fact", metadata={"mismatch": True}),
             Input("desk", "EXIT", NOW), held=True)
    assert {f.rule for f in flags(fs)} <= {"T1", "R12"}
    t1 = next(f for f in fs if f.rule == "T1")
    assert t1.kind == "DATA_ERROR" and t1.never_auto and t1.tier == 1
    assert not any(f.rule in {"U7", "R11"} for f in fs), "a fact disagreement freezes stance evaluation"


def test_r1_cadence_limit_and_refresh_only_to_a_producer_that_writes_the_input():
    stale = NOW - timedelta(days=5)
    # cadence 2 days -> superseded after min(14, 4) = 4 days.
    no_writer = Input("desk", "BUY", stale, inputs_as_of=stale, metadata={"cadence_days": 2})
    fs = run("WATCH", no_writer)
    sup = next(f for f in fs if f.kind == "SUPERSEDED")
    assert sup.rule == "R1" and sup.action == "none"
    writer = Input("desk", "BUY", stale, inputs_as_of=stale, metadata={"cadence_days": 2, "writes_compared_input": True})
    assert next(f for f in run("WATCH", writer) if f.kind == "SUPERSEDED").action == "queue_refresh"


def test_three_way_split_with_a_recorded_cio_side_needs_the_operator():
    """Never-auto: >=3-way splits including an operator/CIO side. A valid recorded decision becomes the canonical
    (T4), so the split carries its recorded_by side and is protected."""
    history = [{"key": "security:guid:R11", "signature": []}]
    fs = run("WATCH", _decision("cio", "BUY"), Input("desk", "WATCH", NOW), Input("advisory", "AVOID", NOW),
             held=False, history=history)
    r11 = [f for f in fs if f.rule == "R11"]
    assert r11 and r11[0].kind == "NEEDS_OPERATOR" and r11[0].never_auto
    assert any(s["source"] == "cio decision" for s in r11[0].sides)


def test_rulebook_loader_refuses_a_weakened_never_auto_list(tmp_path):
    import json

    from scripts.lib.conflicts.profiles.rulebook import load_rulebook

    doc = load_rulebook()
    assert len(doc["never_auto"]) == 12
    for dropped in doc["never_auto"]:
        path = tmp_path / f"rb-{dropped}.json"
        path.write_text(json.dumps({**doc, "never_auto": [x for x in doc["never_auto"] if x != dropped]}))
        with pytest.raises(ValueError):
            load_rulebook(path)


def test_no_t0_or_t1_finding_is_resolvable_by_a_decision(tmp_path):
    from scripts.lib.conflicts.engine import Subject
    from scripts.lib.conflicts.ledger import DECISION_SCHEMA, ConflictLedger

    subject = Subject("security", "guid", "FIXTURE", {"held": True, "identity_confirmed": True})
    fs = run("ADD", Input("kill", "ENGAGED", NOW, role="safety"),
             Input("positions", "12", NOW, role="fact", metadata={"mismatch": True}), held=True)
    hard = [f for f in fs if f.tier <= 1]
    assert {f.rule for f in hard} >= {"T0", "T1"}
    ledger = ConflictLedger(tmp_path, memory_writer=lambda e: True)
    ledger.reconcile(subject, hard, at=NOW, apply=True)
    for key, record in ledger.records().items():
        decision = {"schema": DECISION_SCHEMA, "actor_kind": "operator", "actor": "op", "chosen_side": "ADD",
                    "reason": "x", "evidence_refs": ["x"], "expires_at": (NOW + timedelta(days=1)).isoformat()}
        with pytest.raises(ValueError):
            ledger.transition(key, "decided", at=NOW, decision=decision, apply=False)
