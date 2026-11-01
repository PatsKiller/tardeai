"""Look-through exposure of each held position to the engine's sector and theme groups (precision PR).

Operator 2026-10-31: the look-through of growth funds and private-company proxies behind the AI theme. Sources, in order,
never guessed:
1. ETF sector and industry weights from ``config/fund_lookthrough.json`` (provider factsheets; the same file the
   Defense desk uses). ``lookthrough: none`` stays UNKNOWN with its reason.
2. ETF top holdings from the ``etf_holdings_snapshot`` store (writer ``scripts/lib/writers/etf_holdings_writer.py``)
   give the AI-basket share and the holdings reporting inside the earnings window.
3. A single stock maps to its own sector (``symbol_profiles``) plus the AI basket and semis when it is a member.
4. A recent IPO listed in ``config/ipo_lockups.json`` is a single stock, even when ``fund_lookthrough.json`` still
   carries an older fund under the same ticker (a ticker reused after a fund closed: that entry describes the old
   fund; the ticker is now an operating company's equity). The stale entry is reported, never used.

Output per symbol: ``{groups: {group_key: share}, ai_share, reporting: [...], basis, note}`` — shares of the position,
never an amount (MBI_BEHAVIOR = 0; positions arrive as symbols only).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

SECTOR_TO_GROUP = {
    "technology": "tech",
    "information technology": "tech",
    "communications": "comm",
    "communication services": "comm",
    "consumer discretionary": "discretionary",
    "consumer cyclical": "discretionary",
    "consumer staples": "staples",
    "consumer defensive": "staples",
    "healthcare": "healthcare",
    "health care": "healthcare",
    "utilities": "utilities",
    "energy": "energy",
    "financials": "financials",
    "financial services": "financials",
    "industrials": "industrials",
    "materials": "materials",
    "basic materials": "materials",
    "real estate": "real_estate",
}
SEMI_INDUSTRIES = ("semiconductor",)
#: theme groups overlap sectors (a theme weight is extra, never part of the sector partition)
THEME_GROUPS = ("ai_basket", "semis")
SEGMENT_SUM_TOLERANCE = 0.01
ALIASES = {"GOOG": "GOOGL"}


def _load(name: str) -> dict[str, Any]:
    try:
        return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def exposure_for(
    symbol: str,
    *,
    ai_basket: list[str],
    holdings: dict[str, list[dict[str, Any]]] | None = None,
    profiles: dict[str, dict[str, Any]] | None = None,
    reporting_soon: set[str] | None = None,
    fund_cfg: dict[str, Any] | None = None,
    ipos: dict[str, Any] | None = None,
    themes: dict[str, list[str]] | None = None,
    segments_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = _exposure_for(
        symbol,
        ai_basket=ai_basket,
        holdings=holdings,
        profiles=profiles,
        reporting_soon=reporting_soon,
        fund_cfg=fund_cfg,
        ipos=ipos,
        segments_cfg=segments_cfg,
    )
    extra = (themes or {}).get(str(symbol).upper()) or []
    if extra:
        # operator-owned theme mapping (config positions.theme_overrides): a stock held as a theme exposure that its
        # own sector does not show gets those groups at full weight beside its sector — never inferred by code
        out["groups"] = {**(out.get("groups") or {}), **{g: 1.0 for g in extra}}
        out["basis"] = (out.get("basis") or "") + " + operator theme override"
    return out


def _exposure_for(
    symbol: str,
    *,
    ai_basket: list[str],
    holdings: dict[str, list[dict[str, Any]]] | None = None,
    profiles: dict[str, dict[str, Any]] | None = None,
    reporting_soon: set[str] | None = None,
    fund_cfg: dict[str, Any] | None = None,
    ipos: dict[str, Any] | None = None,
    segments_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sym = str(symbol).upper()
    fund_cfg = fund_cfg if fund_cfg is not None else (_load("fund_lookthrough.json").get("funds") or {})
    ipos = ipos if ipos is not None else (_load("ipo_lockups.json") or {})
    ipo_syms = {k.upper() for k in (ipos.get("lockups") or ipos) if not str(k).startswith("_")}
    basket = {b.upper() for b in ai_basket}
    holdings = holdings or {}
    profiles = profiles or {}
    reporting_soon = {s.upper() for s in (reporting_soon or set())}
    out: dict[str, Any] = {"symbol": sym, "groups": {}, "ai_share": None, "reporting": [], "basis": None, "note": ""}
    fund = fund_cfg.get(sym)
    if fund and sym in ipo_syms:
        out["note"] = (
            f"fund_lookthrough.json entry for {sym} ({fund.get('name')}) is stale: {sym} is a listed IPO; treated as a stock"
        )
        fund = None
    if not fund:
        seg = issuer_segments_for(sym, segments_cfg)
        if seg is not None:
            out.update(groups=seg["groups"], basis=seg["basis"])
            if sym in reporting_soon:
                out["reporting"] = [sym]
            return out
    if fund:
        if str(fund.get("lookthrough") or "") == "none" or not fund.get("weights"):
            out.update(
                basis="fund_unknown",
                note=f"no factsheet decomposition for {sym}: {fund.get('why') or 'not decomposed'}",
            )
            return out
        groups: dict[str, float] = {}
        for sector, w in (fund.get("weights") or {}).items():
            g = SECTOR_TO_GROUP.get(str(sector).lower())
            if g:
                groups[g] = groups.get(g, 0.0) + float(w)
        semis = sum(
            float(w)
            for ind, w in (fund.get("industries") or {}).items()
            if any(k in ind.lower() for k in SEMI_INDUSTRIES)
        )
        if semis:
            groups["semis"] = round(semis, 4)
        out.update(
            groups={k: round(v, 4) for k, v in groups.items()},
            basis=f"factsheet ({fund.get('source') or 'fund_lookthrough.json'})",
        )
        hs = holdings.get(sym) or []
        if hs:
            ai = sum(
                float(h.get("weight") or 0)
                for h in hs
                if ALIASES.get(str(h.get("holding")).upper(), str(h.get("holding")).upper()) in basket
            )
            out["ai_share"] = round(ai, 4)
            out["groups"]["ai_basket"] = round(ai, 4)
            out["reporting"] = sorted({str(h.get("holding")).upper() for h in hs} & reporting_soon)
            out["holdings_as_of"] = max((str(h.get("as_of") or "") for h in hs), default=None)
            out["basis"] += f" + top {len(hs)} holdings"
        else:
            out["note"] = (out["note"] + "; " if out["note"] else "") + "no holdings snapshot: AI-basket share unknown"
        return out
    prof = profiles.get(sym) or {}
    g = SECTOR_TO_GROUP.get(str(prof.get("sector") or "").lower())
    if not g and sym not in basket:
        out.update(basis="stock_unknown", note=out["note"] or f"no sector profile for {sym}")
        return out
    groups = {g: 1.0} if g else {}
    if any(k in str(prof.get("industry") or "").lower() for k in SEMI_INDUSTRIES):
        groups["semis"] = 1.0
    if sym in basket:
        groups["ai_basket"] = 1.0
        out["ai_share"] = 1.0
    out.update(groups=groups, basis="stock (symbol_profiles sector)")
    if sym in reporting_soon:
        out["reporting"] = [sym]
    return out


def issuer_segments_for(sym: str, segments_cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Segment look-through for a multi-segment issuer from ``config/issuer_segments.json`` (design home/v005). Only
    ``status: APPROVED`` entries count — the weights are operator-owned; a PROPOSED entry is never used in a number.
    Sector-kind weights must sum to 1.0 within ``SEGMENT_SUM_TOLERANCE``, else the entry is refused (None)."""
    cfg = segments_cfg if segments_cfg is not None else (_load("issuer_segments.json").get("issuers") or {})
    e = cfg.get(str(sym).upper()) if isinstance(cfg, dict) else None
    if not isinstance(e, dict) or str(e.get("status") or "").upper() != "APPROVED":
        return None
    groups: dict[str, float] = {}
    for seg in e.get("segments") or []:
        g, w = str((seg or {}).get("group") or ""), (seg or {}).get("weight")
        if g and isinstance(w, (int, float)) and w > 0:
            groups[g] = round(groups.get(g, 0.0) + float(w), 4)
    sector_sum = sum(w for g, w in groups.items() if g not in THEME_GROUPS)
    if abs(sector_sum - 1.0) > SEGMENT_SUM_TOLERANCE:
        return None
    return {"groups": groups, "basis": f"segments ({e.get('source') or 'issuer_segments.json'}, {e.get('as_of') or 'no date'})"}


def book_group_exposure(
    per_symbol: list[dict[str, Any]], weights: dict[str, float] | None = None
) -> dict[str, float]:
    """Look-through share per group of the measured book. With ``weights`` (symbol -> position value) the shares are
    VALUE-weighted (design home/v005: a fractional residual never counts as much as the largest holding); without
    them, equal per position (legacy callers). Shares only, never an amount."""
    known = [p for p in per_symbol if p.get("groups")]
    if not known:
        return {}
    keys = {k for p in known for k in p["groups"]}
    if weights:
        w = {id(p): max(0.0, float(weights.get(str(p.get("symbol") or "").upper()) or 0.0)) for p in known}
        tot = sum(w.values())
        if tot > 0:
            return {k: round(sum(p["groups"].get(k, 0.0) * w[id(p)] for p in known) / tot, 4) for k in sorted(keys)}
    return {k: round(sum(p["groups"].get(k, 0.0) for p in known) / len(known), 4) for k in sorted(keys)}
