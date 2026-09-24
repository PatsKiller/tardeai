"""M5 step-1 guardrails (audit 2026-09-23).

1. Paper/training accounts never page -- the 09-22 operator decision was wired
   into open_trade_monitor only; eod_open_trade_alert still sent "Alpaca paper
   mode | Simulated positions" on 09-22 and 09-23, and alpaca_stop_manager,
   paper_trade_monitor and atm_auto_approver had no gate at all.
2. pytest dropped the LIVE bitemporal shadow (memory_r10_m2 on m2_shadow) on
   every run: fixtures defaulted to it and the destructive reset was opted in
   for any non-production connection.
3. The stance-gate observe receipt (live evidence) was overwritten by a pytest
   fixture run.
"""
from __future__ import annotations

import importlib.util
import logging
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib.paper_account_policy import (  # noqa: E402
    all_paper_only,
    is_paper_only,
    suppress_paper_alert,
)
from scripts.lib import m2_live_shadow_guard as guard  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Paper accounts never page
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("acct", ["ALPACA_PAPER", "alpaca_paper", "TOS_PAPER", "tradeai_automated"])
def test_paper_accounts_match_case_insensitively(acct):
    # paper_trade_proposals.target_account spells it `alpaca_paper`.
    assert is_paper_only({"account": acct}) is True
    assert is_paper_only({"target_account": acct}) is True
    assert is_paper_only({"execution_account": acct}) is True


@pytest.mark.parametrize("acct", ["schwab_taxable", "schwab_rollover_ira", "schwab_roth_ira",
                                  "alpaca_taxable_live", "some_new_account"])
def test_real_or_unknown_accounts_still_page(acct):
    assert is_paper_only({"account": acct, "broker": "schwab"}) is False


def test_extra_paper_accounts_from_env(monkeypatch):
    assert is_paper_only({"account": "sim_lab"}) is False
    monkeypatch.setenv("TRADEAI_PAPER_ONLY_ACCOUNTS", "sim_lab, other_sim")
    assert is_paper_only({"account": "sim_lab"}) is True


def test_all_paper_only_needs_every_account():
    assert all_paper_only(["ALPACA_PAPER", "tradeai_automated"]) is True
    assert all_paper_only(["ALPACA_PAPER", "schwab_taxable"]) is False
    assert all_paper_only([]) is False  # nothing known -> page


def test_suppression_is_logged(caplog):
    with caplog.at_level(logging.INFO):
        assert suppress_paper_alert("unit", {"account": "ALPACA_PAPER"}, "BAX") is True
    assert "[paper-mute] unit" in caplog.text
    assert suppress_paper_alert("unit", {"account": "schwab_taxable"}) is False


def test_open_trade_monitor_uses_the_shared_policy():
    import lib.paper_account_policy as pol

    src = (SCRIPTS / "open_trade_monitor.py").read_text(encoding="utf-8")
    assert "from lib.paper_account_policy import PAPER_ONLY_ACCOUNTS, is_paper_only" in src
    assert "def is_paper_only" not in src, "policy must have one definition"
    assert pol.PAPER_ONLY_ACCOUNTS == {"ALPACA_PAPER", "TOS_PAPER", "tradeai_automated"}


def _gate_precedes(src: str, gate: str, send: str, start: int = 0) -> bool:
    i_gate = src.index(gate, start)
    return i_gate < src.index(send, i_gate)


def test_every_paper_sender_is_gated_before_send():
    stop = (SCRIPTS / "alpaca_stop_manager.py").read_text(encoding="utf-8")
    assert _gate_precedes(stop, '"alpaca_stop_manager.convert_to_oco"', "🟢 ATM auto (paper)")
    assert _gate_precedes(stop, '"alpaca_stop_manager.repair_oco_replacing"', "🛑 NAKED paper position")

    ptm = (SCRIPTS / "paper_trade_monitor.py").read_text(encoding="utf-8")
    assert "RETURNING id, symbol, proposal_id, account, execution_account, broker" in ptm
    assert _gate_precedes(ptm, '"paper_trade_monitor.never_submitted"', "TRADE CANCELLED")

    atm = (SCRIPTS / "atm_auto_approver.py").read_text(encoding="utf-8")
    assert _gate_precedes(atm, '"atm_auto_approver.approved"', "ATM auto-approved:")
    assert _gate_precedes(atm, '"atm_auto_approver.kill_switch"', "ATM KILL SWITCH: {acct}")
    assert _gate_precedes(atm, "all_paper_only(enabled_accounts)", "ATM KILL SWITCH FIRED")
    assert _gate_precedes(atm, '"atm_auto_approver.expiry"', "expired_this_cycle.append(")


def _load_eod(monkeypatch):
    stub = types.ModuleType("db_adapter")
    stub.get_connection = lambda: None
    monkeypatch.setitem(sys.modules, "db_adapter", stub)
    # The report also mirrors into the comms ledger; keep that off any database.
    comms = types.ModuleType("lib.comms")
    comms.CommunicationEvent = lambda **k: k
    comms.publish_communication = lambda ev: None
    monkeypatch.setitem(sys.modules, "lib.comms", comms)
    spec = importlib.util.spec_from_file_location("_eod_under_test", SCRIPTS / "eod_open_trade_alert.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _row(acct):
    return {"symbol": "BAX", "strategy_id": "s", "shares": 1, "entry_price": 10, "current_price": 11,
            "stop_loss": 9, "target_1": 12, "unrealized_pnl": 1, "r_multiple": 1, "created_at": None,
            "account": acct, "execution_account": None, "broker": None}


def test_eod_alert_sends_nothing_for_an_all_paper_book(monkeypatch):
    m = _load_eod(monkeypatch)
    sent = []
    tg = types.ModuleType("telegram_alert")
    tg.send_telegram = lambda msg, **k: sent.append(msg) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    monkeypatch.setattr(m, "get_open_trades", lambda: ([_row("ALPACA_PAPER"), _row("tradeai_automated")], {}))
    assert m.send_eod_alert() is False
    assert sent == [], "paper-only EOD report reached Telegram"


def test_eod_alert_still_reports_real_money(monkeypatch):
    """POSITIVE CONTROL: the mute must not swallow a real-money row."""
    m = _load_eod(monkeypatch)
    sent = []
    tg = types.ModuleType("telegram_alert")
    tg.send_telegram = lambda msg, **k: sent.append(msg) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    monkeypatch.setattr(m, "format_message", lambda rows, tm: f"{len(rows)} rows")
    monkeypatch.setattr(m, "get_open_trades", lambda: ([_row("ALPACA_PAPER"), _row("schwab_taxable")], {}))
    assert m.send_eod_alert() is True
    assert sent == ["1 rows"]


def test_eod_no_connection_does_not_crash(monkeypatch):
    m = _load_eod(monkeypatch)
    assert m.get_open_trades() == ([], {})


# ---------------------------------------------------------------------------
# 2. pytest never resets (or connects to) the live shadow
# ---------------------------------------------------------------------------

class _Conn:
    def __init__(self, dbname, port="55432"):
        self.dbname, self.port, self.executed = dbname, port, []

    def get_dsn_parameters(self):
        return {"host": "127.0.0.1", "port": self.port, "dbname": self.dbname}


def test_live_shadow_is_never_reset_under_pytest(monkeypatch):
    live = guard.dsn_database(guard.SHADOW_ADMIN_DSN)
    assert live == "m2_shadow"
    assert guard.destructive_reset_permitted(_Conn(live), is_production=False) is False
    # Even the explicit opt-in is ignored inside pytest.
    monkeypatch.setenv(guard.LIVE_RESET_ENV, "1")
    assert guard.destructive_reset_permitted(_Conn(live), is_production=False) is False


def test_test_database_may_be_reset_but_production_never():
    assert guard.destructive_reset_permitted(_Conn("m2_shadow_test"), is_production=False) is True
    assert guard.destructive_reset_permitted(_Conn("m2_shadow_test"), is_production=True) is False


def test_live_reset_opt_in_outside_pytest(monkeypatch):
    monkeypatch.setattr(guard, "under_pytest", lambda: False)
    assert guard.destructive_reset_permitted(_Conn("m2_shadow"), is_production=False) is False
    monkeypatch.setenv(guard.LIVE_RESET_ENV, "1")
    assert guard.destructive_reset_permitted(_Conn("m2_shadow"), is_production=False) is True


def test_connecting_to_the_live_shadow_is_refused_under_pytest():
    with pytest.raises(RuntimeError, match="M2_LIVE_SHADOW_FORBIDDEN_UNDER_PYTEST"):
        guard.refuse_live_shadow_under_pytest(guard.SHADOW_ADMIN_DSN)
    ok = guard.with_database(guard.SHADOW_ADMIN_DSN, "m2_shadow_test")
    assert guard.refuse_live_shadow_under_pytest(ok) == ok


def test_conftest_routed_every_shadow_dsn_off_live():
    import os

    for var in ("M2_DSN", "TEST_DB_DSN", "M2_AGENT_DSN", "MEMORY_SHADOW_DSN",
                "MEMORY_SHADOW_WRITER_DSN", "MEMORY_SHADOW_READER_DSN"):
        assert guard.dsn_database(os.environ[var]) not in guard.live_shadow_databases(), var


def test_dsn_database_parsing():
    assert guard.dsn_database("postgresql://u:p@h:55432/m2_shadow?sslmode=disable") == "m2_shadow"
    assert guard.dsn_database("host=h port=55432 dbname=m2_shadow_test user=m2") == "m2_shadow_test"
    assert guard.dsn_database("") == ""


def test_benchmark_apply_schema_skips_opt_in_on_live_shadow():
    from scripts.lib.memory_m2_benchmark import apply_schema

    class _Cur:
        def __init__(self, sink): self.sink = sink; self.description = None
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None): self.sink.append(str(sql))
        def fetchone(self): return None

    class _FakeConn(_Conn):
        def cursor(self): return _Cur(self.executed)

    live, test = _FakeConn("m2_shadow"), _FakeConn("m2_shadow_test")
    for c in (live, test):
        try:
            apply_schema(c)
        except Exception:
            pass  # packaging heal probes a real DB; only the opt-in decision matters
    opted = lambda c: any(s.strip().upper().startswith("SET M2.ALLOW_DESTRUCTIVE_RESET") for s in c.executed)  # noqa: E731
    assert not opted(live), "live shadow was opted in to DROP SCHEMA ... CASCADE"
    assert opted(test), "positive control: the test database must still rebuild"


def test_shadow_projection_sql_no_longer_drops_unconditionally():
    sql = (ROOT / "sql" / "r10_tradeai_memory_shadow_isolated.sql").read_text(encoding="utf-8")
    body = re.sub(r"--[^\n]*", "", sql)
    guard_block = body[body.index("DO $reset$"):body.index("$reset$;") + len("$reset$;")]
    outside = body.replace(guard_block, "")
    assert "DROP SCHEMA" not in outside, "an unguarded DROP SCHEMA is back"
    assert "M2_DESTRUCTIVE_RESET_REFUSED" in guard_block
    assert "m2.allow_destructive_reset" in guard_block


def test_base_sql_allowlists_the_test_database():
    sql = (ROOT / "sql" / "r10_m2_isolated_benchmark.sql").read_text(encoding="utf-8")
    assert "'m2_shadow,m2_shadow_test'" in sql


# ---------------------------------------------------------------------------
# 3. The stance-gate observe receipt is production evidence
# ---------------------------------------------------------------------------

def test_observe_receipt_not_written_under_pytest(tmp_path, monkeypatch):
    from scripts.lib.cio_telegram_stance_gate import write_organic_observe_receipt

    monkeypatch.setenv("HOME", str(tmp_path))
    assert write_organic_observe_receipt({"organic": 1, "total": 1}) == []
    assert not (tmp_path / ".local/state/tradeai/organic_stance_hold_observe.json").exists()


def test_observe_receipt_still_written_outside_pytest(tmp_path, monkeypatch):
    """POSITIVE CONTROL: the guard is scoped to pytest, not a blanket mute."""
    from scripts.lib import cio_telegram_stance_gate as g

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    fake_root = types.ModuleType("scripts.lib.persistent_state_root")
    fake_root.good_persistent_root = lambda: tmp_path / "nowhere"
    monkeypatch.setitem(sys.modules, "scripts.lib.persistent_state_root", fake_root)
    written = g.write_organic_observe_receipt({"organic": 0})
    assert written == [str(tmp_path / ".local/state/tradeai/organic_stance_hold_observe.json")]
