#!/usr/bin/env python3
"""Recovery engine piece D — GET /api/v2/recovery carries piece A's case projection, read through its one accessor.

Synthetic fixtures only (public repo): symbol DEMO, account ``synthetic_taxable``, invented prices.
The projection computes nothing (no state, size, stop, target or eligibility); it adds the row's version and the latest
quote WITH its observation time, and an absent store reads "unavailable", never zero cases.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402
from lib.recovery_engine import cases as rc  # noqa: E402
from lib.recovery_engine import policy as rp  # noqa: E402

NOW = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)
QUOTE = {"price": 52.5, "observed_at": "2026-11-06T14:55:00+00:00", "source": "synthetic"}


def _seeded_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    policy = rp.load_policy(ROOT / "config/recovery_policy.yaml")
    store = rc.CaseStore(conn, policy)
    fills = [rc.ExitFill(symbol="DEMO", account="synthetic_taxable", exit_date=date(2026, 11, 2), shares=100.0,
                         price=50.0, realized_pnl=-1200.0, stop_price=50.0, source_id="synthetic:1")]
    case = rc.build_case(fills, policy=policy, residual_shares=0.0, pre_exit_shares=100.0, pre_exit_weight_pct=1.0,
                         today=date(2026, 11, 6), now=NOW)
    store.upsert(case)
    return conn


def test_projection_reads_piece_a_cases_and_adds_version_and_quote():
    conn = _seeded_conn()
    out = api_v2._recovery_case_projection(conn=conn, quote_for=lambda symbol: dict(QUOTE), now=NOW)
    assert out["schema"] == "RecoveryCaseProjection@v1"
    assert out["state"] == "ok" and out["count"] == 1
    case = out["cases"][0]
    assert case["symbol"] == "DEMO" and case["account"] == "synthetic_taxable"
    assert case["case_version"] == case["updated_at"] and case["case_version"]
    assert case["quote"] == QUOTE, "the quote travels with its own observation time"
    assert case["state"] in rc.STATES, "state is the store's, not recomputed"
    assert isinstance(case["eligibility"], list)
    conn.close()


def test_actions_are_named_and_reported_unwired():
    out = api_v2._recovery_case_projection(conn=_seeded_conn(), quote_for=lambda s: None, now=NOW)
    assert out["actions"]["names"] == ["create_reentry_plan", "watch", "close_case", "snooze"]
    assert out["actions"]["wired"] is False and out["actions"]["endpoint"] is None


def test_missing_quote_stays_none_not_zero():
    out = api_v2._recovery_case_projection(conn=_seeded_conn(), quote_for=lambda s: None, now=NOW)
    assert out["cases"][0]["quote"] is None


def test_absent_store_is_unavailable_never_zero(monkeypatch):
    import db_adapter

    monkeypatch.setattr(db_adapter, "USE_DB", False, raising=False)
    out = api_v2._recovery_case_projection(conn=None, quote_for=lambda s: None, now=NOW)
    assert out["state"] == "unavailable"
    assert out["count"] is None, "unavailable must not read as zero cases"
    assert out["cases"] == []
    assert out["reason"]


def test_failed_read_is_unavailable():
    class Broken:
        def list(self):
            raise RuntimeError("synthetic failure")

    from lib import recovery_state as R

    original = R.store_accessor
    R.store_accessor = lambda conn, policy: Broken()
    try:
        out = api_v2._recovery_case_projection(conn=sqlite3.connect(":memory:"), quote_for=lambda s: None, now=NOW)
    finally:
        R.store_accessor = original
    assert out["state"] == "unavailable" and out["count"] is None
    assert "RuntimeError" in out["reason"]
