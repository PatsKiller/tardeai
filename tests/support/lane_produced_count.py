"""Shared harness for the CW1-CW3 produced_count tests (2026-10-15, expected_output opt-in).

A lane opts into the executor's output verdict (allowlist ``output_receipt: "v2"``) only together with the code that
writes LaneRunReceipt@v2 ``produced_count``. Each per-lane test drives the lane's REAL ``main()`` with its DB / network
work stubbed, inside a fake n8n attempt (``TRADEAI_RUN_ID`` ... set, ``TRADEAI_STATE_ROOT`` = tmp), then:

* reads the immutable per-attempt receipt the lane wrote (``lane_attempts/<lane>/<run_id>.json``), and
* hands a RUN_DONE executor receipt for that attempt to ``n8n_run_executor.apply_output_verdict`` with the COMMITTED
  health contracts and the COMMITTED allowlist entry -- the same call the executor makes after an exit-0 live run.

Hermetic: tmp state root, no DB, no network, no broker, no secret.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import n8n_run_executor as X
from scripts.lib import lane_last_receipt as LR

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = X.parse_expected_outputs((ROOT / "config" / "n8n_health_contracts.json").read_bytes())
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
_SEQ = [0]


def attempt_env(monkeypatch, tmp_path: Path, lane: str) -> str:
    """Set the attempt identity the executor hands a LIVE lane; returns the run id."""
    _SEQ[0] += 1
    run_id = f"d:{lane}:live:20261015T1200-{_SEQ[0]:04d}"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv(LR.RUN_ID_ENV, run_id)
    monkeypatch.setenv(LR.RUN_ATTEMPT_ENV, "1")
    monkeypatch.setenv(LR.RUN_MODE_ENV, "live")
    monkeypatch.setenv(LR.CODE_SHA_ENV, "0" * 40)
    return run_id


def attempt_receipt(tmp_path: Path, lane: str, run_id: str) -> dict[str, Any]:
    path = LR.attempt_receipt_path(lane, run_id, tmp_path)
    assert path.is_file(), f"{lane}: no per-attempt receipt at {path}"
    doc = json.loads(path.read_text())
    assert doc["schema"] == "LaneRunReceipt@v2" and doc["run_id"] == run_id and doc["lane_id"] == lane
    return doc


def verdict(tmp_path: Path, lane: str, run_id: str) -> dict[str, Any]:
    """The executor's post-spawn receipt for an exit-0 LIVE attempt of ``lane`` (committed contract + entry)."""
    receipt = {"run_id": run_id, "lane_id": lane, "mode": "live", "state": "RUN_DONE", "exit": 0}
    return X.apply_output_verdict(receipt, CONTRACTS, lane_id=lane, mode="live", state_root=tmp_path,
                                  entry=ALLOW[lane])


def assert_opted_in(lane: str) -> None:
    """The committed entry opts in, the committed contract declares the rule on produced_count, and the lane's
    script writes produced_count (the factory rule)."""
    entry = ALLOW[lane]
    assert entry.get("output_receipt") == "v2", lane
    rule = CONTRACTS[lane]
    assert rule["produced_field"] == "produced_count", lane
    scripts = [t for t in entry["command"] if t.endswith(".py")]
    assert any("produced_count" in (ROOT / s).read_text() for s in scripts), lane


def check(tmp_path: Path, lane: str, run_id: str, *, produced: int, expect: str) -> dict[str, Any]:
    """Attempt receipt has ``produced``; the executor verdict is ``expect`` (produced | empty_allowed |
    empty_output). Returns the executor receipt."""
    doc = attempt_receipt(tmp_path, lane, run_id)
    assert doc["produced_count"] == produced, (lane, doc)
    out = verdict(tmp_path, lane, run_id)
    if expect == "empty_output":
        assert out["state"] == "RUN_FAILED" and out["reason"] == "empty_output", (lane, out)
    else:
        assert out["state"] == "RUN_DONE", (lane, out)
        assert out["output_verdict"]["verdict"] == expect, (lane, out)
    return out
