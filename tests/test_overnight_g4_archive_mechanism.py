"""WAVE G4 — archive mechanism tripwire (AGENTS.md §0.6).

Invariants:
  * ARCHIVE_MANIFEST schema requires verdict, evidence, date, review_by,
    restore_command (and path)
  * empty manifest / empty archive/ → tripwire quiet (archive nothing)
  * live import OR read of an archived path → ArchivedPathAccessFinding
  * mechanism ships; first archive batch is operator-only

This file is on the hardening CI allowlist. READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import cio_archive_mechanism as mech  # noqa: E402


REQUIRED = ("path", "verdict", "evidence", "date", "review_by", "restore_command")


def test_g4_schema_declares_required_manifest_fields():
    doc = mech.schema_document()
    assert doc["schema"] == "ArchiveManifest@v1"
    for key in REQUIRED:
        assert key in doc["required_item_fields"]
    assert "DARK" in doc["allowed_verdicts"]
    assert "ONE_SHOT" in doc["allowed_verdicts"]
    assert "SUPERSEDED" in doc["allowed_verdicts"]
    assert "ORPHANED" in doc["allowed_verdicts"]


def test_g4_committed_manifest_is_valid_and_every_archived_file_has_a_row():
    """WAVE G4 built the mechanism and archived nothing; the first batch was
    operator-only. That batch landed 2026-09-13 (One Source of Truth, Phase 2,
    operator-approved): polygon_source.py, retired with a manifest row. The
    invariant now is not "empty" but "every file under archive/ is declared,
    every row validates, and nothing live reads any of it".
    """
    data = mech.load_manifest(ROOT / "archive" / "ARCHIVE_MANIFEST.json")
    assert data["schema"] == "ArchiveManifest@v1"
    assert mech.validate_manifest(data) == []
    on_disk = set(mech.archived_paths_on_disk(ROOT / "archive"))
    declared = set(mech.archived_paths_from_manifest(data))
    assert on_disk == declared, f"undeclared or missing archived files: {on_disk ^ declared}"
    assert "archive/retired_providers_20260913/discovery_sources/polygon_source.py" in declared
    assert set(mech.effective_archived_paths(data, root=ROOT)) == declared


def test_g4_tripwire_quiet_when_nothing_archived():
    hits = mech.scan_archived_path_references(root=ROOT)
    assert hits == []
    mech.assert_no_archived_reads(root=ROOT)  # must not raise


def test_g4_validate_rejects_incomplete_item():
    bad = {
        "schema": "ArchiveManifest@v1",
        "items": [
            {
                "path": "archive/census/demo.py",
                "verdict": "ONE_SHOT",
                # missing evidence/date/review_by/restore_command
            }
        ],
    }
    errors = mech.validate_manifest(bad)
    assert errors
    joined = " ".join(errors)
    assert "evidence" in joined
    assert "date" in joined
    assert "review_by" in joined
    assert "restore_command" in joined


def test_g4_validate_accepts_complete_item_and_restore_helper():
    day = "2026-08-31"
    item = {
        "path": "archive/census-2026-08-30/one_shot/scripts/run_paper_canary_chain.py",
        "original_path": "scripts/run_paper_canary_chain.py",
        "verdict": "ONE_SHOT",
        "evidence": "date-guarded cron; never fires again [census part4]",
        "date": day,
        "review_by": mech.default_review_by(day),
        "restore_command": mech.make_restore_command(
            "archive/census-2026-08-30/one_shot/scripts/run_paper_canary_chain.py",
            "scripts/run_paper_canary_chain.py",
        ),
    }
    assert item["review_by"] == "2026-09-30"
    assert item["restore_command"].startswith("git mv ")
    assert mech.validate_manifest({"schema": "ArchiveManifest@v1", "items": [item]}) == []


def test_g4_tripwire_raises_on_import_of_archived_path(tmp_path: Path):
    """Live `import` of an archived module must raise ArchivedPathAccessFinding."""
    archived = "archive/census_demo/one_shot/legacy_mod.py"
    (tmp_path / "archive" / "census_demo" / "one_shot").mkdir(parents=True)
    (tmp_path / "archive" / "census_demo" / "one_shot" / "legacy_mod.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (tmp_path / "archive" / "ARCHIVE_MANIFEST.json").write_text(
        json.dumps(
            {
                "schema": "ArchiveManifest@v1",
                "items": [
                    {
                        "path": archived,
                        "verdict": "ONE_SHOT",
                        "evidence": "synthetic tripwire fixture",
                        "date": "2026-08-31",
                        "review_by": "2026-09-30",
                        "restore_command": mech.make_restore_command(
                            archived, "scripts/legacy_mod.py"
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    live = tmp_path / "scripts"
    live.mkdir()
    (live / "consumer.py").write_text(
        "from archive.census_demo.one_shot import legacy_mod  # noqa\n",
        encoding="utf-8",
    )

    with pytest.raises(mech.ArchivedPathAccessFinding) as ei:
        mech.assert_no_archived_reads(root=tmp_path, archived=[archived])
    finding = ei.value
    assert finding.findings
    assert any(h.kind == "import" for h in finding.findings)
    assert any(h.consumer == "scripts/consumer.py" for h in finding.findings)
    assert any(h.archived_path == archived for h in finding.findings)


def test_g4_tripwire_raises_on_read_of_archived_path(tmp_path: Path):
    archived = "archive/batch_a/superseded_page.tsx"
    (tmp_path / "archive" / "batch_a").mkdir(parents=True)
    (tmp_path / "archive" / "batch_a" / "superseded_page.tsx").write_text(
        "export default function Gone(){return null}\n", encoding="utf-8"
    )
    app = tmp_path / "apps" / "command-center-v3" / "src"
    app.mkdir(parents=True)
    (app / "AccidentalRead.ts").write_text(
        "import fs from 'fs';\n"
        f"const body = fs.readFileSync('{archived}', 'utf8');\n",
        encoding="utf-8",
    )

    with pytest.raises(mech.ArchivedPathAccessFinding) as ei:
        mech.assert_no_archived_reads(root=tmp_path, archived=[archived])
    hits = ei.value.findings
    assert any(h.archived_path == archived for h in hits)
    assert any(h.kind in {"read", "path_literal"} for h in hits)


def test_g4_report_is_quiet_with_the_first_operator_approved_batch():
    report = mech.build_report(root=ROOT)
    assert report["item_count"] == 1
    assert report["trip_count"] == 0
    assert report["archived_nothing"] is False
    assert report["validation_errors"] == []


def test_g4_ci_allowlist_names_this_suite():
    text = (ROOT / "scripts" / "run_cio_hardening_ci.py").read_text(encoding="utf-8")
    assert "tests/test_overnight_g4_archive_mechanism.py" in text
