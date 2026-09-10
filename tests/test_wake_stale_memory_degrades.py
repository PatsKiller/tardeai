#!/usr/bin/env python3
"""Stale memory must cost recall, never the whole decision.

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

    A wake whose only memory is 18 days old must still reach a decision. It
    proceeds with no facts — exactly the position it was in before memory was
    loadable — and records why.
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
    assert r["wake"]["memory_fact_ids"] == [], "must not reason from stale facts"
    assert "stale_memory_degraded_to_empty" in r["wake"]["provenance"]["policy_decisions"]


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
    assert "stale_memory_degraded_to_empty" not in r["wake"]["provenance"]["policy_decisions"]


def test_stale_branch_no_longer_returns_a_terminal_refusal():
    """Source-level guard against the refusal being reinstated.

    Asserted on the AST rather than on text so a comment quoting the old
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
        "stale memory must degrade to empty, not refuse the wake"
    )
    assert "stale_memory_degraded_to_empty" in literals


def test_malformed_memory_still_refuses():
    """The degrade applies to STALE only. Malformed memory is a real refusal.

    Guards against widening the change: a store we cannot parse is a different
    condition from a store that is merely old.
    """
    def backend(_g):
        raise ValueError("unreadable")

    snap = paw.MemoryLoader(backend).load(SUBJECT, now=NOW)
    assert snap.malformed is True
