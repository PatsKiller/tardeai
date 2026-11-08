"""LQ-20261107-1122: the market-outlook-weekly registry row and health contract land together.

Shipped with the registry patch (config/lane_registry.json was claimed elsewhere at commit time): a contract
without its registry row is an ORPHAN_CONTRACT, so the two rows and this pin are one unit.
"""
from __future__ import annotations

import json
from pathlib import Path

import scripts.market_outlook_lane as lane

ROOT = Path(__file__).resolve().parents[1]
LANE = "market-outlook-weekly"
CRON = ["0 20 * * 0", "0 7 * * 1"]


def _load(rel):
    return json.loads((ROOT / rel).read_text())


def test_the_registry_dispatches_sunday_20_and_monday_07_new_york():
    rows = [r for r in _load("config/lane_registry.json")["lanes"] if r["lane_id"] == LANE]
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "ACTIVE" and row["expected_cadence_hours"] == 168
    assert row["scheduler"]["kind"] == "n8n" and row["scheduler"]["expression"] == "dispatcher"
    assert row["scheduler"]["stage"] == "canary" and row["scheduler"]["match"] == lane.SCRIPT_REL
    d = row["dispatch"]
    assert d["mode"] == "live" and d["cron"] == CRON and d["tz"] == "America/New_York"
    assert row["output_signal"]["path"] == lane.RECEIPT_REL


def test_the_contract_is_reviewed_canary_and_matches_the_allowlist_and_registry():
    contracts = [c for c in _load("config/n8n_health_contracts.json")["contracts"] if c["id"] == LANE]
    assert len(contracts) == 1
    c = contracts[0]
    assert c["status"] == "REVIEWED" and c["stage"] == "canary"
    allow = [r for r in _load("config/n8n_run_allowlist.json")["lanes"] if r["lane_id"] == LANE][0]
    assert c["baseline"]["timeout_s"] == allow["timeout_s"]
    assert c["evidence"]["receipt"] == lane.RECEIPT_REL
    effect = _load("config/n8n_effect_keys.json")["lanes"][LANE]
    assert effect["schedule"] == CRON
