"""DefenseProjection@v1 — one defense read built on the Market Risk engine (design defense/v001).

The Defense page used to keep its own copies of sector state, hedge thesis and exposure, 22 hours to
92 days old, and none of them read the engine (defects D1/D2). This module joins, in one pure function:

* the Market Risk projection as the API serves it (engine snapshot + book join): tier, score, shock type,
  heatmap, book_exposure, protect, hedge, position stances, deep-brief base rates, de-escalation rule;
* cio_truth.resolve: counted positions and the stop breakdown (via the stored DefenseStopsSlice@v1, see
  ``stops_slice``; or passed in live by a host caller);
* the labelled side inputs: inverse stoplights, cash alternatives, recommendations, the sector desk copy,
  industries, hedging radar, options lifecycle.

Contract
--------
* Read-only and advisory. No size, order, share-count, price-level or stop-level field exists anywhere in
  the output; ``assert_advisory`` enforces it (the engine's BEHAVIOR_FIELDS plus this desk's list) and the
  build refuses to write a document that fails it.
* Every section carries ``as_of`` and ``stale_reason``. A stale or missing input says so in the section and
  in ``sources[]``; it never disappears and never reads as calm.
* Narrative sentences come from a fixed template, one field each. No LLM.
* ``inverse_triggers`` (hedge_readiness) is the thesis input the inverse stoplights read (D2): it uses the
  engine's look-through stressed share, not a recommendation card title.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

SCHEMA = "DefenseProjection@v1"
OUT_REL = "data/runtime/defense_engine_latest.json"
#: The stops/positions slice of cio_truth.resolve that the build reads (DefenseStopsSlice@v1). The host side
#: (lib.defense_stops_slice) resolves and writes it; the builder only reads the file, so the n8n lane
#: defense-engine-build never imports cio_truth -> holdings_document -> db_adapter (broker-reach gate).
STOPS_SLICE_SCHEMA = "DefenseStopsSlice@v1"
STOPS_SLICE_REL = "data/runtime/defense_stops_slice_latest.json"
#: The position-row fields the projection reads (_stops_section, _held_exit_review, held_symbols).
STOPS_SLICE_ROW_FIELDS = ("symbol", "account_id", "account_label", "counted", "market_value", "stop_category",
                          "stop_note", "distance_to_stop_pct", "resting_stop_distance_pct")
LADDER = ("GREEN", "BLUE", "YELLOW", "ORANGE", "RED")

#: Desk-level forbidden keys on top of lib.market_risk.contract.BEHAVIOR_FIELDS (checked case-insensitively).
FORBIDDEN_KEYS = frozenset({
    "size_band", "share_count", "shares", "ticket", "tickets", "levels", "entry_price", "target_price",
    "limit_price", "stop_price", "stop_level", "new_stop", "tp1", "tp2", "order_id", "order_type",
    "dollars_by_account", "impact_dollars", "trim_plan", "qty", "quantity",
})

#: Defaults; config/defense_recommendations.json "defense_engine" overrides each key.
DEFAULTS: dict[str, Any] = {
    "near_stop_pct": 4.0,
    "stale_projection_hours": 26.0,   # the stoplights' THESIS reads the projection up to this age
    "projection_serve_hours": 1.5,    # GET /api/v2/defense/engine builds in-request past this age
    "max_rows": 12,
    "index_inverse": {"SPY": "SH", "DIA": "DOG", "IWM": "RWM"},
    "sector_inverse": {"QQQ": ["tech", "semis", "ai_basket", "comm"]},
    "systemic_shocks": ["SYSTEMIC", "CREDIT"],
    "sources": {
        # id: [label, sla_hours, [lane ids]]   (an empty lane list = no scheduled writer)
        "market_risk": ["Market Risk engine", 1.0, ["market-risk-evaluate"]],
        "stops": ["Stops (CIO record)", 1.0, ["unified-stop-supervisor"]],
        "stoplights": ["Inverse stoplights", 26.0, ["defense-inverse-stoplights"]],
        "recommendations": ["Recommendations", 26.0, ["defense-recommendations"]],
        "sector_desk": ["Sector desk copy", 26.0, ["sector-momentum-engine"]],
        "industries": ["Industries", 26.0, ["industry-momentum-groups"]],
        "radar": ["Hedging radar", 26.0, ["hedging-radar"]],
        "options": ["Options lifecycle", 26.0, ["options-lifecycle-run"]],
        "cash": ["Cash alternatives", 26.0, []],
    },
}

_OFF_STATES = ("PAUSED", "RETIRED", "NEVER_SCHEDULED")
_HELD_GROUPS = ("protect", "income")  # recommendation groups that are about names the book holds


# ── small helpers ────────────────────────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _dt(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    s = str(raw).strip()
    try:
        if len(s) == 10:
            d = datetime.fromisoformat(s).replace(hour=21, tzinfo=timezone.utc)  # a date = that session's close
        else:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(raw: Any) -> Optional[str]:
    d = _dt(raw)
    return d.isoformat() if d else None


def age_hours(raw: Any, now: datetime) -> Optional[float]:
    d = _dt(raw)
    return round((now - d).total_seconds() / 3600, 2) if d else None


def money(v: Any) -> str:
    """$86.6K / $1.2M / $211 — display text for narrative sentences."""
    f = _num(v)
    if f is None:
        return "not on file"
    a = abs(f)
    sign = "-" if f < 0 else ""
    if a >= 1e6:
        return f"{sign}${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:.1f}K"
    return f"{sign}${a:,.0f}"


def pct(v: Any, digits: int = 0) -> str:
    f = _num(v)
    return "not on file" if f is None else f"{f:.{digits}f}%"


def fmt_signed(v: Any, digits: int = 1) -> str:
    """'+7.5' / '-5.5' / 'n/a' — None-safe (the D5 class of crash: format spec on None)."""
    f = _num(v)
    return "n/a" if f is None else f"{f:+.{digits}f}"


def _and(names: list[str]) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _section(as_of: Any, stale_reason: Optional[str], **body: Any) -> dict:
    return {"as_of": _iso(as_of) if as_of else None, "stale_reason": stale_reason, **body}


def config(raw: Optional[dict]) -> dict:
    """DEFAULTS overlaid with config/defense_recommendations.json "defense_engine" (unknown keys ignored)."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for k, v in ((raw or {}).get("defense_engine") or {}).items():
        if k in out and k != "_comment":
            out[k] = {**out[k], **v} if isinstance(out[k], dict) and isinstance(v, dict) else v
    return out


# ── advisory guard ───────────────────────────────────────────────────────────

def assert_advisory(obj: Any, path: str = "") -> None:
    """Raise ValueError when any key is a behaviour/size/order/level field. Walks dicts and lists."""
    try:
        from lib.market_risk.contract import BEHAVIOR_FIELDS  # type: ignore
    except Exception:  # noqa: BLE001 -- the desk list still applies when the engine package is absent
        BEHAVIOR_FIELDS = frozenset()
    banned = set(BEHAVIOR_FIELDS) | FORBIDDEN_KEYS
    if isinstance(obj, dict):
        for k, v in obj.items():
            where = f"{path}.{k}" if path else str(k)
            if str(k).lower() in banned:
                raise ValueError(f"advisory projection carries a forbidden field: {where}")
            assert_advisory(v, where)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_advisory(v, f"{path}[{i}]")


# ── D4: recommendation cards for names no longer held ────────────────────────

def _card_symbols(card: dict) -> list[str]:
    out = []
    for i in card.get("instruments") or []:
        s = str((i or {}).get("symbol") or "").strip().upper() if isinstance(i, dict) else ""
        if s and re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", s):
            out.append(s)
    return out


def drop_unheld_cards(groups: Any, held: Optional[Iterable[str]]) -> tuple[dict, list[dict]]:
    """Cards in the held-name groups whose every instrument is no longer in the book are dropped (D4).

    ``held`` None means the holdings could not be read: nothing is dropped (unknown is never "sold").
    A card with no real symbol (a status card such as "PUT HEDGES · designer live") is kept.
    Returns (groups, dropped[{group, id, title, symbols}]).
    """
    groups = groups if isinstance(groups, dict) else {}
    if held is None:
        return dict(groups), []
    held_set = {str(s).upper() for s in held if s}
    kept: dict = {}
    dropped: list[dict] = []
    for g, cards in groups.items():
        if not isinstance(cards, list) or g not in _HELD_GROUPS:
            kept[g] = cards
            continue
        keep = []
        for c in cards:
            syms = _card_symbols(c) if isinstance(c, dict) else []
            if syms and not any(s in held_set for s in syms):
                dropped.append({"group": g, "id": c.get("id"), "title": c.get("title"), "symbols": syms})
            else:
                keep.append(c)
        kept[g] = keep
    return kept, dropped


# ── D2: thesis inputs for the inverse stoplights ─────────────────────────────

def inverse_triggers(mr: Optional[dict], cfg: dict, *, stale_reason: Optional[str] = None) -> dict:
    """bench → {inverse, trigger, exposure_pct, reason} from the engine's look-through stressed share.

    * QQQ (PSQ): one tech-family group (tech / semis / AI basket / comm) at or above trigger_book_pct of
      invested — a sector shock is what a Nasdaq hedge answers.
    * SPY / DIA / IWM: stressed share of invested at or above trigger_book_pct AND the shock is broad
      (lagging sectors at or above index_trigger_lagging_sectors, or shock type SYSTEMIC/CREDIT).
    * No engine, no hedge block, or a stale engine: trigger None (the light goes AMBER, never RED).
    """
    index_inv = cfg.get("index_inverse") or {}
    sector_inv = cfg.get("sector_inverse") or {}
    benches = list(index_inv) + [b for b in sector_inv if b not in index_inv]
    inv_names = {**index_inv, "QQQ": "PSQ"}
    hedge = (mr or {}).get("hedge") if isinstance((mr or {}).get("hedge"), dict) else None
    unknown_why = stale_reason or ("Market Risk engine not on file" if not mr else
                                   "the engine projection carries no hedge block" if hedge is None else None)
    if unknown_why:
        return {b: {"inverse": inv_names.get(b), "trigger": None, "exposure_pct": None,
                    "reason": f"trigger unknown: {unknown_why}"} for b in benches}
    th = hedge.get("thresholds") or {}
    trig = _num(th.get("trigger_book_pct"))
    lag_need = _num(th.get("index_trigger_lagging_sectors"))
    lagging = _num(hedge.get("lagging_count"))
    stressed = _num(hedge.get("stressed_pct_invested"))
    shock = str(((mr or {}).get("shock_type") or {}).get("class") or "").upper() or None
    systemic = shock in {s.upper() for s in cfg.get("systemic_shocks") or []}
    out: dict = {}
    for bench, inv in index_inv.items():
        if trig is None or stressed is None:
            out[bench] = {"inverse": inv, "trigger": None, "exposure_pct": stressed,
                          "reason": "trigger unknown: threshold or stressed share not on file"}
            continue
        broad = systemic or (lagging is not None and lag_need is not None and lagging >= lag_need)
        met = stressed >= trig and broad
        why = (f"stressed {stressed:.1f}% of invested vs {trig:g}%; "
               f"{'shock ' + shock + ' is systemic' if systemic else f'{lagging:g} sectors lagging vs {lag_need:g}' if lagging is not None and lag_need is not None else 'breadth not on file'}")
        out[bench] = {"inverse": inv, "trigger": bool(met), "exposure_pct": round(stressed, 2), "reason": why}
    rows = [r for r in hedge.get("stressed_breakdown") or [] if isinstance(r, dict)]
    for bench, keys in sector_inv.items():
        fam = [r for r in rows if str(r.get("key")) in set(keys or [])]
        best = max(fam, key=lambda r: _num(r.get("pct_invested")) or 0, default=None)
        share = _num((best or {}).get("pct_invested"))
        if trig is None:
            out[bench] = {"inverse": inv_names.get(bench), "trigger": None, "exposure_pct": share,
                          "reason": "trigger unknown: threshold not on file"}
            continue
        if best is None:
            out[bench] = {"inverse": inv_names.get(bench), "trigger": False, "exposure_pct": 0.0,
                          "reason": "no tech-family group in stress"}
            continue
        out[bench] = {"inverse": inv_names.get(bench), "trigger": bool(share is not None and share >= trig),
                      "exposure_pct": round(share, 2) if share is not None else None,
                      "reason": f"{best.get('label') or best.get('key')} {best.get('state') or ''} carries "
                                f"{pct(share, 1)} of invested (look-through) vs {trig:g}%"}
    return out


def thesis_inputs_from_projection(doc: Any, now: datetime, *, max_age_hours: float) -> tuple[dict, dict, Optional[str]]:
    """(trigger{bench: bool|None}, exposure{bench: pct|None}, unknown_reason) for the stoplights' THESIS.

    A missing, unreadable or stale projection → every trigger None (AMBER), never False (RED).
    """
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return {}, {}, "defense engine projection not on file"
    age = age_hours(doc.get("generated_at"), now)
    if age is None or age > max_age_hours:
        return {}, {}, f"defense engine projection is {age if age is not None else '?'} h old (limit {max_age_hours:g} h)"
    trig = ((doc.get("hedge_readiness") or {}).get("inverse_triggers") or {})
    if not isinstance(trig, dict) or not trig:
        return {}, {}, "defense engine projection carries no inverse triggers"
    return ({b: (v or {}).get("trigger") for b, v in trig.items()},
            {b: _num((v or {}).get("exposure_pct")) for b, v in trig.items()}, None)


# ── sources ──────────────────────────────────────────────────────────────────

def source_row(sid: str, as_of: Any, cfg: dict, states: Optional[dict], now: datetime, *,
               gap: Optional[str] = None, stale: Optional[bool] = None) -> dict:
    label, sla, lanes = (cfg.get("sources") or {}).get(sid) or [sid, None, []]
    age = age_hours(as_of, now)
    off = [ln for ln in lanes if states is not None and states.get(ln) in _OFF_STATES]
    if not lanes:
        state, why = "no_writer", "no scheduled writer" + (f"; last output {_iso(as_of)[:10]}" if _iso(as_of) else "")
    elif off and len(off) == len(lanes):
        state, why = "paused", f"writer {', '.join(f'{ln} {states.get(ln)}' for ln in off)}"
    elif gap or as_of is None:
        state, why = "missing", gap or "not on file"
    elif stale is True or (stale is None and sla is not None and age is not None and age > sla):
        state, why = "stale", f"{age:g} h old, over the {sla:g} h limit" if age is not None else "stale"
    else:
        state, why = "fresh", None
    return {"id": sid, "label": label, "as_of": _iso(as_of), "age_hours": age, "sla_hours": sla,
            "lane_ids": list(lanes), "state": state, "stale_reason": why}


def _why(sources: dict, sid: str) -> Optional[str]:
    s = sources.get(sid) or {}
    return None if s.get("state") == "fresh" else (s.get("stale_reason") or s.get("state"))


# ── sections ─────────────────────────────────────────────────────────────────

def _tier_section(mr: dict, policy_tiers: Optional[dict], why: Optional[str]) -> dict:
    ep = mr.get("episode") if isinstance(mr.get("episode"), dict) else {}
    tier = str(mr.get("tier") or "") or None
    hist = [h for h in ep.get("tier_history") or [] if isinstance(h, dict)]
    since = next((h.get("at") for h in reversed(hist) if h.get("tier") == tier), ep.get("opened_at"))
    deesc = mr.get("deescalates_if")
    held = bool(deesc and "held by the completed-session rule" in str(deesc))
    m = re.search(r"(\d+) of (\d+) completed trading sessions", str(deesc or ""))
    ladder = []
    for t in LADDER:
        floor = _num(((policy_tiers or {}).get(t.lower()) or {}).get("min_score")) if t != "GREEN" else 0.0
        ladder.append({"tier": t, "min_score": floor, "current": t == tier})
    shock = mr.get("shock_type") if isinstance(mr.get("shock_type"), dict) else {}
    history = [{"as_of": h.get("as_of"), "score": _num(h.get("score")), "tier": h.get("tier")}
               for h in (mr.get("history") or []) if isinstance(h, dict)]
    return _section(mr.get("as_of"), why, tier=tier, score=_num(mr.get("score")), state=mr.get("state"),
                    mode=mr.get("mode"),
                    shock={"class": shock.get("class"), "label": shock.get("label"),
                           "confidence": _num(shock.get("confidence")), "headline": shock.get("headline")},
                    confirming=mr.get("confirming"),
                    categories=[{"name": c.get("name"), "category": c.get("category"), "state": c.get("state"),
                                 "score": _num(c.get("score")), "detail": c.get("detail"), "as_of": c.get("as_of")}
                                for c in mr.get("categories") or [] if isinstance(c, dict)],
                    ladder=ladder, since=since, opened_at=ep.get("opened_at"),
                    acknowledged_at=ep.get("acknowledged_at"), deescalates_if=deesc,
                    held_by_session_rule=held,
                    sessions_recorded={"n": int(m.group(1)), "of": int(m.group(2))} if m else None,
                    history=history[-48:])


def _exposure_section(mr: dict, max_rows: int, why: Optional[str]) -> dict:
    be = mr.get("book_exposure") if isinstance(mr.get("book_exposure"), dict) else None
    if not be:
        return _section(None, why or mr.get("book_exposure_error") or "book exposure is not joined (holdings store unreadable)",
                        rows=[], budgets=[], rotate=[], unmapped=[])
    stances = mr.get("positions") if isinstance(mr.get("positions"), dict) else {}
    rows = []
    for r in sorted((r for r in be.get("rows") or [] if isinstance(r, dict)),
                    key=lambda r: -(_num(r.get("usd_exposed")) or 0)):
        rows.append({"symbol": r.get("symbol"), "account_label": r.get("account_label"),
                     "value_usd": _num(r.get("value_usd")), "stressed_share": _num(r.get("stressed_share")),
                     "usd_exposed": _num(r.get("usd_exposed")), "stop_distance_pct": _num(r.get("stop_distance_pct")),
                     "stance": r.get("stance") or (stances.get(r.get("symbol")) or {}).get("stance"),
                     "stance_label": (stances.get(r.get("symbol")) or {}).get("label"),
                     "material": r.get("material")})
    material = [r for r in rows if (r["usd_exposed"] or 0) > 0 and r.get("material") is not False]
    residual = [r for r in rows if r not in material and (r["usd_exposed"] or 0) > 0]
    budgets = [{"account_label": b.get("account_label"), "budget": b.get("budget"), "limit": _num(b.get("limit")),
                "actual": _num(b.get("actual")), "unit": b.get("unit"), "actual_usd": _num(b.get("actual_usd")),
                "drivers": [{"symbol": d.get("symbol"), "usd": _num(d.get("usd"))}
                            for d in (b.get("drivers") or []) if isinstance(d, dict)]}
               for b in mr.get("budgets_detail") or [] if isinstance(b, dict)]
    rotate = mr.get("rotate") if isinstance(mr.get("rotate"), dict) else {}
    return _section(be.get("as_of"), why or be.get("ledger_error"),
                    total_usd=_num(be.get("total_usd")), invested_usd=_num(be.get("invested_usd")),
                    cash_usd=_num(be.get("cash_usd")), cash_pct_book=_num(be.get("cash_pct_book")),
                    stressed_usd=_num(be.get("stressed_usd")), stressed_pct_invested=_num(be.get("stressed_pct_invested")),
                    stressed_pct_book=_num(be.get("stressed_pct_book")), stressed_groups=be.get("stressed_groups") or [],
                    largest_contributor=be.get("largest_contributor"),
                    rows=material[:max_rows],
                    residuals={"count": len(residual), "usd_exposed": round(sum(r["usd_exposed"] or 0 for r in residual), 2),
                               "symbols": [r["symbol"] for r in residual[:6]]},
                    unmapped=[u for u in be.get("unmapped") or []][:max_rows],
                    budgets=budgets,
                    rotate=[{"key": g.get("key"), "label": g.get("label"), "state": g.get("state"),
                             "rs5": _num(g.get("rs5")), "usd": _num(g.get("usd"))}
                            for g in rotate.get("groups") or [] if isinstance(g, dict)],
                    rotate_as_of=rotate.get("as_of"), stops_known=be.get("stops_known"))


def _stops_section(truth: dict, near_pct: float, max_rows: int, why: Optional[str]) -> dict:
    pos = truth.get("positions") if isinstance(truth.get("positions"), dict) else {}
    rows = [p for p in pos.get("rows") or [] if isinstance(p, dict)]
    counted = [p for p in rows if p.get("counted")] if any(isinstance(p.get("counted"), bool) for p in rows) else rows
    bd = pos.get("stop_breakdown") if isinstance(pos.get("stop_breakdown"), dict) else None
    as_of = truth.get("generated_at") or truth.get("as_of")
    if bd is None:
        return _section(as_of, why or "the stop breakdown is not on file (broker stop reads unavailable)",
                        no_stop=None, planned_only=None, pending=None, filled=None, unknown=None, gaps=[], near=[])

    def _n(cat: str) -> int:
        return int((bd.get(cat) or {}).get("count") or 0)

    def _v(cat: str) -> Optional[float]:
        return _num((bd.get(cat) or {}).get("value_usd"))
    gaps = []
    for p in sorted((p for p in counted if p.get("stop_category") in ("none", "planned")),
                    key=lambda p: -(_num(p.get("market_value")) or 0))[:max_rows]:
        state = "planned level only" if p.get("stop_category") == "planned" else (p.get("stop_note") or "no stop")
        gaps.append({"symbol": p.get("symbol"), "account_label": p.get("account_label") or p.get("account_id"),
                     "value_usd": _num(p.get("market_value")), "state": state})
    near = []
    for p in counted:
        d = _num(p.get("distance_to_stop_pct"))
        if d is None:
            d = _num(p.get("resting_stop_distance_pct"))
        if d is not None and 0 <= d <= near_pct:
            near.append({"symbol": p.get("symbol"), "account_label": p.get("account_label") or p.get("account_id"),
                         "distance_pct": d})
    near.sort(key=lambda r: r["distance_pct"])
    vals = [_v("none"), _v("planned")]
    return _section(as_of, why,
                    no_stop={"count": _n("none") + _n("planned"),
                             "value_usd": round(sum(vals), 2) if all(v is not None for v in vals) else None},
                    planned_only=_n("planned"), pending={"count": _n("pending_activation"), "value_usd": _v("pending_activation")},
                    active=_n("active"), filled={"count": _n("filled")}, unknown={"count": _n("unknown")},
                    near_threshold_pct=near_pct, gaps=gaps, near=near[:max_rows],
                    hedged_share="not measured", beta="not measured")


def _hedge_section(mr: dict, cfg: dict, stoplights: dict, radar: dict, options_src: dict, why: Optional[str],
                   lights_why: Optional[str]) -> dict:
    hedge = mr.get("hedge") if isinstance(mr.get("hedge"), dict) else None
    triggers = inverse_triggers(mr, cfg, stale_reason=why)
    shock = mr.get("shock_type") if isinstance(mr.get("shock_type"), dict) else {}
    lanes = [c for c in stoplights.get("candidates") or [] if isinstance(c, dict)]
    lane = [{"inverse": c.get("inverse"), "bench": c.get("bench"), "name": c.get("name"),
             "leverage": c.get("leverage"), "expense_pct": _num(c.get("expense_pct")),
             "thesis_state": ((c.get("lights") or {}).get("THESIS") or {}).get("state"),
             "thesis_label": ((c.get("lights") or {}).get("THESIS") or {}).get("label")} for c in lanes]
    qqq = next((r for r in radar.get("radar") or [] if isinstance(r, dict) and r.get("symbol") == "QQQ"), {})
    put_rows = [r for r in radar.get("radar") or [] if isinstance(r, dict) and r.get("prot_put")]
    thesis = next(((c.get("lights") or {}).get("THESIS") for c in lanes if c.get("bench") == "SPY"), None) or {}
    if not hedge:
        return _section(None, why or "the engine projection carries no hedge block", readiness="UNKNOWN", verdict=None, triggers=[],
                        met_count=None, of=None, inverse_triggers=triggers, inverse_lane=lane,
                        thesis_light={"state": thesis.get("state"), "label": thesis.get("label"),
                                      "as_of": stoplights.get("generated_at"), "stale_reason": lights_why},
                        put_protection={"qqq_atm_iv": _num(qqq.get("atm_iv")), "as_of": radar.get("captured_at"),
                                        "structures": len(put_rows), "lifecycle": options_src})
    th = hedge.get("thresholds") or {}
    trig, lag_need = _num(th.get("trigger_book_pct")), _num(th.get("index_trigger_lagging_sectors"))
    stressed, lagging = _num(hedge.get("stressed_pct_invested")), _num(hedge.get("lagging_count"))
    measured = _num(((mr.get("sectors") or {}).get("sectors_measured")))
    systemic = str(shock.get("class") or "").upper() in {s.upper() for s in cfg.get("systemic_shocks") or []}
    lw = hedge.get("largest_weakening") or {}
    t1 = {"id": "exposure", "label": f"Stressed groups ≥ {trig:g}% of invested" if trig is not None else "Stressed groups vs threshold",
          "value": stressed, "threshold": trig, "unit": "% of invested",
          "met": (stressed >= trig) if stressed is not None and trig is not None else None,
          "detail": f"Now {pct(stressed, 1)}" + (f" ({lw.get('label')}, look-through)" if lw.get("label") else "")}
    broad_met = None if lagging is None or lag_need is None else (lagging >= lag_need or systemic)
    t2 = {"id": "breadth", "label": (f"{lag_need:g} or more of {measured:g} sectors lagging, or the shock is SYSTEMIC"
                                     if lag_need is not None and measured is not None else "Broad selloff or SYSTEMIC shock"),
          "value": lagging, "threshold": lag_need, "unit": "sectors",
          "met": broad_met,
          "detail": f"Now {lagging:g} lagging, shock {shock.get('class') or 'not on file'}"
                    + (f" (confidence {pct(100 * (_num(shock.get('confidence')) or 0))})" if shock.get("confidence") is not None else "")
          if lagging is not None else "lagging count not on file"}
    t1["when"] = f"stressed groups reach {trig:g}% of invested" if trig is not None else None
    t2["when"] = (f"the shock turns systemic or {lag_need:g} or more sectors lag" if lag_need is not None else None)
    met = [t for t in (t1, t2) if t["met"]]
    unknown = any(t["met"] is None for t in (t1, t2))
    # The page's readiness word comes from the two conditions; the engine's own verdict (which waits on the
    # stoplight's thesis) is carried beside it with its reason, never as the section's staleness.
    readiness = "UNKNOWN" if unknown and len(met) < 2 else "CONDITIONS MET" if len(met) == 2 else "NOT NOW"
    return _section(hedge.get("as_of") or mr.get("as_of"), why,
                    readiness=readiness,
                    verdict=hedge.get("verdict"), verdict_reason=hedge.get("reason"), thesis_state=hedge.get("thesis_state"),
                    shock_class=shock.get("class"), shock_confidence=_num(shock.get("confidence")),
                    triggers=[t1, t2], met_count=len(met), of=2,
                    candidates=list(hedge.get("candidates") or []), since=hedge.get("since"),
                    momentum_as_of=hedge.get("momentum_as_of"),
                    inverse_triggers=triggers, inverse_lane=lane,
                    thesis_light={"state": thesis.get("state"), "label": thesis.get("label"),
                                  "reason": thesis.get("reason"), "as_of": stoplights.get("generated_at"),
                                  "stale_reason": lights_why},
                    put_protection={"qqq_atm_iv": _num(qqq.get("atm_iv")), "as_of": radar.get("captured_at"),
                                    "structures": len(put_rows), "lifecycle": options_src})


_BR = re.compile(r"^(?P<sym>[A-Z]{2,5}) next (?P<n>\d+) sessions: median (?P<med>[-+]?\d+(?:\.\d+)?)%"
                 r"(?:, 10th pct (?P<p10>[-+]?\d+(?:\.\d+)?)%)?(?:, 90th pct (?P<p90>[-+]?\d+(?:\.\d+)?)%)?"
                 r", lower in (?P<low>\d+(?:\.\d+)?)% of cases \(n=(?P<cnt>\d+)\)")


def base_rates_from_facts(brief: Any) -> dict:
    brief = brief if isinstance(brief, dict) else {}
    facts = [f for f in brief.get("facts") or [] if isinstance(f, dict) and f.get("section") == "next"]
    if not facts:
        return _section(brief.get("generated_at"), "no base rates in the engine's deep brief (it is written on trigger)",
                        rows=[], notes=[])
    rows, notes, n = [], [], None
    for f in facts:
        m = _BR.match(str(f.get("text") or ""))
        if m and m.group("sym") in ("SPY", "QQQ"):
            n = int(m.group("cnt"))
            rows.append({"label": f"{m.group('sym')} +{m.group('n')} sessions", "symbol": m.group("sym"),
                         "sessions": int(m.group("n")), "median_pct": float(m.group("med")),
                         "p10_pct": _num(m.group("p10")), "p90_pct": _num(m.group("p90")),
                         "lower_pct": float(m.group("low")), "n": n})
        elif not m:
            notes.append({"id": f.get("id"), "text": f.get("text")})
    drop = next((float(x.group(1)) for x in (re.search(r"followed in (\d+(?:\.\d+)?)% of cases", str(f.get("text")))
                                                for f in facts) if x), None)
    return _section(brief.get("generated_at") or (facts[0].get("as_of")), None, rows=rows, n=n,
                    further_drop_pct=drop, notes=notes, caveat="history, not a forecast")


def _cash_section(cash: dict, exposure: dict, src: dict) -> dict:
    vehicles = []
    for c in cash.get("top3") or cash.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        y = c.get("yield_data") or {}
        vehicles.append({"symbol": c.get("symbol"), "name": c.get("name"), "category": c.get("category"),
                         "yield_pct": _num(y.get("sec_yield")) if _num(y.get("sec_yield")) is not None else _num(y.get("div_yield"))})
    empty = bool(vehicles) and all(v["yield_pct"] is None for v in vehicles)
    why = src.get("stale_reason") if src.get("state") != "fresh" else None
    if empty:
        why = (why + "; " if why else "") + "every yield in the last run is empty"
    return _section(cash.get("generated_at"), why, state=src.get("state"), vehicles=vehicles[:6],
                    yields_on_file=not empty and bool(vehicles),
                    risk_free_rate_constant=_num(cash.get("risk_free_rate")),
                    cash_pct_book=exposure.get("cash_pct_book"), cash_usd=exposure.get("cash_usd"))


_ENGINE_TO_DESK = {"STRESS": "weak", "WEAK": "weak", "WEAKENING": "weak", "RESILIENT": "strong",
                   "ROTATING": "strong", "LAGGING": "weak", "LEADING": "strong", "IMPROVING": "strong"}


def _norm_label(s: Any) -> str:
    return re.sub(r"[^a-z]", "", str(s or "").lower().replace("communication services", "communications"))


def _sector_section(mr: dict, desk: dict, why: Optional[str], desk_why: Optional[str]) -> dict:
    heat = [h for h in mr.get("heatmap") or [] if isinstance(h, dict)]
    order = {"STRESS": 0, "WEAK": 1, "RESILIENT": 2}
    engine = [{"key": h.get("key"), "label": h.get("label"), "kind": h.get("kind"), "state": h.get("state"),
               "rs5": _num(h.get("rs5")), "r5": _num(h.get("r5")), "book_exposure_share": _num(h.get("book_exposure_share")),
               "check_data": _num(h.get("rs5")) is None, "as_of": h.get("as_of")}
              for h in sorted(heat, key=lambda h: (order.get(str(h.get("state")), 3), _num(h.get("rs5")) or 0))]
    desk_rows = [{"sector": r.get("sector"), "state": r.get("state")} for r in desk.get("rows") or [] if isinstance(r, dict)]
    by_label = {_norm_label(e["label"]): e for e in engine if e.get("kind") in ("sector", None)}
    disagree = []
    for d in desk_rows:
        e = by_label.get(_norm_label(d["sector"]))
        if not e or not d.get("state") or not e.get("state"):
            continue
        a, b = _ENGINE_TO_DESK.get(str(e["state"]).upper()), _ENGINE_TO_DESK.get(str(d["state"]).upper())
        if a and b and a != b:
            disagree.append({"sector": d["sector"], "engine": e["state"], "desk": d["state"]})
    secs = mr.get("sectors") if isinstance(mr.get("sectors"), dict) else {}
    return _section((secs.get("as_of") or (heat[0].get("as_of") if heat else None)), why,
                    engine=engine, stressed=[e["label"] for e in engine if e["state"] == "STRESS"],
                    sectors_measured=secs.get("sectors_measured"), sectors_hit=secs.get("sectors_hit"),
                    sectors_down=secs.get("sectors_down"), defensive=secs.get("defensive"),
                    desk_copy={"as_of": desk.get("generated_at"), "stale_reason": desk_why, "rows": desk_rows,
                               "classified": sum(1 for d in desk_rows if d.get("state")), "of": len(desk_rows)},
                    disagreements=disagree, shown="engine")


def _watch_section(mr: dict, tier: dict) -> dict:
    brief = mr.get("deep_brief") if isinstance(mr.get("deep_brief"), dict) else {}
    items = []
    if tier.get("held_by_session_rule") and tier.get("sessions_recorded"):
        s = tier["sessions_recorded"]
        items.append({"kind": "deescalation", "text": f"De-escalation clock: {s['n']} of {s['of']} completed sessions below "
                                                      f"{tier.get('tier')} recorded; the next close can add one.",
                      "as_of": tier.get("as_of")})
    for f in brief.get("facts") or []:
        if isinstance(f, dict) and f.get("section") in ("catalysts",) and f.get("id") in ("cat-a", "cat-b"):
            items.append({"kind": "calendar", "text": f.get("text"), "as_of": f.get("as_of")})
    of = (mr.get("sources") or {}).get("options_flow") if isinstance(mr.get("sources"), dict) else None
    if isinstance(of, dict):
        items.append({"kind": "options_flow", "text": "Options flow refreshes with the next radar capture; watch whether "
                                                      "index put/call positioning falls back toward its median.",
                      "as_of": of.get("as_of")})
    for c in mr.get("categories") or []:
        if isinstance(c, dict) and c.get("state") == "UNKNOWN":
            items.append({"kind": "unknown", "text": f"{c.get('name')}: reads UNKNOWN, not calm.", "as_of": c.get("as_of")})
    for u in brief.get("unknown") or []:
        if isinstance(u, dict):
            items.append({"kind": "not_measured", "text": f"Not measured: {u.get('what')} ({u.get('reason')}).", "as_of": None})
    return _section(brief.get("generated_at") or mr.get("as_of"), None if brief else "the engine deep brief is not on file",
                    items=items[:12])


# ── narrative ────────────────────────────────────────────────────────────────

def _narrative(tier: dict, exposure: dict, stops: dict, hedge: dict, cash: dict, sector: dict, mr: dict,
               held_exit: list[dict]) -> dict:
    t = tier.get("tier")
    shock = (tier.get("shock") or {}).get("class")
    stressed = sector.get("stressed") or []
    if not t:
        headline = "Market risk is not on file."
    elif t in ("GREEN", "NONE", "BLUE"):
        headline = f"Market risk is {t}: no broad stress."
    elif shock == "SECTOR" and stressed:
        headline = f"{_and(stressed[:3])} {'is' if len(stressed) == 1 else 'are'} selling off. The rest of the market is holding."
    elif shock in ("SYSTEMIC", "CREDIT"):
        headline = f"The selloff is broad ({shock.lower()} shock)."
    else:
        headline = f"Market risk is {t}" + (f" ({(tier.get('shock') or {}).get('label')})." if shock else ".")

    stand = []
    m, hit = _num(sector.get("sectors_measured")), _num(sector.get("sectors_hit"))
    if m is not None and hit is not None:
        dfn = (sector.get("defensive") or {}).get("state") if isinstance(sector.get("defensive"), dict) else None
        stand.append({"field": "sectors", "as_of": sector.get("as_of"), "stale_reason": sector.get("stale_reason"),
                      "text": f"{m - hit:g} of {m:g} sectors are holding up" + (" and defensives are rising." if dfn == "RESILIENT" else ".")})
    of = (mr.get("sources") or {}).get("options_flow") if isinstance(mr.get("sources"), dict) else None
    if isinstance(of, dict):
        fac = [(_num(f.get("pc_oi_factor")), f.get("symbol")) for f in of.get("findings") or []
               if isinstance(f, dict) and f.get("symbol") in ("QQQ", "SPY") and f.get("pc_oi_state") == "STRESS"]
        fac = [x for x in fac if x[0] is not None]
        if fac:
            lo, hi = min(x[0] for x in fac), max(x[0] for x in fac)
            rng = f"{lo:.1f}×" if abs(hi - lo) < 0.05 else f"{lo:.1f}–{hi:.1f}×"
            stand.append({"field": "options_flow", "as_of": of.get("as_of"), "stale_reason": None,
                          "text": f"Options traders hold {rng} their usual put/call positions on {_and(sorted({x[1] for x in fac}, reverse=True))}."})
    if exposure.get("invested_usd") is not None:
        names = list(dict.fromkeys(r["symbol"] for r in exposure.get("rows") or [] if r.get("symbol")))[:2]
        txt = (f"Your book is {pct(exposure.get('cash_pct_book'))} cash. Of the {money(exposure.get('invested_usd'))} invested, "
               f"{money(exposure.get('stressed_usd'))} ({pct(exposure.get('stressed_pct_invested'))}) is in the stressed groups"
               + (f", mostly {_and(names)}." if names and (exposure.get('stressed_usd') or 0) > 0 else "."))
        stand.append({"field": "book_exposure", "as_of": exposure.get("as_of"), "stale_reason": exposure.get("stale_reason"),
                      "text": txt})
    else:
        stand.append({"field": "book_exposure", "as_of": None, "stale_reason": exposure.get("stale_reason"),
                      "text": f"Book exposure is not on file: {exposure.get('stale_reason')}."})

    steps = []
    if held_exit:
        names = [h["symbol"] for h in held_exit]
        big = held_exit[0]
        steps.append({"id": "review-exits", "sheet": "exposure", "tone": "bad",
                      "title": f"Review {_and(names[:3])}" + (f" and {len(names) - 3} more" if len(names) > 3 else "") + ".",
                      "text": f"The engine has {'both' if len(names) == 2 else 'these' if len(names) > 2 else 'it'} on exit review. "
                              f"{big['symbol']} is {money(big['value_usd'])}" + (f" across {big['accounts']} accounts." if big["accounts"] > 1 else ".")})
    ns = stops.get("no_stop") or {}
    if ns.get("count"):
        gap0 = (stops.get("gaps") or [{}])[0]
        pend = (stops.get("pending") or {}).get("count") or 0
        steps.append({"id": "stop-gaps", "sheet": "stops", "tone": "warn", "title": "Close the stop gaps.",
                      "text": f"{ns['count']} position{'s' if ns['count'] != 1 else ''} ({money(ns.get('value_usd'))}) "
                              f"{'have' if ns['count'] != 1 else 'has'} no broker stop"
                              + (f", including {gap0.get('symbol')} in {gap0.get('account_label')} ({money(gap0.get('value_usd'))})" if gap0.get("symbol") else "")
                              + "." + (f" {pend} stop{'s are' if pend != 1 else ' is'} resting until activation." if pend else "")})
    elif stops.get("stale_reason"):
        steps.append({"id": "stop-gaps", "sheet": "stops", "tone": "warn", "title": "Stop coverage unknown.",
                      "text": f"{stops['stale_reason']}."})
    trig = hedge.get("triggers") or []
    if hedge.get("readiness") in ("NOT NOW", "CONDITIONS MET"):
        unmet = next((x for x in trig if x.get("met") is False), None)
        met = next((x for x in trig if x.get("met")), None)
        indicated = hedge.get("readiness") == "CONDITIONS MET"
        steps.append({"id": "index-hedge", "sheet": "hedge", "tone": "warn" if indicated else "info",
                      "title": "Index hedge: " + ("conditions met." if indicated else "not indicated."),
                      "text": (f"It would be considered when {unmet.get('when') or unmet['label']} ({unmet['detail'][0].lower() + unmet['detail'][1:]})."
                               if unmet else "Both triggers are met.")
                              + (" The decision is yours." if indicated else "")
                              + (f" The exposure trigger is already met ({pct(met['value'], 1)} of invested vs {met['threshold']:g}%)."
                                 if met and met.get("id") == "exposure" and unmet and met.get("value") is not None else "")})
    else:
        steps.append({"id": "index-hedge", "sheet": "hedge", "tone": "warn", "title": "Hedge readiness unknown.",
                      "text": f"{hedge.get('stale_reason') or 'a trigger value is not on file'}."})
    if not cash.get("yields_on_file"):
        steps.append({"id": "cash-yield", "sheet": "cash", "tone": "warn", "title": "Cash yield: unknown.",
                      "text": "Cash-alternative yields are not on file" + (f" ({cash.get('stale_reason')})" if cash.get("stale_reason") else "")
                              + ", so the page can't compare T-bill or money-market rates yet."})
    return {"headline": headline, "where_we_stand": stand, "what_to_do": steps,
            "disclaimer": "Advisory. No order, size or stop level is implied. The decision is yours."}


def _held_exit_review(mr: dict, truth: dict) -> list[dict]:
    stances = mr.get("positions") if isinstance(mr.get("positions"), dict) else {}
    rows = [p for p in ((truth.get("positions") or {}).get("rows") or []) if isinstance(p, dict) and p.get("counted") is not False]
    out = []
    for sym, st in stances.items():
        if not isinstance(st, dict) or st.get("stance") != "EXIT":
            continue
        mine = [p for p in rows if str(p.get("symbol")) == sym]
        if not mine:
            continue  # the engine still lists a name the book no longer holds: not a step (D4 class)
        out.append({"symbol": sym, "value_usd": round(sum(_num(p.get("market_value")) or 0 for p in mine), 2),
                    "accounts": len({p.get("account_id") for p in mine})})
    return sorted(out, key=lambda r: -r["value_usd"])


def stops_slice(truth: Optional[dict], *, source: str = "cio_truth.resolve") -> Optional[dict]:
    """The part of a cio_truth.resolve document this projection reads, as a DefenseStopsSlice@v1 document.

    Pure. ``as_of`` is the resolve time; rows keep only STOPS_SLICE_ROW_FIELDS; the stop breakdown is copied
    whole. None when ``truth`` carries no positions object. ``truth_from_slice`` turns it back into the shape
    ``build_projection(truth=...)`` reads, so a slice-fed build and a live-fed build see the same fields."""
    if not isinstance(truth, dict) or not isinstance(truth.get("positions"), dict):
        return None
    pos = truth["positions"]
    rows = [{k: p.get(k) for k in STOPS_SLICE_ROW_FIELDS if k in p} for p in pos.get("rows") or [] if isinstance(p, dict)]
    bd = pos.get("stop_breakdown")
    return {"schema": STOPS_SLICE_SCHEMA, "source": source, "as_of": truth.get("generated_at") or truth.get("as_of"),
            "positions": {"rows": rows, "stop_breakdown": bd if isinstance(bd, dict) else None}}


def truth_from_slice(doc: Optional[dict]) -> tuple[Optional[dict], Optional[str]]:
    """(truth-shaped dict, gap) from a DefenseStopsSlice@v1 document; a wrong schema is a stated gap."""
    if not isinstance(doc, dict):
        return None, "stops slice not on file"
    if doc.get("schema") != STOPS_SLICE_SCHEMA:
        return None, f"stops slice schema {doc.get('schema')!r} is not {STOPS_SLICE_SCHEMA}"
    pos = doc.get("positions") if isinstance(doc.get("positions"), dict) else {}
    return {"generated_at": doc.get("as_of"), "positions": {"rows": list(pos.get("rows") or []),
                                                            "stop_breakdown": pos.get("stop_breakdown")}}, None


def held_symbols(truth: Optional[dict]) -> Optional[set[str]]:
    rows = ((truth or {}).get("positions") or {}).get("rows") if isinstance((truth or {}).get("positions"), dict) else None
    if not isinstance(rows, list):
        return None
    return {str(p.get("symbol")).upper() for p in rows if isinstance(p, dict) and p.get("symbol")}


# ── the projection ───────────────────────────────────────────────────────────

def build_projection(*, mr: Optional[dict], truth: Optional[dict], stoplights: Optional[dict] = None,
                     cash: Optional[dict] = None, recs: Optional[dict] = None, sector_desk: Optional[dict] = None,
                     industries: Optional[dict] = None, radar: Optional[dict] = None, options: Optional[dict] = None,
                     gaps: Optional[dict] = None, states: Optional[dict] = None, policy_tiers: Optional[dict] = None,
                     cfg_raw: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    """DefenseProjection@v1. Pure: every input is passed in; nothing is read or written here."""
    now = now or datetime.now(timezone.utc)
    cfg = config(cfg_raw)
    gaps = gaps or {}
    mr = mr if isinstance(mr, dict) else {}
    truth = truth if isinstance(truth, dict) else {}
    stoplights, cash, recs = stoplights or {}, cash or {}, recs or {}
    sector_desk, industries, radar, options = sector_desk or {}, industries or {}, radar or {}, options or {}

    src = {
        "market_risk": source_row("market_risk", mr.get("as_of"), cfg, states, now, gap=gaps.get("market_risk"),
                                  stale=bool(mr.get("stale")) if mr else None),
        "stops": source_row("stops", truth.get("generated_at") or truth.get("as_of"), cfg, states, now, gap=gaps.get("stops")),
        "stoplights": source_row("stoplights", stoplights.get("generated_at"), cfg, states, now, gap=gaps.get("stoplights")),
        "recommendations": source_row("recommendations", recs.get("generated_at"), cfg, states, now, gap=gaps.get("recommendations")),
        "sector_desk": source_row("sector_desk", sector_desk.get("generated_at"), cfg, states, now, gap=gaps.get("sector_desk")),
        "industries": source_row("industries", industries.get("captured_at"), cfg, states, now, gap=gaps.get("industries")),
        "radar": source_row("radar", radar.get("captured_at"), cfg, states, now, gap=gaps.get("radar")),
        "options": source_row("options", options.get("generated_at"), cfg, states, now, gap=gaps.get("options")),
        "cash": source_row("cash", cash.get("generated_at"), cfg, states, now, gap=gaps.get("cash")),
    }
    if mr and mr.get("stale") and mr.get("reason"):
        src["market_risk"]["stale_reason"] = str(mr.get("reason"))
    mr_why = _why(src, "market_risk") if mr else (gaps.get("market_risk") or "Market Risk engine not on file")
    tier = _tier_section(mr, policy_tiers, mr_why)
    exposure = _exposure_section(mr, int(cfg["max_rows"]), mr_why)
    stops = _stops_section(truth, float(cfg["near_stop_pct"]), int(cfg["max_rows"]), _why(src, "stops"))
    options_src = {"state": src["options"]["state"], "as_of": src["options"]["as_of"],
                   "stale_reason": src["options"]["stale_reason"]}
    hedge = _hedge_section(mr, cfg, stoplights, radar, options_src, mr_why, _why(src, "stoplights"))
    sector = _sector_section(mr, sector_desk, mr_why, _why(src, "sector_desk"))
    cash_s = _cash_section(cash, exposure, src["cash"])
    base = base_rates_from_facts(mr.get("deep_brief"))
    watch = _watch_section(mr, tier)

    held = held_symbols(truth)
    kept, dropped = drop_unheld_cards(recs.get("groups"), held)
    recs_s = _section(recs.get("generated_at"), _why(src, "recommendations"), mode=recs.get("mode"),
                      counts={g: len(v) for g, v in kept.items() if isinstance(v, list)},
                      dropped_unheld=dropped,
                      short_side=[{"title": c.get("title"), "symbols": _card_symbols(c), "mode": c.get("mode") or recs.get("mode")}
                                  for c in kept.get("short_side") or [] if isinstance(c, dict)][:6],
                      note="Cards carry tickets and sizes; they stay on Classic Defense. This page shows titles and counts only.")
    playbook = _section(tier.get("as_of"), tier.get("stale_reason"), current_tier=tier.get("tier"), since=tier.get("since"),
                        acknowledged_at=tier.get("acknowledged_at"), deescalates_if=tier.get("deescalates_if"),
                        held_by_session_rule=tier.get("held_by_session_rule"),
                        hedge_conditions=[t.get("label") for t in hedge.get("triggers") or []],
                        stage_text=None,
                        stage_text_reason="config/defense_playbook.yaml is not built yet; tier stage text needs operator approval",
                        black_tier="proposed, not built (RED is the engine's top tier)")
    narrative = _narrative(tier, exposure, stops, hedge, cash_s, sector, mr, _held_exit_review(mr, truth))
    sources = list(src.values())
    doc = {
        "schema": SCHEMA, "generated_at": now.isoformat(), "read_only": True, "financial_action": False,
        "as_of": tier.get("as_of"), "stale_reason": mr_why,
        "narrative": narrative, "tier": tier, "exposure": exposure, "stops": stops, "hedge_readiness": hedge,
        "playbook": playbook, "base_rates": base, "cash_alternatives": cash_s, "sector_posture": sector,
        "recommendations": recs_s, "watch_next": watch,
        "industries": _section(industries.get("captured_at"), _why(src, "industries"),
                               count=len(industries.get("industries") or []),
                               bottom=[{"name": i.get("industry") or i.get("name"), "state": i.get("quadrant") or i.get("state")}
                                       for i in (industries.get("bottom10") or [])[:5] if isinstance(i, dict)],
                               transitions=len(industries.get("transitions_confirmed") or [])),
        "sources": sources,
        "source_summary": {s: sum(1 for x in sources if x["state"] == s) for s in ("fresh", "stale", "missing", "paused", "no_writer")},
    }
    assert_advisory(doc)
    return doc
