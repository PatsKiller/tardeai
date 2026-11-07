"""ANCHOR: HERMES_NEWS_BRIDGE_WINDOW_20261107. LQ-20261107-112 — a bridge that runs but produces nothing
for its whole contract window is a FAILURE, not ``no_new_input``.

Live defect this pins: ``hermes-news-bridge`` exited 0 with ``no_new_input`` on every run from 2026-10-29 to
2026-11-07 while ``news_articles source='hermes'`` had 0 new rows (its upstream momentum_catalyst feed was
dead). The lane's own contract (``per_window`` 48 h, ``min_produced`` 1) already said so; nothing read it.

Hermetic: fake cursor, no database, no network, synthetic symbols. Lane ids and reason strings are the only
real values, because the contract's allow/deny lists are matched by name.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_news_bridge as B  # noqa: E402


class _FakeCursor:
    """Records every statement; answers the window count with a fixed value."""

    def __init__(self, window_rows: int):
        self.window_rows = window_rows
        self.sql: list[str] = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))

    def fetchone(self):
        return (self.window_rows,)


def test_window_count_reads_the_output_store_not_this_runs_zero():
    cur = _FakeCursor(0)
    assert B.hermes_rows_in_window(cur) == 0
    sql, params = cur.sql[-1]
    assert "from news_articles" in sql.lower()
    assert "source = 'hermes'" in sql
    assert params == (B.WINDOW_HOURS,)
    assert cur.window_rows == 0  # the number comes from the store, not from the run


def test_window_count_refuses_to_turn_a_missing_count_into_zero():
    """count(*) cannot be NULL; an empty reply means the read broke, and reporting it as 0 would blame the feed."""
    cur = _FakeCursor(None)
    with pytest.raises(RuntimeError, match="returned no value"):
        B.hermes_rows_in_window(cur)


def test_per_run_zero_is_still_the_allowed_no_new_input():
    out = B.lane_output({"bridged": 0, "candidates": 0, "skipped_dup": 0, "insert_errors": 0}, window_rows=3)
    assert out["empty_reason"] == "no_new_input"
    assert "dependency_unavailable" not in out["skipped_reasons"]


def test_window_zero_is_a_fatal_typed_skip_and_a_disallowed_empty_reason():
    out = B.lane_output({"bridged": 0, "candidates": 0, "skipped_dup": 0, "insert_errors": 0}, window_rows=0)
    assert out["empty_reason"] == B.WINDOW_EMPTY_REASON == "no_input_in_window"
    assert out["skipped_reasons"]["dependency_unavailable"] == 1


def test_an_unreadable_window_is_its_own_reason_and_never_folded_into_zero():
    out = B.lane_output({"bridged": 0, "candidates": 0, "skipped_dup": 0, "insert_errors": 0}, window_rows=None)
    assert out["empty_reason"] == B.WINDOW_UNKNOWN_REASON == "window_unreadable"
    assert out["skipped_reasons"]["dependency_unavailable"] == 1


def test_empty_reason_is_only_stamped_when_nothing_was_produced():
    out = B.lane_output({"bridged": 2, "candidates": 2, "skipped_dup": 0, "insert_errors": 0}, window_rows=2)
    assert out["empty_reason"] is None
    assert out["produced_count"] == 2


def _run_main(monkeypatch, tmp_path, *, window_rows: int, bridged: int = 0):
    """Call main() with run() and the receipt writer replaced; return (exit code, receipt kwargs)."""
    import lib.lane_last_receipt as llr  # the module main() imports at call time

    captured: dict = {}

    def fake_run(**kwargs):
        return {"run_at": "2026-11-07T00:00:00+00:00", "candidates": 0, "bridged": bridged,
                "skipped_dup": 0, "insert_errors": 0, "window_hours": B.WINDOW_HOURS,
                "window_rows": window_rows, "rows": []}

    def fake_write(lane_id, **kw):
        captured.update({"lane_id": lane_id, **kw})
        return {"lane_id": lane_id}

    monkeypatch.setattr(B, "run", fake_run)
    monkeypatch.setattr(llr, "write_lane_receipt", fake_write)
    monkeypatch.setattr(llr, "receipt_path", lambda name: tmp_path / f"{name}_last.json")
    monkeypatch.setattr(llr, "now_iso", lambda: "2026-11-07T00:00:00+00:00")
    return B.main(["--json"]), captured


def test_main_fails_the_run_when_the_contract_window_is_empty(monkeypatch, tmp_path):
    code, receipt = _run_main(monkeypatch, tmp_path, window_rows=0)
    assert code == 1
    assert receipt["ok"] is False
    assert "no source=hermes rows in the last 48 h" in receipt["error"]
    assert receipt["output"]["empty_reason"] == "no_input_in_window"
    assert receipt["output"]["skipped_reasons"]["dependency_unavailable"] == 1


def test_main_fails_the_run_when_the_window_count_did_not_arrive(monkeypatch, tmp_path):
    """A missing window count is unknown, not green and not zero: the contract rule is stated as unverified."""
    import lib.lane_last_receipt as llr

    captured: dict = {}

    def fake_run(**kwargs):
        return {"run_at": "x", "candidates": 0, "bridged": 0, "skipped_dup": 0, "insert_errors": 0, "rows": []}

    monkeypatch.setattr(B, "run", fake_run)
    monkeypatch.setattr(llr, "write_lane_receipt", lambda lane_id, **kw: captured.update(kw))
    monkeypatch.setattr(llr, "receipt_path", lambda name: tmp_path / f"{name}_last.json")
    monkeypatch.setattr(llr, "now_iso", lambda: "2026-11-07T00:00:00+00:00")
    assert B.main(["--json"]) == 1
    assert captured["ok"] is False
    assert "window count could not be read" in captured["error"]
    assert captured["output"]["empty_reason"] == "window_unreadable"


def test_main_stays_green_when_the_window_has_output(monkeypatch, tmp_path):
    code, receipt = _run_main(monkeypatch, tmp_path, window_rows=4, bridged=1)
    assert code == 0
    assert receipt["ok"] is True
    assert receipt["error"] is None
    assert receipt["output"]["empty_reason"] is None


def test_main_still_fails_when_every_insert_errored(monkeypatch, tmp_path):
    import lib.lane_last_receipt as llr

    captured: dict = {}

    def fake_run(**kwargs):
        return {"run_at": "x", "candidates": 2, "bridged": 0, "skipped_dup": 0, "insert_errors": 2,
                "window_hours": B.WINDOW_HOURS, "window_rows": 5, "rows": []}

    monkeypatch.setattr(B, "run", fake_run)
    monkeypatch.setattr(llr, "write_lane_receipt",
                        lambda lane_id, **kw: captured.update({"ok": kw.get("ok"), "error": kw.get("error")}))
    monkeypatch.setattr(llr, "receipt_path", lambda name: tmp_path / f"{name}_last.json")
    monkeypatch.setattr(llr, "now_iso", lambda: "2026-11-07T00:00:00+00:00")
    assert B.main(["--json"]) == 1
    assert captured["ok"] is False
    assert captured["error"] == "every news_articles insert errored"


def test_the_contract_declares_the_window_this_code_enforces():
    """The window and the empty reason are the contract's, not this module's invention."""
    contracts = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
    rows = contracts.get("contracts") if isinstance(contracts, dict) else contracts
    rows = rows if isinstance(rows, list) else rows.get("lanes", [])
    row = next(r for r in rows if isinstance(r, dict) and r.get("id") == B.LANE_ID)
    eo = row["expected_output"]
    assert eo["rule"] == "per_window"
    assert eo["min_produced"] == 1
    assert eo["window_h"] == B.WINDOW_HOURS
    assert "dependency_unavailable" in eo["fatal_skip_reasons"]
    assert B.WINDOW_EMPTY_REASON not in eo["empty_allowed_reasons"]
    assert B.WINDOW_UNKNOWN_REASON not in eo["empty_allowed_reasons"]


def test_module_imports_without_a_database():
    spec = importlib.util.find_spec("hermes_news_bridge")
    assert spec is not None
    assert "psycopg2" not in Path(B.__file__).read_text(encoding="utf-8").split("def db(")[0]
