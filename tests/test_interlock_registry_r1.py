#!/usr/bin/env python3
"""R1 interlock: broker_accounts canonical + legacy fallback + behavior table."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import live_trading_interlock as lti  # noqa: E402


class _Cur:
    def __init__(self, script):
        self._script = list(script)
        self._i = 0
        self.description = None

    def execute(self, sql, params=None):
        self._sql = sql
        self._params = params
        self._i += 1

    def fetchone(self):
        if not self._script:
            return None
        return self._script.pop(0)

    def fetchall(self):
        return []


class _Conn:
    def __init__(self, answers):
        # answers: list of fetchone results in order of execute calls
        self._answers = list(answers)
        self.commits = 0

    def cursor(self):
        return _Cur(self._answers)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_normalize_aliases():
    assert lti._normalize("alpaca_paper") == "tradeai_automated"
    assert lti._normalize("ALPACA_PAPER") == "tradeai_automated"
    assert lti._normalize("fidelity_401k") == "fidelity_rollover_ira"


def test_paper_allows():
    # canonical paper from broker_accounts, then parity insert
    conn = _Conn([
        ("paper",),  # canonical
        ("paper",),  # legacy for parity
        None,        # parity insert doesn't fetch
    ])
    # simplify: mock _log_parity
    with mock.patch.object(lti, "_log_parity"):
        with mock.patch.object(lti, "_canonical_mode", return_value="paper"):
            with mock.patch.object(lti, "_legacy_mode", return_value="paper"):
                r = lti.assert_writable(conn, "tradeai_automated", "arm")
    assert r["ok"] and r["mode"] == "paper"


def test_live_refused_when_policy_off():
    with mock.patch.object(lti, "_log_parity"):
        with mock.patch.object(lti, "account_mode", return_value="live"):
            with mock.patch.object(lti, "gate_status", return_value={"passed": False}):
                with pytest.raises(lti.InterlockRefused):
                    lti.assert_writable(object(), "schwab_taxable", "arm")


def test_live_allowed_when_policy_on():
    with mock.patch.object(lti, "_log_parity"):
        with mock.patch.object(lti, "account_mode", return_value="live"):
            with mock.patch.object(lti, "gate_status", return_value={"passed": True}):
                r = lti.assert_writable(object(), "schwab_taxable", "arm")
    assert r["ok"] and r["mode"] == "live"


def test_unknown_refused():
    with mock.patch.object(lti, "_log_parity"):
        with mock.patch.object(lti, "account_mode", return_value=None):
            with pytest.raises(lti.InterlockRefused, match="unknown"):
                lti.assert_writable(object(), "nope", "arm")


def test_canonical_prefers_broker_accounts_over_legacy():
    with mock.patch.object(lti, "_log_parity") as lp:
        with mock.patch.object(lti, "_canonical_mode", return_value="paper"):
            with mock.patch.object(lti, "_legacy_mode", return_value="live"):
                m = lti.account_mode(object(), "tradeai_automated", log_parity=True)
    assert m == "paper"
