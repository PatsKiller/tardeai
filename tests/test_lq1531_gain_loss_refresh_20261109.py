"""The Schwab sync refreshes unrealized P/L after it rewrites market value.

ANCHOR: LQ1531_GAIN_LOSS_REFRESH_20261109

An existing aligned row used to keep its previous gain_loss when price and
market value changed. The financial-truth gate treats that gap as upl_mismatch
and withholds sizing. This refreshes display arithmetic only. Synthetic rows.
The builder does not write the served book.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TRADE_AI_CI", "1")

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

_ORDER_KEYS = (
    "recommended_delta_usd",
    "size_usd",
    "order",
    "stop",
    "limit",
    "target_weight_pct",
    "trade",
    "execution",
)


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sync = _load("schwab_position_sync_lq1531", "scripts/schwab_position_sync.py")
gate = _load("cio_financial_truth_gate_lq1531", "scripts/lib/cio_financial_truth_gate.py")


def _served_holdings() -> Path:
    override = os.environ.get("LQ1531_HOLDINGS_STAT")
    if override:
        return Path(override)
    return (
        Path.home()
        / "trade-ai-releases"
        / "persistent-state"
        / "data"
        / "portfolios"
        / "state"
        / "holdings.json"
    )


def _live(symbol: str, qty: float, price: float, avg: float) -> dict:
    return {
        "symbol": symbol,
        "qty": qty,
        "current_price": price,
        "market_value": round(qty * price, 2),
        "avg_entry_price": avg,
    }


def _prior(symbol: str, **extra) -> dict:
    row = {
        "symbol": symbol,
        "account": "synth_ira",
        "shares": 10.0,
        "system_shares": 10.0,
        "market_value": 1100.0,
        "gain_loss": 50.0,
        "gain_loss_pct": 5.0,
        "share_drift_status": "aligned",
    }
    row.update(extra)
    return row


def _one(symbol: str, live: dict, prior: dict | None) -> dict:
    existing = {} if prior is None else {(symbol, "synth_ira"): prior}
    rows, events = sync._build_account_rows("synth_ira", [live], existing)
    assert events == []
    assert len(rows) == 1
    return rows[0]


def _types(row: dict) -> set[str]:
    report = gate.check_position_row(row, portfolio_value=10_000.0)
    return {item["type"] for item in report["exceptions"]}


def test_aligned_existing_row_refreshes_gain_loss_from_market_value():
    prior = _prior("SYN", cost_basis=1000.0, cost_basis_source="broker_api")
    row = _one("SYN", _live("SYN", 10, 120, 100), prior)
    assert row["share_drift_status"] == "aligned"
    assert row["shares"] == 10.0
    assert row["market_value"] == 1200.0
    assert row["cost_basis"] == 1000.0
    assert row["gain_loss"] == 200.0
    assert row["gain_loss_pct"] == 20.0
    for key in _ORDER_KEYS:
        assert key not in row


def test_missing_or_non_positive_basis_does_not_invent_gain_loss():
    missing = _one("SYN", _live("SYN", 10, 120, 100), _prior("SYN"))
    assert "cost_basis" not in missing
    assert missing["market_value"] == 1200.0
    assert missing["gain_loss"] == 50.0

    zero = _one("SYN", _live("SYN", 10, 120, 100), _prior("SYN", cost_basis=0))
    assert zero["cost_basis"] == 0
    assert zero["gain_loss"] == 50.0
    assert zero["gain_loss_pct"] == 5.0

    blank = {"market_value": 1200.0, "cost_basis": "n/a", "gain_loss": 50.0}
    sync._refresh_gain_loss(blank)
    assert blank["gain_loss"] == 50.0
    assert "gain_loss_pct" not in blank

    absent = {"market_value": 1200.0}
    sync._refresh_gain_loss(absent)
    assert "gain_loss" not in absent
    assert "cost_basis" not in absent


def test_new_row_sets_basis_then_gain_loss():
    row = _one("SYN", _live("SYN", 10, 120, 100), None)
    assert row["cost_basis"] == 1000.0
    assert row["cost_basis_source"] == "broker_api"
    assert row["gain_loss"] == 200.0
    assert row["gain_loss_pct"] == 20.0


def test_auto_applied_share_change_rebases_basis_and_refreshes_gain_loss():
    prior = _prior("SYN", cost_basis=1000.0, cost_basis_source="broker_api")
    row = _one("SYN", _live("SYN", 20, 120, 100), prior)
    assert row["share_drift_status"] == "auto_applied"
    assert row["shares"] == 20.0
    assert row["cost_basis"] == 2000.0
    assert row["market_value"] == 2400.0
    assert row["gain_loss"] == 400.0
    assert row["gain_loss_pct"] == 20.0


def test_delisted_row_refreshes_after_market_value_is_zeroed():
    prior = _prior("ZZ1234567", cost_basis=1000.0, gain_loss=50.0)
    row = _one("ZZ1234567", _live("ZZ1234567", 10, 120, 100), prior)
    assert row["delisted"] is True
    assert row["market_value"] == 0.0
    assert row["cost_basis"] == 1000.0
    assert row["gain_loss"] == -1000.0
    assert row["gain_loss_pct"] == -100.0


def test_refresh_follows_a_later_basis_reassignment():
    row = {"market_value": 1200.0, "cost_basis": 1000.0, "gain_loss": 50.0, "gain_loss_pct": 5.0}
    sync._refresh_gain_loss(row)
    assert row["gain_loss"] == 200.0
    row["cost_basis"] = 800.0
    sync._refresh_gain_loss(row)
    assert row["gain_loss"] == 400.0
    assert row["gain_loss_pct"] == 50.0


def test_gate_reports_upl_mismatch_on_the_stale_row_only():
    prior = _prior(
        "SYN",
        cost_basis=1000.0,
        portfolio_pct=12.0,
        source_as_of="2026-11-09T13:50:00+00:00",
    )
    rebuilt = _one("SYN", _live("SYN", 10, 120, 100), prior)
    stale = dict(rebuilt)
    stale["gain_loss"] = 50.0
    stale["gain_loss_pct"] = 5.0
    assert "upl_mismatch" in _types(stale)
    assert "upl_mismatch" not in _types(rebuilt)
    assert "upl_pct_mismatch" not in _types(rebuilt)


def test_emulation_writes_only_the_temp_book(tmp_path, monkeypatch):
    live = _served_holdings()
    assert live.is_file(), "served holdings book is not present"
    live_before = live.stat().st_mtime_ns
    module_book = Path(sync.HOLDINGS_PATH)
    module_existed = module_book.exists()
    module_before = module_book.stat().st_mtime_ns if module_existed else None

    scratch = tmp_path / "project"
    state = scratch / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    monkeypatch.setattr(sync, "PROJECT_ROOT", scratch)
    monkeypatch.setattr(sync, "HOLDINGS_PATH", state / "holdings.json")

    prior = _prior("SYN", cost_basis=1000.0, cost_basis_source="broker_api")
    row = _one("SYN", _live("SYN", 10, 120, 100), prior)
    dest = Path(sync.HOLDINGS_PATH)
    dest.write_text(json.dumps({"holdings": [row]}), encoding="utf-8")
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded["holdings"][0]["gain_loss"] == 200.0
    assert loaded["holdings"][0]["gain_loss_pct"] == 20.0
    assert dest.is_relative_to(tmp_path)

    assert live.stat().st_mtime_ns == live_before
    assert module_book.exists() == module_existed
    if module_existed:
        assert module_book.stat().st_mtime_ns == module_before
