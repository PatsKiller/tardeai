"""Unused state-changing routes and session validators are retired."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_uncalled_atm_posts_are_refused():
    text = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8")
    assert text.count("retired: no caller recorded. Not restored from an access count.") == 2
    assert 'base_path == "/api/v2/admin/atm/set-state"' in text
    assert 'base_path == "/api/v2/atm/close-action"' in text


def test_session_validator_stub_points_at_the_archive():
    stub = ROOT / "scripts/session11_validate.py"
    assert "scripts/archive/session_validate_20260927/" in stub.read_text(encoding="utf-8")
    assert (ROOT / "scripts/archive/session_validate_20260927/session11_validate.py").is_file()
