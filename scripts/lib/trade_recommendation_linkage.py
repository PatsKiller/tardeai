"""Trade → recommendation linkage and R-multiple attribution (learning loop PR1, operator 2026-10-21).

Pure functions, used by scripts/trade_recommendation_linker.py (the writer of trade_recommendation_links) and by
/api/v2/journal (``attach_recommendation_links``). Design: docs/ops/LEARNING_LOOP_PR1_2026-10-21.md.

Matching rule for one closed trade (a Schwab round trip: symbol, entry time, entry price, long):
  candidates = recs with the same symbol and direction whose active window contains the entry time:
               created_at <= entry_time <= expires_at + GRACE
  confidence = exact        entry price inside the plan's entry zone (a single-price zone is widened by EXACT_POINT_PCT)
               zone         within NEAR_PCT of the zone's nearer edge
               window_only  inside the window but further than NEAR_PCT and no more than MAX_DRIFT_PCT from the zone
  best       = highest confidence, then smallest distance to the zone, then the most recently issued, then rec_id
  none       → origin 'operator_initiated' (recorded explicitly; never null)

R attribution (long; a short mirrors it):
  r_multiple = (exit - entry) / (entry - plan_stop), with the linked recommendation's plan stop; with no linked stop,
               the journal's recorded stop (trade_closed.stop_used); else null with r_null_reason.
  planned_rr = (plan_target - plan_entry) / (plan_entry - plan_stop), plan_entry = middle of the entry zone.
  target_hit / stop_hit are judged on the exit price (hit_basis 'exit_price'); there is no intratrade path here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

LINKER_VERSION = "trade_rec_linker@v1"
LINK_METHOD = "symbol+direction+active_window+entry_zone@v1"
GRACE = timedelta(days=1)
EXACT_POINT_PCT = 0.5
NEAR_PCT = 2.0
MAX_DRIFT_PCT = 10.0
CONFIDENCE_RANK = {"exact": 0, "zone": 1, "window_only": 2}
TRADE_SOURCE_TABLE = "schwab_round_trips"   # the round-trip table the linker reads (a table name, not a broker)


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if x == x and x not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ── price geometry ────────────────────────────────────────────────────────────────────────────────────────────────
def zone_distance_pct(price: float, lo: Optional[float], hi: Optional[float]) -> Optional[float]:
    """% distance from price to the zone [lo, hi] (0 inside it). A single-price zone is widened by EXACT_POINT_PCT."""
    lo, hi = _f(lo), _f(hi)
    if lo is None and hi is None:
        return None
    lo = hi if lo is None else lo
    hi = lo if hi is None else hi
    lo, hi = min(lo, hi), max(lo, hi)
    if hi <= 0:
        return None
    if abs(hi - lo) / hi * 100 < 1e-9:
        pad = hi * EXACT_POINT_PCT / 100
        lo, hi = lo - pad, hi + pad
    if lo <= price <= hi:
        return 0.0
    edge = lo if price < lo else hi
    return abs(price - edge) / edge * 100


def classify(distance_pct: Optional[float]) -> Optional[str]:
    if distance_pct is None:
        return "window_only"            # a rec with no entry level at all can only ever match on the window
    if distance_pct <= 0:
        return "exact"
    if distance_pct <= NEAR_PCT:
        return "zone"
    if distance_pct <= MAX_DRIFT_PCT:
        return "window_only"
    return None


def in_window(entry_time: datetime, rec: dict[str, Any], grace: timedelta = GRACE) -> bool:
    c, e = _ts(rec.get("created_at")), _ts(rec.get("expires_at"))
    return bool(c and e and c <= entry_time <= e + grace)


def match_trade(trade: dict[str, Any], recs: Iterable[dict[str, Any]], grace: timedelta = GRACE
                ) -> Optional[dict[str, Any]]:
    """Best recommendation for one trade, or None. Returns {rec, confidence, distance_pct, candidates}."""
    sym = str(trade.get("symbol") or "").upper()
    et, px = _ts(trade.get("entry_time")), _f(trade.get("entry_price"))
    direction = trade.get("direction") or "long"
    if not sym or et is None or px is None:
        return None
    scored = []
    for r in recs:
        if str(r.get("symbol") or "").upper() != sym or (r.get("direction") or "long") != direction:
            continue
        if not in_window(et, r, grace):
            continue
        d = zone_distance_pct(px, r.get("entry_low"), r.get("entry_high"))
        conf = classify(d)
        if conf is None:
            continue
        issued = _ts(r.get("created_at"))
        scored.append((CONFIDENCE_RANK[conf], round(d if d is not None else MAX_DRIFT_PCT, 3),
                       -issued.timestamp(), str(r.get("rec_id")), conf, d, r))
    if not scored:
        return None
    scored.sort(key=lambda t: t[:4])
    best = scored[0]
    return {"rec": best[6], "confidence": best[4], "distance_pct": None if best[5] is None else round(best[5], 3),
            "candidates": len(scored)}


# ── R math ────────────────────────────────────────────────────────────────────────────────────────────────────────
def r_multiple(entry: Any, exit_: Any, stop: Any, direction: str = "long") -> tuple[Optional[float], Optional[str]]:
    e, x, s = _f(entry), _f(exit_), _f(stop)
    if s is None:
        return None, "no_stop"
    if e is None or x is None:
        return None, "missing_fill_price"
    risk = (e - s) if direction == "long" else (s - e)
    if risk <= 0:
        return None, "stop_on_wrong_side_of_entry"
    move = (x - e) if direction == "long" else (e - x)
    return round(move / risk, 3), None


def planned_rr(entry_low: Any, entry_high: Any, stop: Any, target: Any, direction: str = "long") -> Optional[float]:
    lo, hi, s, t = _f(entry_low), _f(entry_high), _f(stop), _f(target)
    if s is None or t is None or (lo is None and hi is None):
        return None
    e = ((lo if lo is not None else hi) + (hi if hi is not None else lo)) / 2
    risk = (e - s) if direction == "long" else (s - e)
    reward = (t - e) if direction == "long" else (e - t)
    if risk <= 0 or reward <= 0:
        return None
    return round(reward / risk, 2)


def hits(exit_: Any, stop: Any, target: Any, direction: str = "long") -> tuple[Optional[bool], Optional[bool]]:
    """(target_hit, stop_hit) judged on the exit price; None when the level is unknown."""
    x, s, t = _f(exit_), _f(stop), _f(target)
    if x is None:
        return None, None
    if direction == "long":
        return (None if t is None else x >= t), (None if s is None else x <= s)
    return (None if t is None else x <= t), (None if s is None else x >= s)


def attribute(trade: dict[str, Any], match: Optional[dict[str, Any]], now: Optional[datetime] = None
              ) -> dict[str, Any]:
    """The trade_recommendation_links row for one trade (pure)."""
    direction = trade.get("direction") or "long"
    rec = (match or {}).get("rec") or {}
    row: dict[str, Any] = {
        "round_trip_key": trade["round_trip_key"], "round_trip_id": trade.get("round_trip_id"),
        "trade_source": trade.get("trade_source") or TRADE_SOURCE_TABLE,
        "symbol": str(trade.get("symbol") or "").upper(), "account": trade.get("account"), "direction": direction,
        "entry_time": trade.get("entry_time"), "exit_time": trade.get("exit_time"),
        "entry_price": _f(trade.get("entry_price")), "exit_price": _f(trade.get("exit_price")), "qty": _f(trade.get("qty")),
        "origin": "recommendation" if match else "operator_initiated",
        "rec_id": rec.get("rec_id") if match else None, "rec_source": rec.get("source") if match else None,
        "link_confidence": match["confidence"] if match else "none", "link_method": LINK_METHOD,
        "link_detail": ({"distance_pct": match["distance_pct"], "candidates": match["candidates"],
                         "grace_days": GRACE.days} if match else {"candidates": 0}),
        "plan_entry_low": _f(rec.get("entry_low")), "plan_entry_high": _f(rec.get("entry_high")),
        "plan_stop": _f(rec.get("plan_stop")), "plan_target": _f(rec.get("plan_target")),
        "linker_version": LINKER_VERSION, "linked_at": now or datetime.now(timezone.utc),
    }
    stop, src = row["plan_stop"], "recommendation"
    if stop is None:
        stop, src = _f(trade.get("journal_stop")), "journal"
    if stop is None:
        src = "none"
    r, why = r_multiple(row["entry_price"], row["exit_price"], stop, direction)
    if r is None and src == "none":
        why = "no_linked_or_journal_stop" if match else "operator_initiated_no_journal_stop"
    th, sh = hits(row["exit_price"], stop, row["plan_target"], direction)
    row.update({"stop_source": src, "r_multiple": r, "r_null_reason": why,
                "planned_rr": planned_rr(row["plan_entry_low"], row["plan_entry_high"], row["plan_stop"],
                                         row["plan_target"], direction),
                "target_hit": th, "stop_hit": sh, "hit_basis": "exit_price"})
    return row


def link_all(trades: Iterable[dict[str, Any]], recs: list[dict[str, Any]], grace: timedelta = GRACE,
             now: Optional[datetime] = None) -> list[dict[str, Any]]:
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for r in recs:
        by_sym.setdefault(str(r.get("symbol") or "").upper(), []).append(r)
    out = []
    for t in trades:
        cands = by_sym.get(str(t.get("symbol") or "").upper(), [])
        out.append(attribute(t, match_trade(t, cands, grace), now=now))
    return out


# ── read side: /api/v2/journal ────────────────────────────────────────────────────────────────────────────────────
LINK_FIELDS = ("rec_id", "rec_source", "link_confidence", "origin", "plan_entry_low", "plan_entry_high", "plan_stop",
               "plan_target", "r_multiple", "r_null_reason", "planned_rr", "target_hit", "stop_hit", "stop_source",
               "linked_at")

READ_SQL = """SELECT 'srt:' || s.id AS trade_dedupe_key, l.rec_id, l.rec_source, l.link_confidence, l.origin,
                     l.plan_entry_low, l.plan_entry_high, l.plan_stop, l.plan_target, l.r_multiple, l.r_null_reason,
                     l.planned_rr, l.target_hit, l.stop_hit, l.stop_source, l.linked_at::text AS linked_at,
                     rr.conviction_at_issue, rr.created_at::text AS rec_issued_at
              FROM trade_recommendation_links l
              JOIN schwab_round_trips s ON s.dedupe_key = l.round_trip_key
              LEFT JOIN recommendation_registry rr ON rr.rec_id = l.rec_id
              WHERE 'srt:' || s.id = ANY(%s)"""


def attach_recommendation_links(trades: list[dict[str, Any]], db_query: Callable[..., Any]) -> str:
    """Adds a ``recommendation`` block to each journal trade (keyed by trade_closed.dedupe_key). Returns the status:
    'ok', 'unavailable' (tables absent / query failed — every trade gets recommendation=None) or 'empty'."""
    keys = [t.get("dedupe_key") for t in trades if t.get("dedupe_key")]
    for t in trades:
        t["recommendation"] = None
    if not keys:
        return "empty"
    try:
        rows = db_query(READ_SQL, (keys,), fetch="all")
    except Exception:  # noqa: BLE001 — migration not applied yet, or a read failure: say so, never guess
        return "unavailable"
    if rows is None:
        return "unavailable"
    by_key = {r["trade_dedupe_key"]: r for r in rows}
    for t in trades:
        r = by_key.get(t.get("dedupe_key"))
        if not r:
            continue
        blk = {k: (float(r[k]) if r.get(k) is not None and k in (
            "plan_entry_low", "plan_entry_high", "plan_stop", "plan_target", "r_multiple", "planned_rr")
            else r.get(k)) for k in LINK_FIELDS}
        blk["r_achieved"] = blk.pop("r_multiple")       # the API names it for what the operator reads
        blk["conviction_at_issue"] = _f(r.get("conviction_at_issue"))
        blk["rec_issued_at"] = r.get("rec_issued_at")
        t["recommendation"] = blk
    return "ok"
