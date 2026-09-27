"""One execution root links and the migration report. No SQL is applied."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.report_docs_inventory import declared_archive_status  # noqa: E402
from scripts.report_schema_migrations import pending  # noqa: E402


def test_pending_migrations_are_filenames_not_yet_applied():
    files = ["migrations/001_a.sql", "migrations/002_b.sql"]
    assert pending(files, {"001_a.sql"}) == ["migrations/002_b.sql"]
    assert pending(files, set()) == sorted(files)


def test_v3_0_header_is_superseded():
    path = ROOT / "docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_0.md"
    assert declared_archive_status(path) == "SUPERSEDED"
    current = ROOT / "docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md"
    assert declared_archive_status(current) is None
