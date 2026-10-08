"""Watch decision standards — category, priority, five scores, TTL + expiry, status, actionability per Watch item.

Operator 2026-10-07: the Command Center standards Communications follows (config/comms_categories.yaml) apply to
the Watchlist: every item carries a category, priority, confidence, TTL with an expiration timestamp, status and
an actionability indicator, sortable by priority / confidence / risk / reward / time sensitivity, with an
at-a-glance board. Rules and thresholds live in config/watch_decision_standards.yaml.

Read-only, zero provider calls. Inputs are batched once per request:
  watchlist_entry_plans (latest per symbol), watchlist_strategy_cards, watchlist_final_synthesis,
  symbol_profiles.next_earnings_date, and the deterministic re-entry desk (lib/data_broker/reentry_decision_desk).
What expires is the signal, never the membership — an expired item leaves the active views until new evidence
reaffirms it.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "watch_decision_standards.yaml"
DECISION_VERSION = "watch_decision.v1"
PRIORITY_TIER = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
PRIORITY_ORDER = ("critical", "high", "medium", "low")
STATUSES = ("active", "expired", "invalidated", "needs_data")
SORTS = ("priority_score", "confidence", "risk_score", "reward_score", "time_sensitivity", "expires_at")

_cfg_cache: dict[str, Any] = {"mtime": None, "cfg": None}
_desk_cache: dict[str, Any] = {"at": 0.0, "rows": {}}
DESK_CACHE_S = 120


def load_config() -> dict[str, Any]:
    import yaml

    m = CONFIG_PATH.stat().st_mtime
    if _cfg_cache["mtime"] != m:
        _cfg_cache["cfg"] = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        _cfg_cache["mtime"] = m
    return _cfg_cache["cfg"]


def categories() -> list[dict[str, Any]]:
    cats = load_config().get("categories") or {}
    return [{"id": k, "label": v.get("label") or k, "ttl_hours": float(v.get("ttl_hours") or 168)} for k, v in cats.items()]


# ── inputs ──────────────────────────────────────────────────────────────────


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _rows(sql: str, params: Any) -> list[dict]:
    try:
        from db_adapter import _execute

        return list(_execute(sql, params, fetch="all") or [])
    except Exception:
        return []


def load_inputs(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """One batched read per source for the request's symbols → {SYMBOL: {plan, strategy, synthesis, earnings}}."""
    syms = sorted({(s or "").upper() for s in symbols if s})
    out: dict[str, dict[str, Any]] = {s: {} for s in syms}
    if not syms:
        return out
    for r in _rows(
        """SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, entry_zone_low, entry_zone_high, limit_price,
                  stop_price, target_price, risk_reward, urgency, confidence, created_at
             FROM watchlist_entry_plans WHERE upper(symbol) = ANY(%s)
            ORDER BY upper(symbol), created_at DESC, id DESC""",
        (syms,),
    ):
        out.setdefault(r["s"], {})["plan"] = r
    for r in _rows(
        """SELECT upper(symbol) AS s, stop_loss, target_price, risk_reward, confidence, updated_at
             FROM watchlist_strategy_cards WHERE upper(symbol) = ANY(%s)""",
        (syms,),
    ):
        out.setdefault(r["s"], {})["strategy"] = r
    for r in _rows(
        """SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, recommendation, confidence, actionable, updated_at
             FROM watchlist_final_synthesis
            WHERE upper(symbol) = ANY(%s) AND NOT COALESCE(superseded, FALSE)
            ORDER BY upper(symbol), updated_at DESC NULLS LAST""",
        (syms,),
    ):
        out.setdefault(r["s"], {})["synthesis"] = r
    for r in _rows(
        "SELECT upper(symbol) AS s, next_earnings_date FROM symbol_profiles WHERE upper(symbol) = ANY(%s)", (syms,)
    ):
        out.setdefault(r["s"], {})["earnings"] = r.get("next_earnings_date")
    desk = reentry_rows()
    for s in syms:
        if s in desk:
            out.setdefault(s, {})["reentry"] = desk[s]
    return out


def reentry_rows() -> dict[str, dict[str, Any]]:
    """Deterministic re-entry desk rows by symbol, cached briefly (the desk recomputes from broker stores)."""
    now = time.monotonic()
    if now - _desk_cache["at"] < DESK_CACHE_S and _desk_cache["rows"]:
        return _desk_cache["rows"]
    rows: dict[str, dict[str, Any]] = {}
    try:
        from db_adapter import _execute
        from lib.data_broker.reentry_decision_desk import build_decision_desk

        desk = build_decision_desk(lambda sql, params=None, fetch="all": _execute(sql, params, fetch=fetch))
        for r in desk.get("rows") or []:
            intel = r.get("intel") or {}
            rows[str(r.get("symbol") or "").upper()] = {
                "state": intel.get("state"),
                "action": intel.get("action"),
                "reason": intel.get("reason"),
                "distance_pct": intel.get("distance_pct"),
                "price_as_of": r.get("price_as_of"),
                "plan_as_of": r.get("plan_as_of"),
            }
    except Exception:
        rows = {}
    _desk_cache.update(at=now, rows=rows)
    return rows


# ── facts → rule → scores ───────────────────────────────────────────────────


def facts(card: dict[str, Any], inp: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    cfg = load_config()
    sc = cfg.get("scores") or {}
    last = _f(card.get("last"))
    plan = inp.get("plan") or {}
    plan_at = _ts(plan.get("created_at"))
    plan_fresh = bool(plan_at and (now - plan_at) <= timedelta(hours=float(sc.get("plan_fresh_hours") or 168)))
    syn = inp.get("synthesis") or {}
    syn_at = _ts(syn.get("updated_at"))
    syn_fresh = bool(syn_at and (now - syn_at) <= timedelta(hours=float(sc.get("synthesis_fresh_hours") or 336)))
    strat = inp.get("strategy") or {}
    lo, hi = _f(plan.get("entry_zone_low")), _f(plan.get("entry_zone_high"))
    in_zone = bool(plan_fresh and last and lo and hi and min(lo, hi) <= last <= max(lo, hi))
    nt = card.get("near_trigger") or {}
    earn = _ts(inp.get("earnings"))
    earnings_days = (earn.date() - now.date()).days if earn else None
    re = inp.get("reentry") or {}
    return {
        "held": bool(card.get("held")),
        "last": last,
        "trade_state": str(card.get("trade_ai_state") or "").upper(),
        "proposal_allowed": bool(card.get("proposal_allowed")),
        "near_trigger": bool(card.get("is_near_trigger") or nt.get("is_near")),
        "near_pct": _f(nt.get("distance_pct")),
        "plan_fresh": plan_fresh,
        "plan_at": plan_at,
        "plan_urgency": str(plan.get("urgency") or "").lower() if plan_fresh else "",
        "plan_confidence": _f(plan.get("confidence")) if plan_fresh else None,
        "plan_rr": _f(plan.get("risk_reward")) if plan_fresh else None,
        "plan_stop": _f(plan.get("stop_price")) if plan_fresh else None,
        "in_zone": in_zone,
        "strategy_confidence": _f(strat.get("confidence")),
        "strategy_rr": _f(strat.get("risk_reward")),
        "strategy_stop": _f(strat.get("stop_loss")),
        "synthesis": str(syn.get("recommendation") or "").upper() if syn_fresh else "",
        "synthesis_confidence": _f(syn.get("confidence")) if syn_fresh else None,
        "synthesis_at": syn_at if syn_fresh else None,
        "review_at": _ts(card.get("review_completed_at")),
        "earnings_days": earnings_days,
        "upside_pct": _f(card.get("implied_upside_pct")),
        "primary_risk": bool(card.get("primary_risk")),
        "reentry_state": str(re.get("state") or "").upper(),
        "reentry_at": _ts(re.get("price_as_of")) or _ts(re.get("plan_as_of")),
        "reentry_action": re.get("action"),
        "reentry_distance_pct": _f(re.get("distance_pct")),
    }


def _holds(when: dict[str, Any], fx: dict[str, Any]) -> bool:
    for k, v in (when or {}).items():
        if k in ("held", "near_trigger", "in_zone", "proposal_allowed"):
            if bool(fx.get(k)) is not bool(v):
                return False
        elif k == "reentry_state_in":
            if fx["reentry_state"] not in {str(x).upper() for x in v}:
                return False
        elif k == "trade_state_in":
            if fx["trade_state"] not in {str(x).upper() for x in v}:
                return False
        elif k == "plan_urgency_in":
            if fx["plan_urgency"] not in {str(x).lower() for x in v}:
                return False
        elif k == "synthesis_in":
            if fx["synthesis"] not in {str(x).upper() for x in v}:
                return False
        elif k == "min_plan_confidence":
            if (fx["plan_confidence"] or 0) < float(v):
                return False
        elif k == "min_rr":
            if (fx["plan_rr"] or 0) < float(v):
                return False
        else:
            return False  # unknown condition never matches silently
    return True


def _clip(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 3)


def score(fx: dict[str, Any]) -> dict[str, float]:
    sc = load_config().get("scores") or {}
    # confidence: planner → strategy card → synthesis → default
    conf = next(
        (c for c in (fx["plan_confidence"], fx["strategy_confidence"], fx["synthesis_confidence"]) if c is not None),
        None,
    )
    conf_src = "entry_plan" if fx["plan_confidence"] is not None else (
        "strategy_card" if fx["strategy_confidence"] is not None else (
            "synthesis" if fx["synthesis_confidence"] is not None else "default"))
    if conf is None:
        conf = float(sc.get("default_confidence") or 0.3)
    if conf > 1:
        conf = conf / 100.0
    # reward: plan R:R → strategy R:R → street upside
    rr = fx["plan_rr"] if fx["plan_rr"] is not None else fx["strategy_rr"]
    if rr is not None and rr > 0:
        reward = rr / float(sc.get("reward_rr_full") or 3.0)
    elif fx["upside_pct"] is not None:
        reward = fx["upside_pct"] / float(sc.get("reward_upside_full_pct") or 30)
    else:
        reward = 0.0
    # risk: stop distance + held-and-negative + earnings + blocked state + stated risk
    stop = fx["plan_stop"] if fx["plan_stop"] is not None else fx["strategy_stop"]
    risk = 0.2
    if stop and fx["last"]:
        risk = abs(fx["last"] - stop) / fx["last"] * 100 / float(sc.get("risk_stop_full_pct") or 15)
    if fx["held"] and (fx["synthesis"] in ("SELL", "TRIM", "AVOID") or fx["trade_state"] in ("AVOID", "BLOCKED")):
        risk = max(risk, 0.9)
    ed = fx["earnings_days"]
    earn_window = float(sc.get("risk_earnings_days") or 7)
    if ed is not None and 0 <= ed <= earn_window:
        risk += 0.2
    if fx["trade_state"] in ("AVOID", "BLOCKED", "DETERMINISTIC_FAIL"):
        risk += 0.2
    if fx["primary_risk"]:
        risk += 0.05
    # time sensitivity: in zone / ready → near trigger / near re-entry → near_entry plan → earnings → idle
    near_full = float(sc.get("near_full_pct") or 6)
    t = 0.2
    if fx["in_zone"] or fx["reentry_state"] == "READY TO REVIEW" or fx["proposal_allowed"]:
        t = 1.0
    else:
        dists = [d for d in (fx["near_pct"] if fx["near_trigger"] else None, fx["reentry_distance_pct"]
                             if fx["reentry_state"] == "NEAR ENTRY" else None) if d is not None]
        if dists:
            t = max(t, 1.0 - min(dists) / near_full)
        if fx["plan_urgency"] == "ready":
            t = max(t, 0.8)
        elif fx["plan_urgency"] == "near_entry":
            t = max(t, 0.6)
    if ed is not None and 0 <= ed <= earn_window:
        t = max(t, 0.7)
    return {
        "confidence": _clip(conf),
        "confidence_source": conf_src,
        "risk_score": _clip(risk),
        "reward_score": _clip(reward),
        "time_sensitivity": _clip(t),
    }


def decide(card: dict[str, Any], inp: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """The decision block for one Watch card."""
    now = now or datetime.now(timezone.utc)
    cfg = load_config()
    fx = facts(card, inp, now=now)
    rule = next((r for r in cfg.get("rules") or [] if _holds(r.get("when") or {}, fx)), None) or {
        "id": "candidate", "category": "watchlist_candidate", "priority": "low", "actionable": False}
    cat = rule["category"]
    cats = {c["id"]: c for c in categories()}
    ttl_h = cats.get(cat, {}).get("ttl_hours", 168.0)
    s = score(fx)
    base = str(rule.get("priority") or "low")
    ps = round(100 * (0.35 * s["time_sensitivity"] + 0.25 * max(s["risk_score"], s["reward_score"])
                      + 0.20 * s["confidence"] + 0.20 * PRIORITY_TIER.get(base, 0.25)), 1)
    bands = cfg.get("priority_bands") or {}
    label = "low"
    for p in ("critical", "high", "medium"):
        if ps >= float(bands.get(p, 101)):
            label = p
            break
    bi = PRIORITY_ORDER.index(base) if base in PRIORITY_ORDER else 3
    li = min(max(PRIORITY_ORDER.index(label), bi - 1), bi)  # at most one tier above base, never below it
    label = PRIORITY_ORDER[li]

    # evidence: the newest fact that (re)affirms the signal
    ev = [x for x in (fx["plan_at"] if fx["plan_fresh"] else None, fx["synthesis_at"], fx["review_at"],
                      fx["reentry_at"] if cat == "re_entry" else None) if x is not None]
    evidence_at = max(ev) if ev else None
    expires_at = evidence_at + timedelta(hours=ttl_h) if evidence_at else None
    reentry_status = (cfg.get("reentry_status") or {}).get(fx["reentry_state"]) if fx["reentry_state"] else None

    inval_states = {str(x).upper() for x in cfg.get("invalidating_trade_states") or []}
    inval_syn = {str(x).upper() for x in cfg.get("invalidating_synthesis") or []}
    if not fx["held"] and cat != "re_entry" and (fx["trade_state"] in inval_states or fx["synthesis"] in inval_syn):
        status = "invalidated"
    elif evidence_at is None:
        status = "needs_data"
    elif expires_at and expires_at < now:
        status = "expired"
    else:
        status = "active"
    if status == "expired" and reentry_status and reentry_status != "invalidated":
        reentry_status = "expired"
    actionable = bool(rule.get("actionable")) and status == "active"
    return {
        "version": DECISION_VERSION,
        "rule_id": rule.get("id"),
        "category": cat,
        "category_label": cats.get(cat, {}).get("label", cat),
        "priority": label,
        "priority_score": ps,
        **s,
        "reentry_status": reentry_status,
        "reentry_state": fx["reentry_state"] or None,
        "actionable": actionable,
        "action_hint": (rule.get("action") or fx["reentry_action"]) if actionable else None,
        "status": status,
        "held": fx["held"],
        "ttl_hours": ttl_h,
        "evidence_at": evidence_at.isoformat() if evidence_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "ttl_remaining_s": int((expires_at - now).total_seconds()) if expires_at and status == "active" else None,
        "inputs": {
            "plan_urgency": fx["plan_urgency"] or None,
            "plan_rr": fx["plan_rr"],
            "in_zone": fx["in_zone"],
            "near_trigger": fx["near_trigger"],
            "synthesis": fx["synthesis"] or None,
            "earnings_days": fx["earnings_days"],
        },
    }


def attach(cards: list[dict[str, Any]], *, now: Optional[datetime] = None) -> None:
    """Set card["decision"] on every card in place (one batched input read)."""
    now = now or datetime.now(timezone.utc)
    inputs = load_inputs([c.get("symbol") for c in cards])
    for c in cards:
        c["decision"] = decide(c, inputs.get((c.get("symbol") or "").upper()) or {}, now=now)


# ── filters, sorts, board ───────────────────────────────────────────────────


def _csv(v: Any) -> set[str]:
    return {x.strip().lower() for x in str(v or "").split(",") if x.strip()}


def is_live(d: dict[str, Any]) -> bool:
    """Shown in the active views. Held positions always are — only a non-held idea's signal can age out."""
    return d.get("status") in ("active", "needs_data") or bool(d.get("held"))


def passes(d: dict[str, Any], q: dict[str, Any]) -> bool:
    """Decision filters (all optional). Expired/invalidated are hidden unless asked for."""
    st = _csv(q.get("decision_status"))
    re_st = _csv(q.get("reentry_status"))
    # A text search always finds the name (its status badge says why it is out of the active views).
    include = str(q.get("include_expired") or "").lower() in ("1", "true", "yes") or bool(
        str(q.get("q") or q.get("search") or "").strip())
    if st:
        if d.get("status") not in st:
            return False
    elif not include and not (re_st & {"expired", "invalidated"}) and not is_live(d):
        return False
    if _csv(q.get("category")) and d.get("category") not in _csv(q.get("category")):
        return False
    if _csv(q.get("priority")) and d.get("priority") not in _csv(q.get("priority")):
        return False
    if re_st and (d.get("reentry_status") or "") not in re_st:
        return False
    if str(q.get("actionable") or "").lower() in ("1", "true", "yes") and not d.get("actionable"):
        return False
    for key, fld in (("min_confidence", "confidence"), ("min_risk", "risk_score"), ("min_reward", "reward_score"),
                     ("min_time", "time_sensitivity"), ("min_priority_score", "priority_score")):
        v = _f(q.get(key))
        if v is not None and (_f(d.get(fld)) or 0) < v:
            return False
    for key, fld in (("max_risk", "risk_score"),):
        v = _f(q.get(key))
        if v is not None and (_f(d.get(fld)) or 0) > v:
            return False
    within = _f(q.get("expiring_within_h"))
    if within is not None:
        rem = d.get("ttl_remaining_s")
        if rem is None or rem > within * 3600:
            return False
    return True


def sort_key(sort: str):
    sort = (sort or "").lower()

    def key(it: dict[str, Any]):
        d = (it.get("card") or {}).get("decision") or {}
        if sort == "expires_at":
            rem = d.get("ttl_remaining_s")
            return (rem is None, rem if rem is not None else 0)
        return (-(_f(d.get(sort)) or 0), -(_f(d.get("priority_score")) or 0))

    return key


def _compact(c: dict[str, Any]) -> dict[str, Any]:
    d = c.get("decision") or {}
    return {
        "symbol": c.get("symbol"),
        "company": c.get("company"),
        "last": c.get("last"),
        "day_change_pct": c.get("day_change_pct"),
        "held": bool(c.get("held")),
        **{k: d.get(k) for k in ("category", "category_label", "priority", "priority_score", "confidence",
                                 "risk_score", "reward_score", "time_sensitivity", "reentry_status", "actionable",
                                 "action_hint", "status", "expires_at", "ttl_remaining_s", "evidence_at")},
    }


def board(cards: list[dict[str, Any]], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """The six at-a-glance answers over the whole matched universe (not just the page)."""
    now = now or datetime.now(timezone.utc)
    b = load_config().get("board") or {}
    n = int(b.get("panel_size") or 6)
    live = [c for c in cards if is_live(c.get("decision") or {})]
    d = lambda c: c.get("decision") or {}  # noqa: E731
    exp_s = float(b.get("expiring_within_hours") or 24) * 3600
    recent = now - timedelta(hours=float(b.get("recent_hours") or 24))
    rmin, kmin = float(b.get("reward_min") or 0.5), float(b.get("risk_min") or 0.6)

    def top(rows, k):
        return [_compact(c) for c in sorted(rows, key=lambda c: (-(_f(d(c).get(k)) or 0),
                                                              -(_f(d(c).get("priority_score")) or 0)))[:n]]

    panels = {
        "attention": {"label": "Needs attention now", "count": sum(1 for c in live if d(c).get("actionable")),
                      "items": top([c for c in live if d(c).get("actionable")], "priority_score")},
        "reward": {"label": "Highest reward", "count": sum(1 for c in live if (d(c).get("reward_score") or 0) >= rmin),
                   "items": top([c for c in live if (d(c).get("reward_score") or 0) >= rmin], "reward_score")},
        "reentry": {"label": "Top re-entry candidates",
                    "count": sum(1 for c in live if d(c).get("reentry_status") in ("confirmed", "potential")),
                    "items": top([c for c in live if d(c).get("reentry_status") in ("confirmed", "potential")],
                                 "priority_score")},
        "risk": {"label": "Highest risk",
                 "count": sum(1 for c in live if d(c).get("category") == "risk" or (d(c).get("risk_score") or 0) >= kmin),
                 "items": top([c for c in live if d(c).get("category") == "risk" or (d(c).get("risk_score") or 0) >= kmin],
                              "risk_score")},
        "expiring": {"label": "Expiring soon",
                     "count": sum(1 for c in live if (d(c).get("ttl_remaining_s") or exp_s + 1) <= exp_s),
                     "items": [_compact(c) for c in sorted(
                         [c for c in live if (d(c).get("ttl_remaining_s") or exp_s + 1) <= exp_s],
                         key=lambda c: d(c).get("ttl_remaining_s") or 0)[:n]]},
        "recent": {"label": "Recently actionable",
                   "count": sum(1 for c in live if d(c).get("actionable") and (_ts(d(c).get("evidence_at")) or recent) > recent),
                   "items": [_compact(c) for c in sorted(
                       [c for c in live if d(c).get("actionable") and (_ts(d(c).get("evidence_at")) or recent) > recent],
                       key=lambda c: str(d(c).get("evidence_at") or ""), reverse=True)[:n]]},
    }
    facets: dict[str, dict[str, int]] = {"category": {}, "priority": {}, "status": {}, "reentry_status": {}}
    for c in cards:
        for k in facets:
            v = d(c).get(k)
            if v:
                facets[k][v] = facets[k].get(v, 0) + 1
    return {"version": DECISION_VERSION, "panels": panels, "live": len(live),
            "actionable": sum(1 for c in live if d(c).get("actionable")), "facets": facets,
            "categories": categories(), "sorts": list(SORTS)}
