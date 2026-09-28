"""Operator-cleared containment satisfies a containment requirement (W0-1 precedent, 2026-09-27 triage)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import agent_jobs_containment as ajc  # noqa: E402
import watch_review_policy_ledger as wrpl  # noqa: E402


def test_cleared_tripwire_is_honoured(tmp_path, monkeypatch):
    monkeypatch.setattr(ajc, "CLEARED_TRIPWIRE", tmp_path / "TRIPWIRE.md")
    monkeypatch.setattr(ajc, "evaluate_containment_state", lambda: {"status": ajc.STATUS_INACTIVE, "source": "no_flag"})
    import lib.agent_jobs_containment as lib_ajc  # the ledger imports through `lib.`
    monkeypatch.setattr(lib_ajc, "evaluate_containment_state", lambda: {"status": ajc.STATUS_INACTIVE, "source": "no_flag"})
    monkeypatch.setattr(lib_ajc, "CLEARED_TRIPWIRE", tmp_path / "TRIPWIRE.md")
    ok, reason = wrpl.containment_required_ok()
    assert (ok, reason) == (False, "containment_not_active:INACTIVE")
    (tmp_path / "TRIPWIRE.md").write_text("archived by operator 2026-09-15\n")
    ok, reason = wrpl.containment_required_ok()
    assert (ok, reason) == (True, "containment_cleared_by_operator")
