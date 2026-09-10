"""Unit tests for docs tip hygiene planning (no live git rm)."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "docs_tip_hygiene_enforcer.py"
    spec = importlib.util.spec_from_file_location("docs_tip_hygiene_enforcer", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_plan_never_includes_active_keep():
    hy = _load()
    pol = hy._load_policy()
    planned = hy.plan(pol)
    for c in planned["candidates"]:
        assert "project/" not in c["path"] or c["status_guess"] not in (
            "active_keep",
            "current_phase_keep",
        )
        assert c["path"] != "docs/INDEX.md"
        assert not c["path"].startswith("docs/architecture/")


def test_dry_run_apply_git_rm_does_not_delete(tmp_path, monkeypatch):
    hy = _load()
    # Point ROOT temporarily? apply_git_rm uses module ROOT — just dry_run
    res = hy.apply_git_rm(["docs/DOES_NOT_EXIST.md"], dry_run=True)
    assert res["dry_run"] is True
    assert res["ok"] is True
