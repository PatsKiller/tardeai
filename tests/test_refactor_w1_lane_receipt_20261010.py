"""Refactor wave 1 (cron -> n8n, 2026-10-10): scripts/lib/lane_last_receipt.py.

The per-script receipt every W3 script writes on a REAL run: <state_root>/data/runtime/<name>_last.json,
LaneRunReceipt@v1, ok_at only on success (a failed run keeps the previous ok_at so a json_key signal on
ok_at goes stale instead of lying). Hermetic: TRADEAI_STATE_ROOT is a tmp dir.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import lane_last_receipt as llr  # noqa: E402


def test_receipt_path_resolves_under_state_root_data_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert llr.receipt_path("x") == tmp_path / "data" / "runtime" / "x_last.json"


def test_receipt_path_never_resolves_into_a_release_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path / "trade-ai-releases" / "portfolio-server" / "abc-release"))
    p = llr.receipt_path("x")
    assert "portfolio-server" not in str(p), p


def test_ok_run_sets_ok_at_and_failed_run_keeps_previous_ok_at(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    p = llr.write_receipt("lane", ok=True, summary={"n": 3}, started_at="s")
    first = json.loads(p.read_text())
    assert first["schema"] == "LaneRunReceipt@v1" and first["status"] == "ok"
    assert first["ok_at"] == first["finished_at"] and first["summary"] == {"n": 3}

    llr.write_receipt("lane", ok=False, error="boom " * 200)
    second = json.loads(p.read_text())
    assert second["status"] == "failed"
    assert second["ok_at"] == first["ok_at"], "a failure must not advance ok_at"
    assert len(second["error"]) <= 300


def test_first_ever_failure_has_null_ok_at(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    doc = json.loads(llr.write_receipt("lane", ok=False).read_text())
    assert doc["ok_at"] is None and doc["status"] == "failed"


def test_enforce_readonly_rolls_back_then_sets_readonly():
    calls = []

    class Conn:
        def rollback(self):
            calls.append("rollback")

        def set_session(self, **kw):
            calls.append(("set_session", kw))

    llr.enforce_readonly(Conn())
    assert calls == ["rollback", ("set_session", {"readonly": True})]


def test_enforce_readonly_is_a_noop_on_a_double_without_set_session():
    class Conn:
        def rollback(self):
            raise AssertionError("must not be called")

    llr.enforce_readonly(Conn())


# ── wave-1 integration: one helper serves the W1, W2, W3 and W4 call shapes ──────────────────


def test_w1_call_shape_records_script_exit_and_started_at(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    p = llr.write_lane_receipt("w1-lane", ok=True, started_at="s", script="x.py", exit_code=0, summary={"n": 1})
    doc = json.loads(p.read_text())
    assert doc["lane_id"] == "w1-lane" and doc["script"] == "x.py" and doc["exit"] == 0
    assert doc["started_at"] == "s" and doc["ok_at"] == doc["finished_at"]


def test_w2_call_shape_explicit_path_and_root_keyword(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    assert llr.receipt_path("w2", root=tmp_path) == tmp_path / "data" / "runtime" / "w2_last.json"
    target = tmp_path / "custom" / "prepare_last.json"
    assert llr.write_lane_receipt("w2", ok=False, exit_code=3, path=target) == target
    doc = json.loads(target.read_text())
    assert doc["status"] == "failed" and doc["exit"] == 3 and doc["ok_at"] is None


def test_w4_call_shape_datetime_started_at_and_durable_dir_resolver(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    persistent = tmp_path / "persistent"
    (persistent / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(persistent))
    started = datetime(2026, 10, 10, tzinfo=timezone.utc)
    p = llr.write_lane_receipt("w4-lane", ok=True, exit_code=0, started_at=started)
    assert p == persistent / "data" / "runtime" / "w4-lane_last.json"
    assert json.loads(p.read_text())["started_at"] == started.isoformat()


def test_never_raises_into_the_caller(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    blocker = tmp_path / "a_file"
    blocker.write_text("x")
    assert llr.write_lane_receipt("x", ok=True, exit_code=0, path=blocker / "sub" / "r.json") is None
    assert llr.write_receipt("bad/lane", ok=True) is None  # path-like id: refused, not raised


def test_exception_text_is_reduced_to_the_type_name(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    secret = "password=hunter2 host=db"
    p = llr.write_lane_receipt(
        "lane",
        ok=False,
        exit_code=1,
        error=f"OperationalError: {secret}",
        summary={"error": f"ConnectionError: {secret}", "chain_error": f"KeyError: {secret}", "n": 2},
    )
    text = p.read_text()
    doc = json.loads(text)
    assert secret not in text
    assert doc["error"] == "OperationalError"
    assert doc["summary"] == {"error": "ConnectionError", "chain_error": "KeyError", "n": 2}


def test_dry_run_report_prints_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    rep = llr.dry_run_report("lane", {"would": 3}, would_write=["t"])
    assert rep["dry_run"] is True and rep["would_write_receipt"].endswith("data/runtime/lane_last.json")
    assert capsys.readouterr().out.startswith("DRY-RUN ")
    assert not (tmp_path / "data").exists()


def test_one_receipt_module_only():
    assert not (ROOT / "scripts" / "lib" / "lane_ok_receipt.py").exists()
