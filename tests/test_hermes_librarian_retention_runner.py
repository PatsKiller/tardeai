"""Smoke tests for librarian retention CLI wiring."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_retention():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "lib" / "hermes_librarian" / "retention.py"
    spec = importlib.util.spec_from_file_location("hermes_librarian_retention", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_retention_module_exposes_apply():
    mod = _load_retention()
    assert callable(mod.apply_retention)
    assert callable(mod.load_policy)
    pol = mod.load_policy()
    assert "content_embeddings" in pol
    assert int(pol["content_embeddings"].get("orphan_purge_days", 0)) >= 1


def test_runner_script_exists_and_is_executable_entry():
    root = Path(__file__).resolve().parents[1]
    p = root / "scripts" / "run_hermes_librarian_retention.py"
    assert p.is_file()
    text = p.read_text()
    assert "apply_retention" in text
    assert "--apply" in text
