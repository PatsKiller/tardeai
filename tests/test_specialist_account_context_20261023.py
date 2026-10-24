"""Actual specialist context over scratch holdings and injected read-only rows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import process_watchlist_agent_jobs as jobs
from lib import account_display as accounts


class Cursor:
    def execute(self, sql, params=()):
        assert sql.lstrip().startswith("SELECT"), sql

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


class Connection:
    def cursor(self, **kwargs):
        return Cursor()

    def commit(self):
        pass


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "STATE_DIR", tmp_path)

    def build(rows):
        path = tmp_path / "holdings.json"
        original = json.dumps({"holdings": rows})
        path.write_text(original)
        result = jobs._get_context(Connection(), "NVDA")
        assert path.read_text() == original
        return result

    return build


def row(account, **extra):
    return {"symbol": "NVDA", "account": account, "shares": 0.125, "market_value": 10.0, **extra}


def test_taxable_holding_overrides_stale_ira_label_in_text_and_snapshot(context):
    result = context([row("moomoo_taxable_live", account_name="stale IRA location")])
    assert "moomoo Taxable (type=taxable, status=operator_confirmed)" in result["text"]
    assert "account: moomoo Taxable" in result["text"]
    assert "stale IRA location" not in json.dumps(result)
    assert result["snapshot"]["position"]["account_name"] == "moomoo Taxable"
    assert result["snapshot"]["position_accounts"][0]["account_type"] == "taxable"
    assert result["snapshot"]["position"]["shares"] == 0.125


def test_all_held_accounts_are_in_context_without_inventing_one_tax_location(context):
    result = context([row("moomoo_taxable_live"), row("schwab_roth")])
    assert len(result["snapshot"]["position_accounts"]) == 2
    assert "moomoo Taxable (type=taxable" in result["text"]
    assert "Schwab Roth IRA (type=roth_ira" in result["text"]
    assert "Evaluate each held account separately" in result["text"]


def test_unknown_or_numbered_account_never_infers_ira_or_exposes_digits(context):
    result = context([row("12345678", account_id="...678", account_number="12345678")])
    assert "Unlabelled account (type=unknown, status=unknown)" in result["text"]
    assert "12345678" not in json.dumps(result)
    assert "...678" not in json.dumps(result)
    assert result["snapshot"]["position_accounts"][0]["account_type"] == "unknown"


def test_unheld_symbol_has_no_account_claim(context):
    result = context([])
    assert "NOT CURRENTLY HELD" in result["text"]
    assert result["snapshot"]["position"] is None
    assert result["snapshot"]["position_accounts"] == []
    assert "CURRENT ACCOUNT LOCATION" not in result["text"]


def test_registry_metadata_status_and_missing_type_are_preserved(monkeypatch):
    monkeypatch.setattr(
        accounts, "_load", lambda: {"names": {"fixture": {"name": "Fixture account", "status": "proposed"}}}
    )
    facts = accounts.location_facts({"account": "fixture"})
    assert facts["account_name"] == "Fixture account"
    assert facts["account_type"] == "unknown"
    assert facts["account_name_status"] == "proposed"
    assert facts["account_metadata_source"] == "config/account_display_names.json"
