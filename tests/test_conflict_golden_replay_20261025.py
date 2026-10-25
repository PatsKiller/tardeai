"""Golden replay of real stored state (EXCEPTIONS_MATRIX.md "golden replay", gap (f) 2026-10-25).

The 2026-10-24 capture of the 31 live flags was never saved. tests/fixtures/conflicts/golden_20261025/inputs.json is
a read-only capture of 2026-10-25 18:22Z state built by scripts/conflict_golden_capture.py (served Watch read model,
CIO truth holdings/risk, the cio-prospect-shadow build, the stored re-entry desk snapshot, the identity registry).
expected.json is the reviewed table: every subject's findings for the resolver's first run and its confirming second
run (R15: a new flag needs two consecutive runs). Deviations from the matrix's ~17/5/4/3 estimate are documented in
docs/ops/CONFLICT_GOLDEN_REPLAY_20261025.md. A rule change that moves any subject must update both, reviewed.
"""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path

import pytest

from scripts.lib.conflicts.adapters import evaluate_inputs, security_inputs_from_truth
from scripts.lib.conflicts.profiles.vocabulary import ordinal

FIXTURE = Path(__file__).resolve().parent / "fixtures/conflicts/golden_20261025"
INPUTS = json.loads((FIXTURE / "inputs.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
NOW = datetime.fromisoformat(INPUTS["now"])
FLAGS = {"GATE", "CONFLICT", "DATA_ERROR", "NEEDS_OPERATOR"}


def replay(subject):
    """Two resolver runs: observations carried exactly as scripts/conflict_resolver.py records them."""
    history, runs = [], []
    for _ in range(2):
        bundle = security_inputs_from_truth(subject["truth"], card=subject["card"], reentry=subject["reentry"])
        findings = evaluate_inputs(bundle, now=NOW, history=list(history))
        held = bundle.subject.context.get("held")
        for f in findings:
            if f.rule in {"R15", "U7", "R11"}:
                history.append({"key": f.key, "signature": sorted([s["source"], ordinal(s["value"], held)] for s in f.sides)})
        runs.append(findings)
    return runs


@pytest.fixture(scope="module")
def results():
    return {s["symbol"]: replay(s) for s in INPUTS["subjects"]}


def label(findings):
    return sorted(f"{f.kind}:{f.rule}" for f in findings)


def test_fixture_is_a_read_only_capture_without_secrets():
    assert INPUTS["schema"] == "ConflictGoldenFixture@v1" and INPUTS["counts"]["subjects"] == len(INPUTS["subjects"])
    text = (FIXTURE / "inputs.json").read_text(encoding="utf-8").lower()
    for marker in ("password", "secret", "api_key", "token", "bearer ", "authorization:"):
        assert marker not in text, marker
    assert set(INPUTS["sources"]) == {"watch", "holdings", "risk", "cio_shadow", "reentry_snapshot"}


def test_every_subject_matches_the_reviewed_table(results):
    assert set(results) == set(EXPECTED["subjects"])
    moved = {sym: {"run1": label(r[0]), "run2": label(r[1])} for sym, r in results.items()
             if {"run1": label(r[0]), "run2": label(r[1])} != EXPECTED["subjects"][sym]}
    assert not moved, f"{len(moved)} subjects moved; review and update expected.json + the doc: {dict(list(moved.items())[:5])}"


def test_summary_counts(results):
    for n, run in ((0, "run1"), (1, "run2")):
        counts = Counter(f.kind for r in results.values() for f in r[n])
        assert dict(sorted(counts.items())) == EXPECTED["summary"][run]
    assert EXPECTED["summary"]["flagged_subjects_run2"] == sum(
        1 for r in results.values() if any(f.kind in FLAGS for f in r[1]))


def test_two_run_rule_turns_each_observation_into_one_confirmed_conflict(results):
    observed = {sym for sym, r in results.items() if any(f.rule == "R15" for f in r[0])}
    confirmed = {sym for sym, r in results.items() if any(f.kind == "CONFLICT" for f in r[1])}
    assert observed == confirmed and not any(f.kind == "CONFLICT" for r in results.values() for f in r[0])


def test_matrix_invariants_hold_on_real_state(results):
    for sym, (first, second) in results.items():
        for f in first + second:
            if f.kind in FLAGS:
                assert f.clears_when and f.clears_when != "—", (sym, f.key)
                assert f.owner and f.next_run, (sym, f.key)
            if f.tier <= 1:
                assert f.kind in {"GATE", "DATA_ERROR", "NEEDS_OPERATOR"}, (sym, f.key)
            if f.rule in {"T0", "R12", "R16"}:
                assert f.never_auto, (sym, f.key)
            if f.kind == "SUPERSEDED":
                # R1: refresh is queued only to a producer that writes the compared input.
                assert f.action in {"queue_refresh", "none"}
                if f.sides[0]["source"] in {"watchlist_final_synthesis", "reentry_decision_desk"}:
                    assert f.action == "none", (sym, f.key)


def test_named_matrix_cases_on_todays_state(results):
    second = {sym: label(r[1]) for sym, r in results.items()}
    # Trade AI STALE names gate go-actions (matrix "newly visible gaps": QCOM/HPE/KBR/LMT Trade AI STALE).
    for sym in ("QCOM", "HPE", "KBR", "LMT"):
        assert "GATE:R3" in second[sym], sym
    # Trade AI deterministic failures gate (DESIGN 5: FATN/ANET/SMCI).
    for sym in ("FATN", "ANET", "SMCI"):
        assert "GATE:R3" in second[sym], sym
    # Not-held WATCH vs AVOID is the same action (matrix: 6 such names were false flags).
    for sym in ("DT", "AXTI", "DXCM"):
        assert [x for x in second[sym] if not x.startswith("AGREEMENT")] == [], sym
    # SCHG: held WATCH vs desk SELL on the fresh synthesis is the one real stance conflict today.
    assert "CONFLICT:U7" in second["SCHG"]
    # Reviews frozen since 2026-09-02 are superseded, never sides (R1 + R14).
    assert "SUPERSEDED:R1" in second["QCOM"] and "SUPERSEDED:R1" in second["LDOS"]
