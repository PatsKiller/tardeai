"""/v3/cio/home memory: same output, without parsing whole logs to keep a few rows.

Measured 2026-10-03 on prod data, one cold build: peak +363..370 MB -> +190 MB.
- _cio_actions_data parsed the 71 MB action ledger (~52k open actions) to
  return 20; it now streams twice and keeps only the newest k.
- home took the last 2-4 rows of three logs by parsing all of them (27 MB wake
  log); it now reads them backwards (_read_jsonl_tail).
- the two plan reads share one plan-store load.

Golden references below are the pre-change algorithms, frozen verbatim.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import api_v3_cio as A  # noqa: E402


def _golden_actions(path: Path, limit: int) -> list[dict]:
    events = A._read_jsonl(path)
    actions: dict = {}
    for event in events:
        payload = event.get("payload", {})
        aid = payload.get("cio_action_id")
        if not aid:
            continue
        event_type = event.get("event_type", "")
        if event_type == "CIO_ACTION_CREATED":
            actions[aid] = payload
        elif event_type == "CIO_ACTION_UPDATED":
            if aid in actions:
                actions[aid].update(payload)
    open_actions = [a for a in actions.values() if a.get("status") in ("OPEN", "ACKNOWLEDGED")]
    return sorted(open_actions, key=lambda a: a.get("created_at", ""), reverse=True)[:limit]


def _ev(et: str, **payload) -> dict:
    return {"event_type": et, "payload": payload}


def _ledger_rows() -> list:
    rows = [
        _ev("CIO_ACTION_UPDATED", cio_action_id="ghost", status="OPEN", created_at="2026-09-30"),  # update before create
        _ev("CIO_ACTION_CREATED", cio_action_id="a", status="OPEN", created_at="2026-09-01", title="a"),
        _ev("CIO_ACTION_CREATED", cio_action_id="b", status="OPEN", created_at="2026-09-05"),
        _ev("CIO_ACTION_UPDATED", cio_action_id="b", status="DONE"),
        _ev("CIO_ACTION_UPDATED", cio_action_id="b", status="ACKNOWLEDGED"),  # reopened
        _ev("CIO_ACTION_CREATED", cio_action_id="c", status="OPEN", created_at="2026-09-05"),  # tie with b
        _ev("CIO_ACTION_CREATED", cio_action_id="d", status="OPEN", created_at="2026-09-02"),
        _ev("CIO_ACTION_UPDATED", cio_action_id="d", created_at="2026-09-09", note="moved"),  # created_at changes
        _ev("CIO_ACTION_CREATED", cio_action_id="e", status="DONE", created_at="2026-09-03"),
        _ev("CIO_ACTION_CREATED", cio_action_id="a", status="OPEN"),  # re-create drops created_at, keeps position
        _ev("CIO_ACTION_CREATED", cio_action_id="f", status="OPEN", created_at="2026-09-07"),
        _ev("CIO_ACTION_UPDATED", cio_action_id="f", status="CLOSED"),
        _ev("OTHER_EVENT", cio_action_id="g", status="OPEN"),
        {"event_type": "CIO_ACTION_CREATED", "payload": {}},
    ]
    for i in range(80):  # more open actions than the cached k
        rows.append(_ev("CIO_ACTION_CREATED", cio_action_id=f"bulk{i:03d}", status="OPEN",
                        created_at=f"2026-08-{(i % 28) + 1:02d}"))
    return rows


def _write_ledger(root: Path, rows: list, extra_lines: tuple[str, ...] = ()) -> Path:
    path = root / "data" / "cio" / "cio_action_ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r) + "\n" for r in rows) + "".join(extra_lines)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "PROJECT_ROOT", tmp_path)
    A._OPEN_ACTIONS_CACHE.update({"key": None, "rows": None})
    path = _write_ledger(tmp_path, _ledger_rows(), ("\n", "not json\n", "[1, 2]\n"))
    yield path
    A._OPEN_ACTIONS_CACHE.update({"key": None, "rows": None})


@pytest.mark.parametrize("limit", [1, 2, 5, 15, 20, 30, 49, 50, 51, 200])
def test_actions_match_the_full_projection(ledger, limit):
    golden = _golden_actions(ledger, limit)
    A._OPEN_ACTIONS_CACHE.update({"key": None, "rows": None})
    assert json.dumps(A._cio_actions_data(limit), sort_keys=True) == json.dumps(golden, sort_keys=True)


def test_actions_cache_is_bounded_isolated_and_refreshes(ledger):
    first = A._cio_actions_data(20)
    assert len(A._OPEN_ACTIONS_CACHE["rows"]) == A._OPEN_ACTIONS_MIN_K
    first[0]["status"] = "MUTATED"
    assert A._cio_actions_data(20)[0]["status"] != "MUTATED"
    rows = _ledger_rows() + [_ev("CIO_ACTION_CREATED", cio_action_id="z", status="OPEN", created_at="2026-12-31")]
    _write_ledger(ledger.parents[2], rows)
    assert A._cio_actions_data(1)[0]["cio_action_id"] == "z"


def test_missing_ledger_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "PROJECT_ROOT", tmp_path)
    A._OPEN_ACTIONS_CACHE.update({"key": None, "rows": None})
    assert A._cio_actions_data(20) == []


def test_tail_reader_matches_full_read(tmp_path):
    path = tmp_path / "log.jsonl"
    parts = []
    for i in range(40):
        parts.append(json.dumps({"i": i, "s": "é✓" * (i % 5)}))
        if i % 7 == 0:
            parts.append("")
        if i % 9 == 0:
            parts.append("{broken")
        if i % 11 == 0:
            parts.append("[1]")
    body = "\n".join(parts[:20]) + "\r\n" + "\r\n".join(parts[20:30]) + "\r" + "\n".join(parts[30:])  # no trailing newline
    path.write_bytes(body.encode("utf-8"))
    full = A._read_jsonl(path)
    for n in (1, 2, 3, 4, 7, 30, 39, 40, 41, 500):
        for block in (1, 3, 16, 64, 65536):
            assert A._read_jsonl_tail(path, n, block=block) == full[-n:], (n, block)
    assert A._read_jsonl_tail(tmp_path / "missing.jsonl", 3) == []
    assert A._read_jsonl_tail(path, 0) == []


def test_home_uses_tail_reads_and_one_plan_store():
    src = inspect.getsource(A.get_cio_home)
    assert src.count("_plan_store()") == 1
    assert "get_cio_plans(limit=12, store=plan_store)" in src
    assert "_coverage_plan_index(store=plan_store)" in src
    assert "_read_jsonl(PROJECT_ROOT" not in src
    assert src.count("_read_jsonl_tail(") == 3


class _Store:
    def __init__(self):
        self.calls = []

    def list_open_plans(self, situation_type=None, limit=None):
        self.calls.append(limit)
        return [{"plan_id": "p1", "situation_type": "S6", "status": "draft", "symbols": ["X"]}]


def test_plan_reads_use_the_given_store(monkeypatch):
    monkeypatch.setattr(A, "_plan_store", lambda: (_ for _ in ()).throw(AssertionError("store reopened")))
    store = _Store()
    assert A.get_cio_plans(limit=12, store=store)["count"] == 1
    assert A._coverage_plan_index(store=store)[0]["plan_id"] == "p1"
    assert store.calls == [12, 5000]
