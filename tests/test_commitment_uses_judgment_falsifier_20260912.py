"""A commitment must inherit the judgment's claim and falsifier, not a template.

The wake runs an L3 judgment and then throws its conclusion away. Measured on
the live store 2026-09-12:

    views.jsonl        2 rows with REAL falsifiers, e.g.
                       "Retrieval of at least one approved primary or news
                        source ... that directly addresses this subject and
                        supports a directional stance."
    commitments.jsonl  99 governed rows, ALL carrying
                       "observation contradicts claim within horizon"
                       over the claim
                       "Scheduled persistent wake reviewed subject <GUID>;
                        advisory observation only."

Both come out of the same wake. `run_persistent_wake._maybe_cortex_shadow_after_wake`
builds its summary from a hardcoded f-string and passes no falsifier at all, so
`run_cortex_shadow` falls back to its default parameter value — while the
judgment that ran seconds earlier in the same wake sits unused.

That is why 0 of 99 predictions are falsifiable, and why the L4 sweep would score
none of the 102 that come due on 2026-09-20.
"""

from __future__ import annotations

import inspect

import pytest

from scripts.lib.commitment_outcome_sweep import claim_is_falsifiable


def _commitment(claim, falsifier):
    return {
        "claim": claim,
        "falsifier": falsifier,
        "due_at": "2026-09-19T00:00:00Z",
        "horizon": "7d",
    }


def test_the_template_pair_is_unfalsifiable_and_that_is_the_bug():
    """Baseline: what the wake writes today cannot be scored."""
    ok, reason = claim_is_falsifiable(_commitment(
        "Scheduled persistent wake reviewed subject "
        "4b54769d-c407-5732-81c3-cf67575dd759; advisory observation only.",
        "observation contradicts claim within horizon",
    ))
    assert ok is False
    assert reason == "claim_asserts_only_that_a_review_occurred"


def test_a_real_judgment_falsifier_is_scoreable():
    """And what the judgment produced in the same wake CAN be."""
    ok, reason = claim_is_falsifiable(_commitment(
        "ADBE's prior position is no longer supported by the cited evidence.",
        "Retrieval of an approved primary or news source that directly "
        "addresses this subject and supports a directional stance.",
    ))
    assert ok is True, reason


def test_the_wake_passes_the_judgment_through_to_the_commitment():
    """DEFECT: the call site builds a hardcoded summary and passes no
    falsifier, so run_cortex_shadow uses its vacuous default."""
    import scripts.run_persistent_wake as rpw

    src = inspect.getsource(rpw._maybe_cortex_shadow_after_wake)
    assert "falsifier" in src, (
        "the wake never passes a falsifier, so every governed commitment it "
        "mints inherits the vacuous default"
    )
    assert "judgment" in src, (
        "the wake ran an L3 judgment in this same slot and does not consult it"
    )


def test_the_wake_run_result_exposes_the_judgment():
    """The judgment is put into `context` and dropped. The caller that builds
    the commitment cannot reach it."""
    from scripts.lib.persistent_agent_wake import WakeEngine

    src = inspect.getsource(WakeEngine.run)
    assert '"judgment":' in src or "'judgment':" in src, (
        "run() returns ok/inserted/wake/receipts/commitments/view/memory_empty "
        "and not the judgment, so no caller downstream can use its falsifier"
    )


def test_a_vacuous_falsifier_is_refused_rather_than_written():
    """Guard rail: once the judgment is wired through, a caller that still
    supplies the template must be refused, or the defect returns silently."""
    from scripts.lib.cortex_shadow_pipeline import refuse_vacuous_falsifier

    with pytest.raises(ValueError, match="vacuous_falsifier"):
        refuse_vacuous_falsifier("observation contradicts claim within horizon")
    # A real one passes through untouched.
    real = "Next 10-Q shows gross margin below the prior quarter."
    assert refuse_vacuous_falsifier(real) == real


def test_an_empty_falsifier_is_also_refused():
    from scripts.lib.cortex_shadow_pipeline import refuse_vacuous_falsifier

    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            refuse_vacuous_falsifier(bad)


def test_the_guard_is_actually_called_not_merely_defined():
    """A guard nobody calls is a dark contract — the exact defect the repo's
    own check_dark_contracts gate exists to catch. The first draft of this
    change defined refuse_vacuous_falsifier and never invoked it."""
    import scripts.run_persistent_wake as rpw

    src = inspect.getsource(rpw._maybe_cortex_shadow_after_wake)
    assert "refuse_vacuous_falsifier(falsifier)" in src, (
        "the guard is defined but never invoked on the judgment path"
    )


def test_the_observation_path_is_deliberately_not_guarded():
    """The no-judgment branch writes an observation, not a prediction. Raising
    there would trade one honest record for no record at all, so it keeps the
    'advisory observation only' summary and no falsifier — and the sweep
    classifies it as not-a-prediction on the missing due_at/horizon."""
    import scripts.run_persistent_wake as rpw

    src = inspect.getsource(rpw._maybe_cortex_shadow_after_wake)
    observation_branch = src.split("else:", 1)[1]
    assert "refuse_vacuous_falsifier" not in observation_branch
    assert "advisory observation only" in observation_branch
