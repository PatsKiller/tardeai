"""Training trades must never reach the operator's phone.

OPERATOR DECISION 2026-09-22: "Anything being traded in the alpaca paper
account is just for training purposes. We don't need to be alerted on it...
I only want to care about being alerted about what I should be trading real
money with."

WHAT WENT WRONG
---------------
open_trade_monitor emitted EXTENDED PROFIT for BAX 12 times between 10:45 and
11:21 -- "+$170.04" on a position the operator does not own. Measured: every
row in paper_trades belongs to ALPACA_PAPER, TOS_PAPER or tradeai_automated
(the SANDBOX_ACCOUNT at validation_submitter.py:20). Not one is real money;
the real accounts live in schwab_positions_live and hold none of those symbols.

The gate is on the ACCOUNT, not the script, so a real-money row appearing in
this table would still alert rather than be swallowed by a blanket mute.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "scripts" / "open_trade_monitor.py"


@pytest.fixture
def otm():
    if not TARGET.is_file():
        pytest.skip("open_trade_monitor not present")
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("_otm_under_test", TARGET)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.__file__ == str(TARGET)
    return m


@pytest.mark.parametrize("acct", ["ALPACA_PAPER", "TOS_PAPER", "tradeai_automated"])
def test_every_paper_account_is_muted(otm, acct):
    assert otm.is_paper_only({"account": acct, "broker": ""}) is True


@pytest.mark.parametrize("broker", ["alpaca_paper", "tos_paper"])
def test_broker_column_also_mutes(otm, broker):
    assert otm.is_paper_only({"account": "", "broker": broker}) is True


@pytest.mark.parametrize("acct", ["schwab_taxable", "schwab_rollover_ira", "schwab_roth_ira"])
def test_real_money_accounts_still_alert(otm, acct):
    """The whole point: real money must NOT be silenced."""
    assert otm.is_paper_only({"account": acct, "broker": "schwab"}) is False


def test_unknown_account_still_alerts(otm):
    """Fail OPEN for alerting: an account we do not recognise is not assumed paper."""
    assert otm.is_paper_only({"account": "some_new_account", "broker": ""}) is False
    assert otm.is_paper_only({}) is False
    assert otm.is_paper_only(None) is False


def test_monitor_trade_mutes_telegram_for_paper(otm):
    """Structural: the gate is wired into monitor_trade, not merely defined."""
    src = TARGET.read_text(encoding="utf-8")
    assert "if is_paper_only(trade):" in src
    assert "no_telegram = True" in src
    i_gate = src.index("if is_paper_only(trade):")
    i_def = src.index("def monitor_trade(")
    i_first_send = src.index("send_telegram(", i_def)
    assert i_def < i_gate < i_first_send, "the gate must precede every send"


def test_the_detector_can_fail(otm):
    """POSITIVE CONTROL: a stub that mutes everything must fail the real-money case."""
    always = lambda t: True  # noqa: E731
    assert always({"account": "schwab_taxable"}) is True
    with pytest.raises(AssertionError):
        assert always({"account": "schwab_taxable"}) is False
    assert otm.is_paper_only({"account": "schwab_taxable", "broker": "schwab"}) is False


def test_the_poisoning_query_is_fixed(otm):
    """stop_decisions has decided_at, NOT created_at.

    The wrong column aborted the whole Postgres transaction every cycle, so
    conn.commit() persisted nothing -- the dedupe row was rolled back while the
    Telegram had already been sent, and the alert re-fired every 3 minutes.
    """
    src = TARGET.read_text(encoding="utf-8")
    seg = src[src.index("FROM stop_decisions"):src.index("FROM stop_decisions") + 260]
    assert "decided_at" in seg, "stop_decisions has no created_at column"
    assert "created_at" not in seg, "the aborting column reference is back"
    assert "SAVEPOINT ack_lookup" in src, "no savepoint: one bad lookup poisons the cycle"
    assert "ROLLBACK TO SAVEPOINT ack_lookup" in src
