"""Live wake persist must stamp cc_narrative.writer with the live path.

LITMUS_WAKE / CIO_M5_FIRST_FIRE defect 2: decide_after_load moved
next_eligible_at on EXIT:WLDS while leaving writer=migration:deterministic —
the store attributed a production wake to a migration.

Acceptance:
  * decision that moves next_eligible_at → writer=cognition:decide_after_load
  * same next_eligible_at (cadence_not_due shape) → cognition_noop, stamp untouched
  * prose fields (what / evidence_refs) preserved on restamp
  * BehaviorWriteRefused still raises on size_usd
  * mutation: omit the restamp block → red on the writer assertion
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib.cio_instrument_record import (
    BehaviorWriteRefused,
    CognitionNoOp,
    apply_cognition,
    cc_narrative,
    new_record,
)
from scripts.lib.cio_rehydrate import apply_after_cycle

ROOT = Path(__file__).resolve().parents[1]
REHYDRATE = ROOT / "scripts" / "lib" / "cio_rehydrate.py"
NOW = datetime(2026, 9, 1, 17, 35, 11, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(hours=72)).isoformat()
WRITER = "cognition:decide_after_load"


def _fossil_record(*, next_eligible_at=None):
    """Shape of a migration-seeded row the live wake actually wrote on."""
    rec = new_record("EXIT", "WLDS")
    rec["cc_narrative"] = {
        "what": "Cash sleeve fossil prose that must survive a restamp.",
        "thesis_fit": "optionality",
        "recommendation_option_id": "hold_cash",
        "risks": [],
        "evidence_refs": [{"total_cash": 630784.82, "as_of": "2026-08-29"}],
        "as_of": "2026-08-30T02:34:32.327723+00:00",
        # Raw migration stamp as stored on disk (not yet normalize_writer_author).
        "writer": "migration:deterministic",
        "author": "migration:deterministic",
    }
    if next_eligible_at is not None:
        rec["next_eligible_at"] = next_eligible_at
    return rec


def test_decide_after_load_cadence_write_stamps_the_live_writer():
    rec = _fossil_record()
    assert (rec["cc_narrative"] or {}).get("writer") == "migration:deterministic"

    out, changed = apply_after_cycle(
        rec,
        decision={
            "decision": "flash",
            "reason": "free_sources_exhausted_first_pass",
            "next_eligible_at": FUTURE,
        },
        now=NOW,
        strict=False,
    )

    assert "next_eligible_at" in changed
    assert "cc_narrative" in changed
    assert out["next_eligible_at"] == FUTURE
    narrative = out["cc_narrative"] or {}
    assert narrative.get("writer") == WRITER
    assert narrative.get("author") == WRITER
    # Prose and evidence survive; only authorship moves.
    assert "fossil prose" in narrative.get("what", "")
    assert narrative.get("evidence_refs") == [
        {"total_cash": 630784.82, "as_of": "2026-08-29"}
    ]
    assert "migration:deterministic" not in str(narrative.get("writer"))


def test_cadence_not_due_same_stamp_stays_a_noop():
    """Wakes 2/3 at 13:35: skip with the same next_eligible_at must not
    rewrite the narrative just to refresh as_of — that would turn every skip
    into a false persist."""
    rec = _fossil_record(next_eligible_at=FUTURE)
    out, changed = apply_after_cycle(
        rec,
        decision={
            "decision": "skip",
            "reason": "cadence_not_due",
            "next_eligible_at": FUTURE,
        },
        now=NOW,
        strict=False,
    )
    assert changed == []
    assert (out["cc_narrative"] or {}).get("writer") == "migration:deterministic"


def test_defer_path_keeps_its_own_writer():
    """More-specific rules still own authorship; we do not overwrite them."""
    rec = new_record("HELD", "SCHD")
    out, changed = apply_after_cycle(
        rec,
        lesson={"claim": "operator defer honored, no new catalyst", "note": "wait"},
        operator_turn={"intent": "defer", "note": "wait", "ts": NOW.isoformat()},
        now=NOW,
        strict=False,
    )
    assert "cc_narrative" in changed
    assert (out["cc_narrative"] or {}).get("writer") == "cognition:defer_honored"


def test_behaviour_rail_untouched():
    with pytest.raises(BehaviorWriteRefused):
        apply_cognition(
            new_record("EXIT", "WLDS"),
            next_eligible_at=FUTURE,
            size_usd=1000,
        )


def test_mutation_pre_fix_shape_has_no_live_writer_string():
    """Source-shape gate (comments stripped). The pre-fix file had no
    cognition:decide_after_load stamp; a comment quoting it must not pass."""
    src = REHYDRATE.read_text(encoding="utf-8")
    src_code = re.sub(r"#.*?$", "", src, flags=re.M)
    assert f'writer="{WRITER}"' in src_code, (
        f"apply_after_cycle must stamp writer={WRITER!r} when a decision "
        "moves next_eligible_at; absent string is the FIRST_FIRE defect"
    )
    # The guard that skips restamp on cadence_not_due must also remain —
    # without it every skip would rewrite the narrative.
    assert "nxt_at != rec.get(\"next_eligible_at\")" in src_code or \
           "nxt_at != rec.get('next_eligible_at')" in src_code
