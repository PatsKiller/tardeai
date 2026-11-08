"""LQ-20261107-361: every relay-live lane is either keyed (declares its owned effect) or on the audited-unkeyed baseline.

A keyed lane needs an effect_owners row (effect_claim.py set-owner, seeded by the W5 packet) before its n8n claim is
admitted; a relay-live lane with no key has no owner at all and its cron line races the n8n run for the flock. Seven
lanes were in that state on 2026-11-07. This test keeps the set from growing back: a newly relay-live lane must be keyed
in config/n8n_effect_keys.json or named, with a reason, in UNKEYED_BASELINE.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.lib import n8n_relay_live_lanes as RLL
from scripts.lib.effect_claim import load_effect_lanes

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "docs/ops/packets/n8n-cutover-wave-w5-20261107/02_effect_owners.sh"

LQ361_LANES = (
    "reconcile-exit-advisory-outcomes",
    "reconcile-watch-outcomes",
    "tmp-scratch-cleanup",
    "active-trader-session-review",
    "fee-efficiency-analyzer",
    "overnight-batch-tax",
    "ask-alerts",
)

# LQ-20261107-508: the two lanes LQ-479 took live (scheduler.stage canary + dispatch.mode live) with no key. They ship
# staged like the LQ-361 seven — the key exists and declares the effect, neither runner claims until a cutover arms it.
LQ508_LANES = (
    "market-event-outcomes",
    "market-reference-bars",
)

# Relay-live lanes with no effect key at 2026-11-07. Baseline only: not individually audited by LQ-361. Remove a lane
# from this list when it is keyed; never add one (key it instead). Read-only / overwrite-only lanes are unkeyed by the
# canary-key convention in config/n8n_effect_keys.json (_comment_canary_keys).
UNKEYED_BASELINE = frozenset(
{
    "active-trader-motion-watchdog",
    "build-hermes-canonical-status",
    "catalyst-graph",
    "cio-prospect-shadow",
    "classify-instruments",
    "crontab-snapshot-for-health-agent",
    "disk-hygiene",
    "disk-usage-monitor",
    "finviz-enrichment",
    "finviz-sector-research",
    "hermes-discovery-scorecard",
    "hermes-governance-api",
    "identity-sweep-stage0",
    "job-coverage-monitor",
    "macro-calendar-refresh",
    "materialize-watchlist-strategy-cards",
    "n8n-comms-intent-consumer",
    "n8n-data-plausibility-audit",
    "n8n-gap-resolution-audit",
    "opening-intelligence-render",
    "pr-hygiene-audit",
    "prospectus-build",
    "registry-runtime-truth",
    "sync-social-to-intelligence",
    "tmp-hygiene",
}
)


def _relay_live() -> set[str]:
    reg = json.loads((ROOT / RLL.REGISTRY_REL).read_text(encoding="utf-8"))
    al = json.loads((ROOT / RLL.ALLOWLIST_REL).read_text(encoding="utf-8"))
    lanes, _excluded = RLL.registry_live_lanes(reg, al)
    return set(lanes)


def _unkeyed(live: set[str], keyed: set[str], baseline: frozenset[str] = UNKEYED_BASELINE) -> list[str]:
    """The guard's one predicate: live lanes that declare no effect and are not on the audited baseline."""
    return sorted(set(live) - set(keyed) - set(baseline))


#: Every live lane at collection time, so the guard is ONE TEST PER LANE. A single assertion over the whole set kept
#: the count flat when LQ-479 took two lanes live unkeyed (the message grew, "1 failed" did not), which is how the
#: fold called it green. A new unkeyed lane now adds a failing test whose name is the lane.
LIVE_LANES = sorted(_relay_live())


@pytest.mark.parametrize("lane", LIVE_LANES)
def test_every_relay_live_lane_is_keyed_or_on_the_unkeyed_baseline(lane):
    keyed = set(load_effect_lanes())
    assert lane in keyed or lane in UNKEYED_BASELINE, (
        f"relay-live lane {lane} has no effect key and is not on UNKEYED_BASELINE: key it (staged) in "
        f"config/n8n_effect_keys.json instead of adding a baseline name"
    )


def test_the_guard_reports_a_new_unkeyed_live_lane_by_name():
    """Negative control: the predicate above fails for a lane that goes live unkeyed, and only for that lane."""
    live = {"keyed-lane", "baselined-lane", "new-unkeyed-lane"}
    assert _unkeyed(live, {"keyed-lane"}, frozenset({"baselined-lane"})) == ["new-unkeyed-lane"]
    assert _unkeyed(live, {"keyed-lane", "new-unkeyed-lane"}, frozenset({"baselined-lane"})) == []
    assert _unkeyed(set(), set()) == []


def test_the_baseline_only_shrinks():
    keyed = set(load_effect_lanes())
    live = _relay_live()
    assert not (UNKEYED_BASELINE & keyed), "keyed lanes must leave UNKEYED_BASELINE"
    assert not (UNKEYED_BASELINE - live), "baseline names a lane that is not relay-live"


def test_the_seven_lq361_lanes_declare_an_effect_and_are_seeded():
    cfg = json.loads((ROOT / "config/n8n_effect_keys.json").read_text(encoding="utf-8"))["lanes"]
    seed = SEED.read_text(encoding="utf-8")
    loop = re.search(r"for lane in ([^;]+); do", seed).group(1).split()
    live = _relay_live()
    for lane in LQ361_LANES:
        assert lane in live
        spec = cfg[lane]
        assert spec["process"] == lane and spec["effects"], lane
        assert spec["n8n_claim"] is False and spec["cron_claim"] is False, f"{lane} must ship staged"
        assert lane in loop, f"{lane} missing from the owner seed loop"


def test_staged_keys_change_no_executor_behaviour():
    from scripts.lib.effect_claim import load_effect_config

    armed = load_effect_config()
    assert not (set(LQ361_LANES) & set(armed))


def test_the_lq479_lanes_declare_an_effect_and_are_seeded():
    """LQ-20261107-508: the two lanes LQ-479 takes live carry a staged key and an owner seed, like the LQ-361 seven."""
    cfg = json.loads((ROOT / "config/n8n_effect_keys.json").read_text(encoding="utf-8"))["lanes"]
    seed = SEED.read_text(encoding="utf-8")
    loop = re.search(r"for lane in ([^;]+); do", seed).group(1).split()
    live = _relay_live()
    for lane in LQ508_LANES:
        assert lane in live
        spec = cfg[lane]
        assert spec["process"] == lane and spec["effects"] == ["append"], lane
        assert spec["n8n_claim"] is False and spec["cron_claim"] is False, f"{lane} must ship staged"
        assert lane in loop, f"{lane} missing from the owner seed loop"

    from scripts.lib.effect_claim import load_effect_config

    assert not (set(LQ508_LANES) & set(load_effect_config()))
