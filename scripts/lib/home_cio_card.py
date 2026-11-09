"""Home CIO card + Market Risk panel projection (design cio-card v5, LQ-20261107-1352).

One read-only composition over records that already exist. It never computes a market view of its own:

* ``market_risk``   the Market Risk Engine projection, as GET /api/v2/market-risk/latest serves it (tier, score,
                     categories, sectors, hedge, book_exposure joined API-side, reentry_watch). It is the sector
                     state of record on this card (operator, LQ-1352).
* ``since_close``   the overnight "since last close" snapshot (CIO synopsis + stop_advice).
* ``defense``       defense_recommendations_latest.json, used ONLY for the disagreement notes, never blended.
* ``momentum``      sector_momentum_latest.json, used ONLY for the disagreement notes, never blended.
* ``bars``          daily closes from market_ohlcv_bars (close and 20-session average for the rotation ETFs).

Every scalar is a ``fact``: ``{"value", "source_id", "as_of"}``. Every list item and grouped record carries its own
``source_id`` and ``as_of``. A value whose source or time cannot be named is dropped (None / omitted), never filled
in. A stale market-risk record or a stale/absent CIO synopsis turns the advice sections off with the reason
(``advice.ok = false``); the facts still show, the actions do not.

Advisory only (MBI_BEHAVIOR = 0): nothing here sizes an order, writes a stop or reaches a broker. The rotation
sizing rule is the operator's PROPOSED rule from the v5 mockup and is labelled ``proposed: true`` on every value it
produces until the operator approves it.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

SCHEMA = "HomeCioCard@v1"

#: Proposed rotation sizing rule (v5 mockup, "proposed, needs your OK"): target % of book by sector state.
PROPOSED_TARGET_PCT = {"LEADERSHIP_CONFIRMED": 4.0, "RESILIENT": 3.0, "NEUTRAL": 2.0}
PROPOSED_TRANCHES = (0.30, 0.30, 0.40)
#: Hedge suggestion, proposed rule: up to half of the stressed dollars, staged like the tranches.
PROPOSED_HEDGE_SHARE = 0.5
#: Defensive groups the rotate column considers (market-risk group keys).
DEFENSIVE_KEYS = ("healthcare", "staples", "utilities")
#: Hedge candidates by what is stressed: tech-led stress → Nasdaq-100 inverse.
TECH_KEYS = {"tech", "semis", "ai_basket"}
ACTIONABLE = ("RAISE", "ADD_STOP", "LOWER", "TIGHTEN")
_HELD_RE = re.compile(r"held by the completed-session rule:\s*(\d+)\s+of\s+(\d+)\s+completed trading sessions below this tier recorded;\s*current readings support\s+([A-Z]+)", re.I)
TIERS = ("GREEN", "YELLOW", "ORANGE", "RED")


# ------------------------------------------------------------------------------------------------ provenance
def fact(value: Any, source_id: Any, as_of: Any) -> dict | None:
    """A traceable value, or None when the value, its source or its time is missing (dropped, not caveated)."""
    if value is None or value == "" or not source_id or not as_of:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    return {"value": value, "source_id": str(source_id), "as_of": str(as_of)}


def item(source_id: Any, as_of: Any, **fields: Any) -> dict | None:
    """A grouped record from one source; None when its provenance is missing. ``None`` fields are omitted."""
    if not source_id or not as_of:
        return None
    out = {k: v for k, v in fields.items() if v is not None and v != ""}
    out["source_id"], out["as_of"] = str(source_id), str(as_of)
    return out


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        try:
            d = datetime.combine(date.fromisoformat(str(v)[:10]), datetime.min.time())
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _r(v: Any, nd: int = 1) -> float | None:
    f = _num(v)
    return None if f is None else round(f, nd)


# ------------------------------------------------------------------------------------------------ inputs
def _input_meta(mr: Mapping | None, sc: Mapping | None, defense: Mapping | None, momentum: Mapping | None,
                bars_meta: Mapping | None) -> dict:
    syn = ((sc or {}).get("cio_brief") or {}).get("synopsis") or {}
    fr = (sc or {}).get("freshness") or {}
    return {
        "market_risk": {"present": bool(mr), "source_id": f"market_risk:{(mr or {}).get('as_of')}" if mr else None,
                        "as_of": (mr or {}).get("as_of"), "stale": bool((mr or {}).get("stale")) if mr else None,
                        "age_hours": (mr or {}).get("age_hours")},
        "cio_synopsis": {"present": bool(syn), "source_id": f"cio_synopsis:{syn.get('as_of')}" if syn else None,
                         "as_of": syn.get("as_of"), "stale": bool(fr.get("stale")) if sc else None},
        "defense": {"present": bool(defense), "as_of": (defense or {}).get("generated_at"),
                    "mode": (defense or {}).get("mode"), "role": "notes only"},
        "sector_momentum": {"present": bool(momentum), "as_of": (momentum or {}).get("generated_at"),
                            "role": "notes only"},
        "daily_bars": dict(bars_meta or {"present": False}),
    }


def advice_gate(mr: Mapping | None, sc: Mapping | None) -> tuple[bool, str | None]:
    """Advice shows only on a fresh market-risk record AND a fresh CIO synopsis for the current window."""
    if not mr or mr.get("state") == "not_evaluated" or not mr.get("tier"):
        return False, "market risk not evaluated"
    if mr.get("stale"):
        return False, f"market risk record is stale ({_r(mr.get('age_hours'))} h old)"
    syn = ((sc or {}).get("cio_brief") or {}).get("synopsis")
    if not syn:
        return False, "no CIO synopsis for this window"
    fr = (sc or {}).get("freshness") or {}
    if fr.get("stale") or fr.get("window_current") is False:
        return False, "CIO synopsis is stale or from an earlier window"
    return True, None


# ------------------------------------------------------------------------------------------------ card
def _held(mr: Mapping) -> dict | None:
    m = _HELD_RE.search(str(mr.get("deescalates_if") or ""))
    if not m:
        return None
    n, of, support = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if support not in TIERS or support == str(mr.get("tier") or "").upper():
        return None
    return item(f"market_risk:{mr.get('as_of')}", mr.get("as_of"), readings_support=support, sessions_recorded=n,
                sessions_needed=of, held_tier=mr.get("tier"))


def _drivers(mr: Mapping) -> tuple[list, dict | None, dict | None, list]:
    sid, at = f"market_risk:{mr.get('as_of')}", mr.get("as_of")
    states = {str(c.get("name")): c for c in (mr.get("categories") or []) if isinstance(c, Mapping)}
    drivers = []
    for c in mr.get("contributors") or []:
        pts = _num(c.get("points"))
        if not pts or pts <= 0:
            continue
        cat = states.get(str(c.get("name"))) or {}
        d = item(sid, c.get("as_of") or at, name=c.get("name"), state=cat.get("state"), points=round(pts, 1),
                 detail=c.get("detail"))
        if d:
            drivers.append(d)
    total = round(sum(d["points"] for d in drivers), 1) if drivers else None
    score_sum = fact(total, sid, at)
    cats = [c for c in (mr.get("categories") or []) if isinstance(c, Mapping)]
    calm = [c for c in cats if str(c.get("state") or "").upper() == "CALM"]
    calm_item = item(sid, at, n=len(calm), of=len(cats), names=[c.get("name") for c in calm],
                     details=[f"{c.get('name')}: {c.get('detail')}" for c in calm if c.get("detail")]) if cats else None
    gaps = []
    for c in cats:
        det = str(c.get("detail") or "")
        st = str(c.get("state") or "").upper()
        if st in ("UNMEASURED", "NO_DATA", "GAP", "UNKNOWN") or "level-only" in det or "not scored" in det:
            g = item(sid, c.get("as_of") or at, name=c.get("name"), detail=det)
            if g:
                gaps.append(g)
    return drivers, score_sum, calm_item, gaps


def _catalyst(syn: Mapping, now: datetime) -> dict | None:
    tw = syn.get("this_week") or {}
    sid = f"cio_synopsis:{syn.get('as_of')}"
    today = now.date().isoformat()
    for m in tw.get("macro") or []:
        if isinstance(m, Mapping) and str(m.get("date") or "") >= today and m.get("event"):
            return item(sid, syn.get("as_of"), event=m.get("event"), date=m.get("date"), time_et=m.get("time_et"),
                        label=(syn.get("buys") or {}).get("until"))
    return None


def _held_symbols(mr: Mapping) -> set[str]:
    be = mr.get("book_exposure") or {}
    syms = {str(r.get("symbol")) for r in be.get("rows") or [] if isinstance(r, Mapping)}
    return syms | {str(s) for s in be.get("zero_exposure_symbols") or []}


def _this_week(syn: Mapping, mr: Mapping, now: datetime) -> list:
    tw = syn.get("this_week") or {}
    sid, at = f"cio_synopsis:{syn.get('as_of')}", syn.get("as_of")
    held = _held_symbols(mr)
    out = []
    today = now.date().isoformat()
    for m in tw.get("macro") or []:
        if isinstance(m, Mapping) and m.get("date") and str(m["date"]) >= today:
            out.append(item(sid, at, kind="macro", date=m.get("date"), time_et=m.get("time_et"), label=m.get("event")))
    for e in tw.get("earnings") or []:
        if isinstance(e, Mapping) and e.get("date") and str(e["date"]) >= today:
            out.append(item(sid, at, kind="earnings", date=e.get("date"), label=f"{e.get('symbol')} earnings",
                            symbol=e.get("symbol"), held=str(e.get("symbol")) in held))
    out = [x for x in out if x]
    out.sort(key=lambda x: (x["date"], x.get("time_et") or ""))
    return out


def _actions(sc: Mapping) -> list:
    brief = (sc or {}).get("cio_brief") or {}
    out = []
    for a in brief.get("stop_advice") or []:
        if not isinstance(a, Mapping) or str(a.get("answer") or "").upper() not in ACTIONABLE:
            continue
        at = a.get("as_of") or brief.get("generated_at")
        it = item(f"stop_advice:{at}", at, symbol=a.get("symbol"), account=a.get("account"), answer=a.get("answer"),
                  stop_now=_num(a.get("stop_now")), stop_qty=_num(a.get("stop_qty")), held_qty=_num(a.get("held_qty")),
                  suggested_stop=_num(a.get("suggested_stop")), reason=a.get("reason"))
        if it and it.get("symbol"):
            it["n"] = len(out) + 1
            out.append(it)
    return out


def _sector_line(mr: Mapping) -> dict | None:
    s = mr.get("sectors") or {}
    sid, at = f"market_risk:{mr.get('as_of')}", s.get("as_of") or mr.get("as_of")
    if not s.get("groups"):
        return None
    stressed = list(s.get("stressed") or [])
    return item(sid, at, stressed=stressed, stressed_sectors=_num(s.get("sectors_hit")),
                measured=_num(s.get("sectors_measured")), down_5d=_num(s.get("sectors_down")),
                resilient=list(s.get("resilient") or []))


def build_card(mr: Mapping, sc: Mapping | None, now: datetime, advice_ok: bool) -> dict:
    sid, at = f"market_risk:{mr.get('as_of')}", mr.get("as_of")
    syn = ((sc or {}).get("cio_brief") or {}).get("synopsis") or {}
    ssid, sat = f"cio_synopsis:{syn.get('as_of')}", syn.get("as_of")
    buys, book, re_, dn = (syn.get(k) or {} for k in ("buys", "book", "reentry", "do_now"))
    drivers, score_sum, calm, gaps = _drivers(mr)
    lu = book.get("largest_unprotected_risk") or {}
    card: dict[str, Any] = {
        "tier": fact(mr.get("tier"), sid, at),
        "score": fact(_r(mr.get("score")), sid, at),
        "held": _held(mr),
        "posture": fact(syn.get("posture"), ssid, sat),
        "buys_gate": fact(buys.get("gate"), ssid, sat),
        "buys_until": fact(buys.get("until"), ssid, sat),
        "buys_until_short": fact(buys.get("until_short"), ssid, sat),
        "buys_line": fact(buys.get("line"), ssid, sat),
        "stops_total": fact(dn.get("stop_advice_count"), ssid, sat),
        "stops_actionable": fact(dn.get("actionable_count"), ssid, sat),
        "largest_unprotected": item(lu.get("source_id"), book.get("as_of") or sat, symbol=lu.get("symbol"),
                                    account=lu.get("account"), shares=_num(lu.get("shares")),
                                    price=_num(lu.get("price")), value=_num(lu.get("value"))) if lu.get("symbol") else None,
        "book": item(ssid, book.get("as_of") or sat, positions=book.get("positions"), accounts=book.get("accounts"),
                     cash=_num(book.get("cash"))) if book else None,
        "reentry": item(ssid, re_.get("as_of") or sat, ready=re_.get("stage3"), near=re_.get("stage2"),
                        tracked=re_.get("tracked"), line=re_.get("line")) if re_ else None,
        "drivers": drivers,
        "score_sum": score_sum,
        "calm": calm,
        "gaps": gaps,
        "sectors": _sector_line(mr),
        "shock": fact(syn.get("market", {}).get("shock_class") if isinstance(syn.get("market"), Mapping) else None, ssid, sat),
        "catalyst": _catalyst(syn, now) if syn else None,
        "this_week": _this_week(syn, mr, now) if syn else [],
        "do_now": None,
        "actions": [],
    }
    if advice_ok:
        card["actions"] = _actions(sc or {})
        first = (card["actions"] or [None])[0]
        if first:
            card["do_now"] = item(first["source_id"], first["as_of"], symbol=first["symbol"], account=first.get("account"),
                                  answer=first.get("answer"), suggested_stop=first.get("suggested_stop"),
                                  n=1, of=len(card["actions"]))
    return card


# ------------------------------------------------------------------------------------------------ panel
def _protect(mr: Mapping, actions: list) -> list:
    be = mr.get("book_exposure") or {}
    bsid, bat = f"book_exposure:{be.get('as_of')}", be.get("as_of") or mr.get("as_of")
    rows = [r for r in be.get("rows") or [] if isinstance(r, Mapping)]
    out = []
    for a in actions:
        out.append(dict(a, kind="action"))
    acted = {a["symbol"] for a in actions}
    watch = sorted((r for r in rows if _num(r.get("stop_distance_pct")) is not None and r.get("symbol") not in acted),
                   key=lambda r: _num(r.get("stop_distance_pct")))
    for r in watch[:2]:
        it = item(bsid, bat, kind="watch", symbol=r.get("symbol"), account_label=r.get("account_label"),
                  stop_distance_pct=_num(r.get("stop_distance_pct")), stressed_share=_num(r.get("stressed_share")),
                  value_usd=_num(r.get("value_usd")), stance=r.get("stance"))
        if it:
            out.append(it)
    return out


def _hedge(mr: Mapping, advice_ok: bool) -> dict | None:
    h = mr.get("hedge") or {}
    be = mr.get("book_exposure") or {}
    if not h.get("verdict"):
        return None
    sid, at = f"market_risk:hedge:{h.get('as_of') or mr.get('as_of')}", h.get("as_of") or mr.get("as_of")
    th = h.get("thresholds") or {}
    pct, trig, mat = _num(h.get("stressed_pct_book")), _num(th.get("trigger_book_pct")), _num(th.get("materiality_exposure_pct"))
    lag, lag_t = _num(h.get("lagging_count")), _num(th.get("index_trigger_lagging_sectors"))
    triggers = []
    if pct is not None and trig:
        triggers.append({"key": "stressed_pct_book", "label": "Stressed exposure, % of book", "value": round(pct, 1),
                         "consider": mat, "act": trig, "fill": round(min(1.0, pct / trig), 3), "source_id": sid, "as_of": at})
    if lag is not None and lag_t:
        triggers.append({"key": "lagging_sectors", "label": "Sectors lagging SPY", "value": lag, "act": lag_t,
                         "fill": round(min(1.0, lag / lag_t), 3), "source_id": sid, "as_of": at})
    total = _num(be.get("total_usd"))
    stressed_usd = _num(be.get("stressed_usd")) if be.get("stressed_usd") is not None else _num(h.get("stressed_usd"))
    gap = round(mat / 100.0 * total - stressed_usd, 0) if (mat and total and stressed_usd is not None) else None
    labels = [b.get("label") for b in h.get("stressed_breakdown") or [] if isinstance(b, Mapping) and _num(b.get("usd"))]
    keys = {b.get("key") for b in h.get("stressed_breakdown") or [] if isinstance(b, Mapping)}
    cands = [c for c in h.get("candidates") or [] if c]
    pick = None
    if advice_ok and cands:
        sym = "PSQ" if (keys & TECH_KEYS and "PSQ" in cands) else cands[0]
        size = round(stressed_usd * PROPOSED_HEDGE_SHARE, 0) if stressed_usd else None
        pick = {"symbol": sym, "stress_led_by": labels, "others": [c for c in cands if c != sym],
                "proposed_size_usd": size, "proposed": True, "staged": list(PROPOSED_TRANCHES),
                "basis": "proposed rule: up to half the stressed dollars, staged 30/30/40 (needs operator OK)"}
    return item(sid, at, verdict=h.get("verdict"), triggers=triggers, gap_to_consider_usd=gap if gap and gap > 0 else None,
                stressed_labels=labels, cash_pct_book=_num(be.get("cash_pct_book")), if_triggered=pick)


def _bar_stats(bars: Iterable[Mapping]) -> dict:
    by: dict[str, list] = {}
    for b in bars or []:
        c = _num(b.get("close"))
        if c is None or not b.get("symbol") or not b.get("session"):
            continue
        by.setdefault(str(b["symbol"]).upper(), []).append((str(b["session"]), c))
    out = {}
    for s, rows in by.items():
        rows.sort()
        last = rows[-1]
        tail = [c for _, c in rows[-20:]]
        out[s] = {"close": round(last[1], 2), "session": last[0],
                  "avg20": round(sum(tail) / len(tail), 2) if len(tail) == 20 else None}
    return out


def _rotate(mr: Mapping, bars: Iterable[Mapping], advice_ok: bool, catalyst: dict | None) -> dict | None:
    heat = {h.get("key"): h for h in mr.get("heatmap") or [] if isinstance(h, Mapping)}
    groups = {g.get("key"): g for g in (mr.get("sectors") or {}).get("groups") or [] if isinstance(g, Mapping)}
    lead = ((mr.get("leadership") or {}).get("groups") or {})
    be = mr.get("book_exposure") or {}
    total, cash = _num(be.get("total_usd")), _num(be.get("cash_usd"))
    sat = (mr.get("sectors") or {}).get("as_of") or mr.get("as_of")
    stats = _bar_stats(bars)
    cands = []
    for k in DEFENSIVE_KEYS:
        g, h = groups.get(k) or {}, heat.get(k) or {}
        state = str(h.get("state") or g.get("state") or "").upper()
        if not state or state == "STRESS":
            continue
        sym = (g.get("symbols") or [None])[0]
        lc = str((lead.get(k) or {}).get("class") or "").upper()
        rule = "LEADERSHIP_CONFIRMED" if lc == "LEADERSHIP_CONFIRMED" else state if state in PROPOSED_TARGET_PCT else None
        st = stats.get(str(sym).upper()) if sym else None
        qualifies = rule in ("LEADERSHIP_CONFIRMED", "RESILIENT")
        target_pct = PROPOSED_TARGET_PCT.get(rule) if rule else None
        target_usd = round(total * target_pct / 100.0, 0) if (total and target_pct) else None
        t1 = round(target_usd * PROPOSED_TRANCHES[0], 0) if (target_usd and qualifies) else None
        shares = int(t1 // st["close"]) if (t1 and st and st.get("close")) else None
        c = item(f"market_risk:sectors:{sat}", sat, key=k, symbol=sym, label=g.get("label") or h.get("label"),
                 state=state, leadership=lc or None, rs20=_r(g.get("rs20") if g.get("rs20") is not None else h.get("rs20")),
                 dd20=_r(g.get("dd20")), qualifies=qualifies)
        if not c:
            continue
        if st:
            c["close"] = fact(st["close"], f"market_ohlcv_bars:daily:{sym}:{st['session']}", st["session"])
            if st.get("avg20") is not None:
                c["avg20"] = fact(st["avg20"], f"market_ohlcv_bars:daily:{sym}:20s", st["session"])
        if advice_ok and target_pct:
            c["proposed"] = {"target_pct": target_pct, "target_usd": target_usd, "tranche1_usd": t1, "shares": shares,
                             "proposed": True}
        cands.append(c)
    if not cands:
        return None
    order = {"LEADERSHIP_CONFIRMED": 0, "RESILIENT": 1, "NEUTRAL": 2}
    cands.sort(key=lambda c: (order.get(c.get("leadership") if c.get("leadership") == "LEADERSHIP_CONFIRMED" else c["state"], 3), -(c.get("rs20") or 0)))
    plan = None
    if advice_ok and total:
        t1_total = sum((c.get("proposed") or {}).get("tranche1_usd") or 0 for c in cands)
        if t1_total:
            plan = {"proposed": True, "tranche1_usd": t1_total, "tranche1_pct_book": round(t1_total / total * 100, 1),
                    "cash_after_pct": round((cash - t1_total) / total * 100, 1) if cash is not None else None,
                    "tranche2_after": (catalyst or {}).get("label"), "tranche3_when": "market tier YELLOW or better",
                    "split": list(PROPOSED_TRANCHES),
                    "rule": "target 4% of book if leadership confirmed, 3% if resilient, 2% if neutral (starts once resilient); staged 30/30/40"}
    return item(f"market_risk:sectors:{sat}", sat, candidates=cands, plan=plan, cash_usd=cash)


def _positions(mr: Mapping) -> dict | None:
    be = mr.get("book_exposure") or {}
    if not be.get("rows"):
        return None
    sid, at = f"book_exposure:{be.get('as_of')}", be.get("as_of") or mr.get("as_of")
    rows = []
    for r in be.get("rows") or []:
        if not isinstance(r, Mapping) or not _num(r.get("stressed_share")):
            continue
        rows.append({"symbol": r.get("symbol"), "account_label": r.get("account_label"),
                     "value_usd": _num(r.get("value_usd")), "pct_account": _num(r.get("pct_account")),
                     "stressed_share": _num(r.get("stressed_share")), "usd_exposed": _num(r.get("usd_exposed")),
                     "stop_distance_pct": _num(r.get("stop_distance_pct")), "stance": r.get("stance"),
                     "stops_known": bool(be.get("stops_known"))})
    rows.sort(key=lambda r: -(r["usd_exposed"] or 0))
    more = be.get("more") or {}
    return item(sid, at, rows=rows[:5], extra_rows=max(0, len(rows) - 5), more_count=_num(more.get("count")),
                more_usd=_num(more.get("usd")), zero_exposure_symbols=list(be.get("zero_exposure_symbols") or []),
                stops_known=bool(be.get("stops_known")))


def _stopped_out(mr: Mapping) -> list:
    rw = mr.get("reentry_watch") or {}
    det = mr.get("reentry_detail") or {}
    card = mr.get("reentry_card") or {}
    sessions, max_rows = int(card.get("recent_sessions") or 5), int(card.get("max_rows") or 5)
    ref = _parse_ts(mr.get("as_of"))
    if not ref:
        return []
    # recent sessions → calendar window: weekends add two days per week spanned
    floor = (ref.date() - timedelta(days=sessions + 2 * (sessions // 5 + 1))).isoformat()
    out = []
    for sym, e in rw.items():
        if not isinstance(e, Mapping) or str(e.get("exit_date") or "") < floor:
            continue
        stg = e.get("stages") or {}
        s1 = stg.get("stage1") or {}
        d = det.get(sym) or {}
        it = item(f"market_risk:reentry_watch:{mr.get('as_of')}", e.get("as_of") or mr.get("as_of"), symbol=sym,
                  exit_date=e.get("exit_date"), exit_price=_num(e.get("exit_price")), exit_basis=e.get("exit_basis"),
                  account_label=d.get("exit_account_label"), held_elsewhere=list(d.get("held_elsewhere_labels") or []),
                  last_close=_num(stg.get("last_close")), last_date=stg.get("last_date"),
                  pct_vs_exit=_num(stg.get("pct_vs_exit")), verdict=stg.get("verdict"), status=e.get("status"),
                  headline=e.get("headline"), invalidation=_num(stg.get("invalidation_level")),
                  stage1_met=s1.get("met"), stage1_of=s1.get("of"),
                  waiting_for=[c.get("text") for c in s1.get("conditions") or [] if isinstance(c, Mapping) and not c.get("met") and c.get("text")])
        if it:
            out.append(it)
    out.sort(key=lambda x: x.get("exit_date") or "", reverse=True)
    return out[:max_rows]


def build_panel(mr: Mapping, bars: Iterable[Mapping], advice_ok: bool, actions: list, catalyst: dict | None) -> dict:
    sid, at = f"market_risk:{mr.get('as_of')}", mr.get("as_of")
    be = mr.get("book_exposure") or {}
    bsid, bat = f"book_exposure:{be.get('as_of')}", be.get("as_of") or at
    ep = mr.get("episode") or {}
    lc = be.get("largest_contributor") or {}
    conf = mr.get("confirming") or {}
    return {
        "header": {
            "tier": fact(mr.get("tier"), sid, at), "score": fact(_r(mr.get("score")), sid, at),
            "held": _held(mr), "evaluated": fact(at, sid, at),
            "confirming": item(sid, at, n=conf.get("n"), of=conf.get("of")) if conf.get("of") else None,
            "episode": item(f"market_risk:episode:{ep.get('id')}", ep.get("opened_at"), tier=ep.get("current_tier") or ep.get("tier"),
                            opened_at=ep.get("opened_at"), acknowledged_at=ep.get("acknowledged_at")) if ep.get("id") else None,
            "sectors": _sector_line(mr),
        },
        "exposure": {
            "book_usd": fact(_r(be.get("total_usd"), 0), bsid, bat),
            "cash_usd": fact(_r(be.get("cash_usd"), 0), bsid, bat),
            "cash_pct_book": fact(_r(be.get("cash_pct_book")), bsid, bat),
            "stressed_usd": fact(_r(be.get("stressed_usd"), 0), bsid, bat),
            "stressed_pct_book": fact(_r(be.get("stressed_pct_book")), bsid, bat),
            "largest": item(bsid, bat, symbol=lc.get("symbol"), account_label=lc.get("account_label"),
                            group=lc.get("group"), share=_num(lc.get("share"))) if lc.get("symbol") else None,
        },
        "protect": _protect(mr, actions) if advice_ok else [],
        "hedge": _hedge(mr, advice_ok),
        "rotate": _rotate(mr, bars, advice_ok, catalyst),
        "positions": _positions(mr),
        "stopped_out": _stopped_out(mr),
    }


# ------------------------------------------------------------------------------------------------ notes
_UP, _DOWN = {"RESILIENT", "LEADING", "IMPROVING", "LEADERSHIP_CONFIRMED"}, {"STRESS", "LAGGING", "WEAKENING"}


def _direction(state: Any) -> str:
    """The two engines name states differently; compare what they mean (up / down / flat), not the words."""
    s = str(state or "").upper()
    return "up" if s in _UP else "down" if s in _DOWN else "flat"


def build_notes(mr: Mapping, defense: Mapping | None, momentum: Mapping | None, bars: Iterable[Mapping]) -> list:
    """Where the three sector engines and the defense desk disagree with the market-risk record. Shown, never blended."""
    notes = []
    groups = {g.get("key"): g for g in (mr.get("sectors") or {}).get("groups") or [] if isinstance(g, Mapping)}
    by_etf = {(g.get("symbols") or [None])[0]: g for g in groups.values() if g.get("kind") == "sector" or g.get("key") in DEFENSIVE_KEYS}
    sat = (mr.get("sectors") or {}).get("as_of") or mr.get("as_of")
    if momentum and momentum.get("rows"):
        mat = momentum.get("generated_at")
        diffs = []
        for r in momentum["rows"]:
            g = by_etf.get(r.get("etf"))
            if g and r.get("state") and _direction(r["state"]) != _direction(g.get("state")):
                diffs.append(f"{g.get('label')}: market risk {g.get('state')}, sector momentum {r['state']}")
        if diffs:
            n = item(f"sector_momentum:{mat}", mat, topic="Sector state",
                     text="; ".join(diffs[:6]) + ". This card uses the market-risk record (" + str(sat) + ").",
                     compared_with=f"market_risk:sectors:{sat}")
            if n:
                notes.append(n)
    if defense:
        dat = defense.get("generated_at")
        dsid = f"defense_recommendations:{dat}"
        stats = _bar_stats(bars)
        gi = ((defense.get("groups") or {}).get("get_into")) or []
        px = []
        for g in gi:
            for ins in (g or {}).get("instruments") or []:
                s = str(ins.get("symbol") or "").upper()
                if s in stats and _num(ins.get("price")) is not None and abs(_num(ins["price"]) - stats[s]["close"]) > 0.005:
                    px.append(f"{s}: defense desk {ins['price']:.2f}, daily close {stats[s]['close']:.2f} ({stats[s]['session']})")
        if px:
            notes.append(item(dsid, dat, topic="Prices", text="; ".join(px[:4]) + ". This card uses the daily bars."))
        titles = [str(g.get("title")) for g in gi if isinstance(g, Mapping) and g.get("title")]
        if titles:
            notes.append(item(dsid, dat, topic="Sector calls (defense desk)", text="; ".join(titles[:4])))
        ss = ((defense.get("groups") or {}).get("short_side")) or []
        hv = (mr.get("hedge") or {}).get("verdict")
        if ss and hv:
            s0 = ss[0] or {}
            notes.append(item(dsid, dat, topic="Hedge",
                              text=f"Market risk: {hv}. Defense desk: {s0.get('title')} · {s0.get('size_band')}."))
        eq = defense.get("account_equities") or {}
        tot = _num((mr.get("book_exposure") or {}).get("total_usd"))
        if eq and tot:
            s = sum(_num(v) or 0 for v in eq.values())
            notes.append(item(dsid, dat, topic="Sizing base",
                              text=f"Defense desk sizes on account equity without cash (${s:,.0f} across {len(eq)} accounts); "
                                   f"this panel sizes on the whole book incl. cash (${tot:,.0f})."))
        notes.append(item(dsid, dat, topic="Freshness",
                          text=f"Defense record mode {defense.get('mode') or 'unknown'}, generated {dat}."))
    return [n for n in notes if n]


# ------------------------------------------------------------------------------------------------ entry
def build(mr: Mapping | None, since_close: Mapping | None, *, defense: Mapping | None = None,
          momentum: Mapping | None = None, bars: Iterable[Mapping] | None = None,
          bars_meta: Mapping | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    bars = list(bars or [])
    ok, why = advice_gate(mr, since_close)
    out: dict[str, Any] = {
        "schema": SCHEMA, "generated_at": now.isoformat(), "advisory_only": True,
        "inputs": _input_meta(mr, since_close, defense, momentum, bars_meta),
        "advice": {"ok": ok, "reason": why},
    }
    if not mr or mr.get("state") == "not_evaluated" or not mr.get("tier"):
        out.update(card=None, panel=None, notes=[])
        return out
    card = build_card(mr, since_close, now, ok)
    out["card"] = card
    out["panel"] = build_panel(mr, bars, ok, card["actions"], card.get("catalyst"))
    out["notes"] = build_notes(mr, defense, momentum, bars)
    return out


def rotation_symbols(mr: Mapping | None) -> list[str]:
    """ETF symbols whose daily bars the rotate column and the notes need (defensive groups + defense get_into)."""
    groups = {g.get("key"): g for g in ((mr or {}).get("sectors") or {}).get("groups") or [] if isinstance(g, Mapping)}
    return sorted({(groups.get(k) or {}).get("symbols", [None])[0] for k in DEFENSIVE_KEYS} - {None})
