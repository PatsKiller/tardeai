#!/usr/bin/env python3
"""Stale memory must cost WEIGHT, never recall and never the whole decision.

2026-09-11 (L2). This file originally asserted that stale memory "degrades to
empty". That was the second of three positions, and it was still wrong:

    refuse the wake        -> lost the decision entirely
    degrade to empty       -> kept the decision, discarded every fact
    decay the weight       <- current: keeps the decision AND the facts

Degrading to empty still meant one 18-day-old observation erased every other
fact for that subject, so the desk did strictly less the more memory it could
find. Facts now carry a continuous weight in (0, 1] that never reaches zero
from age alone. Raising 168h to 720h was explicitly rejected: it moves the
cliff instead of removing it.

`refuse_stale_memory` had never executed. `stale` is computed from the newest
loaded fact, and until 2026-09-10 every wake loaded zero facts, so `newest`
stayed None and `stale` stayed False. Making memory findable (#960) armed a
control that had been dead since it was written, and its first act was to
abort a wake.

Measured when this was found:

    71  subjects had loadable memory
    65  of those were past the 168h window (median newest-fact age 432h)
     2  of 25 wake subjects would refuse
     0  proceeded with memory

A refused wake produces no decision at all, so the system did strictly less
the more memory it could find — the same terminal slot loss as that morning's
MEMORY_MALFORMED regression.

Producer:
`trade-ai-audits/cursor-independent-closure-20260910/stale_memory_blast_radius.py`
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import persistent_agent_wake as paw  # noqa: E402

SUBJECT = "a2ee84b5-e1bc-5288-8402-7c1fbca65657"
NOW = datetime(2026, 9, 10, 23, 0, tzinfo=timezone.utc)
OLD = (NOW - timedelta(hours=432)).isoformat().replace("+00:00", "Z")
FRESH = (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z")


def _row(fid: str, as_of: str) -> dict:
    return {
        "memory_id": fid,
        "subject_guid": SUBJECT,
        "content": "prior observation",
        "as_of": as_of,
    }


# ------------------------------------------------------------ the loader

def test_loader_still_reports_stale():
    """The signal is preserved; only the response to it changes."""
    snap = paw.MemoryLoader(lambda _g: [_row("old", OLD)]).load(SUBJECT, now=NOW)
    assert snap.stale is True
    assert len(snap.facts) == 1


def test_fresh_memory_is_not_stale():
    snap = paw.MemoryLoader(lambda _g: [_row("new", FRESH)]).load(SUBJECT, now=NOW)
    assert snap.stale is False


def test_one_fresh_fact_keeps_the_snapshot_fresh():
    """Staleness is a property of the NEWEST fact, not of every fact."""
    rows = [_row("old", OLD), _row("new", FRESH)]
    snap = paw.MemoryLoader(lambda _g: rows).load(SUBJECT, now=NOW)
    assert snap.stale is False
    assert len(snap.facts) == 2


# ------------------------------------------------------------- the wake

ENV_ON = {
    paw.FEATURE_FLAG: "1",
    "PROVENANCE_PRODUCER": "test",
    "TRADEAI_SOURCE_SHA": "f17c0e7594ce65661911858eb50623446ae3aca5",
}


def _mem_file(tmp_path: Path, rows: list[dict]) -> Path:
    import json

    p = tmp_path / "mem.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def test_stale_memory_does_not_abort_the_wake(tmp_path):
    """The regression this file exists for — driven through the real wake.

    A wake whose only memory is 18 days old must still reach a decision, and
    must still SEE that memory — discounted, not deleted.
    """
    state = tmp_path / "state"
    state.mkdir()
    mem = _mem_file(tmp_path, [_row("old", OLD)])
    r = paw.run_scheduled_wake(
        agent_id="cio", subject_guid=SUBJECT, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON,
    )
    assert r["ok"] is True, "a stale memory store must not cost the whole wake"
    assert r.get("state") != "STALE"
    assert r["wake"]["lifecycle_state"] != "STALE"
    assert r["wake"]["memory_fact_ids"] == ["old"], (
        "an old fact is OLD, not absent — it must survive with a decay weight"
    )
    decisions = r["wake"]["provenance"]["policy_decisions"]
    assert "stale_memory_retained_with_decay" in decisions
    assert "stale_memory_degraded_to_empty" not in decisions
    retrieval = r["wake"]["provenance"]["memory_retrieval"]
    assert retrieval["cliff_applied"] is False
    assert retrieval["returned"] == 1
    (weight,) = retrieval["decay_weights"]
    assert 0.0 < weight < 1.0, f"432h fact must be weak but present, got {weight}"


def test_fresh_memory_still_reaches_the_wake(tmp_path):
    """Positive control: the degrade must not swallow usable memory."""
    state = tmp_path / "state"
    state.mkdir()
    mem = _mem_file(tmp_path, [_row("new", FRESH)])
    r = paw.run_scheduled_wake(
        agent_id="cio", subject_guid=SUBJECT, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON,
    )
    assert r["ok"] is True
    assert r["wake"]["memory_fact_ids"] == ["new"]
    decisions = r["wake"]["provenance"]["policy_decisions"]
    assert "stale_memory_retained_with_decay" not in decisions
    assert "stale_memory_degraded_to_empty" not in decisions


def test_stale_branch_no_longer_returns_a_terminal_refusal():
    """Source-level guard against the refusal being reinstated.

    Asserted on the AST rather than on text so a comment quoting either old
    string cannot satisfy it.
    """
    import ast

    src = (ROOT / "scripts" / "lib" / "persistent_agent_wake.py").read_text()
    tree = ast.parse(src)
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "refuse_stale_memory" not in literals, (
        "stale memory must not refuse the wake"
    )
    assert "stale_memory_degraded_to_empty" not in literals, (
        "stale memory must not discard facts either — it decays their weight"
    )
    assert "stale_memory_retained_with_decay" in literals


def test_malformed_memory_still_refuses():
    """The degrade applies to STALE only. Malformed memory is a real refusal.

    Guards against widening the change: a store we cannot parse is a different
    condition from a store that is merely old.
    """
    def backend(_g):
        raise ValueError("unreadable")

    snap = paw.MemoryLoader(backend).load(SUBJECT, now=NOW)
    assert snap.malformed is True


# ------------------------------------------- the production fact that was lost

def test_the_real_production_fact_survives(tmp_path):
    """Regression guard built from the fact the cliff actually discarded.

    Not a synthetic fixture. This is the real row from the served store
    (`aif_memory.jsonl`, file sha256 41147d2c…), and the real wake that lost it:

        subject      0bc81168-…  ("Research refresh requested for ADBE")
        memory_id    mem_490759abbefb8957cf58850a6cadfc2c
        as_of        2026-08-23T22:26:07.327282+00:00

        2026-09-10T23:00Z  f17c0e759  STALE    1 fact  refuse_stale_memory
        2026-09-11T00:00Z  410d125c6  SETTLED  0 facts stale_memory_degraded_to_empty
        2026-09-11T03:00Z  aa43a8c9e  SETTLED  0 facts stale_memory_degraded_to_empty

    The fact was never missing. It was found on every one of those wakes and
    then thrown away by policy. At the 03:00Z wake it was ~437h old — weight
    ~0.41 under the current policy, nowhere near the influence floor.
    """
    subject = "0bc81168-8531-5f3e-9c3a-1d2e4f5a6b7c"
    as_of = "2026-08-23T22:26:07.327282+00:00"
    now = datetime(2026, 9, 11, 3, 0, 2, tzinfo=timezone.utc)
    row = {
        "memory_id": "mem_490759abbefb8957cf58850a6cadfc2c",
        "subject_guid": subject,
        "content": "Evidence refresh required: insufficient_contradictory_rag, "
                   "insufficient_supporting_rag, no_approved_primary_or_news",
        "as_of": as_of,
    }
    snap = paw.MemoryLoader(lambda _g: [row]).load(subject, now=now)

    assert snap.stale is True, "the 168h label still fires — only the response changed"
    assert [f.fact_id for f in snap.facts] == ["mem_490759abbefb8957cf58850a6cadfc2c"], (
        "the fact the cliff discarded must now survive"
    )
    (fact,) = snap.facts
    assert 430 < fact.age_seconds / 3600.0 < 445
    assert 0.30 < fact.decay_weight < 0.50, (
        f"expected a weak-but-usable weight, got {fact.decay_weight}"
    )
    assert fact.freshness_class == "stale_but_usable"
    assert fact.decay_model == "halflife_exp:336h"


def test_raising_the_window_is_not_the_fix():
    """The cliff must be gone, not relocated.

    Guards the explicit rejection of "set WAKE_MEMORY_STALE_HOURS=720": any
    single threshold still deletes everything on the far side of it. A fact far
    past *any* window must keep a positive weight.
    """
    subject = "a2ee84b5-e1bc-5288-8402-7c1fbca65657"
    now = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)
    for hours in (169, 721, 1000):
        old = (now - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
        snap = paw.MemoryLoader(lambda _g: [_row("f", old)]).load(subject, now=now)
        assert len(snap.facts) == 1, f"{hours}h fact was deleted — a cliff still exists"
        assert snap.facts[0].decay_weight > 0.0
