"""LQ-170: injectable clock (--as-of) for weekday/session emulation in watchlist_priority."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import watchlist_priority as wp  # noqa: E402


@pytest.fixture(autouse=True)
def _clear():
    wp.set_as_of(None)
    yield
    wp.set_as_of(None)


def test_saturday_midday_is_off_hours_even_if_real_clock_is_session():
    wp.set_as_of("2026-11-07T12:00:00")  # Saturday
    assert wp.is_off_hours_et() is True


def test_weekday_midday_is_in_session():
    wp.set_as_of("2026-11-09T12:00:00")  # Monday
    assert wp.is_off_hours_et() is False
    assert wp.off_hours_top_n(None) is None


def test_weekday_evening_off_hours_caps_to_top_n():
    wp.set_as_of("2026-11-09T18:00:00-05:00")
    assert wp.off_hours_top_n(None) == wp.WATCHLIST_TOP_N


def test_bad_value_raises_and_none_clears():
    with pytest.raises(ValueError):
        wp.set_as_of("not-a-date")
    wp.set_as_of("2026-11-07T12:00:00")
    wp.set_as_of(None)
    assert wp._AS_OF is None


def test_sweep_cli_accepts_as_of(monkeypatch):
    import watchlist_enrichment_sweep as sw
    seen = {}

    def fake_sweep(**kw):
        seen["off"] = wp.is_off_hours_et()
        return {"total": 0, "enriched": 0}

    monkeypatch.setattr(sw, "sweep", fake_sweep)
    monkeypatch.setattr(sw, "_receipt_lib", lambda: type("R", (), {"dry_run_report": staticmethod(lambda *a, **k: None)}))
    assert sw.main(["--dry-run", "--as-of", "2026-11-07T12:00:00"]) == 0
    assert seen["off"] is True
