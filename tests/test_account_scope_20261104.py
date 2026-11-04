"""ACCOUNT_SCOPE_20261104 — FQ-096 / SPEC_ONE_POSITION_VERDICT §1b rule 3.

Operator (2026-11-04): "each account should be isolated and counted separately ... only aggregated when it
shows my total position weight." The named defect: `canonical_observation.py` defaulted
`account_scope="ALL_ACCOUNTS"`, so a residual held in an Individual account could be read as held everywhere
and block an IRA re-entry.

These tests pin: no silent all-account default, an explicit scope propagating, and (symbol, account) holdings
semantics — an Individual residual never holds an IRA position.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.account_scope import SCOPE_UNSCOPED, account_of, held_accounts, held_for, held_in  # noqa: E402
from lib.canonical_observation import ObservationEnvelope, observe_state_file  # noqa: E402

HOLDINGS = {
    "holdings": [
        {"symbol": "SPCX", "account": "schwab_individual", "shares": 12},
        {"symbol": "SCHD", "account": "schwab_ira", "shares": 40},
        {"symbol": "CASH", "account": "schwab_ira", "is_cash": True},
        {"symbol": "LOAN", "account": "schwab_individual", "is_loan": True},
    ]
}


def test_an_unstated_scope_is_not_all_accounts():
    env = ObservationEnvelope(dataset="x.json", source_identity="/x.json")
    assert env.account_scope == SCOPE_UNSCOPED
    assert env.account_scope != "ALL_ACCOUNTS"


def test_an_explicit_scope_is_carried(tmp_path):
    (tmp_path / "state.json").write_text('{"ok": true}')
    _payload, env = observe_state_file("state.json", checkout_root=tmp_path,
                                       account_scope="schwab_ira")
    # The file may not resolve under the canonical root; the scope must still be carried, not defaulted.
    assert env.account_scope == "schwab_ira"


def test_holdings_are_keyed_by_symbol_and_account():
    held = held_accounts(HOLDINGS)
    assert held["SPCX"] == {"schwab_individual"}
    assert held["SCHD"] == {"schwab_ira"}
    assert "CASH" not in held and "LOAN" not in held


def test_an_individual_residual_never_holds_an_ira():
    held = held_accounts(HOLDINGS)
    assert held_for(held, "SPCX", "schwab_individual") is True
    assert held_for(held, "SPCX", "schwab_ira") is False, (
        "an Individual residual blocked an IRA re-entry — the cross-account defect FQ-096 names")
    assert held_for(held, "SCHD", "schwab_ira") is True
    assert held_for(held, "SCHD", "schwab_individual") is False


def test_an_unscoped_reader_is_told_the_accounts_not_just_true():
    # Clearing condition (#2603 reviewers, 2026-11-04): an unscoped reader must NOT be told "held".
    # That symbol-wide boolean is the cross-account block. It gets the accounts and decides, or asks.
    held = held_accounts(HOLDINGS)
    assert held_for(held, "SPCX", None) is False
    assert held_in(held, "SPCX") == ["schwab_individual"]  # ...and it is told where


def test_account_of_never_returns_all_accounts():
    assert account_of({"account": "schwab_ira"}) == "schwab_ira"
    assert account_of({}) == SCOPE_UNSCOPED
    assert account_of(None) == SCOPE_UNSCOPED


def test_the_entry_state_runner_uses_the_per_account_view():
    # A cheap textual guard only. The behaviour is pinned by
    # tests/test_account_scope_runner_20261104.py, which calls gather() with a scripted cursor; that
    # file is what fails if the wiring regresses, and it is what a reviewer should read.
    src = (ROOT / "scripts" / "cio_entry_state_runner.py").read_text()
    assert "held_for(held, sym, _acct or None)" in src, "the runner still blocks on a symbol-wide held set"
    assert 'e["held_accounts"]' in src, "the runner does not record which accounts hold the symbol"


def test_the_canonical_observation_module_no_longer_defaults_to_all_accounts():
    src = (ROOT / "scripts" / "lib" / "canonical_observation.py").read_text()
    assert 'account_scope: str = "ALL_ACCOUNTS"' not in src
