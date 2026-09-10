"""Dry self-repair harness — synthetic before/after only."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.run_self_repair_loop_dry import main, run_dry


def test_run_dry_success():
    report = run_dry()
    assert report["dry_ok"] is True
    assert report["mbi_behavior"] == 0
    assert report["proposal"]["executable"] is False
    assert report["proposal"]["financial_surface_reachable"] is False
    assert report["verify"]["passed"] is True
    assert report["production_mutation"] is False


def test_run_dry_fails_when_after_still_drifted():
    report = run_dry(
        before={"matches_current": False, "mismatch_reason": "cwd_ne_current"},
        after={"matches_current": False, "mismatch_reason": "cwd_ne_current"},
    )
    assert report["dry_ok"] is False
    assert report["verify"]["passed"] is False
    assert report["verify"]["rollback_recommended"] is True


def test_cli_exit_zero(tmp_path: Path, capsys):
    out = tmp_path / "dry.json"
    rc = main(["--out", str(out)])
    assert rc == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["dry_ok"] is True
    captured = capsys.readouterr().out
    assert "dry_ok" in captured
