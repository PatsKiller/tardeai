"""The host-validated ``rtw:`` run-key namespace for the release-train request lanes (operator 2026-10-21, "rtw yes").

``rtw:<slot>:<window date YYYYMMDD>:<shadow|live>``: the gateway accepts it for a LIVE run only when the slot is the
lane's own and the date is the slot's CURRENT window date (scripts/lib/release_train_window_view.check_window_run_key).
One deterministic key per lane and window, so a repeat replays the same row. Hermetic: a tmp ledger, test HMAC keys.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import n8n_coordination_gateway as G
from scripts.lib import release_train_window_view as V
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerNonceStore, LedgerReceiptStore, LedgerRunStore

ROOT = Path(__file__).resolve().parents[1]
KEY = b"dispatch-key-not-a-live-secret-0123456"
N8N = b"relay-key-not-a-live-secret-9876543210"
SHA = "a" * 40
NOW = datetime(2026, 10, 21, 20, 30, tzinfo=timezone.utc)  # 16:30 EDT: the 18:00 window's request tick
NOW_0000 = datetime(2026, 10, 22, 2, 30, tzinfo=timezone.utc)  # 22:30 EDT Oct 21: the 00:00 window is Oct 22
LANES = frozenset(f"release-train-request-{s}" for s in ("1800", "0000", "0600", "0800"))
CFG = V.load_config()


def _claim(nonce: str, now: datetime) -> dict:
    claim = {"v": 1, "caller_id": G.RELAY_CALLER, "project": "trade-ai", "iat": now.timestamp(),
             "exp": now.timestamp() + 120, "nonce": "nonce-" + nonce, "scope": G.SCOPE_RUN}
    return {"claim": claim, "signature": hmac.new(N8N, G.canonical(claim), hashlib.sha256).hexdigest()}


@pytest.fixture
def stores(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield LedgerNonceStore(ledger), LedgerReceiptStore(ledger), LedgerRunStore(ledger)
    ledger.close()


def _run(stores, nonce: str, key: str, *, lane: str = "release-train-request-1800", mode: str = "live",
         now: datetime = NOW, requested_by: str = "n8n:tradeai-fabric-release-train") -> dict:
    nonces, receipts, runs = stores
    req = {**_claim(nonce, now), "route": "coordination/run", "operation": "run", "lane_id": lane, "mode": mode,
           "idempotency_key": key, "requested_by": requested_by}
    return G.handle_request(req, key=KEY, now=now, nonce_store=nonces, idempotency_store=receipts,
                            expected_origin_sha=SHA, caller_keys=G.build_caller_keys(KEY, n8n_key=N8N),
                            run_store=runs, run_allowlist=LANES)


def test_window_run_key_is_deterministic_and_uses_the_window_date():
    assert V.window_run_key("1800", NOW, CFG, "live") == "rtw:1800:20261021:live"
    assert V.window_run_key("0000", NOW_0000, CFG, "shadow") == "rtw:0000:20261022:shadow"
    assert V.window_run_key("1800", NOW, CFG, "live") == V.window_run_key("1800", NOW, CFG, "live")
    with pytest.raises(V.ContractError):
        V.window_run_key("1800", NOW, CFG, "dry_run")


@pytest.mark.parametrize("kind", ["live", "shadow"])
def test_valid_live_key_is_accepted_once_and_replays(stores, kind):
    key = f"rtw:1800:20261021:{kind}"
    out = _run(stores, "a1", key)
    assert out["schema"] == "RunRequested@v1" and out["state"] == "REQUESTED" and out["run_id"] == key
    again = _run(stores, "a2", key)
    assert again["duplicate"] is True and again["run_id"] == key
    assert len(stores[2].list()) == 1


def test_valid_key_for_a_window_on_the_next_calendar_day(stores):
    out = _run(stores, "n1", "rtw:0000:20261022:live", lane="release-train-request-0000", now=NOW_0000)
    assert out["state"] == "REQUESTED"


@pytest.mark.parametrize(
    "key,lane,mode,state",
    [
        ("rtw:0600:20261021:live", "release-train-request-1800", "live", "SLOT_MISMATCH"),  # wrong slot for the lane
        ("rtw:1800:20261020:live", "release-train-request-1800", "live", "WINDOW_DATE_MISMATCH"),  # yesterday's window
        ("rtw:1800:20261022:live", "release-train-request-1800", "live", "WINDOW_DATE_MISMATCH"),  # tomorrow's window
        ("rtw:1800:2026-10-21:live", "release-train-request-1800", "live", "MALFORMED_KEY"),
        ("rtw:1800:20261021:canary", "release-train-request-1800", "live", "MALFORMED_KEY"),
        ("RTW:1800:20261021:live", "release-train-request-1800", "live", "MALFORMED_KEY"),  # case variant
        ("rtw:release-train-request-1800:live:20261021T163000", "release-train-request-1800", "live",
         "MALFORMED_KEY"),  # the old free-form shape inside the namespace
        ("rtw:1800:20261021:live", "release-train-request-0000", "live", "SLOT_MISMATCH"),  # another lane's key
        ("rtw:1800:20261021:live", "release-train-request-1800", "dry_run", "MODE_NOT_LIVE"),
    ],
)
def test_bad_window_keys_are_refused_and_write_nothing(stores, key, lane, mode, state):
    out = _run(stores, "b-" + hashlib.sha256((key + lane + mode).encode()).hexdigest()[:8], key, lane=lane, mode=mode)
    assert out["state"] == "REFUSED" and out["reason"] == "run_window_key_invalid" and out["key_state"] == state
    assert stores[2].list() == []


def test_free_form_live_key_is_still_refused_for_the_relay(stores):
    out = _run(stores, "f1", "release-train-request-1800-free-form-key")
    assert out["reason"] == "run_key_namespace_refused" and out["key_state"] == "UNVALIDATED_NAMESPACE"
    assert stores[2].list() == []


def test_replay_of_an_accepted_key_for_another_lane_or_mode_is_refused(stores):
    assert _run(stores, "c1", "rtw:1800:20261021:live")["state"] == "REQUESTED"
    other = _run(stores, "c2", "rtw:1800:20261021:live", lane="release-train-request-0000")
    assert other["reason"] == "run_window_key_invalid" and other["key_state"] == "KEY_MISMATCH"


def test_refusal_reason_is_declared_and_the_workflow_mints_the_namespace():
    assert "run_window_key_invalid" in G.REFUSAL_REASONS
    wf = json.loads((ROOT / "docs/implementation/n8n-maturity/workflows/fabric/tradeai-fabric-release-train.json")
                    .read_text())
    js = "\n".join(str(n.get("parameters", {}).get("jsCode") or "") for n in wf["nodes"])
    assert "'rtw:' + slot + ':' + wstart.toFormat('yyyyLLdd') + ':' + kind" in js
    assert "rtw:' + sl.lane_id" not in js  # the old free-form shape is gone
