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


def test_legacy_deploy_links_reports_from_canonical_source():
    """deploy_portfolio_server.sh links DATA_DIRS_TO_LINK from CANONICAL_SOURCE,
    which is where the pipeline writes reports/ — so listing it there is correct."""
    if not LEGACY.exists():
        pytest.skip("deploy_portfolio_server.sh absent")
    assert "reports" in _linked_dirs(LEGACY.read_text(), "DATA_DIRS_TO_LINK=(")


def test_phase2_links_reports_from_canonical_source_not_the_overlay():
    """reports/ must NOT be in the phase2 overlay list.

    That list links from `overlay_src` (persistent-state), which has no reports/.
    Adding it there on 2026-09-01 linked nothing: the `[[ -e "$source" ]]` test
    was false and the branch had no else, so the deploy skipped in silence and the
    release still served an absent reports/. It needs its own link from
    CANONICAL_SOURCE, where the pipeline actually writes.
    """
    if not PHASE2.exists():
        pytest.skip("cio_phase2_exact_main_deploy.sh absent")
    text = PHASE2.read_text()
    assert "reports" not in _linked_dirs(text, "local dirs=("), (
        "reports/ is in the overlay list; the overlay root has no reports/ so this "
        "silently links nothing"
    )
    assert 'reports_src="${CANONICAL_SOURCE}/reports"' in text, (
        "phase2 must link reports/ explicitly from CANONICAL_SOURCE"
    )


def test_a_missing_overlay_source_is_reported_not_skipped_silently():
    """The silent skip is what hid this for a full deploy cycle.

    This originally required the literal WARN string "will serve it ABSENT".
    2026-09-05 replaced warning with something stronger: a path on the durable
    list is DECLARED durable, so a missing canonical source is now CREATED and
    linked rather than reported and left broken. Warning was better than silence
    and worse than fixing — reports/ sat warned-about and unlinked for four days.

    So the property is unchanged and the bar is raised: the else-branch must
    still never be silent, and must now also leave the directory linked. The old
    literal is no longer the only acceptable way to satisfy it.
    """
    if not PHASE2.exists():
        pytest.skip("cio_phase2_exact_main_deploy.sh absent")
    text = PHASE2.read_text()
    body = re.search(r'for rel in "\$\{dirs\[@\]\}"; do(.*?)\n  done', text, re.S)
    assert body, "could not locate the durable-directory link loop"
    else_branch = body.group(1).split("else", 1)[1]

    assert "log " in else_branch, (
        "a listed dir missing at the overlay source leaves no trace; a false "
        "[[ -e ]] with a silent else is indistinguishable from success"
    )
    assert 'ln -sfn "$source" "$target"' in else_branch, (
        "a missing canonical source is reported but still not linked — the "
        "directory stays orphaned and the list entry does nothing"
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
