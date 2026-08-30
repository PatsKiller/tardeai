"""Curation may rearrange an advisory. It may not restate the book.

The safety property is mechanical, not prompt-based: every numeric token in the
output must already exist in the input. A prompt rule is a request; this is a
check. Live runs confirmed the model does not always obey the prompt (it added
a derived comparison), which is exactly why the numeric check exists and why
the curator is OFF by default.
"""
import os

import pytest

from scripts.lib.cio_advisory_curator import (
    LANE, MODEL, curate, enabled, validate, _numbers,
)

ORIG = ("🧠 CIO · READ_ONLY · `desk@v4`\nCash 630,784.82 · weight 42.1pct\n"
        "`plan_77e48566970e` · revisit 2026-08-12\nREAD_ONLY_ADVISORY")


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("CIO_ADVISORY_CURATOR", raising=False)
    assert enabled() is False
    r = curate(ORIG, plan_id="plan_77e48566970e")
    assert r["curated"] is False and r["reason"] == "disabled"
    assert r["text"] == ORIG          # deterministic message passes through


def test_a_faithful_reformat_is_accepted():
    good = ("READ_ONLY_ADVISORY\nDecision: hold.\nCash 630,784.82, weight "
            "42.1pct.\n`plan_77e48566970e` revisit 2026-08-12")
    assert validate(ORIG, good, plan_id="plan_77e48566970e") is None


@pytest.mark.parametrize("bad,why", [
    ("READ_ONLY_ADVISORY Cash 999,111.00 `plan_77e48566970e`", "invented_numbers"),
    ("READ_ONLY_ADVISORY Cash 630,784.82", "dropped_plan_id"),
    ("Cash 630,784.82 `plan_77e48566970e`", "dropped_authority_marker"),
    ("", "empty"),
])
def test_unsafe_curations_are_rejected(bad, why):
    r = validate(ORIG, bad, plan_id="plan_77e48566970e")
    assert r and r.startswith(why), r


def test_a_rounded_figure_counts_as_invented():
    """630,785 is not 630,784.82. A desk number is exact or it is wrong."""
    r = validate(ORIG, "READ_ONLY_ADVISORY Cash 630,785 `plan_77e48566970e`",
                 plan_id="plan_77e48566970e")
    assert r and r.startswith("invented_numbers")


def test_growth_is_rejected():
    """Curation compresses; a longer result means something was added."""
    assert validate(ORIG, ORIG + " plus some extra commentary") == "grew"


def test_numbers_normalise_across_formatting():
    assert _numbers("630,784.82") == _numbers("630784.82")


def test_failure_returns_the_deterministic_message(monkeypatch):
    """Fail-open is correct: the input was already sendable."""
    monkeypatch.setenv("CIO_ADVISORY_CURATOR", "1")
    monkeypatch.setattr(
        "scripts.lib.deepseek_client.chat",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("provider down")))
    r = curate(ORIG, plan_id="plan_77e48566970e")
    assert r["curated"] is False
    assert r["reason"].startswith("error:")
    assert r["text"] == ORIG


def test_it_uses_an_existing_governed_lane():
    """No new governance invented for a formatting feature."""
    assert LANE == "agent_narrative"
    assert MODEL == "deepseek-v4-flash"


def test_the_notify_path_is_wired_to_the_curator():
    """A module with no consumer is a module that does nothing.

    Acceptance flagged this file as a zero-consumer schema on first write —
    correctly. The curator only means something once the delivery path calls it.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "lib"
           / "cio_plan_enrichment.py").read_text(encoding="utf-8")
    assert "cio_advisory_curator" in src
    assert "advisory_curation" in src          # decision is logged either way
