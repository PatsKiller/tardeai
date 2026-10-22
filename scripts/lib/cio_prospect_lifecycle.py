"""CIO prospect — position lifecycle: origin, fills, observed stops, excursion, exit cause, post-exit review, re-entry.

Operator 2026-10-22 (verbatim): "navn was one of the top picks with the highest conviction. I got into it a few days
ago. I got stopped out today. I want to make sure that the trade and view actually tracks where that stock came from.
I didn't pick it on my own. It came from internal. It examines the ups and downs and what was the cause of getting out
and advises me on when to get back in. All on the same data backend. Not a separate work stream."

So this is part of the CIO prospect record (AGENTS.md §26), not a new store: every block below is a field of the same
``InstrumentRecord@v1``-extended record (``origin``, ``position_lifecycle``, ``post_exit_review``, ``reentry_advice``,
``stage_phase``), written only through ``apply_prospect``, and each fact becomes an append-only ``cio_prospect_events``
row (``lifecycle_events``). Nothing here is a new matcher or a new re-entry engine (§13.5):

* origin attribution REUSES the learning-loop linkage rules (``scripts/lib/trade_recommendation_linkage.py``:
  ``match_trade`` / ``attribute`` / ``r_multiple``) — over the ``trade_recommendation_links`` row when the learning-loop
  migration is applied, else over recommendations rebuilt in memory from the CIO's own records (opportunity
  assessment versions and cio_entry_state signals), the same shape the registry holds;
* re-entry advice REUSES the Re-Entry Decision Desk classifier (``scripts/lib/reentry_rules.derive_intel_state``,
  READY / NEAR / WAIT; moved verbatim out of the desk so this lane does not import the desk's broker-reaching closure).

MBI_BEHAVIOR = 0: these are OBSERVED facts and advice for a person. Field names never use a behaviour key (the rail
in ``cio_instrument_record.BEHAVIOR_FIELDS`` refuses ``stop``, ``qty``, ``shares``, ``order``, ``trade`` ...): an
observed broker stop is ``stop_price_observed``, a plan level is ``plan_stop`` (the learning-loop convention), a level
to watch is a ``reference``. Nothing here sizes, orders, places or moves a stop, and no alert is sent — a re-entry
alert is described (``one_alert``) for the comms path to carry once the operator promotes the lane.

Pure functions. AUTHORITY: READ_ONLY_ADVISORY. Provenance class D (deterministic) for every number; model prose for the
post-exit review is only ever requested through a registered capability (§12, §23.4) and is null until one exists.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

try:
    from scripts.lib import trade_recommendation_linkage as lk
    from scripts.lib import reentry_rules as rr
except ImportError:  # scripts/ (not the repo root) on sys.path
    from lib import trade_recommendation_linkage as lk  # type: ignore
    from lib import reentry_rules as rr  # type: ignore

SCHEMA = "CioProspectLifecycle@v1"
FILL_MATCH_PCT = 0.5              # an exit within 0.5% of the last observed stop is that stop filling
ENTRY_SIGNAL_TTL = timedelta(days=5)
LATEST_VERSION_TTL = timedelta(days=7)
EXIT_REVIEW_DAYS = 2              # stage_phase exit_review for this long after an exit, then re_entry_watch
REENTRY_WATCH_DAYS = 30
NOISE_MAX_GIVEBACK_PCT = 5.0      # close-basis giveback from the peak that still reads as noise when the trend holds
NOISE_MAX_GIVEBACK_ATR = 2.0
REENTRY_MIN_CONVICTION = 70.0     # config/opportunity_conviction.yaml stance.re_enter_if.min_conviction


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[datetime]:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    if len(s) >= 3 and s[-3] in "+-" and s[-2:].isdigit() and ":" not in s[-6:]:
        s += ":00"                                   # '2026-10-19 11:01:04-04' -> '-04:00'
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(v: Any) -> Optional[str]:
    dt = _ts(v)
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    return round((a - b) / b * 100.0, 2)


# ── recommendations the CIO published (linkage-registry shape) ──────────────


def recommendations_from_records(symbol: str, assessment_versions: Iterable[dict[str, Any]],
                                 entry_signals: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild the CIO's published recommendations for one symbol in the ``recommendation_registry`` row shape, from
    its own records: each opportunity-assessment version (active until the next version) and each cio_entry_state
    signal (active ENTRY_SIGNAL_TTL). Used only when the learning-loop tables are absent; never written."""
    sym = str(symbol).upper()
    vers = sorted((v for v in assessment_versions if str(v.get("symbol") or "").upper() == sym),
                  key=lambda v: str(v.get("written_at") or ""))
    recs: list[dict[str, Any]] = []
    for i, v in enumerate(vers):
        a = v.get("assessment") or {}
        rk = a.get("risk_reward") or {}
        zone = rk.get("entry_zone") or [None, None]
        created = _ts(v.get("written_at"))
        if created is None:
            continue
        nxt = _ts(vers[i + 1].get("written_at")) if i + 1 < len(vers) else None
        recs.append({
            "rec_id": f"opp:{sym}:v{v.get('version')}", "source": "cio_opportunity_curator",
            "source_table": "data/cio/cio_opportunity_assessments.jsonl", "source_id": f"{sym}:v{v.get('version')}",
            "symbol": sym, "direction": "long", "entry_low": _f(zone[0]), "entry_high": _f(zone[1]),
            "plan_stop": _f(rk.get("invalidation_level")), "plan_target": _f(rk.get("primary_target")),
            "created_at": created.isoformat(), "expires_at": (nxt or created + LATEST_VERSION_TTL).isoformat(),
            "conviction_at_issue": _f(a.get("conviction")), "rank_at_issue": a.get("rank"),
            "stance_at_issue": a.get("stance"), "type_at_issue": a.get("type"), "rr_at_issue": _f(rk.get("rr")),
            "coverage_at_issue": _f(a.get("coverage")),
        })
    for s in entry_signals:
        p = s.get("payload") or {}
        if str(p.get("symbol") or "").upper() != sym or p.get("signal") != "cio_entry_state":
            continue
        created = _ts(s.get("timestamp"))
        if created is None:
            continue
        recs.append({
            "rec_id": f"entry:{s.get('event_id')}", "source": "cio_entry_state",
            "source_table": "data/cio/cio_events.jsonl", "source_id": s.get("event_id"), "symbol": sym,
            "direction": "long", "entry_low": _f(p.get("entry_low")), "entry_high": _f(p.get("entry_high")),
            "plan_stop": None, "plan_target": None, "created_at": created.isoformat(),
            "expires_at": (created + ENTRY_SIGNAL_TTL).isoformat(), "state_at_issue": p.get("state"),
            "price_at_issue": _f(p.get("price")), "rr_at_issue": _f(p.get("rr")),
        })
    return recs


def _version_at(recs: list[dict[str, Any]], at: datetime) -> Optional[dict[str, Any]]:
    live = [r for r in recs if r["source"] == "cio_opportunity_curator" and _ts(r["created_at"]) <= at]
    return max(live, key=lambda r: r["created_at"]) if live else None


def surfaces_at(recs: list[dict[str, Any]], at: datetime, *, home_bar: dict[str, Any]) -> list[dict[str, Any]]:
    """What the operator's surfaces showed for this symbol at ``at`` — reconstructed from the CIO's own versioned
    records (the projection Home and Telegram read is versioned in cio_opportunity_assessments.jsonl)."""
    out: list[dict[str, Any]] = []
    v = _version_at(recs, at)
    if v is not None:
        passes = all(
            (home_bar.get(k) is None) or (val is not None and val >= float(home_bar[k]))
            for k, val in (("min_conviction", v.get("conviction_at_issue")), ("min_rr", v.get("rr_at_issue")),
                           ("min_coverage", v.get("coverage_at_issue"))))
        rank = v.get("rank_at_issue")
        out.append({"surface": "Home · Best opportunities (preset top5)",
                    "shown": bool(passes and rank is not None and int(rank) <= int(home_bar.get("limit") or 5)),
                    "rank": rank, "conviction": v.get("conviction_at_issue"), "rr": v.get("rr_at_issue"),
                    "stance": v.get("stance_at_issue"), "type": v.get("type_at_issue"),
                    "passes_bar": passes, "record": v["source_table"] + " " + v["source_id"], "at": v["created_at"],
                    "basis": "rank is the curator's conviction rank; shown when it clears the top5 bar and ranks <= 5"})
        conv = v.get("conviction_at_issue")
        out.append({"surface": "Telegram · conviction line (opportunity_alert.enrich)",
                    "shown": conv is not None,
                    "text": (f"Conviction {round(conv)}/100 · #{rank} · R:R {v.get('rr_at_issue')} · "
                             f"{v.get('stance_at_issue')}") if conv is not None else None,
                    "record": v["source_table"] + " " + v["source_id"], "at": v["created_at"],
                    "basis": "appended to alerts naming the symbol while the curated projection is <= 26 h old; "
                             "the projection refreshes every 30 min and carries the active version (a version is "
                             "written only on a material change), so this is the line an alert would have carried"})
    sigs = [r for r in recs if r["source"] == "cio_entry_state" and _ts(r["created_at"]) <= at <= _ts(r["expires_at"])]
    for s in sorted(sigs, key=lambda r: r["created_at"]):
        out.append({"surface": "CIO entry state (Telegram HIGH CONVICTION ENTRY card source)", "shown": True,
                    "state": s.get("state_at_issue"), "entry_zone": [s.get("entry_low"), s.get("entry_high")],
                    "price": s.get("price_at_issue"), "rr": s.get("rr_at_issue"),
                    "record": s["source_table"] + " " + str(s["source_id"]), "at": s["created_at"]})
    return out


def attribute_origin(round_trip: dict[str, Any], recs: list[dict[str, Any]], *,
                     link_row: Optional[dict[str, Any]] = None, home_bar: dict[str, Any],
                     decisions: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """Where the position came from. ``link_row`` (trade_recommendation_links) wins when present; otherwise the
    linkage rules run over ``recs``. 'internal' when a CIO recommendation matched; 'operator_initiated' otherwise —
    explicitly, never null (the learning-loop rule)."""
    entry_at = _ts(round_trip.get("entry_time"))
    trade = {"round_trip_key": round_trip.get("round_trip_key"), "symbol": round_trip.get("symbol"),
             "entry_time": entry_at, "exit_time": _ts(round_trip.get("exit_time")),
             "entry_price": round_trip.get("entry_price"), "exit_price": round_trip.get("exit_price"),
             "journal_stop": round_trip.get("journal_stop"), "direction": "long"}
    if link_row:
        linkage = {"source": "trade_recommendation_links (learning loop PR1)", "rec_id": link_row.get("rec_id"),
                   "rec_source": link_row.get("rec_source"), "link_confidence": link_row.get("link_confidence"),
                   "origin": link_row.get("origin"), "plan_stop": _f(link_row.get("plan_stop")),
                   "plan_target": _f(link_row.get("plan_target")), "r_multiple": _f(link_row.get("r_multiple")),
                   "planned_rr": _f(link_row.get("planned_rr")), "link_method": lk.LINK_METHOD}
    else:
        match = lk.match_trade(trade, recs) if entry_at else None
        row = lk.attribute(trade, match)
        rec = (match or {}).get("rec") or {}
        linkage = {"source": "linkage rules over the CIO's own records (learning-loop tables not read)",
                   "rec_id": row["rec_id"], "rec_source": row["rec_source"], "link_confidence": row["link_confidence"],
                   "distance_pct": (row.get("link_detail") or {}).get("distance_pct"),
                   "candidates": (row.get("link_detail") or {}).get("candidates"), "origin": row["origin"],
                   "plan_entry_zone": [row["plan_entry_low"], row["plan_entry_high"]], "plan_stop": row["plan_stop"],
                   "plan_target": row["plan_target"], "r_multiple": row["r_multiple"],
                   "r_null_reason": row["r_null_reason"], "planned_rr": row["planned_rr"],
                   "rec_issued_at": rec.get("created_at"), "link_method": lk.LINK_METHOD}
    surfaces = surfaces_at(recs, entry_at, home_bar=home_bar) if entry_at else []
    for d in decisions:
        dat = _ts(d.get("created_at"))
        if entry_at and dat and dat <= entry_at <= (_ts(d.get("expires_at")) or dat + ENTRY_SIGNAL_TTL):
            surfaces.append({"surface": "CIO decision (cio_decisions)", "shown": True, "action": d.get("action"),
                             "status": d.get("status"), "record": "cio_decisions", "at": _iso(dat)})
    internal = linkage.get("origin") == "recommendation"
    return {
        "classification": "internal" if internal else "operator_initiated",
        "summary": (f"From internal: {linkage.get('rec_source')} {linkage.get('rec_id')} "
                    f"({linkage.get('link_confidence')}); {sum(1 for s in surfaces if s.get('shown'))} surface(s) "
                    "showed it before the entry fill") if internal else
                   "Your own trade: no CIO recommendation was active for this entry (recorded explicitly)",
        "linkage": linkage,
        "at_entry": {"entry_fill_at": _iso(entry_at), "entry_fill_price": _f(round_trip.get("entry_price")),
                     "surfaces": surfaces},
    }


# ── fills, observed stops, excursion, exit cause ────────────────────────────


def stop_path(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Observed broker stops for one position, in order (stop_lifecycle rows; read-only observation)."""
    path = []
    for r in rows:
        px = _f(r.get("stop_price") if "stop_price" in r else r.get("stop_price_observed"))
        if px is None:
            continue
        path.append({"stop_price_observed": px, "status": str(r.get("status") or "").upper() or None,
                     "order_ref": r.get("order_id") or r.get("order_ref"), "at": _iso(r.get("snapshot_at") or r.get("at")),
                     "seq": r.get("seq")})
    path.sort(key=lambda p: (p.get("seq") if p.get("seq") is not None else 0, p.get("at") or ""))
    ratchets = sum(1 for a, b in zip(path, path[1:]) if b["stop_price_observed"] > a["stop_price_observed"])
    filled = [p for p in path if p["status"] == "FILLED"]
    return {"path": path, "ratchets_up": ratchets, "initial": path[0]["stop_price_observed"] if path else None,
            "last": path[-1]["stop_price_observed"] if path else None,
            "filled": filled[-1]["stop_price_observed"] if filled else None}


def excursion(entry_price: Any, entry_at: Any, exit_at: Any, bars: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Max favourable / adverse excursion over the hold. Intraday high/low when the bars carry them, else closes
    (``basis`` says which — a close-basis MAE understates intraday risk)."""
    e = _f(entry_price)
    t0, t1 = _ts(entry_at), _ts(exit_at)
    rows = []
    for b in bars:
        d = _ts(b.get("time") or b.get("date") or b.get("bar_time") or b.get("price_date"))
        if d is None or t0 is None:
            continue
        if d.date() < t0.date() or (t1 is not None and d.date() > t1.date()):
            continue
        rows.append((d, _f(b.get("high")), _f(b.get("low")), _f(b.get("close") or b.get("close_price"))))
    if e is None or not rows:
        return {"basis": None, "mfe_pct": None, "mae_pct": None, "why": "no bars over the hold"}
    intraday = all(h is not None and lo is not None for _, h, lo, _c in rows)
    hi = max(rows, key=lambda r: (r[1] if intraday else r[3]) or 0)
    lo = min(rows, key=lambda r: (r[2] if intraday else r[3]) or 0)
    hpx = hi[1] if intraday else hi[3]
    lpx = lo[2] if intraday else lo[3]
    return {"basis": "intraday_high_low" if intraday else "daily_close",
            "mfe_price": hpx, "mfe_at": hi[0].date().isoformat(), "mfe_pct": _pct(hpx, e),
            "mae_price": lpx, "mae_at": lo[0].date().isoformat(), "mae_pct": _pct(lpx, e), "bars": len(rows)}


def classify_exit(exit_price: Any, entry_price: Any, stops: dict[str, Any], plan_target: Any) -> dict[str, Any]:
    """stop-out / trailing ratchet / target / manual sell, with the evidence that decided it."""
    x, e, t = _f(exit_price), _f(entry_price), _f(plan_target)
    last_fill = stops.get("filled") if stops.get("filled") is not None else stops.get("last")
    if x is not None and last_fill is not None and abs(x - last_fill) / last_fill * 100.0 <= FILL_MATCH_PCT:
        trailing = stops.get("ratchets_up", 0) >= 1 and e is not None and last_fill > (stops.get("initial") or 0)
        cls = "trailing_ratchet" if trailing else "stop_out"
        return {"class": cls, "evidence": f"exit {x} = observed stop {last_fill}"
                f"{' (FILLED)' if stops.get('filled') is not None else ''}; stop raised {stops.get('ratchets_up')}x "
                f"from {stops.get('initial')}" + (f"; exit {'above' if x >= e else 'below'} entry {e}" if e else ""),
                "in_profit": None if e is None else x >= e}
    if x is not None and t is not None and x >= t * (1 - FILL_MATCH_PCT / 100.0):
        return {"class": "target", "evidence": f"exit {x} at/above plan target {t}", "in_profit": True}
    if not stops.get("path"):
        return {"class": "unknown_no_stop_history", "evidence": "no observed stop rows for this position",
                "in_profit": None if (x is None or e is None) else x >= e}
    return {"class": "manual_sell", "evidence": f"exit {x} matches no observed stop (last {last_fill}) and no target",
            "in_profit": None if (x is None or e is None) else x >= e}


def _sma(closes: list[float], n: int) -> Optional[float]:
    return round(sum(closes[-n:]) / n, 4) if len(closes) >= n else None


def _atr(bars: list[dict[str, Any]], n: int = 14) -> Optional[float]:
    rows = [(_f(b.get("high")), _f(b.get("low")), _f(b.get("close"))) for b in bars]
    if len(rows) < n + 1 or any(h is None or lo is None or c is None for h, lo, c in rows[-(n + 1):]):
        return None
    trs = []
    for (h, lo, _c), (_h0, _l0, pc) in zip(rows[-n:], rows[-(n + 1):-1]):
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return round(sum(trs) / n, 4)


def post_exit_review(*, entry_price: Any, exit_price: Any, exit_at: Any, bars: list[dict[str, Any]],
                     stops: dict[str, Any], exc: dict[str, Any], exit_cause: dict[str, Any]) -> dict[str, Any]:
    """Deterministic facts about the exit, and whether it reads as noise or a trend break (class D). Prose is only
    ever produced by a registered capability (none is registered for this; prose stays null and says so)."""
    t1 = _ts(exit_at)
    upto = [b for b in bars if t1 is None or (_ts(b.get("time") or b.get("date") or b.get("price_date"))
                                               or t1).date() <= t1.date()]
    closes = [c for c in (_f(b.get("close") or b.get("close_price")) for b in upto) if c is not None]
    sma20, sma50 = _sma(closes, 20), _sma(closes, 50)
    atr = _atr(upto)
    x, e = _f(exit_price), _f(entry_price)
    last_close = closes[-1] if closes else None
    giveback_pct = None if exc.get("mfe_price") in (None, 0) or x is None else round(
        (exc["mfe_price"] - x) / exc["mfe_price"] * 100.0, 2)
    giveback_atr = None if atr in (None, 0) or exc.get("mfe_price") is None or x is None else round(
        (exc["mfe_price"] - x) / atr, 2)
    trend_ok = last_close is not None and sma20 is not None and last_close >= sma20 and (
        sma50 is None or last_close >= sma50)
    if last_close is None or sma20 is None:
        verdict, basis = "undetermined", "fewer than 20 closes up to the exit"
    elif not trend_ok:
        verdict, basis = "trend_break", f"exit-day close {last_close} below SMA20 {sma20}" + (
            f" / SMA50 {sma50}" if sma50 else "")
    elif giveback_atr is not None:
        verdict = "noise" if giveback_atr <= NOISE_MAX_GIVEBACK_ATR else "trend_break"
        basis = f"giveback {giveback_atr} ATR from the peak; close {last_close} >= SMA20 {sma20}"
    else:
        verdict = "noise" if (giveback_pct is not None and giveback_pct <= NOISE_MAX_GIVEBACK_PCT) else "undetermined"
        basis = (f"close-basis giveback {giveback_pct}% from the peak close {exc.get('mfe_price')}; exit-day close "
                 f"{last_close} >= SMA20 {sma20}" + (f" and SMA50 {sma50}" if sma50 else "") +
                 "; ATR not measured (no intraday high/low in this read)")
    return {
        "schema": SCHEMA, "provenance": "D",
        "facts": {"entry_price": e, "exit_price": x, "exit_vs_entry_pct": _pct(x, e),
                  "peak": {"price": exc.get("mfe_price"), "at": exc.get("mfe_at"), "basis": exc.get("basis")},
                  "trough": {"price": exc.get("mae_price"), "at": exc.get("mae_at"), "basis": exc.get("basis")},
                  "giveback_from_peak_pct": giveback_pct, "giveback_from_peak_atr": giveback_atr,
                  "observed_stop_path": [p["stop_price_observed"] for p in stops.get("path") or []],
                  "stop_distance_from_peak_pct": None if (exc.get("mfe_price") in (None, 0) or stops.get("last") is None)
                  else round((exc["mfe_price"] - stops["last"]) / exc["mfe_price"] * 100.0, 2),
                  "exit_day_close": last_close, "sma20": sma20, "sma50": sma50, "atr14": atr,
                  "vwap": None, "vwap_note": "no intraday VWAP in the stores this lane reads (NOT_MEASURED)",
                  "exit_cause": exit_cause.get("class")},
        "noise_vs_trend": {"verdict": verdict, "basis": basis},
        "prose": None,
        "prose_status": "not requested: no registered capability for post-exit review prose (registering one is a "
                        "§12 / §23.4 decision); the facts above are the review",
    }


# ── re-entry advice (the desk's classifier, reused) ─────────────────────────


def reentry_advice(*, symbol: str, security_guid: str, round_trip_key: Any, exit_price: Any, exit_at: Any,
                   entry_price: Any, net_pnl: Any, price: Any, price_as_of: Any, rsi: Any,
                   entry_zone: Optional[list[Any]], resistance: Any, conviction: Any, thesis_status: Any,
                   now: datetime) -> dict[str, Any]:
    """When to get back in: the desk's READY / NEAR / WAIT state plus the conditions behind it and the levels to
    watch. Wash window: open only when the exit realised a loss (within WASH_DAYS)."""
    lo, hi = ((entry_zone or [None, None]) + [None, None])[:2]
    lo, hi = _f(lo), _f(hi)
    t1 = _ts(exit_at)
    loss = (_f(net_pnl) is not None and _f(net_pnl) < 0)
    wash_until = (t1 + timedelta(days=rr.WASH_DAYS)).date().isoformat() if (loss and t1) else None
    wash_blocked = bool(loss and t1 and now < t1 + timedelta(days=rr.WASH_DAYS))
    intel = rr.derive_intel_state(price=_f(price), rsi=_f(rsi), as_of=price_as_of, entry_low=lo, entry_high=hi,
                                  held=False, wash_blocked=wash_blocked)
    conv = _f(conviction)
    reclaim = max([v for v in (_f(exit_price), _f(resistance)) if v is not None], default=None)
    conds = [
        {"id": "conviction_floor", "text": f"CIO conviction >= {REENTRY_MIN_CONVICTION:.0f}",
         "met": None if conv is None else conv >= REENTRY_MIN_CONVICTION, "value": conv},
        {"id": "thesis_valid", "text": "thesis active and not invalidated",
         "met": None if thesis_status is None else str(thesis_status).lower() not in ("invalidated", "retired"),
         "value": thesis_status},
        {"id": "wash_window", "text": "wash-sale window clear (only a losing exit opens one)",
         "met": not wash_blocked, "value": wash_until},
        {"id": "pullback_entry", "text": f"pullback into the entry zone {lo}–{hi} with RSI "
                                         f"{rr.RSI_READY_LOW:.0f}–{rr.RSI_READY_HIGH:.0f} (desk READY)",
         "met": intel["state"] == "READY TO REVIEW", "value": intel["state"]},
        {"id": "reclaim", "text": f"or a daily close back above {reclaim} (the exit / resistance level) on volume",
         "met": None if (_f(price) is None or reclaim is None) else _f(price) > reclaim,
         "value": _f(price), "volume_note": "relative volume not in the stores this lane reads (NOT_MEASURED)"},
    ]
    alert_levels = []
    if hi is not None:
        alert_levels.append({"reference": "near_entry", "level": round(hi * (1 + rr.NEAR_PCT / 100.0), 4),
                             "means": f"within {rr.NEAR_PCT:.0f}% above the entry zone (desk NEAR ENTRY)"})
        alert_levels.append({"reference": "in_zone", "level": hi, "means": "entry zone top"})
    if reclaim is not None:
        alert_levels.append({"reference": "reclaim", "level": reclaim, "means": "close above the exit level"})
    return {
        "schema": SCHEMA, "provenance": "D", "classifier": "reentry_rules.derive_intel_state (Re-Entry Decision Desk)",
        "state": intel["state"], "action": intel["action"], "reason": intel["reason"],
        "distance_pct": intel["distance_pct"], "conditions": conds,
        "levels": {"entry_zone": [lo, hi], "reclaim": reclaim, "price": _f(price), "price_as_of": _iso(price_as_of),
                   "rsi": _f(rsi)},
        "alert_levels": alert_levels,
        "lane": "Watch · Re-entry near (desk NEAR ENTRY / READY TO REVIEW)",
        "one_alert": {"kind": "reentry_near", "dedupe_key": f"reentry_near:{security_guid}:{round_trip_key}",
                      "fires_when": "state becomes NEAR ENTRY or READY TO REVIEW",
                      "delivery": "one comms intent (§24.1) once the lane is promoted; the shadow queues nothing"},
        "note": "advice for a person: levels are references, never orders (MBI_BEHAVIOR = 0)",
    }


def stage_phase_for(exit_at: Any, now: datetime) -> tuple[str, str]:
    """(stage, stage_phase) after an exit: exit/exit_review for EXIT_REVIEW_DAYS, then re_entry/re_entry_watch."""
    t1 = _ts(exit_at)
    if t1 is not None and now - t1 <= timedelta(days=EXIT_REVIEW_DAYS):
        return "exit", "exit_review"
    return "re_entry", "re_entry_watch"


def lifecycle_events(security_guid: str, origin: Optional[dict[str, Any]], life: Optional[dict[str, Any]],
                     review: Optional[dict[str, Any]], advice: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """The append-only ``cio_prospect_events`` rows these facts become (idempotent ``event_key`` per fact)."""
    if not life:
        return []
    rk = life.get("round_trip_key") or life.get("position_key")
    ev: list[dict[str, Any]] = []

    def add(etype: str, key: str, at: Any, change: dict[str, Any]) -> None:
        ev.append({"security_guid": security_guid, "event_type": etype, "event_key": f"{etype}:{rk}:{key}",
                   "at": _iso(at), "writer": "InstrumentRecordStore", "change": change})

    if origin:
        add("origin_attributed", "1", (origin.get("at_entry") or {}).get("entry_fill_at"),
            {"classification": origin.get("classification"), "rec_id": (origin.get("linkage") or {}).get("rec_id"),
             "link_confidence": (origin.get("linkage") or {}).get("link_confidence")})
    ent = life.get("entry_fill") or {}
    if ent.get("at"):
        add("entry_fill", "1", ent["at"], {"fill_price": ent.get("price")})
    for i, p in enumerate((life.get("observed_stops") or {}).get("path") or []):
        add("stop_change", str(i), p.get("at") or ent.get("at"),
            {"stop_price_observed": p["stop_price_observed"], "status": p.get("status"), "order_ref": p.get("order_ref")})
    for c in life.get("conviction_while_held") or []:
        add("conviction_change", str(c.get("record")), c.get("at"),
            {"conviction": c.get("conviction"), "stance": c.get("stance"), "rank": c.get("rank")})
    exc = life.get("excursion") or {}
    if exc.get("basis"):
        add("excursion", "1", (life.get("exit_fill") or {}).get("at") or ent.get("at"),
            {k: exc.get(k) for k in ("basis", "mfe_pct", "mfe_price", "mae_pct", "mae_price")})
    xf = life.get("exit_fill") or {}
    if xf.get("at"):
        add("exit_fill", "1", xf["at"], {"fill_price": xf.get("price"), "cause": (life.get("exit_cause") or {}).get("class"),
                                         "pnl": life.get("pnl")})
    if review:
        add("exit_review", "1", xf.get("at"), {"verdict": (review.get("noise_vs_trend") or {}).get("verdict")})
    if advice:
        add("reentry_advice", str(advice.get("state")), xf.get("at"),
            {"state": advice.get("state"), "alert_levels": advice.get("alert_levels")})
    return ev
