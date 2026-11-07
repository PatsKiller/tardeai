"""ANCHOR: DEFENSE_BOOK_SECTOR_SOURCE_20261107 — a company's sector comes from its profile, not a fund seed.

LQ-20261107-224. The /v3/defense/classic "Your book" table showed sector "unknown" for SPCX, T, V,
ANET, PFE and XAR. Two different causes sat behind that one column:

  * the request that builds it 500'd on the default sector (Healthcare), so the page lost the ranks
    it had been served — fixed in LQ-89/LQ-93 on their own branches; and
  * SPCX had no rank to serve at all. ``config/fund_lookthrough.json`` (seeded 2026-07-18) listed it
    as "SPAC and New Issue ETF", a different instrument that shares the ticker string, with
    ``lookthrough: "none"``. Three stores in this system say it is an operating company instead:
    ``symbol_profiles`` (Industrials / Aerospace & Defense, Finviz-sourced) and the Finviz
    enrichment cache ("Space Exploration Technologies Corp.") agree, as does the instrument record.

``book_sector_ranks`` consults the lookthrough seed FIRST and only then ``symbol_profiles``, so one
stale seed line removed the name from the column while the answer was already on file. The seed is
now ``lookthrough: "direct"`` — the company path — and the rules pinned here are:

  1. a symbol the seed calls a blind fund still renders its reason, and is never guessed;
  2. a symbol the seed does not claim resolves through its symbol_profiles sector;
  3. the Finviz name → ETF-label alias map still applies (V's "Financial Services");
  4. ``effective_sector_exposure`` books a company directly to its sector only when the seed does
     not mark it blind — the same correction, on the momentum engine's side of the wall.

Hermetic: a temporary root, an injected cursor and synthetic symbols. No host, no database, no
network, no real instrument names in the fixtures.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fund_lookthrough  # noqa: E402
import sector_leaders_service as svc  # noqa: E402

# The 11-sector strip the rank column is read against, in rank order.
SECTOR_ROWS = [
    {"etf": "XLV", "sector": "Healthcare", "rank": 1},
    {"etf": "XLF", "sector": "Financials", "rank": 2},
    {"etf": "XLI", "sector": "Industrials", "rank": 3},
]

ALIASES = {"sector_aliases": {
    "Financials": ["Financial Services", "Financials"],
    "Industrials": ["Industrials"],
    "Healthcare": ["Healthcare"],
    "Communications": ["Communication Services", "Communications"],
}}


class _Cursor:
    """Only the two calls book_sector_ranks makes on its own cursor."""

    def __init__(self, profile):
        self.profile = profile
        self.params = None

    def execute(self, sql, params=None):
        assert "symbol_profiles" in sql, sql
        self.params = params

    def fetchall(self):
        wanted = set(self.params[0]) if self.params else set()
        return [(s, v) for s, v in self.profile.items() if s in wanted]


def _store(tmp_path, monkeypatch, *, funds, profile, holdings=("TESTX",)):
    """A temporary ROOT with only the files the rank column reads."""
    (tmp_path / "config").mkdir()
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (tmp_path / "config" / "sector_momentum.json").write_text(json.dumps(ALIASES))
    (tmp_path / "config" / "fund_lookthrough.json").write_text(json.dumps({"funds": funds}))
    # The reader looks for this exact name, so build it beside and move it into place rather than
    # truncating a store path mid-write (same rule the repo's protected writers follow).
    draft = state / "holdings.json.draft"
    draft.write_text(json.dumps(
        {"holdings": [{"symbol": s, "market_value": 1000} for s in holdings]}))
    os.replace(draft, state / "holdings.json")
    monkeypatch.setattr(svc, "ROOT", tmp_path)
    monkeypatch.setattr(svc, "_sector_rows", lambda cur: SECTOR_ROWS)
    # fund_lookthrough keeps its own cached ROOT and config; point both at the same store.
    monkeypatch.setattr(fund_lookthrough, "ROOT", tmp_path)
    monkeypatch.setattr(fund_lookthrough, "_CFG", None)
    monkeypatch.setattr(fund_lookthrough, "_CANON", None)
    return _Cursor(profile)


# ── 1. a blind fund still says why ────────────────────────────────────────────────────────────────

def test_a_fund_the_seed_calls_blind_renders_its_reason_and_no_rank(tmp_path, monkeypatch):
    cur = _store(tmp_path, monkeypatch,
                 funds={"TESTF": {"lookthrough": "none", "why": "the factsheet is not on file"}},
                 profile={"TESTF": "Industrials"}, holdings=("TESTF",))
    out = svc.book_sector_ranks(cur=cur)["TESTF"]

    assert out["rank"] is None and out["sector"] is None
    assert out["reason"] == "the factsheet is not on file"


# ── 2. a company resolves through its profile ─────────────────────────────────────────────────────

def test_a_symbol_the_seed_does_not_claim_resolves_from_its_profile(tmp_path, monkeypatch):
    cur = _store(tmp_path, monkeypatch, funds={}, profile={"TESTX": "Industrials"})
    out = svc.book_sector_ranks(cur=cur)["TESTX"]

    assert out["sector"] == "Industrials" and out["rank"] == 3
    assert out["reason"] is None


def test_a_multi_sector_fund_is_a_category_error_not_a_rank(tmp_path, monkeypatch):
    cur = _store(tmp_path, monkeypatch,
                 funds={"TESTW": {"weights": {"Industrials": 0.6, "Healthcare": 0.4}}},
                 profile={"TESTW": "Industrials"}, holdings=("TESTW",))
    out = svc.book_sector_ranks(cur=cur)["TESTW"]

    assert out["rank"] is None and "multi-sector holding" in out["reason"]


# ── 3. the Finviz name goes through the alias map ────────────────────────────────────────────────

def test_a_finviz_sector_name_maps_to_the_etf_label(tmp_path, monkeypatch):
    cur = _store(tmp_path, monkeypatch, funds={}, profile={"TESTV": "Financial Services"},
                 holdings=("TESTV",))
    out = svc.book_sector_ranks(cur=cur)["TESTV"]

    assert out["sector"] == "Financials" and out["rank"] == 2


def test_no_profile_and_no_fund_says_the_sector_is_missing(tmp_path, monkeypatch):
    cur = _store(tmp_path, monkeypatch, funds={}, profile={})
    out = svc.book_sector_ranks(cur=cur)["TESTX"]

    assert out["rank"] is None and out["reason"] == "no sector on symbol_profiles"


# ── 4. the momentum engine's side of the wall agrees ─────────────────────────────────────────────

def test_a_blind_fund_lands_in_not_decomposed(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch,
           funds={"TESTF": {"lookthrough": "none", "why": "no factsheet"}},
           profile={}, holdings=("TESTF",))
    eff = fund_lookthrough.effective_sector_exposure(
        [{"symbol": "TESTF", "sector": "Industrials", "value": 1000}])

    assert [r["symbol"] for r in eff["_not_decomposed"]["positions"]] == ["TESTF"]
    assert eff["_not_decomposed"]["dollars"] == 1000
    assert "Industrials" not in eff


def test_a_company_the_seed_no_longer_blinds_is_booked_to_its_sector(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch,
           funds={"TESTX": {"lookthrough": "direct", "why": "single company"}},
           profile={}, holdings=("TESTX",))
    eff = fund_lookthrough.effective_sector_exposure(
        [{"symbol": "TESTX", "sector": "Industrials", "value": 1000}])

    assert eff["Industrials"]["direct_dollars"] == 1000
    assert eff["_not_decomposed"]["positions"] == []


# ── 5. the shipped seed, on the symbol that was wrong ────────────────────────────────────────────

def test_the_shipped_seed_no_longer_blinds_a_single_company():
    """The 2026-07-18 seed called SPCX a fund with no factsheet; it is an operating company and the
    profile carries its sector. Pin the correction, not the ticker's presence."""
    funds = json.loads((ROOT / "config" / "fund_lookthrough.json").read_text())["funds"]
    entry = funds.get("SPCX") or {}

    assert entry.get("lookthrough") != "none", (
        "SPCX is an operating company (symbol_profiles: Industrials); a blind-fund entry removes it "
        "from the Your-book sector column while the answer is on file")
    assert "SPAC" not in str(entry.get("name", "")), (
        "the seed named a different instrument that shares the ticker string")


def test_the_shipped_seed_combined_with_the_profile_gives_the_rank(tmp_path, monkeypatch):
    """End of the chain the column walks: the shipped seed + the profile sector → a rank, not a
    reason. This is the exact pair that rendered 'unknown' live."""
    shipped = json.loads((ROOT / "config" / "fund_lookthrough.json").read_text())["funds"]
    cur = _store(tmp_path, monkeypatch, funds=shipped,
                 profile={"SPCX": "Industrials"}, holdings=("SPCX",))
    out = svc.book_sector_ranks(cur=cur)["SPCX"]

    assert out["sector"] == "Industrials" and out["rank"] == 3, out
