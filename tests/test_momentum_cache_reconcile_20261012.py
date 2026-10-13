"""Derived-cache repair boundary: isolated source/state only, no provider or canonical writes."""

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts import momentum_cache_reconcile as repair
from scripts.lib import n8n_momentum_lifecycle as lifecycle

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
NOW = datetime.fromisoformat("2026-10-12T10:20:00+00:00")


@pytest.fixture
def setup(tmp_path):
    code = tmp_path / "code"
    state = tmp_path / "state"
    (code / "config").mkdir(parents=True)
    (state / "data/runtime").mkdir(parents=True)
    (state / "data/active_trader").mkdir(parents=True)
    (code / "SOURCE_COMMIT").write_text(SHA)
    path = ROOT / "docs/implementation/n8n-maturity/reconciliation-20261012/MOMENTUM_HEALTH_CONTRACT_PROPOSALS.json"
    contract = copy.deepcopy(next(c for c in json.loads(path.read_text())["contracts"] if c["id"] == repair.LANE))
    contract["baseline"].update(timeout_s=60, freshness_degraded_after_h=0.167, freshness_failed_after_h=0.25)
    contract.update(id=repair.LANE, status="REVIEWED", owner="fixture-owner", ownership_confirmation="OWNER_ACCEPTED")
    contract["review"] = {"reviewed_by": "fixture-owner", "decision_ref": "fixture://actual-test-decision"}
    contract["review"]["contract_body_sha256"] = lifecycle.contract_body_digest(contract)
    config = {
        "lane_registry": {
            "lanes": [
                {
                    "lane_id": repair.LANE,
                    "state": "ACTIVE",
                    "scheduler": {"stage": "cutover"},
                    "dispatch": {"class": "report", "retry_policy": "none"},
                }
            ]
        },
        "n8n_health_contracts": {"contracts": [contract]},
        "n8n_run_allowlist": {
            "lanes": {
                repair.LANE: {"live_arg": ["--apply"], "lock_kind": "flock", "lock": "/fixture/shared-projection.lock"}
            }
        },
        "n8n_momentum_lifecycle_candidate": {"enabled": True, "recovery": {"armed": True}},
    }
    for name, doc in config.items():
        (code / f"config/{name}.json").write_text(json.dumps(doc))
    (code / "config/n8n_retry_policies.json").write_bytes((ROOT / "config/n8n_retry_policies.json").read_bytes())
    cache = {
        "run_id": "2026-10-09::1730",
        "run_date": "2026-10-09",
        "stale": True,
        "setup_run_summary": {"run_id": "2026-10-09::1730", "run_date": "2026-10-09", "scanned_count": 44},
        "tickers": [{"symbol": "ABC", "decision": "GO", "run_id": "2026-10-09::1730"}],
    }
    (state / "data/runtime/trade_ai_cache.json").write_text(json.dumps(cache))
    (state / "data/active_trader/momentum_alerts.jsonl").write_text("")
    return code, state


def test_dry_run_never_writes_or_refreshes_canonical_business_identity(setup):
    code, state = setup
    source = state / "data/runtime/trade_ai_cache.json"
    before = source.read_bytes()
    result = repair.reconcile(code_root=code, state_root=state, now=NOW)
    assert result["status"] == "ok" and result["reason"] == "would_reconcile_derived_projection"
    assert result["projection"]["run_date"] == "2026-10-09"
    assert result["projection"]["source_sha"] == "UNKNOWN"
    assert not (state / repair.PROJECTION_REL).exists()
    assert not (state / repair.RECEIPT_REL).exists() and source.read_bytes() == before


@pytest.mark.parametrize("stage", ["canary", "cutover"])
def test_approved_apply_updates_only_resettable_derivative_and_own_receipt(setup, stage):
    code, state = setup
    registry_path = code / "config/lane_registry.json"
    registry = json.loads(registry_path.read_text())
    registry["lanes"][0]["scheduler"]["stage"] = stage
    registry_path.write_text(json.dumps(registry))
    cache = state / "data/runtime/trade_ai_cache.json"
    journal = state / "data/active_trader/momentum_alerts.jsonl"
    originals = cache.read_bytes(), journal.read_bytes()
    result = repair.reconcile(code_root=code, state_root=state, now=NOW, apply=True)
    projected = json.loads((state / repair.PROJECTION_REL).read_text())
    assert result["status"] == "ok" and result["canonical_business_writes"] == 0
    assert result["execution_stage"] == stage
    assert result["provider_calls"] == 0 and result["business_acceptance"] == "NOT_MEASURED"
    assert projected["run_date"] == "2026-10-09" and projected["source_sha"] == "UNKNOWN"
    assert projected["candidates"][0]["classification"] == "STALE"
    assert projected["candidates"][0]["execution_authority"] == "NONE"
    assert (cache.read_bytes(), journal.read_bytes()) == originals
    before = (state / repair.PROJECTION_REL).read_bytes()
    again = repair.reconcile(code_root=code, state_root=state, now=NOW, apply=True)
    assert again["reason"] == "derived_projection_already_consistent"
    assert (state / repair.PROJECTION_REL).read_bytes() == before


@pytest.mark.parametrize(
    "change",
    [
        "disarmed",
        "disabled",
        "draft",
        "wrong_digest",
        "no_decision",
        "missing_owner",
        "protected_class",
        "shadow",
        "paused",
        "wrong_lane",
        "missing_live_arg",
        "missing_lock",
        "wrong_lock_kind",
    ],
)
@pytest.mark.parametrize("stage", ["canary", "cutover"])
def test_apply_refuses_unreviewed_or_protected_operation_without_writes(setup, change, stage):
    code, state = setup
    registry_path = code / "config/lane_registry.json"
    registry = json.loads(registry_path.read_text())
    registry["lanes"][0]["scheduler"]["stage"] = stage
    registry_path.write_text(json.dumps(registry))
    if change in {"disarmed", "disabled"}:
        p = code / "config/n8n_momentum_lifecycle_candidate.json"
        doc = json.loads(p.read_text())
        if change == "disarmed":
            doc["recovery"]["armed"] = False
        else:
            doc["enabled"] = False
    elif change in {"protected_class", "shadow", "paused", "wrong_lane"}:
        p = code / "config/lane_registry.json"
        doc = json.loads(p.read_text())
        row = doc["lanes"][0]
        if change == "protected_class":
            row["dispatch"]["class"] = "send"
        elif change == "shadow":
            row["scheduler"]["stage"] = "shadow"
        elif change == "paused":
            row["state"] = "PAUSED"
        else:
            row["lane_id"] = "other-cache-lane"
    elif change in {"missing_live_arg", "missing_lock", "wrong_lock_kind"}:
        p = code / "config/n8n_run_allowlist.json"
        doc = json.loads(p.read_text())
        row = doc["lanes"][repair.LANE]
        if change == "missing_live_arg":
            row["live_arg"] = None
        elif change == "missing_lock":
            row["lock"] = None
        else:
            row["lock_kind"] = "none"
    else:
        p = code / "config/n8n_health_contracts.json"
        doc = json.loads(p.read_text())
        contract = doc["contracts"][0]
        if change == "draft":
            contract["status"] = "DRAFT"
        elif change == "wrong_digest":
            contract["purpose"]["text"] += " unreviewed change"
        elif change == "missing_owner":
            contract.pop("ownership_confirmation")
            # A matching digest cannot manufacture owner confirmation.
            contract["review"]["contract_body_sha256"] = lifecycle.contract_body_digest(contract)
        else:
            contract["review"]["decision_ref"] = None
    p.write_text(json.dumps(doc))
    result = repair.reconcile(code_root=code, state_root=state, now=NOW, apply=True)
    assert result["reason"] == "operative_recovery_admission_unproven"
    assert not (state / repair.PROJECTION_REL).exists() and not (state / repair.RECEIPT_REL).exists()


def test_missing_sources_are_not_empty_success_or_generated_business_proof(setup):
    code, state = setup
    (state / "data/runtime/trade_ai_cache.json").unlink()
    (state / "data/active_trader/momentum_alerts.jsonl").unlink()
    result = repair.reconcile(code_root=code, state_root=state, now=NOW, apply=True)
    assert result["status"] == "REFUSED" and result["reason"] == "owner_inputs_not_measured"
    assert not (state / repair.PROJECTION_REL).exists()
