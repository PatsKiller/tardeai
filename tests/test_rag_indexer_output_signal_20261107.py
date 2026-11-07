"""``rag-indexer`` is graded EMPTY unless its declaration names the file the RUN writes (QUALITY ROUND 2).

The row declared ``{"kind": "file_mtime", "path": "logs/rag_indexer.log", "evidence": "CRON_LOG_REDIRECT"}``.
Only the cron arm appends to that log (its shell redirect), so a run made any other way — an n8n dispatch,
an operator, a change trigger — wrote its own ``LaneRunReceipt`` and was still graded "output was not
written by that run". The lane now declares the receipt itself:

    {"kind": "json_key", "path": "data/runtime/rag-indexer_last.json", "key": "ok_at"}

This file pins the repair in the direction that fails loudly:

* the declaration is written out per lane instead of read from the file it checks (a test that derives its
  expectation from the artifact asserts only that the file equals itself);
* the declared path is the one ``lane_last_receipt.receipt_path`` computes, so renaming the receipt in the
  producer breaks the test rather than silently un-declaring the lane;
* a REAL run, driven through ``main()`` with a fake connection, actually writes that file with ``ok_at`` —
  the declaration is not an invented signal (AGENTS.md §0 rule 8);
* a ``--dry-run`` writes nothing and opens no connection (AGENTS.md §7; offline previews since 1c733d98f);
* a revert to the cron log, or to any ``logs/`` path, is refused here.

Hermetic: a synthetic state root under ``tmp_path``, a fake DB connection, no network, no crontab, no live
persistent state.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import rag_indexer  # noqa: E402
from lib import lane_last_receipt  # noqa: E402

LANE = "rag-indexer"
DECLARED_PATH = "data/runtime/rag-indexer_last.json"
REGISTRY = ROOT / "config" / "lane_registry.json"


def _lane_row() -> dict:
    doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for row in doc.get("lanes") or []:
        if row.get("lane_id") == LANE:
            return row
    raise AssertionError(f"{LANE} has no row in config/lane_registry.json")


class _FakeConn:
    def close(self) -> None:  # pragma: no cover - main() calls it once
        pass


def _isolated_state(monkeypatch, tmp_path: Path) -> Path:
    """A state root of our own, and no executor run id (a run id would also write an attempt receipt)."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.delenv("TRADEAI_RUN_ID", raising=False)
    monkeypatch.delenv("TRADEAI_RUN_ATTEMPT", raising=False)
    monkeypatch.delenv("TRADEAI_RUN_MODE", raising=False)
    return tmp_path / DECLARED_PATH


# ── the declaration ─────────────────────────────────────────────────────────────────────────────


def test_the_row_declares_the_receipt_key_and_not_the_cron_log():
    signal = _lane_row().get("output_signal") or {}
    assert signal == {"kind": "json_key", "path": DECLARED_PATH, "key": "ok_at"}
    assert not str(signal.get("path", "")).startswith("logs/")
    assert signal.get("evidence") != "CRON_LOG_REDIRECT"


def test_the_declared_path_is_the_path_the_producer_writes(tmp_path):
    """Ties the registry row to lane_last_receipt's own naming: a rename in the library fails here."""
    produced = lane_last_receipt.receipt_path(LANE, tmp_path)
    assert produced == tmp_path / DECLARED_PATH


# ── the producer: a real run writes it, a dry run does not ─────────────────────────────────────


def test_a_real_run_writes_the_declared_receipt_with_ok_at(monkeypatch, tmp_path, capsys):
    target = _isolated_state(monkeypatch, tmp_path)
    monkeypatch.setattr(rag_indexer, "_get_conn", lambda: _FakeConn())
    monkeypatch.setattr(rag_indexer, "index_source", lambda source_type, **kwargs: (0, {}))

    assert rag_indexer.main([]) == 0

    receipt = json.loads(target.read_text(encoding="utf-8"))
    assert receipt["lane_id"] == LANE
    assert receipt["mode"] == "live"
    assert receipt["status"] == "ok"
    assert receipt["ok_at"]  # the key the registry grades on
    assert receipt["summary"]["total"] == 0
    assert "RAG_INDEXER_SUMMARY" in capsys.readouterr().out


def test_a_dry_run_writes_no_receipt_and_opens_no_connection(monkeypatch, tmp_path, capsys):
    target = _isolated_state(monkeypatch, tmp_path)

    def _refuse():  # a preview must not reach the DB at all
        raise AssertionError("--dry-run opened a database connection")

    monkeypatch.setattr(rag_indexer, "_get_conn", _refuse)

    assert rag_indexer.main(["--dry-run"]) == 0

    out = capsys.readouterr().out
    assert out.count("DRY-RUN") == 1
    assert "would index" in out
    assert not target.exists()
    assert not target.parent.exists()


def test_a_failed_connection_still_writes_a_failed_receipt(monkeypatch, tmp_path):
    """A run that cannot open the DB is a run: its receipt must carry status failed and no ok_at."""
    target = _isolated_state(monkeypatch, tmp_path)

    def _boom():
        raise OSError("no database")

    monkeypatch.setattr(rag_indexer, "_get_conn", _boom)
    try:
        rag_indexer.main([])
    except OSError:
        pass
    receipt = json.loads(target.read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    assert receipt["ok_at"] is None or "ok_at" not in receipt
