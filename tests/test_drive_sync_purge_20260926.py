"""The hourly purge must not drop dated top-level docs FILES (they re-uploaded every hour).

2026-09-26: purge_dead_archive_cache in sync-docs-to-drive.sh treated the first
segment after docs/ as a directory. For a top-level dated doc
(docs/CIO_AS_IS_2026-09-20-0604.md) that segment is the FILE name, so its manifest
line was purged every run and the file re-uploaded hourly. It also dropped any line
containing /_archive/, including config/strategies/_archive/*.yaml, which the
config find does not prune -- another hourly re-upload.

Intent (d0412874c): dated first-level docs DIRS excluded; dated files synced;
_archive excluded. config/strategies/_archive is now excluded by the
is_runtime_dump_excluded case rule, not by the purge.

Behavioural: the script's embedded purge Python is extracted and executed on temp
files; the bash exclusion function is extracted and executed. No Drive call.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "scripts" / "sync-docs-to-drive.sh"


def _between(body: str, start: str, end: str) -> str:
    a = body.index(start)
    b = body.index(end, a)
    return body[a:b]


def _purge_python() -> str:
    body = SYNC.read_text(encoding="utf-8")
    fn = _between(body, "purge_dead_archive_cache() {", "\n}\n")
    return _between(fn, "<<'PY'\n", "\nPY")[len("<<'PY'\n"):]


def _purge(tmp_path: Path, cache_lines: list[str], manifest_lines: list[str]) -> tuple[list[str], list[str]]:
    cache = tmp_path / "cache.txt"
    manifest = tmp_path / "manifest.txt"
    cache.write_text("".join(f"{x}\n" for x in cache_lines), encoding="utf-8")
    manifest.write_text("".join(f"{x}\n" for x in manifest_lines), encoding="utf-8")
    proc = subprocess.run([sys.executable, "-c", _purge_python(), str(cache), str(manifest)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return (cache.read_text(encoding="utf-8").splitlines(),
            manifest.read_text(encoding="utf-8").splitlines())


def test_dated_top_level_docs_file_is_kept(tmp_path):
    line = "docs/CIO_AS_IS_2026-09-20-0604.md|abc"
    _, manifest = _purge(tmp_path, [], [line])
    assert line in manifest


def test_dated_docs_dir_is_dropped_from_cache_and_nested_manifest(tmp_path):
    cache_line = "docs/session_2026_05_22|FOLDERID"
    man_line = "docs/session_2026_05_22/notes.md|abc"
    cache, manifest = _purge(tmp_path, [cache_line], [man_line])
    assert cache_line not in cache
    assert man_line not in manifest


def test_docs_archive_is_dropped(tmp_path):
    cache, manifest = _purge(tmp_path, ["docs/_archive|F1", "docs/_archive/old|F2"],
                             ["docs/_archive/old/x.md|abc"])
    assert not [x for x in cache if "_archive" in x]
    assert not manifest


def test_config_strategies_archive_is_left_for_the_case_rule(tmp_path):
    line = "config/strategies/_archive/retired.yaml|abc"
    cache_line = "config/strategies/_archive|F3"
    cache, manifest = _purge(tmp_path, [cache_line], [line])
    assert line in manifest
    assert cache_line in cache


def test_session_docs_under_ops_are_kept(tmp_path):
    line = "docs/ops/SESSION_2026-09-20_notes.md|abc"
    cache, manifest = _purge(tmp_path, ["docs/ops|OPS"], [line])
    assert line in manifest
    assert "docs/ops|OPS" in cache


def test_canonical_folder_lines_kept(tmp_path):
    cache, _ = _purge(tmp_path, ["docs|D", "docs/recovery|R"], [])
    assert cache == ["docs|D", "docs/recovery|R"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
@pytest.mark.parametrize("rel,expected", [
    ("config/strategies/_archive/x.yaml", 0),
    ("config/strategies/live.yaml", 1),
    ("docs/CIO_AS_IS_2026-09-20-0604.md", 1),
    ("docs/_archive/x.md", 0),
])
def test_is_runtime_dump_excluded(rel, expected):
    body = SYNC.read_text(encoding="utf-8")
    fn = _between(body, "is_runtime_dump_excluded() {", "\n}\n") + "\n}\n"
    proc = subprocess.run(["bash", "-c", fn + f'\nis_runtime_dump_excluded "{rel}"'],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == expected, (rel, proc.stderr)
