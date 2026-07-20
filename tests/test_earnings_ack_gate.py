#!/usr/bin/env python3
"""Operator-acknowledged earnings risk — the narrow downgrade, and its limits.

Authorised by the operator 2026-07-20. Selling premium through an earnings print
is a legitimate strategy and the risk is the operator's; without this, the desk
would offer an actionable covered_call_earnings_iv card that the gate always
refuses, recreating the CSCO contradiction.

These tests exist to keep the downgrade NARROW. Every case below that still
blocks is a way the acknowledgement must not be abusable.

Pure: no network, no broker, no order.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import options_desk_enterprise as ent  # noqa: E402

SOON = (date.today() + timedelta(days=6)).isoformat()
OTHER = (date.today() + timedelta(days=20)).isoformat()
BASE = {"symbol": "ANET", "strategy": "covered_call", "dte": 30, "contracts": 1,
        "occ_symbol": "ANET260821C00200000", "data_source": "chain"}


def _codes(proposal):
    return [b["code"] for b in ent.evaluate_hard_risk_blocks(proposal, mode="submit")]


def _full_ack(earnings_date=SOON):
    return {"code": "EARNINGS_INSIDE_CONTRACT", "earnings_date": earnings_date,
            "acknowledged_by": "operator:john",
            "acknowledged_at": "2026-07-20T17:30:00Z"}


@pytest.fixture
def scheduled(monkeypatch):
    monkeypatch.setattr(ent, "earnings_calendar", lambda syms: {s: SOON for s in syms})


@pytest.fixture
def unknown(monkeypatch):
    monkeypatch.setattr(ent, "earnings_calendar",
                        lambda syms: {s: ent.EARNINGS_UNKNOWN for s in syms})


# ── the downgrade works ────────────────────────────────────────────────────

def test_without_ack_earnings_blocks(scheduled):
    assert "earnings_blackout" in _codes(BASE)


def test_valid_ack_downgrades_to_warning(scheduled):
    assert "earnings_blackout" not in _codes({**BASE, "operator_ack": _full_ack()})


# ── and cannot be abused ───────────────────────────────────────────────────

def test_ack_for_a_different_date_does_not_apply(scheduled):
    """Consent to one report must never cover a different or rescheduled one."""
    assert "earnings_blackout" in _codes({**BASE, "operator_ack": _full_ack(OTHER)})


def test_ack_without_acknowledged_by_is_rejected(scheduled):
    a = _full_ack(); a.pop("acknowledged_by")
    assert "earnings_blackout" in _codes({**BASE, "operator_ack": a})


def test_ack_without_timestamp_is_rejected(scheduled):
    a = _full_ack(); a.pop("acknowledged_at")
    assert "earnings_blackout" in _codes({**BASE, "operator_ack": a})


def test_ack_with_wrong_code_is_rejected(scheduled):
    a = _full_ack(); a["code"] = "SOMETHING_ELSE"
    assert "earnings_blackout" in _codes({**BASE, "operator_ack": a})


def test_empty_ack_is_rejected(scheduled):
    assert "earnings_blackout" in _codes({**BASE, "operator_ack": {}})


@pytest.mark.parametrize("bad", [None, "", "yes", 1, []])
def test_non_dict_ack_is_rejected(scheduled, bad):
    assert "earnings_blackout" in _codes({**BASE, "operator_ack": bad})


# ── unknown timing is NOT acknowledgeable ──────────────────────────────────

def test_unknown_earnings_cannot_be_acknowledged(unknown):
    """You cannot consent to a risk whose date the system could not establish."""
    codes = _codes({**BASE, "operator_ack": _full_ack()})
    assert "EARNINGS_TIMESTAMP_UNKNOWN" in codes


def test_invalid_earnings_cannot_be_acknowledged(monkeypatch):
    monkeypatch.setattr(ent, "earnings_calendar", lambda syms: {s: "garbage" for s in syms})
    codes = _codes({**BASE, "operator_ack": _full_ack()})
    assert "EARNINGS_TIMESTAMP_INVALID" in codes


# ── other gates are untouched ──────────────────────────────────────────────

def test_ack_does_not_clear_unrelated_blocks(scheduled):
    """An earnings ack must not launder a liquidity or contract failure."""
    p = {**BASE, "operator_ack": _full_ack()}
    p.pop("occ_symbol")                    # no resolved contract
    p["data_source"] = "bs_estimate"       # estimate, not a live chain
    codes = _codes(p)
    assert "no_resolved_occ" in codes
    assert "bs_estimate_only" in codes
