"""Gain Guardian tax annotation gate (F3) — advisory context on TRIM advisories.

Arithmetic on existing data only. Bracket/IRMAA context comes from Alex's
`get_tax_context()` (reused, never reimplemented); anything we cannot compute
from real data degrades to an honest instruction, never a guessed number.

Verified constraints (2026-07-16 diagnosis):
- schwab_cost_basis_lots.opened_date is NULL on 100% of rows → LT/ST lot term
  is UNVERIFIABLE from the database. We report lot coverage and say so.
- Account routing comes from holdings.json (four real accounts).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

HOLDINGS_PATH = ROOT / "data" / "portfolios" / "state" / "holdings.json"

_IRA_ACCOUNTS = ("roth", "ira", "401k")  # substring match on account label


def _accounts_holding(symbol: str) -> list[dict[str, Any]]:
    d = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
    out = []
    for h in d.get("holdings") or []:
        if str(h.get("symbol") or "").upper() == symbol.upper() and not h.get("is_cash"):
            out.append({
                "account": str(h.get("account") or "unknown"),
                "shares": float(h.get("shares") or 0),
                "market_value": float(h.get("market_value") or 0),
                "cost_basis": float(h.get("cost_basis") or 0),
            })
    return out


def _is_sheltered(account: str) -> bool:
    a = account.lower()
    return any(k in a for k in _IRA_ACCOUNTS)


def annotate_trim(*, symbol: str, trim_fraction: float, price: float,
                  basis_ps: float | None, db_execute) -> dict[str, Any]:
    """Annotate a TRIM_ADVISORY with account routing, lot-term honesty, and a
    MAGI/IRMAA line. Returns dict with `lines` (list of one-liners) + fields."""
    sym = symbol.upper()
    positions = _accounts_holding(sym)
    sheltered = [p for p in positions if _is_sheltered(p["account"])]
    taxable = [p for p in positions if not _is_sheltered(p["account"])]
    lines: list[str] = []
    routing = None

    if sheltered and taxable:
        routing = "prefer_sheltered"
        lines.append(
            f"Account routing: {sym} held in both sheltered ({', '.join(p['account'] for p in sheltered)}) "
            f"and taxable — prefer the IRA/Roth trim first (no cap-gains event, no MAGI impact)."
        )
    elif sheltered:
        routing = "sheltered_only"
        lines.append(f"Account routing: {sym} held only in sheltered accounts — trim has no cap-gains/MAGI impact.")
    elif taxable:
        routing = "taxable_only"
        lines.append(f"Account routing: {sym} held only in taxable — every trimmed share is a taxable event.")
    else:
        return {"ok": False, "error": f"{sym} not found in holdings state", "lines": []}

    # Lot term (taxable only) — dates are missing, say so instead of computing a wrong LT/ST split
    lot_note = None
    est_gain = None
    if taxable:
        shares_t = sum(p["shares"] for p in taxable)
        trim_shares = shares_t * float(trim_fraction)
        try:
            lots = db_execute(
                """SELECT count(*) AS n, count(opened_date) AS dated
                   FROM schwab_cost_basis_lots
                   WHERE upper(symbol)=%s AND kind='unrealized' AND quantity > 0""",
                (sym,), fetch="one",
            ) or {"n": 0, "dated": 0}
        except Exception:
            lots = {"n": 0, "dated": 0}
        if lots["n"] and lots["dated"]:
            lot_note = f"{lots['dated']}/{lots['n']} lots carry acquisition dates — LT/ST split computable."
        else:
            lot_note = (
                f"holding-period term unverified — export dated Cost Basis from Schwab to confirm "
                f"LT/ST before acting ({lots['n']} lot rows on file, none dated; assume ST for planning)."
            )
        lines.append(f"Lot term ({trim_shares:.1f} sh of the taxable {shares_t:.1f}): {lot_note}")

        if basis_ps and basis_ps > 0 and price > 0:
            est_gain = round(trim_shares * (price - basis_ps), 2)
            lines.append(
                f"Estimated realized gain on the taxable slice: ${est_gain:,.0f} "
                f"({trim_shares:.1f} sh × (${price:,.2f} − ${basis_ps:,.2f}))."
            )
        else:
            lines.append("Basis unresolved on the taxable slice — reconcile before trimming (no gain estimate).")

    # MAGI / IRMAA context — reuse Alex, degrade honestly on any failure
    magi_line = None
    try:
        from alex_retirement_advisor import get_tax_context
        ctx = get_tax_context(tax_year=2026)
        if ctx.get("error"):
            raise RuntimeError(ctx["error"])
        room = float(ctx.get("bracket_room_22pct") or 0)
        agi = float(ctx.get("agi") or 0)
        gain_txt = f"~${est_gain:,.0f} realized gain" if est_gain else "the realized gain"
        magi_line = (
            f"MAGI/IRMAA: AGI ~${agi:,.0f}, room to top of 22% bracket ~${room:,.0f}; "
            f"{gain_txt} consumes that room and counts toward the IRMAA two-year lookback "
            f"(Medicare enrollment ~Dec 2026)."
        )
        if est_gain and est_gain > room:
            magi_line += " ⚠ Estimated gain EXCEEDS remaining bracket room."
    except Exception:
        magi_line = (
            f"MAGI/IRMAA context unavailable — run "
            f"`alex_retirement_advisor.py --analyze {sym} --tax-advisor` before acting."
        )
    lines.append(magi_line)

    return {
        "ok": True, "symbol": sym, "routing": routing,
        "trim_fraction": trim_fraction, "estimated_realized_gain": est_gain,
        "lot_note": lot_note, "magi_line": magi_line, "lines": lines,
    }
