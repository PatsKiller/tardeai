"""The rest of the 2026-09-26 audit that does not delete routes or tables."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.route_access_count import flush, note  # noqa: E402
from scripts.report_docs_inventory import declared_archive_status  # noqa: E402
from scripts.rotate_append_only_store import apply, plan  # noqa: E402


def test_route_count_strips_the_query_and_does_not_raise(tmp_path):
    store: dict[str, int] = {}
    note("GET", "/api/v2/options/proposals?token=secret", store=store)
    note("GET", "/api/v2/options/proposals?x=1", store=store)
    assert store == {"GET /api/v2/options/proposals": 2}
    dest = tmp_path / "counts.json"
    flush(store, dest)
    body = json.loads(dest.read_text(encoding="utf-8"))
    assert body["schema"] == "RouteAccessCounts@v1"
    assert body["counts"]["GET /api/v2/options/proposals"] == 2
    assert "secret" not in dest.read_text(encoding="utf-8")


def test_rotate_keeps_the_tail_and_refuses_other_names(tmp_path):
    src = tmp_path / "cio_wake_jobs.jsonl"
    lines = [f'{{"n":{i}}}\n' for i in range(20)]
    src.write_text("".join(lines), encoding="utf-8")
    refused = plan(tmp_path / "positions.jsonl")
    assert refused["ok"] is False
    out = apply(src, tmp_path / "archive", keep_bytes=40)
    assert out["action"] == "archive_head"
    tail = src.read_text(encoding="utf-8")
    assert tail.startswith("{")
    archived = Path(out["archived_to"]).read_text(encoding="utf-8")
    assert archived + tail == "".join(lines)


def test_superseded_header_is_archived(tmp_path):
    doc = tmp_path / "old.md"
    doc.write_text("# Old\n\nStatus: SUPERSEDED BY newer.md\n", encoding="utf-8")
    assert declared_archive_status(doc) == "SUPERSEDED"
    active = tmp_path / "live.md"
    active.write_text("Status: ACTIVE\n", encoding="utf-8")
    assert declared_archive_status(active) is None


def test_update_docx_stub_is_the_tripwire():
    stub = ROOT / "scripts" / "update_docx_data_accuracy_20260616.py"
    text = stub.read_text(encoding="utf-8")
    assert "scripts/archive/update_docx_202606/" in text
    assert (ROOT / "scripts/archive/update_docx_202606" / stub.name).is_file()
