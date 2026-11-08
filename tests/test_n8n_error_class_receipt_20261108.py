"""LQ-20261107-992 (Fable n8n design audit item #11) — a lane's run receipt carries the failure CLASS.

Measured in the audit (inbox/claude-lead/FABLE-N8N-DESIGN-AUDIT-LQ-984.md Q4): 19,483 diagnosis events in one week,
`failure_kind: unknown` on 19,036 (97.7%), because the deterministic tier classified the SIEM row's error TEXT and a
lane that exited non-zero without a traceback carried nothing to classify — and an 800-char tail cut the useful frame
out of the ones that did.

This suite pins the three halves of the fix:
1. `scripts/lib/n8n_error_class.py` — one vocabulary (the existing `n8n_self_heal.failure_kind` classes plus the
   receipt-only states), the lane's own declaration wins, `unknown` only when a failed run names nothing at all;
2. the executor stamps `error_class` on every terminal receipt, keeps a 4,000-char tail, and prefers the class the
   lane wrote on its own LaneRunReceipt for THAT attempt (a stale `_last.json` from another run is not evidence);
3. `resolve()` gives the diagnoser the receipt's class before the text fallback.

Every fixture is synthetic (the repo is PUBLIC). No ledger, DB, broker or network is touched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import n8n_error_class as EC  # noqa: E402
from scripts.lib import n8n_self_heal as H  # noqa: E402
from scripts.lib.lane_last_receipt import (  # noqa: E402
    attempt_receipt_path,
    receipt_path,
    write_lane_receipt,
)

RUN_ID = "run-errclass-000000001"
LANE = "errclass-lane"
#: > 800 chars with the class on the LAST line: the old cut lost every frame above it.
TRACEBACK = (
    "Traceback (most recent call last):\n"
    + "".join(f'  File "/srv/lanes/step_{i}.py", line {i}, in <module>\n    work()\n' for i in range(60))
    + "ValueError: universe is empty\n"
)


class _Runner:
    """Same contract as ``_subprocess_runner`` without spawning; optionally writes the lane's receipt."""

    def __init__(self, *, rc=0, out="", err="", exc=None, lane_class=None, state=None, run_id=RUN_ID):
        self.rc, self.out, self.err, self.exc = rc, out, err, exc
        self.lane_class, self.state, self.run_id = lane_class, state, run_id

    def __call__(self, argv, *, timeout, env, cwd):
        if self.lane_class is not None:
            path = attempt_receipt_path(LANE, self.run_id, self.state)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "schema": "LaneRunReceipt@v2", "run_id": self.run_id, "lane_id": LANE,
                "error_class": self.lane_class,
            }), encoding="utf-8")
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.rc, self.out, self.err)


@pytest.fixture
def bench(tmp_path, monkeypatch):
    code = tmp_path / "code"
    (code / "scripts").mkdir(parents=True)
    (code / "GIT_SHA").write_text("f" * 40 + "\n")
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "locks").mkdir()
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("TRADEAI_VENV_PYTHON", sys.executable)
    monkeypatch.setenv("SAFE_FLOCK_LOG_DIR", str(tmp_path / "flock-logs"))
    entry = {
        "lane_id": LANE,
        "command": [sys.executable, "scripts/fake_lane.py"],
        "lock": str(tmp_path / "locks" / "lane.lock"),
        "timeout_s": 5,
        "dry_run_arg": ["--dry-run"],
        "live_arg": ["--apply"],
        "market_gate": False,
    }
    row = {"run_id": RUN_ID, "lane_id": LANE, "mode": "live", "attempt": 1}
    return {"code": code, "state": state, "entry": entry, "row": row}


def _execute(bench, runner):
    return X._execute_once(
        bench["row"], bench["entry"], env=dict(os.environ), state_root=bench["state"],
        code_root=bench["code"], runner=runner,
    )


# ---------------------------------------------------------------- the vocabulary


@pytest.mark.parametrize(
    "state,kwargs,expected",
    [
        ("RUN_TIMEOUT", {}, ("timeout", EC.EXECUTOR)),
        ("RUN_FAILED", {"timed_out": True}, ("timeout", EC.EXECUTOR)),
        ("RUN_SKIPPED_LOCK", {"reason": "flock_held"}, ("lock_contention", EC.EXECUTOR)),
        ("RUN_REFUSED", {"reason": "lane_not_allowlisted"}, ("refused", EC.EXECUTOR)),
        ("RUN_FAILED", {"exit_code": 1}, ("nonzero_exit", EC.EXECUTOR)),
        ("RUN_FAILED", {"exit_code": -9}, ("killed", EC.EXECUTOR)),
        ("RUN_FAILED", {"exit_code": 1, "reason": "spawn:OSError:ENOMEM"}, ("environment", EC.EXECUTOR)),
        ("RUN_FAILED", {"exit_code": 1, "reason": "empty_output"}, ("empty_output", EC.EXECUTOR)),
        ("RUN_FAILED", {"exit_code": 1, "stderr_tail": "HTTP 429 Too Many Requests"}, ("rate_limit", EC.EXECUTOR)),
        ("RUN_FAILED", {"exit_code": 1, "stderr_tail": "HTTP 401 Unauthorized"}, ("auth", EC.EXECUTOR)),
        ("RUN_FAILED", {"exit_code": 1, "stderr_tail": TRACEBACK}, ("code_error:ValueError", EC.EXECUTOR)),
        ("RUN_DONE", {}, (None, None)),
        ("RUN_DONE", {"output_verdict": {"verdict": "empty_violation"}}, ("empty_output", EC.EXECUTOR)),
        ("RUN_DONE", {"output_verdict": {"verdict": "unverifiable"}}, ("output_unverifiable", EC.EXECUTOR)),
        # unknown only when a failed run names neither an exit code, a reason nor any text
        ("RUN_FAILED", {}, ("unknown", EC.EXECUTOR)),
        # the lane's own declaration wins over everything
        ("RUN_FAILED", {"exit_code": 1, "stderr_tail": TRACEBACK, "lane_class": "rate_limit"},
         ("rate_limit", EC.LANE)),
    ],
)
def test_classify(state, kwargs, expected):
    assert EC.classify(state=state, **kwargs) == expected


@pytest.mark.parametrize("value,expected", [
    ("auth", "auth"),
    ("code_error:ValueError", "code_error:ValueError"),
    ("kill -9", None),
    ("Made Up Class!", None),
    ("", None),
    (None, None),
    ("unknown", "unknown"),
])
def test_declared_values_must_be_in_the_one_vocabulary(value, expected):
    assert EC.normalise_declared(value) == expected


def test_out_of_vocabulary_declaration_is_kept_bounded_but_never_a_class():
    receipt = EC.stamp({"state": "RUN_FAILED", "exit_code": 1}, lane_class="Totally Made Up! " * 20)
    assert receipt["error_class"] == "nonzero_exit"
    assert receipt["error_class_source"] == EC.EXECUTOR
    assert len(receipt[EC.DECLARED_FIELD]) == EC.DECLARED_MAX_CHARS


# ---------------------------------------------------------------- the executor


def test_failing_lane_receipt_carries_its_class_and_the_whole_tail(bench):
    receipt = _execute(bench, _Runner(rc=1, err=TRACEBACK))
    assert receipt["state"] == "RUN_FAILED" and receipt["reason"] == "exit_1"
    assert receipt["error_class"] == "code_error:ValueError"
    assert receipt["error_class_source"] == EC.EXECUTOR
    assert X.TAIL_CHARS == 4000
    assert TRACEBACK in receipt["stderr_tail"] and len(receipt["stderr_tail"]) > 800


def test_silent_nonzero_exit_is_classed_not_unknown(bench):
    receipt = _execute(bench, _Runner(rc=1))
    assert (receipt["error_class"], receipt["error_class_source"]) == ("nonzero_exit", EC.EXECUTOR)


def test_timeout_is_classed(bench):
    receipt = _execute(bench, _Runner(exc=subprocess.TimeoutExpired(["x"], 5)))
    assert receipt["state"] == "RUN_TIMEOUT" and receipt["error_class"] == "timeout"


def test_run_done_receipt_has_no_error_class(bench):
    receipt = _execute(bench, _Runner(rc=0, out="did the work"))
    assert receipt["state"] == "RUN_DONE" and "error_class" not in receipt


def test_the_lane_declared_class_wins_over_the_text(bench):
    receipt = _execute(bench, _Runner(rc=1, err="something vague", lane_class="network", state=bench["state"]))
    assert (receipt["error_class"], receipt["error_class_source"]) == ("network", EC.LANE)


def test_a_stale_last_receipt_is_not_this_runs_evidence(bench):
    last = receipt_path(LANE, bench["state"])
    last.parent.mkdir(parents=True, exist_ok=True)
    last.write_text(json.dumps({"schema": "LaneRunReceipt@v1", "lane_id": LANE,
                                "run_id": "run-errclass-other", "error_class": "auth"}), encoding="utf-8")
    receipt = _execute(bench, _Runner(rc=1))
    assert (receipt["error_class"], receipt["error_class_source"]) == ("nonzero_exit", EC.EXECUTOR)


def test_lane_receipt_stores_only_a_valid_class(bench):
    good = write_lane_receipt(LANE, ok=False, error="boom", error_class="rate_limit",
                              path=bench["state"] / "good.json")
    doc = json.loads(Path(good).read_text(encoding="utf-8"))
    assert doc["error_class"] == "rate_limit" and doc["status"] == "failed"
    bad = write_lane_receipt(LANE, ok=False, error="boom", error_class="not a class",
                             path=bench["state"] / "bad.json")
    assert "error_class" not in json.loads(Path(bad).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the diagnoser's input


def _row(receipt: dict | None) -> dict:
    return {"receipt_json": json.dumps(receipt) if receipt is not None else "{}"}


def test_receipt_class_is_read_off_the_ledger_row():
    assert EC.from_receipt(_row({"error_class": "auth"})) == "auth"
    assert EC.from_receipt(_row({"error_class": "garbage !!"})) is None
    assert EC.from_receipt(_row(None)) is None and EC.from_receipt({}) is None


def test_resolve_prefers_the_receipt_class_over_the_text():
    assert EC.resolve("", _row({"error_class": "timeout"}), event_type="RUN_FAILED") == ("timeout", "receipt")
    assert EC.resolve("HTTP 401 Unauthorized", _row(None), event_type="RUN_FAILED") == ("auth", "text")


def test_signature_keeps_two_silent_failures_of_different_classes_apart():
    timeout = H.signature(LANE, "RUN_FAILED", "", error_class="timeout")
    nonzero = H.signature(LANE, "RUN_FAILED", "", error_class="nonzero_exit")
    assert timeout != nonzero
    assert timeout == H.signature(LANE, "RUN_FAILED", "", error_class="timeout")
