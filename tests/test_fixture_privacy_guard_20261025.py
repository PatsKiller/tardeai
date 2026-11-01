"""The repository is public: no test fixture may carry the operator's account ids or live holdings symbols.

CI: committed account-id patterns only (tests/privacy/fixture_privacy_denylist.json; no real symbols are committed).
Host: the live held symbols and account ids are computed at test time from persistent-state holdings.json and checked
too. Files present on main before this guard are listed by path (shrink-only); everything else must be clean.
"""
import json
import os
from pathlib import Path
import pwd
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
DENY = json.loads((ROOT / "tests/privacy/fixture_privacy_denylist.json").read_text(encoding="utf-8"))
PATTERNS = [re.compile(p) for p in DENY["account_id_patterns"]]
PREEXISTING = set(DENY["preexisting_files"])
HOLDINGS = (Path(pwd.getpwuid(os.getuid()).pw_dir)
            / "trade-ai-releases/persistent-state/data/portfolios/state/holdings.json")


def fixture_files():
    for path in sorted((ROOT / "tests/fixtures").rglob("*")):
        if path.is_file():
            yield path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8", errors="ignore")


def test_no_new_fixture_carries_an_account_id_pattern():
    bad = [rel for rel, text in fixture_files() if rel not in PREEXISTING and any(p.search(text) for p in PATTERNS)]
    assert not bad, f"account ids in public fixtures: {bad}"


def test_preexisting_list_is_shrink_only():
    present = {rel for rel, _ in fixture_files()}
    assert PREEXISTING <= present, f"remove deleted files from the denylist: {sorted(PREEXISTING - present)}"
    assert not any("golden_20261025" in rel for rel in PREEXISTING)


def test_detector_catches_account_ids():
    for sample in ("schwab_rollover_ira", "acct moomoo_taxable_live", "Fidelity_Roth_IRA"):
        assert any(p.search(sample) for p in PATTERNS), sample
    for sample in ("taxable_a", "ira_a", "roth_a", "schwab_transport"):
        assert not any(p.search(sample) for p in PATTERNS), sample


@pytest.mark.host_state("reads the live holdings file to build the check list at test time; skips in CI")
def test_host_live_holdings_never_appear_in_new_fixtures():
    if not HOLDINGS.is_file():
        pytest.skip("live holdings are host-only")
    rows = json.loads(HOLDINGS.read_text(encoding="utf-8")).get("holdings") or []
    symbols = {str(r.get("symbol") or "").upper() for r in rows
               if not r.get("is_cash") and float(r.get("quantity") or r.get("shares") or 0) > 0} - {""}
    accounts = {str(r.get("account_id") or r.get("account") or "") for r in rows} - {""}
    words = [re.compile(r"(?<![A-Za-z0-9_])" + re.escape(s) + r"(?![A-Za-z0-9_])") for s in symbols]
    bad = [rel for rel, text in fixture_files() if rel not in PREEXISTING and (
        any(a in text for a in accounts) or any(w.search(text) for w in words))]
    assert not bad, f"{len(bad)} public fixture(s) carry live holdings symbols or account ids: {bad}"
