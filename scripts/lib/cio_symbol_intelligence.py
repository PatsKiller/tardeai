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


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fmt_money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "DATA_UNAVAILABLE"


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


def render_telegram_card(obj: dict[str, Any]) -> str:
    """Human Investment Intelligence Card for Telegram."""
    sym = str(obj.get("symbol") or "—")
    headline = str(obj.get("headline") or f"{sym} update")
    lines = [
        f"*{headline}*",
        "",
    ]
    cont = ((obj.get("memory") or {}).get("continuity") or {})
    if cont.get("summary"):
        lines += ["*Your previous view*", str(cont["summary"])[:280], ""]

    lines.append("*Why now*")
    for b in (obj.get("why_now") or [])[:4]:
        lines.append(f"• {b}")
    lines.append("")

    th = obj.get("thesis") or {}
    conf = th.get("confidence_0_10")
    conf_s = f"{conf:.1f}/10" if isinstance(conf, (int, float)) else "DATA_UNAVAILABLE"
    lines += [
        "*Thesis*",
        str(th.get("summary") or "DATA_UNAVAILABLE")[:400],
        f"State: `{th.get('state')}` · Confidence: {conf_s}",
        "",
    ]

    tech = obj.get("technical") or {}
    lines += [
        "*Technical setup*",
        f"Price: {_fmt_money(tech.get('price'))}",
        f"Zone / support→resist: {_fmt_money(tech.get('support_or_zone_low'))} → "
        f"{_fmt_money(tech.get('resistance_or_zone_high'))}",
        f"Invalidation (stop): {_fmt_money(tech.get('stop_invalidation'))}",
        f"Desk status: `{tech.get('status') or 'DATA_UNAVAILABLE'}`",
        "",
    ]

    cat = obj.get("catalyst") or {}
    lines += [
        "*Catalyst*",
        f"{cat.get('primary') or 'DATA_UNAVAILABLE'}",
        "",
    ]

    cau = obj.get("causality") or {}
    lines += [
        "*Causality*",
        str(cau.get("narrative") or "DATA_UNAVAILABLE")[:320],
        "",
    ]

    prov = obj.get("provenance") or {}
    lines += [
        "*Provenance*",
        f"Decision origin: `{prov.get('decision_origin')}`",
        f"Research status: {obj.get('research_status')}",
        "",
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
