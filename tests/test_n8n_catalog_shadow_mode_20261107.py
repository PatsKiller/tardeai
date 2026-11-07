"""ANCHOR: N8N_CATALOG_SHADOW_MODE_20261107 — a shadow/dry-run lane is not "live" because of one old apply.

`jsonl-archive-rotate` was FAIL_CONFIG in the 17:30 ET DB integrity re-test with the defect "Not in the relay
list; stage=shadow. It was mislabelled as live n8n." The live catalog proved it on release 232e794a2:

    {"lane_id": "jsonl-archive-rotate", "last_run_mode": "live", "mode": "live", "in_relay": false,
     "verdict": "FAIL_CONFIG"}

The chain: the lane is `scheduler.stage: shadow` with `dispatch.mode: dry_run`, and every dispatched run is a
dry run (`run_outcomes`: 11-03 … 11-06 all mode dry_run, RUN_DONE). `jobs_history` merges the lane's own last
receipt — a one-off manual `--apply` at 2026-11-04T02:42Z, `"mode": "live"` — and `last = (live or runs)[-1]`
keeps the last LIVE run, so `last_run.mode` is "live" four days later. `n8n_catalog.derive_mode` then read the
mode off that receipt and called the lane live, while the registry, the relay list and the ledger all say it
rehearses.

The fix makes the registry the authority, matching LQ-114's rule ("a shadow lane is never n8n-live"): a lane
whose registry row is stage shadow or dispatch.mode dry_run derives "dry" whatever its last run says. A lane
that is not declared that way keeps the previous reading, and cron lanes are untouched.

COVERS: scripts/lib/n8n_catalog.py::rehearsal_lanes
COVERS: scripts/lib/n8n_catalog.py::derive_mode
COVERS: scripts/lib/n8n_catalog.py::build
COVERS: scripts/lib/n8n_catalog.py::compute
COVERS: config/lane_registry.json::jsonl-archive-rotate (stage shadow, dispatch dry_run)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import n8n_catalog as N  # noqa: E402

RELAY = frozenset({"relay-n8n", "relay-cron"})


def _row(lane, scheduler, *, mode=None, state="ACTIVE"):
    return {"lane_id": lane, "title": lane, "job": lane, "does": f"does {lane}", "category_key": "ops",
            "scheduler": scheduler, "state": state, "status": "ok",
            "last_run": {"mode": mode} if mode else None,
            "cadence": {"expressions": ["45 16 * * 1-5"], "timezone": "America/New_York"}}


def _registry(tmp_path: Path, rows) -> Path:
    p = tmp_path / "lane_registry.json"
    p.write_text(json.dumps({"schema": "LaneRegistry@v1", "lanes": rows}), encoding="utf-8")
    return p


# ── derive_mode: the registry decides, not a stale receipt ───────────────────────────────────────────────────


def test_a_shadow_lane_with_an_old_live_run_is_dry():
    """The defect: one manual --apply in the past must not make a shadow lane 'live' today."""
    row = _row("jsonl-archive-rotate", "n8n", mode="live")
    assert N.derive_mode(row, RELAY, frozenset({"jsonl-archive-rotate"})) == "dry"


def test_the_same_row_without_the_registry_declaration_stays_live():
    """Control: the declaration is what changed the answer — an undeclared lane keeps reading its last run."""
    row = _row("some-n8n-lane", "n8n", mode="live")
    assert N.derive_mode(row, RELAY) == "live"
    assert N.derive_mode(row, RELAY, frozenset()) == "live"


def test_a_rehearsing_lane_in_the_relay_list_is_still_dry():
    """The registry wins over relay membership too: a shadow lane is never n8n-live (LQ-114)."""
    row = _row("relay-n8n", "n8n", mode="live")
    assert N.derive_mode(row, RELAY, frozenset({"relay-n8n"})) == "dry"


def test_cron_lanes_are_unchanged_by_the_declaration():
    row = _row("relay-cron", "cron")
    assert N.derive_mode(row, RELAY, frozenset({"relay-cron"})) == "both"


# ── rehearsal_lanes: which registry rows say they rehearse ────────────────────────────────────────────────────


def test_rehearsal_lanes_reads_stage_shadow_and_dry_run_dispatch(tmp_path):
    reg = _registry(tmp_path, [
        {"lane_id": "shadow-lane", "scheduler": {"kind": "n8n", "stage": "shadow"}, "dispatch": {"mode": "live"}},
        {"lane_id": "dry-lane", "scheduler": {"kind": "n8n"}, "dispatch": {"mode": "dry_run"}},
        {"lane_id": "live-lane", "scheduler": {"kind": "n8n"}, "dispatch": {"mode": "live"}},
        {"lane_id": "cron-lane", "scheduler": {"kind": "cron"}},
        "not-a-row",
    ])
    lanes, note = N.rehearsal_lanes(reg)
    assert lanes == frozenset({"shadow-lane", "dry-lane"}) and note is None


def test_a_missing_registry_is_a_note_not_a_crash(tmp_path):
    lanes, note = N.rehearsal_lanes(tmp_path / "absent.json")
    assert lanes == frozenset() and note and "not found" in note


@pytest.mark.parametrize("body", ["{not json", json.dumps({"lanes": "nope"}), json.dumps([1, 2])])
def test_an_unreadable_registry_is_a_note_not_a_crash(tmp_path, body):
    p = tmp_path / "lane_registry.json"
    p.write_text(body, encoding="utf-8")
    lanes, note = N.rehearsal_lanes(p)
    assert lanes == frozenset() and note and "could not be read" in note


def test_the_shipped_registry_declares_the_lane_as_rehearsing():
    """The config contract this fix relies on: jsonl-archive-rotate is stage shadow with dispatch dry_run."""
    lanes, note = N.rehearsal_lanes(ROOT / N.REGISTRY_REL)
    assert note is None
    assert "jsonl-archive-rotate" in lanes


# ── compute(): the catalog the page serves ───────────────────────────────────────────────────────────────────


def _compute(tmp_path, registry, rows):
    import scripts.lib.n8n_catalog as mod

    snap = {"rows": rows, "categories": [{"key": "ops", "label": "Ops", "blurb": ""}],
            "computed_at": "2026-11-07T23:00:00+00:00"}
    orig = mod.read_relay
    mod.read_relay = lambda root, env: (RELAY, {"source": "test", "lanes": len(RELAY), "paused": [], "note": None})
    try:
        return N.compute(environ={}, state=tmp_path, snapshot_fn=lambda: snap, registry=registry)
    finally:
        mod.read_relay = orig


def test_compute_labels_the_shadow_lane_dry_end_to_end(tmp_path):
    reg = _registry(tmp_path, [{"lane_id": "jsonl-archive-rotate",
                                "scheduler": {"kind": "n8n", "stage": "shadow"},
                                "dispatch": {"mode": "dry_run"}}])
    out = _compute(tmp_path, reg, [_row("jsonl-archive-rotate", "n8n", mode="live")])
    lane = out["lanes"]["jsonl-archive-rotate"]
    assert lane["mode"] == "dry"
    assert lane["last_run_mode"] == "live", "the last live run is still reported — it is the mode that was wrong"
    assert out["stats"]["modes"]["dry"] == 1 and out["stats"]["modes"]["live"] == 0


def test_compute_leaves_an_undeclared_lane_reading_its_last_run(tmp_path):
    reg = _registry(tmp_path, [{"lane_id": "elsewhere", "scheduler": {"kind": "n8n"},
                                "dispatch": {"mode": "live"}}])
    out = _compute(tmp_path, reg, [_row("jsonl-archive-rotate", "n8n", mode="live")])
    assert out["lanes"]["jsonl-archive-rotate"]["mode"] == "live"
