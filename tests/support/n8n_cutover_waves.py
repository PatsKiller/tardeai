"""Lanes promoted by the 2026-10-15 n8n cutover waves (scripts/n8n_cutover_wave.py).

Older wave tests pin rows at shadow (dispatch.mode dry_run, allowlist live_arg null). A cutover wave moves a lane on to
canary (and its next PR to cutover); those tests read this module so the pin follows the lane instead of being
deleted. The source of truth is each wave packet's lanes.json (docs/ops/packets/n8n-cutover-wave-<n>-20261015/).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKETS = sorted((ROOT / "docs" / "ops" / "packets").glob("n8n-cutover-wave-*-20261015/lanes.json"))


def _load() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in PACKETS:
        doc = json.loads(p.read_text(encoding="utf-8"))
        plan = {v["lane_id"]: v for v in doc.get("plan") or []}
        for lane in doc.get("ready") or []:
            out[lane] = {"wave": doc.get("wave"), "keyed": lane in set(doc.get("effect_keyed") or []), **plan.get(lane, {})}
    return out


WAVES = _load()
PROMOTED = frozenset(WAVES)
#: Lanes whose effect key a wave ARMED (n8n_claim + cron_claim true).
ARMED = frozenset(k for k, v in WAVES.items() if v.get("keyed"))


def live_arg(lane: str, default=None):
    """The allowlist live_arg a wave wrote for `lane` (the cron line's argv), else `default`."""
    v = WAVES.get(lane)
    return v.get("live_arg") if v is not None else default
