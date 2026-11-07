"""hermes-research-worker-pool says WHY an hourly slot produced nothing (WORK-QUEUE item 16, 2026-11-07).

The live 2026-11-07T19:05Z receipt was LaneRunReceipt@v1 only:

    summary {completed_lanes 0, skipped_lanes 9, scanned 0, upserted 0,
             lane_outcomes {holdings: not_due, watchlist: not_due, ... all 9}}

— a normal hourly slot in which no worker lane was due. The quality grader can only read that as
"produced nothing (summary.upserted = 0; the receipt does not say why)", and the lane's own contract
(config/n8n_health_contracts.json) had already named ``produced_count`` as its unit with
``empty_allowed_reasons: [nothing_due, no_new_input]``. The reason was knowable; the receipt just never said it.

Hermetic: the pool's ``run_pool`` is replaced by a synthetic report, the state root is tmp, no DB, no network,
no runner module import.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import lane_last_receipt as LR  # noqa: E402
from lib import n8n_output_verdict as V  # noqa: E402

LANE = "hermes-research-worker-pool"
# The live shape: nine configured worker lanes, every one of them outside its cadence window.
NINE_NOT_DUE = ("holdings", "watchlist", "white_space", "strategy", "private_proxy",
                "legal_domain", "tax_retirement", "system_ops", "custom_domain")


def _load():
    spec = importlib.util.spec_from_file_location("hrwp_receipt_t", ROOT / "scripts" / "hermes_research_worker_pool.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _contract() -> dict:
    """The lane's expected_output rule from the committed health contracts (its ``id`` is the lane id)."""
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())
    for entry in doc["contracts"]:
        if entry.get("id") == LANE or entry.get("lane_id") == LANE:
            return entry["expected_output"]
    raise AssertionError(f"no health contract for {LANE}")


class _FakePool:
    def __init__(self, report):
        self.report = report

    def run_pool(self, lane_ids, dry_run=False, force=False):
        return self.report


def _report(lanes: dict, *, ok: bool = True, failures: list | None = None) -> dict:
    outcomes = {}
    for lane_id, res in lanes.items():
        scanned = res.get("scanned")
        produced = isinstance(scanned, int) and scanned > 0 and "skipped" not in res
        outcomes[lane_id] = {"lane": lane_id, "ok": True,
                             "outcome": "produced" if produced else "not_due"}
    return {"do_no_harm": {"ok": True}, "caps_applied": {}, "dry_run": False, "max_workers": 4,
            "lanes": lanes, "lane_outcomes": outcomes,
            "failures": list(failures or []), "ok": ok}


@pytest.fixture
def lane_env(tmp_path, monkeypatch):
    run_id = f"d:{LANE}:live:20261107T1905"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv(LR.RUN_ID_ENV, run_id)
    monkeypatch.setenv(LR.RUN_ATTEMPT_ENV, "1")
    monkeypatch.setenv(LR.RUN_MODE_ENV, "live")
    monkeypatch.setenv(LR.CODE_SHA_ENV, "0" * 40)
    mod = _load()
    mod.RUNNER_IMPORT_ERRORS.clear()
    mod._load_dependencies = lambda: None  # the runners are not imported for a stubbed report
    return mod, tmp_path, run_id


def _run(mod, report) -> int:
    mod.worker_pool = _FakePool(report)
    return mod.main(["--run", "--json"])


def _attempt(tmp_path, run_id) -> dict:
    path = LR.attempt_receipt_path(LANE, run_id, tmp_path)
    assert path.is_file(), f"no per-attempt receipt at {path}"
    return json.loads(path.read_text())


# ── the live shape: nothing was due, and the receipt now says so ───────────────────────────────────────────────


def test_the_live_all_not_due_slot_names_nothing_due(lane_env):
    mod, tmp_path, run_id = lane_env
    assert _run(mod, _report({lid: {"skipped": "cadence"} for lid in NINE_NOT_DUE})) == 0
    doc = _attempt(tmp_path, run_id)
    assert doc["schema"] == "LaneRunReceipt@v2"
    assert doc["produced_count"] == 0
    assert doc["attempted_count"] == 0
    assert doc["empty_reason"] == "nothing_due"


def test_the_live_all_not_due_slot_grades_empty_allowed(lane_env):
    mod, tmp_path, run_id = lane_env
    _run(mod, _report({lid: {"skipped": "cadence"} for lid in NINE_NOT_DUE}))
    verdict = V.evaluate(_contract(), _attempt(tmp_path, run_id), run_id=run_id, lane_id=LANE, mode="live")
    assert verdict["verdict"] == "empty_allowed", verdict


def test_the_v1_last_receipt_keeps_its_readers(lane_env):
    # output= rides the v2 fields additively: _last.json stays v1 for anything that reads summary.upserted today.
    mod, tmp_path, run_id = lane_env
    _run(mod, _report({lid: {"skipped": "cadence"} for lid in NINE_NOT_DUE}))
    last = json.loads(LR.receipt_path(LANE, tmp_path).read_text())
    assert last["schema"] == "LaneRunReceipt@v1"
    assert last["output_fields"] == "LaneRunReceipt@v2"
    assert last["empty_reason"] == "nothing_due"
    assert last["summary"]["upserted"] == 0 and last["summary"]["skipped_lanes"] == 9


# ── the other two shapes ──────────────────────────────────────────────────────────────────────────────────────


def test_a_slot_that_produced_reports_its_counts_and_no_empty_reason(lane_env):
    mod, tmp_path, run_id = lane_env
    report = _report({"watchlist": {"scanned": 5, "upserted": 3, "skipped_payloads": 2}})
    assert _run(mod, report) == 0
    doc = _attempt(tmp_path, run_id)
    assert doc["produced_count"] == 3 and doc["attempted_count"] == 5
    assert doc.get("empty_reason") is None
    assert V.evaluate(_contract(), doc, run_id=run_id, lane_id=LANE, mode="live")["verdict"] == "produced"


def test_runners_scanned_but_upserted_none_is_no_new_input(lane_env):
    mod, tmp_path, run_id = lane_env
    report = _report({"watchlist": {"scanned": 4, "upserted": 0, "skipped_payloads": 4}})
    assert _run(mod, report) == 0
    doc = _attempt(tmp_path, run_id)
    assert doc["produced_count"] == 0 and doc["attempted_count"] == 4
    assert doc["empty_reason"] == "no_new_input"
    assert V.evaluate(_contract(), doc, run_id=run_id, lane_id=LANE, mode="live")["verdict"] == "empty_allowed"


def test_a_failed_run_claims_no_empty_reason(lane_env):
    # A failure is graded on its failure; naming an empty reason would describe only part of it.
    mod, tmp_path, run_id = lane_env
    report = _report({"watchlist": {"scanned": 0}}, ok=False,
                     failures=[{"lane": "watchlist", "outcome": "runner_error"}])
    assert _run(mod, report) == 3
    doc = _attempt(tmp_path, run_id)
    assert doc["status"] == "failed" and doc["exit"] == 3
    assert doc.get("empty_reason") is None


# ── drift guard ──────────────────────────────────────────────────────────────────────────────────────────────


def test_every_reason_this_lane_can_emit_is_allowed_by_its_contract():
    import inspect

    emitted = {"nothing_due", "no_new_input"}
    allowed = set(_contract()["empty_allowed_reasons"])
    assert emitted <= allowed, (emitted - allowed)
    # and the emitted reasons are exactly the ones lane_output can return for a healthy empty run
    src = inspect.getsource(_load().lane_output)
    for reason in emitted:
        assert f'"{reason}"' in src, reason
