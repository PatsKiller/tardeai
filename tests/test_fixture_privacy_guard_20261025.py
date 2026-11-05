"""The repository is public: no test fixture may carry the operator's account ids or live holdings symbols.

CI: committed account-id patterns only (tests/privacy/fixture_privacy_denylist.json; no real symbols are committed).
Host: the live held symbols and account ids are computed at test time from persistent-state holdings.json and checked
too.

The pre-existing set — fixtures already on ``origin/main`` — is DERIVED at test time from
``git ls-tree -r --name-only origin/main -- tests/fixtures``, never hand-listed. A hand-listed set cannot notice a
fixture main gains from another branch, so it reports main's own fixtures as this branch's leak; a generated file the
build refreshes has the same defect between refreshes. Derivation has one failure mode worth stating: if
``origin/main`` cannot be resolved (shallow clone, no remote), the guard cannot tell a new fixture from an old one,
so it FAILS CLOSED with that reason rather than silently treating every fixture — or no fixture — as new.
"""
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
DENY = json.loads((ROOT / "tests/privacy/fixture_privacy_denylist.json").read_text(encoding="utf-8"))
PATTERNS = [re.compile(p) for p in DENY["account_id_patterns"]]
HOLDINGS = (Path(pwd.getpwuid(os.getuid()).pw_dir)
            / "trade-ai-releases/persistent-state/data/portfolios/state/holdings.json")
BASE_REF = "origin/main"


class BaseUnavailable(RuntimeError):
    """``origin/main`` could not be read, so the pre-existing fixture set cannot be derived."""


def _git_paths(*args):
    """Repo-relative paths printed by one git command, or BaseUnavailable with git's own reason."""
    try:
        listing = subprocess.run(["git", "-C", str(ROOT), *args],
                                 capture_output=True, text=True, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", "") or getattr(exc, "stdout", "") or str(exc)
        first = (detail.strip().splitlines() or ["no output"])[0]
        raise BaseUnavailable(f"cannot derive the pre-existing fixture set: git {' '.join(args)}: {first[:200]}")
    return {rel for rel in listing.stdout.splitlines() if rel}


def preexisting_fixtures():
    """Fixtures already on origin/main. Derived from git, never hand-listed."""
    return _git_paths("ls-tree", "-r", "--name-only", BASE_REF, "--", "tests/fixtures")


def branch_added_fixtures():
    """Fixtures this branch adds relative to origin/main (empty once it has merged).

    The comparison ref is the literal main branch, not BASE_REF: a derivation pointed at the branch tree must not
    also move the yardstick it is checked against.
    """
    return _git_paths("diff", "--name-only", "origin/main...HEAD", "--", "tests/fixtures")


def _preexisting():
    try:
        preexisting = preexisting_fixtures()
    except BaseUnavailable as exc:
        pytest.fail(str(exc))
    if not preexisting:
        pytest.fail("origin/main carries no tests/fixtures paths, so the derived pre-existing set is empty and the "
                    "guard cannot tell a new fixture from an old one; refusing to pass")
    return preexisting


def fixture_files():
    for path in sorted((ROOT / "tests/fixtures").rglob("*")):
        if path.is_file():
            yield path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8", errors="ignore")


def test_no_new_fixture_carries_an_account_id_pattern():
    preexisting = _preexisting()
    bad = [rel for rel, text in fixture_files() if rel not in preexisting and any(p.search(text) for p in PATTERNS)]
    assert not bad, f"account ids in public fixtures: {bad}"


def test_preexisting_set_is_derived_from_main_and_nonempty():
    try:
        preexisting = preexisting_fixtures()
    except BaseUnavailable as exc:
        pytest.fail(str(exc))
    assert preexisting, ("origin/main carries no tests/fixtures paths, so the derived pre-existing set is empty "
                         "and every fixture would be reported as this branch's leak; refusing to pass")
    strays = sorted(rel for rel in preexisting if not rel.startswith("tests/fixtures/"))
    assert not strays, f"the derivation must be scoped to tests/fixtures, not the whole tree: {strays[:5]}"
    added = branch_added_fixtures()
    assert not (preexisting & added), (
        "fixtures this branch adds must never be in the pre-existing set, or the guard cannot bite: "
        f"{sorted(preexisting & added)[:5]}")


def test_detector_catches_account_ids():
    for sample in ("schwab_rollover_ira", "acct moomoo_taxable_live", "Fidelity_Roth_IRA"):
        assert any(p.search(sample) for p in PATTERNS), sample
    for sample in ("taxable_a", "ira_a", "roth_a", "schwab_transport"):
        assert not any(p.search(sample) for p in PATTERNS), sample


def test_new_fixture_is_flagged_while_preexisting_is_spared(monkeypatch):
    """The filter bites: the same offending text is spared on main and flagged when this branch adds it."""
    preexisting = _preexisting()
    old = sorted(preexisting)[0]
    new = "tests/fixtures/zz_privacy_probe_new_fixture.json"
    assert new not in preexisting
    text = "schwab_rollover_ira"  # the committed pattern, no live value
    monkeypatch.setattr(sys.modules[__name__], "fixture_files", lambda: [(old, text), (new, text)])
    bad = [rel for rel, body in fixture_files() if rel not in preexisting and any(p.search(body) for p in PATTERNS)]
    assert bad == [new], f"a pre-existing fixture must be spared and a new one flagged, got {bad}"


@pytest.mark.host_state("reads the live holdings file to build the check list at test time; skips in CI")
def test_host_live_holdings_never_appear_in_new_fixtures():
    if not HOLDINGS.is_file():
        pytest.skip("live holdings are host-only")
    preexisting = _preexisting()
    rows = json.loads(HOLDINGS.read_text(encoding="utf-8")).get("holdings") or []
    symbols = {str(r.get("symbol") or "").upper() for r in rows
               if not r.get("is_cash") and float(r.get("quantity") or r.get("shares") or 0) > 0} - {""}
    accounts = {str(r.get("account_id") or r.get("account") or "") for r in rows} - {""}
    words = [re.compile(r"(?<![A-Za-z0-9_])" + re.escape(s) + r"(?![A-Za-z0-9_])") for s in symbols]
    bad = [rel for rel, text in fixture_files() if rel not in preexisting and (
        any(a in text for a in accounts) or any(w.search(text) for w in words))]
    assert not bad, f"{len(bad)} public fixture(s) carry live holdings symbols or account ids: {bad}"
