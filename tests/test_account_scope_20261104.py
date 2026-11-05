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

from lib.account_scope import (  # noqa: E402
    HELD_CONFIRMED,
    HELD_SCOPE_UNKNOWN,
    HELD_UNKNOWN,
    SCOPE_UNSCOPED,
    account_identity_unknown,
    account_of,
    held_accounts,
    held_for,
    held_in,
    holdings_document_known,
    resolve_held,
)
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


def test_an_unscoped_reader_is_told_the_accounts_and_that_it_is_held():
    """claude-lead BLOCK on #2603 (2026-11-05): the earlier clearing condition returned False for an
    unscoped reader whenever the holding named an account — which is EVERY live holding. That took the
    desk's HELD rows from 14 to 0 and let a position the book already holds page BUY_READY. Where the
    position is must still be named; "not held" is reserved for a symbol no account holds."""
    held = held_accounts(HOLDINGS)
    assert held_for(held, "SPCX", None) is True
    assert held_in(held, "SPCX") == ["schwab_individual"]  # ...and it is told where
    assert held_for(held, "NOT_HELD", None) is False


def test_the_scoped_answer_is_still_narrowed_by_the_account():
    """The original FQ-096 defect stays fixed: a scoped row in another account is not held."""
    held = held_accounts(HOLDINGS)
    assert held_for(held, "SPCX", "schwab_ira") is False
    assert held_for(held, "SPCX", "schwab_individual") is True


def test_account_of_never_returns_all_accounts():
    assert account_of({"account": "schwab_ira"}) == "schwab_ira"
    assert account_of({}) == SCOPE_UNSCOPED
    assert account_of(None) == SCOPE_UNSCOPED


def test_the_entry_state_runner_uses_the_per_account_view():
    # A cheap textual guard only. The behaviour is pinned by
    # tests/test_account_scope_runner_20261104.py, which calls gather() with a scripted cursor; that
    # file is what fails if the wiring regresses, and it is what a reviewer should read.
    src = (ROOT / "scripts" / "cio_entry_state_runner.py").read_text()
    assert "resolve_held(" in src, "the runner still ORs an inherited symbol-wide held into a scoped row"
    assert 'e["held_evidence"]' in src, "the runner does not record how sure the held answer is"
    assert 'e["held_accounts"]' in src, "the runner does not record which accounts hold the symbol"


def test_holdings_evidence_distinguishes_confirmed_empty_from_unknown():
    """cx-openai-3 CX3-S-F4: a metadata-only or null document is unknown, not an empty portfolio."""
    assert holdings_document_known({"holdings": []}) is True
    assert holdings_document_known({"holdings": [{"symbol": "SPCX", "account": "a"}]}) is True
    assert holdings_document_known({}) is False                  # metadata only
    assert holdings_document_known({"holdings": None}) is False  # explicit null
    assert holdings_document_known(None) is False                 # failed read
    assert holdings_document_known([]) is False                   # wrong shape


def test_a_named_account_is_decided_by_validated_evidence_alone():
    """cx-openai-3 CX3-S-F1 / cx-openai-2 F1: inheritance must not defeat the scoped lookup."""
    held = held_accounts(HOLDINGS)
    # The inherited symbol-wide flag says held; the only holding is Individual. The IRA row is free.
    assert resolve_held(held, "SPCX", "schwab_ira", inherited=True) == (False, HELD_CONFIRMED)
    assert resolve_held(held, "SPCX", "schwab_individual", inherited=False) == (True, HELD_CONFIRMED)
    # Unscoped keeps the conservative held-somewhere answer.
    assert resolve_held(held, "SPCX", None, inherited=False) == (True, HELD_CONFIRMED)


def test_unknown_or_account_less_evidence_is_never_affirmative_absence():
    held = held_accounts(HOLDINGS)
    assert resolve_held(held, "SPCX", "schwab_ira", inherited=True, evidence_known=False) == (True, HELD_UNKNOWN)
    assert resolve_held(held, "SPCX", "schwab_ira", inherited=False, evidence_known=False) == (False, HELD_UNKNOWN)
    # A holding row with no account: the symbol is in the book, but not attributable to this account.
    unknown = held_accounts({"holdings": [{"symbol": "SPCX", "shares": 3}]})
    assert account_identity_unknown(unknown, "SPCX") is True
    assert resolve_held(unknown, "SPCX", "schwab_ira", inherited=True) == (True, HELD_SCOPE_UNKNOWN)
    assert resolve_held(unknown, "SPCX", "schwab_ira", inherited=False) == (False, HELD_SCOPE_UNKNOWN)


def test_the_canonical_observation_module_no_longer_defaults_to_all_accounts():
    src = (ROOT / "scripts" / "lib" / "canonical_observation.py").read_text()
    assert 'account_scope: str = "ALL_ACCOUNTS"' not in src


def test_account_aliases_are_canonicalized_before_ownership():
    """codex-cloud P1 (account_scope:123): two spellings of one account must decide ownership once.

    config/account_display_names.json declares ``schwab_roth`` -> ``schwab_roth_ira`` (and others).
    A literal set-membership test turned a genuinely held position into a new-position review.
    """
    held = held_accounts({"holdings": [{"symbol": "SPCX", "account": "schwab_roth", "shares": 1}]})
    assert held_for(held, "SPCX", "schwab_roth_ira") is True, (
        "the alias spelling missed the holding row — the account is the same account")
    assert resolve_held(held, "SPCX", "schwab_roth_ira") == (True, HELD_CONFIRMED)

    # ...and the reverse spelling (holdings canonical, candidate aliased).
    canonical = held_accounts({"holdings": [{"symbol": "SPCX", "account": "schwab_roth_ira", "shares": 1}]})
    assert held_for(canonical, "SPCX", "schwab_roth") is True

    # A different account stays a different account.
    assert held_for(held, "SPCX", "schwab_ira") is False
    assert held_for(held, "SPCX", "schwab_individual") is False
    # held_in still names where the position is, in the spelling the source used.
    assert held_in(held, "SPCX") == ["schwab_roth"]
