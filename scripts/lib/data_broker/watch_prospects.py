"""Watch prospects — the record shape behind the /v3/watch redesign (operator directive 2026-10-22: build the
Gate 3 Watch mockup). Read-only. Zero provider calls.

What it returns: one row per security in exactly one stage lane — Actionable now · Setup forming · Re-entry near ·
Manage (held) · Expired — with conviction and its components, stance, why it is here, what is missing, every
conflict between inputs (shown, never resolved here: AGENTS.md §26.5), the next trigger (a reference level, never an
order), ONE next step, and what each surface shows for the same security.

Where the record comes from (AGENTS.md §26.1, §26.3):

* **The CIO prospect projection, when the store is live.** ``lib.data_broker.cio_prospect.get_prospects`` (the
  one-writer ``cio_prospect`` store, docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md §5.3) is built on its own
  branch. When it imports and reads the live store (``source.kind == "store"``), this adapter only maps each record to
  a lane (``source = "cio_prospect"``). A shadow build is not read: switching Watch onto it is an operator decision.
* **Until then, an interim adapter** builds the same shape from today's sources, and every payload says so
  (``interim = True``, ``source_label = INTERIM_LABEL``):

  - conviction + factor components: the CIO opportunity projection (``cio_opportunity_projection.json`` through
    ``CIOOpportunityStore``; registry domain ``opportunity_assessment``);
  - stage, status, expiry, actionability: the Watch decision standards (``watch_decision.v1``) attached by
    ``watch_intelligence.compose_universe``;
  - Trade AI state: the rockville decision projection already on each Watch card;
  - held: the one Watch held reader (``watch_domains.held_positions(surface="watch")``, positions_store reader
    batch #1, operator 2026-10-22);
  - re-entry: the deterministic re-entry desk rows (``watch_decision.reentry_rows``).

Curation rules (applied here, deterministic, tested): one lane per security; held names are always Manage (a held
name is managed, never entered — 2026-10-22 audit); a non-held name whose signal expired or was invalidated is
Expired; a size cap per lane with the overflow named, never silently dropped; expiry from the decision's
``expires_at``.

``MBI_BEHAVIOR = 0``: nothing here sizes, orders, stops or weights. Reference levels carry ``_ref`` keys so no key is
a ``cio_instrument_record.BEHAVIOR_FIELDS`` name (a test pins it). Changing what is ranked onto Watch is §17: this
module orders rows by lane, then conviction, then the existing decision priority — the order the approved mockup shows.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

SCHEMA = "WatchProspects@v1"
ROW_SCHEMA = "WatchProspectRow@v1"
INTERIM_LABEL = "interim — CIO prospect store not live"
CIO_LABEL = "CIO prospect record · 1 writer"

LANES: tuple[dict[str, str], ...] = (
    {"id": "actionable", "label": "Actionable now", "hint": "can be proposed"},
    {"id": "forming", "label": "Setup forming", "hint": "distance to trigger"},
    {"id": "reentry", "label": "Re-entry near", "hint": "sold, near your level"},
    {"id": "manage", "label": "Manage (held)", "hint": "protect, add, trim"},
    {"id": "expired", "label": "Expired", "hint": "collapsed, auto-closed"},
)
LANE_IDS = tuple(lane["id"] for lane in LANES)
# Size cap per lane. Manage is never capped below the held count in practice (60 > the 23 held names measured
# 2026-10-22); a cap overflow is returned by name so the page can say what it left out.
LANE_CAPS: dict[str, int] = {"actionable": 12, "forming": 25, "reentry": 20, "manage": 60, "expired": 150}

# Re-entry desk intel states (lib/data_broker/reentry_decision_desk.py) that put a sold name in a lane.
REENTRY_READY = frozenset({"READY TO REVIEW"})
REENTRY_NEAR = frozenset({"NEAR ENTRY"})
# Decision rules (config/watch_decision_standards.yaml) whose actionable verdict means "can be proposed now".
PROPOSABLE_RULES = frozenset({"proposal_ready", "plan_ready_strong", "plan_ready", "reentry_confirmed"})
RISK_RULES = frozenset({"held_negative", "held_blocked"})
BLOCKING_TRADE_STATES = frozenset({"DETERMINISTIC_FAIL", "BLOCKED", "AVOID"})

STANCE_FAMILY: dict[str, str] = {}
for _s in ("ADD", "BUY", "BUY_SETUP", "STRONG_BUY", "STRONG BUY", "RE_ENTER", "RE-ENTER", "ACCUMULATE", "ENTER"):
    STANCE_FAMILY[_s] = "positive"
for _s in ("HOLD", "WATCH", "WAIT", "NEUTRAL", "MANAGING", "HUMAN_REVIEW"):
    STANCE_FAMILY[_s] = "neutral"
for _s in ("SELL", "TRIM", "EXIT", "AVOID", "TRIM_REVIEW", "EXIT_REVIEW", "REDUCE", "IGNORE", "STRONG_SELL"):
    STANCE_FAMILY[_s] = "negative"

CONVICTION_STALE_HOURS = 48.0
REENTRY_TTL_HOURS = 96.0  # the re-entry desk's own stale window (reentry_decision_desk.STALE_HOURS)
SURFACES = ("Home", "Trade AI", "Options", "Open Trades", "Telegram")
NOT_JOINED = "not joined (interim)"


# ── small helpers ────────────────────────────────────────────────────────────


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() if t else None


def _up(v: Any) -> str:
    return str(v or "").strip().upper()


def family(stance: Any) -> Optional[str]:
    """positive / neutral / negative for a stance, verdict or synthesis label; None when unknown or empty."""
    return STANCE_FAMILY.get(_up(stance).replace(" ", "_")) or STANCE_FAMILY.get(_up(stance))


def _money(v: Optional[float]) -> str:
    return "—" if v is None else f"${v:,.2f}"


def _pct_away(price: Optional[float], level: Optional[float]) -> Optional[float]:
    if price is None or level is None or price == 0:
        return None
    return round((level - price) / price * 100, 1)


# ── conviction ───────────────────────────────────────────────────────────────


def conviction_block(opp: Optional[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    """Conviction 0–100 with its named components, from the CIO opportunity projection (interim source)."""
    if not opp or opp.get("conviction") is None:
        return {"conviction": None, "components": [], "missing_components": [], "evidence_at": None,
                "stale": False, "source": "cio_opportunity_projection",
                "rank": None, "coverage": None}
    comps = []
    for key, fx in (opp.get("factors") or {}).items():
        if not isinstance(fx, dict):
            continue
        comps.append({"key": key, "label": fx.get("label") or key, "value": _f(fx.get("score")),
                      "weight": _f(fx.get("weight")), "detail": fx.get("detail"), "source": fx.get("source")})
    comps.sort(key=lambda c: -(c["weight"] or 0))
    at = _ts(opp.get("as_of"))
    stale = bool(at and (now - at) > timedelta(hours=CONVICTION_STALE_HOURS))
    return {"conviction": round(float(opp["conviction"]), 1), "components": comps,
            "missing_components": list(opp.get("factors_missing") or []), "evidence_at": _iso(at), "stale": stale,
            "source": "cio_opportunity_projection", "rank": opp.get("rank"), "coverage": _f(opp.get("coverage"))}


# ── conflicts — shown, never resolved (AGENTS.md §26.5) ───────────────────────


def _side(value: Any, source: str, at: Any) -> dict[str, Any]:
    t = _ts(at)
    return {"value": value, "source": source, "at": _iso(t) if t else (str(at) if at else None)}


def conflicts_for(*, symbol: str, card: Optional[dict[str, Any]], opp: Optional[dict[str, Any]], held: bool,
                  held_source: str, reentry: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every disagreement between two inputs about this security, both values, both sources, both times."""
    out: list[dict[str, Any]] = []
    card = card or {}
    dec = card.get("decision") or {}
    stance = _up((opp or {}).get("stance"))
    stance_at = (opp or {}).get("as_of")
    stance_fam = family(stance)
    # 1. CIO stance vs the CIO watch review verdict (cio_review on the card).
    rev = card.get("cio_review") or {}
    verdict = _up(rev.get("verdict"))
    if stance_fam and family(verdict) and family(verdict) != stance_fam:
        out.append({"kind": "stance_vs_review",
                    "summary": f"CIO conviction says {stance}; the CIO watch review says {verdict}",
                    "a": _side(stance, "cio_opportunity_projection", stance_at),
                    "b": _side(verdict, "watchlist CIO review", rev.get("completed_at"))})
    # 2. CIO stance vs the desk's final synthesis.
    syn = _up((dec.get("inputs") or {}).get("synthesis"))
    if stance_fam and family(syn) and family(syn) != stance_fam:
        out.append({"kind": "stance_vs_synthesis",
                    "summary": f"Today's desk synthesis says {syn}; conviction says {stance}",
                    "a": _side(stance, "cio_opportunity_projection", stance_at),
                    "b": _side(syn, "watchlist_final_synthesis", (dec.get("inputs") or {}).get("synthesis_at"))})
    # 3. Ownership: the conviction record's position status vs the held reader.
    pos = str((opp or {}).get("position_status") or "")
    if opp and pos and (pos == "owned") != held:
        out.append({"kind": "ownership",
                    "summary": ("The conviction record treats it as owned; the broker-synced holdings say not held"
                                if pos == "owned" else
                                "Held per the broker-synced holdings; the conviction record treats it as not owned"),
                    "a": _side(pos, "cio_opportunity_projection.position_status", stance_at),
                    "b": _side("held" if held else "not held", held_source, None)})
    # 4. A hard Trade AI check failed while the stance or the re-entry desk says go.
    ts = _up(card.get("trade_ai_state"))
    desk_state = _up((reentry or {}).get("state"))
    if not held and ts in BLOCKING_TRADE_STATES and (
            stance_fam == "positive" or desk_state in REENTRY_READY | REENTRY_NEAR):
        go = stance if stance_fam == "positive" else desk_state
        out.append({"kind": "trade_ai_block",
                    "summary": f"Trade AI {ts.replace('_', ' ').lower()} — not actionable until it passes "
                               f"(the {'stance' if stance_fam == 'positive' else 're-entry desk'} says {go})",
                    "a": _side(go, "cio_opportunity_projection" if stance_fam == "positive" else "reentry_decision_desk",
                               stance_at if stance_fam == "positive" else (reentry or {}).get("price_as_of")),
                    "b": _side(ts, "rockville decision_projection (Trade AI)", card.get("price_as_of"))})
    return out


# ── lanes ────────────────────────────────────────────────────────────────────


def lane_for(*, card: Optional[dict[str, Any]], held: bool, reentry: Optional[dict[str, Any]],
             now: datetime) -> tuple[str, str]:
    """(lane, why) — the one lane this security belongs to. Order matters: held first, then expiry, then go."""
    dec = (card or {}).get("decision") or {}
    desk_state = _up((reentry or {}).get("state"))
    if held:
        return "manage", "Held — managed, never entered"
    status = dec.get("status")
    exp = _ts(dec.get("expires_at"))
    if card is not None and status in ("expired", "invalidated"):
        return "expired", ("Signal invalidated" if status == "invalidated" else "Signal expired")
    if card is not None and exp and exp < now and status != "needs_data":
        return "expired", "Signal expired"
    blocked = _up((card or {}).get("trade_ai_state")) in BLOCKING_TRADE_STATES
    if dec.get("actionable") and dec.get("rule_id") in PROPOSABLE_RULES and not blocked:
        return "actionable", str(dec.get("action_hint") or "Can be proposed")
    if desk_state in REENTRY_READY and not blocked:
        return "actionable", "Re-entry desk: ready to review"
    if desk_state in REENTRY_READY | REENTRY_NEAR or dec.get("category") == "re_entry":
        if card is None:
            at = _ts((reentry or {}).get("price_as_of"))
            if at and now - at > timedelta(hours=REENTRY_TTL_HOURS):
                return "expired", "Re-entry desk price older than 96 h"
        return "reentry", "Sold; near your re-entry level"
    return "forming", "Setup not confirmed yet"


# ── the row ──────────────────────────────────────────────────────────────────


def _levels(card: Optional[dict[str, Any]], reentry: Optional[dict[str, Any]],
            opp: Optional[dict[str, Any]]) -> dict[str, Optional[float]]:
    """Reference levels (never orders) from the freshest source that has them: plan → re-entry desk → conviction."""
    pl = (((card or {}).get("decision") or {}).get("inputs") or {}).get("plan_levels") or {}
    re = reentry or {}
    rr = (opp or {}).get("risk_reward") or {}
    zone = rr.get("entry_zone") if isinstance(rr.get("entry_zone"), list) else [None, None]
    lo = _f(pl.get("entry_low_ref")) or _f(re.get("entry_low_ref")) or _f(zone[0] if zone else None)
    hi = _f(pl.get("entry_high_ref")) or _f(re.get("entry_high_ref")) or _f(zone[1] if len(zone) > 1 else None)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return {
        "entry_low_ref": lo,
        "entry_high_ref": hi,
        "entry_ref": _f(pl.get("limit_ref")) or hi or _f(rr.get("entry_ref")),
        "stop_ref": _f(pl.get("stop_ref")) or _f(re.get("stop_ref")) or _f(rr.get("invalidation_level")),
        "target_ref": _f(pl.get("target_ref")) or _f(re.get("target_ref")) or _f(rr.get("primary_target")),
        "support_ref": _f((card or {}).get("support")),
        "resistance_ref": _f((card or {}).get("resistance")),
    }


def next_trigger(lane: str, *, price: Optional[float], lv: dict[str, Optional[float]],
                 reentry: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The observable level that moves the stage next — a reference, never an order."""
    lo, hi = lv["entry_low_ref"], lv["entry_high_ref"]
    if lane in ("actionable", "reentry", "forming") and lo is not None and hi is not None:
        inside = price is not None and lo <= price <= hi
        away = None if inside else _pct_away(price, hi if (price or 0) > hi else lo)
        src = "re-entry desk" if lane == "reentry" else "entry plan"
        return {"label": f"zone {_money(lo)}–{_money(hi)}" + ("" if away is None else f" ({away:+.1f}%)"),
                "level_ref": hi if (price or 0) > hi else lo, "inside": inside, "distance_pct": away,
                "observed_by": src}
    if lane == "reentry" and (reentry or {}).get("distance_pct") is not None:
        return {"label": f"re-entry level ({float(reentry['distance_pct']):+.1f}%)", "level_ref": None,
                "inside": False, "distance_pct": _f(reentry.get("distance_pct")), "observed_by": "re-entry desk"}
    if lane == "manage" and lv["support_ref"] is not None:
        return {"label": f"support {_money(lv['support_ref'])}", "level_ref": lv["support_ref"], "inside": False,
                "distance_pct": _pct_away(price, lv["support_ref"]), "observed_by": "watch card support"}
    if lane == "forming" and lv["resistance_ref"] is not None:
        return {"label": f"break above {_money(lv['resistance_ref'])}", "level_ref": lv["resistance_ref"],
                "inside": False, "distance_pct": _pct_away(price, lv["resistance_ref"]),
                "observed_by": "watch card resistance"}
    return {"label": "—", "level_ref": None, "inside": False, "distance_pct": None, "observed_by": None}


def next_step(lane: str, *, symbol: str, conflicts: list[dict[str, Any]], stance: str, conviction: Optional[float],
              decision: dict[str, Any], lv: dict[str, Optional[float]], price: Optional[float],
              rsi: Optional[float]) -> dict[str, Any]:
    """ONE next step. Protection comes first for a held name at risk; a conflict comes before any go action."""
    sym = symbol.upper()
    open_trades = f"/v3/trading?tab=Open+Trades&symbol={sym}"
    if lane == "expired":
        return {"kind": "none", "label": "—", "reason": "Signal closed; it returns when new evidence arrives.",
                "href": None}
    if lane == "manage" and (decision.get("rule_id") in RISK_RULES or family(stance) == "negative"):
        return {"kind": "protect", "label": "Protect first", "href": open_trades,
                "reason": "A risk rule fired for this held name (a sell/trim synthesis or a Trade AI block). "
                          "Open Trades shows its stop and protection."}
    if conflicts:
        return {"kind": "resolve_conflict", "label": "Resolve conflict", "href": None,
                "reason": "Two inputs disagree. The page shows both; ask the CIO to review rather than pick one."}
    if lane == "actionable":
        seed = {"entry_ref": lv["entry_ref"], "stop_ref": lv["stop_ref"], "target_ref": lv["target_ref"]}
        return {"kind": "propose", "label": "Propose", "href": None, "seed": seed,
                "reason": "Opens the existing Propose form. You size it; it goes to Proposals for your approval."}
    if lane in ("forming", "reentry"):
        seed = {"price": price, "rsi": rsi, "entry_low_ref": lv["entry_low_ref"],
                "entry_high_ref": lv["entry_high_ref"] or lv["resistance_ref"]}
        return {"kind": "set_alert", "label": "Set alert", "href": None, "seed": seed,
                "reason": "Arms an advisory Watch alert at the trigger (price and RSI). Notifications only."}
    if lane == "manage" and family(stance) == "positive":
        return {"kind": "review_add", "label": "Review add-on", "href": f"/v3/watch/intelligence/{sym}",
                "reason": "The CIO stance on this held name is ADD; review the add-on idea or leave it."}
    if lane == "manage" and conviction is not None and conviction < 50:
        return {"kind": "decide", "label": "Decide hold/exit", "href": open_trades,
                "reason": "Weak conviction on a held name: decide hold with a stop, hedge or exit on Open Trades."}
    return {"kind": "open_position", "label": "View position", "href": open_trades,
            "reason": "Held; nothing argues for a change today. Open Trades shows the position."}


def surfaces_for(*, card: Optional[dict[str, Any]], opp: Optional[dict[str, Any]], held: bool,
                 held_source: str, reentry: Optional[dict[str, Any]], interim: bool) -> list[dict[str, Any]]:
    """What each surface shows for this security today. Interim: only the sources this adapter reads are joined;
    the rest say so instead of guessing."""
    ts = _up((card or {}).get("trade_ai_state"))
    rows = [
        {"surface": "Home", "value": NOT_JOINED, "source": None, "joined": False},
        {"surface": "Trade AI", "value": ts.replace("_", " ") if ts else "—",
         "source": "rockville decision_projection", "joined": bool(card)},
        {"surface": "Options", "value": NOT_JOINED, "source": None, "joined": False},
        {"surface": "Open Trades", "value": "held" if held else "not held", "source": held_source, "joined": True},
        {"surface": "Telegram", "value": NOT_JOINED, "source": None, "joined": False},
        {"surface": "Opportunities (CIO curator)",
         "value": (f"#{opp.get('rank')} · {float(opp['conviction']):.0f} · {_up(opp.get('stance'))}"
                   if opp and opp.get("conviction") is not None and opp.get("rank") else
                   (f"{float(opp['conviction']):.0f} · {_up(opp.get('stance'))} (unranked)"
                    if opp and opp.get("conviction") is not None else "not in the curator universe")),
         "source": "cio_opportunity_projection", "joined": True},
        {"surface": "Re-entry desk", "value": (_up((reentry or {}).get("state")) or "—").title() if reentry else "—",
         "source": "reentry_decision_desk", "joined": True},
    ]
    if not interim:
        for r in rows:
            r["joined"] = True
    return rows


def whats_missing(*, card: Optional[dict[str, Any]], opp: Optional[dict[str, Any]], conv: dict[str, Any],
                  lv: dict[str, Optional[float]], lane: str, identity: dict[str, Any]) -> list[str]:
    out: list[str] = []
    dec = (card or {}).get("decision") or {}
    if conv["conviction"] is None:
        out.append("No CIO conviction yet — not in the curator's universe")
    elif conv["stale"]:
        out.append(f"Conviction older than {int(CONVICTION_STALE_HOURS)} h")
    for k in conv["missing_components"]:
        out.append(f"{str(k).replace('_', ' ').capitalize()} factor not scored")
    if card is None:
        out.append("Not on the Watch universe — seen only by the re-entry desk")
    elif dec.get("status") == "needs_data":
        out.append("No fresh entry plan, synthesis or review")
    if lane in ("actionable", "forming") and (lv["entry_low_ref"] is None or lv["stop_ref"] is None):
        out.append("No complete entry plan (zone and invalidation)")
    blocked = dec.get("actionable_blocked_by")
    if blocked:
        out.append(f"Trade AI {str(blocked).replace('_', ' ').lower()} must clear")
    if not identity.get("confirmed"):
        out.append("Identity unresolved (no CONFIRMED security GUID)")
    return out


def build_row(symbol: str, *, card: Optional[dict[str, Any]], opp: Optional[dict[str, Any]], held: bool,
              held_source: str, reentry: Optional[dict[str, Any]], identity: Optional[dict[str, Any]],
              now: datetime, interim: bool = True) -> dict[str, Any]:
    sym = symbol.upper()
    identity = identity or {"security_guid": None, "issuer_guid": None, "status": None, "confirmed": False}
    dec = (card or {}).get("decision") or {}
    lane, why = lane_for(card=card, held=held, reentry=reentry, now=now)
    conv = conviction_block(opp, now=now)
    stance = _up((opp or {}).get("stance")) or None
    conflicts = conflicts_for(symbol=sym, card=card, opp=opp, held=held, held_source=held_source, reentry=reentry)
    price = _f((card or {}).get("last")) if card else _f((reentry or {}).get("price"))
    rsi = _f((card or {}).get("rsi")) if card else _f((reentry or {}).get("rsi"))
    lv = _levels(card, reentry, opp)
    trig = next_trigger(lane, price=price, lv=lv, reentry=reentry)
    step = next_step(lane, symbol=sym, conflicts=conflicts, stance=stance or "", conviction=conv["conviction"],
                     decision=dec, lv=lv, price=price, rsi=rsi)
    evidence = [t for t in (_ts(dec.get("evidence_at")), _ts(conv["evidence_at"]),
                            _ts((reentry or {}).get("price_as_of"))) if t]
    exp = _ts(dec.get("expires_at"))
    if exp is None and reentry and not card:
        at = _ts(reentry.get("price_as_of"))
        exp = at + timedelta(hours=REENTRY_TTL_HOURS) if at else None
    reason_bits = [why]
    if (opp or {}).get("stance_rationale"):
        reason_bits.append(str(opp["stance_rationale"]))
    elif (reentry or {}).get("reason") and lane in ("reentry", "actionable"):
        reason_bits.append(str(reentry["reason"]))
    elif (card or {}).get("operator_meaning"):
        reason_bits.append(str(card["operator_meaning"]))
    return {
        "schema": ROW_SCHEMA,
        "symbol": sym,
        "security_guid": identity.get("security_guid"),
        "issuer_guid": identity.get("issuer_guid"),
        "identity_status": identity.get("status"),
        "company": (card or {}).get("company") or (opp or {}).get("company") or (reentry or {}).get("company"),
        "lane": lane,
        "stage": {"actionable": "actionable", "forming": "setup_forming", "reentry": "re_entry", "manage": "held",
                  "expired": "expired"}[lane],
        "why": why,
        "summary": ". ".join(b.strip().rstrip(".") for b in reason_bits) + ".",
        "conviction": conv["conviction"],
        "conviction_rank": conv["rank"],
        "conviction_coverage": conv["coverage"],
        "conviction_components": conv["components"],
        "conviction_missing": conv["missing_components"],
        "conviction_source": conv["source"],
        "conviction_as_of": conv["evidence_at"],
        "conviction_stale": conv["stale"],
        "stance": stance,
        "stance_family": family(stance),
        "whats_missing": whats_missing(card=card, opp=opp, conv=conv, lv=lv, lane=lane, identity=identity),
        "conflicts": conflicts,
        "next_trigger": trig,
        "next_action": step,
        "levels_ref": lv,
        "price": price,
        "price_as_of": (card or {}).get("price_as_of") or (reentry or {}).get("price_as_of"),
        "rsi": rsi,
        "held": held,
        "trade_ai_state": _up((card or {}).get("trade_ai_state")) or None,
        "decision": {k: dec.get(k) for k in ("rule_id", "category_label", "priority", "priority_score", "status",
                                               "actionable", "actionable_blocked_by", "action_hint")} if dec else None,
        "reentry_state": _up((reentry or {}).get("state")) or None,
        "surfaces": surfaces_for(card=card, opp=opp, held=held, held_source=held_source, reentry=reentry,
                                 interim=interim),
        "evidence_at": _iso(max(evidence)) if evidence else None,
        "expires_at": _iso(exp),
        "stale": bool(exp and exp < now),
    }


# ── curation ─────────────────────────────────────────────────────────────────


def _sort_key(r: dict[str, Any]) -> tuple:
    conv = r.get("conviction")
    pscore = ((r.get("decision") or {}).get("priority_score")) or 0.0
    return (conv is None, -(conv or 0.0), -float(pscore), r["symbol"])


def curate(rows: Iterable[dict[str, Any]], caps: Optional[dict[str, int]] = None) -> dict[str, dict[str, Any]]:
    """One lane per security, sorted by conviction then decision priority, capped per lane (overflow named)."""
    caps = caps or LANE_CAPS
    seen: set[str] = set()
    by_lane: dict[str, list[dict[str, Any]]] = {k: [] for k in LANE_IDS}
    for r in rows:
        if r["symbol"] in seen:
            continue  # one membership: the first (highest-precedence) row wins; callers pass one row per symbol
        seen.add(r["symbol"])
        by_lane[r["lane"]].append(r)
    out: dict[str, dict[str, Any]] = {}
    for lane in LANES:
        items = sorted(by_lane[lane["id"]], key=_sort_key)
        cap = int(caps.get(lane["id"], len(items)))
        out[lane["id"]] = {**lane, "count": len(items), "cap": cap, "items": items[:cap],
                           "overflow": [r["symbol"] for r in items[cap:]]}
    return out


# ── compose ──────────────────────────────────────────────────────────────────


def build_watch_prospects(*, cards: list[dict[str, Any]], opportunities: dict[str, dict[str, Any]],
                          reentry: dict[str, dict[str, Any]], held: set[str], held_source: str,
                          identities: Optional[dict[str, dict[str, Any]]] = None,
                          held_detail: Optional[dict[str, Any]] = None, opp_as_of: Any = None,
                          now: Optional[datetime] = None, caps: Optional[dict[str, int]] = None) -> dict[str, Any]:
    """Pure: today's sources → the WatchProspects@v1 payload (interim adapter)."""
    now = now or datetime.now(timezone.utc)
    identities = identities or {}
    by_sym: dict[str, dict[str, Any]] = {}
    for c in cards:
        sym = _up(c.get("symbol"))
        if sym and sym not in by_sym:
            by_sym[sym] = c
    symbols = list(by_sym)
    # Re-entry candidates outside the Watch universe still belong on the page (2026-10-22: 13 NEAR/READY desk names
    # were not Watch cards).
    for sym, r in reentry.items():
        if sym not in by_sym and not r.get("held") and sym not in held and \
                _up(r.get("state")) in REENTRY_READY | REENTRY_NEAR:
            symbols.append(sym)
    rows = [build_row(s, card=by_sym.get(s), opp=opportunities.get(s), held=s in held, held_source=held_source,
                      reentry=reentry.get(s), identity=identities.get(s), now=now, interim=True)
            for s in symbols]
    lanes = curate(rows, caps)
    n_conf = sum(len(r["conflicts"]) for r in rows if r["lane"] != "expired")
    return {
        "ok": True,
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "source": "interim_adapter",
        "interim": True,
        "source_label": INTERIM_LABEL,
        "sources": {
            "conviction": {"store": "data/cio/cio_opportunity_projection.json", "domain": "opportunity_assessment",
                           "as_of": opp_as_of},
            "stage": {"projection": "watch_intelligence.compose_universe", "standards": "watch_decision.v1"},
            "trade_ai": {"projection": "rockville decision_projection"},
            "held": {"reader": "watch_domains.held_positions(surface='watch')", "source": held_source,
                     "as_of": (held_detail or {}).get("as_of"), "stale": (held_detail or {}).get("stale")},
            "reentry": {"projection": "reentry_decision_desk", "rows": len(reentry)},
        },
        "curation": {"one_membership": True, "caps": dict(caps or LANE_CAPS),
                     "sort_order": "lane, then conviction (high first), then decision priority",
                     "expiry": "a non-held name whose decision expired or was invalidated is Expired; held names "
                               "stay in Manage"},
        "lanes": [lanes[k] for k in LANE_IDS],
        "counts": {k: lanes[k]["count"] for k in LANE_IDS} | {"conflicts": n_conf, "total": len(rows)},
        "authority": "READ_ONLY_ADVISORY",
        "mbi_behavior": 0,
        "provider_calls": 0,
    }


# ── the CIO prospect projection, when it is live ─────────────────────────────
#
# lib/data_broker/cio_prospect.get_prospects() (branch feat/cio-prospect-p0-p1-20261022) returns
# {prospects: [...], source: {kind: "store" | "shadow"}, store_status: {live}}. Watch reads it only when the store is
# live (kind "store"): a shadow build is not the record of truth, and moving Watch onto it is the P3(b) reader batch
# (CIO_PROSPECT_DATA_FOUNDATION.md §7, an operator decision). Record shapes follow cio_prospect_builder.assemble:
# conflicts {field, values: [{value, source, at}, {…}], resolved}, conviction_components {name: {value, weight, source,
# evidence_at, detail}}, next_trigger {kind: reference_level | evidence, entry_zone, entry_ref, invalidation_level,
# observed_by}. The ONE next step is derived with the same next_step() the interim adapter uses.

_STAGE_TO_LANE = {"actionable": "actionable", "proposed": "actionable", "setup_forming": "forming",
                  "watching": "forming", "re_entry": "reentry", "held": "manage", "exit": "manage"}


def _map_conflict(c: dict[str, Any]) -> dict[str, Any]:
    """cio_prospect conflict → the page's {kind, summary, a, b}; both sides kept verbatim."""
    if "a" in c and "b" in c:
        return c
    vals = list(c.get("values") or []) + [{}, {}]
    a, b = vals[0] or {}, vals[1] or {}
    kind = str(c.get("field") or c.get("kind") or "conflict")
    summary = c.get("summary") or (f"{kind.replace('_', ' ')}: {a.get('value')} ({a.get('source')}) vs "
                                   f"{b.get('value')} ({b.get('source')})")
    return {"kind": kind, "summary": str(summary), "note": c.get("note"),
            "a": {"value": a.get("value"), "source": a.get("source"), "at": a.get("at")},
            "b": {"value": b.get("value"), "source": b.get("source"), "at": b.get("at")}}


def _trigger_from_record(nt: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Optional[float]]]:
    zone = nt.get("entry_zone") if isinstance(nt.get("entry_zone"), list) else [None, None]
    lo = _f(zone[0] if zone else None)
    hi = _f(zone[1] if len(zone) > 1 else None)
    inv = _f(nt.get("invalidation_level"))
    lv = {"entry_low_ref": lo, "entry_high_ref": hi, "entry_ref": _f(nt.get("entry_ref")) or hi, "stop_ref": inv,
          "target_ref": _f(nt.get("target_ref")), "support_ref": None, "resistance_ref": None}
    if lo is not None and hi is not None:
        label = f"zone {_money(min(lo, hi))}–{_money(max(lo, hi))}"
    elif nt.get("label"):
        label = str(nt["label"])
    elif inv is not None:
        label = f"invalidation {_money(inv)}"
    elif nt.get("what"):
        label = f"needs {nt['what']}"
    else:
        label = "—"
    return ({"label": label, "level_ref": lo if lo is not None else inv, "inside": False, "distance_pct": None,
             "observed_by": nt.get("observed_by")}, lv)


def from_cio_prospect(records: list[dict[str, Any]], *, now: Optional[datetime] = None,
                      caps: Optional[dict[str, int]] = None) -> dict[str, Any]:
    """Map cio_prospect records (DATA_DICTIONARY.md "CIOProspect") to lanes. No judgment is added here: the lane
    comes from the record's stage (expired by its expires_at), the step from the same next_step() rules."""
    now = now or datetime.now(timezone.utc)
    rows = []
    for rec in records:
        sym = _up(rec.get("symbol"))
        if not sym:
            continue
        stage = str(rec.get("stage") or "watching")
        exp = _ts(rec.get("expires_at"))
        lane = _STAGE_TO_LANE.get(stage, "forming")
        if lane != "manage" and exp and exp < now:
            lane = "expired"
        comps = rec.get("conviction_components") or {}
        comp_rows = []
        for k, v in (comps.items() if isinstance(comps, dict) else []):
            v = v if isinstance(v, dict) else {"value": v}
            comp_rows.append({"key": k, "label": k.replace("_", " ").capitalize(), "value": _f(v.get("value")),
                              "weight": _f(v.get("weight")), "detail": v.get("detail"), "source": v.get("source")})
        comp_rows.sort(key=lambda c: -(c["weight"] or 0))
        conflicts = [_map_conflict(c) for c in (rec.get("conflicts") or []) if isinstance(c, dict)]
        stance = _up(rec.get("stance")) or None
        trig, lv = _trigger_from_record(rec.get("next_trigger") or {})
        held = stage in ("held", "exit") or bool((rec.get("position_ref") or {}).get("held"))
        conv = _f(rec.get("conviction"))
        step = next_step(lane, symbol=sym, conflicts=conflicts, stance=stance or "", conviction=conv,
                         decision={}, lv=lv, price=None, rsi=None)
        na = rec.get("next_action") or {}
        why = str((rec.get("stage_evidence") or {}).get("state") or stage.replace("_", " "))
        rows.append({
            "schema": ROW_SCHEMA, "symbol": sym, "security_guid": rec.get("security_guid"),
            "issuer_guid": rec.get("issuer_guid"), "identity_status": rec.get("identity_status") or "CONFIRMED",
            "company": rec.get("company"), "lane": lane, "stage": stage, "why": why,
            "summary": str(rec.get("cc_narrative") or (f"{na.get('who')}: {na.get('what')}" if na.get("what") else why)),
            "conviction": conv, "conviction_rank": rec.get("shadow_rank"), "conviction_coverage": None,
            "conviction_components": comp_rows, "conviction_missing": [], "conviction_source": "cio_prospect",
            "conviction_as_of": rec.get("evidence_at"), "conviction_stale": bool(exp and exp < now),
            "stance": stance, "stance_family": family(stance),
            "whats_missing": [str(x) for x in (rec.get("whats_missing") or [])],
            "conflicts": conflicts, "next_trigger": trig, "next_action": step, "levels_ref": lv,
            "price": None, "price_as_of": None, "rsi": None, "held": held,
            "trade_ai_state": None, "decision": None, "reentry_state": None,
            "surfaces": [{"surface": s, "value": "same record", "source": "cio_prospect", "joined": True}
                         for s in SURFACES],
            "evidence_at": rec.get("evidence_at"), "expires_at": rec.get("expires_at"), "stale": bool(exp and exp < now),
        })
    lanes = curate(rows, caps)
    return {
        "ok": True, "schema": SCHEMA, "generated_at": now.isoformat(), "source": "cio_prospect", "interim": False,
        "source_label": CIO_LABEL, "sources": {"prospect": {"projection": "cio_prospect", "kind": "store"}},
        "curation": {"one_membership": True, "caps": dict(caps or LANE_CAPS),
                     "sort_order": "lane, then conviction (high first)", "expiry": "expires_at from the record"},
        "lanes": [lanes[k] for k in LANE_IDS],
        "counts": {k: lanes[k]["count"] for k in LANE_IDS} | {
            "conflicts": sum(len(r["conflicts"]) for r in rows if r["lane"] != "expired"), "total": len(rows)},
        "authority": "READ_ONLY_ADVISORY", "mbi_behavior": 0, "provider_calls": 0,
    }


# ── live gather (the HTTP path) ──────────────────────────────────────────────

_CACHE: dict[str, Any] = {"at": 0.0, "val": None}
CACHE_S = 60.0


def _db_query() -> Optional[Callable[..., Any]]:
    try:
        from db_adapter import _execute
    except Exception:  # noqa: BLE001
        return None
    return lambda sql, params=None, fetch="all": _execute(sql, params, fetch=fetch)


def _cio_prospect_records() -> tuple[Optional[list[dict[str, Any]]], str]:
    """(records, status). Records only when the cio_prospect projection exists AND reads the live store;
    status is "absent" (module not on this build), "shadow" / "not_live" (store not live), "error" or "store"."""
    try:
        from lib.data_broker import cio_prospect as cp  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — not merged yet
        return None, "absent"
    fn: Optional[Callable[..., Any]] = getattr(cp, "get_prospects", None)
    if fn is None:
        return None, "absent"
    try:
        out = fn(db_query=_db_query())
    except Exception:  # noqa: BLE001
        return None, "error"
    if not isinstance(out, dict):
        return None, "error"
    kind = str((out.get("source") or {}).get("kind") or "")
    live = bool((out.get("store_status") or {}).get("live"))
    recs = out.get("prospects")
    if live and kind == "store" and isinstance(recs, list) and recs:
        return list(recs), "store"
    return None, "shadow" if kind == "shadow" else "not_live"


def _identities(symbols: list[str]) -> dict[str, dict[str, Any]]:
    try:
        from lib import identity_registry as ir
    except Exception:  # noqa: BLE001
        return {}
    try:
        doc = ir.load_cached()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict[str, Any]] = {}
    for s in symbols:
        ent = ir.lookup_symbol(doc, s) or {}
        if not ent:
            continue
        st = str(ent.get("identity_status") or "")
        out[s] = {"security_guid": ent.get("security_guid") or ent.get("subject_guid"),
                  "issuer_guid": ent.get("issuer_guid"), "status": st or None, "confirmed": st == "CONFIRMED"}
    return out


def list_watch_prospects(query: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-prospects — the record the Watch page reads (cached 60 s)."""
    now_m = time.monotonic()
    fresh = str((query or {}).get("fresh") or "") in ("1", "true")
    if not fresh and _CACHE["val"] is not None and now_m - _CACHE["at"] < CACHE_S:
        return _CACHE["val"]
    recs, cp_status = _cio_prospect_records()
    if recs:
        out = from_cio_prospect(recs)
    else:
        from lib.data_broker import watch_decision as wd
        from lib.data_broker.watch_intelligence import compose_universe

        composed = compose_universe(view="all", page_size=100)
        cards = [i.get("card") or {} for i in composed["items"]]
        try:
            try:
                from scripts.lib.cio_opportunity_store import CIOOpportunityStore
            except ImportError:  # pragma: no cover
                from lib.cio_opportunity_store import CIOOpportunityStore  # type: ignore
            proj = CIOOpportunityStore().read_projection() or {}
        except Exception:  # noqa: BLE001
            proj = {}
        opps = {_up(k): v for k, v in (proj.get("items") or {}).items() if isinstance(v, dict)}
        desk = wd.reentry_rows()
        syms = [_up(c.get("symbol")) for c in cards] + list(desk)
        out = build_watch_prospects(cards=cards, opportunities=opps, reentry=desk, held=set(composed["held"]),
                                    held_source=composed["held_source"], held_detail=composed["held_detail"],
                                    identities=_identities(syms), opp_as_of=proj.get("as_of"))
    out["cio_prospect_status"] = cp_status
    out["data_broker"] = {"package": "scripts/lib/data_broker", "projection": "watch_prospects",
                          "catalog": "/api/v3/data-broker", "read_only": True, "provider_calls": 0}
    _CACHE.update(at=now_m, val=out)
    return out
