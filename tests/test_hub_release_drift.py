#!/usr/bin/env python3
"""A promote updates the release. It does not update the pipeline.

Cause, 2026-09-10: the Telegram presentation fix merged and promoted at
22:48Z, and messages sent afterwards were unchanged. The wake path runs from
CURRENT and had the fix; the Telegram producers are cron jobs that `cd` to the
hub tree, which sat three merges behind on detached HEAD:

    grep -c operator_wire_text scripts/telegram_alert.py  -> 0

The fix was live and inert at the same time, and every check that reads the
release would have called it deployed. Nothing compared the two trees.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import deterministic_integrity as di  # noqa: E402

A = "410d125c68b60e7cdf6eed39802780d205bf30e2"
B = "eaec6f3a1f08d68fbbef3bca62cf0b34605a6d45"


def test_aligned_trees_produce_no_finding():
    assert di.check_hub_behind_served_release(hub_head=A, served_sha=A) == []


def test_drift_is_reported_as_p1():
    out = di.check_hub_behind_served_release(hub_head=B, served_sha=A)
    assert len(out) == 1
    f = out[0]
    assert f["check"] == "hub_behind_served_release"
    assert f["severity"] == di.P1
    assert B[:9] in f["subject"] and A[:9] in f["subject"]


def test_drift_detail_names_the_consequence_not_just_the_mismatch():
    """An alarm that says 'these differ' gets ignored; one that says what
    breaks gets acted on."""
    f = di.check_hub_behind_served_release(hub_head=B, served_sha=A)[0]
    assert "cron" in f["detail"] or "producer" in f["detail"]


def test_unresolvable_side_is_not_a_pass(monkeypatch):
    """Two states cannot express 'no input' (AGENTS.md §7).

    A check whose failure condition needs both sides would read healthy when
    one is missing. `None` as an argument means 'resolve it live', so the
    unresolvable case is forced by breaking the resolvers — patching the
    parameter default would test argument handling, not the condition.
    """
    monkeypatch.setattr(di, "_git_head", lambda _t: None)
    out = di.check_hub_behind_served_release(served_sha=A)
    assert len(out) == 1 and out[0]["check"] == "hub_release_drift_unknown"

    monkeypatch.setattr(di, "_served_sha", lambda: None)
    out = di.check_hub_behind_served_release(hub_head=A)
    assert len(out) == 1 and out[0]["check"] == "hub_release_drift_unknown"

    out = di.check_hub_behind_served_release()
    assert len(out) == 1 and out[0]["check"] == "hub_release_drift_unknown"


def test_defaults_resolve_live_and_do_not_crash():
    """The zero-argument form is what the sweep calls."""
    out = di.check_hub_behind_served_release()
    assert isinstance(out, list)
    for f in out:
        assert f["check"] in {"hub_behind_served_release", "hub_release_drift_unknown"}


def test_empty_string_is_treated_as_unknown_not_as_a_match():
    """Two empty strings are equal; that must not read as aligned."""
    out = di.check_hub_behind_served_release(hub_head="", served_sha="")
    assert out and out[0]["check"] == "hub_release_drift_unknown"


def test_check_is_registered_in_the_sweep():
    """A check nothing calls is the defect this file exists to prevent."""
    import inspect

    src = inspect.getsource(di.run_all) if hasattr(di, "run_all") else ""
    if not src:
        for name in dir(di):
            obj = getattr(di, name)
            if callable(obj) and name.startswith(("run", "sweep", "collect")):
                try:
                    src += inspect.getsource(obj)
                except Exception:
                    pass
    assert "check_hub_behind_served_release" in src


def test_engine_still_never_mutates():
    """The sweep reports and never repairs. Advancing the hub moves ~190
    scheduled jobs at once and is not a machine's decision."""
    src = (ROOT / "scripts" / "lib" / "deterministic_integrity.py").read_text()
    for forbidden in ("rmtree", "DELETE FROM", "INSERT INTO", "UPDATE "):
        assert forbidden not in src, f"integrity engine must not {forbidden}"
