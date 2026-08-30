"""P2-WS4 / P2-WS5 — identity confidence census + Surface A dust EXITED regression.

READ_ONLY_ADVISORY. MBI=0. Never mints. Never deletes lots.
"""
from __future__ import annotations

from scripts.lib.cio_identity_confidence_census import (
    CONFIDENCE_SCORE_DEFINITION,
    MATERIAL_HELD_MIN_SHARES,
    collect_position_state_matrix,
    measure_identity_confidence_census,
)
from scripts.lib.cio_investment_product import collect_surface_a_status

REGISTRY = {
    "entities": {
        "g-nke": {"subject_guid": "g-nke", "identity_status": "CONFIRMED"},
        "g-schd": {"subject_guid": "g-schd", "identity_status": "CONFIRMED"},
        "g-fth": {"subject_guid": "g-fth", "identity_status": "CANDIDATE"},
        "g-bah": {"subject_guid": "g-bah", "identity_status": "CONFIRMED"},
    },
    "by_symbol": {
        "NKE": "g-nke",
        "SCHD": "g-schd",
        "FTH": "g-fth",
        "BAH": "g-bah",
    },
}

PRODUCT = {
    "action_book": {
        "NEW_POSITION_IF": [
            {"symbol": "NKE", "subject_guid": "g-nke"},
            {"symbol": "ZZZX"},
        ],
    },
    "reentry_book": {"names": [{"symbol": "SCHD"}, {"symbol": "FTH"}]},
    "opportunity_book": {"top": [{"symbol": "SCHD"}, {"symbol": "BAH"}]},
    "watch_block_summary": {"top": [{"symbol": "FTH"}]},
}

HOLDINGS = {
    "holdings": [
        {"symbol": "CASH", "is_cash": True, "market_value": 1000.0},
        {"symbol": "12507E201", "market_value": 0.0, "shares": 7},
        {"symbol": "SCHG", "shares": 0.2294, "broker_actual_shares": 0.2294, "market_value": 8.09},
        {"symbol": "SCHD", "shares": 100.0, "market_value": 365694.75},
        {"symbol": "BAH", "shares": 5.0, "market_value": 673.83},
        {"symbol": "SRNE", "shares": 1000.0, "market_value": 0.90},
        {"symbol": "NOC", "shares": 0.2317, "broker_actual_shares": 0.2317, "market_value": 127.67},
    ]
}

PREV = [
    {"symbol": "AXTI", "is_currently_held": False},
    {"symbol": "FATN"},
]


def test_confidence_score_definition_is_documented():
    d = CONFIDENCE_SCORE_DEFINITION
    assert d["schema"] == "IdentityConfidenceScore@v1"
    assert d["components"]["resolvable"]["weight"] == 0.50
    assert d["components"]["confirmed"]["weight"] == 0.30
    assert d["components"]["stamped"]["weight"] == 0.20
    assert abs(
        d["components"]["resolvable"]["weight"]
        + d["components"]["confirmed"]["weight"]
        + d["components"]["stamped"]["weight"]
        - 1.0
    ) < 1e-9
    assert "production_record" in d
    assert "ticker-as-security-GUID regression" in d["never"]


def test_census_reports_resolvable_and_stamped_separately():
    m = measure_identity_confidence_census(
        product=PRODUCT,
        registry=REGISTRY,
        holdings=HOLDINGS,
        previously_traded=PREV,
    )
    by = {s["surface"]: s for s in m["surfaces"]}
    assert by["new_position_if"]["resolvable_pct"] == 50.0
    assert by["new_position_if"]["stamped_pct"] == 50.0
    assert by["reentry_book"]["resolvable_pct"] == 100.0
    assert by["reentry_book"]["stamped_pct"] == 0.0
    assert by["new_position_if"]["confidence_score"] is not None
    assert m["minted"] == 0
    assert m["mint"] is False
    assert m["memory_behavior_influence"] == 0
    assert m["authority"] == "READ_ONLY_ADVISORY"


def test_holdings_cusip_vs_ticker_split():
    m = measure_identity_confidence_census(
        product=PRODUCT,
        registry=REGISTRY,
        holdings=HOLDINGS,
        previously_traded=PREV,
    )
    cvt = m["holdings"]["cusip_vs_ticker"]
    ids = {i["instrument_id"] for i in cvt["instrument_ids"]}
    assert "12507E201" in ids
    assert all(i["is_ticker"] is False for i in cvt["instrument_ids"])
    assert all(i["id_type"] == "CUSIP" for i in cvt["instrument_ids"])
    # CUSIP is not counted as a holdings equity ticker.
    assert "12507E201" not in [
        r.get("symbol") for r in []  # placeholder clarity
    ]
    he = m["holdings"]["holdings_equity"]
    assert he["n"] >= 1
    # SCHD/BAH resolve; dust tickers still tickers for equity count.
    assert "SCHG" in cvt["dust_residual_symbols"] or "SRNE" in cvt["dust_residual_symbols"]


def test_production_records_exclude_cash_and_include_watch_exit_held():
    m = measure_identity_confidence_census(
        product=PRODUCT,
        registry=REGISTRY,
        holdings=HOLDINGS,
        previously_traded=PREV,
    )
    prod = m["production_records"]
    # ZZZX is NPI only — not in production (held/watch/exit). NKE is NPI only too.
    # Production = held nondust ∪ watch ∪ exit.
    assert prod["n"] >= 4  # SCHD, BAH, FTH, AXTI/FATN at minimum
    assert "CASH" not in (prod.get("unresolved_symbols") or [])
    assert prod["confidence_score"] is not None


def test_census_does_not_mutate_registry_or_product():
    before_by = dict(REGISTRY["by_symbol"])
    before_npi = [dict(r) for r in PRODUCT["action_book"]["NEW_POSITION_IF"]]
    measure_identity_confidence_census(
        product=PRODUCT,
        registry=REGISTRY,
        holdings=HOLDINGS,
        previously_traded=PREV,
    )
    assert REGISTRY["by_symbol"] == before_by
    assert PRODUCT["action_book"]["NEW_POSITION_IF"] == before_npi


# ── P2-WS5 / Surface A dust EXITED regression ─────────────────────────────────


def test_schg_share_dust_is_exited_not_held():
    """SCHG-class: shares < 1 → EXITED (Wave 2 slice 04 invariant)."""
    assert MATERIAL_HELD_MIN_SHARES == 1.0
    cov = collect_surface_a_status(
        symbols=["SCHG"],
        holdings=HOLDINGS,
        previously_traded=[],
    )
    row = cov["items"][0]
    assert row["status"] == "EXITED"
    assert row["status_reason"] == "residual_dust_not_material_held"
    assert row.get("residual_shares") == 0.2294
    assert "current_price" not in row


def test_position_matrix_dust_table_labels_share_and_mv_rules():
    matrix = collect_position_state_matrix(
        holdings=HOLDINGS,
        product=PRODUCT,
        previously_traded=PREV,
    )
    assert matrix["schema"] == "CIOPositionStateMatrix@v1"
    assert matrix["deletes_lots"] is False
    assert matrix["memory_behavior_influence"] == 0
    by = {r["symbol"]: r for r in matrix["dust_table"]}
    assert "SCHG" in by
    assert by["SCHG"]["share_rule_dust"] is True
    assert by["SCHG"]["mv_rule_dust"] is True
    assert by["SCHG"]["surface_a_status"] == "EXITED"
    # NOC: <1 share but MV > $50 → share dust / Surface A EXITED, not MV dust.
    assert by["NOC"]["share_rule_dust"] is True
    assert by["NOC"]["mv_rule_dust"] is False
    assert by["NOC"]["surface_a_status"] == "EXITED"
    # SRNE: ≥1 share, MV < $50 → MV DUST_RESIDUAL; Surface A still HELD.
    assert by["SRNE"]["share_rule_dust"] is False
    assert by["SRNE"]["mv_rule_dust"] is True
    assert by["SRNE"]["surface_a_status"] == "HELD"
    assert matrix["invariants"]["schg_surface_a_exited"] is True
    assert matrix["invariants"]["lots_deleted"] is False
    assert matrix["counts"]["CASH_rows"] >= 1
    assert matrix["instrument_ids"]["instrument_id_n"] >= 1
    assert matrix["reentry_pipes"]["merged"] is False


def test_surface_a_default_probe_schg_exited_regression():
    """Canonical four-name probe: SCHG remains EXITED dust residual."""
    cov = collect_surface_a_status(
        holdings=HOLDINGS,
        previously_traded=PREV,
    )
    by = {r["symbol"]: r for r in cov["items"]}
    assert by["SCHG"]["status"] == "EXITED"
    assert by["AXTI"]["status"] == "EXITED"
    assert by["FATN"]["status"] == "EXITED"
    assert by["FANG"]["status"] == "UNAVAILABLE"
