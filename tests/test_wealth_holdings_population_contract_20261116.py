"""/api/v2/portfolio/holdings population + account identity + portfolio_pct basis (portfolio audit 2026-11-16).

Synthetic fixtures only (QZ* tickers, syn_* accounts). No broker, no DB, no production read or write.

New, additive keys under contract test here:
  * holdings[].portfolio_pct_basis — D2: which value and clock ``portfolio_pct`` was computed on
    (``repricer_stored`` / ``derived_at_read`` / ``not_computed``), set by ``api_v2.portfolio_holdings`` and
    re-declared after the ``cio_truth.holdings_payload`` merge (a stored fact overrides the API row's value).
  * account_labels / account_label_source / account_aliases — F2/A: registry vs derived vs unlabelled names, and
    the registry alias map, so one aliased account is one account and the page never prints a raw key.

Compatibility: the base revision's modules are executed from ``git show`` beside the working tree's, on the same
synthetic state, and the payloads must be identical once the new keys are removed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import api_v2  # noqa: E402
from lib import broker_route_evidence  # noqa: E402
from lib import cio_truth  # noqa: E402

BASE = "c472fd288"
NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
REPRICED = "2026-11-14T14:45:00+00:00"
REGISTRY = {"aliases": {"syn_roth": "syn_roth_ira"}, "names": {"syn_roth_ira": {"name": "Synthetic Roth"}}}
NEW_ROW_KEYS = {"portfolio_pct_basis"}
NEW_TOP_KEYS = {"account_labels", "account_label_source", "account_aliases"}


def _doc() -> dict:
    return {
        "as_of": "2026-11-14",
        "last_repriced": REPRICED,
        "generated_at": REPRICED,
        "portfolio_totals": {"total_value": 1000.0, "day_change": 0.0},
        "account_summaries": {"syn_roth_ira": {"total_value": 500.0}, "syn_taxable": {"total_value": 500.0}},
        "holdings": [
            # stored by the repricer: the served percent is this one, whatever the read's mark
            {"symbol": "QZA", "account": "syn_roth", "shares": 3.0, "price": 100.0, "market_value": 300.0,
             "portfolio_pct": 30.0, "updated_at": REPRICED},
            # no stored percent: derived at read from the read's mark over portfolio_totals.total_value
            {"symbol": "QZB", "account": "syn_taxable", "shares": 2.0, "price": 100.0, "market_value": 200.0,
             "updated_at": REPRICED},
            # a stored zero is "not stored": also derived at read
            {"symbol": "QZC", "account": "syn_taxable", "shares": 1.0, "price": 100.0, "market_value": 100.0,
             "portfolio_pct": 0, "updated_at": REPRICED},
            {"symbol": "CASH", "account": "syn_roth", "is_cash": True, "shares": 400.0, "price": 1.0,
             "market_value": 400.0, "name": "Cash & Cash Investments"},
            # a number-like account key: never echoed by the identity maps
            {"symbol": "QZD", "account": "syn_9876", "shares": 1.0, "price": 50.0, "market_value": 50.0,
             "portfolio_pct": 5.0, "updated_at": REPRICED},
        ],
    }


def _exec_base(rel: str, name: str, package: str | None) -> types.ModuleType:
    """The base revision's source, executed as its own module with the real file path (so PROJECT_ROOT holds)."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE}:{rel}"], check=True, capture_output=True,
                         text=True).stdout
    mod = types.ModuleType(name)
    mod.__file__ = str(ROOT / rel)
    if package:
        mod.__package__ = package
    sys.modules[name] = mod
    exec(compile(src, str(ROOT / rel), "exec"), mod.__dict__)
    return mod


@pytest.fixture(scope="module")
def base():
    try:
        old_cio = _exec_base("scripts/lib/cio_truth.py", "lib.cio_truth_base_20261116", "lib")
        old_api = _exec_base("scripts/api_v2.py", "api_v2_base_20261116", None)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - a shallow clone without the base commit
        pytest.skip(f"base revision {BASE} unavailable: {exc}")
    return types.SimpleNamespace(api=old_api, cio=old_cio)


def _wire(mod, monkeypatch, state: Path) -> None:
    monkeypatch.setattr(mod, "STATE_DIR", state)
    monkeypatch.setattr(mod, "_db_query", lambda *a, **k: [])
    monkeypatch.setattr(mod._acct_disp, "_load", lambda *a, **k: REGISTRY)


@pytest.fixture()
def state(tmp_path, monkeypatch):
    s = tmp_path / "state"
    s.mkdir()
    (s / "holdings.json").write_text(json.dumps(_doc()))
    _wire(api_v2, monkeypatch, s)
    return s


def _document(root: Path) -> dict:
    return cio_truth.resolve(root, NOW, inputs={"holdings": _doc(), "companies": {}, "policy": {}, "cio_status": {},
                                                "broker_stops": [], "finviz_quotes": {}})


def _strip_rows(payload: dict) -> dict:
    out = deepcopy(payload)
    for r in out.get("holdings") or []:
        for k in NEW_ROW_KEYS:
            r.pop(k, None)
    for k in NEW_TOP_KEYS:
        out.pop(k, None)
    return out


def _row(payload: dict, symbol: str) -> dict:
    return next(r for r in payload["holdings"] if r["symbol"] == symbol)


# ── compatibility: identical apart from the new keys ─────────────────────────────────────────────────────────


def test_portfolio_holdings_identical_to_base_apart_from_the_basis(base, state, monkeypatch):
    _wire(base.api, monkeypatch, state)
    old, new = base.api.portfolio_holdings(), api_v2.portfolio_holdings()
    assert "portfolio_pct_basis" not in json.dumps(old)
    assert json.dumps(_strip_rows(new), sort_keys=True, default=str) == json.dumps(old, sort_keys=True, default=str)
    assert all("portfolio_pct_basis" in r for r in new["holdings"])


def test_holdings_payload_identical_to_base_apart_from_the_basis(base, state, tmp_path, monkeypatch):
    _wire(base.api, monkeypatch, state)
    doc = _document(tmp_path)
    old = base.cio.holdings_payload(base.api.portfolio_holdings(), document=deepcopy(doc))
    new = cio_truth.holdings_payload(api_v2.portfolio_holdings(), document=deepcopy(doc))
    assert "portfolio_pct_basis" not in json.dumps(old, default=str)
    assert json.dumps(_strip_rows(new), sort_keys=True, default=str) == json.dumps(old, sort_keys=True, default=str)


def test_route_identical_to_base_apart_from_new_keys(base, state, tmp_path, monkeypatch):
    _wire(base.api, monkeypatch, state)
    doc = _document(tmp_path)
    for mod in (cio_truth, base.cio):  # the route's resolve must never reach the production root
        monkeypatch.setattr(mod, "resolve", lambda *a, **k: deepcopy(doc))
    real_attach = broker_route_evidence.attach
    monkeypatch.setattr(broker_route_evidence, "attach", lambda p, **k: real_attach(p, now=NOW, window=24))
    monkeypatch.setattr(base.api, "_cio_truth_readers", lambda: base.cio)
    old = base.api._cio_holdings_with_evidence()
    new = api_v2._cio_holdings_with_evidence()
    assert NEW_TOP_KEYS <= set(new) and not (NEW_TOP_KEYS & set(old))
    assert set(new) - set(old) == NEW_TOP_KEYS
    assert json.dumps(_strip_rows(new), sort_keys=True, default=str) == json.dumps(old, sort_keys=True, default=str)


# ── D2: portfolio_pct_basis ───────────────────────────────────────────────────────────────────────────────────


def test_basis_names_the_branch_the_producer_took(state):
    rows = api_v2.portfolio_holdings()
    a, b, c, cash = (_row(rows, s) for s in ("QZA", "QZB", "QZC", "CASH"))
    assert a["portfolio_pct"] == 30.0
    assert a["portfolio_pct_basis"]["source"] == "repricer_stored"
    assert a["portfolio_pct_basis"]["snapshot_at"] == REPRICED
    # the stored percent's value is not retained: never back-filled from today's row value
    assert a["portfolio_pct_basis"]["value_usd"] is None and a["portfolio_pct_basis"]["denominator_usd"] is None
    for r in (b, c, cash):
        basis = r["portfolio_pct_basis"]
        assert basis["source"] == "derived_at_read"
        assert basis["value_field"] == "market_value" and basis["denominator_field"] == "portfolio_totals.total_value"
        assert basis["value_usd"] == r["market_value"] and basis["denominator_usd"] == 1000.0
        assert round(basis["value_usd"] / basis["denominator_usd"] * 100, 4) == r["portfolio_pct"]
        assert basis["snapshot_at"] == (r["price_as_of"] or None)  # an empty clock is unknown, never ""


def test_basis_not_computed_when_no_denominator(state):
    doc = _doc()
    doc["portfolio_totals"] = {}
    (state / "holdings.json").write_text(json.dumps(doc))
    b = _row(api_v2.portfolio_holdings(), "QZB")
    assert b["portfolio_pct"] == 0  # the legacy placeholder is unchanged …
    assert b["portfolio_pct_basis"] == {"source": "not_computed", "value_field": None, "value_usd": None,
                                        "denominator_field": None, "denominator_usd": None,
                                        "snapshot_field": None, "snapshot_at": None}  # … and declared as no basis


def test_merge_redeclares_the_basis_of_the_value_it_serves(state, tmp_path):
    doc = _document(tmp_path)
    out = cio_truth.holdings_payload(api_v2.portfolio_holdings(), document=doc)
    a, b, c = (_row(out, s) for s in ("QZA", "QZB", "QZC"))
    # QZA: the fact's stored percent wins the merge, and the basis says stored
    assert a["portfolio_pct"] == 30.0 and a["portfolio_pct_basis"]["source"] == "repricer_stored"
    assert a["portfolio_pct_basis"]["snapshot_at"] == doc["portfolio"]["quote_as_of"]
    # QZB: no stored key on the fact, the API row's derived value and basis survive together
    assert b["portfolio_pct_basis"]["source"] == "derived_at_read"
    assert b["portfolio_pct"] == round(b["portfolio_pct_basis"]["value_usd"] / 1000.0 * 100, 4)
    # QZC: the fact carries a stored 0, which overrides the API row's derived value: no basis, said so
    assert not c["portfolio_pct"] and c["portfolio_pct_basis"]["source"] == "not_computed"


def test_merge_without_an_api_row_declares_no_basis():
    fact = {"symbol": "QZX", "account_id": "syn_taxable"}
    assert cio_truth._pct_basis_after_merge(fact, dict(fact), REPRICED)["source"] == "not_computed"


# ── F2/A: account identity ───────────────────────────────────────────────────────────────────────────────────


def test_identity_resolves_registry_derived_and_aliases(state):
    payload = {"holdings": [{"account": "syn_roth"}, {"account_key": "syn_roth_ira"}, {"account": "syn_taxable"},
                            {"account": "syn_9876"}],
               "reconciliation": {"accounts": [{"account": "syn_roth_ira"}]},
               "scope_coverage": {"scope": {"accounts": ["syn_roth_ira", "syn_taxable"]}}}
    ident = api_v2._holdings_account_identity(payload)
    # one registry-aliased account is ONE canonical account, never two
    assert ident["account_aliases"] == {"syn_roth": "syn_roth_ira"}
    assert ident["account_labels"] == {"syn_roth_ira": "Synthetic Roth", "syn_taxable": "Syn Taxable"}
    assert ident["account_label_source"] == {"syn_roth_ira": "registry", "syn_taxable": "derived"}
    assert "9876" not in json.dumps(ident)


def test_identity_never_raises_into_the_route(state, tmp_path, monkeypatch):
    doc = _document(tmp_path)
    monkeypatch.setattr(cio_truth, "resolve", lambda *a, **k: deepcopy(doc))
    monkeypatch.setattr(api_v2, "_holdings_account_identity", lambda p: 1 / 0)
    out = api_v2._cio_holdings_with_evidence()
    assert out["holdings"] and not (NEW_TOP_KEYS & set(out))


def test_identity_on_the_route_names_every_served_account(state, tmp_path, monkeypatch):
    doc = _document(tmp_path)
    monkeypatch.setattr(cio_truth, "resolve", lambda *a, **k: deepcopy(doc))
    out = api_v2._cio_holdings_with_evidence()
    served = {r["account_id"] for r in out["holdings"] if "9876" not in r["account_id"]}
    assert served <= set(out["account_label_source"])
    assert out["account_label_source"]["syn_roth_ira"] == "registry"
    assert "9876" not in json.dumps({k: out[k] for k in NEW_TOP_KEYS})
