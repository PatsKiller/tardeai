"""Where leadership is moving: advisory stances from the leadership detector (rotation advisor).

Operator 2026-10-31, verbatim: "And on a larger note, if stuff is turning for the long term, I should have advisement of
what I should be getting into".

Reuses, never re-implements: the leadership classes come from ``leadership.py``; candidate names and their conviction
come from the CIO's own opportunity projection (``data/cio/cio_opportunity_projection.json``, written by
``scripts/cio_opportunity_curator.py``); the entry gate is the existing ``market_risk_gate`` (entries held at ORANGE+).

Stances use the CIO's existing vocabulary only:

* ``LEADERSHIP_CONFIRMED`` group: its ETF and qualifying names are ``ADD`` candidates (``HOLD_CASH_FOR`` the group while
  market risk is ORANGE or RED);
* ``LEADERSHIP_EMERGING``: ``WATCH``;
* ``LEADERSHIP_FADING``: ``AVOID`` new entries, ``WATCH_CLOSELY`` where the book already holds the exposure;
* ``BOUNCE_ONLY``: ``WATCH`` with the reason "bounce only".

Advisory only (``MBI_BEHAVIOR = 0``): a stance, its reasons, catalysts and book overlap. Never a size, weight, price,
order or stop; ``assert_no_behavior_fields`` and the shared ``_SIZING_TEXT`` guard run on every record and the card.
The card is rendered deterministically. LLM narration is off (``narration: off``) until the strict validator ships.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from scripts.lib.market_risk import contract as c

ADVICE_SCHEMA = "RotationAdvice@v1"
PRODUCER = "market_risk_rotation"
MESSAGE_CLASS = "market_risk"

SECTOR_TO_GROUP = {
    "technology": "tech",
    "information technology": "tech",
    "communication services": "comm",
    "communications": "comm",
    "consumer cyclical": "discretionary",
    "consumer discretionary": "discretionary",
    "consumer defensive": "staples",
    "consumer staples": "staples",
    "healthcare": "healthcare",
    "health care": "healthcare",
    "utilities": "utilities",
    "energy": "energy",
    "financial services": "financials",
    "financials": "financials",
    "industrials": "industrials",
    "basic materials": "materials",
    "materials": "materials",
    "real estate": "real_estate",
}


def _cfg(policy: dict[str, Any]) -> dict[str, Any]:
    return dict((policy or {}).get("leadership") or {})


def group_of(item: dict[str, Any], groups: dict[str, Any]) -> list[str]:
    """The leadership groups a name belongs to: its sector group, plus any theme whose symbol list names it."""
    out = []
    g = SECTOR_TO_GROUP.get(str(item.get("sector") or "").strip().lower())
    if g:
        out.append(g)
    sym = str(item.get("symbol") or "").upper()
    for key, rec in groups.items():
        if sym in {s.upper() for s in rec.get("symbols") or []} and key not in out:
            out.append(key)
    return out


def load_candidates(path: Path) -> list[dict[str, Any]]:
    """Rankable names from the CIO opportunity projection (read-only). Missing file -> [] (the card says so)."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = doc.get("items") or {}
    rows = items.values() if isinstance(items, dict) else items
    out = []
    for it in rows:
        if not isinstance(it, dict) or not it.get("symbol"):
            continue
        out.append(
            {
                "symbol": str(it["symbol"]).upper(),
                "sector": it.get("sector"),
                "conviction": it.get("conviction"),
                "stance": it.get("stance"),
                "rankable": it.get("rankable", True),
                "type": it.get("type"),
                "as_of": it.get("as_of") or doc.get("as_of"),
            }
        )
    return out


def book_by_group(holdings: list[dict[str, Any]], groups: dict[str, Any], min_value: float) -> dict[str, list[str]]:
    """{group: [symbols the book already holds there]}. Residual / fractional lots below ``min_value`` are ignored."""
    out: dict[str, list[str]] = {}
    for h in holdings or []:
        try:
            value = float(h.get("market_value") or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value < min_value:
            continue
        for g in group_of(h, groups):
            out.setdefault(g, [])
            if h["symbol"] not in out[g]:
                out[g].append(h["symbol"])
    return out


def advise(
    block: dict[str, Any],
    *,
    policy: dict[str, Any],
    tier: Optional[str],
    candidates: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    earnings: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The advisory payload: per group a stance with reasons, vehicles (ETF + ranked names), catalysts and overlap."""
    cfg = _cfg(policy)
    groups = (block or {}).get("groups") or {}
    gated = str(tier or "").upper() in {t.upper() for t in cfg.get("entry_gate_tiers") or ["ORANGE", "RED"]}
    floor = float(cfg.get("candidate_min_conviction") or 55)
    per = int(cfg.get("candidates_per_group") or 5)
    held = book_by_group(holdings, groups, float(cfg.get("residual_min_value_usd") or 1000))
    earnings = earnings or {}
    recs: dict[str, dict[str, Any]] = {}
    for key, g in groups.items():
        cls = g.get("class")
        if cls not in ("LEADERSHIP_CONFIRMED", "LEADERSHIP_EMERGING", "LEADERSHIP_FADING", "BOUNCE_ONLY"):
            continue
        reasons = list(g.get("evidence") or [])
        overlap = held.get(key) or []
        if cls == "LEADERSHIP_CONFIRMED":
            stance = "HOLD_CASH_FOR" if gated else "ADD"
            if gated:
                reasons.append(f"entries held while market risk is {str(tier).upper()} (market_risk_gate)")
        elif cls == "LEADERSHIP_EMERGING":
            stance = "WATCH"
        elif cls == "LEADERSHIP_FADING":
            stance = "WATCH_CLOSELY" if overlap else "AVOID"
        else:
            stance = "WATCH"
            reasons.append("bounce only: the longer relative trend is still down")
        names = []
        if cls in ("LEADERSHIP_CONFIRMED", "LEADERSHIP_EMERGING"):
            pool = [
                x
                for x in candidates
                if x.get("rankable", True)
                and key in group_of(x, groups)
                and isinstance(x.get("conviction"), (int, float))
                and float(x["conviction"]) >= floor
            ]
            pool.sort(key=lambda x: (-float(x["conviction"]), x["symbol"]))
            for x in pool[:per]:
                names.append(
                    {
                        "symbol": x["symbol"],
                        "cio_conviction": x["conviction"],
                        "cio_stance": x.get("stance"),
                        "earnings": earnings.get(x["symbol"]),
                        "already_held": x["symbol"] in overlap,
                        "as_of": x.get("as_of"),
                    }
                )
        rec = {
            "group": key,
            "label": g.get("label"),
            "class": cls,
            "confidence": g.get("confidence"),
            "horizon": g.get("horizon"),
            "macro_aligned": g.get("macro_aligned"),
            "stance": stance,
            "reasons": reasons,
            "vehicles": list(g.get("symbols") or []) if g.get("kind") == "sector" else [],
            "names": names,
            "book_overlap": overlap,
        }
        if overlap and cls in ("LEADERSHIP_CONFIRMED", "LEADERSHIP_EMERGING"):
            rec["reasons"].append("you already hold this exposure through " + ", ".join(overlap))
        recs[key] = rec
    payload = {
        "schema": ADVICE_SCHEMA,
        "as_of": (block or {}).get("as_of"),
        "tier": tier,
        "macro": (block or {}).get("macro"),
        "groups": recs,
        "candidates_available": bool(candidates),
        "narration": "off",
    }
    c.assert_no_behavior_fields(payload)
    _check_text(payload)
    return payload


def _check_text(payload: dict[str, Any]) -> None:
    from scripts.lib import buy_ready_cio_review as br

    blob = json.dumps(payload, default=str)
    if br._SIZING_TEXT.search(blob):  # noqa: SLF001 — the shared sizing-text guard, used as-is
        raise ValueError("sizing text in rotation advice")


ORDER = ("LEADERSHIP_CONFIRMED", "LEADERSHIP_EMERGING", "LEADERSHIP_FADING", "BOUNCE_ONLY")
HEAD = {
    "LEADERSHIP_CONFIRMED": "Confirmed leaders",
    "LEADERSHIP_EMERGING": "Emerging",
    "LEADERSHIP_FADING": "Fading",
    "BOUNCE_ONLY": "Bounce only",
}


def render_card(payload: dict[str, Any]) -> str:
    """Deterministic phone card. No size, weight, price, order or stop."""
    lines = [f"🧭 WHERE LEADERSHIP IS MOVING · as of {payload.get('as_of')}"]
    groups = payload.get("groups") or {}
    if not groups:
        lines.append("No group shows a durable change of leadership.")
    for cls in ORDER:
        rows = [r for r in groups.values() if r["class"] == cls]
        if not rows:
            continue
        lines.append(f"{HEAD[cls]}:")
        for r in sorted(rows, key=lambda r: -(r.get("confidence") or 0)):
            hz = f" · {r['horizon']}" if r.get("horizon") else ""
            lines.append(f"• {r['label']} — CIO {r['stance']}{hz} (confidence {r.get('confidence')})")
            lines.append(f"  {r['reasons'][0]}" if r.get("reasons") else "")
            if r.get("names"):
                named = ", ".join(
                    f"{n['symbol']} ({n['cio_conviction']:.0f}{', earnings ' + n['earnings'] if n.get('earnings') else ''})"
                    for n in r["names"]
                )
                lines.append(f"  Names by CIO conviction: {named}")
            if r.get("book_overlap"):
                lines.append("  Already held: " + ", ".join(r["book_overlap"]))
    tr = payload.get("track_record") or {}
    if tr:
        lines.append(
            f"Track record 2016-2025: confirmed leaders beat SPY over 60 sessions {tr.get('confirmed_hit_60')} of the "
            f"time (n={tr.get('confirmed_n_60')}) vs {tr.get('baseline_hit_60')} for plain momentum; {tr.get('verdict')}."
        )
    if payload.get("tier"):
        lines.append(f"Market risk: {payload['tier']}.")
    lines.append("Advisory. Your decision; no order, size, weight or price is implied.")
    text = "\n".join(x for x in lines if x)
    from scripts.lib import buy_ready_cio_review as br

    if br._SIZING_TEXT.search(text):  # noqa: SLF001
        raise ValueError("sizing text in rotation card")
    return text


def signature(payload: dict[str, Any]) -> str:
    """Leadership-state signature: a card is due when it changes (or weekly via dedupe)."""
    return "|".join(sorted(f"{k}:{v['class']}" for k, v in (payload.get("groups") or {}).items()))


def cio_facts(payload: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Ask-the-CIO facts block; every field carries as_of through the payload."""
    if not isinstance(payload, dict):
        return {"state": "not_evaluated"}
    return {
        "as_of": payload.get("as_of"),
        "groups": {
            k: {x: v.get(x) for x in ("label", "class", "stance", "horizon", "confidence", "reasons", "book_overlap")}
            | {"names": [n["symbol"] for n in v.get("names") or []]}
            for k, v in (payload.get("groups") or {}).items()
        },
    }


def send_card(payload: dict[str, Any], policy: dict[str, Any]) -> bool:
    """P2 card through the single chokepoint ``telegram_alert.send_telegram``. Errors propagate to the caller."""
    from telegram_alert import send_telegram

    cfg = _cfg(policy)
    return bool(
        send_telegram(
            render_card(payload),
            priority=str(cfg.get("card_priority") or "P2"),
            dedupe_minutes=int(cfg.get("card_dedupe_minutes") or 10080),
            producer=PRODUCER,
            message_class=MESSAGE_CLASS,
        )
    )
