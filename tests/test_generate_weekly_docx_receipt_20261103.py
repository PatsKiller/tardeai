"""generate-weekly-docx writes a durable lane receipt, not a directory mtime.

Jobs coverage audit (2026-11-03): the lane's registry ``output_signal`` was the reports DIRECTORY
(``data/portfolios/reports/analyst``). A directory mtime is advanced by any file landing in it, and a
rerun of the same dated report never refreshes it, so it could not prove that THIS run completed — the
lane sat between "Measured" and "Unmeasured" with no honest answer. The lane now writes the standard
``LaneRunReceipt`` at ``<state root>/data/runtime/generate-weekly-docx_last.json`` and the registry
reads ``ok_at`` from it.

Hermetic: the report builder and the exporter are stubbed in ``sys.modules``; ``PROJECT_ROOT`` and the
reports root are redirected to ``tmp_path``; the state root is a temp dir. No database, no Telegram, no
file outside the temp tree.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Load the producer by file path under a dedicated module name, registering it before exec_module
# (AGENTS.md §7, L7-05). An ordinary ``import generate_weekly_docx`` reuses whatever a previous test
# left in ``sys.modules``, so this suite could then exercise a cached stub instead of the producer.
_SPEC = importlib.util.spec_from_file_location(
    "_receipt_test_generate_weekly_docx", ROOT / "scripts" / "generate_weekly_docx.py"
)
gw = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gw
_SPEC.loader.exec_module(gw)


def _stub_modules(monkeypatch, *, build=None, export=None):
    builder = types.ModuleType("analyst_report_builder")
    builder.build_weekly_review = build or (lambda: {"report": "weekly"})
    saved: list[str] = []

    def save_report_json(report, stem):
        saved.append(stem)
        return stem

    builder.save_report_json = save_report_json
    exporter = types.ModuleType("report_export")

    def default_export(report, fmt, output_stem):
        return {
            "ok": True,
            "filename": f"{output_stem}.{fmt}",
            "path": f"/nonexistent/{output_stem}.{fmt}",
            "size_kb": 1,
        }

    exporter.export_report = export or default_export
    monkeypatch.setitem(sys.modules, "analyst_report_builder", builder)
    monkeypatch.setitem(sys.modules, "report_export", exporter)
    return saved


def _run(monkeypatch, tmp_path, argv):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(gw, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(gw, "_portfolio_reports_root", lambda: tmp_path / "reports")
    monkeypatch.setattr(sys, "argv", ["generate_weekly_docx.py", *argv])
    gw.main()
    return tmp_path / "state" / "data/runtime/generate-weekly-docx_last.json"


def test_a_real_run_writes_the_lane_receipt_with_ok_at(tmp_path, monkeypatch):
    """Revert the receipt write -> no file, and the registry's json_key signal stays silent forever."""
    _stub_modules(monkeypatch)
    receipt = _run(monkeypatch, tmp_path, [])
    assert receipt.is_file(), "the lane receipt was not written"
    doc = json.loads(receipt.read_text())
    assert doc["lane_id"] == "generate-weekly-docx"
    assert doc["status"] == "ok" and doc["ok_at"], doc
    assert doc["schema"] == "LaneRunReceipt@v2", doc["schema"]
    assert doc["produced_count"] == 2 and doc["attempted_count"] == 2, doc  # dated JSON + docx export


def test_a_failed_export_fails_the_run_and_records_the_skip(tmp_path, monkeypatch):
    """Revert the ok rule to produced>0 -> a week with no report artifact still reads LIVE (cc2 BLOCK)."""
    _stub_modules(monkeypatch, export=lambda report, fmt, output_stem: {"ok": False, "error": "pdf backend missing"})
    receipt = _run(monkeypatch, tmp_path, ["--format", "pdf"])
    doc = json.loads(receipt.read_text())
    assert doc["status"] == "failed", "the requested export was not produced"
    assert doc["produced_count"] == 1 and doc["attempted_count"] == 2, doc
    assert doc["skipped_reasons"].get("pdf_export_failed") == 1, doc


def test_a_run_whose_exports_all_fail_is_not_ok(tmp_path, monkeypatch):
    """--format all with both exports failing produced no report artifact; ok_at must not advance."""
    _stub_modules(monkeypatch, export=lambda report, fmt, output_stem: {"ok": False, "error": "backend missing"})
    receipt = _run(monkeypatch, tmp_path, ["--format", "all"])
    doc = json.loads(receipt.read_text())
    assert doc["status"] == "failed", doc
    assert doc["ok_at"] is None, doc
    assert doc["produced_count"] == 1 and doc["attempted_count"] == 3, doc
    assert doc["skipped_reasons"] == {"docx_export_failed": 1, "pdf_export_failed": 1}, doc


def test_partial_counts_survive_an_export_exception(tmp_path, monkeypatch):
    """An exception mid-run must not collapse the counters to 0/0 (cc2's non-blocking finding)."""
    def boom(report, fmt, output_stem):
        raise RuntimeError("exporter exploded")

    _stub_modules(monkeypatch, export=boom)
    with pytest.raises(RuntimeError):
        _run(monkeypatch, tmp_path, ["--format", "all"])
    doc = json.loads((tmp_path / "state/data/runtime/generate-weekly-docx_last.json").read_text())
    assert doc["status"] == "failed" and doc["error"] == "RuntimeError", doc
    assert doc["produced_count"] == 1 and doc["attempted_count"] == 2, doc


def test_a_failed_run_writes_a_failed_receipt_and_keeps_the_error(tmp_path, monkeypatch):
    """Revert the except-path receipt -> a failing lane looks like it never ran instead of going stale."""

    def boom():
        raise RuntimeError("builder exploded")

    _stub_modules(monkeypatch, build=boom)
    with pytest.raises(RuntimeError):
        _run(monkeypatch, tmp_path, [])
    receipt = tmp_path / "state" / "data/runtime/generate-weekly-docx_last.json"
    doc = json.loads(receipt.read_text())
    assert doc["status"] == "failed" and doc["exit"] != 0, doc
    assert "builder exploded" not in json.dumps(doc), "the receipt must not carry exception text"
    assert "RuntimeError" in json.dumps(doc), doc


def test_a_dry_run_writes_no_receipt(tmp_path, monkeypatch):
    """A dry run cannot reach the write (AGENTS.md section 6)."""
    _stub_modules(monkeypatch)
    _run(monkeypatch, tmp_path, ["--dry-run"])
    assert not (tmp_path / "state" / "data/runtime/generate-weekly-docx_last.json").exists()
