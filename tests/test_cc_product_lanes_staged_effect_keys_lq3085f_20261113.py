"""LQ-20261113-3085f: the five lanes LQ-3096 promotes to the n8n relay carry STAGED effect keys.

LQ-3096 moved cc-product-{analyst-links,home,market-risk,risk} and cio-pages-product to scheduler stage ``canary``,
which puts them in the canary double-effect audit's scope (tests/test_canary_effect_keys_20261015.py). Every live
run of these builders appends one ``cc_product_build_log`` audit row (OK, UNCHANGED, SKIPPED_BUSY, FAILED, REFUSED;
scripts/lib/cc_products/product_builder.py, cio_pages.py), so they are not overwrite-only: the audit requires a key.

The keys are STAGED: cron_claim false and n8n_claim false. The executor's view (load_effect_config) skips them and
process_armed is False, so no live run changes behaviour. Arming them is a separate, reviewed cutover step.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib import effect_claim as E

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "n8n_effect_keys.json"
REGISTRY = ROOT / "config" / "lane_registry.json"

LANES = (
    "cc-product-analyst-links",
    "cc-product-home",
    "cc-product-market-risk",
    "cc-product-risk",
    "cio-pages-product",
)


def _raw() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))["lanes"]


def _registry() -> dict:
    return {r["lane_id"]: r for r in json.loads(REGISTRY.read_text(encoding="utf-8"))["lanes"]}


@pytest.mark.parametrize("lane", LANES)
def test_lane_has_a_staged_append_key(lane):
    spec = _raw().get(lane)
    assert spec is not None, f"{lane} is canary and appends cc_product_build_log rows: it needs a staged effect key"
    assert spec["process"] == lane and spec["input_version"] == "v1"
    assert spec["cron_claim"] is False and spec["n8n_claim"] is False
    assert spec["effects"] == ["append"]  # no LLM, no send
    assert spec["slot"] == "scheduled_minute" and spec["slot_tz"] == "America/New_York"
    assert spec["idempotent_today"].startswith("no:")


@pytest.mark.parametrize("lane", LANES)
def test_key_schedule_is_the_dispatch_schedule(lane):
    row = _registry()[lane]
    crons = row["dispatch"]["cron"]
    sched = _raw()[lane]["schedule"]
    assert ([sched] if isinstance(sched, str) else sched) == crons
    assert row["scheduler"]["stage"] == "canary"


@pytest.mark.parametrize("lane", LANES)
def test_staged_key_arms_nothing(lane):
    assert lane in E.load_effect_lanes(CONFIG)
    assert lane not in E.load_effect_config(CONFIG)
    assert E.process_armed(lane, CONFIG) is False
