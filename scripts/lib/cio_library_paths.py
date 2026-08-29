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
