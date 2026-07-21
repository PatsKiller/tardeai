#!/usr/bin/env python3
"""packet_invalidation.py — is a decision packet still current, or must it regen?

WHY THIS EXISTS
---------------
The batch skipped regeneration on a bare "packet younger than 12h" rule. But a
fresh catalyst, a volume-confirmed move, an ownership change, an earnings update,
or a chain change can invalidate a packet that is only two hours old. Skipping on
age alone means the operator can be shown a "constructive" decision that the
evidence has already overtaken — the same absence-vs-staleness confusion this
programme keeps closing.

A packet is regenerated when ANY of these is true, and the EXACT reason is
recorded:
    packet older than TTL
    packet/policy version changed
    a material input hash changed        (event state/date, ownership, fundamentals age)
    material price drift vs the packet's price
    a newer non-trivial catalyst since the packet was generated

Price is deliberately NOT in the discrete hash — price always moves, so hashing
it would invalidate every packet every run. Price is a SEPARATE governed drift
check against the packet's own price_used, so small ticks are ignored and a real
move is caught.

PURE hashing; the DB read is a thin separate function.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

# Kept in sync with the live packet/policy versions so a bump forces a refresh.
CURRENT_PACKET_VERSION = "1.1.0-shadow"

TTL_HOURS = float(os.getenv("PACKET_TTL_HOURS", "12"))
PRICE_DRIFT_PCT = float(os.getenv("PACKET_PRICE_DRIFT_PCT", "3.0"))


def _now(now=None) -> datetime:
    return now or datetime.now(timezone.utc)


def _parse(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        s = str(ts).replace(" ", "T", 1) if "T" not in str(ts) else str(ts)
        s = s.replace("Z", "+00:00")
        d = datetime.fromisoformat(s[:32])
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def material_fields(*, symbol, event_state, event_date, held, shares,
                    fundamentals_as_of, packet_version, source_commit_sha) -> dict:
    """The DISCRETE inputs a decision rests on (price excluded — see module doc).
    Shares are bucketed to whole numbers so fractional-reinvestment drift does not
    invalidate, but a held/not-held flip or a real size change does."""
    return {
        "symbol": str(symbol or "").upper(),
        "event_state": str(event_state or ""),
        "event_date": str(event_date or ""),
        "held": bool(held),
        "shares_bucket": int(round(float(shares or 0))),
        "fundamentals_as_of": str(fundamentals_as_of or ""),
        "packet_version": str(packet_version or ""),
        "source_commit_sha": str(source_commit_sha or ""),
    }


def material_hash(fields: dict) -> str:
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()[:16]


def fields_from_packet(packet: dict) -> dict:
    p = packet or {}
    ev = (p.get("event_state") or {}).get("earnings") or {}
    own = p.get("ownership") or {}
    return material_fields(
        symbol=p.get("symbol"), event_state=ev.get("state"), event_date=ev.get("date"),
        held=own.get("held"), shares=own.get("shares"),
        fundamentals_as_of=p.get("fundamentals_as_of"),
        packet_version=p.get("packet_version"),
        source_commit_sha=p.get("source_commit_sha"))


def evaluate_invalidation(packet: dict, current: dict, *, generated_at,
                          ttl_hours: float = TTL_HOURS,
                          price_drift_pct: float = PRICE_DRIFT_PCT,
                          now=None) -> tuple:
    """(invalidated: bool, reason: str). `current` is current material facts from
    current_material(); packet is the stored packet."""
    gen = _parse(generated_at) or _parse((packet or {}).get("evaluated_at"))
    if gen is not None:
        age_h = (_now(now) - gen).total_seconds() / 3600.0
        if age_h > ttl_hours:
            return True, f"ttl_exceeded ({age_h:.0f}h > {ttl_hours}h)"

    # version bump forces a refresh
    if str((packet or {}).get("packet_version") or "") != CURRENT_PACKET_VERSION:
        return True, f"packet_version ({(packet or {}).get('packet_version')} -> {CURRENT_PACKET_VERSION})"

    # discrete material change — report WHICH field
    old = fields_from_packet(packet)
    new = material_fields(
        symbol=current.get("symbol"), event_state=current.get("event_state"),
        event_date=current.get("event_date"), held=current.get("held"),
        shares=current.get("shares"), fundamentals_as_of=current.get("fundamentals_as_of"),
        packet_version=CURRENT_PACKET_VERSION,
        source_commit_sha=old["source_commit_sha"])  # sha not a per-symbol input here
    if material_hash(old) != material_hash({**new, "source_commit_sha": old["source_commit_sha"],
                                            "packet_version": old["packet_version"]}):
        for k in ("event_state", "event_date", "held", "shares_bucket", "fundamentals_as_of"):
            if old.get(k) != new.get(k):
                return True, f"{k} changed ({old.get(k)} -> {new.get(k)})"
        return True, "material_input_changed"

    # price drift vs the packet's own price
    pp = (packet or {}).get("price_used")
    cp = current.get("current_price")
    if pp and cp:
        drift = abs(float(cp) - float(pp)) / float(pp) * 100.0
        if drift > price_drift_pct:
            return True, f"material_price_drift ({drift:.1f}% > {price_drift_pct}%)"

    # a newer non-trivial catalyst since the packet was generated
    cat = _parse(current.get("latest_catalyst_at"))
    if cat is not None and gen is not None and cat > gen:
        return True, f"fresh_catalyst (published {current.get('latest_catalyst_at')} after packet)"

    return False, "current"


def current_material(symbol: str, conn=None) -> dict:
    """Cheap read of the CURRENT material facts for a symbol — no model pass.
    Mirrors the fields a packet captured at generation so they are comparable."""
    sym = str(symbol or "").upper()
    if conn is None:
        from db_adapter import _get_conn
        conn = _get_conn()
    cur = conn.cursor()
    out = {"symbol": sym}

    cur.execute("SELECT price FROM market_quotes WHERE symbol=%s ORDER BY fetched_at DESC LIMIT 1", (sym,))
    r = cur.fetchone()
    out["current_price"] = float(r[0]) if r and r[0] is not None else None

    try:
        import event_normalizer as ev
        e = ev.resolve_from_db(sym, conn)
        out["event_state"], out["event_date"] = e.state, (e.date.isoformat() if e.date else None)
    except Exception:
        out["event_state"], out["event_date"] = None, None

    # ownership from holdings.json
    try:
        import position_truth as pt
        from pathlib import Path
        hp = Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state" / "holdings.json"
        own = pt.ownership_from_holdings(sym, json.loads(hp.read_text()) if hp.exists() else {})
        out["held"], out["shares"] = own.held, own.shares
    except Exception:
        out["held"], out["shares"] = False, 0

    # fundamentals age
    try:
        import shadow_decision_service as svc
        out["fundamentals_as_of"] = (svc._fundamentals_for(sym) or {}).get("fundamentals_as_of")
    except Exception:
        out["fundamentals_as_of"] = None

    cur.execute("""SELECT MAX(published_at) FROM catalyst_events
                   WHERE upper(symbol)=%s AND catalyst_type <> 'other'
                     AND COALESCE(confidence,0) >= 0.7""", (sym,))
    r = cur.fetchone()
    out["latest_catalyst_at"] = str(r[0]) if r and r[0] else None
    return out
