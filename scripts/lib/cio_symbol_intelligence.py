"""Symbol Intelligence Object + Telegram Investment Intelligence Card (Phase A).

Shared narrative layer for CIO product alerts (and later CC / freeform).
READ_ONLY_ADVISORY — never invent prices, zones, or theses.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SymbolIntelligenceObject@v1"
CARD_SCHEMA = "InvestmentIntelligenceCard@v1"

_KIND_HEADLINE = {
    "reentry_added": "Added To Reentry Watch",
    "reentry_upgrade": "Reentry Status Upgraded",
    "reentry_downgrade": "Reentry Status Downgraded",
    "reentry_removed": "Removed From Reentry Book",
    "opportunity_added": "Added To Opportunity Book",
    "opportunity_removed": "Removed From Opportunity Book",
    "opportunity_rank_change": "Opportunity Rank Changed",
    "action_added": "Action Book Update",
    "action_removed": "Action Book Update",
}

_KIND_VERB = {
    "reentry_added": "Added to Reentry",
    "reentry_removed": "Removed from Reentry",
    "reentry_upgrade": "Reentry upgraded",
    "reentry_downgrade": "Reentry downgraded",
    "opportunity_added": "Added to Opportunity",
    "opportunity_removed": "Removed from Opportunity",
    "opportunity_rank_change": "Opportunity rank change",
    "action_added": "Action update",
    "action_removed": "Action update",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fmt_money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "DATA_UNAVAILABLE"


def _html_escape(s: Any) -> str:
    """Escape &, <, >, \" for Telegram HTML bodies."""
    t = "" if s is None else str(s)
    return (
        t.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _severity_emoji(kind: Any, to_state: Any) -> str:
    """HOT/WARM/COOL/COLD emoji from change kind + to-state (fail-soft)."""
    k = str(kind or "").strip().lower()
    to_raw = to_state
    to_s = str(to_state).strip().upper() if to_state is not None else ""

    # 🔴 HOT
    if k == "reentry_upgrade" and to_s in ("READY", "REENTER"):
        return "🔴"
    if "action" in k and "DO_NOW" in to_s:
        return "🔴"
    if k == "opportunity_rank_change":
        try:
            if int(to_raw) <= 5:
                return "🔴"
        except (TypeError, ValueError):
            pass

    # 🟠 WARM
    if k == "reentry_added":
        return "🟠"
    if k == "reentry_upgrade" and to_s == "NEAR":
        return "🟠"
    if k == "opportunity_added":
        return "🟠"

    # 🟡 COOL
    if k == "reentry_downgrade":
        return "🟡"
    if to_s in ("AVOID", "WAIT"):
        return "🟡"
    if "action" in k and to_s == "AVOID":
        return "🟡"

    # ⚪ COLD (removed + default)
    return "⚪"


def _human_verb(kind: Any) -> str:
    k = str(kind or "").strip().lower()
    return _KIND_VERB.get(k, "Material update")


def _do_this_line(obj: dict[str, Any]) -> str:
    """Fail-soft one-liner from technical.status + why_now[0] + action_class."""
    change = obj.get("change") if isinstance(obj.get("change"), dict) else {}
    kind = str(change.get("kind") or "").strip().lower()
    tech = obj.get("technical") if isinstance(obj.get("technical"), dict) else {}
    status = tech.get("status")
    status_s = str(status).strip().upper() if status is not None else ""
    why = obj.get("why_now") if isinstance(obj.get("why_now"), list) else []

    if kind == "opportunity_removed":
        return "No opportunity slot — do not add."
    if status_s == "NEAR":
        return "Watch entry zone — do not chase. Desk NEAR."
    if status_s in ("READY", "REENTER"):
        return "Elevated watch — confirm zone before any action. Desk READY."
    if status_s in ("AVOID", "WAIT"):
        return f"Stand down / wait. Desk {status_s}."
    if why:
        return str(why[0])[:160]
    return "DATA_UNAVAILABLE — review in CIO."


def _reentry_row_from_product(product: dict[str, Any], symbol: str) -> dict[str, Any]:
    names = ((product or {}).get("reentry_book") or {}).get("names") or []
    sym = symbol.upper()
    for r in names:
        if isinstance(r, dict) and str(r.get("symbol") or "").upper() == sym:
            return r
    return {}


def _desk_row(symbol: str, *, root: Path | None = None) -> dict[str, Any]:
    try:
        from scripts.lib.cio_telegram_converse import load_reentry_desk_rows

        rows, _, _ = load_reentry_desk_rows()
        sym = symbol.upper()
        for r in rows or []:
            if isinstance(r, dict) and str(r.get("symbol") or "").upper() == sym:
                return r
    except Exception:
        pass
    return {}


def _thesis_fields(symbol: str, *, root: Path | None = None) -> dict[str, Any]:
    try:
        from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol

        return thesis_fields_for_symbol(symbol, root=root) or {}
    except Exception:
        return {}


def _provenance_for_trigger(trigger: str | None) -> str:
    t = str(trigger or "").upper()
    if "RESEARCH" in t or "HERMES" in t or "FLASH" in t:
        return "FRESH_RESEARCH"
    if "OPERATOR" in t:
        return "OPERATOR_ASK"
    return "DETERMINISTIC_RANK"


def assemble_symbol_intelligence(
    symbol: str,
    *,
    change_item: dict[str, Any] | None = None,
    product: dict[str, Any] | None = None,
    parent: dict[str, Any] | None = None,
    root: Path | str | None = None,
    prior_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a SymbolIntelligenceObject (fail-soft fields)."""
    root_p = Path(root) if root else None
    sym = str(symbol or "").upper()
    item = change_item if isinstance(change_item, dict) else {}
    product = product if isinstance(product, dict) else {}
    parent = parent if isinstance(parent, dict) else {}

    kind = str(item.get("kind") or "update")
    to_state = item.get("to")
    from_state = item.get("from")
    prod_row = _reentry_row_from_product(product, sym)
    desk = _desk_row(sym, root=root_p)
    thesis = _thesis_fields(sym, root=root_p)

    price = prod_row.get("current_price") or desk.get("price")
    entry_low = desk.get("entry_low") or prod_row.get("entry_low")
    entry_high = desk.get("entry_high") or prod_row.get("entry_high")
    stop = desk.get("stop")
    resistance = None
    if isinstance(desk.get("resistance"), dict):
        resistance = desk["resistance"].get("level")
    target = desk.get("target")

    why_bits: list[str] = []
    if prod_row.get("what_happened_since"):
        why_bits.append(str(prod_row["what_happened_since"])[:220])
    if prod_row.get("setup"):
        why_bits.append(str(prod_row["setup"])[:160])
    if desk.get("why"):
        w = desk["why"]
        if isinstance(w, list):
            why_bits.extend(str(x)[:120] for x in w[:2])
        else:
            why_bits.append(str(w)[:160])
    if not why_bits:
        why_bits.append(
            f"Status {from_state or '—'} → {to_state or '—'} on CIO product rebuild "
            f"({kind}). Detailed why: DATA_UNAVAILABLE."
        )

    thesis_summary = (
        thesis.get("thesis_summary")
        or prod_row.get("why_previously_owned")
        or thesis.get("why_owned_or_watched")
        or "DATA_UNAVAILABLE — living thesis not CURRENT"
    )
    conf = thesis.get("conviction") or thesis.get("confidence")
    try:
        conf_f = float(conf) if conf is not None else None
        if conf_f is not None and conf_f <= 1.0:
            conf_f *= 10.0
    except (TypeError, ValueError):
        conf_f = None

    trigger_symbol = str(parent.get("symbol") or "").upper() or None
    trigger = str(product.get("trigger") or parent.get("trigger") or "RESEARCH_COMPLETED")
    effect = (
        f"{sym} {kind.replace('_', ' ')} "
        f"{('→ ' + str(to_state)) if to_state is not None else ''}".strip()
    )
    causality = {
        "trigger_symbol": trigger_symbol,
        "trigger_event": trigger,
        "effect": effect,
        "narrative": (
            f"Research/product rebuild on {trigger_symbol or 'BOOK'} "
            f"({trigger}) caused: {effect}."
            if trigger_symbol
            else f"Product rebuild ({trigger}) caused: {effect}."
        ),
    }

    continuity = None
    if prior_feedback is None:
        try:
            from scripts.lib.cio_operator_ticker_feedback import latest_feedback

            prior_feedback = latest_feedback(sym, root=root_p)
        except Exception:
            prior_feedback = None
    if isinstance(prior_feedback, dict) and prior_feedback.get("intent"):
        continuity = {
            "prior_intent": prior_feedback.get("intent"),
            "prior_stance": prior_feedback.get("stance"),
            "prior_ts": prior_feedback.get("ts"),
            "prior_note": (prior_feedback.get("free_text") or prior_feedback.get("concerns")),
            "summary": (
                f"Your previous view ({str(prior_feedback.get('ts') or '')[:10] or 'prior'}): "
                f"{prior_feedback.get('intent')}"
                + (
                    f" — {prior_feedback.get('free_text')}"
                    if prior_feedback.get("free_text")
                    else ""
                )
            ),
        }

    return {
        "schema": SCHEMA,
        "as_of": _now(),
        "symbol": sym,
        "action_class": "REENTRY_WATCH" if "reentry" in kind else (
            "OPPORTUNITY" if "opportunity" in kind else "UPDATE"
        ),
        "change": {
            "kind": kind,
            "from": from_state,
            "to": to_state,
        },
        "headline": f"{sym} {_KIND_HEADLINE.get(kind, 'Material Update')}",
        "why_now": why_bits[:4],
        "thesis": {
            "summary": str(thesis_summary)[:400],
            "state": thesis.get("thesis_state") or "DATA_UNAVAILABLE",
            "version": thesis.get("symbol_thesis_version"),
            "confidence_0_10": conf_f,
            "role": thesis.get("portfolio_role"),
        },
        "technical": {
            "price": price,
            "support_or_zone_low": entry_low,
            "resistance_or_zone_high": entry_high if entry_high is not None else resistance,
            "stop_invalidation": stop,
            "target": target,
            "status": (
                to_state
                or prod_row.get("status")
                or ((desk.get("intel") or {}).get("state") if isinstance(desk.get("intel"), dict) else None)
            ),
        },
        "catalyst": {
            "primary": "DATA_UNAVAILABLE",
            "note": "Attach catalyst_record in Phase A+ when broker row present",
        },
        "sector": {"name": "DATA_UNAVAILABLE"},
        "historical_context": "DATA_UNAVAILABLE",
        "causality": causality,
        "provenance": {
            "decision_origin": _provenance_for_trigger(trigger),
            "trigger": trigger,
        },
        "memory": {
            "continuity": continuity,
        },
        "research_status": (
            "Fresh research" if _provenance_for_trigger(trigger) == "FRESH_RESEARCH"
            else "Deterministic ranking / product rebuild"
        ),
        "object_id": f"sio_{sym}_{kind}_{to_state or 'x'}".replace(" ", "")[:64],
        "authority": AUTHORITY,
        "financial_action": False,
    }


def _transition_label(change: dict[str, Any]) -> str:
    fr = change.get("from")
    to = change.get("to")
    if fr is not None and to is not None:
        return f"{fr}→{to}"
    if to is not None:
        return f"→{to}"
    if fr is not None:
        return f"{fr}→"
    return "—"


def render_telegram_card(obj: dict[str, Any]) -> str:
    """Human Investment Intelligence Card for Telegram (HTML).

    READ_ONLY_ADVISORY — escape all dynamic text; never invent prices/theses.
    """
    obj = obj if isinstance(obj, dict) else {}
    sym = str(obj.get("symbol") or "—").upper()
    change = obj.get("change") if isinstance(obj.get("change"), dict) else {}
    kind = str(change.get("kind") or "update")
    to_state = change.get("to")
    verb = _human_verb(kind)
    emoji = _severity_emoji(kind, to_state)
    transition = _transition_label(change)

    lead = (
        f"{emoji} <b>{_html_escape(sym)} · {_html_escape(verb)} · "
        f"{_html_escape(transition)}</b>"
    )

    prov = obj.get("provenance") if isinstance(obj.get("provenance"), dict) else {}
    origin = str(prov.get("decision_origin") or "DETERMINISTIC_RANK")
    if origin == "FRESH_RESEARCH":
        research_icon = "🔬"
        research_label = "Fresh research"
    else:
        research_icon = "📐"
        research_label = "Deterministic rank"
    cau = obj.get("causality") if isinstance(obj.get("causality"), dict) else {}
    trigger_sym = cau.get("trigger_symbol") or "NONE"
    meta = (
        f"{research_icon} {_html_escape(research_label)} · trigger "
        f"{_html_escape(trigger_sym)}"
    )

    do_this = _html_escape(_do_this_line(obj))

    why_lines: list[str] = []
    for b in (obj.get("why_now") or [])[:4]:
        why_lines.append(f"• {_html_escape(str(b)[:220])}")
    if not why_lines:
        why_lines.append(f"• {_html_escape('DATA_UNAVAILABLE')}")

    tech = obj.get("technical") if isinstance(obj.get("technical"), dict) else {}
    price_s = _html_escape(_fmt_money(tech.get("price")))
    zone_lo = _html_escape(_fmt_money(tech.get("support_or_zone_low")))
    zone_hi = _html_escape(_fmt_money(tech.get("resistance_or_zone_high")))
    stop_s = _html_escape(_fmt_money(tech.get("stop_invalidation")))
    levels = (
        f"Price <code>{price_s}</code> · Zone <code>{zone_lo}–{zone_hi}</code> · "
        f"Invalidation <code>{stop_s}</code>"
    )

    th = obj.get("thesis") if isinstance(obj.get("thesis"), dict) else {}
    conf = th.get("confidence_0_10")
    conf_s = f"{conf:.1f}/10" if isinstance(conf, (int, float)) else "DATA_UNAVAILABLE"
    thesis_summary = _html_escape(str(th.get("summary") or "DATA_UNAVAILABLE")[:400])
    thesis_state = _html_escape(th.get("state") or "DATA_UNAVAILABLE")
    thesis_line = (
        f"{thesis_summary} · State <code>{thesis_state}</code> · "
        f"Conf <code>{_html_escape(conf_s)}</code>"
    )

    lines = [
        lead,
        meta,
        "",
        "<b>Do this</b>",
        do_this,
        "",
        "<b>Why now</b>",
        *why_lines,
        "",
        "<b>Levels</b>",
        levels,
        "",
        "<b>Thesis</b>",
        thesis_line,
    ]

    cont = ((obj.get("memory") or {}).get("continuity") or {})
    if isinstance(cont, dict) and cont.get("summary"):
        lines += ["", f"Your previous view: {_html_escape(str(cont['summary'])[:280])}"]

    narrative = str(cau.get("narrative") or "DATA_UNAVAILABLE")[:320]
    lines += [
        "",
        f"Causality: {_html_escape(narrative)}",
        f"Provenance: <code>{_html_escape(origin)}</code>",
        AUTHORITY,
    ]
    return "\n".join(lines)


def cards_for_product_change(
    product: dict[str, Any],
    changed: dict[str, Any],
    parent: dict[str, Any],
    *,
    root: Path | str | None = None,
    max_cards: int = 3,
    material_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build up to max_cards IICs from material what_changed items (one per ticker)."""
    items = material_items if material_items is not None else [
        i for i in ((changed or {}).get("items") or [])
        if isinstance(i, dict) and i.get("material") and str(i.get("symbol") or "").strip()
    ]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for it in items:
        sym = str(it.get("symbol") or "").upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(
            assemble_symbol_intelligence(
                sym,
                change_item=it,
                product=product,
                parent=parent,
                root=root,
            )
        )
        if len(out) >= max_cards:
            break
    return out
