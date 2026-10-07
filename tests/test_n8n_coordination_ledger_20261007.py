"""The sqlite coordination ledger refuses replay after a restart. It is not served."""
from __future__ import annotations

import threading

import pytest

from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerError


def _accept(ledger: CoordinationLedger, *, nonce: str = "nonce-0001", key: str = "trade-ai:idem-0001", now: float = 1000.0, **extra):
    return ledger.accept(
        nonce=nonce,
        nonce_exp=now + 120,
        idempotency_key=key,
        payload_hash="abc123",
        now=now,
        source_sha="18a27ff288894c4e428151d5f385e68522ecd47b",
        served_sha=None,
        caller_id="n8n-lab",
        **extra,
    )


def test_crash_before_commit_leaves_no_nonce_or_effect(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = CoordinationLedger(path)
    with pytest.raises(RuntimeError, match="crash_before_commit"):
        _accept(ledger, crash_before_commit=True)
    assert ledger.nonce_present("nonce-0001") is False
    assert ledger.effect_count() == 0
    ledger.close()


def test_restart_refuses_replay_and_keeps_one_effect(tmp_path):
    path = tmp_path / "ledger.sqlite"
    first = CoordinationLedger(path)
    row = _accept(first)
    assert row["duplicate"] is False
    assert row["durable"] is True and row["durable_scope"] == "sqlite_commit_returned"   # 2026-10-07: the COMMIT returned
    assert row["external_delivery"] == "NOT_CLAIMED"
    assert first.effect_count() == 1
    first.close()
    second = CoordinationLedger(path)
    replay = _accept(second, nonce="nonce-0002")
    assert replay["duplicate"] is True
    assert second.effect_count() == 1
    with pytest.raises(LedgerError) as caught:
        _accept(second, nonce="nonce-0001", key="trade-ai:other")
    assert caught.value.reason == "replayed_nonce"
    assert second.effect_count() == 1
    second.close()


def test_two_threads_accept_once(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = CoordinationLedger(path)
    barrier = threading.Barrier(2)
    outcomes: list[object] = []

    def worker() -> None:
        local = CoordinationLedger(path)
        try:
            barrier.wait()
            outcomes.append(_accept(local))
        except LedgerError as exc:
            outcomes.append(exc.reason)
        finally:
            local.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert ledger.effect_count() == 1
    assert sum(1 for item in outcomes if isinstance(item, dict) and item.get("duplicate") is False) == 1
    assert any(item == "replayed_nonce" or (isinstance(item, dict) and item.get("duplicate")) for item in outcomes)
    ledger.close()


def test_reference_cannot_change_lane_or_mint_a_key(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = CoordinationLedger(path)
    _accept(ledger)
    token = ledger.issue_reference(
        idempotency_key="trade-ai:idem-0001",
        project="trade-ai",
        lane_id="morning-brief-0730",
        exp=2000,
    )
    assert token not in path.read_bytes().decode("utf-8", errors="replace")
    redeemed = ledger.redeem_reference(
        token,
        idempotency_key="trade-ai:idem-0001",
        project="trade-ai",
        lane_id="morning-brief-0730",
        now=1500,
    )
    assert redeemed["hmac_key_returned"] is False
    assert redeemed["can_mint_claim"] is False
    with pytest.raises(LedgerError) as caught:
        ledger.redeem_reference(
            token,
            idempotency_key="trade-ai:idem-0001",
            project="trade-ai",
            lane_id="approval-package-reminder",
            now=1500,
        )
    assert caught.value.reason == "reference_bound"
    with pytest.raises(LedgerError) as expired:
        ledger.redeem_reference(
            token,
            idempotency_key="trade-ai:idem-0001",
            project="trade-ai",
            lane_id="morning-brief-0730",
            now=3000,
        )
    assert expired.value.reason == "reference_expired"
    ledger.close()


def test_rate_limit_and_payload_bound(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    for index in range(30):
        _accept(ledger, nonce=f"nonce-{index:04d}", key=f"trade-ai:idem-{index:04d}", now=1000 + index)
    with pytest.raises(LedgerError) as caught:
        _accept(ledger, nonce="nonce-9999", key="trade-ai:idem-9999", now=1029)
    assert caught.value.reason == "rate_limited"
    with pytest.raises(LedgerError) as large:
        _accept(ledger, nonce="nonce-large", key="trade-ai:large", now=5000, payload_bytes=70000)
    assert large.value.reason == "payload_too_large"
    ledger.close()
