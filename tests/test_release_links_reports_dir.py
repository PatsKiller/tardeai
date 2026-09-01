"""Every directory a served surface READS must be in the deploy's linked set.

Cause (2026-09-01 09:58): the scalp scanner globs
    PROJECT_ROOT/reports/2026-*/*/run_summary.json
and PROJECT_ROOT is the RELEASE directory. `reports` was not in the linked set,
so every release served a reports/ that did not exist. The glob returned zero
runs and the panel fell back to a stale record: run_label "1730" from 2026-08-31
with an empty timestamp and 0 symbols scanned, while $PROJ/reports held that
morning's 09:00 run with 53 tickers.

This is the same shape as the logs/ fork already documented in the deploy script:
a directory absent from the list is silently forked per release, and the surface
reading it reports a false ABSENT rather than an error.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PHASE2 = ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh"
LEGACY = ROOT / "scripts" / "deploy_portfolio_server.sh"


def _linked_dirs(text: str, opener: str) -> list:
    """Entries between the opener and the closing paren ON ITS OWN LINE.

    Splitting on the first ")" is wrong: a prose comment inside the array can
    contain one, which truncates the block and hides later entries. That is
    exactly how this test first failed against a correct source file.
    """
    body = text.split(opener, 1)[1]
    end = re.search(r"^\s*\)\s*$", body, re.M)
    block = body[: end.start()] if end else body
    return re.findall(r'"([^"]+)"', block)


@pytest.mark.parametrize("path,opener", [
    (PHASE2, "local dirs=("),
    (LEGACY, "DATA_DIRS_TO_LINK=("),
], ids=["phase2", "legacy"])
def test_reports_is_linked_into_the_release(path, opener):
    if not path.exists():
        pytest.skip(f"{path.name} absent")
    dirs = _linked_dirs(path.read_text(), opener)
    assert "reports" in dirs, (
        f"{path.name} does not link reports/ — the scalp scanner reads "
        "PROJECT_ROOT/reports and will serve an absent directory as zero runs"
    )


@pytest.mark.parametrize("path,opener", [
    (PHASE2, "local dirs=("),
    (LEGACY, "DATA_DIRS_TO_LINK=("),
], ids=["phase2", "legacy"])
def test_the_known_state_dirs_are_still_linked(path, opener):
    """Guard against a future edit dropping one, which is how reports/ was lost."""
    if not path.exists():
        pytest.skip(f"{path.name} absent")
    dirs = _linked_dirs(path.read_text(), opener)
    for required in ("data/portfolios/state", "state/data_broker", "data/runtime",
                     "data/health", "data/cio"):
        assert required in dirs, f"{path.name} stopped linking {required}"


def test_the_scanner_still_reads_reports_from_project_root():
    """If the scanner stops globbing PROJECT_ROOT/reports this test is obsolete.

    Pinning the coupling means the link requirement above cannot quietly become
    wrong without something failing.
    """
    api = ROOT / "scripts" / "api_v2.py"
    if not api.exists():
        pytest.skip("api_v2.py absent")
    text = api.read_text()
    assert "reports/2026-*/*/run_summary.json" in text, (
        "the scanner no longer globs PROJECT_ROOT/reports — re-evaluate whether "
        "reports/ still needs to be linked into the release"
    )
