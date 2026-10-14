"""catalyst_momentum_engine --generate-proposals ALPACA_MODE gate (2026-10-14).

66ca87501 (G8) stopped copying ALPACA_* from .env, so the old "ALPACA_MODE must equal paper"
gate aborted every premarket_scalp / market_swing run from 2026-10-12. The gate now refuses
only an explicit non-paper value; unset proceeds (the proposal subprocess pins paper).

Hermetic: main()'s DB/network work (_run), the lane receipt, the kill switch and the .env loader
are stubbed. No DB, no subprocess, no token store, no real .env.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import catalyst_momentum_engine as cme  # noqa: E402


class _Receipts:
    def __init__(self):
        self.calls = []

    def write_lane_receipt(self, *args, **kwargs):
        self.calls.append((args, kwargs))


@pytest.fixture
def harness(monkeypatch):
    ran = []
    receipts = _Receipts()

    def fake_run(args, stats):
        ran.append(args)
        return 0

    monkeypatch.setattr(cme, "_load_env", lambda: None)
    monkeypatch.setattr(cme, "kill_active", lambda: False)
    monkeypatch.setattr(cme, "_run", fake_run)
    monkeypatch.setattr(cme, "_receipt_lib", lambda: receipts)
    monkeypatch.delenv("ALPACA_MODE", raising=False)

    def call(*argv):
        monkeypatch.setattr(sys, "argv", ["catalyst_momentum_engine.py", *argv])
        return cme.main()

    return call, ran, receipts


@pytest.mark.parametrize("band", ["premarket_scalp", "market_swing"])
def test_unset_alpaca_mode_does_not_abort_proposal_generation(harness, band):
    call, ran, receipts = harness
    rc = call("--band", band, "--apply", "--generate-proposals")
    assert rc == 0
    assert len(ran) == 1 and ran[0].generate_proposals is True
    assert len(receipts.calls) == 1


@pytest.mark.parametrize("value", ["paper", "PAPER", " paper "])
def test_paper_alpaca_mode_proceeds(harness, monkeypatch, value):
    call, ran, _ = harness
    monkeypatch.setenv("ALPACA_MODE", value)
    assert call("--band", "market_swing", "--apply", "--generate-proposals") == 0
    assert len(ran) == 1


@pytest.mark.parametrize("value", ["live", "LIVE", "production"])
def test_explicit_non_paper_alpaca_mode_refuses(harness, monkeypatch, value):
    call, ran, receipts = harness
    monkeypatch.setenv("ALPACA_MODE", value)
    assert call("--band", "premarket_scalp", "--apply", "--generate-proposals") == 1
    assert ran == [] and receipts.calls == []


def test_live_mode_without_generate_proposals_is_not_gated(harness, monkeypatch):
    call, ran, _ = harness
    monkeypatch.setenv("ALPACA_MODE", "live")
    assert call("--band", "overnight", "--apply") == 0
    assert len(ran) == 1


def test_env_loader_still_db_only():
    assert cme._ENV_KEYS == frozenset({"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"})
