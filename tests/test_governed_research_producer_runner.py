"""Controls for the scheduled entrypoint of the governed research producer.

The producer library landed with 12 tests and no way to run it: no entrypoint,
no cron, flag default OFF. `research_objects_proxy` read 0 on every hourly pass
and every wake fell through to `material_change`. These controls pin the
properties that make a SCHEDULED path safe, and each must go red if the
corresponding guarantee is removed.

They exercise the runner only. Provider governance belongs to the library and is
tested there; nothing here re-implements or relaxes it.
"""
from __future__ import annotations

import json

import pytest

from scripts import run_governed_research_producer as runner


def _run(argv, capsys):
    rc = runner.main(argv)
    return rc, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


# --- fail-closed defaults -----------------------------------------------------

def test_no_target_source_produces_nothing(capsys, monkeypatch):
    """A scheduled run with no targets must not become a provider call."""
    monkeypatch.delenv(runner.grp.FEATURE_FLAG, raising=False)
    rc, out = _run(["--dry-run"], capsys)
    assert rc == 0
    assert out["requested"] == 0 and out["eligible"] == 0


def test_flag_off_is_disabled_and_has_no_side_effects(capsys, monkeypatch):
    """The feature flag is the outermost switch; OFF must reach no provider."""
    monkeypatch.delenv(runner.grp.FEATURE_FLAG, raising=False)
    rc, out = _run(["--symbols", "NVDA"], capsys)
    assert rc == 0, "a disabled scheduled run is a legitimate outcome, not a failure"
    assert out["outcome"] == "disabled"
    assert out["produced"] == 0
    assert "feature_flag_off" in out["errors"]


def test_dry_run_never_calls_the_provider(capsys, monkeypatch):
    """--dry-run must exit before the provider boundary even when ENABLED.

    The regression this blocks: making --dry-run a thin wrapper that still runs a
    pass. `gog drive upload -n` was observed mutating for exactly this reason, so
    a dry-run flag in this repo has to be proven, not assumed.
    """
    monkeypatch.setenv(runner.grp.FEATURE_FLAG, "1")

    def _explode(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("dry-run reached produce_research()")

    monkeypatch.setattr(runner.grp, "produce_research", _explode)
    rc, out = _run(["--dry-run", "--symbols", "NVDA"], capsys)
    assert rc == 0 and out["mode"] == "dry_run"


# --- target handling ----------------------------------------------------------

def test_limit_caps_targets_so_a_schedule_cannot_run_away(capsys, monkeypatch):
    """An unbounded scheduled pass is unbounded spend."""
    monkeypatch.delenv(runner.grp.FEATURE_FLAG, raising=False)
    rc, out = _run(["--dry-run", "--symbols", "NVDA,AMD,INTC,AAPL", "--limit", "2"], capsys)
    assert out["requested"] == 2


def test_targets_without_a_registry_subject_guid_are_skipped(capsys, monkeypatch):
    """subject_guid is looked up, never minted. Unknown symbols drop out."""
    monkeypatch.delenv(runner.grp.FEATURE_FLAG, raising=False)
    rc, out = _run(["--dry-run", "--symbols", "ZZZZNOTAREALTICKER"], capsys)
    assert out["eligible"] == 0
    assert out["skipped_no_subject_guid"] == 1


def test_targets_file_accepts_json_and_jsonl(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(runner.grp.FEATURE_FLAG, raising=False)
    p = tmp_path / "t.json"
    p.write_text(json.dumps([{"symbol": "NVDA"}]), encoding="utf-8")
    _, a = _run(["--dry-run", "--targets-file", str(p)], capsys)
    p2 = tmp_path / "t.jsonl"
    p2.write_text('{"symbol": "NVDA"}\n', encoding="utf-8")
    _, b = _run(["--dry-run", "--targets-file", str(p2)], capsys)
    assert a["requested"] == b["requested"] == 1


def test_symbols_and_targets_file_are_mutually_exclusive(tmp_path):
    """Two target sources in one scheduled line is an ambiguity, not a merge."""
    with pytest.raises(SystemExit):
        runner.build_parser().parse_args(
            ["--symbols", "NVDA", "--targets-file", str(tmp_path / "x.json")]
        )


# --- exit status contract -----------------------------------------------------

def test_broken_is_the_only_nonzero_exit(capsys, monkeypatch):
    """Cron needs 'nothing to do' to be quiet and 'broken' to be loud."""
    monkeypatch.setenv(runner.grp.FEATURE_FLAG, "1")

    class _R:
        outcome, ok, disabled, eligible, produced, errors = "broken", False, False, 1, 0, ["provider_unavailable"]

    monkeypatch.setattr(runner.grp, "produce_research", lambda **k: _R())
    rc, out = _run(["--symbols", "NVDA"], capsys)
    assert rc == 1 and out["outcome"] == "broken"

    class _O(_R):
        outcome, ok, errors = "nothing_eligible", True, []

    monkeypatch.setattr(runner.grp, "produce_research", lambda **k: _O())
    rc2, _ = _run(["--symbols", "NVDA"], capsys)
    assert rc2 == 0
