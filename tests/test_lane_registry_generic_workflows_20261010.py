"""The six generic n8n workflows (AGENTS.md §23.11) are declared by their committed INDEX.

2026-10-10, W0 import packet dry run: the gate's known-id list held only the per-lane generated INDEX, so once the
six were activated under their `cron` grant, `check_lane_registry --n8n-live --fail-on-new` would have reported
six UNDECLARED_N8N_WORKFLOW. Hermetic: reads only committed repository files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_registry as LR  # noqa: E402

SIX = (
    "tradeai-dispatcher",
    "tradeai-event-router",
    "tradeai-heartbeat-watcher",
    "tradeai-incident-router",
    "tradeai-digest-scheduler",
    "tradeai-approval-router",
)


def _found(*ids: str) -> dict:
    return {"cron": [], "systemd": [], "n8n": [{"kind": "n8n", "expression": i, "name": i} for i in ids]}


def test_generic_index_lists_exactly_the_six():
    assert sorted(LR.n8n_generic_workflow_ids()) == sorted(SIX)


def test_the_six_active_are_declared_but_an_unknown_id_still_is_not():
    known = LR.n8n_known_workflow_ids()
    assert LR.find_undeclared({"lanes": []}, _found(*SIX), n8n_known_ids=known) == []
    out = LR.find_undeclared({"lanes": []}, _found("tradeai-dispatcher-2"), n8n_known_ids=known)
    assert [u["code"] for u in out] == [LR.UNDECLARED_N8N_WORKFLOW]


def test_per_lane_generated_ids_are_still_known():
    from scripts.lib import n8n_live_inventory as inv

    assert set(inv.known_workflow_ids()) <= set(LR.n8n_known_workflow_ids())


def test_unreadable_or_foreign_generic_index_fails_closed(tmp_path):
    with pytest.raises(OSError):
        LR.n8n_generic_workflow_ids(tmp_path / "missing.json")
    bad = tmp_path / "INDEX.json"
    bad.write_text(json.dumps({"schema": "Other@v1", "workflows": [{"id": "x"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        LR.n8n_generic_workflow_ids(bad)
