"""Wave 2 slice 04: Surface A former-sold → HELD|EXITED|UNAVAILABLE. No prices."""
from __future__ import annotations

from scripts.lib.cio_investment_product import collect_surface_a_status


def test_schg_dust_is_exited_not_held():
    holdings = {"holdings": [{
        "symbol": "SCHG",
        "shares": 0.2294,
        "broker_actual_shares": 0.2294,
        "market_value": 8.09,
        "portfolio_pct": 0.0006,
    }]}
    cov = collect_surface_a_status(
        symbols=["SCHG"],
        holdings=holdings,
        previously_traded=[],
    )
    row = cov["items"][0]
    assert row["status"] == "EXITED"
    assert row["status_reason"] == "residual_dust_not_material_held"
    assert row.get("residual_shares") == 0.2294
    assert "current_price" not in row
    assert "last_exit_price" not in row


def test_material_held_is_held():
    holdings = {"holdings": [{"symbol": "NOC", "shares": 10.0}]}
    cov = collect_surface_a_status(
        symbols=["NOC"],
        holdings=holdings,
        previously_traded=[],
    )
    assert cov["items"][0]["status"] == "HELD"


def test_previously_traded_is_exited():
    cov = collect_surface_a_status(
        symbols=["AXTI"],
        holdings={"holdings": []},
        previously_traded=[{"symbol": "AXTI", "is_currently_held": False}],
    )
    assert cov["items"][0]["status"] == "EXITED"
    assert cov["items"][0]["status_reason"] == "previously_traded"


def test_fang_unavailable_when_absent():
    cov = collect_surface_a_status(
        symbols=["FANG"],
        holdings={"holdings": []},
        previously_traded=[],
    )
    assert cov["items"][0]["status"] == "UNAVAILABLE"


def test_probe_four_default_names_no_prices():
    cov = collect_surface_a_status(
        holdings={"holdings": [{"symbol": "SCHG", "shares": 0.2}]},
        previously_traded=[
            {"symbol": "AXTI"},
            {"symbol": "FATN"},
        ],
    )
    by = {r["symbol"]: r["status"] for r in cov["items"]}
    assert by["SCHG"] == "EXITED"
    assert by["AXTI"] == "EXITED"
    assert by["FATN"] == "EXITED"
    assert by["FANG"] == "UNAVAILABLE"
    for r in cov["items"]:
        assert "current_price" not in r
        assert "pct_above_exit" not in r
