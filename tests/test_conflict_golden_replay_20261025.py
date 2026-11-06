"""Golden replay of real stored state (EXCEPTIONS_MATRIX.md "golden replay", gap (f) 2026-10-25).

The 2026-10-24 capture of the 31 live flags was never saved. tests/fixtures/conflicts/golden_20261025/inputs.json is
SYNTHETIC: scripts/conflict_golden_anonymize.py derived it from a read-only capture of 2026-10-25 18:22Z state
(served Watch read model, CIO truth holdings/risk, the cio-prospect-shadow build, the stored re-entry desk snapshot,
the identity registry). The real capture holds portfolio facts and stays host-only (REAL_CAPTURE.json pins its
sha256); symbols, GUIDs, accounts, weights, convictions and times are replaced, every engine outcome is kept.
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
    assert INPUTS["synthetic"] is True and all(s["symbol"].startswith("SYM") for s in INPUTS["subjects"])
    text = (FIXTURE / "inputs.json").read_text(encoding="utf-8").lower()
    for marker in ("password", "secret", "api_key", "token", "bearer ", "authorization:"):
        assert marker not in text, marker


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


def test_structural_matrix_cases_survive_anonymization(results):
    """The synthetic twin keeps every case the matrix names (described by shape, never by real symbol)."""
    subjects = {s["symbol"]: s for s in INPUTS["subjects"]}
    second = {sym: label(r[1]) for sym, r in results.items()}

    def card(sym):
        return subjects[sym]["card"] or {}
    # Trade AI STALE / DETERMINISTIC_FAIL / BLOCKED on a positive stance gate go-actions (R3).
    for state in ("STALE", "DETERMINISTIC_FAIL", "BLOCKED"):
        gated = [s for s in second if card(s).get("trade_ai_state") == state and "GATE:R3" in second[s]]
        assert gated, state
    # Not-held WATCH vs AVOID is the same action: agreement only.
    same = [s for s in second if subjects[s]["truth"]["context"].get("held") is False
            and (subjects[s]["truth"]["canonical"] or {}).get("value") == "WATCH"
            and ((card(s).get("decision") or {}).get("inputs") or {}).get("synthesis") == "AVOID"]
    assert same and all(not [x for x in second[s] if not x.startswith("AGREEMENT")] for s in same)
    # Exactly one confirmed stance conflict: a held WATCH against a fresh desk SELL.
    (conflict,) = [s for s in second if "CONFLICT:U7" in second[s]]
    assert subjects[conflict]["truth"]["context"]["held"] is True
    assert card(conflict)["decision"]["inputs"]["synthesis"] == "SELL"
    # Every superseded CIO review is older than its 7-day limit (reviews frozen since early September).
    for sym, (_, run2) in results.items():
        for f in run2:
            if f.kind == "SUPERSEDED" and f.sides[0]["source"] == "watchlist CIO review":
                assert (NOW - datetime.fromisoformat(f.sides[0]["as_of"])).days > 7, sym
    # Each never-automatic kind is present.
    for kind in ("NEEDS_OPERATOR:R12", "DATA_ERROR:R12", "GATE:R16", "GATE:R7", "GATE:R7b", "GATE:R13", "DATA_ERROR:U1"):
        assert any(kind in v for v in second.values()), kind


REAL = json.loads((FIXTURE / "REAL_CAPTURE.json").read_text(encoding="utf-8"))
def _real_dir():
    import os
    import pwd
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / "trade-ai-releases/persistent-state/data/conflicts/golden"


REAL_DIR = _real_dir()  # the account's real home: tests may run with HOME redirected


@pytest.mark.host_state("read-only replay of the private real golden capture; skips where it is absent (CI)")
def test_host_only_real_capture_replay():
    """Replays the private real capture when this host has it (never in CI); pinned by sha256."""
    import hashlib
    inputs, expected = REAL_DIR / REAL["files"]["inputs"], REAL_DIR / REAL["files"]["expected"]
    if not inputs.is_file() or not expected.is_file():
        pytest.skip("private real capture is host-only")
    assert hashlib.sha256(inputs.read_bytes()).hexdigest() == REAL["inputs_sha256"]
    assert hashlib.sha256(expected.read_bytes()).hexdigest() == REAL["expected_sha256"]
    doc, table = json.loads(inputs.read_text()), json.loads(expected.read_text())
    global NOW
    saved, NOW = NOW, datetime.fromisoformat(doc["now"])
    try:
        for subject in doc["subjects"]:
            first, second = replay(subject)
            assert {"run1": label(first), "run2": label(second)} == table["subjects"][subject["symbol"]]
    finally:
        NOW = saved
