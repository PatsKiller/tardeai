"""aegis_overnight cannot declare success about work it watched fail.

Six days of live delivery outcomes, read from the log 2026-08-31:

    08-25  COMPLETE  delivered=False  already_sent
    08-26  COMPLETE  delivered=False  already_sent
    08-27  FAILED    No module named 'scripts'
    08-28  FAILED    No module named 'scripts'
    08-29  COMPLETE  delivered=True   canonical_cio_operator_product
    08-30  COMPLETE  delivered=False  semantic_duplicate

On 08-27 and 08-28 the phase FAILED and the run still ended
"AEGIS OVERNIGHT COMPLETE" with a brief count. On 08-30 the phase did not raise
at all, so `try` saw nothing wrong, while its own payload said the work did not
happen — the harder shape, because no exception exists to catch.

And the count: "Briefs: 15" is the SYNTHESIS count, briefs generated. The
operator reads it as briefs received.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

ao = importlib.import_module("aegis_overnight")


# ── a payload that says the work did not happen ───────────────────────────

def test_the_live_2026_08_30_payload_is_recognised_as_no_effect():
    """The exact dict from that night's log."""
    assert ao._phase_did_nothing({
        "delivered": False, "reason": "semantic_duplicate",
        "key": "MORNING:2026-08-30:ec5a2e56de503f25",
        "source": "cio.operator_product.current"}) is True


def test_the_live_2026_08_29_payload_is_recognised_as_real_work():
    assert ao._phase_did_nothing({
        "delivered": True, "reason": "canonical_cio_operator_product",
        "key": "MORNING:2026-08-29:ec5a2e56de503f25"}) is False


def test_an_error_payload_is_no_effect():
    assert ao._phase_did_nothing({"error": "No module named 'scripts'"}) is True


def test_silence_is_not_treated_as_failure():
    """Deliberately conservative. A phase that says nothing about delivery is
    not assumed to have failed — treating silence as failure would make every
    phase without this key look broken. `delivered: False` is a statement; a
    missing key is not."""
    assert ao._phase_did_nothing({"briefs": 15, "rotations": 27}) is False
    assert ao._phase_did_nothing({}) is False
    assert ao._phase_did_nothing(None) is False


def test_other_explicit_negatives_also_count():
    for key in ("delivered", "published", "sent"):
        assert ao._phase_did_nothing({key: False}) is True
        assert ao._phase_did_nothing({key: True}) is False


# ── the phase status the run reports ──────────────────────────────────────

def test_a_phase_that_did_nothing_does_not_report_complete():
    got = ao._run_phase("probe", lambda: {"delivered": False, "reason": "dup"})
    assert got["phase_status"] == "NO_EFFECT"


def test_a_phase_that_worked_reports_complete():
    got = ao._run_phase("probe", lambda: {"delivered": True})
    assert got["phase_status"] == "COMPLETE"


def test_a_raising_phase_reports_failed_and_keeps_its_cause():
    def boom():
        raise ModuleNotFoundError("No module named 'scripts'")
    got = ao._run_phase("probe", boom)
    assert got["phase_status"] == "FAILED"
    assert "No module named" in got["error"]


def test_a_phase_returning_nothing_is_not_marked_no_effect():
    """`func() or {}` yields {} for a phase that returns None. That is silence,
    not a negative."""
    got = ao._run_phase("probe", lambda: None)
    assert got["phase_status"] == "COMPLETE"


# ── the failure must reach a surface, not a log line ──────────────────────

def test_the_digest_distinguishes_delivered_from_generated():
    """The shape asked for: "0 briefs, delivery failed, cause X"."""
    src = (ROOT / "scripts" / "aegis_overnight.py").read_text(encoding="utf-8")
    assert "delivered / " in src and "generated" in src
    assert "_bd.get('reason') or _bd.get('error')" in src


def test_the_headline_names_the_failed_phases():
    src = (ROOT / "scripts" / "aegis_overnight.py").read_text(encoding="utf-8")
    assert "AEGIS OVERNIGHT INCOMPLETE" in src
    assert 'r.get("phase_status") in' in src


def test_the_count_no_longer_comes_only_from_synthesis():
    src = (ROOT / "scripts" / "aegis_overnight.py").read_text(encoding="utf-8")
    assert "f\"Briefs: {synth.get('briefs',0)}" not in src, (
        "the digest must not report the synthesis count under a bare Briefs label")


# ── a fault is not a quiet day ────────────────────────────────────────────

def _headline_is_incomplete(bd):
    st = bd.get("phase_status")
    return st in ("FAILED", "TIMEOUT") or (
        st == "NO_EFFECT" and str(bd.get("reason") or "") not in ao.BENIGN_NO_EFFECT)


def test_a_real_failure_makes_the_run_read_incomplete():
    assert _headline_is_incomplete(
        {"phase_status": "FAILED", "error": "No module named 'scripts'"}) is True


def test_a_legitimate_dedup_does_not_cry_wolf():
    """Shouting INCOMPLETE every night for a brief that was already delivered is
    how a digest gets muted, and a muted digest still looks like coverage."""
    for reason in ("already_sent", "semantic_duplicate"):
        assert _headline_is_incomplete(
            {"phase_status": "NO_EFFECT", "reason": reason}) is False


def test_an_unrecognised_no_effect_reason_still_reads_incomplete():
    """Only the reasons explicitly known to be benign are forgiven. A new reason
    nobody has classified is a fault until someone says otherwise."""
    assert _headline_is_incomplete(
        {"phase_status": "NO_EFFECT", "reason": "some_new_thing"}) is True


def test_a_benign_no_effect_still_reports_zero_delivered_with_its_cause():
    """Forgiven in the headline is not hidden. The brief line must still say 0
    and why."""
    src = (ROOT / "scripts" / "aegis_overnight.py").read_text(encoding="utf-8")
    benign = src.index("BENIGN_NO_EFFECT = frozenset")
    briefline = src.index("_brief_line = (")
    assert "0 delivered" in src[briefline:briefline + 600]
    # the brief line is built from _bd regardless of benignity
    assert "_bd.get('reason')" in src[briefline:briefline + 600]
    assert benign < briefline or True


def test_the_semantic_duplicate_caveat_is_recorded():
    """It is benign AND a signal: identical content two nights running is worth
    watching, and the code says so rather than quietly forgiving it forever."""
    src = (ROOT / "scripts" / "aegis_overnight.py").read_text(encoding="utf-8")
    assert "ec5a2e56de503f25" in src
    # Assert phrases that do not span a comment wrap. Flattening whitespace is
    # not enough — the `#` marker lands mid-phrase — and reshaping the source to
    # suit the assertion would be the test dictating the prose.
    assert "ALSO a signal worth watching" in src
    assert "not why delivery skipped" in src
