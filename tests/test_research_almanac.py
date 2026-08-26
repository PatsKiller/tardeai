"""R3 Almanac reproduction dry tests."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_governance import acceptance  # noqa: E402
from scripts.lib.research_governance.almanac import (  # noqa: E402
    AUTHORITY,
    bundle,
    challenge_calendar_family,
    is_midterm_year,
    presidential_cycle_label,
    reproduce_slice,
    reproduced_weak_months,
)


def test_2026_is_mechanical_midterm():
    assert is_midterm_year(2026)
    assert presidential_cycle_label(2026) == "midterm_year"
    assert presidential_cycle_label(2024) == "election_year"


def test_layers_not_collapsed():
    sl = reproduce_slice("september_general")
    assert set(sl["layers"]) == {"source_claim", "trade_ai_reproduction", "current_application"}
    claim = sl["layers"]["source_claim"]
    assert claim["citation_only"] is True
    assert claim["fulltext"] is False
    assert claim["url"].startswith("https://")
    assert sl["partisan_conclusion"] is None
    assert sl["layers"]["current_application"]["standalone_sell"] is False
    assert sl["layers"]["current_application"]["creates_trim"] is False


def test_fixture_reproduction_nonzero():
    sl = reproduce_slice("august_general")
    assert sl["n"] and sl["n"] > 10
    assert sl["mean"] is not None


def test_august_not_hardcoded_bearish():
    pack = bundle(as_of_year=2026)
    assert pack["august_hardcoded_bearish"] is False
    weak = set(pack["reproduced_weak_months"])
    if 8 in weak:
        assert pack["slices"]["august_general"]["mean"] is not None


def test_no_trim_no_sell_authority():
    pack = bundle()
    assert pack["authority"] == AUTHORITY
    assert pack["standalone_sell"] is False
    assert pack["creates_trim"] is False
    assert pack["fulltext"] is False
    assert pack["max_influence_pct"] <= 10.0


def test_calendar_family_challenge_is_family():
    ch = challenge_calendar_family()
    assert ch["winner_only"] is False
    assert ch["whole_family"] is True
    if ch["status"] == "OK":
        assert ch["n_rules"] >= 2


def test_weak_months_from_stats():
    weak = reproduced_weak_months()
    assert isinstance(weak, set)
    assert all(1 <= m <= 12 for m in weak)


def test_r3_acceptance_profile():
    rep = acceptance.run_acceptance("R3_almanac")
    assert "RGA-15" in rep["required_runtime_pass"], rep
    assert "RGA-16" in rep["not_in_scope"]
    assert rep["overall"] == "PASS", rep
