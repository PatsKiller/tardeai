"""Wave 2 slices 13 / 14 — identity coverage measured, never minted.

13  % subject_guid on NEW_POSITION_IF / reentry / watch, reported as two
    distinct numbers: `resolvable` (registry can answer) and `stamped` (the
    payload row carries the guid).
14  would_register for held (non-dust) + active watch, capped at 30, dry by
    default and refused above the cap.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from scripts.lib.cio_identity_coverage import (
    REGISTER_CAP,
    apply_registerable,
    collect_registerable,
    measure_identity_coverage,
)

# by_symbol → entity; matches identity_registry.lookup_symbol's expectations.
REGISTRY = {
    "entities": {
        "g-schd": {"subject_guid": "g-schd", "identity_status": "CONFIRMED"},
        "g-nke": {"subject_guid": "g-nke", "identity_status": "CONFIRMED"},
        "g-fth": {"subject_guid": "g-fth", "identity_status": "CANDIDATE"},
    },
    "by_symbol": {"SCHD": "g-schd", "NKE": "g-nke", "FTH": "g-fth"},
}

PRODUCT = {
    "action_book": {
        "NEW_POSITION_IF": [
            {"symbol": "NKE", "subject_guid": "g-nke"},
            {"symbol": "ZZZX"},                          # unresolved, unstamped
        ],
    },
    "reentry_book": {"names": [{"symbol": "SCHD"}, {"symbol": "FTH"}]},
    "opportunity_book": {"top": [{"symbol": "SCHD"}]},
    "watch_block_summary": {"top": [{"symbol": "FTH"}]},
}


def test_resolvable_and_stamped_are_reported_separately():
    m = measure_identity_coverage(product=PRODUCT, registry=REGISTRY)
    by = {s["surface"]: s for s in m["surfaces"]}

    npi = by["new_position_if"]
    assert npi["n"] == 2
    assert npi["resolvable_n"] == 1 and npi["resolvable_pct"] == 50.0
    assert npi["stamped_n"] == 1 and npi["stamped_pct"] == 50.0
    assert npi["unresolved_symbols"] == ["ZZZX"]

    # These surfaces resolve but ship no guid — the whole point of two numbers.
    assert by["reentry_book"]["resolvable_pct"] == 100.0
    assert by["reentry_book"]["stamped_pct"] == 0.0
    assert by["watch_block"]["resolvable_pct"] == 100.0
    assert by["watch_block"]["stamped_pct"] == 0.0


def test_totals_and_no_mint_contract():
    m = measure_identity_coverage(product=PRODUCT, registry=REGISTRY)
    assert m["total_rows"] == 6          # 2 NPI + 2 reentry + 1 opp + 1 watch
    assert m["total_resolvable"] == 5    # everything but ZZZX
    assert m["total_stamped"] == 1       # only the NKE row carries a guid
    assert m["minted"] == 0
    assert m["mint"] is False
    assert m["financial_action"] is False
    assert m["memory_behavior_influence"] == 0
    assert m["authority"] == "READ_ONLY_ADVISORY"


def test_measure_does_not_mutate_the_registry_or_the_product():
    before_reg = {k: dict(v) if isinstance(v, dict) else v for k, v in REGISTRY.items()}
    before_rows = [dict(r) for r in PRODUCT["reentry_book"]["names"]]
    measure_identity_coverage(product=PRODUCT, registry=REGISTRY)
    assert REGISTRY["by_symbol"] == before_reg["by_symbol"]
    assert len(REGISTRY["entities"]) == len(before_reg["entities"])
    # no guid was written onto a row that did not have one
    assert PRODUCT["reentry_book"]["names"] == before_rows
    assert all("subject_guid" not in r for r in PRODUCT["reentry_book"]["names"])


def test_empty_surface_reports_none_pct_not_zero_division():
    m = measure_identity_coverage(product={}, registry=REGISTRY)
    for s in m["surfaces"]:
        assert s["n"] == 0
        assert s["resolvable_pct"] is None
        assert s["stamped_pct"] is None
    assert m["total_resolvable_pct"] is None


# ── slice 14 ─────────────────────────────────────────────────────────────────

HOLDINGS = {
    "holdings": [
        {"symbol": "CASH", "is_cash": True, "market_value": 100.0},
        {"symbol": "12507E201", "market_value": 0.0},          # CUSIP
        {"symbol": "SCHG", "market_value": 8.09},              # dust
        {"symbol": "SCHD", "market_value": 365694.75},         # known
        {"symbol": "BAH", "market_value": 673.83},             # missing
    ]
}


def test_would_register_skips_cash_cusip_dust_and_known_symbols():
    dry = collect_registerable(product=PRODUCT, registry=REGISTRY, holdings=HOLDINGS)
    syms = [r["symbol"] for r in dry["would_register"]]
    assert "BAH" in syms                    # held, non-dust, not in registry
    assert "SCHD" not in syms               # already registered
    assert "SCHG" not in syms               # dust
    assert "12507E201" not in syms          # instrument id, not a ticker
    assert "CASH" not in syms
    assert dry["held_non_dust_n"] == 2


def test_would_register_reasons_distinguish_held_from_watch():
    dry = collect_registerable(product=PRODUCT, registry=REGISTRY, holdings=HOLDINGS)
    by = {r["symbol"]: r["reason"] for r in dry["would_register"]}
    assert by["BAH"] == "held_non_dust"
    assert by.get("ZZZX") is None           # NEW_POSITION_IF is not a register source


def test_apply_is_refused_above_the_cap():
    # Alphabetic tickers only — a digit makes _looks_like_ticker reject the row.
    over = {"holdings": [
        {"symbol": f"Q{chr(65 + i // 26)}{chr(65 + i % 26)}", "market_value": 1000.0}
        for i in range(REGISTER_CAP + 5)
    ]}
    dry = collect_registerable(product={}, registry=REGISTRY, holdings=over)
    assert dry["would_register_n"] > REGISTER_CAP
    assert dry["over_cap"] is True
    assert dry["apply_allowed"] is False
    res = apply_registerable(dry, apply=True)
    assert res["applied"] is False
    assert res["refused"] is True
    assert str(REGISTER_CAP) in res["reason"]


def test_dry_by_default_never_writes():
    dry = collect_registerable(product=PRODUCT, registry=REGISTRY, holdings=HOLDINGS)
    res = apply_registerable(dry, apply=False)
    assert res["applied"] is False
    assert res["refused"] is False
    assert res["registry"]["applied"] is False
