"""The CANONICAL list must only name docs the sync can actually upload.

`sync-docs-to-drive.sh` skips docs/_archive, docs/_trash and docs/_findings via
`is_runtime_dump_excluded` — "dead Drive parents / scratch shots". Two
docs/_findings/ entries sat in CANONICAL from 2026-07-19 to 2026-08-29 and so
reported DRIFT every hour of that window. The cost is not the noise: a standing
alarm hides a real one.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "scripts" / "check_docs_drive_parity.py"
SYNC = ROOT / "scripts" / "sync-docs-to-drive.sh"


def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_parity", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # raises SystemExit if the list is bad
    return mod


def test_no_canonical_doc_lives_in_a_tree_the_sync_skips():
    mod = _load()
    bad = [d for d in mod.CANONICAL
           if d.startswith(mod.SYNC_EXCLUDED_PREFIXES)]
    assert not bad, f"unsyncable and therefore permanently drifting: {bad}"


def test_the_two_findings_entries_are_gone():
    """They are scratch shots, not canonical — operator decision 2026-08-29."""
    assert not [d for d in _load().CANONICAL if "_findings/" in d]


def test_the_excluded_prefixes_match_the_sync_script():
    """If the sync widens its skip list, this list has to follow."""
    mod = _load()
    body = SYNC.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"docs/_archive/\*\|docs/_trash/\*\|docs/_findings/\*", body)
    assert m, "sync exclusion line moved — re-check SYNC_EXCLUDED_PREFIXES"
    for prefix in ("docs/_archive/", "docs/_trash/", "docs/_findings/"):
        assert prefix in mod.SYNC_EXCLUDED_PREFIXES


def test_canonical_docs_exist_on_disk():
    missing = [d for d in _load().CANONICAL if not (ROOT / d).exists()]
    assert not missing, f"CANONICAL names files that do not exist: {missing}"
