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

import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

try:  # one definition of "cash row" shared with the rotation engine (LQ-20261107-1688/1689)
    from lib.holdings_universe import is_cash_row as _is_cash_row
except ImportError:  # this module imported as scripts.lib.home_cio_card
    from .holdings_universe import is_cash_row as _is_cash_row

try:  # the stop-advice producer's own actionable answers (LQ-20261107-1735): never a second copy of the vocabulary
    from lib.since_close_card import CIO_ACTIONABLE as ACTIONABLE
except ImportError:  # this module imported as scripts.lib.home_cio_card
    from .since_close_card import CIO_ACTIONABLE as ACTIONABLE

try:  # one owner of "has this release already printed" (LQ-20261107-1784)
    from lib.cio_buys_gate import event_passed as _event_passed
except ImportError:  # this module imported as scripts.lib.home_cio_card
    from .cio_buys_gate import event_passed as _event_passed

SCHEMA = "HomeCioCard@v1"

#: Proposed rotation sizing rule (v5 mockup, "proposed, needs your OK"): target % of book by sector state.
PROPOSED_TARGET_PCT = {"LEADERSHIP_CONFIRMED": 4.0, "RESILIENT": 3.0, "NEUTRAL": 2.0}
PROPOSED_TRANCHES = (0.30, 0.30, 0.40)
#: Hedge suggestion, proposed rule: up to half of the stressed dollars, staged like the tranches.
PROPOSED_HEDGE_SHARE = 0.5
#: Defensive groups the rotate column considers (market-risk group keys).
DEFENSIVE_KEYS = ("healthcare", "staples", "utilities")
#: A holding of at least this share of the planned tranche-1 shares is that tranche already bought (operator
#: 2026-11-09, LQ-20261107-1689: a held position of "~90% of the tranche" marks tranche 1 FILLED). A rounding's worth
#: of shares short is a fill; a fifth of the tranche short is not. Never applied without a live share count.
FILLED_FRACTION = 0.90
#: Hedge candidates by what is stressed: tech-led stress → Nasdaq-100 inverse.
TECH_KEYS = {"tech", "semis", "ai_basket"}
#: ``ACTIONABLE`` is imported above from its producer (``since_close_card.CIO_ACTIONABLE`` — RAISE / ADD_STOP /
#: FIX_QTY). The old local tuple listed LOWER/TIGHTEN, which stop advice never emits, and omitted FIX_QTY, which it
#: does: a name answered "fix stop size" in one account and "hold" in another ranked as a hold (LQ-20261107-1735).
#: How the CIO's stop-advice answer reads in a table's Stance column (LQ-20261107-1389): the answer alone ("RAISE")
#: does not say WHAT is raised, and it must be visibly the CIO's verdict, not a second engine's label.
_STANCE = {"RAISE": "CIO: raise stop", "ADD_STOP": "CIO: add stop", "FIX_QTY": "CIO: fix stop size", "HOLD": "CIO: hold"}
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
        # LQ-20261107-1784: a release already behind ``now`` is not "the next event". The old date-only test kept
        # "CPI Tue 11-10 08:30 ET" on the card all day, after the print, which is exactly the stale line the
        # operator called out. Fall through to the next event; if none is ahead, the card shows the gate's state.
        if (isinstance(m, Mapping) and str(m.get("date") or "") >= today and m.get("event")
                and not _event_passed(m.get("date"), m.get("time_et"), now)):
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
        # LQ-20261107-1672: the broker's book already answers this ask (since_close_card.reconcile_stop_advice
        # marked it done). It is not an action and must not be counted as one — the operator was told to raise
        # four stops Schwab already had working. A row with no state (an old snapshot) is still an action.
        if str(a.get("state") or "").lower() == "done":
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
    # LQ-20261107-1578: the desk's materiality line is the floor for a proposal, never just a display hint. The
    # card proposed "up to half the stressed dollars" at 0.0% of book, against a semis theme the book does not
    # hold. Below the line (or when the line cannot be read) the honest answer is the gap only.
    material = pct is not None and mat is not None and pct >= mat
    pick = None
    if advice_ok and cands and material:
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


def shares_for(usd: float | None, price: float | None) -> tuple[int | None, float | None]:
    """Whole shares ``floor(usd / price)`` and the cash that does not buy another share (LQ-20261107-1654).

    ``price`` is the CURRENT quote, never the prior daily close: a share count is only honest at the price it would
    actually be bought at. With no price (or no dollars) the count is None, never a count off yesterday's close.
    The ticket's worked example — $15,065 at 184.80 — is 81 shares and $96.20 left. Its "$95.20" is the leftover of
    a $15,064.00 tranche (81 x 184.80 = 14,968.80), so this follows floor + remainder, not the typo."""
    usd_n, price_n = _num(usd), _num(price)
    if usd_n is None or usd_n <= 0 or price_n is None or price_n <= 0:
        return None, None
    # +1e-9 absorbs binary float error when usd is an exact multiple of price (15065 / 184.80 is not, but
    # 1000 / 25.0 is); without it floor(39.99999999999999) would cost the operator a share.
    shares = int(math.floor(usd_n / price_n + 1e-9))
    return shares, round(usd_n - shares * price_n, 2)


def tranche_rows(target_usd: float | None, price: float | None) -> list[dict]:
    """Whole-share sizing for each proposed tranche (LQ-20261107-1654): ``floor(tranche_usd / live price)`` shares
    and the leftover cash, per the operator's 30/30/40 split. Without a current price every count is None."""
    if not target_usd:
        return []
    rows = []
    for i, frac in enumerate(PROPOSED_TRANCHES, start=1):
        usd = round(target_usd * frac, 0)
        shares, left = shares_for(usd, price)
        rows.append({"tranche": i, "usd": usd, "shares": shares, "leftover_usd": left})
    return rows


def tranche1_filled(held_shares: float | None, tranche1_shares: float | None) -> bool:
    """Whether the book already holds the planned tranche-1 shares (LQ-20261107-1689).

    Both numbers must be real: an unknown holding is not a fill, and a tranche with no live price has no share count
    to be filled. A quantity of zero is no holding, and a tranche of zero shares holds nothing to compare against.
    """
    if held_shares is None or tranche1_shares is None:
        return False
    if held_shares != held_shares or tranche1_shares != tranche1_shares:  # NaN
        return False
    if tranche1_shares <= 0 or held_shares <= 0:
        return False
    return held_shares >= FILLED_FRACTION * tranche1_shares


def _held_by_symbol(holdings: Iterable[Mapping] | None) -> dict[str, dict]:
    """{SYMBOL: {shares, avg_cost, as_of, source_id}} from the holdings-store rows the API already joins.

    Cash rows are not holdings. A symbol held in several accounts is one holding: the shares are summed, the average
    cost is the basis-weighted one when every row carries a basis, and ``as_of`` is the NEWEST row's instant (compared
    as instants, never as text — two stamps with different UTC offsets sort wrongly as strings). A row with no
    ``as_of`` cannot be shown as a fact and is left out; the card then reports no holding rather than an undated one.
    """
    acc: dict[str, dict] = {}
    for r in holdings or []:
        if not isinstance(r, Mapping) or not r.get("symbol") or _is_cash_row(dict(r)):
            continue
        q = _num(r.get("shares") if r.get("shares") is not None else r.get("quantity"))
        if q is None or q <= 0:
            continue
        at = _parse_ts(r.get("as_of"))
        if at is None:
            continue
        sym = str(r["symbol"]).upper()
        rec = acc.setdefault(sym, {"shares": 0.0, "basis": 0.0, "basis_known": True, "at": None, "raw": None, "run": None})
        rec["shares"] += q
        basis = _num(r.get("cost_basis_total"))
        if basis is None:
            rec["basis_known"] = False
        else:
            rec["basis"] += basis
        if rec["at"] is None or at > rec["at"]:
            rec["at"], rec["raw"] = at, r.get("as_of")
            rec["run"] = r.get("sync_run_id") if r.get("sync_run_id") is not None else rec["run"]
    out: dict[str, dict] = {}
    for sym, rec in acc.items():
        costs = rec["shares"]
        out[sym] = {
            "shares": round(costs, 4),
            "avg_cost": round(rec["basis"] / costs, 2) if (rec["basis_known"] and costs) else None,
            "as_of": rec["raw"],
            "source_id": f"positions_current:sync_run_{rec['run']}" if rec["run"] is not None else "positions_current",
        }
    return out


def _quote_time(value: str | None) -> datetime | None:
    """An aware ISO instant, or None when the string does not carry one.

    A price whose time cannot be stated is not a current price: the card owes the operator "Prices as of <ET>", and
    an unparsable ``as_of`` would render as an empty time beside a live-looking share count.
    """
    s = str(value or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def _stock_line(one: Mapping, cand: Mapping, rs: Mapping | None) -> str | None:
    """One relational phrase: this name against the group's ETF, on the same 20-session RS (LQ-20261107-1784).

    The operator asked for one line per stock: symbol, held flag, price, and "stronger/weaker than <ETF> by N pts".
    The old line repeated the two RS numbers and compared two closes the operator cannot act on; the numbers stay
    on the record as facts, this is the only reading drawn from them. Descriptive
    only, never "buy"/"sell". Unmeasurable on either side means no phrase, not an invented comparison.
    """
    etf = cand.get("symbol")
    etf_rs = _num(cand.get("rs20"))
    if not rs or etf_rs is None:
        return None
    diff = round(rs["value"] - etf_rs, 1)
    if diff > 0:
        return f"stronger than {etf} by {diff:.1f} pts"
    if diff < 0:
        return f"weaker than {etf} by {abs(diff):.1f} pts"
    return f"matches {etf}"


def _buy_hold(buys: Mapping | None) -> dict | None:
    """Why a NEW tranche may not be proposed now, or None when the CIO's buys line allows one (LQ-20261107-1389).

    The buys line is the CIO's verdict, and the rotate column must not contradict it. With ``gate`` NONE the
    verdict is "no new buys"; with SMALL_ONLY and a pending event it is "nothing new before <event>". A card that
    prints "Buys NONE until CPI Tue" above a live "$26,224 · tranche 1" proposal shows the operator two answers
    and leaves him to pick — the same defect as two as-of dates. The sizing is WITHHELD (not zero) and the gate
    travels with it, so the column can say when a tranche would be allowed instead of dropping it silently.

    The gate is read from the synopsis, never re-derived from the market-risk tier here: the card reports the
    verdict the operator is being shown, and recomputing it would be this module computing a view of its own."""
    buys = buys or {}
    gate = str(((buys.get("gate") or {}).get("value")) or "").strip().upper()
    until = (buys.get("until") or {}).get("value")
    if not (gate == "NONE" or (gate == "SMALL_ONLY" and until)):
        return None
    return {k: buys.get(k) for k in ("gate", "until", "until_short", "line") if buys.get(k)}


def _cio_verdicts(sc: Mapping | None) -> dict[str, str]:
    """{SYMBOL: the CIO's own answer} from the brief's stop advice (LQ-20261107-1389).

    The stressed table printed the market-risk projection's stance — "exit review", its label for a holding in a
    stressed group near or past its stop — while the CIO's actions on the same page said raise the stop (SPCX) or
    hold (ANET). Two verdicts on one screen, and the operator left to reconcile them. The CIO's line is the single
    verdict these surfaces render, so a name the CIO answers is labelled with that answer and nothing else.

    An ask the broker already satisfies (``state`` done, LQ-1672) is not a verdict about the name and does not
    override. Across accounts one actionable answer outranks a hold: "raise the stop in the IRA, hold it in the
    taxable" is still a name whose stop is being raised."""
    brief = (sc or {}).get("cio_brief") or {}
    best: dict[str, str] = {}
    for a in brief.get("stop_advice") or []:
        if not isinstance(a, Mapping) or not a.get("symbol"):
            continue
        ans = str(a.get("answer") or "").strip().upper()
        if not ans or ans == "NO_ACTION" or str(a.get("state") or "").lower() == "done":
            continue
        sym = str(a["symbol"]).upper()
        prev = best.get(sym)
        if prev is None or (ans in ACTIONABLE and prev not in ACTIONABLE):
            best[sym] = ans
    return {sym: _STANCE.get(ans, f"CIO: {ans.lower()}") for sym, ans in best.items()}


def _rotate(mr: Mapping, bars: Iterable[Mapping], advice_ok: bool, catalyst: dict | None,
            quotes: Mapping[str, Mapping] | None = None,
            held: Mapping[str, Mapping] | None = None,
            stocks: Mapping | None = None,
            buys: Mapping | None = None) -> dict | None:
    """``quotes``: {SYMBOL: {price, as_of, source}} from the intraday quote tier (Finviz ≤30 min, else a fresh
    broker row — api_v2._fresh_price_batch). The daily bars still supply the 20-session average and the last close as
    context; they are never a sizing price (operator 2026-11-09: the card sized off the prior close).

    ``held``: {SYMBOL: {shares, avg_cost, as_of, source_id}} from ``_held_by_symbol``. A position of at least
    ``FILLED_FRACTION`` of the planned tranche-1 shares marks that tranche FILLED (LQ-20261107-1689): the card then
    reports the shares, average cost and date actually held, and the plan stops proposing — and stops deducting — the
    money already spent.

    ``stocks``: {group key: {"rows": [...], "as_of": ..., "gap": ...}} from ``lib/rotation_stocks.read``
    (LQ-20261107-1655), listing the individual names under each group's ETF. Not supplied means the column simply
    does not carry them, exactly as before; supplied-but-empty is said on the candidate (``stocks_gap``) rather than
    shown as "none exist".

    ``buys``: the CIO's buys line ({gate, until, until_short, line}), taken from the synopsis the card already
    renders (LQ-20261107-1389). Under a no-buys gate every candidate keeps its target and loses its tranche: no
    dollars, no share count, no plan, and the gate rides out on the column (``gated``) so the row can say which
    release the tranche is waiting for. The gate is read, never re-derived from the market-risk tier. It withholds
    the proposal only: a position the book already holds still reports its FILLED state, because that is a fact
    about the book rather than a command (LQ-20261107-1735)."""
    heat = {h.get("key"): h for h in mr.get("heatmap") or [] if isinstance(h, Mapping)}
    groups = {g.get("key"): g for g in (mr.get("sectors") or {}).get("groups") or [] if isinstance(g, Mapping)}
    lead = ((mr.get("leadership") or {}).get("groups") or {})
    be = mr.get("book_exposure") or {}
    total, cash = _num(be.get("total_usd")), _num(be.get("cash_usd"))
    sat = (mr.get("sectors") or {}).get("as_of") or mr.get("as_of")
    stats = _bar_stats(bars)
    # LQ-20261107-1389: the CIO's buys line, applied to every candidate. A gated column shows the target a group
    # would reach and when a tranche would be allowed — never a dollar amount it may not act on.
    hold = _buy_hold(buys)
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
        q = (quotes or {}).get(str(sym).upper()) if sym else None
        price, price_as_of, price_src = _num((q or {}).get("price")), (q or {}).get("as_of"), (q or {}).get("source")
        # A price is usable for sizing only if it can be traced: a real positive price AND the source that quoted it
        # AND an instant that can be stated. A ≤0 quote is a data error; a nameless quote is not a fact; a quote with
        # no time cannot be shown as "as of" anything.
        q_fact = (fact(price, f"quote:{price_src}", price_as_of)
                  if (price is not None and price > 0 and price_src and _quote_time(price_as_of)) else None)
        if not q_fact:
            price, price_as_of = None, None
        c = item(f"market_risk:sectors:{sat}", sat, key=k, symbol=sym, label=g.get("label") or h.get("label"),
                 state=state, leadership=lc or None, rs20=_r(g.get("rs20") if g.get("rs20") is not None else h.get("rs20")),
                 dd20=_r(g.get("dd20")), qualifies=qualifies)
        if not c:
            continue
        if st:
            c["close"] = fact(st["close"], f"market_ohlcv_bars:daily:{sym}:{st['session']}", st["session"])
            if st.get("avg20") is not None:
                c["avg20"] = fact(st["avg20"], f"market_ohlcv_bars:daily:{sym}:20s", st["session"])
        if q_fact:
            c["price"] = q_fact
        tr = tranche_rows(target_usd, price)
        t1 = None
        if advice_ok and target_pct:
            # Under a no-buys gate there is no tranche to size yet: the target stays (it is where the group would
            # go), the money and the share count are withheld, and the gate rides out on the rotate item.
            t1 = tr[0]["usd"] if (tr and qualifies and not hold) else None
            c["proposed"] = {
                "target_pct": target_pct, "target_usd": target_usd, "tranche1_usd": t1,
                # The headline count is tranche 1's, at the CURRENT price; None (not a daily-close count) when the
                # quote is absent or stale-past-30-min, so the card cannot print a stale share count.
                "shares": tr[0]["shares"] if t1 else None,
                "tranches": tr if not hold else [],
                "priced": price is not None,
                "proposed": True,
            }
            # The book's own position, and whether it already covers the tranche. Only a group that offers a tranche
            # can have one filled: a non-qualifying group shows a target, not a tranche.
            # LQ-20261107-1735 (F3): a buys gate withholds the PROPOSAL, never the fact. `t1` is None under such a
            # gate — that IS the withholding — but the tranche's share count is still in `tr`, so the holding is
            # reported as FILLED either way. Otherwise the first RED/ORANGE morning after the fold tells the
            # operator that a tranche already bought is "after CPI Tue".
            hq = (held or {}).get(str(sym).upper()) if sym else None
            if hq and qualifies and tr:
                t1_shares = tr[0]["shares"]
                hs = _num(hq.get("shares"))
                h_rec = item(hq.get("source_id") or "positions_current", hq.get("as_of"),
                             shares=hs, avg_cost=hq.get("avg_cost"),
                             pct_of_tranche1=(round(min(100.0, hs / t1_shares * 100.0), 1)
                                              if (hs is not None and t1_shares) else None),
                             filled=tranche1_filled(hs, t1_shares))
                if h_rec:
                    c["held"] = h_rec
            # LQ-20261107-1784: once tranche 1 is a fill, the one thing the row still owes the operator is the next
            # step — its size at the CURRENT price and what it waits on. Only a group whose tranche 1 is FILLED has
            # a next tranche to state: a partial fill still owes the rest of tranche 1, and the view's own
            # "tranche 1 … needs your OK" line is suppressed whenever this key exists (grok-a/-9 review, r3).
            if (c.get("held") or {}).get("filled") is True and len(tr) > 1:
                c["next_tranche"] = {"tranche": 2, "usd": tr[1]["usd"], "shares": tr[1]["shares"],
                                     "after": (catalyst or {}).get("label")}
        if stocks is not None:
            # LQ-20261107-1655: the individual names under this group's ETF. The group block already ordered
            # them (held names first, then the best RS20 constituents); here each row becomes traceable values,
            # and a row without a dated close is dropped rather than filled in.
            grp = stocks.get(k) if isinstance(stocks, Mapping) else None
            rows = []
            for r in (grp or {}).get("rows") or []:
                one = {"symbol": str(r.get("symbol") or "").upper(), "held": bool(r.get("held"))}
                close = fact(r.get("close"), r.get("source_id") or f"ticker_prices:daily:{one['symbol']}",
                             r.get("close_as_of"))
                if not close:
                    continue
                if r.get("held_value_usd") is not None:
                    one["held_value_usd"] = fact(r.get("held_value_usd"), f"book_exposure:{sat}", sat)
                one["close"] = close
                # LQ-20261107-1784: a HELD name is a fact about the book, so a name that fails a floor is still
                # listed — with a plain flag ("below $5.00 — review", "no reliable price — review") instead of a
                # silently good-looking number. A non-held name that fails a floor never reaches this loop.
                if r.get("flag"):
                    one["flag"] = str(r["flag"])
                rs = fact(r.get("rs20"), r.get("rs_source_id") or f"ticker_prices:rs20_vs_spy:{one['symbol']}",
                          r.get("rs20_as_of"))
                if rs:
                    one["rs20"] = rs
                if advice_ok and t1 and close["value"]:
                    # the same proposed rule and the same tranche-1 dollars the ETF row carries; a share count
                    # for this name if the tranche went to it whole. Watch groups get neither, as on the ETF row.
                    # The count is 1654's floor at the price the close carries, never a rounded-up approximation.
                    one["tranche1_usd"] = t1
                    one["tranche1_shares"] = shares_for(t1, close["value"])[0]
                    one["proposed"] = True
                line = _stock_line(one, c, rs)
                if line:
                    one["compare"] = line
                row = item(r.get("source_id") or f"ticker_prices:daily:{one['symbol']}", r.get("close_as_of"), **one)
                if row:
                    rows.append(row)
            if rows:
                c["stocks"] = rows
            else:
                c["stocks_gap"] = (grp or {}).get("gap") or "no constituent with a measured close"
            # LQ-20261107-1784: what the floors dropped and why, counted — the operator must be able to tell a
            # short list from a filtered one. The rotation reader owns the sentence; this only carries it out.
            if (grp or {}).get("filter_note"):
                c["stocks_note"] = str(grp["filter_note"])
            if _num((grp or {}).get("min_price")) is not None:
                c["stocks_min_price"] = _num(grp["min_price"])
        cands.append(c)
    if not cands:
        return None
    order = {"LEADERSHIP_CONFIRMED": 0, "RESILIENT": 1, "NEUTRAL": 2}
    cands.sort(key=lambda c: (order.get(c.get("leadership") if c.get("leadership") == "LEADERSHIP_CONFIRMED" else c["state"], 3), -(c.get("rs20") or 0)))
    plan = None
    if advice_ok and total:
        # Only a group that actually offers a tranche is in the sum; a missing size is not a zero-dollar tranche, so
        # nothing is coalesced to 0 here — the filter decides membership, the sum adds the sizes that exist.
        offering = [c for c in cands if (c.get("proposed") or {}).get("tranche1_usd")]
        t1_total = sum(c["proposed"]["tranche1_usd"] for c in offering)
        if t1_total:
            # A tranche the book already bought is not money still to be spent: only the UNFILLED tranches come out of
            # cash (LQ-20261107-1689 — the card used to deduct the filled tranche a second time).
            t1_open = sum(c["proposed"]["tranche1_usd"]
                          for c in offering if not (c.get("held") or {}).get("filled"))
            plan = {"proposed": True, "tranche1_usd": t1_total, "tranche1_pct_book": round(t1_total / total * 100, 1),
                    "tranche1_filled": bool(offering) and all((c.get("held") or {}).get("filled") is True for c in offering),
                    "cash_after_pct": round((cash - t1_open) / total * 100, 1) if cash is not None else None,
                    "tranche2_after": (catalyst or {}).get("label"), "tranche3_when": "market tier YELLOW or better",
                    "split": list(PROPOSED_TRANCHES),
                    "rule": "target 4% of book if leadership confirmed, 3% if resilient, 2% if neutral (starts once resilient); staged 30/30/40"}
    # The quote time the share counts rest on, so the card can say "Prices as of <ET time>" instead of implying the
    # daily close is current. The OLDEST quote in the batch is the honest one: "as of" must hold for every row.
    # Sorted by the INSTANT each quote carries, not by string: two quotes with different UTC offsets sort wrongly as
    # text, and the "as of" must be the true oldest. Every entry here already parsed in _quote_time.
    quoted = sorted((c["price"] for c in cands if c.get("price")), key=lambda p: _quote_time(p["as_of"]))
    prices_as_of = quoted[0]["as_of"] if quoted else None
    missing = [c["symbol"] for c in cands if c.get("qualifies") and not c.get("price")]
    out = item(f"market_risk:sectors:{sat}", sat, candidates=cands, plan=plan, cash_usd=cash,
               prices_as_of=prices_as_of,
               prices_sources=sorted({str(p["source_id"]) for p in quoted}) or None,
               prices_missing=missing or None, gated=hold,
               # LQ-20261107-1784: the CIO's buys line itself (all gates, not only a gating one) rides out so the
               # column can state TODAY from the verdict the operator is being shown — and, because the gate owner
               # is now time-aware, it stops naming a release that has already printed.
               buys=({k: buys.get(k) for k in ("gate", "until", "until_short", "line") if buys.get(k)}
                     if buys else None))
    return out


def _positions(mr: Mapping, verdicts: Mapping[str, str] | None = None) -> dict | None:
    """The stressed holdings table. ``verdicts``: {SYMBOL: the CIO's answer} — when the CIO names a held name, the
    Stance column carries the CIO's verdict and the market-risk projection's own label is kept beside it
    (``stance_engine``) so the override is traceable rather than a lost reading (LQ-20261107-1389)."""
    be = mr.get("book_exposure") or {}
    if not be.get("rows"):
        return None
    sid, at = f"book_exposure:{be.get('as_of')}", be.get("as_of") or mr.get("as_of")
    rows = []
    for r in be.get("rows") or []:
        if not isinstance(r, Mapping) or not _num(r.get("stressed_share")):
            continue
        row = {"symbol": r.get("symbol"), "account_label": r.get("account_label"),
               "value_usd": _num(r.get("value_usd")), "pct_account": _num(r.get("pct_account")),
               "stressed_share": _num(r.get("stressed_share")), "usd_exposed": _num(r.get("usd_exposed")),
               "stop_distance_pct": _num(r.get("stop_distance_pct")), "stance": r.get("stance"),
               "stops_known": bool(be.get("stops_known"))}
        cio = (verdicts or {}).get(str(r.get("symbol") or "").upper())
        if cio:
            row["stance_engine"], row["stance"] = row["stance"], cio
        rows.append(row)
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


def build_panel(mr: Mapping, bars: Iterable[Mapping], advice_ok: bool, actions: list, catalyst: dict | None,
                quotes: Mapping[str, Mapping] | None = None,
                holdings: Iterable[Mapping] | None = None,
                stocks: Mapping | None = None,
                buys: Mapping | None = None,
                verdicts: Mapping[str, str] | None = None) -> dict:
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
        "rotate": _rotate(mr, bars, advice_ok, catalyst, quotes, _held_by_symbol(holdings), stocks, buys),
        "positions": _positions(mr, verdicts),
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
          bars_meta: Mapping | None = None, quotes: Mapping[str, Mapping] | None = None,
          holdings: Iterable[Mapping] | None = None, now: datetime | None = None,
          stocks: Mapping | None = None) -> dict:
    """``stocks``: {group key: {"rows": [...], "as_of": ..., "gap": ...}} from ``lib/rotation_stocks.read``
    (LQ-20261107-1655). Not supplied means the card simply does not carry the constituent rows, exactly as
    before; supplied-but-empty is said on the candidate (``stocks_gap``) rather than shown as "none exist"."""
    now = now or datetime.now(timezone.utc)
    bars = list(bars or [])
    ok, why = advice_gate(mr, since_close)
    out: dict[str, Any] = {
        "schema": SCHEMA, "generated_at": now.isoformat(), "advisory_only": True,
        "inputs": _input_meta(mr, since_close, defense, momentum, bars_meta),
        "advice": {"ok": ok, "reason": why},
    }
    if stocks is not None:
        blocks = [g for g in stocks.values() if isinstance(g, Mapping)]
        # What the caller supplied, not what was drawn: a row with no dated close is dropped by _rotate, and the
        # drawn rows are already on the candidates. Naming it ``supplied`` keeps the two counts from disagreeing
        # silently in the inputs block.
        out["inputs"]["rotation_stocks"] = {
            "present": any(g.get("rows") for g in blocks),
            "as_of": max((str(g.get("as_of")) for g in blocks if g.get("as_of")), default=None),
            "groups": sorted(k for k, g in stocks.items() if isinstance(g, Mapping) and g.get("rows")),
            "supplied": sum(len(g.get("rows") or []) for g in blocks),
        }
    if not mr or mr.get("state") == "not_evaluated" or not mr.get("tier"):
        out.update(card=None, panel=None, notes=[])
        return out
    card = build_card(mr, since_close, now, ok)
    out["card"] = card
    # LQ-20261107-1389: the CIO's buys line and its per-name stop answers reach the panel from the card's own
    # facts, so the two halves of the page cannot disagree. Both are advice, so a stale synopsis (ok False) turns
    # them off exactly as it turns the actions off — a stale verdict is not a verdict.
    buys = ({k: card.get(f"buys_{k}") for k in ("gate", "until", "until_short", "line")} if ok else None)
    out["panel"] = build_panel(mr, bars, ok, card["actions"], card.get("catalyst"), quotes, holdings, stocks,
                               buys=buys, verdicts=_cio_verdicts(since_close) if ok else None)
    out["notes"] = build_notes(mr, defense, momentum, bars)
    return out


def rotation_symbols(mr: Mapping | None) -> list[str]:
    """ETF symbols whose daily bars the rotate column and the notes need (defensive groups + defense get_into)."""
    groups = {g.get("key"): g for g in ((mr or {}).get("sectors") or {}).get("groups") or [] if isinstance(g, Mapping)}
    return sorted({(groups.get(k) or {}).get("symbols", [None])[0] for k in DEFENSIVE_KEYS} - {None})
