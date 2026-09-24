"""The docs sync must not trash Drive copies of preserved captures when a release lacks them.

2026-09-23: an ad-hoc page walk wrote 228 Command Center captures INTO the live release
dir (docs/command-center-pages, not git-tracked). The next promote built a release
without them and the sync's cleanup pass trashed their Drive copies ("no longer exists
locally"). Preserved captures now keep their Drive file and manifest line.

Behavioural: the script's real cleanup block is extracted and EXECUTED in bash with
`gog` stubbed and a temp manifest/source tree, so no Drive call and no live state.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "scripts" / "sync-docs-to-drive.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")


def _between(body: str, start: str, end: str) -> str:
    a = body.index(start)
    b = body.index(end, a)
    return body[a:b]


def _run_cleanup(tmp_path: Path, manifest_lines: list[str], local_files: list[str]) -> tuple[str, str, str]:
    body = SYNC.read_text(encoding="utf-8")
    preserved_fn = _between(body, "is_preserved_capture() {", "\n}\n") + "\n}\n"
    excluded_fn = _between(body, "is_runtime_dump_excluded() {", "\n}\n") + "\n}\n"
    # The cleanup pass is the script's final section; it runs to end of file.
    cleanup = body[body.index("# ── Cleanup: remove Drive files whose local source was deleted ──") :]

    src = tmp_path / "src"
    for rel in local_files:
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    (src / "docs").mkdir(parents=True, exist_ok=True)
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("".join(f"{line}\n" for line in manifest_lines), encoding="utf-8")
    log = tmp_path / "sync.log"
    rm_calls = tmp_path / "rm_calls.txt"

    harness = f"""
SRC="{src}"
MANIFEST="{manifest}"
LOG="{log}"
DRIVE_FOLDER_ID=root
GOG_ACCOUNT=test
log() {{ echo "$1" >> "$LOG"; }}
resolve_existing_folder() {{ echo parent; }}
gog() {{
  if [ "$2" = "ls" ]; then
    echo '{{"files":[{{"id":"ID1","name":"'"$FNAME"'","mimeType":"text/plain"}}]}}'
  elif [ "$2" = "rm" ]; then
    echo "$3" >> "{rm_calls}"
  fi
}}
{preserved_fn}
{excluded_fn}
{cleanup}
"""
    # The ls stub lists exactly the file being cleaned up, so the real match logic finds it.
    harness = harness.replace('filename=$(basename "$relpath")', 'filename=$(basename "$relpath"); FNAME="$filename"')
    proc = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    read = lambda p: p.read_text(encoding="utf-8") if p.exists() else ""  # noqa: E731
    return read(manifest), read(log), read(rm_calls)


def test_missing_preserved_capture_is_kept_on_drive_and_in_manifest(tmp_path):
    rel = "docs/command-center-pages/009-trade-portfolio-tax.md"
    manifest, log, rm_calls = _run_cleanup(tmp_path, [f"{rel}|abc"], local_files=[])
    assert rm_calls == "", "a preserved capture must never be removed from Drive"
    assert f"{rel}|abc" in manifest
    assert "no longer exists locally" not in log
    assert "kept 1 preserved capture" in log


def test_missing_ordinary_doc_is_still_cleaned_up(tmp_path):
    rel = "docs/SOME_RETIRED_DOC.md"
    manifest, log, rm_calls = _run_cleanup(tmp_path, [f"{rel}|abc"], local_files=[])
    assert rm_calls.strip() == "ID1"
    assert rel not in manifest
    assert f"CLEANUP: {rel} no longer exists locally" in log


def test_present_preserved_capture_is_untouched(tmp_path):
    rel = "docs/command-center-pages/001-trade-home-default.png"
    manifest, log, rm_calls = _run_cleanup(tmp_path, [f"{rel}|abc"], local_files=[rel])
    assert rm_calls == ""
    assert f"{rel}|abc" in manifest
    assert "preserved" not in log
