"""Company names the house already holds resolve to their symbols.

2026-09-13: "what's the outlook for SpaceX" resolved no symbol and was about to be
refused as unanswerable. The book holds 400 SPCX; the identity registry has it
CONFIRMED; config/ipo_lockups.json records "SpaceX (Space Exploration Technologies
Corp)"; symbol_profiles describes "Space Exploration Technologies Corp. provides ...".
The name index knew only the Schwab instrument sweep. Offline: lockups and profile
rows are injected; the database is never touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import company_name_index as cni  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    inst = tmp_path / "instruments.json"
    from scripts.lib.schwab_instrument_evidence import SCHEMA  # noqa: PLC0415
    inst.write_text(json.dumps({"schema": SCHEMA, "instruments": {
        "SPCE": {"description": "VIRGIN GALACTIC HOLDINGS INC", "identifiers": {"cusip": "T1"}},
        "NOC": {"description": "NORTHROP GRUMMAN CORP", "identifiers": {"cusip": "T2"}},
    }}), encoding="utf-8")
    monkeypatch.setenv("TRADEAI_SCHWAB_INSTRUMENT_EVIDENCE", str(inst))
    lock = tmp_path / "ipo_lockups.json"
    lock.write_text(json.dumps({"lockups": {"SPCX": {"company": "SpaceX (Space Exploration Technologies Corp)"}}}), encoding="utf-8")
    monkeypatch.setenv("TRADEAI_IPO_LOCKUPS", str(lock))
    monkeypatch.setenv("TRADEAI_HOUSE_NAMES_DB", "0")
    cni.refresh()
    yield
    cni.refresh()


@pytest.mark.parametrize("name", ["SpaceX", "spacex", "Space Exploration Technologies", "Space Exploration Technologies Corp."])
def test_lockup_company_field_resolves_brand_and_legal_name(name):
    hit = cni.resolve_name(name)
    assert hit and hit["symbol"] == "SPCX", (name, hit)


def test_negative_control_without_house_names_spacex_does_not_resolve(monkeypatch):
    monkeypatch.setattr(cni, "_house_names", lambda: [])
    cni.refresh()
    assert cni.resolve_name("SpaceX") is None


def test_instrument_feed_names_still_resolve_and_are_not_overridden():
    assert cni.resolve_name("Northrop Grumman")["symbol"] == "NOC"


def test_a_house_name_colliding_with_a_feed_name_stays_ambiguous(monkeypatch, tmp_path):
    lock = tmp_path / "l2.json"
    lock.write_text(json.dumps({"lockups": {"XNOC": {"company": "Northrop Grumman Corp"}}}), encoding="utf-8")
    monkeypatch.setenv("TRADEAI_IPO_LOCKUPS", str(lock))
    cni.refresh()
    assert cni.resolve_name("Northrop Grumman") is None, "two symbols for one name: never pick a winner"


@pytest.mark.parametrize("desc,expected", [
    ("Space Exploration Technologies Corp. provides satellite-based broadband services.", "Space Exploration Technologies Corp"),
    ("Northrop Grumman Corporation operates as an aerospace and defense company.", "Northrop Grumman Corporation"),
    ("Visa Inc., together with its subsidiaries, operates as a payments technology company.", "Visa Inc"),
    ("", None),
    ("The fund seeks to track the total return of a broad index of large and mid cap growth stocks in the US.", None),
])
def test_company_phrase_takes_the_leading_name_only(desc, expected):
    assert cni.company_phrase(desc) == expected


def test_profile_names_come_through_the_broker_projection_for_held_symbols_only(monkeypatch, tmp_path):
    hold = tmp_path / "holdings.json"
    hold.write_text(json.dumps({"holdings": [{"symbol": "ACME"}]}), encoding="utf-8")
    monkeypatch.setenv("TRADEAI_HOLDINGS_PATH", str(hold))
    monkeypatch.setenv("TRADEAI_HOUSE_NAMES_DB", "1")
    monkeypatch.delenv("TRADE_AI_CI", raising=False)
    monkeypatch.setenv("DB_PASSWORD", "test-only")
    seen = {}
    import scripts.lib.data_broker.symbol_profile as sp  # noqa: PLC0415

    def fake_profiles(db_query, symbols):
        seen["symbols"] = list(symbols)
        return {"ACME": {"description": "Acme Rocket Works Inc. designs reusable launch vehicles."}}

    monkeypatch.setattr(sp, "get_symbol_profiles", fake_profiles)
    cni.refresh()
    assert cni.resolve_name("Acme Rocket Works")["symbol"] == "ACME"
    assert seen["symbols"] == ["ACME"], "only held symbols are looked up"


def test_profile_names_are_off_in_ci_and_without_credentials(monkeypatch):
    monkeypatch.setenv("TRADEAI_HOUSE_NAMES_DB", "1")
    monkeypatch.setenv("TRADE_AI_CI", "1")
    assert cni._profile_names() == []
    monkeypatch.delenv("TRADE_AI_CI", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    assert cni._profile_names() == []
