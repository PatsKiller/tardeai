"""Wave 3A — the institutional library has a home outside tests/.

Live operator numbers must not resolve out of a test directory. A fixture
edited to make some unrelated test pass would silently move the `grade=B`
figures shown on the operator product, and nothing in that test would look
wrong. This pins the new home and the provenance record.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.cio_library_paths import (
    LIBRARY_ROOT, US_EQUITY_MONTHLY, US_EQUITY_MONTHLY_MANIFEST,
    resolves_under_tests, us_equity_monthly_path,
)

REPO = Path(__file__).resolve().parents[1]


def test_seasonality_does_not_resolve_under_tests():
    """The guard the operator asked for."""
    assert not resolves_under_tests(), (
        f"seasonality series still resolves under tests/: {us_equity_monthly_path()}")


def test_both_consumers_point_at_the_library():
    """Neither resolves out of tests/ any more.

    Wave 3A.3 split the two: the operator surface grades off real market data
    (Ken French) while research_governance/almanac keeps the synthetic
    determinism fixture. Both live under reference/library.
    """
    from scripts.lib.cio_library_paths import OPERATOR_MONTHLY
    from scripts.lib.cio_seasonality_analytics import DEFAULT_FIXTURE as analytics
    from scripts.lib.research_governance.almanac import DEFAULT_FIXTURE as almanac

    for p in (analytics, almanac):
        assert "tests" not in p.parts, p
        assert LIBRARY_ROOT in p.parents, p
    assert analytics == OPERATOR_MONTHLY, "operator surface must be real data"
    assert almanac == US_EQUITY_MONTHLY, "R1 determinism fixture is unchanged"


def test_the_series_is_present_and_intact():
    assert US_EQUITY_MONTHLY.exists()
    rows = US_EQUITY_MONTHLY.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 901, "900 data rows + header"


def test_the_old_fixture_path_is_gone():
    """A stale reference must fail loudly, not resolve to leftover test data."""
    assert not (REPO / "tests" / "fixtures" / "us_equity_monthly_sample.csv").exists()


def test_no_source_still_references_the_old_path():
    # pr_scope_guard names the retired path as an allowlist pattern so the
    # move itself is permitted; that is a reference to the path, not a use of
    # it, so it is exempt.
    exempt = {"scripts/lib/research_governance/pr_scope_guard.py"}
    offenders = []
    for path in list((REPO / "scripts").rglob("*.py")):
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        if rel in exempt:
            continue
        txt = path.read_text(encoding="utf-8", errors="replace")
        if "tests/fixtures/us_equity_monthly_sample.csv" in txt.replace("\\", "/"):
            offenders.append(rel)
    assert not offenders, offenders


# ------------------------------------------------------------ provenance

def test_the_manifest_records_that_the_series_is_synthetic():
    """The finding that motivated the rename.

    Two repo docs already said so (PHASE11_16_RESEARCH_BRAIN: "synthetic but
    statistically usable"; R3_ALMANAC_REPRODUCTION: "not a vendor print"), but
    the filename said "sample" and the operator product says "grade=B".
    """
    m = json.loads(US_EQUITY_MONTHLY_MANIFEST.read_text(encoding="utf-8"))
    assert m["provenance"] == "SYNTHETIC"
    assert m["is_market_data"] is False
    assert m["vendor_print"] is False
    assert m["previous_path"] == "tests/fixtures/us_equity_monthly_sample.csv"


def test_the_series_is_demonstrably_not_market_history():
    """Guards the manifest's claim against the file silently being swapped.

    If someone later drops real market data in at this path, this test fails
    and the manifest must be corrected — which is the intended outcome, not a
    nuisance. October 1987 is the cheapest possible discriminator.
    """
    import csv

    rows = list(csv.DictReader(US_EQUITY_MONTHLY.open(encoding="utf-8")))
    oct87 = next(r for r in rows
                 if int(r["year"]) == 1987 and int(r["month"]) == 10)
    worst = min(float(r["return_pct"]) for r in rows)
    assert float(oct87["return_pct"]) > -10.0, (
        "1987-10 looks like real market history (about -21.5%); if the series "
        "was replaced with real data, update the manifest provenance")
    assert worst > -10.0, "no crash-magnitude month exists in this series"


def test_manifest_hash_matches_the_file():
    import hashlib

    m = json.loads(US_EQUITY_MONTHLY_MANIFEST.read_text(encoding="utf-8"))
    actual = hashlib.md5(US_EQUITY_MONTHLY.read_bytes()).hexdigest()
    assert actual == m["content_md5"], (
        "series content changed without the manifest being updated")


# ------------------------------------------------------- numbers unchanged

@pytest.mark.parametrize("fn,n,grade", [
    ("august_general", 75, "B"),
    ("august_midterm", 19, "C"),
    ("september_general", 75, "B"),
    ("best_six_months", 450, "B"),
])
def test_relocation_did_not_move_the_numbers(fn, n, grade):
    """The 3A.1 move was number-neutral, pinned against that same file.

    Read explicitly from the synthetic fixture rather than the module default:
    3A.3 repointed the default to Ken French, which moves these numbers on
    purpose. What this test still guards is that *relocating a file* changed
    nothing — which is a different claim from what the surface should show.
    """
    from scripts.lib import cio_seasonality_analytics as sa

    prev = sa.DEFAULT_FIXTURE
    sa.DEFAULT_FIXTURE = US_EQUITY_MONTHLY
    sa._cached_rows.cache_clear()
    try:
        rec = getattr(sa, fn)()
        assert rec["n"] == n
        assert rec["evidence_grade"] == grade
    finally:
        sa.DEFAULT_FIXTURE = prev
        sa._cached_rows.cache_clear()


def test_august_headline_figures_are_unchanged():
    """Against the determinism fixture. The live surface now shows French."""
    from scripts.lib import cio_seasonality_analytics as sa

    prev = sa.DEFAULT_FIXTURE
    sa.DEFAULT_FIXTURE = US_EQUITY_MONTHLY
    sa._cached_rows.cache_clear()
    try:
        rec = sa.august_general()
        assert round(rec["mean"], 2) == -0.07
        assert round(rec["win_rate"] * 100, 1) == 45.3
    finally:
        sa.DEFAULT_FIXTURE = prev
        sa._cached_rows.cache_clear()


def test_library_root_is_not_under_data():
    """`data/` is rsync-excluded by the deploy and symlinked to host state.

    A tracked file under data/cio/library/ would be shadowed on the host and
    never promoted, so the library lives in a normal repo path instead.
    """
    assert "data" not in LIBRARY_ROOT.relative_to(REPO).parts
    deploy = (REPO / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text(
        encoding="utf-8", errors="replace")
    assert "--exclude='data/'" in deploy, (
        "if data/ is no longer excluded, reconsider the library home")
