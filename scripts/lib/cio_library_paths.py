"""Where the institutional library lives on disk. One resolver, not three.

Wave 3A moved the monthly series out of `tests/fixtures/`. Live operator
numbers must not resolve out of a test directory: a fixture edited to make a
test pass would silently move `grade=B` figures on the operator product, and
nothing in the test would look wrong.

`data/` is NOT a viable home. `cio_phase2_exact_main_deploy.sh` rsyncs the
release with `--exclude='data/'` (line ~312), and `CURRENT/data/cio` is a
symlink to mutable host state, so a tracked file under `data/cio/library/`
would be shadowed on the host and never promoted. `reference/` is a normal
repo path: version-controlled, copied into every release, identical across
hosts — which is what static reference data needs.
"""
from __future__ import annotations

from pathlib import Path

LIBRARY_PATHS_VERSION = "library_paths_1.0.0"

_REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_ROOT = _REPO_ROOT / "reference" / "library"

US_EQUITY_MONTHLY = LIBRARY_ROOT / "us_equity_monthly_synthetic_1950_2024.csv"
US_EQUITY_MONTHLY_MANIFEST = LIBRARY_ROOT / (
    "us_equity_monthly_synthetic_1950_2024.manifest.json")

# The old location, kept only so a stale reference fails loudly instead of
# silently resolving to a file someone edited for a test.
LEGACY_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "us_equity_monthly_sample.csv"


def us_equity_monthly_path() -> Path:
    """Resolve the monthly series. Never returns a path under tests/."""
    if US_EQUITY_MONTHLY.exists():
        return US_EQUITY_MONTHLY
    # Do not fall back to tests/. A missing library file is a deployment
    # problem to surface, not something to paper over with test data.
    return US_EQUITY_MONTHLY


def resolves_under_tests(path: Path | str | None = None) -> bool:
    """True if a path lives under tests/. Used by the guard test."""
    p = Path(path) if path is not None else us_equity_monthly_path()
    return "tests" in p.resolve().parts


# --- Wave 3A.3: operator surfaces grade off real market data -----------------
#
# `us_equity_monthly_path()` above still returns the SYNTHETIC series. That is
# deliberate and must stay: `research_governance/almanac.py` reads it, that
# module is R1-frozen, and the synthetic file is a legitimate
# pipeline-determinism fixture — 1987-10 at +3.27% is stable and knowable.
#
# What it must NOT do is grade an operator-visible number. Everything the
# operator reads (home.seasonality, strategy_context, the almanac headlines)
# now resolves here instead: the Ken French monthly series, normalised by
# scripts/build_french_monthly_normalized.py into the columns the seasonality
# loader already parses.
#
# Two resolvers, one rule: determinism fixtures may be synthetic, operator
# surfaces may not.

OPERATOR_MONTHLY = (LIBRARY_ROOT / "series" /
                    "us_equity_monthly_french_1926.csv")
FRENCH_FACTORS_MONTHLY = (LIBRARY_ROOT / "series" /
                          "ff_research_data_factors_monthly.csv")


def operator_monthly_series_path() -> Path:
    """The series any operator-visible seasonality number must grade from.

    Never falls back to the synthetic file. A missing library file should
    surface as a deployment problem, not silently downgrade the operator
    product to synthetic data wearing a grade=B label.
    """
    return OPERATOR_MONTHLY


def is_synthetic_path(path: Path | str | None = None) -> bool:
    """True for the synthetic determinism fixture or the retired test path."""
    p = Path(path) if path is not None else operator_monthly_series_path()
    name = p.name.lower()
    return "synthetic" in name or "tests" in p.parts or name == LEGACY_FIXTURE.name
