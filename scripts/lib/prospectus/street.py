"""The institutional ("Street") blocks — what analysts are saying, what the Street expects, what is coming, who is
positioned how, and where the valuation sits against its own history (operator 2026-10-27: "does it also have analyst
reviews and what are analysts saying along with catalysts? … something I can use on the Goldman desk, Citadel,
anywhere").

Every number is computed here, in Python, from house stores read through ``data_broker.street_detail`` (no provider
call, no per-process market fetch); the writer receives the results as cited facts and never does arithmetic.

Blocks (keys in ``bundle.blocks``):

* ``analyst_coverage``   rating distribution now and its trend, the target distribution and its 30/60/90-day trend,
                         and the analyst ACTION LOG (firm, date, action, old → new rating, old → new target, link).
* ``estimates``          the existing block, extended: FY1 / FY2 and next-quarter EPS and revenue consensus with the
                         number of estimates, EPS trend 7/30/60/90 days, up/down revisions, the last 8 quarters of
                         EPS beat / miss with the 1-day and 5-session price reaction from house closes.
* ``catalyst_calendar``  forward (next earnings with time and the options-implied move, ex-dividend, FOMC) and
                         backward (past earnings and material catalysts with their price reaction).
* ``positioning``        short interest, insider Form 4 net (90 days), 13F holders, options put/call, skew, ATM IV,
                         IV rank / percentile and term structure.
* ``valuation_history``  trailing P/E from reported EPS and house closes against its own range (up to 5 years).
* ``fundamentals_xbrl``  the last quarters of SEC XBRL revenue, operating income and margin, net income, operating
                         cash flow, and cash / long-term debt / net debt.

Each block names what the house does not hold in ``gaps``; nothing is estimated to fill one. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import re
import statistics
from pathlib import Path
from typing import Any, Callable, Optional

from . import ROOT
from .blocks import _series, is_session

SCHEMA = "ProspectusStreet@v1"
#: Blocks that do not apply to a fund (hidden on fund reports, like the existing estimates / ownership blocks).
FUND_HIDDEN = ("analyst_coverage", "valuation_history", "fundamentals_xbrl")
STALE_DAYS = {"targets": 10, "extended": 10, "options": 5, "distribution_history": 45}
ACTION_LABEL = {"up": "Upgrade", "down": "Downgrade", "init": "Initiation", "main": "Maintains", "reit": "Reiterates",
                "upgrade": "Upgrade", "downgrade": "Downgrade"}
PERIOD_LABEL = {"0q": "Current quarter", "+1q": "Next quarter", "0y": "Current fiscal year (FY1)",
                "+1y": "Next fiscal year (FY2)", "-1q": "Last quarter"}
RATING_KEYS = (("strong_buy", "Strong buy"), ("buy", "Buy"), ("hold", "Hold"), ("sell", "Sell"), ("strong_sell", "Strong sell"))
# A headline counts as an analyst action only when it names one; "analyst roundup" style items are not actions.
ACTION_RE = re.compile(r"\b(upgrade[sd]?|downgrade[sd]?|initiat\w*|reiterat\w*|raises?|lifts?|boosts?|cuts?|lowers?|"
                       r"trims?|price target|PT)\b", re.I)
FIRM_RE = re.compile(r"^(?P<firm>[A-Z][\w&.'-]*(?:\s+(?:[A-Z][\w&.'-]*|&|of|and)){0,4})\s+"
                     r"(?P<verb>upgrades?|downgrades?|initiates?|reiterates?|raises?|lifts?|boosts?|cuts?|lowers?|"
                     r"trims?|maintains?|starts?)\b")


# ── small helpers ──────────────────────────────────────────────────────────────────────────────────────────────
def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _day(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _norm(row: dict) -> dict:
    """yfinance column names vary in case and punctuation ("upLast7days", "downLast7Days", "EPS Estimate")."""
    return {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in (row or {}).items()}


def _age(as_of: Any, now: datetime) -> Optional[int]:
    d = _day(as_of)
    return (now.date() - d).days if d else None


def _round(v: Optional[float], n: int = 2) -> Optional[float]:
    return None if v is None else round(v, n)


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """(a / b - 1) × 100, or None."""
    if a is None or b is None or b == 0:
        return None
    return round((a / b - 1) * 100, 2)


class Closes:
    """House session closes with "close on or before" / "close after" lookups."""

    def __init__(self, bars: Any):
        self.s = _series(bars or [])
        self.days = [d for d, _ in self.s]

    def on_or_before(self, d: date) -> Optional[tuple[str, float]]:
        key = d.isoformat()
        best = None
        for day, c in self.s:
            if day <= key:
                best = (day, c)
            else:
                break
        return best

    def nth_after(self, d: date, n: int) -> Optional[tuple[str, float]]:
        key = d.isoformat()
        after = [(day, c) for day, c in self.s if day > key]
        return after[n - 1] if len(after) >= n else None

    def last(self) -> Optional[tuple[str, float]]:
        return self.s[-1] if self.s else None


def reaction(closes: Closes, when: Any, timing: str | None) -> dict:
    """Price reaction to an event: base = the last close BEFORE the market could react, then the next session
    (1-day) and the 5th session (5-day). After-close / unknown-time events react the next session; a pre-market event
    reacts the same session."""
    d = _day(when)
    if d is None or not closes.s:
        return {"base_date": None, "one_day_pct": None, "five_day_pct": None}
    if timing in ("bmo", "dmh"):  # the market reacts the same session
        base = closes.on_or_before(d - timedelta(days=1))
        first = closes.nth_after(d - timedelta(days=1), 1)
        fifth = closes.nth_after(d - timedelta(days=1), 5)
    else:
        base = closes.on_or_before(d)
        first = closes.nth_after(d, 1)
        fifth = closes.nth_after(d, 5)
    return {"base_date": base[0] if base else None,
            "one_day_pct": _pct(first[1], base[1]) if base and first else None,
            "five_day_pct": _pct(fifth[1], base[1]) if base and fifth else None}


def _timing(ts: Any) -> Optional[str]:
    """'bmo' / 'amc' from an earnings timestamp's local hour; None when the time is not recorded (midnight)."""
    m = re.search(r"T(\d{2}):(\d{2})", str(ts or ""))
    if not m:
        return None
    h = int(m.group(1)) + int(m.group(2)) / 60
    if h == 0:
        return None
    return "bmo" if h < 9.5 else "amc" if h >= 16 else "dmh"


# ── analyst coverage ──────────────────────────────────────────────────────────────────────────────────────────
def _distribution_rows(ext: dict, history: list[dict]) -> tuple[list[dict], str, Optional[str]]:
    """[{period, strong_buy..strong_sell, total}] newest first, the source label and its as-of."""
    rows = []
    for r in ext.get("recommendations") or []:
        n = _norm(r)
        period = str(n.get("period") or "")
        rows.append({"period": period, "strong_buy": _f(n.get("strongbuy")), "buy": _f(n.get("buy")),
                     "hold": _f(n.get("hold")), "sell": _f(n.get("sell")), "strong_sell": _f(n.get("strongsell"))})
    if rows:
        return rows, "Yahoo recommendation trend (pro_analyst_fetch extended)", ext.get("snapshot_date")
    for r in history or []:
        rows.append({"period": r.get("period"), **{k: _f(r.get(k)) for k, _ in RATING_KEYS}})
    as_of = (history or [{}])[0].get("as_of") if history else None
    return rows, "analyst_data_history (monthly counts recorded before the provider was retired)", as_of


def _total(r: dict) -> Optional[int]:
    vals = [r.get(k) for k, _ in RATING_KEYS]
    return int(sum(v for v in vals if v is not None)) if any(v is not None for v in vals) else None


def _bullish_share(r: dict) -> Optional[float]:
    t = _total(r)
    if not t:
        return None
    return round(((r.get("strong_buy") or 0) + (r.get("buy") or 0)) / t * 100, 1)


def _target_at(hist: list[dict], d: date, tolerance_days: int = 10) -> Optional[dict]:
    """The newest row on or before ``d`` — only when it is within ``tolerance_days`` of ``d`` (a gap in the history
    never passes an older row off as "30 days ago")."""
    best = None
    for r in hist:
        rd = _day(r.get("date"))
        if rd and rd <= d and _f(r.get("mean")) is not None:
            best = r
    if best and (d - _day(best["date"])).days > tolerance_days:
        return None
    return best


def parse_action_headline(headline: str) -> dict:
    """Firm and verb from a headline like "Example Bank upgrades Zeeco to Buy" — None fields when not stated."""
    h = re.sub(r"^\W+", "", str(headline or "")).strip()
    m = FIRM_RE.match(h)
    firm = m.group("firm") if m else None
    verb = (m.group("verb") if m else (ACTION_RE.search(h).group(1) if ACTION_RE.search(h) else "")).lower()
    action = ("up" if verb.startswith("upgrade") else "down" if verb.startswith("downgrade") else
              "init" if verb.startswith(("initiat", "start")) else "reit" if verb.startswith(("reiterat", "maintain")) else
              "target_up" if verb.startswith(("raise", "lift", "boost")) else
              "target_down" if verb.startswith(("cut", "lower", "trim")) else None)
    to = re.search(r"\bto\s+(Strong Buy|Buy|Outperform|Overweight|Neutral|Hold|Equal[- ]Weight|Market Perform|Sector "
                   r"Perform|Underperform|Underweight|Sell)\b", h, re.I)
    tgt = re.search(r"(?:price target|PT|target)[^$\d]{0,30}\$(\d[\d,]*(?:\.\d+)?)", h, re.I)
    return {"firm": firm, "action": action, "to_grade": to.group(1) if to else None,
            "target": _f(tgt.group(1).replace(",", "")) if tgt else None}


def action_log(ext: dict, catalysts: list[dict], *, sym: str, name: str | None, now: datetime,
               days: int = 365, limit: int = 25) -> tuple[list[dict], dict]:
    """The analyst action log: structured Yahoo rows first, then catalyst_events analyst items that NAME a firm and
    an action and are not already in the structured rows (same firm within ±3 days). Newest first."""
    out: list[dict] = []
    cut = now.date() - timedelta(days=days)
    for r in ext.get("upgrades_downgrades") or []:
        n = _norm(r)
        d = _day(n.get("index") or n.get("gradedate"))
        if not d or d < cut:
            continue
        act = str(n.get("action") or "").lower()
        out.append({"date": d.isoformat(), "firm": n.get("firm") or None, "action": act or None,
                    "action_label": ACTION_LABEL.get(act, act.title() or "n/a"),
                    "from_grade": n.get("fromgrade") or None, "to_grade": n.get("tograde") or None,
                    "prior_target": _f(n.get("priorpricetarget")) or None, "target": _f(n.get("currentpricetarget")) or None,
                    "target_action": n.get("pricetargetaction") or None, "source": "yahoo", "url": None})
    structured = len(out)
    from . import news_gate  # noqa: PLC0415 - the same relevance gate the report's catalysts pass
    kept, _dropped = news_gate.filter_facts([{"headline": c.get("headline"), **c} for c in catalysts or []], sym, name or sym,
                                            text_key="headline")
    added = rejected = 0
    for c in kept:
        d = _day(c.get("at"))
        p = parse_action_headline(c.get("headline") or "")
        names = news_gate.relevance({"title": c.get("headline")}, sym, {"name": name})[0] == "relevant"
        if not d or d < cut or not p["firm"] or not p["action"] or not names:
            rejected += 1
            continue
        dup = any(x.get("firm") and p["firm"] and x["firm"].split()[0].lower() == p["firm"].split()[0].lower()
                  and abs((_day(x["date"]) - d).days) <= 3 for x in out)
        if dup:
            continue
        out.append({"date": d.isoformat(), "firm": p["firm"], "action": p["action"],
                    "action_label": {"target_up": "Raises target", "target_down": "Cuts target"}.get(
                        p["action"], ACTION_LABEL.get(p["action"], p["action"])),
                    "from_grade": None, "to_grade": p["to_grade"], "prior_target": None, "target": p["target"],
                    "target_action": None, "source": f"news: {c.get('source') or 'feed'}", "url": c.get("url"),
                    "headline": str(c.get("headline") or "")[:200]})
        added += 1
    out.sort(key=lambda x: x["date"], reverse=True)
    return out[:limit], {"structured": structured, "from_news": added, "news_rejected": rejected}


def analyst_coverage(raw: dict, *, sym: str, name: str | None, now: datetime, last_close: Optional[float]) -> dict:
    ext = raw.get("extended") or {}
    hist = [r for r in raw.get("target_history") or [] if _f(r.get("mean")) is not None]
    gaps: list[str] = []
    rows, dist_src, dist_as_of = _distribution_rows(ext, raw.get("rating_history") or [])
    dist = None
    if rows:
        cur = rows[0]
        back = rows[3] if len(rows) > 3 else rows[-1]
        dist = {"current": {**cur, "total": _total(cur), "bullish_pct": _bullish_share(cur)},
                "three_months_ago": {**back, "total": _total(back), "bullish_pct": _bullish_share(back)} if back is not cur else None,
                "history": [{**r, "total": _total(r), "bullish_pct": _bullish_share(r)} for r in rows[:6]],
                "source": dist_src, "as_of": str(dist_as_of)[:10] if dist_as_of else None}
        b0, b3 = dist["current"]["bullish_pct"], (dist.get("three_months_ago") or {}).get("bullish_pct")
        dist["trend_90d"] = (None if b0 is None or b3 is None else "more bullish" if b0 - b3 >= 3 else
                             "less bullish" if b3 - b0 >= 3 else "unchanged")
        dist["bullish_change_pts"] = None if b0 is None or b3 is None else round(b0 - b3, 1)
        age = _age(dist_as_of, now)
        if age is not None and age > STALE_DAYS["distribution_history"]:
            dist["stale"] = f"{age} days old"
            gaps.append(f"rating distribution: newest counts are {age} days old ({dist_src})")
    else:
        gaps.append("rating distribution (strong buy … strong sell counts): not in the house for this symbol")
    targets = None
    if hist:
        newest = hist[-1]
        tdate = _day(newest["date"]) or now.date()
        trend = {}
        for days in (30, 60, 90):
            past = _target_at(hist, tdate - timedelta(days=days))
            trend[f"d{days}"] = None if not past else {
                "date": past["date"], "mean": _round(_f(past.get("mean"))), "low": _round(_f(past.get("low"))),
                "high": _round(_f(past.get("high"))), "analysts": past.get("analysts"),
                "rating_mean": _round(_f(past.get("rating_mean")), 2),
                "mean_change_pct": _pct(_f(newest.get("mean")), _f(past.get("mean")))}
        targets = {"as_of": newest["date"], "mean": _round(_f(newest.get("mean"))), "median": _round(_f(newest.get("median"))),
                   "low": _round(_f(newest.get("low"))), "high": _round(_f(newest.get("high"))),
                   "analysts": newest.get("analysts"), "rating_mean": _round(_f(newest.get("rating_mean")), 2),
                   "rating_key": newest.get("rating_key"), "trend": trend,
                   "upside_to_mean_pct": _pct(_f(newest.get("mean")), last_close),
                   "dispersion_pct": (_round((_f(newest.get("high")) - _f(newest.get("low"))) / _f(newest.get("mean")) * 100, 1)
                                      if _f(newest.get("high")) and _f(newest.get("low")) and _f(newest.get("mean")) else None),
                   "series": [[r["date"], _round(_f(r.get("mean"))), _round(_f(r.get("low"))), _round(_f(r.get("high")))]
                              for r in hist[-130:]]}
        age = _age(newest["date"], now)
        if age is not None and age > STALE_DAYS["targets"]:
            targets["stale"] = f"{age} days old"
            gaps.append(f"price targets: newest consensus row is {age} days old")
        if not any(trend.values()):
            gaps.append("price-target trend: the house history is shorter than 30 days")
    else:
        gaps.append("price targets: no consensus row in the house")
    actions, counts = action_log(ext, raw.get("analyst_catalysts") or [], sym=sym, name=name, now=now)
    if not ext.get("upgrades_downgrades"):
        gaps.append("structured analyst action history (firm, old → new rating and target): not captured yet for this "
                    "symbol (pro_analyst_fetch extended capture); actions below come from news headlines only"
                    if actions else "analyst action log: no structured history captured and no news headline names "
                                    "a firm's action")
    since90 = (now.date() - timedelta(days=90)).isoformat()
    recent = [a for a in actions if a["date"] >= since90]
    tally = {"upgrades": sum(1 for a in recent if a["action"] == "up"),
             "downgrades": sum(1 for a in recent if a["action"] == "down"),
             "initiations": sum(1 for a in recent if a["action"] == "init"),
             "target_raises": sum(1 for a in recent if (a.get("target") and a.get("prior_target") and a["target"] > a["prior_target"])
                                  or a["action"] == "target_up"),
             "target_cuts": sum(1 for a in recent if (a.get("target") and a.get("prior_target") and a["target"] < a["prior_target"])
                                or a["action"] == "target_down")}
    return {"schema": SCHEMA, "distribution": dist, "targets": targets, "actions": actions, "actions_90d": tally,
            "action_sources": counts, "gaps": gaps}


# ── estimates ─────────────────────────────────────────────────────────────────────────────────────────────────
def _by_period(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for r in rows or []:
        n = _norm(r)
        p = str(n.get("index") or n.get("period") or "")
        if p:
            out[p] = n
    return out


def eps_history(ext: dict, closes: Closes, *, now: datetime, limit: int = 8) -> list[dict]:
    """Reported quarters newest first: date, timing, EPS estimate / actual, surprise %, 1-day / 5-day reaction."""
    out = []
    for r in ext.get("earnings_dates") or []:
        n = _norm(r)
        when = n.get("index") or n.get("earningsdate")
        d = _day(when)
        act, est = _f(n.get("reportedeps")), _f(n.get("epsestimate"))
        if not d or d > now.date() or act is None:
            continue
        timing = _timing(when)
        surprise = _round((act - est) / abs(est) * 100, 2) if est not in (None, 0) else _f(n.get("surprise"))
        out.append({"date": d.isoformat(), "timing": timing, "actual": act, "estimate": est, "surprise_pct": surprise,
                    "beat": None if est is None else (act > est) - (act < est), **reaction(closes, d, timing)})
    if not out:  # quarter-end rows without report dates: no price reaction
        for r in ext.get("earnings_history") or []:
            n = _norm(r)
            d = _day(n.get("index") or n.get("quarter"))
            act, est = _f(n.get("epsactual")), _f(n.get("epsestimate"))
            if d and act is not None:
                out.append({"date": d.isoformat(), "timing": None, "actual": act, "estimate": est,
                            "surprise_pct": _round((act - est) / abs(est) * 100, 2) if est not in (None, 0) else None,
                            "beat": None if est is None else (act > est) - (act < est), "quarter_end": True,
                            "base_date": None, "one_day_pct": None, "five_day_pct": None})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out[:limit]


def estimates_block(base: dict, ext: dict, closes: Closes, *, now: datetime) -> dict:
    """The existing ``estimates`` block plus consensus, EPS trend, revisions and 8-quarter beat / miss history."""
    est = dict(base or {})
    gaps = [g for g in est.get("gaps") or [] if not g.startswith(("EPS surprise history", "90-day estimate revisions"))]
    eps, rev = _by_period(ext.get("earnings_estimate")), _by_period(ext.get("revenue_estimate"))
    trend, revs = _by_period(ext.get("eps_trend")), _by_period(ext.get("eps_revisions"))
    consensus = []
    for p in ("0q", "+1q", "0y", "+1y"):
        e, r = eps.get(p) or {}, rev.get(p) or {}
        if not e and not r:
            continue
        consensus.append({"period": p, "label": PERIOD_LABEL.get(p, p), "eps_avg": _f(e.get("avg")),
                          "eps_low": _f(e.get("low")), "eps_high": _f(e.get("high")), "eps_n": _f(e.get("numberofanalysts")),
                          "eps_year_ago": _f(e.get("yearagoeps")),
                          "eps_growth_pct": _round(_f(e.get("growth")) * 100, 1) if _f(e.get("growth")) is not None else None,
                          "rev_avg": _f(r.get("avg")), "rev_low": _f(r.get("low")), "rev_high": _f(r.get("high")),
                          "rev_n": _f(r.get("numberofanalysts")), "rev_year_ago": _f(r.get("yearagorevenue")),
                          "rev_growth_pct": _round(_f(r.get("growth")) * 100, 1) if _f(r.get("growth")) is not None else None})
    eps_trend = []
    for p in ("0q", "+1q", "0y", "+1y"):
        t = trend.get(p)
        if not t:
            continue
        cur = _f(t.get("current"))
        row = {"period": p, "label": PERIOD_LABEL.get(p, p), "current": cur}
        for k, lab in (("7daysago", "d7"), ("30daysago", "d30"), ("60daysago", "d60"), ("90daysago", "d90")):
            row[lab] = _f(t.get(k))
            row[f"chg_{lab}_pct"] = _pct(cur, _f(t.get(k)))
        eps_trend.append(row)
    revisions = []
    for p in ("0q", "+1q", "0y", "+1y"):
        r = revs.get(p)
        if not r:
            continue
        revisions.append({"period": p, "label": PERIOD_LABEL.get(p, p), "up_7d": _f(r.get("uplast7days")),
                          "up_30d": _f(r.get("uplast30days")), "down_7d": _f(r.get("downlast7days")),
                          "down_30d": _f(r.get("downlast30days"))})
    hist = eps_history(ext, closes, now=now)
    if hist:
        est["eps_surprises"] = hist
        beats = [h for h in hist if h.get("beat") is not None]
        est["beat_rate"] = {"quarters": len(beats), "beats": sum(1 for h in beats if h["beat"] > 0),
                            "misses": sum(1 for h in beats if h["beat"] < 0),
                            "avg_surprise_pct": _round(statistics.mean([h["surprise_pct"] for h in hist
                                                                         if h.get("surprise_pct") is not None]), 2)
                            if any(h.get("surprise_pct") is not None for h in hist) else None,
                            "avg_abs_one_day_pct": _round(statistics.mean([abs(h["one_day_pct"]) for h in hist
                                                                            if h.get("one_day_pct") is not None]), 2)
                            if any(h.get("one_day_pct") is not None for h in hist) else None}
        if len(hist) < 8:
            gaps.append(f"EPS beat / miss history: {len(hist)} of 8 quarters in the house")
    elif len(est.get("eps_surprises") or []) < 4:
        gaps.append(f"EPS surprise history: the house keeps the latest quarter only "
                    f"({len(est.get('eps_surprises') or [])} of 8)")
    up = sum(r["up_30d"] or 0 for r in revisions if r["period"] in ("0q", "0y"))
    down = sum(r["down_30d"] or 0 for r in revisions if r["period"] in ("0q", "0y"))
    if revisions:
        est["revisions_90d"] = {"up": up, "down": down, "window": "30d (current quarter + FY1)"}
    else:
        gaps.append("estimate revisions (up / down): not captured yet for this symbol")
    if not consensus:
        gaps.append("EPS / revenue consensus (FY1, FY2, next quarter): not captured yet for this symbol")
    gaps.append("revenue beat / miss history: no house source records reported revenue against the consensus at "
                "report time (operator decision: paid estimates provider)")
    gaps.append("company guidance vs consensus: no structured guidance store (earnings-call notes cover it in prose)")
    est.update({"consensus": consensus, "eps_trend": eps_trend, "revisions": revisions,
                "as_of": ext.get("snapshot_date"), "gaps": gaps})
    return est


# ── catalyst calendar ─────────────────────────────────────────────────────────────────────────────────────────
def implied_move(term: dict, when: date, last: Optional[float], *, now: datetime) -> Optional[dict]:
    """The one-standard-deviation move to the first expiry on/after ``when``, from that expiry's ATM IV:
    IV × √(days / 365). It is a standard approximation of what options price in, not a forecast."""
    rows = []
    for t in term.get("term_structure") or []:
        exp, iv = _day(t.get("exp")), _f(t.get("atm_iv_pct"))
        if exp and iv and exp >= when:
            rows.append((exp, iv))
    if not rows:
        return None
    exp, iv = min(rows)
    cap = _day(term.get("captured_at")) or now.date()
    dte = max((exp - cap).days, 1)
    pct = round(iv * (dte / 365) ** 0.5, 2)
    return {"expiry": exp.isoformat(), "atm_iv_pct": iv, "days": dte, "move_pct": pct,
            "move_usd": round(last * pct / 100, 2) if last else None, "captured_at": str(term.get("captured_at") or "")[:16]}


def _fomc_dates(root: Path) -> list[dict]:
    try:
        cfg = json.loads((root / "config/macro_calendar_overrides.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    f = cfg.get("fomc") or {}
    return [{"date": r.get("date"), "label": f.get("name") or "FOMC rate decision", "time": f.get("time_et"),
             "sep": bool(r.get("sep"))} for r in f.get("decision_dates") or [] if r.get("date")]


def next_ex_dividend(div: dict, profile: dict, *, now: datetime) -> Optional[dict]:
    today = now.date()
    for key, basis in (("next_distribution_est", "fund distribution estimate (symbol_profiles)"),):
        d = _day((profile or {}).get(key))
        if d and d >= today:
            return {"date": d.isoformat(), "basis": basis, "estimated": True}
    rec = _day((div or {}).get("recorded_next_ex"))
    if rec and rec >= today:
        return {"date": rec.isoformat(), "basis": "recorded ex-dividend date (ticker_dividend_data)", "estimated": False}
    hist = sorted({_day(h.get("ex_date")) for h in (div or {}).get("history") or [] if _day(h.get("ex_date"))}, reverse=True)
    if len(hist) >= 3:
        gaps = [(a - b).days for a, b in zip(hist, hist[1:])][:6]
        step = statistics.median(gaps)
        if 20 <= step <= 380:
            nxt = hist[0] + timedelta(days=int(step))
            while nxt < today:
                nxt += timedelta(days=int(step))
            amt = next((_f(h.get("amount")) for h in div["history"] if _day(h.get("ex_date")) == hist[0]), None)
            return {"date": nxt.isoformat(), "basis": f"estimated from the ex-date cadence (median {int(step)} days)",
                    "estimated": True, "last_amount": amt, "last_ex": hist[0].isoformat()}
    return None


def catalyst_calendar(raw: dict, ctx: dict, closes: Closes, *, now: datetime, root: Path, fund: bool,
                      eps_hist: list[dict], horizon_days: int = 120) -> dict:
    today = now.date()
    end = today + timedelta(days=horizon_days)
    last = closes.last()
    last_px = last[1] if last else None
    forward, gaps = [], []
    ext = raw.get("extended") or {}
    term = raw.get("term_structure") or {}
    upcoming = []
    for r in ext.get("earnings_dates") or []:
        n = _norm(r)
        d = _day(n.get("index") or n.get("earningsdate"))
        if d and today <= d <= end and _f(n.get("reportedeps")) is None:
            upcoming.append((d, _timing(n.get("index") or n.get("earningsdate")), _f(n.get("epsestimate"))))
    nxt = min(upcoming, key=lambda x: x[0]) if upcoming else None
    ne = _day(ctx.get("next_earnings_date"))
    if not nxt and ne and today <= ne <= end:
        nxt = (ne, None, None)
    if nxt and not fund:
        move = implied_move(term, nxt[0], last_px, now=now)
        forward.append({"date": nxt[0].isoformat(), "kind": "earnings", "label": "Earnings report",
                        "time": {"bmo": "before the open", "amc": "after the close", "dmh": "during market hours"}.get(nxt[1] or "", "time not recorded"),
                        "detail": (f"EPS consensus ${nxt[2]:.2f}" if nxt[2] is not None else ""),
                        "implied_move": move, "source": "Yahoo earnings dates / symbol_profiles"})
        if not move:
            gaps.append("options-implied earnings move: no stored option term structure covers the report date")
    elif not fund:
        gaps.append("next earnings date: not in the house (or beyond the horizon)")
    xd = next_ex_dividend(raw.get("dividends") or {}, ctx.get("profile") or {}, now=now)
    if xd and xd["date"] <= end.isoformat():
        forward.append({"date": xd["date"], "kind": "ex_dividend", "label": "Ex-dividend" + (" (estimated)" if xd.get("estimated") else ""),
                        "time": "", "detail": xd["basis"] + (f"; last ${xd['last_amount']:.4g} on {xd['last_ex']}"
                                                             if xd.get("last_amount") else ""),
                        "implied_move": None, "source": "ticker_dividends / ticker_dividend_data"})
    for f in _fomc_dates(root):
        d = _day(f["date"])
        if d and today <= d <= end:
            forward.append({"date": d.isoformat(), "kind": "macro", "label": f["label"] + (" + projections" if f["sep"] else ""),
                            "time": f"{f['time']} ET" if f.get("time") else "", "detail": "", "implied_move": None,
                            "source": "config/macro_calendar_overrides.json (Federal Reserve calendar)"})
    for e in ctx.get("macro_events") or []:
        d = _day(e.get("date") or e.get("at"))
        if d and today <= d <= end and not any(x["date"] == d.isoformat() and x["kind"] == "macro" for x in forward):
            forward.append({"date": d.isoformat(), "kind": "macro", "label": str(e.get("name") or e.get("event") or "macro release"),
                            "time": str(e.get("time_et") or ""), "detail": "", "implied_move": None,
                            "source": "macro_calendar.json"})
    if not ctx.get("macro_events"):
        gaps.append("CPI / payrolls / PCE release dates: the macro calendar file is not produced (FOMC dates shown "
                    "from the Federal Reserve calendar config)")
    gaps.append("investor days, product / regulatory / FDA / legal dates, lock-ups and index rebalances: no structured "
                "house calendar (catalyst news covers what has been reported)")
    forward.sort(key=lambda x: x["date"])
    backward = []
    for h in eps_hist[:4]:
        backward.append({"date": h["date"], "kind": "earnings",
                         "label": f"Earnings: EPS ${h['actual']:.2f} vs ${h['estimate']:.2f}" if h.get("estimate") is not None
                         else f"Earnings: EPS ${h['actual']:.2f}", "one_day_pct": h.get("one_day_pct"),
                         "five_day_pct": h.get("five_day_pct"), "source": "Yahoo earnings dates + house closes"})
    from . import news_gate  # noqa: PLC0415
    mats, _ = news_gate.filter_facts(list(raw.get("material_catalysts") or []), ctx.get("symbol") or "",
                                     ctx.get("name") or "", text_key="headline")
    seen_days = {b["date"] for b in backward}
    for c in mats:
        d = _day(c.get("at"))
        if not d or d.isoformat() in seen_days or len(backward) >= 10:
            continue
        seen_days.add(d.isoformat())
        r = reaction(closes, d, None)
        backward.append({"date": d.isoformat(), "kind": str(c.get("type") or "event"),
                         "label": str(c.get("headline") or "")[:160], "one_day_pct": r["one_day_pct"],
                         "five_day_pct": r["five_day_pct"], "source": f"catalyst_events / {c.get('source') or 'feed'}",
                         "url": c.get("url")})
    backward.sort(key=lambda x: x["date"], reverse=True)
    return {"schema": SCHEMA, "forward": forward, "backward": backward, "horizon_days": horizon_days, "gaps": gaps,
            "method": "Reaction: last close before the market could react to the next session (1-day) and the 5th "
                      "session (5-day). Implied move: ATM IV of the first expiry on/after the date × √(days/365)."}


# ── positioning ───────────────────────────────────────────────────────────────────────────────────────────────
def _rank(series: list[float], cur: float) -> tuple[Optional[float], Optional[float]]:
    """(IV rank 0-100 = position between min and max, IV percentile 0-100 = share of days below)."""
    if not series:
        return None, None
    lo, hi = min(series), max(series)
    rank = None if hi == lo else round((cur - lo) / (hi - lo) * 100, 1)
    pct = round(sum(1 for v in series if v < cur) / len(series) * 100, 1)
    return rank, pct


def positioning(raw: dict, own: dict, *, now: datetime, fund: bool, min_sessions: int = 60) -> dict:
    gaps: list[str] = []
    snaps = [s for s in raw.get("option_snapshots") or [] if _f(s.get("atm_iv")) is not None]
    opt = None
    if snaps:
        cur = snaps[-1]
        ivs = [_f(s["atm_iv"]) for s in snaps[-252:]]
        rank, pctl = _rank(ivs, _f(cur["atm_iv"])) if len(ivs) >= min_sessions else (None, None)
        back = next((s for s in reversed(snaps) if (_day(cur["date"]) - _day(s["date"])).days >= 28), None)
        term = raw.get("term_structure") or {}
        opt = {"as_of": cur["date"], "atm_iv_pct": _f(cur["atm_iv"]), "put_call_oi": _f(cur.get("pc_oi_ratio")),
               "put_call_volume": _f(cur.get("pc_vol_ratio")), "skew25": _f(cur.get("skew25")),
               "put_oi": _f(cur.get("put_oi")), "call_oi": _f(cur.get("call_oi")),
               "iv_rank": rank, "iv_percentile": pctl, "iv_sessions": len(ivs), "iv_since": snaps[-len(ivs)]["date"],
               "put_call_oi_30d_ago": _f((back or {}).get("pc_oi_ratio")), "atm_iv_30d_ago": _f((back or {}).get("atm_iv")),
               "front_iv_pct": _f(term.get("front_iv_pct")), "back_iv_pct": _f(term.get("back_iv_pct")),
               "term_slope_pct": _f(term.get("term_slope_pct"))}
        if rank is None:
            gaps.append(f"IV rank: only {len(ivs)} stored sessions since {snaps[0]['date']} (needs {min_sessions})")
        age = _age(cur["date"], now)
        if age is not None and age > STALE_DAYS["options"]:
            opt["stale"] = f"{age} days old"
            gaps.append(f"options positioning: newest chain summary is {age} days old")
    else:
        gaps.append("options put/call, skew and IV history: no stored chain summary for this symbol")
    gaps.append("unusual options activity: the options-flow provider was retired 2026-09-13 (operator decision: paid "
                "flow feed)")
    insider = None
    if not fund:
        f4 = raw.get("form4") or {}
        cut = (now.date() - timedelta(days=90)).isoformat()
        rows = [r for r in f4.get("rows") or [] if str(r.get("filing_date") or "")[:10] >= cut]
        def kind(r: dict) -> str:
            t = str(r.get("transaction_type") or "").upper()
            return "buy" if t.startswith("P") or "BUY" in t or "PURCHASE" in t else "sell" if t.startswith("S") or "SALE" in t or "SELL" in t else "other"
        buys = [r for r in rows if kind(r) == "buy"]
        sells = [r for r in rows if kind(r) == "sell"]
        bv = sum(_f(r.get("total_value")) or 0 for r in buys)
        sv = sum(_f(r.get("total_value")) or 0 for r in sells)
        covered = f4.get("symbol_rows_ever", 0) > 0
        insider = {"covered": covered, "buys_90d": len(buys), "sells_90d": len(sells), "buy_value_90d": round(bv, 2),
                   "sell_value_90d": round(sv, 2), "net_value_90d": round(bv - sv, 2),
                   "rows": [{"date": str(r.get("filing_date"))[:10], "filer": r.get("filer_name"),
                             "relation": r.get("filer_relation"), "type": kind(r), "shares": _f(r.get("shares")),
                             "value": _f(r.get("total_value")), "url": r.get("sec_url")} for r in (buys + sells)[:8]],
                   "store_symbols": f4.get("store_symbols"), "store_last": f4.get("store_last")}
        if not covered:
            gaps.append(f"insider Form 4: the house store does not cover this symbol yet ({f4.get('store_symbols') or 0} "
                        f"symbols ingested; SEC EDGAR is free, the ingest backfill is a follow-up)")
            insider.update({"buys_90d": None, "sells_90d": None, "buy_value_90d": None, "sell_value_90d": None,
                            "net_value_90d": None})
    holders = raw.get("holders_13f") or []
    inst = None
    if holders:
        inst = [{"institution": h.get("institution"), "shares": _f(h.get("shares")), "change_pct": _f(h.get("change_pct")),
                 "report_date": str(h.get("report_date") or "")[:10], "url": h.get("sec_url")} for h in holders[:10]]
    elif not fund:
        gaps.append("13F holders and quarter-over-quarter changes: the house 13F store is empty (SEC EDGAR is free; "
                    "the ingest is a follow-up)")
    gaps.append("short-interest trend: the house keeps the current Finviz reading only (no history)")
    if fund:
        gaps.append("ETF creations / redemptions (flows): no house source (operator decision: paid flows feed)")
    return {"schema": SCHEMA, "short": {"short_float_pct": own.get("short_float_pct"), "days_to_cover": own.get("days_to_cover"),
                                        "source": "Finviz enrichment cache"},
            "institutional": {"own_pct": own.get("institutional_pct"), "change_pct": own.get("institutional_change_pct"),
                              "holders": inst},
            "insider": insider, "options": opt, "gaps": gaps}


# ── valuation history ─────────────────────────────────────────────────────────────────────────────────────────
def valuation_history(ext: dict, bars_long: Any, *, now: datetime, forward_pe: Optional[float],
                      max_years: int = 5, xbrl_rows: list[dict] | None = None) -> dict:
    """Trailing P/E at each month-end = close / sum of the four most recent REPORTED EPS (Yahoo earnings dates) known
    on that date; the current reading against its own range. Negative / missing TTM EPS months are skipped."""
    gaps = ["EV/EBITDA, P/S and FCF-yield history: the house has no share count, EBITDA or capex series "
            "(SEC XBRL ingest of those tags is a free follow-up)"]
    reported = []
    for r in ext.get("earnings_dates") or []:
        n = _norm(r)
        d, a = _day(n.get("index") or n.get("earningsdate")), _f(n.get("reportedeps"))
        if d and a is not None and d <= now.date():
            reported.append((d, a))
    for r in ext.get("earnings_history") or []:  # quarter-end rows fill older quarters when dates are thin
        n = _norm(r)
        d, a = _day(n.get("index") or n.get("quarter")), _f(n.get("epsactual"))
        if d and a is not None and not any(abs((d - x).days) < 60 for x, _ in reported):
            reported.append((d + timedelta(days=30), a))  # quarter end → approx. report date; marks basis below
    basis = "Yahoo earnings dates"
    if len(reported) < 4 and xbrl_rows:  # SEC diluted EPS per quarter, known from its filing date
        eps = xbrl_quarters(xbrl_rows).get("eps_diluted") or {}
        reported = [(_day(row.get("filed")) or _day(end) + timedelta(days=40), row["value"]) for end, row in eps.items()]
        basis = "SEC XBRL diluted EPS (filing dates; Q4 derived from the 10-K)"
    reported.sort()
    closes = _series(bars_long or [])
    if len(reported) < 4 or not closes:
        gaps.insert(0, "trailing P/E history: fewer than four reported quarters or no long price history in the house")
        return {"schema": SCHEMA, "pe": None, "forward_pe": forward_pe, "gaps": gaps}
    start = (now.date() - timedelta(days=365 * max_years)).isoformat()
    month_ends: dict[str, tuple[str, float]] = {}
    for d, c in closes:
        if d >= start:
            month_ends[d[:7]] = (d, c)
    pts = []
    for ym in sorted(month_ends):
        d, c = month_ends[ym]
        known = [a for rd, a in reported if rd.isoformat() <= d]
        if len(known) < 4:
            continue
        ttm = sum(known[-4:])
        if ttm > 0:
            pts.append([d, round(c / ttm, 2)])
    if len(pts) < 12:
        gaps.insert(0, f"trailing P/E history: only {len(pts)} months computable (needs 12)")
        return {"schema": SCHEMA, "pe": None, "forward_pe": forward_pe, "gaps": gaps}
    vals = [v for _, v in pts]
    cur = vals[-1]
    ttm_now = sum(a for _, a in reported[-4:])
    return {"schema": SCHEMA, "forward_pe": forward_pe, "gaps": gaps,
            "pe": {"current": cur, "min": min(vals), "max": max(vals), "median": round(statistics.median(vals), 2),
                   "percentile": round(sum(1 for v in vals if v < cur) / len(vals) * 100, 1),
                   "vs_median_pct": _pct(cur, statistics.median(vals)), "months": len(pts), "since": pts[0][0],
                   "ttm_eps": round(ttm_now, 4), "series": pts,
                   "basis": f"month-end house close ÷ sum of the last four reported quarterly EPS ({basis})"}}


# ── fundamentals (SEC XBRL) ───────────────────────────────────────────────────────────────────────────────────
XBRL_FLOW = ("revenue", "operating_income", "net_income", "operating_cash_flow", "eps_diluted")
XBRL_INSTANT = ("cash", "long_term_debt", "remaining_performance_obligation")


def xbrl_quarters(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """{metric: {quarter_end: {value, derived, filed, form, url}}} for duration metrics.

    A 10-Q states a quarter directly (80-100 days) for most lines, but cash-flow lines are year-to-date and the fourth
    quarter only exists inside the 10-K's year. A quarter is therefore the direct value when stored, else the
    difference of two durations with the SAME start whose ends are one quarter apart (YTD − prior YTD; FY − 9M)."""
    spans: dict[str, dict[tuple[date, date], dict]] = {}
    for r in rows or []:
        m, v, st, en = r.get("metric"), _f(r.get("value")), _day(r.get("start")), _day(r.get("end"))
        if m not in XBRL_FLOW or v is None or not st or not en:
            continue
        spans.setdefault(m, {}).setdefault((st, en), {"value": v, "filed": r.get("filed"), "form": r.get("form"),
                                                       "url": r.get("url")})
    out: dict[str, dict[str, dict]] = {}
    for m, by in spans.items():
        q: dict[str, dict] = {}
        for (st, en), row in by.items():
            if 80 <= (en - st).days <= 100:
                q[en.isoformat()] = {**row, "derived": False}
        for (st, en), row in by.items():
            if en.isoformat() in q or (en - st).days < 150:
                continue
            prev = [(e2, r2) for (s2, e2), r2 in by.items() if s2 == st and 75 <= (en - e2).days <= 105]
            if prev:
                e2, r2 = prev[0]
                q[en.isoformat()] = {**row, "value": row["value"] - r2["value"], "derived": True}
        for (st, en), row in by.items():  # Q4 = the fiscal year minus the three stated quarters inside it
            if en.isoformat() in q or not 350 <= (en - st).days <= 380:
                continue
            inside = [v for k, v in q.items() if st < _day(k) < en and not v["derived"]]
            if len(inside) == 3:
                q[en.isoformat()] = {**row, "value": row["value"] - sum(v["value"] for v in inside), "derived": True}
        out[m] = q
    return out


def fundamentals_xbrl(rows: list[dict], *, now: datetime, quarters: int = 6) -> dict:
    """Quarterly flows (direct or derived, see ``xbrl_quarters``) and period-end balances from SEC XBRL, newest
    first, with operating margin, YoY revenue growth and net debt (long-term debt − cash)."""
    gaps = ["segment revenue and margins: the house XBRL ingest keeps consolidated tags only",
            "free cash flow, buybacks and dividends paid: capex / repurchase / dividend tags are not ingested yet",
            "10-K / 10-Q risk-factor changes: risk-factor text is not ingested (SEC EDGAR is free; follow-up)"]
    flows = xbrl_quarters(rows)
    q: dict[str, dict] = {}
    for m, by in flows.items():
        for end, row in by.items():
            r = q.setdefault(end, {"period_end": end, "derived": []})
            r[m] = row["value"]
            if row["derived"]:
                r["derived"].append(m)
            for k in ("filed", "form", "url"):
                if not row["derived"] or k not in r:
                    r.setdefault(k, row.get(k))
    for r in rows or []:
        m, v, en = r.get("metric"), _f(r.get("value")), _day(r.get("end"))
        if m in XBRL_INSTANT and v is not None and en and not r.get("start"):
            q.setdefault(en.isoformat(), {"period_end": en.isoformat(), "derived": []}).setdefault(m, v)
    out = []
    for key in sorted(q, reverse=True):
        row = dict(q[key])
        if row.get("revenue") and row.get("operating_income") is not None:
            row["operating_margin_pct"] = round(row["operating_income"] / row["revenue"] * 100, 1)
        if row.get("cash") is not None and row.get("long_term_debt") is not None:
            row["net_debt"] = row["long_term_debt"] - row["cash"]
        d = _day(key)
        prior = next((q[k] for k in q if _day(k) and 350 <= (d - _day(k)).days <= 380 and q[k].get("revenue")), None)
        if prior and row.get("revenue"):
            row["revenue_yoy_pct"] = _pct(row["revenue"], prior["revenue"])
        out.append(row)
    out = out[:quarters]
    if not out:
        gaps.insert(0, "SEC XBRL statements: none stored for this symbol")
    latest = out[0] if out else {}
    return {"schema": SCHEMA, "quarters": out, "as_of": latest.get("filed"), "net_debt": latest.get("net_debt"),
            "method": "Quarter = the 10-Q quarter when stated, else year-to-date minus the prior year-to-date (Q4 = "
                      "10-K year minus nine months); derived lines are listed per quarter.", "gaps": gaps}


# ── facts for the writer ──────────────────────────────────────────────────────────────────────────────────────
def add_facts(b: Any, blocks: dict) -> None:
    """A compact, cited fact set from the blocks (the writer never computes these itself)."""
    ac = blocks.get("analyst_coverage") or {}
    src_t = "yahoo_analyst_targets_history (data_broker.street_detail)"
    dist = ac.get("distribution") or {}
    cur = dist.get("current") or {}
    if cur.get("total"):
        b.add("analyst", "Rating distribution now (strong buy / buy / hold / sell / strong sell)",
              text=" / ".join(str(int(cur.get(k) or 0)) for k, _ in RATING_KEYS) + f" of {cur['total']}",
              source=dist.get("source") or src_t, as_of=dist.get("as_of"))
        b.add("analyst", "Analysts rating buy or strong buy %", value=cur.get("bullish_pct"), unit="%",
              source=dist.get("source") or src_t, as_of=dist.get("as_of"))
        if dist.get("bullish_change_pts") is not None:
            b.add("analyst", "Change in buy-rated share over ~3 months (points)", value=dist["bullish_change_pts"],
                  source=dist.get("source") or src_t, as_of=dist.get("as_of"))
    tg = ac.get("targets") or {}
    for days in (30, 90):
        t = (tg.get("trend") or {}).get(f"d{days}") or {}
        if t.get("mean_change_pct") is not None:
            b.add("analyst", f"Mean price target change over {days} days %", value=t["mean_change_pct"], unit="%",
                  source=src_t, as_of=tg.get("as_of"))
            b.add("analyst", f"Mean price target {days} days ago", value=t.get("mean"), unit="$", source=src_t,
                  as_of=t.get("date"))
    if tg.get("dispersion_pct") is not None:
        b.add("analyst", "Target dispersion (high − low) / mean %", value=tg["dispersion_pct"], unit="%", source=src_t,
              as_of=tg.get("as_of"))
    tally = ac.get("actions_90d") or {}
    if ac.get("actions"):
        b.add("analyst", "Analyst actions, last 90 days", text=", ".join(f"{v} {k.replace('_', ' ')}" for k, v in tally.items()),
              source="analyst action log (Yahoo upgrades/downgrades + catalyst_events)", as_of=(ac["actions"][0] or {}).get("date"))
    for a in (ac.get("actions") or [])[:8]:
        grade = " → ".join(x for x in (a.get("from_grade"), a.get("to_grade")) if x)
        tgt = (f"target ${a['prior_target']:,.0f} → ${a['target']:,.0f}" if a.get("prior_target") and a.get("target")
               else f"target ${a['target']:,.0f}" if a.get("target") else "")
        b.add("analyst", f"Analyst action: {a.get('firm') or 'firm not named'} — {a.get('action_label')}",
              text="; ".join(x for x in (grade, tgt) if x) or (a.get("headline") or a.get("action_label")),
              source=f"analyst action log ({a.get('source')})", as_of=a.get("date"), url=a.get("url"))
    est = blocks.get("estimates") or {}
    for c in est.get("consensus") or []:
        if c["period"] in ("0y", "+1y", "0q"):
            b.add("estimates", f"EPS consensus, {c['label']}", value=c.get("eps_avg"), unit="$",
                  source="Yahoo earnings estimate (pro_analyst_fetch extended)", as_of=est.get("as_of"))
            b.add("estimates", f"Number of EPS estimates, {c['label']}", value=c.get("eps_n"),
                  source="Yahoo earnings estimate (pro_analyst_fetch extended)", as_of=est.get("as_of"))
            if c.get("rev_avg"):
                b.add("estimates", f"Revenue consensus, {c['label']} ($B)", value=c["rev_avg"] / 1e9, unit="$B",
                      source="Yahoo revenue estimate (pro_analyst_fetch extended)", as_of=est.get("as_of"))
    for t in est.get("eps_trend") or []:
        if t["period"] in ("0y", "+1y"):
            for k in ("chg_d30_pct", "chg_d90_pct"):
                if t.get(k) is not None:
                    b.add("estimates", f"EPS estimate revision, {t['label']}, {k[5:7]} days %", value=t[k], unit="%",
                          source="Yahoo EPS trend (pro_analyst_fetch extended)", as_of=est.get("as_of"))
    rev = est.get("revisions_90d") or {}
    if rev.get("window"):
        b.add("estimates", f"Estimate revisions up / down ({rev['window']})", text=f"{rev.get('up'):g} up / {rev.get('down'):g} down",
              source="Yahoo EPS revisions (pro_analyst_fetch extended)", as_of=est.get("as_of"))
    br = est.get("beat_rate") or {}
    if br.get("quarters"):
        b.add("estimates", f"EPS beats in the last {br['quarters']} quarters", value=br.get("beats"),
              source="Yahoo earnings dates", as_of=(est.get("eps_surprises") or [{}])[0].get("date"))
        b.add("estimates", f"Average EPS surprise, last {br['quarters']} quarters %", value=br.get("avg_surprise_pct"),
              unit="%", source="Yahoo earnings dates", as_of=(est.get("eps_surprises") or [{}])[0].get("date"))
        b.add("estimates", "Average absolute 1-day move after earnings %", value=br.get("avg_abs_one_day_pct"), unit="%",
              source="Yahoo earnings dates + house closes", as_of=(est.get("eps_surprises") or [{}])[0].get("date"))
    for h in (est.get("eps_surprises") or [])[:4]:
        if h.get("one_day_pct") is not None:
            b.add("estimates", f"1-day price reaction to the {h['date']} report %", value=h["one_day_pct"], unit="%",
                  source="house closes (ticker_prices)", as_of=h["date"])
    cal = blocks.get("catalyst_calendar") or {}
    for e in (cal.get("forward") or [])[:6]:
        mv = e.get("implied_move") or {}
        b.add("catalyst", f"Upcoming: {e['label']}", text=f"{e['date']} {e.get('time') or ''}".strip(),
              source=e.get("source") or "catalyst calendar", as_of=e["date"])
        if mv.get("move_pct") is not None:
            b.add("catalyst", f"Options-implied move to {mv['expiry']} (±%)", value=mv["move_pct"], unit="%",
                  source="options_chain_snapshots ATM IV (term structure)", as_of=mv.get("captured_at"))
    pos = blocks.get("positioning") or {}
    opt = pos.get("options") or {}
    for key, label, unit in (("put_call_oi", "Put/call ratio (open interest)", ""), ("put_call_volume", "Put/call ratio (volume)", ""),
                             ("skew25", "25-delta skew (put IV − call IV, points)", ""), ("iv_rank", "IV rank (0-100)", ""),
                             ("iv_percentile", "IV percentile (0-100)", ""), ("term_slope_pct", "IV term slope, front − back (points)", "")):
        if opt.get(key) is not None:
            b.add("positioning", label, value=opt[key], unit=unit, source="option_chain_snapshots / options_chain_snapshots",
                  as_of=opt.get("as_of"))
    ins = pos.get("insider") or {}
    if ins.get("covered") and ins.get("net_value_90d") is not None:
        b.add("positioning", "Insider net buying, 90 days (Form 4, $)", value=ins["net_value_90d"], unit="$",
              source="sec_form4 (SEC EDGAR)", as_of=ins.get("store_last"))
        b.add("positioning", "Insider purchases / sales, 90 days (count)", text=f"{ins['buys_90d']} / {ins['sells_90d']}",
              source="sec_form4 (SEC EDGAR)", as_of=ins.get("store_last"))
    vh = (blocks.get("valuation_history") or {}).get("pe") or {}
    if vh:
        for key, label in (("current", "Trailing P/E (reported EPS)"), ("median", f"Trailing P/E median since {vh.get('since')}"),
                           ("min", "Trailing P/E low of the range"), ("max", "Trailing P/E high of the range"),
                           ("percentile", "Trailing P/E percentile in its own range (0-100)")):
            b.add("valuation", label, value=vh.get(key), source="derived: house closes ÷ reported EPS (Yahoo)",
                  as_of=(vh.get("series") or [[None]])[-1][0])
    fx = blocks.get("fundamentals_xbrl") or {}
    for row in (fx.get("quarters") or [])[:2]:  # the raw XBRL lines are already facts (domains.r_fundamentals)
        pe = row["period_end"]
        for key, label, div, unit in (("operating_margin_pct", "Operating margin %", 1, "%"),
                                      ("revenue_yoy_pct", "Revenue growth YoY %", 1, "%"), ("net_debt", "Net debt ($B)", 1e9, "$B")):
            if row.get(key) is not None:
                b.add("fundamental", f"SEC XBRL quarter ending {pe}: {label}", value=row[key] / div, unit=unit,
                      source=f"sec_xbrl ({row.get('form') or 'filing'})", as_of=row.get("filed"), url=row.get("url"))


# ── entry point ───────────────────────────────────────────────────────────────────────────────────────────────
def read_raw(sources: Any, sym: str) -> dict:
    """The broker projection for one symbol (test sources may provide ``street(sym)`` directly)."""
    if hasattr(sources, "street"):
        return sources.street(sym) or {}
    import importlib  # noqa: PLC0415 - house pattern: the lane's static import closure stays its own read path
    try:
        mod = importlib.import_module("lib.data_broker.street_detail")
    except ImportError:
        mod = importlib.import_module("scripts.lib.data_broker.street_detail")
    return mod.get_street_detail(sources.db(), sym)


def attach(sources: Any, b: Any, *, now: datetime | None = None, fund: bool = False, root: Path | None = None) -> None:
    """Build every Street block for a bundle, add its facts, and replace the gaps it closes. Never raises."""
    now = now or datetime.now(timezone.utc)
    try:
        raw = read_raw(sources, b.symbol)
    except Exception as exc:  # noqa: BLE001
        b.gaps.append(f"Street blocks not built: {type(exc).__name__}")
        b.cover("street_detail", "failed", detail=type(exc).__name__)
        return
    errs = raw.get("errors") or {}
    b.cover("street_detail", "used" if any(raw.get(k) for k in ("target_history", "extended", "option_snapshots", "xbrl"))
            else "empty", as_of=raw.get("as_of"), detail="data_broker.street_detail" + (f"; errors: {', '.join(errs)}" if errs else ""))
    try:
        bars_long = sources.bars(b.symbol, 1900)
    except TypeError:
        bars_long = sources.bars(b.symbol)
    except Exception:  # noqa: BLE001
        bars_long = []
    closes = Closes(bars_long)
    last = closes.last()
    ext = raw.get("extended") or {}
    macro = (b.blocks.get("macro_sensitivity") or {}).get("next_events") or []
    ctx = {"symbol": b.symbol, "name": b.name, "next_earnings_date": b.context.get("next_earnings_date"),
           "profile": b.blocks.get("fund_profile") or {}, "macro_events": macro}
    steps: list[tuple[str, Callable[[], Any]]] = [] if fund else [
        ("analyst_coverage", lambda: analyst_coverage(raw, sym=b.symbol, name=b.name, now=now, last_close=last[1] if last else None)),
        ("estimates", lambda: estimates_block(b.blocks.get("estimates") or {}, ext, closes, now=now)),
    ]
    for key, fn in steps:
        try:
            b.blocks[key] = fn()
        except Exception as exc:  # noqa: BLE001
            b.gaps.append(f"{key}: not built ({type(exc).__name__}: {str(exc)[:80]})")
    eps_hist = (b.blocks.get("estimates") or {}).get("eps_surprises") or []
    fwd_pe = next((f.get("value") for f in b.facts if f.get("label") == "Forward P/E" and "value" in f), None)
    later: list[tuple[str, Callable[[], Any]]] = [
        ("catalyst_calendar", lambda: catalyst_calendar(raw, ctx, closes, now=now, root=root or ROOT, fund=fund,
                                                        eps_hist=[h for h in eps_hist if not h.get("quarter_end")])),
        ("positioning", lambda: positioning(raw, b.blocks.get("ownership_flows") or {}, now=now, fund=fund)),
        ("valuation_history", lambda: valuation_history(ext, bars_long, now=now, forward_pe=fwd_pe,
                                                        xbrl_rows=raw.get("xbrl") or [])),
        ("fundamentals_xbrl", lambda: fundamentals_xbrl(raw.get("xbrl") or [], now=now)),
    ]
    for key, fn in later:
        try:
            b.blocks[key] = fn()
        except Exception as exc:  # noqa: BLE001
            b.gaps.append(f"{key}: not built ({type(exc).__name__}: {str(exc)[:80]})")
    own = b.blocks.get("ownership_flows")
    ins = (b.blocks.get("positioning") or {}).get("insider") or {}
    if isinstance(own, dict) and ins.get("covered"):
        own["insider_buys_90d"], own["insider_sells_90d"] = ins.get("buys_90d"), ins.get("sells_90d")
    if fund:
        for k in FUND_HIDDEN:
            b.blocks.pop(k, None)
    try:
        add_facts(b, b.blocks)
    except Exception as exc:  # noqa: BLE001
        b.gaps.append(f"Street facts not added: {type(exc).__name__}")
    # The estimates block now states its own gaps precisely (n of 8 quarters, consensus / revisions captured or not):
    # the older blanket lines are replaced by those, so the writer sees one accurate statement each.
    est_gaps = [] if fund else [g for g in (b.blocks.get("estimates") or {}).get("gaps") or []
                                if g.startswith(("EPS beat", "EPS surprise", "estimate revisions", "EPS / revenue consensus"))]
    b.gaps[:] = [g for g in b.gaps if not g.startswith(("EPS surprise history", "90-day estimate revisions"))]
    b.gaps += [g for g in est_gaps if g not in b.gaps]
