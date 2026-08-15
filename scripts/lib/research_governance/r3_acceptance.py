"""RGA-15 Almanac reproduction acceptance."""
from __future__ import annotations

from .almanac import (
    AUTHORITY,
    MAX_INFLUENCE_PCT,
    bundle,
    is_midterm_year,
    load_monthly_fixture,
    presidential_cycle_label,
    reproduce_slice,
)
from .enums import GateState
from .source_catalog import load_sources


def _pass(d: str) -> tuple[str, str]:
    return GateState.PASS.value, d


def _fail(d: str) -> tuple[str, str]:
    return GateState.FAIL.value, d


def check_almanac_reproduction() -> tuple[str, str]:
    srcs = {s["source_id"]: s for s in load_sources()}
    sta = srcs.get("stock_traders_almanac")
    if not sta:
        return _fail("stock_traders_almanac missing from catalog")
    if sta.get("claim_status") != "SOURCE_CLAIM_INCOMPLETE":
        return _fail("STA book must remain SOURCE_CLAIM_INCOMPLETE (no full text)")
    if not is_midterm_year(2026) or presidential_cycle_label(2026) != "midterm_year":
        return _fail("2026 must be mechanical midterm_year")
    rows = load_monthly_fixture()
    if len(rows) < 100:
        return _fail("fixture too small")
    pack = bundle(as_of_year=2026)
    if pack["authority"] != AUTHORITY:
        return _fail("authority drifted")
    if pack["partisan_conclusion"] is not None:
        return _fail("partisan conclusion must be null")
    if pack["standalone_sell"] or pack["creates_trim"]:
        return _fail("almanac must not sell or TRIM")
    if pack["fulltext"]:
        return _fail("fulltext flag must be false")
    if pack["august_hardcoded_bearish"]:
        return _fail("August must not be hardcoded bearish")
    for key in ("august_general", "september_general", "august_midterm", "september_midterm"):
        sl = pack["slices"][key]
        layers = sl["layers"]
        if set(layers) != {"source_claim", "trade_ai_reproduction", "current_application"}:
            return _fail(f"{key} layers collapsed or missing")
        claim = layers["source_claim"]
        if not claim.get("citation_only") or claim.get("fulltext"):
            return _fail(f"{key} is not citation-only")
        if not claim.get("url") or not claim.get("title") or not claim.get("date"):
            return _fail(f"{key} missing public alert citation")
        if sl["n"] in (None, 0):
            return _fail(f"{key} reproduction empty")
        app = layers["current_application"]
        if app.get("max_influence_pct") > MAX_INFLUENCE_PCT:
            return _fail("influence cap exceeded")
        if app.get("partisan_conclusion") is not None:
            return _fail("slice partisan conclusion not null")
    ch = pack["calendar_family_challenge"]
    if ch.get("status") not in {"OK", "UNAVAILABLE"}:
        return _fail(f"family challenge bad status {ch}")
    if ch.get("status") == "OK" and (ch.get("n_rules") or 0) < 2:
        return _fail("STW family must have >= 2 rules")
    if ch.get("winner_only"):
        return _fail("calendar challenge must not be winner-only")
    # August is in weak set only if stats put it there
    aug = pack["slices"]["august_general"]
    if pack["august_in_weak_set"] and aug["mean"] is None:
        return _fail("August in weak set without mean")
    return _pass("Almanac layers, citations, fixture reproduction, family challenge, no TRIM/sell")


CHECKS = {"RGA-15": check_almanac_reproduction}
