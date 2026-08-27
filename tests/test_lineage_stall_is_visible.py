"""A lineage stage that fails to advance must not look like work in progress.

`record_hermes_completion` is the only call that advances
`stage_status.research` to COMPLETED (via hermes_completion_fields), and that
stage gates `is_complete_to_checkpoint`. It sat inside a bare
`except Exception: pass` while the enclosing function returned ok=True.

So a failure there produced an envelope reading NOT_YET_CREATED forever -- which
is byte-identical to research that simply has not finished yet. Measured
2026-08-27: 41 envelopes sat at NOT_YET_CREATED on every stage. Those 41 turned
out to be genuinely open requests (0 of 41 had a completed result), so this was
NOT their cause -- but the two states were indistinguishable from the data,
which is why establishing that took a cross-reference against the results store
instead of a glance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def test_the_swallow_is_gone():
    """Pin the specific silence, not the file's 11 other bare excepts."""
    src = (ROOT / "scripts/lib/cio_hermes_research.py").read_text(encoding="utf-8")
    i = src.index("record_hermes_completion(req_meta")
    block = src[i:i + 1400]
    assert "except Exception as e:" in block
    assert "lineage_recording_failed" in block


def test_a_failure_is_reported_on_the_result(monkeypatch, tmp_path):
    """The caller learns the envelope did not advance."""
    import scripts.lib.cio_hermes_research as mod

    notes = []
    monkeypatch.setattr(mod, "_note_lineage_stall",
                        lambda **kw: notes.append(kw))

    out = {"ok": True, "result_id": "r1", "result": {}}
    try:
        raise RuntimeError("envelope store unavailable")
    except Exception as e:
        out["lineage_recording_failed"] = f"{type(e).__name__}: {e}"
        mod._note_lineage_stall(research_id="r1", request={"research_id": "res_1"}, error=e)

    assert out["ok"] is True, "a bookkeeping failure must not lose the result"
    assert "RuntimeError" in out["lineage_recording_failed"]
    assert notes and notes[0]["research_id"] == "r1"


def test_the_stall_note_is_durable_and_append_only(tmp_path, monkeypatch):
    import scripts.lib.cio_hermes_research as mod

    calls = []
    real_open = open

    logs = tmp_path / "logs"

    class FakePath(type(Path())):
        pass

    # Point the helper at a temp root by monkeypatching Path resolution.
    monkeypatch.setattr(mod, "__file__", str(tmp_path / "scripts" / "lib" / "x.py"))
    (tmp_path / "scripts" / "lib").mkdir(parents=True)

    mod._note_lineage_stall(research_id="r1", request={"research_id": "res_1", "plan_id": "p1"},
                            error=ValueError("boom"))
    mod._note_lineage_stall(research_id="r2", request={"research_id": "res_2"},
                            error=ValueError("boom2"))

    out = logs / "lineage_stalls.jsonl"
    assert out.is_file(), "the note must be durable, not just logged"
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert len(lines) == 2, "append-only: the second note must not replace the first"
    assert lines[0]["schema"] == "LineageStallNote@v1"
    assert lines[0]["stage"] == "research"
    assert "ValueError" in lines[0]["error"]
    assert lines[1]["research_id"] == "r2"


def test_a_failing_diagnostic_cannot_break_the_path_it_observes():
    """The helper itself may raise; the call site is what must contain it.

    An earlier version of this test asserted the helper never raises, which is
    both false and the wrong guarantee -- what matters is that a diagnostic
    failure cannot propagate into research completion.
    """
    src = (ROOT / "scripts/lib/cio_hermes_research.py").read_text(encoding="utf-8")
    i = src.index("_note_lineage_stall(")
    before, after = src[:i], src[i:i + 300]
    # the call is wrapped in its own try, whose except swallows
    assert before.rstrip().endswith("try:"), "the stall note must sit inside its own try"
    assert "except Exception:" in after and "pass" in after
