"""Refactor wave 1 (cron -> n8n, 2026-10-10): scripts/llm_retry_monitor.py (cron L440).

The default main truncated the shared llm_retry_events.jsonl (destructive retention), which kept the
lane out of config/n8n_run_allowlist.json. The trim is now its own step:
- no flag (the cron form): aggregate + trim, unchanged;
- --no-trim: aggregate only, never rewrites the event log (the dispatcher live form);
- --trim-only: the hygiene step;
- --dry-run: computes the health document and the trim count and writes nothing.
A real run writes llm_retry_monitor[_trim]_last.json (ok_at only on success).
Hermetic: tmp events/out paths, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import inspect
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import llm_retry_monitor as lrm  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402


def _events(path: Path, n: int, gave_up_recent: int = 0) -> None:
    now = datetime.now(timezone.utc)
    lines = [
        json.dumps(
            {"ts": (now - timedelta(days=30, minutes=i)).isoformat(), "outcome": "recovered", "error_type": "timeout"}
        )
        for i in range(n)
    ]
    lines += [
        json.dumps({"ts": (now - timedelta(hours=1)).isoformat(), "outcome": "gave_up", "error_type": "429"})
        for _ in range(gave_up_recent)
    ]
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    events, out = tmp_path / "llm_retry_events.jsonl", tmp_path / "llm_retry_health.json"
    monkeypatch.setattr(lrm, "EVENTS", events)
    monkeypatch.setattr(lrm, "OUT", out)
    monkeypatch.setattr(lrm, "MAX_KEEP", 10)
    return {"events": events, "out": out, "state": tmp_path / "state"}


@pytest.mark.parametrize("argv", [["--dry-run"], ["--dry-run", "--no-trim"], ["--dry-run", "--trim-only"]])
def test_dry_run_writes_nothing(env, monkeypatch, capsys, argv):
    _events(env["events"], 15)
    before = env["events"].read_bytes()

    def boom(*a, **k):
        raise AssertionError("dry run reached a write")

    monkeypatch.setattr(llr, "write_receipt", boom)
    monkeypatch.setattr(lrm, "write_trim", boom)
    assert lrm.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["rows_parsed"] == 15
    assert env["events"].read_bytes() == before and not env["out"].exists() and not env["state"].exists()
    if "--no-trim" in argv:
        assert out["would_trim"] is None
    else:
        assert out["would_trim"]["drop"] == 5 and out["would_trim"]["keep"] == 10


def test_dry_run_report_tracks_state(env, capsys):
    _events(env["events"], 3)
    lrm.main(["--dry-run"])
    first = json.loads(capsys.readouterr().out)
    _events(env["events"], 3, gave_up_recent=2)
    lrm.main(["--dry-run"])
    second = json.loads(capsys.readouterr().out)
    assert (first["status"], second["status"]) == ("HEALTHY", "DEGRADED")


def test_source_order_dry_run_returns_before_writes():
    src = inspect.getsource(lrm.main)
    cut = src.index("# returns before either write is reachable")
    assert cut < src.index("out_path.write_text(") and cut < src.index("write_trim(events, rows)")


def test_cron_form_unchanged_aggregates_and_trims(env):
    _events(env["events"], 15)
    assert lrm.main([]) == 0
    assert json.loads(env["out"].read_text())["status"] == "HEALTHY"
    assert len(env["events"].read_text().splitlines()) == 10
    doc = json.loads((env["state"] / "data/runtime/llm_retry_monitor_last.json").read_text())
    assert doc["status"] == "ok" and doc["summary"]["trimmed"] == 5


def test_no_trim_never_rewrites_the_event_log(env):
    _events(env["events"], 15)
    before = env["events"].read_bytes()
    assert lrm.main(["--no-trim"]) == 0
    assert env["events"].read_bytes() == before and env["out"].exists()
    doc = json.loads((env["state"] / "data/runtime/llm_retry_monitor_last.json").read_text())
    assert doc["summary"]["trimmed"] == 0


def test_trim_only_is_the_hygiene_step(env):
    _events(env["events"], 15)
    assert lrm.main(["--trim-only"]) == 0
    assert not env["out"].exists() and len(env["events"].read_text().splitlines()) == 10
    doc = json.loads((env["state"] / "data/runtime/llm_retry_monitor_trim_last.json").read_text())
    assert doc["status"] == "ok"


def test_no_trim_and_trim_only_are_exclusive(env):
    with pytest.raises(SystemExit):
        lrm.main(["--no-trim", "--trim-only"])


def test_failed_write_leaves_failed_receipt_and_raises(env, monkeypatch):
    _events(env["events"], 15)

    def disk_full(events, rows):
        raise OSError("No space left on device")

    monkeypatch.setattr(lrm, "write_trim", disk_full)
    with pytest.raises(OSError):
        lrm.main(["--trim-only"])
    doc = json.loads((env["state"] / "data/runtime/llm_retry_monitor_trim_last.json").read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None and doc["error"] == "OSError"  # type only, never the message


def test_paths_resolve_through_the_persistent_state_layer():
    assert 'resolve_durable_dir("data/runtime", ROOT)' in inspect.getsource(lrm._runtime_dir)
