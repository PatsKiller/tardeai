"""ask-alerts: the registry reads the lane's LaneRunReceipt, not the alert store's mtime.

Jobs coverage audit (2026-11-03): `ask-alerts` (cron `*/30 8-18 * * 1-5`, `scripts/ask_alerts.py --check`) declared
`output_signal` as `file_mtime` on `data/runtime/ask_alerts.json` — the alert STORE, which `check_alerts()` saves
unconditionally, so a failed evaluation advanced the mtime and looked fresh. The script has written a
`LaneRunReceipt` since shard 03 (success writes `ok`/`ok_at`, a failure writes `failed` with the previous `ok_at`
preserved, `--dry-run` writes nothing); the only defect was the registry pointing at the store instead of the receipt.

Hermetic: the module is loaded from source into its own module object, its `STORE` and the state root are redirected to
``tmp_path``, and `check_alerts` is stubbed. No DB, Telegram, provider, lock or live state.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    """Load scripts/ask_alerts.py into its own module object (its import-time sys.path insert is contained)."""
    path = ROOT / "scripts" / "ask_alerts.py"
    mod = types.ModuleType("ask_alerts_under_test")
    mod.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), mod.__file__, "exec"), mod.__dict__)
    return mod


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "ps"))
    mod = _load()
    mod.STORE = tmp_path / "store" / "ask_alerts.json"
    return mod


def _receipt(tmp_path: Path) -> Path:
    return tmp_path / "state" / "data" / "runtime" / "ask-alerts_last.json"


def test_a_completed_check_writes_ok_and_advances_ok_at(tmp_path, lane, capsys):
    lane.check_alerts = lambda: []
    assert lane.main(["--check"]) == 0
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["lane_id"] == "ask-alerts" and doc["status"] == "ok" and doc["exit"] == 0
    assert doc["ok_at"] and doc["ok_at"] == doc["finished_at"], doc
    assert doc["summary"] == {"checked": True, "fired": 0, "listed": 0}, doc
    assert "fired" in capsys.readouterr().out


def test_a_failed_evaluation_is_failed_and_never_advances_ok_at(tmp_path, lane):
    """Revert the except-path write -> a failed run reads as the previous success (or never ran)."""
    receipt = _receipt(tmp_path)
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {"lane_id": "ask-alerts", "status": "ok", "ok_at": "2026-11-01T00:00:00+00:00", "consecutive_failures": 0}
        )
    )

    def boom():
        raise RuntimeError("fixture evaluation failure")

    lane.check_alerts = boom
    with pytest.raises(RuntimeError):
        lane.main(["--check"])
    doc = json.loads(receipt.read_text())
    assert doc["status"] == "failed" and doc["exit"] == 1, doc
    assert doc["error"] == "RuntimeError", doc
    assert doc["ok_at"] == "2026-11-01T00:00:00+00:00", "a failed run must not advance ok_at"
    assert doc["consecutive_failures"] == 1, doc


def test_ran_and_found_nothing_is_a_success_not_a_failure(tmp_path, lane):
    lane.STORE.parent.mkdir(parents=True)
    lane.STORE.write_text(
        json.dumps(
            {"alerts": [{"id": "a1", "status": "active", "kind": "ipo", "company": "ACME", "last_checked": None}]}
        )
    )
    lane.check_alerts = lambda: []
    assert lane.main(["--check"]) == 0
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "ok" and doc["summary"]["fired"] == 0, doc


def test_dry_run_writes_nothing_and_evaluates_nothing(tmp_path, lane, capsys):
    """A dry run cannot reach the write (AGENTS.md section 6) and must not call the evaluator."""

    def must_not_be_called():
        raise AssertionError("dry run evaluated alerts")

    lane.check_alerts = must_not_be_called
    assert lane.main(["--check", "--dry-run"]) == 0
    assert capsys.readouterr().out.startswith("DRY-RUN ask-alerts: would")
    assert not _receipt(tmp_path).exists()
    with pytest.raises(SystemExit) as exc:
        lane.main(["--made-up-flag"])
    assert exc.value.code == 2
    assert not _receipt(tmp_path).exists()


def test_the_registry_signal_is_the_receipt_json_key(tmp_path):
    """Revert the registry row -> the lane reads the alert store's mtime again and a failed run looks fresh."""
    cfg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    row = next(r for r in (cfg.get("lanes") or []) if r.get("lane_id") == "ask-alerts")
    signal = row["output_signal"]
    assert signal == {"kind": "json_key", "path": "data/runtime/ask-alerts_last.json", "key": "ok_at"}, signal
    assert signal["kind"] != "file_mtime" and signal["path"] != "data/runtime/ask_alerts.json"

    from lib import lane_last_receipt as lr  # noqa: E402

    resolved = lr.receipt_path("ask-alerts", root=tmp_path)
    assert resolved.name == Path(signal["path"]).name
    assert resolved.parent == tmp_path / "data" / "runtime"


# ---------------------------------------------------------------- evaluation honesty (same audit, same lane)
def _store_with(lane, tmp_path, kind="ipo_watch", **extra):
    lane.STORE.parent.mkdir(parents=True, exist_ok=True)
    alert = {
        "id": "a1",
        "question": "when does ACME list?",
        "kind": kind,
        "companies": ["ACME"],
        "symbols": ["ACME"],
        "target_price": None,
        "created_at": "2026-11-01T00:00:00+00:00",
        "status": "active",
        "triggered_at": None,
        **extra,
    }
    lane.STORE.write_text(json.dumps({"alerts": [alert]}))
    return alert


def test_a_failed_news_query_is_a_failed_run_not_no_news(tmp_path, lane, monkeypatch):
    """Revert `_news_hits` to return [] on error -> a database outage reads as a green, quiet run.

    The real `_news_hits` is exercised: only its DB seam (`alert_event_writer._get_conn`) fails.
    """
    _store_with(lane, tmp_path)
    events = types.ModuleType("alert_event_writer")

    def down():
        raise RuntimeError("connection refused")

    events._get_conn = down
    monkeypatch.setitem(sys.modules, "alert_event_writer", events)
    with pytest.raises(lane._EvalError):
        lane.main(["--check"])
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "failed" and doc["error"] == "_EvalError", doc
    stored = json.loads(lane.STORE.read_text())["alerts"][0]
    assert stored["status"] == "active", "a failed evaluation must not mark the alert triggered"


def test_an_alert_whose_event_was_not_saved_stays_active_and_fails_the_run(tmp_path, lane, monkeypatch):
    """Revert `_fire` -> save_alert_event returning None is ignored, the alert is marked triggered and lost, run green."""
    _store_with(lane, tmp_path)
    lane._news_hits = lambda name, kw: [{"title": "ACME files to go public", "url": "https://x", "at": "now"}]
    events = types.ModuleType("alert_event_writer")
    events._get_conn = lambda: None
    events.save_alert_event = lambda **_k: None  # its real failure shape: swallows the DB error and returns None
    monkeypatch.setitem(sys.modules, "alert_event_writer", events)
    with pytest.raises(lane._EvalError):
        lane.main(["--check"])
    assert json.loads(_receipt(tmp_path).read_text())["status"] == "failed"
    assert json.loads(lane.STORE.read_text())["alerts"][0]["status"] == "active"


def test_a_corrupt_store_fails_the_run_and_is_never_overwritten(tmp_path, lane):
    lane.STORE.parent.mkdir(parents=True, exist_ok=True)
    lane.STORE.write_text("{not json")
    with pytest.raises(lane._EvalError):
        lane.main(["--check"])
    assert lane.STORE.read_text() == "{not json", "an unreadable store must not be replaced by an empty one"
    assert json.loads(_receipt(tmp_path).read_text())["status"] == "failed"


def test_a_confirmed_hit_is_enqueued_and_the_alert_is_triggered(tmp_path, lane, monkeypatch):
    _store_with(lane, tmp_path)
    lane._news_hits = lambda name, kw: [{"title": "ACME files to go public", "url": "https://x", "at": "now"}]
    saved = []

    def save(**kwargs):
        saved.append(kwargs)
        return "evt-1"

    events = types.ModuleType("alert_event_writer")
    events.save_alert_event = save
    monkeypatch.setitem(sys.modules, "alert_event_writer", events)
    assert lane.main(["--check"]) == 0
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "ok" and doc["summary"]["fired"] == 1, doc
    assert len(saved) == 1 and saved[0]["parsed_payload"]["alert_id"] == "a1"
    assert json.loads(lane.STORE.read_text())["alerts"][0]["status"] == "triggered"
