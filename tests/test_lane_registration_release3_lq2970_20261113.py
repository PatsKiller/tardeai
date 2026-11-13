"""LANE_REGISTRATION_RELEASE3_LQ2970_20261113 - release-3 lane registration and promotion.

LQ-20261107-2970. Registration is not execution. This file pins what the release-3 order did to the committed
config, and what it deliberately did not do:

* lane-health-snapshot, validation-gates-sync and validation-gate-declare are canary / dispatch live, and their
  live fire is ``--apply``. Each has a REVIEWED health contract at the same stage, and the dispatcher admits it.
* cio-persistent-wake stays shadow / dry_run. The lead promotes it after the bounded canary.
* stop-coverage-incidents is NOT a plain n8n row. The dispatcher's token rail refuses any lane id containing
  ``stop``, and a ``live`` dispatch block cannot override that. Registering it is an operator/lead decision.

It reads only committed config. No DB, no network, no fire.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402

TZ = "America/New_York"
REG = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
ALLOW = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text(encoding="utf-8"))
HEALTH = json.loads((ROOT / "config/n8n_health_contracts.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REG["lanes"]}
ENTRIES = {e["lane_id"]: e for e in ALLOW["lanes"]}
CONTRACTS = {c["id"]: c for c in HEALTH["contracts"]}

# lane_id -> (script, cron, wave, dry argv, live argv)
PROMOTED = {
    "lane-health-snapshot": ("scripts/lane_health_snapshot.py", "*/10 * * * *", "W1", ["--dry-run"], ["--apply"]),
    "validation-gates-sync": ("scripts/validation_gates_sync.py", "*/5 * * * *", "W5", [], ["--apply"]),
    "validation-gate-declare": ("scripts/validation_gate_declare.py", "7 * * * *", "W5", [], ["--apply"]),
}


@pytest.mark.parametrize("lane_id", sorted(PROMOTED))
def test_promoted_lane_is_a_live_canary_dispatcher_row(lane_id):
    script, cron, wave, _dry, _live = PROMOTED[lane_id]
    row = ROWS[lane_id]
    s, d = row["scheduler"], row["dispatch"]
    assert (s["kind"], s["expression"], s["stage"], s["timezone"]) == ("n8n", "dispatcher", "canary", TZ)
    assert script in s["match"]
    assert s["cadence"] == cron and d["cron"] == [cron] and d["tz"] == TZ
    assert s["wave"] == d["wave"] == wave
    assert d["mode"] == "live"
    assert (ROOT / script).is_file()


@pytest.mark.parametrize("lane_id", sorted(PROMOTED))
def test_promoted_lane_allowlist_fires_apply_live_and_never_dry(lane_id):
    script, _cron, _wave, dry, live = PROMOTED[lane_id]
    e = ENTRIES[lane_id]
    assert e["command"] == ["$PY", script]
    assert e["dry_run_arg"] == dry and e["live_arg"] == live
    assert "--apply" not in e["dry_run_arg"]
    assert e["lock_kind"] == "flock" and e["lock"].startswith("/tmp/")
    assert e["market_gate"] is False


@pytest.mark.parametrize("lane_id", sorted(PROMOTED))
def test_promoted_lane_is_admitted_by_the_dispatcher(lane_id):
    eligible, reason = LD.dispatch_eligible(ROWS[lane_id])
    assert eligible is True, reason


@pytest.mark.parametrize("lane_id", sorted(PROMOTED))
def test_promoted_lane_has_a_reviewed_contract_at_its_stage(lane_id):
    c = CONTRACTS[lane_id]
    assert c["status"] == "REVIEWED" and c["review"]["status"] == "REVIEWED"
    assert c["stage"] == ROWS[lane_id]["scheduler"]["stage"] == "canary"
    assert c["review"].get("reviewed_on")
    assert "expected_output" in c


def test_lock_files_are_distinct_across_the_promoted_lanes():
    locks = [ENTRIES[k]["lock"] for k in PROMOTED]
    assert len(set(locks)) == len(locks)


def test_contract_gate_reports_no_error_for_the_release3_lanes():
    res = H.check(H.load_json(H.CONTRACTS_PATH), H.load_json(H.REGISTRY_PATH), H.load_json(H.GENERIC_INDEX_PATH),
                  today=date(2026, 11, 13))
    mine = [e for e in res["errors"] if any(k in e for k in (*PROMOTED, "cio-persistent-wake"))]
    assert mine == []


def test_lane_health_freshness_contract_names_the_monitor_it_replaces():
    fc = {f["key"]: f for f in REG["freshness_contracts"]}["ops.lane_health_current"]
    assert fc["lane_id"] == "lane-health-snapshot"
    assert fc["replaces"] == ["pipeline-freshness-monitor"]


def test_cio_persistent_wake_stays_shadow_dry_run():
    row = ROWS["cio-persistent-wake"]
    assert row["scheduler"]["stage"] == "shadow"
    assert row["dispatch"]["mode"] == "dry_run"
    assert CONTRACTS["cio-persistent-wake"]["stage"] == "shadow"


@pytest.mark.parametrize("lane_id", ["stop-coverage-incidents", "stop-coverage-incidents-offhours"])
def test_stop_coverage_cannot_be_a_plain_n8n_row(lane_id):
    """A synthetic row shaped like the requested lane, live dispatch included, is still refused by the token rail."""
    row = {
        "lane_id": lane_id,
        "scheduler": {"kind": "n8n", "expression": "dispatcher", "match": "scripts/stop_coverage_incidents.py --apply",
                      "cadence": "*/5 9-16 * * 1-5", "stage": "canary", "timezone": TZ},
        "dispatch": {"mode": "live", "cron": ["*/5 9-16 * * 1-5"], "tz": TZ},
    }
    eligible, reason = LD.dispatch_eligible(row)
    assert eligible is False
    assert reason.startswith("forbidden_token:stop")


def test_stop_coverage_is_not_plain_registered():
    for lane_id in ("stop-coverage-incidents", "stop-coverage-incidents-offhours"):
        # Registering it (LQ-2276 exemption path or a cron row) is an operator/lead decision; update this pin then.
        assert lane_id not in ENTRIES and lane_id not in ROWS
