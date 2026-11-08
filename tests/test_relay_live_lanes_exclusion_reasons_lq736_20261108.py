"""ANCHOR: RELAY_LIVE_LANES_EXCLUSION_REASONS_LQ736_20261108. LQ-20261107-736 (follows the LQ-716 CHANGES review).

The relay live-list render must never drop a lane silently. ``registry_live_lanes`` names a reason in
``excluded`` for EVERY registry row that carries a live claim — a ``dispatch`` block, a ``scheduler.stage``,
``scheduler.kind: n8n``, or a non-null allowlist ``live_arg`` — so a lane leaving the live set moves the
``excluded`` map, not only the lane count.

Fail-before (base 446de793a, the LQ-716 head; reproduced in the DONE note): the contract tests below fail — a
shadow lane whose dispatch block says ``dry_run`` was dropped by a bare ``continue``, so the real registry's
``excluded`` map was EMPTY for all 723 rows: 48 rows with a non-live dispatch block (47 ``dry_run``, 1 ``off``),
native n8n rows with no stage named only when ACTIVE *and* holding a live_arg, and cron/systemd rows carrying a
live argv were unnamed. By this file's rule 67 rows carried a live claim and none was named (52 by the review's
narrower dispatch-block-or-stage rule). Pass-after: every claimed row is live or named.

Hermetic: synthetic one-row registries, plus the repo's own committed registry/allowlist read-only for the
completeness sweep; no state root, no DB, no n8n, no live argv. Lane ids and reason codes only.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_relay_live_lanes as RLL  # noqa: E402

LANE = "zz-lq736-lane"
LIVE_ARG = ["--apply", "--confirm", "APPLY"]

#: Reason-code prefixes the function may emit (an unknown new code is a deliberate change; this list is the
#: contract the render and the Ops Controls display read).
PREFIXES = (
    "dispatch_mode:", "bad_dispatch_block:", "stage_", "native_n8n_no_stage", "scheduler_",
    "no_allowlist_live_arg", "not_dispatch_eligible:", "dispatch_not_live", "class_not_admitted:",
    "registry_state_",
)


def _row(**over: object) -> dict:
    row: dict = {"lane_id": LANE, "state": "ACTIVE", "scheduler": {"kind": "n8n", "expression": "dispatcher",
                                                                  "stage": "canary"},
                 "dispatch": {"mode": "live", "class": "hygiene", "retry_policy": "transient-2"}}
    for key, value in over.items():
        if key in ("kind", "stage", "expression"):
            row["scheduler"][key] = value
        elif key == "dispatch":
            row["dispatch"] = value
        else:
            row[key] = value
    return row


def _allow(live_arg: list[str] | None = LIVE_ARG) -> dict:
    return {"lanes": [{"lane_id": LANE, "live_arg": live_arg, "dry_run_arg": ["--dry-run"]}]}


def _call(row: dict, allow: dict | None = None) -> tuple[list[str], dict[str, str]]:
    return RLL.registry_live_lanes({"lanes": [row]}, allow if allow is not None else _allow())


# ---------------------------------------------------------------- the silent classes, now named


def test_a_dry_run_dispatch_block_is_named_not_silent():
    """The LQ-716 class: stage shadow + dispatch.mode dry_run used to drop with excluded == {}."""
    lanes, excluded = _call(_row(stage="shadow", dispatch={"mode": "dry_run"}))
    assert lanes == []
    assert excluded == {LANE: "dispatch_mode:dry_run"}


def test_an_off_dispatch_block_is_named():
    _lanes, excluded = _call(_row(dispatch={"mode": "off"}))
    assert excluded == {LANE: "dispatch_mode:off"}


def test_a_dispatch_block_without_a_mode_is_named_unset():
    _lanes, excluded = _call(_row(dispatch={"class": "hygiene"}))
    assert excluded == {LANE: "dispatch_mode:unset"}


def test_a_dispatch_block_that_is_not_a_mapping_is_named():
    _lanes, excluded = _call(_row(dispatch="live"))
    assert excluded == {LANE: "bad_dispatch_block:not_mapping"}


def test_a_native_n8n_row_with_no_stage_is_named_without_a_live_arg():
    """Was silent unless the row was ACTIVE *and* had a live_arg; now every such row is named."""
    _lanes, excluded = _call(_row(kind="n8n", stage=None, dispatch=None), _allow(None))
    assert excluded == {LANE: "native_n8n_no_stage"}


@pytest.mark.parametrize("state", ["RETIRED", "PAUSED", "NEVER_SCHEDULED"])
def test_a_non_active_state_is_the_named_reason(state):
    """A retired/paused row is not live because of its state, whatever its stage says; the display reads it so."""
    _lanes, excluded = _call(_row(state=state, stage=None, dispatch=None), _allow(None))
    assert excluded == {LANE: f"registry_state_{state}"}


def test_a_native_n8n_row_with_a_shadow_stage_is_named():
    _lanes, excluded = _call(_row(kind="n8n", stage="shadow", dispatch=None))
    assert excluded == {LANE: "stage_shadow"}


@pytest.mark.parametrize("kind", ["cron", "systemd", "none"])
def test_a_non_n8n_scheduler_carrying_a_live_arg_is_named(kind):
    _lanes, excluded = _call(_row(kind=kind, stage=None, dispatch=None))
    assert excluded == {LANE: f"scheduler_{kind}_not_n8n"}


# ---------------------------------------------------------------- the negative control: no claim, no entry


def test_a_row_with_no_live_claim_is_not_named():
    """A cron row with no stage, no dispatch block and no live argv is not a relay candidate at all."""
    lanes, excluded = _call(_row(kind="cron", stage=None, dispatch=None), _allow(None))
    assert lanes == [] and excluded == {}


# ---------------------------------------------------------------- the real registry


def _real() -> tuple[dict, dict]:
    return (json.loads((ROOT / RLL.REGISTRY_REL).read_text(encoding="utf-8")),
            json.loads((ROOT / RLL.ALLOWLIST_REL).read_text(encoding="utf-8")))


def test_every_claimed_row_in_the_real_registry_is_live_or_named():
    registry, allowlist = _real()
    live, excluded = RLL.registry_live_lanes(registry, allowlist)
    entries = {e["lane_id"]: e for e in allowlist["lanes"]
               if isinstance(e, dict) and isinstance(e.get("lane_id"), str)}
    silent: list[str] = []
    for row in registry["lanes"]:
        if not isinstance(row, dict) or not isinstance(row.get("lane_id"), str):
            continue
        lane = row["lane_id"]
        sched = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
        claim = (row.get("dispatch") is not None or sched.get("stage") is not None
                 or sched.get("kind") == "n8n" or (entries.get(lane) or {}).get("live_arg") is not None)
        if claim and lane not in live and lane not in excluded:
            silent.append(lane)
    assert silent == [], f"dropped with no reason: {silent[:10]} ({len(silent)} rows)"
    assert live and excluded, "the real registry has both live lanes and refused candidates"
    for lane, why in excluded.items():
        assert lane not in live
        assert isinstance(why, str) and why.startswith(PREFIXES), (lane, why)


def test_the_lq716_lane_is_still_live_and_not_excluded():
    registry, allowlist = _real()
    live, excluded = RLL.registry_live_lanes(registry, allowlist)
    assert "jsonl-archive-rotate" in live and "jsonl-archive-rotate" not in excluded


def test_render_persists_the_reasons(tmp_path):
    """The reason reaches the artifact the relay and the deploy gate read, not only the function's return."""
    root = tmp_path / "release"
    (root / "config").mkdir(parents=True)
    registry, allowlist = _real()
    lane = next(r["lane_id"] for r in registry["lanes"]
                if r.get("state") == "ACTIVE" and isinstance(r.get("dispatch"), dict)
                and r["dispatch"].get("mode") == "dry_run")
    # nosemgrep: tq-py-nonatomic-store-write -- synthetic registry/allowlist fixtures under pytest tmp_path, not a store
    (root / RLL.REGISTRY_REL).write_text(json.dumps(registry), encoding="utf-8")
    (root / RLL.ALLOWLIST_REL).write_text(json.dumps(allowlist), encoding="utf-8")
    rep = RLL.render(root)
    assert rep["ok"] is True
    doc = json.loads((root / RLL.RENDER_NAME).read_text(encoding="utf-8"))
    assert doc["excluded"][lane] == "dispatch_mode:dry_run"
    assert lane not in doc["lanes"]


def test_render_copy_is_never_written_on_a_registry_error(tmp_path):
    """Unchanged contract: a bad registry renders nothing (no partial file), so no reason map is half-written."""
    root = tmp_path / "release"
    (root / "config").mkdir(parents=True)
    # nosemgrep: tq-py-nonatomic-store-write -- a malformed fixture under pytest tmp_path, not a store
    (root / RLL.REGISTRY_REL).write_text("{not json", encoding="utf-8")
    shutil.copyfile(ROOT / RLL.ALLOWLIST_REL, root / RLL.ALLOWLIST_REL)
    rep = RLL.render(root)
    assert rep["ok"] is False and not (root / RLL.RENDER_NAME).exists()
