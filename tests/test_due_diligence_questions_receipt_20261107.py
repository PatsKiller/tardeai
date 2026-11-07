"""due-diligence-questions: the R1 gate needs a lane receipt, and a dry run must never write one.

LQ-20261107-27 (n8n overnight onboarding, 2026-11-07). `due-diligence-questions` is an `llm` lane, so
`lane_dispatch.r1_class_admission` admits it only when the allowlist/registry `output_signal` IS the lane's own
`LaneRunReceipt` — `{"kind": "json_key", "key": "ok_at", "path": "data/runtime/due-diligence-questions_last.json"}`.
Before this change the only signal was the cron twin's `>> logs/due_diligence_questions.log` redirect, which proves
cron opened a file and nothing else (AGENTS.md §9.3, §0 rail 8), so the lane could not be admitted.

What is pinned here:

* the ``--dry-run`` branch (offline, "no lock, DB, schema, researcher, model or writes") writes NO receipt;
* a real ``--apply`` run writes ``data/runtime/due-diligence-questions_last.json`` with ``ok``/``ok_at``/
  ``produced_count`` and a status no monitor can misread;
* the id the script writes under is the registry lane id and the path the allowlist declares, so the three
  files cannot drift apart silently.

Hermetic: the module is executed from source into its own module object, the state root is redirected to
``tmp_path``, and the DB, DDL guard, curation and router are stubs. No DB, provider, lock or live state.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load() -> types.ModuleType:
    path = ROOT / "scripts" / "due_diligence_questions.py"
    mod = types.ModuleType("ddq_under_test")
    mod.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), mod.__file__, "exec"), mod.__dict__)
    return mod


def _receipt(tmp_path: Path) -> Path:
    return tmp_path / "state" / "data" / "runtime" / "due-diligence-questions_last.json"


class _Cur:
    rowcount = 0

    def execute(self, *a, **k):
        return None

    def fetchone(self):
        return (1,)

    def fetchall(self):
        return []

    def set_session(self, **k):
        return None


class _Conn:
    def cursor(self, *a, **k):
        return _Cur()

    def commit(self):
        return None

    def close(self):
        return None


def _stub_ddl_guard(monkeypatch):
    stub = types.ModuleType("scripts.lib.ddl_guard")
    stub.apply_ddl = lambda cur, ddl: None
    monkeypatch.setitem(sys.modules, "scripts.lib.ddl_guard", stub)


def test_a_dry_run_writes_no_receipt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))
    mod = _load()
    assert mod.main(["--dry-run"]) == 0
    assert "no lock, DB, schema, researcher, model or writes" in capsys.readouterr().out
    assert not _receipt(tmp_path).exists(), "a dry run reached the write"
    assert not (tmp_path / "state" / "data" / "runtime").exists()


def test_a_real_apply_run_with_nothing_due_writes_an_ok_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))
    _stub_ddl_guard(monkeypatch)
    mod = _load()
    mod._db = _Conn
    mod.cap_env_warning = lambda: None
    mod.reconcile_answers = lambda cur, apply=True: {}
    mod.pending_changes = lambda cur, limit: []
    mod.MAX_ROUTED = 0

    assert mod.main(["--apply"]) == 0

    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["lane_id"] == "due-diligence-questions", doc
    assert doc["status"] == "ok" and doc["exit"] == 0, doc
    assert doc["ok_at"] and doc["ok_at"] == doc["finished_at"], doc
    assert doc["produced_count"] == 0, doc
    assert doc["empty_reason"] == "nothing_due", doc


def test_the_lane_id_matches_the_registry_and_the_allowlist_signal(tmp_path, monkeypatch):
    mod = _load()
    from lib.lane_last_receipt import receipt_path

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    assert str(receipt_path(mod.LANE_ID)).endswith(
        "/data/runtime/due-diligence-questions_last.json")

    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    row = next(r for r in reg["lanes"] if r.get("lane_id") == mod.LANE_ID)
    signal = row["output_signal"]
    if signal.get("kind") != "json_key":
        # Pre-onboarding row: the lane still declares the cron twin's log redirect. The onboarding bundle's
        # registry change repoints it at the receipt; this test pins the contract for that state.
        pytest.skip(f"registry still on the legacy signal {signal.get('kind')!r} (lane not yet onboarded)")
    assert signal["key"] == "ok_at", signal
    assert signal["path"] == "data/runtime/due-diligence-questions_last.json", signal

    al = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())
    entry = next(e for e in al["lanes"] if e.get("lane_id") == mod.LANE_ID)
    assert entry["output_signal"] == signal["path"], entry["output_signal"]
