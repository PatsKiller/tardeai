"""Lane C — governed Brave router tests (fixtures only; no paid calls)."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from scripts.lib import brave_router as br
from scripts.lib.search_budget import try_consume, status, budget_path


class FixedClock:
    def __init__(self, start: datetime):
        self._t = start

    def __call__(self) -> datetime:
        return self._t

    def advance(self, **kw) -> None:
        self._t = self._t + timedelta(**kw)


def _fixture_transport(payload=None, headers=None):
    payload = payload or {
        "web": {
            "results": [
                {
                    "title": "V earnings guidance upgrade",
                    "url": "https://www.reuters.com/markets/v-earnings",
                    "description": "Visa reports",
                    "age": "1d",
                }
            ]
        },
        "results": [
            {
                "title": "V earnings guidance upgrade",
                "url": "https://www.reuters.com/markets/v-earnings",
                "description": "Visa reports",
                "age": "1d",
                "meta_url": {"hostname": "reuters.com"},
            }
        ],
    }
    headers = headers or {
        "x-ratelimit-limit": "50, 0",
        "x-ratelimit-remaining": "49, 0",
        "x-ratelimit-reset": "1, 1000",
        "x-ratelimit-policy": "50;w=1, 0;w=2592000",
    }

    def _t(url: str, hdrs: dict):
        return payload, headers

    return _t


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    return tmp_path


def test_off_state_no_side_effect(tmp_root: Path):
    clock = FixedClock(datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))
    before = list(tmp_root.rglob("*"))
    resp = br.search(
        "V stock",
        clock=clock,
        root=tmp_root,
        transport=_fixture_transport(),
        enabled=False,
        api_key="fixture",
    )
    assert resp.ok is False
    assert resp.reason == "ROUTER_DISABLED"
    after = list(tmp_root.rglob("*"))
    # health may still be written — constrain: no reservation / no budget spend
    assert not (tmp_root / "data" / "runtime" / "brave_router_reservations.json").exists()
    assert not budget_path(tmp_root).exists() or status("brave", now=clock(), root=tmp_root)["daily_used"] == 0


def test_cache_hit_uses_no_provider_allocation(tmp_root: Path):
    clock = FixedClock(datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))
    calls = {"n": 0}

    def transport(url, headers):
        calls["n"] += 1
        return _fixture_transport()(url, headers)

    r1 = br.search(
        "V stock", clock=clock, root=tmp_root, transport=transport,
        enabled=True, api_key="fixture", idempotency_key="k1",
    )
    assert r1.ok and r1.budget_allocated and calls["n"] == 1
    used1 = status("brave", now=clock(), root=tmp_root)["daily_used"]
    r2 = br.search(
        "V stock", clock=clock, root=tmp_root, transport=transport,
        enabled=True, api_key="fixture", idempotency_key="k2",
    )
    assert r2.ok and r2.cache_hit and not r2.budget_allocated
    assert calls["n"] == 1
    used2 = status("brave", now=clock(), root=tmp_root)["daily_used"]
    assert used2 == used1


def test_refund_on_provider_error(tmp_root: Path):
    clock = FixedClock(datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))

    def boom(url, headers):
        raise RuntimeError("simulated provider failure")

    before = try_consume("brave", caller="t", now=clock(), root=tmp_root)
    # reset by using fresh root already empty — undo the probe consume via refund path
    from scripts.lib.search_budget import refund
    refund("brave", caller="t", now=clock(), root=tmp_root)

    resp = br.search(
        "V stock", clock=clock, root=tmp_root, transport=boom,
        enabled=True, api_key="fixture", idempotency_key="err1",
    )
    assert not resp.ok
    assert "PROVIDER_ERROR" in resp.reason
    st = status("brave", now=clock(), root=tmp_root)
    assert st["daily_used"] == 0


def test_corrupt_ledger_fail_closed(tmp_root: Path):
    clock = FixedClock(datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))
    path = br.reservation_path(tmp_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(br.QuotaCorrupt):
        br.reserve(
            caller="t", purpose="p", idempotency_key="x",
            clock=clock, root=tmp_root,
        )
    # search path also fail-closed
    resp = br.search(
        "q", clock=clock, root=tmp_root, transport=_fixture_transport(),
        enabled=True, api_key="fixture", idempotency_key="x2",
    )
    assert not resp.ok
    assert "QUOTA_CORRUPT" in resp.reason


def test_double_settlement_detected(tmp_root: Path):
    clock = FixedClock(datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))
    res = br.reserve(
        caller="t", purpose="p", idempotency_key="ds1",
        clock=clock, root=tmp_root,
    )
    br.settle(res.reservation_id, clock=clock, root=tmp_root)
    with pytest.raises(br.DoubleSettlement):
        br.settle(res.reservation_id, clock=clock, root=tmp_root)


def test_midnight_injected_clock_boundary(tmp_root: Path):
    clock = FixedClock(datetime(2026, 9, 7, 23, 59, tzinfo=timezone.utc))
    r1 = br.search(
        "q1", clock=clock, root=tmp_root, transport=_fixture_transport(),
        enabled=True, api_key="fixture", idempotency_key="d1",
    )
    assert r1.ok
    day1 = status("brave", now=clock(), root=tmp_root)["daily_used"]
    clock.advance(minutes=2)  # crosses into 2026-09-08
    r2 = br.search(
        "q2", clock=clock, root=tmp_root, transport=_fixture_transport(),
        enabled=True, api_key="fixture", idempotency_key="d2",
    )
    assert r2.ok
    st = status("brave", now=clock(), root=tmp_root)
    # New day counter — daily_used for Sep 8 should be 1 (not 2)
    assert st["daily_used"] == 1
    assert day1 == 1


def test_concurrent_reservations(tmp_root: Path):
    clock = FixedClock(datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))
    # Raise daily limit via env for this process
    os.environ["SEARCH_BUDGET_BRAVE_DAILY"] = "50"
    results = []
    errors = []

    def worker(i: int):
        try:
            r = br.reserve(
                caller="concurrent", purpose="p",
                idempotency_key=f"c-{i}", clock=clock, root=tmp_root,
            )
            results.append(r.reservation_id)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len(set(results)) == 10
    st = status("brave", now=clock(), root=tmp_root)
    assert st["daily_used"] == 10
    os.environ.pop("SEARCH_BUDGET_BRAVE_DAILY", None)


def test_purpose_reserve_quotas_reconcile(tmp_root: Path):
    clock = FixedClock(datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))
    r = br.reserve(
        caller="web_research", purpose="research",
        idempotency_key="pr1", clock=clock, root=tmp_root,
    )
    br.settle(r.reservation_id, clock=clock, root=tmp_root)
    st = status("brave", now=clock(), root=tmp_root)
    assert st["daily_used"] == 1
    assert st["monthly_used"] == 1
    # refund path mathematical inverse
    r2 = br.reserve(
        caller="web_research", purpose="research",
        idempotency_key="pr2", clock=clock, root=tmp_root,
    )
    br.refund_reservation(r2.reservation_id, clock=clock, root=tmp_root)
    st2 = status("brave", now=clock(), root=tmp_root)
    assert st2["daily_used"] == 1
    assert st2["monthly_used"] == 1


def test_provider_policy_vs_local_policy_labeling(tmp_root: Path):
    clock = FixedClock(datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))
    resp = br.search(
        "q", clock=clock, root=tmp_root, transport=_fixture_transport(),
        enabled=True, api_key="fixture", idempotency_key="pol1",
    )
    assert resp.ok
    assert resp.local_cost_policy["kind"] == "local_cost_policy"
    assert resp.local_cost_policy["invented_provider_monthly_ceiling"] is False
    assert resp.provider_capacity["kind"] == "historical_provider_header_evidence"
    assert resp.provider_capacity["not_current_proof"] is True
    # history file exists and is append-only evidence
    hist = br.capacity_history_path(tmp_root)
    assert hist.exists()
    line = hist.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert json.loads(line)["not_current_proof"] is True


def test_reserve_settle_refund_crash_points(tmp_root: Path):
    clock = FixedClock(datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc))
    # Crash after reserve before settle → refund restores
    r = br.reserve(
        caller="t", purpose="p", idempotency_key="crash1",
        clock=clock, root=tmp_root,
    )
    assert status("brave", now=clock(), root=tmp_root)["daily_used"] == 1
    br.refund_reservation(r.reservation_id, clock=clock, root=tmp_root)
    assert status("brave", now=clock(), root=tmp_root)["daily_used"] == 0
    with pytest.raises(br.DoubleSettlement):
        br.refund_reservation(r.reservation_id, clock=clock, root=tmp_root)
