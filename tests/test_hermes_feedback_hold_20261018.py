"""Preserve the unproven feedback hold through actual host admission/execution; fake effects only."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from scripts import n8n_run_executor as X
from scripts.lib import effect_claim as E, n8n_coordination_gateway as G, n8n_process_keys as PK
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore, LedgerNonceStore, LedgerReceiptStore

ROOT = Path(__file__).resolve().parents[1]
LANE = "hermes-learning-outcome-feedback-agent"
NOW = datetime(2026, 10, 19, 10, 57, tzinfo=ZoneInfo("America/New_York"))
HOST_KEY = b"fixture-host-not-a-live-key-0123456789"
RELAY_KEY = b"fixture-relay-not-a-live-key-9876543210"


def rows(rel, collection):
    return json.loads((ROOT / rel).read_text())[collection]


def test_feedback_default_config_retains_all_current_activation_holds():
    entry = next(x for x in rows("config/n8n_run_allowlist.json", "lanes") if x["lane_id"] == LANE)
    registry = next(x for x in rows("config/lane_registry.json", "lanes") if x["lane_id"] == LANE)
    health = next(x for x in rows("config/n8n_health_contracts.json", "contracts") if x["id"] == LANE)
    assert entry["live_arg"] is None, "unproven feedback must not acquire a live executable argv on release"
    assert registry["scheduler"]["stage"] == health["stage"] == "shadow", "registry and health must retain the hold"
    assert entry["dry_run_arg"] == ["--dry-run"] and entry.get("output_receipt") is None
    assert "registry stage canary" not in health["target_reason"]


def test_real_live_request_remains_effectively_dry_even_if_external_owner_gate_would_allow(tmp_path, monkeypatch):
    # An external owner/list cannot substitute for the explicitly held source stage.
    # No real owner, provider, database, service, grant, scheduler or state root is used.
    ledger = CoordinationLedger(tmp_path / "coordination.sqlite")
    try:
        runs = LedgerRunStore(ledger)
        fx = E.EffectClaimStore(ledger)
        fx.set_owner(LANE, "n8n", expect_epoch=None, by="hermetic-fixture", now=NOW.timestamp() - 300)
        run_id = f"p:{LANE}:live:20261019T1050"
        claim = {
            "v": 1,
            "caller_id": "n8n-relay",
            "project": "trade-ai",
            "iat": NOW.timestamp(),
            "exp": NOW.timestamp() + 120,
            "nonce": "fixture-feedback-hold-1",
            "scope": G.SCOPE_RUN,
        }
        request = {
            "route": "coordination/run",
            "operation": "run",
            "claim": claim,
            "signature": hmac.new(RELAY_KEY, G.canonical(claim), hashlib.sha256).hexdigest(),
            "lane_id": LANE,
            "mode": "live",
            "idempotency_key": run_id,
            "requested_by": "n8n:tradeai-fabric-hermes-learning",
        }
        admitted = G.handle_request(
            request,
            key=HOST_KEY,
            now=NOW,
            nonce_store=LedgerNonceStore(ledger),
            idempotency_store=LedgerReceiptStore(ledger),
            expected_origin_sha="a" * 40,
            caller_keys=G.build_caller_keys(HOST_KEY, n8n_key=RELAY_KEY),
            run_store=runs,
            run_allowlist=frozenset({LANE}),
            process_sources=PK.load_sources(),
        )
        assert admitted["state"] == "REQUESTED"
        row = runs.claim_next(now=NOW.timestamp() + 1)
        entry = copy.deepcopy(next(x for x in rows("config/n8n_run_allowlist.json", "lanes") if x["lane_id"] == LANE))
        entry["lock"] = str(tmp_path / "feedback.lock")
        gate = X.EffectGate(fx, {LANE: {"process": LANE, "input_version": "v1"}}, clock=lambda: NOW.timestamp() + 2)
        monkeypatch.setattr(X, "_offpeak_now", lambda: NOW)
        calls = []

        def runner(argv, **_kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        result = X.execute(
            row,
            entry,
            env={},
            state_root=tmp_path,
            code_root=ROOT,
            runner=runner,
            effects=gate,
            stage_rows=rows("config/lane_registry.json", "lanes"),
        )
        assert result["mode"] == "dry_run", "a live request must not bypass the feedback source hold"
        assert result["requested_mode"] == "live" and result["stage_clamp"]["reason"] == "stage_shadow"
        assert len(calls) == 1 and "--dry-run" in calls[0] and "--apply" not in calls[0]
        assert "effect" not in result
        assert fx.get(E.effect_key(LANE, "20261019T1050", "v1")) is None
    finally:
        ledger.close()
