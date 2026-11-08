"""ANCHOR: CI_GATE_REGISTRY_LOADS_20261107 — the gate registry loads or the line has no CI.

LQ-20261107-426. On 2026-11-07 the serving line carried 1,136 gate files and 27 of them were
malformed: 14 had a `name` that did not equal the file stem (case included) and 13 had `comment`
as a bare string instead of a list of strings. `scripts/lib/ci_gates.load_records()` fails closed
on the first bad file, so it raised before returning any gate — `check_test_coverage.py` (run by
two CI workflows) could not load the registry at all and died before auditing a single test.
Every file was individually *nearly* valid, and nothing on the line ever loaded the registry, so
nothing noticed.

These tests load the registry the way CI does, and name the offending file when one is bad,
instead of failing with one anonymous `GateRegistryError` for 1,136 files.

Hermetic: reads the committed config/ci_gates/*.json read-only. No DB, no network, no git.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import ci_gates  # noqa: E402

ANCHOR = "CI_GATE_REGISTRY_LOADS_20261107"


def _gate_files() -> list[Path]:
    return sorted(ci_gates.gates_dir(ROOT).glob("*.json"))


def test_registry_is_not_empty_and_this_test_runs():
    files = _gate_files()
    assert len(files) > 500, f"only {len(files)} gate files: this is not the registry"
    assert "tests/test_ci_gate_registry_loads_20261107.py" in ci_gates.registry_text(ROOT)


def test_every_gate_file_is_valid_and_the_failure_names_the_file():
    """One bad file must not hide behind a single exception: report every bad file, named.

    The two rules that broke on 2026-11-07 are checked explicitly, because they are the two an
    author can get wrong while the file still looks right in an editor.
    """
    bad: list[str] = []
    for p in _gate_files():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            bad.append(f"{p.name}: unreadable ({exc})")
            continue
        if isinstance(doc, dict) and doc.get("name") != p.stem:
            bad.append(f"{p.name}: name {doc.get('name')!r} != file stem {p.stem!r}")
        if isinstance(doc, dict) and isinstance(doc.get("comment"), str):
            bad.append(f'{p.name}: comment is a bare string; wrap it in a list: ["{doc["comment"][:40]}..."]')
        try:
            ci_gates.validate(doc, stem=p.stem)
        except ci_gates.GateRegistryError as exc:
            bad.append(str(exc))
    assert not bad, "malformed gate files (load_records raises on the first):\n  " + "\n  ".join(bad)


def test_load_records_returns_one_record_per_file():
    """The exact call CI makes: a raise here means no gate runs at all."""
    records = ci_gates.load_records(ROOT)
    files = _gate_files()
    assert len(records) == len(files), f"{len(records)} records for {len(files)} files"
    names = [r["name"] for r in records]
    assert names == sorted(names) and len(names) == len(set(names))
    assert set(names) == {p.stem for p in files}


def test_no_gate_names_a_test_file_that_is_not_on_disk():
    records = ci_gates.load_records(ROOT)
    empty = [r["name"] for r in records if not r["files"]]
    missing = sorted({f for r in records for f in r["files"] if not (ROOT / f).is_file()})
    assert not empty, f"gates with no files: {empty}"
    assert not missing, f"gate files no longer on disk: {missing}"
