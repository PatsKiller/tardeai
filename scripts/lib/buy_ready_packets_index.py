"""Entry-alert index (2026-09-28): every buy-ready / entry-near packet the entry-state runner
saved, in one list for the Re-Entry page's "Entry alerts" lane.

Why: the runner writes data/runtime/buy_ready_packets/<SYM>.json and pages Telegram
(BUY_READY always, ENTRY_NEAR when starred); the Command Center served them only one at a time
(GET /api/v2/symbol/<SYM>/buy-ready-packet) and no page rendered them, so a BUY_READY stock
had no place on the site showing its zone, its risk-reward at the current quote, or what
became of its options alternative. Reviewer 2026-09-28: "give each Telegram idea a drilldown to
exactly one canonical idea or a durable explicit exclusion".

What: deterministic reading of the saved packets plus the options desk cache: state, price vs
zone (in / above / below, distance %), plan R:R and R:R at the current quote (both with the
entry price each assumes), quote and packet age, catalyst, CIO verdict, options-alternative
outcome, and the desk disposition (proposal id | not built: reason | not in the desk universe).
READ_ONLY_ADVISORY; nothing here sizes or orders (MBI_BEHAVIOR=0)."""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "BuyReadyPacketIndex@v1 is read by apps/command-center-v3 EntryAlertsLane (GET /api/v2/buy-ready/packets); "
    "the index is a projection over BuyReadyInstitutionalPacket@v2 files written by cio_entry_state_runner"
)

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "BuyReadyPacketIndex@v1"
STATE_ORDER = {"BUY_READY": 0, "ENTRY_NEAR": 1, "WATCH": 2}


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _hours_since(iso: Any, now: datetime) -> Optional[float]:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return round((now - t).total_seconds() / 3600.0, 2)
    except ValueError:
        return None


def zone_position(price: Optional[float], lo: Optional[float], hi: Optional[float]) -> dict[str, Any]:
    """Where the current quote sits against the plan's entry zone. Never a verdict."""
    if price is None or lo is None or hi is None:
        return {"position": "unknown", "distance_pct": None}
    if lo <= price <= hi:
        return {"position": "in_zone", "distance_pct": 0.0}
    if price > hi:
        return {"position": "above", "distance_pct": round(100.0 * (price - hi) / hi, 1)}
    return {"position": "below", "distance_pct": round(100.0 * (lo - price) / lo, 1)}


def reward_risk(target: Optional[float], entry: Optional[float], stop: Optional[float]) -> Optional[float]:
    """(target - entry) / (entry - stop) at a STATED entry price; None when the stop is not below it."""
    if target is None or entry is None or stop is None or entry <= stop:
        return None
    return round((target - entry) / (entry - stop), 2)


def desk_disposition(symbol: str, proposals: list[dict[str, Any]], dropped: list[dict[str, Any]]) -> dict[str, Any]:
    """Exactly one of: a desk proposal id, a named 'not built' reason, or 'not in the desk universe'."""
    sym = symbol.upper()
    hits = [p for p in proposals if str(p.get("symbol") or "").upper() == sym]
    if hits:
        p = hits[0]
        return {"status": "proposal", "proposal_id": p.get("id"), "strategy": p.get("strategy"),
                "approvable": p.get("approvable"), "severity": p.get("severity"), "count": len(hits)}
    drops = [d for d in dropped if str(d.get("symbol") or "").upper() == sym]
    if drops:
        d = drops[0]
        return {"status": "not_built", "reason": d.get("reason"), "entry_state": d.get("entry_state"),
                "detail": {k: v for k, v in d.items() if k not in ("symbol", "reason", "entry_state")}}
    return {"status": "not_in_desk_universe", "reason": "the options desk did not scan this symbol on its last run"}


def index_packet(packet: dict[str, Any], *, proposals: list[dict[str, Any]], dropped: list[dict[str, Any]],
                 now: datetime) -> dict[str, Any]:
    eq = packet.get("equity") or {}
    alt = packet.get("options_alt") or {}
    alts = packet.get("options_alternatives") or {}
    verdict = packet.get("cio_verdict") or {}
    review = packet.get("cio_review") or {}
    sym = str(packet.get("symbol") or eq.get("symbol") or "").upper()
    price, lo, hi = _f(eq.get("price")), _f(eq.get("entry_low")), _f(eq.get("entry_high"))
    stop, target = _f(eq.get("stop")), _f(eq.get("target"))
    zp = zone_position(price, lo, hi)
    # the plan R:R the alert prints is quoted at the zone's top (the worst in-zone entry); say so
    rr_plan = _f(eq.get("rr"))
    rr_plan_entry = hi
    rr_quote = reward_risk(target, price, stop)
    qualified = [a for a in (alts.get("alternatives") or []) if a.get("qualified")]
    return {
        "symbol": sym,
        "state": str(eq.get("state") or packet.get("state") or "").upper() or None,
        "plan_source": eq.get("plan_source"),
        "saved_at": packet.get("saved_at"),
        "packet_age_h": _hours_since(packet.get("saved_at"), now),
        "price": price,
        "quote_age_h": _f(eq.get("quote_age_h")),
        "entry_low": lo, "entry_high": hi, "stop": stop, "target": target,
        "zone": zp,
        "rr_plan": rr_plan, "rr_plan_entry": rr_plan_entry,
        "rr_at_quote": rr_quote, "rr_at_quote_entry": price,
        "catalyst": eq.get("catalyst"),
        "cio_verdict": {"verdict": verdict.get("verdict"), "token": verdict.get("token"), "rationale": verdict.get("rationale")},
        "cio_review": {"status": review.get("status"), "mode": review.get("mode"), "as_of": review.get("as_of")},
        "options_alt": {"status": alt.get("status") or alts.get("status"), "reason": alt.get("reason"), "detail": alt.get("detail"),
                        "strategy": alt.get("strategy"), "qualified_count": len(qualified),
                        "considered": len(alts.get("alternatives") or []), "chain_as_of": alts.get("chain_as_of")},
        "desk": desk_disposition(sym, proposals, dropped),
        "authority": "READ_ONLY_ADVISORY",
    }


def index_packets(packet_dir: Path, *, proposals: Optional[list[dict[str, Any]]] = None,
                  dropped: Optional[list[dict[str, Any]]] = None, now: Optional[datetime] = None,
                  max_age_h: float = 48.0) -> dict[str, Any]:
    """The served payload. Packets older than ``max_age_h`` are listed under ``stale`` by symbol
    only, so the lane never shows a days-old BUY_READY as current."""
    now = now or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(Path(packet_dir).glob("*.json")) if Path(packet_dir).exists() else []:
        try:
            packet = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{path.name}: {type(exc).__name__}")
            continue
        row = index_packet(packet, proposals=proposals or [], dropped=dropped or [], now=now)
        if row["packet_age_h"] is not None and row["packet_age_h"] > max_age_h:
            stale.append({"symbol": row["symbol"], "state": row["state"], "saved_at": row["saved_at"], "packet_age_h": row["packet_age_h"]})
            continue
        rows.append(row)
    rows.sort(key=lambda r: (STATE_ORDER.get(r["state"] or "", 9), r["packet_age_h"] if r["packet_age_h"] is not None else 1e9))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"] or "UNKNOWN"] = counts.get(r["state"] or "UNKNOWN", 0) + 1
    return {"schema": SCHEMA, "as_of": now.isoformat(), "count": len(rows), "counts": counts, "rows": rows,
            "stale": stale, "max_age_h": max_age_h, "errors": errors, "authority": "READ_ONLY_ADVISORY",
            "note": ("Entry-state packets the runner saved (BUY_READY pages Telegram; ENTRY_NEAR pages when starred). "
                     "Plan R:R is quoted at the zone top; R:R at quote uses the current price. Advisory only.")}
