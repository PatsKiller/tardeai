"""Worker A carry-forward admission boundaries, without broker/model/host calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.lane_stage_clamp import clamp_mode
from scripts.lib.n8n_health_contracts import validate_contract
from scripts.lib.cron_schedule import parse

ROOT = Path(__file__).resolve().parents[1]
LANES = (
    "holdings-drift-monitor", "options-desk-staleness-monitor", "held-exit-coverage-monitor",
    "options-desk-quote-refresh", "cio-ask-research", "jsonl-archive-rotate",
)
NATIVE = tuple(x for x in LANES if x != "options-desk-quote-refresh")


def documents():
    return tuple(json.loads((ROOT / "config" / name).read_text()) for name in
        ("lane_registry.json", "n8n_run_allowlist.json", "n8n_health_contracts.json"))


@pytest.mark.parametrize("lane", NATIVE)
def test_both_requested_modes_clamp_to_shadow_and_command_has_no_live_argv(lane):
    registry, allowlist, _ = documents()
    rows = registry["lanes"]
    row = next(x for x in rows if x["lane_id"] == lane)
    entry = next(x for x in allowlist["lanes"] if x["lane_id"] == lane)
    assert row["scheduler"]["kind"] == "n8n"
    assert row["scheduler"]["expression"] == "dispatcher"
    assert row["scheduler"]["stage"] == "shadow" and row["dispatch"]["mode"] == "dry_run"
    assert row["dispatch"]["tz"] == "America/New_York"
    for expression in row["dispatch"]["cron"]:
        parse(expression)
    assert entry["dry_run_arg"] == ["--dry-run"] and entry["live_arg"] is None
    for requested in ("live", "dry_run"):
        assert clamp_mode(lane, requested, rows)["effective_mode"] == "dry_run"
    assert row["output_signal"]["path"] == entry["output_signal"]


def test_quote_refresh_is_inert_even_with_its_shadow_candidate():
    registry, allowlist, _ = documents()
    row = next(x for x in registry["lanes"] if x["lane_id"] == "options-desk-quote-refresh")
    assert row["state"] == "NEVER_SCHEDULED" and row["scheduler"]["kind"] == "none"
    assert not row.get("dispatch")
    assert "options-desk-quote-refresh" not in {x["lane_id"] for x in allowlist["lanes"]}
    pending = row["f09_staged"]
    assert pending["activation_registry"]["scheduler"]["stage"] == "shadow"
    assert pending["activation_allowlist_entry"]["live_arg"] is None
    assert "NOT RATIFIED" not in str(pending["gated_on"])


@pytest.mark.parametrize("lane", LANES)
def test_six_contracts_are_valid_and_review_provenance_is_explicit(lane):
    _, _, contracts = documents()
    contract = next(x for x in contracts["contracts"] if x["id"] == lane)
    assert validate_contract(contract) == []
    assert contract["status"] == "REVIEWED" and contract["review"]["status"] == "REVIEWED"
    assert "operator" in contract["review"]["reviewed_by"].lower()
    assert contract["review"]["reviewed_on"] == "2026-10-24"
    if lane == "jsonl-archive-rotate":
        assert "legacy-pr-carryforward.md" in json.dumps(contract["review"])


def test_recent_main_rows_survive_and_there_are_no_duplicate_identities():
    registry, allowlist, contracts = documents()
    for doc, section, key in ((registry, "lanes", "lane_id"), (allowlist, "lanes", "lane_id"),
                              (contracts, "contracts", "id")):
        ids = [x[key] for x in doc[section]]
        assert len(ids) == len(set(ids))
    ids = {x["lane_id"] for x in registry["lanes"]}
    assert {"cio-prospect-shadow", "cio-company-facts-populate", *LANES} <= ids


def test_new_manual_rows_precede_generated_suffix_and_registry_is_canonical_utf8():
    from scripts.reconcile_lane_registry import GENERATOR_VERSION, dump_registry
    path = ROOT / "config/lane_registry.json"
    registry = json.loads(path.read_text())
    assert path.read_text() == dump_registry(registry)
    generated_at = next(i for i, row in enumerate(registry["lanes"])
                        if row.get("generated_by") == GENERATOR_VERSION)
    assert all(i < generated_at for i, row in enumerate(registry["lanes"]) if row["lane_id"] in LANES)
    assert "\\u" not in path.read_text()


def test_shadow_archive_has_no_removal_authority():
    rules = json.loads((ROOT / "config/disk_hygiene_rules.json").read_text())
    assert rules["jsonl_retention"]["enabled"] is False
    _, allowlist, _ = documents()
    entry = next(x for x in allowlist["lanes"] if x["lane_id"] == "jsonl-archive-rotate")
    assert entry["live_arg"] is None and "--apply" not in entry["command"]
