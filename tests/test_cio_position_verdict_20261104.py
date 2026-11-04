#!/usr/bin/env python3
"""FQ-095 — the CIO is the only producer of a position verdict, and its history persists per (symbol, account).

Operator's rule (SPEC_ONE_POSITION_VERDICT_20261104 §1b, verbatim): "this is supposed to be saved in a persistent
memory, and if I have SpaceX in different accounts, each account should be isolated and counted separately."

These tests are written against the contract, not the implementation: a verdict is a record with a fixed shape, the
only writer is the CIO, and the history reads back after the process that wrote it is gone.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import cio_position_verdict as V  # noqa: E402

NOW = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)


def verdict(account="schwab_individual", *, action="HOLD", as_of=NOW, sequence=None, **over):
    payload = {
        "symbol": "SPCX", "account": account, "action": action,
        "state": "stopped_out", "stage": "watching", "confidence": 0.72,
        "trigger": "second stop-out on SPCX since 2026-10-14",
        "narrative": "SPCX exited again in this account; the CIO is watching for a reclaim of 138.00",
        "as_of": as_of.isoformat(),
        "evidence": [{"source": "fills", "as_of": "2026-11-04T14:58:00+00:00", "ref": "fill:abc123"},
                     {"source": "watch_canonical_quote", "as_of": "2026-11-04T14:59:00+00:00", "ref": "quote:SPCX"}],
        "tax_constraint": {"account": account, "wash_sale_window_days": 30,
                           "window_ends": "2026-12-04", "holding_period": "short"},
        "alternatives": [{"action": "RE_ENTRY_READY", "rejected_because": "no reclaim above the 2026-10-14 exit"},
                         {"action": "EXIT", "rejected_because": "the residual is already sold in this account"}],
    }
    if sequence is not None:
        payload["sequence"] = sequence
    payload.update(over)
    return payload


def test_history_survives_a_restart_per_symbol_and_account(tmp_path):
    """The whole point: write, stop, start again, and the history is still keyed by (symbol, account)."""
    path = tmp_path / "position_verdicts.jsonl"
    first = V.VerdictStore(path, producer="cio_truth")
    v1 = first.record(verdict())
    v2 = first.record(verdict(action="WATCHING", as_of=datetime(2026, 11, 4, 15, 30, tzinfo=timezone.utc)))

    restarted = V.VerdictStore(path, producer="cio_truth")        # a new process, same durable memory
    assert restarted.current("SPCX", "schwab_individual")["verdict_id"] == v2["verdict_id"]
    history = restarted.history("SPCX", "schwab_individual")
    assert [h["verdict_id"] for h in history] == [v1["verdict_id"], v2["verdict_id"]]
    assert [h["sequence"] for h in history] == [1, 2]


def test_two_accounts_never_bleed_either_way(tmp_path):
    """The cross-account defect at canonical_observation.py:276/352, asserted at the record."""
    path = tmp_path / "position_verdicts.jsonl"
    store = V.VerdictStore(path, producer="cio_truth")
    store.record(verdict(account="schwab_individual", action="HOLD"))
    store.record(verdict(account="schwab_rollover_ira", action="RE_ENTRY_READY"))

    assert [h["account"] for h in store.history("SPCX", "schwab_individual")] == ["schwab_individual"]
    assert [h["account"] for h in store.history("SPCX", "schwab_rollover_ira")] == ["schwab_rollover_ira"]
    assert store.current("SPCX", "schwab_individual")["action"] == "HOLD"
    assert store.current("SPCX", "schwab_rollover_ira")["action"] == "RE_ENTRY_READY"


def test_the_cio_is_the_only_producer(tmp_path):
    """Every surface renders the CIO's record. A surface that computes its own verdict cannot write it here."""
    store = V.VerdictStore(tmp_path / "v.jsonl", producer="home_do_now")
    with pytest.raises(V.NotCIOProducer):
        store.record(verdict())
    assert V.VerdictStore(tmp_path / "v.jsonl", producer="cio_truth").history("SPCX", "schwab_individual") == []


def test_a_verdict_without_evidence_tax_constraint_or_alternatives_is_refused(tmp_path):
    store = V.VerdictStore(tmp_path / "v.jsonl", producer="cio_truth")
    for missing in ("evidence", "tax_constraint", "alternatives", "as_of", "trigger"):
        payload = verdict()
        payload.pop(missing)
        with pytest.raises(ValueError, match=missing):
            store.record(payload)


def test_an_aggregate_is_not_a_verdict(tmp_path):
    """Totals are a read-time computation over per-account verdicts; they are never stored as one."""
    store = V.VerdictStore(tmp_path / "v.jsonl", producer="cio_truth")
    with pytest.raises(ValueError, match="account"):
        store.record({**verdict(), "account": "ALL_ACCOUNTS"})


def test_the_producer_assembles_a_verdict_and_refuses_an_unjustified_one():
    """The CIO's own builder: a payload cannot be assembled without evidence, tax constraint or alternatives."""
    built = V.build_verdict(symbol="SPCX", account="schwab_individual", action="HOLD", state="stopped_out",
                            stage="watching", confidence=0.7, trigger="second stop-out", narrative="watching",
                            as_of=NOW.isoformat(), evidence=[{"source": "fills", "ref": "f1"}],
                            tax_constraint={"wash_sale_window_days": 30}, alternatives=[{"action": "EXIT"}])
    assert set(V.REQUIRED_FIELDS) <= set(built) and built["account"] == "schwab_individual"

    for missing in ("evidence", "tax_constraint", "alternatives"):
        args = dict(symbol="SPCX", account="schwab_individual", action="HOLD", state="stopped_out",
                    stage="watching", confidence=0.7, trigger="t", narrative="n", as_of=NOW.isoformat(),
                    evidence=[{"source": "fills", "ref": "f1"}], tax_constraint={"w": 30},
                    alternatives=[{"action": "EXIT"}])
        args[missing] = []
        with pytest.raises(ValueError, match=missing):
            V.build_verdict(**args)


def test_a_surface_shows_the_record_or_says_unavailable_and_never_its_own(tmp_path):
    """§1b rule 1: the surface renders the CIO record, or states its absence — it does not compute one."""
    store = V.VerdictStore(tmp_path / "v.jsonl", producer="cio_truth")

    empty = V.render_for_surface(store, "SPCX", "schwab_individual")
    assert empty["available"] is False and empty["reason"] == V.UNAVAILABLE
    assert "verdict" not in empty

    store.record(verdict())
    shown = V.render_for_surface(store, "SPCX", "schwab_individual")
    assert shown["available"] is True and shown["verdict"]["action"] == "HOLD"
    assert V.render_for_surface(store, "SPCX", "schwab_rollover_ira")["available"] is False
