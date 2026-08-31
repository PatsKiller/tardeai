"""Morning / EOD / Aegis / Command Center / Telegram renderers.

All consume CIOOperatorProduct@v1. None independently reconstruct investment truth.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.brief_semantic_dedupe import claim, session_date
from scripts.lib.cio_operator_product import build_operator_product
from scripts.lib.operator_human_renderer import render_decision, render_product
from scripts.lib.research_intelligence_summary import from_research_result, render_human as render_research

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0


def _product(root: Path | str | None, supplemental: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_operator_product(root=root, persist=False, supplemental=supplemental)


# ── Wave 2 slices 34 / 36 / 40 ───────────────────────────────────────────────

# Two writers publish a cash total and they disagree on CURRENT by ~$52.7k:
#   product.cash.cash_usd   = sum of the is_cash position rows
#   temperament.cash        = portfolio_totals.total_cash
# Slice 36 says the evening line is the live temperament number. Slice 40 says
# detect, never merge. So the brief prints temperament.cash AND says the sources
# disagree — it never averages them and never silently picks the larger one.
CASH_SOURCE_TOLERANCE_USD = 1.0


def cash_lines(product: dict[str, Any]) -> list[str]:
    """Live cash from temperament, plus an explicit disagreement note.

    Never renders `portfolio_implication` — that is a constant sentence about
    posture, not a cash number, and reading it as one is how a stale narrative
    ends up standing in for a balance.
    """
    temperament = product.get("temperament") or product.get("macro") or {}
    if not isinstance(temperament, dict):
        temperament = {}
    cash_block = product.get("cash") or {}
    if not isinstance(cash_block, dict):
        cash_block = {}

    live = temperament.get("cash")
    pct = temperament.get("cash_pct")
    rows_total = cash_block.get("cash_usd")

    def _num(value):
        """None unless it is genuinely numeric.

        `temperament.cash` is not always a number — a real payload carries
        strings such as "hold reserve". Formatting one with float() raised and
        took the whole morning brief down, so every read goes through here.
        """
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    live_n, rows_n = _num(live), _num(rows_total)

    lines: list[str] = []
    if live_n is None and rows_n is None:
        if live is not None or rows_total is not None:
            # Present but unusable — say so rather than dropping the line.
            return [f"Cash: UNAVAILABLE — non-numeric cash value ({live or rows_total!r})."]
        return ["Cash: UNAVAILABLE — no live temperament cash on the product."]

    try:
        disagree = (
            live_n is not None and rows_n is not None
            and abs(rows_n - live_n) > CASH_SOURCE_TOLERANCE_USD
        )
    except (TypeError, ValueError):
        disagree = False

    if disagree:
        # Operator display law: name both, name the gap, and refuse to pick one.
        # Picking silently is how a writer bug gets hidden, and this brief has
        # already flipped which figure it used once.
        gap = abs(rows_n - live_n)
        lines.append(f"cash_rows      {rows_n:>12,.2f}   source=position_rows")
        lines.append(f"cash_totals    {live_n:>12,.2f}   source=portfolio_totals")
        lines.append(f"cash_gap       {gap:>12,.2f}   status=UNRECONCILED")
        lines.append("cash_for_S5    DATA_UNAVAILABLE_UNTIL_RECONCILED — not merged, not averaged")
        return lines

    # B4 — print the cash block's own age (oldest contributing balance).
    cash_as_of = cash_block.get("as_of")
    if cash_as_of is None and isinstance(cash_block.get("cash_as_of"), dict):
        cash_as_of = cash_block["cash_as_of"].get("as_of")
    if cash_as_of is None and isinstance(temperament.get("cash_as_of"), dict):
        cash_as_of = temperament["cash_as_of"].get("as_of")
    age_bit = f" · as_of {cash_as_of} (oldest cash balance)" if cash_as_of else " · as_of UNSTAMPED"

    if live_n is not None:
        pct_bit = f" · {pct:.1f}% of book" if isinstance(pct, (int, float)) else ""
        lines.append(f"Cash (live, temperament.cash): ${live_n:,.0f}{pct_bit}{age_bit}")
    elif rows_n is not None:
        lines.append(f"Cash (position rows): ${rows_n:,.0f}{age_bit}")
    else:
        lines.append(f"Cash (live, temperament.cash): UNAVAILABLE{age_bit}")
    return lines


PROVENANCE_FOOTER = (
    "_Provenance: D counts/sums · T templates · no model produced this brief. "
    "writer = author._"
)


def reentry_surface_label(product: dict[str, Any]) -> str:
    """Name which re-entry book a brief is quoting. Two books, never merged."""
    re = product.get("reentry") if isinstance(product.get("reentry"), dict) else {}
    surface = str(re.get("surface") or "").strip()
    scope = str(re.get("scope") or "").strip()
    if not surface:
        return "Re-entry book: UNLABELED — surface not declared on the product."
    scope_bit = f" — {scope}" if scope else ""
    return f"Re-entry: Surface {surface}{scope_bit} (Surface B is a separate book; not merged)."


def earnings_lines(product: dict[str, Any], *, cap: int = 8) -> list[str]:
    """Render dated earnings events that already exist on the product.

    Same honesty pattern as watch_lines: a bare count reads as an empty brief
    when symbols and dates are sitting on the payload. List what the collector
    produced (symbol · date · days · scope). Never invent commentary — UNAVAILABLE
    commentary stays off this surface. When items are empty, name DATA_UNAVAILABLE
    from earnings_quality rather than omitting the section.
    """
    earn = product.get("earnings") or []
    if not isinstance(earn, list):
        earn = []
    quality = product.get("earnings_quality") if isinstance(product.get("earnings_quality"), dict) else {}
    lines: list[str] = []
    if earn:
        lines.append(f"Earnings (D): {len(earn)} upcoming")
        for row in earn[:cap]:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").upper()
            if not sym:
                continue
            date_s = str(row.get("earnings_date") or "—")
            scope = str(row.get("scope") or "").strip()
            days = row.get("days_to_event")
            bits = [sym, date_s]
            if isinstance(days, int):
                bits.append(f"{days}d")
            if scope:
                bits.append(scope)
            lines.append("- " + " · ".join(bits))
        return lines
    q = str(quality.get("quality") or "")
    reason = quality.get("reason")
    if q == "DATA_UNAVAILABLE" or reason:
        reason_bit = f" — {reason}" if reason else ""
        lines.append(f"Earnings (D): DATA_UNAVAILABLE{reason_bit}")
    return lines


def watch_lines(product: dict[str, Any], *, cap: int = 8) -> list[str]:
    """Name the watch names. BLOCK is named; READY is never invented.

    The briefs carried a watch *count* and no names, which reads as "nothing to
    look at" when 26 names are sitting on the payload with a reason each. They
    are named here — as BLOCK, with the reason and the desk state — and READY /
    NEAR are reported exactly as found. A BLOCK name is never re-labelled READY
    and never fires S7; `watch_ready: 0` is a legal, honest answer.
    """
    wbs = product.get("watch_block_summary")
    if not isinstance(wbs, dict) or not wbs:
        return []

    lines: list[str] = []
    ready = [str(s).upper() for s in (wbs.get("ready_symbols") or []) if s]
    near = [str(s).upper() for s in (wbs.get("near_symbols") or []) if s]
    if ready or near:
        bits = []
        if ready:
            bits.append("READY " + ", ".join(ready[:cap]))
        if near:
            bits.append("NEAR " + ", ".join(near[:cap]))
        lines.append("Watch promotion-grade: " + " · ".join(bits))
    else:
        lines.append(
            f"Watch promotion-grade: none (ready {int(wbs.get('ready_count') or 0)}, "
            f"fires_s7 {bool(wbs.get('fires_s7'))}) — honest zero, not a filter miss."
        )

    top = [t for t in (wbs.get("top") or []) if isinstance(t, dict) and t.get("symbol")]
    count = wbs.get("count")
    if top:
        named = ", ".join(
            f"{str(t['symbol']).upper()} ({t.get('trade_ai_state') or '?'})"
            for t in top[:cap]
        )
        more = ""
        if isinstance(count, int) and count > len(top[:cap]):
            more = f" +{count - len(top[:cap])} more"
        reasons = wbs.get("by_reason") if isinstance(wbs.get("by_reason"), dict) else {}
        reason_bit = f" · {', '.join(f'{k} {v}' for k, v in reasons.items())}" if reasons else ""
        lines.append(f"Watch BLOCK ({count}): {named}{more}{reason_bit}")
    elif count:
        lines.append(f"Watch BLOCK: {count} names, none surfaced on the payload.")
    return lines


def morning_text(product: dict[str, Any]) -> str:
    if product.get("available") is False:
        return render_product(product)
    lines = ["☀️ MORNING CIO BRIEF", ""]
    if product.get("executive_summary"):
        lines.append(str(product["executive_summary"]).strip())
        lines.append("")
    cash = product.get("cash") or {}
    if cash:
        # Name the source: this is the position-row sum, not portfolio_totals.
        # cash_lines() prints the live temperament number and flags any gap.
        age = cash.get("as_of")
        if age is None and isinstance(cash.get("cash_as_of"), dict):
            age = cash["cash_as_of"].get("as_of")
        age_bit = f" · as_of {age} (oldest cash balance)" if age else " · as_of UNSTAMPED"
        lines.append(
            f"Cash (position rows): {cash.get('status')} ${cash.get('cash_usd') or 0:,.0f}{age_bit}"
            if cash.get("cash_usd") is not None
            else f"Cash (position rows): {cash.get('status')}{age_bit}"
        )
    port = product.get("portfolio") or {}
    if port.get("holdings_n"):
        lines.append(f"Holdings: {port.get('holdings_n')} names")
    dq = product.get("data_quality") or {}
    if dq.get("state") and dq.get("state") not in {"OK", "CURRENT"}:
        lines.append(f"Data quality: {dq.get('state')} — {dq.get('note') or ''}".rstrip(" —"))
    lines.append("")
    action_now = product.get("action_now") or []
    if action_now:
        klass = product.get("action_now_class") or "D"
        lines.append(f"ACTION NOW [{klass}]")
        for e in action_now[:8]:
            lines.append(render_decision(e, product))
            lines.append("")
    else:
        lines.append("No ACT-NOW items. Standing posture below.")
        lines.append("")
        for e in (product.get("standing_decisions") or product.get("entries") or [])[:5]:
            if isinstance(e, dict):
                lines.append(f"- {e.get('symbol') or ''} {e.get('cio_decision')} — {e.get('what_changed')}".strip())
        lines.append("")
    reentry = product.get("reentry") or {}
    if reentry.get("count"):
        counts = reentry.get("counts") or {}
        scope = reentry.get("scope") or "former holdings vs exit trigger"
        lines.append(
            f"Re-entry book A ({scope}): {reentry.get('count')} names {counts}".strip()
        )
    secs = product.get("sector") or []
    if secs:
        lines.append("Sector")
        for sec in secs[:6]:
            if isinstance(sec, dict) and sec.get("prose"):
                lines.append(sec["prose"])
    elif product.get("sector_reason"):
        lines.append(f"Sector: {product.get('sector_reason')}")
    inds = product.get("industry") or []
    if inds:
        lines.append("Industry")
        for ind in inds[:4]:
            if isinstance(ind, dict) and ind.get("prose"):
                lines.append(ind["prose"])
    cats = product.get("catalysts") or []
    if cats:
        lines.append("Catalysts")
        for c in cats[:4]:
            if isinstance(c, dict):
                lines.append(
                    f"- {c.get('entity') or ''} {c.get('catalyst')}: {c.get('why_relevant') or c.get('when') or ''}".strip()
                )
    elif product.get("catalysts_reason"):
        lines.append(f"Catalysts: {product.get('catalysts_reason')}")
    lines.extend(earnings_lines(product))
    new_if = product.get("new_position_if") or []
    if new_if:
        nsyms = [str(x.get("symbol") or "") for x in new_if if isinstance(x, dict) and x.get("symbol")]
        lines.append("NEW_POSITION_IF: " + ", ".join(nsyms[:5]))
    lines.extend(cash_lines(product))
    lines.extend(watch_lines(product))
    lines.append(reentry_surface_label(product))
    cases = product.get("case_summaries") or product.get("research_cases") or {}
    case_items = cases.get("items") if isinstance(cases, dict) else cases
    if case_items:
        top_syms: list[str] = []
        for it in case_items[:3]:
            if not isinstance(it, dict):
                continue
            for s in (it.get("symbols") or []):
                u = str(s).upper()
                if u and u not in top_syms:
                    top_syms.append(u)
            if not it.get("symbols") and it.get("subject"):
                top_syms.append(str(it["subject"]).split(":")[-1])
        n = cases.get("count") if isinstance(cases, dict) and cases.get("count") is not None else len(case_items)
        bit = f" · {', '.join(top_syms[:3])}" if top_syms else ""
        lines.append(f"Research cases (A-context, not action): {n}{bit}")
    lines.append("Open: Command Center → CIO. READ_ONLY_ADVISORY.")
    # B5 — honest provenance footer. This path is a deterministic projection;
    # never assert model provenance for a brief no model produced.
    lines.append(PROVENANCE_FOOTER)
    text = "\n".join(lines).strip()
    # Dashboard brief must never claim a Telegram send.
    return text.replace("Telegram sent", "dashboard only")


def eod_text(product: dict[str, Any]) -> str:
    if product.get("available") is False:
        return render_product(product)
    lines = ["🌆 EOD CIO BRIEF", ""]
    if product.get("executive_summary"):
        lines.append(str(product["executive_summary"]).strip())
        lines.append("")
    material = [e for e in (product.get("decisions") or []) if e.get("cio_decision") in {"TRIM", "REENTER", "AVOID", "REVIEW"}]
    if material:
        lines.append("Meaningful changes")
        for e in material[:8]:
            lines.append(render_decision(e, product))
            lines.append("")
    else:
        lines.append("No material CIO change this session.")
        lines.append("")
    lines.append("Standing overnight posture")
    for e in (product.get("standing_decisions") or [])[:6]:
        lines.append(f"- {e.get('symbol') or 'PORTFOLIO'} {e.get('cio_decision')}: {e.get('what_changed')}")
    lines.extend(cash_lines(product))
    lines.extend(watch_lines(product))
    lines.append(reentry_surface_label(product))
    dq = product.get("data_quality") or {}
    if dq.get("state") not in (None, "OK", "CURRENT"):
        labels = dq.get("labels") if isinstance(dq.get("labels"), list) else []
        label_bit = f" ({', '.join(str(x) for x in labels)})" if labels else ""
        lines.append(f"Data quality overnight: {dq.get('state')}{label_bit}")
    cases = product.get("case_summaries") or product.get("research_cases") or {}
    case_items = cases.get("items") if isinstance(cases, dict) else cases
    if case_items:
        top_syms: list[str] = []
        for it in case_items[:3]:
            if not isinstance(it, dict):
                continue
            for s in (it.get("symbols") or []):
                u = str(s).upper()
                if u and u not in top_syms:
                    top_syms.append(u)
        n = cases.get("count") if isinstance(cases, dict) and cases.get("count") is not None else len(case_items)
        bit = f" · {', '.join(top_syms[:3])}" if top_syms else ""
        lines.append(f"Research cases (A-context, not action): {n}{bit}")
    lines.append("READ_ONLY_ADVISORY — no order is being placed.")
    lines.append(PROVENANCE_FOOTER)
    return "\n".join(lines).strip()


def aegis_summary(product: dict[str, Any]) -> dict[str, Any]:
    """Aegis may summarize CIO state; it cannot create competing CIO truth."""
    return {
        "role": "PROTECTION_SURVEILLANCE_DATA_HEALTH_OVERNIGHT_RISK",
        "source": "cio.operator_product.current",
        "available": product.get("available"),
        "status": product.get("status"),
        "generation_id": product.get("generation_id"),
        "executive_summary": product.get("executive_summary"),
        "action_now_n": len(product.get("action_now") or []),
        "data_quality": product.get("data_quality"),
        "creates_cio_truth": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def command_center_view(product: dict[str, Any]) -> dict[str, Any]:
    decisions = []
    for e in product.get("decisions") or product.get("entries") or []:
        if not isinstance(e, dict):
            continue
        decisions.append({
            "decision_id": e.get("decision_id"),
            "decision": e.get("decision") or e.get("cio_decision"),
            "urgency": e.get("urgency") or e.get("what_should_i_do"),
            "reason": e.get("why_it_matters") or e.get("why"),
            "confidence": e.get("confidence"),
            "confidence_status": e.get("confidence_status"),
            "counter_evidence": e.get("counter_evidence"),
            "research_provenance": e.get("source"),
            "entity_identity": e.get("entity") or e.get("symbol"),
            "data_quality": e.get("data_quality"),
            "next_review": e.get("next_review_at") or e.get("next_review"),
            "generation_id": e.get("generation_id") or product.get("generation_id"),
        })
    cash = product.get("cash") or {}
    temperament = product.get("temperament") or product.get("macro") or {}
    if not isinstance(temperament, dict):
        temperament = {}
    else:
        temperament = dict(temperament)
    # B5 — constant standing-policy text is not situation guidance at display.
    if temperament.get("portfolio_implication") and not temperament.get(
        "portfolio_implication_is_guidance"
    ):
        temperament.setdefault(
            "standing_policy_template", temperament.get("portfolio_implication")
        )
        temperament["portfolio_implication"] = None
        temperament["portfolio_implication_is_guidance"] = False
        temperament["portfolio_implication_role"] = "standing_policy_template"
    provenance = product.get("provenance_footer") if isinstance(
        product.get("provenance_footer"), dict
    ) else {
        "model_produced": False,
        "classes": "D counts/sums · T templates · A case-summary context",
        "writer_means": "author",
        "note": (
            "Deterministic projection of cio.operator_product; "
            "no model produced this view."
        ),
    }
    return {
        "source": "cio.operator_product.current",
        "loaded": bool(product.get("available")),
        "status": product.get("status"),
        "generation_id": product.get("generation_id"),
        "product_id": product.get("product_id"),
        "as_of": product.get("as_of"),
        "block_as_of": product.get("block_as_of") or {
            "cash": cash.get("as_of") if isinstance(cash, dict) else None,
            "product_composition": product.get("as_of"),
        },
        "executive_summary": product.get("executive_summary"),
        "earnings": list(product.get("earnings") or [])[:12],
        "earnings_quality": product.get("earnings_quality") if isinstance(product.get("earnings_quality"), dict) else {
            "quality": "OK" if product.get("earnings") else "DATA_UNAVAILABLE",
            "class": "D",
        },
        "new_position_if": list(product.get("new_position_if") or [])[:8],
        "cash": cash,
        "temperament": temperament,
        "case_summaries": product.get("case_summaries") or product.get("research_cases") or {
            "banner": "A-context · NON_AUTHORITATIVE · does not change action",
            "class": "A",
            "count": 0,
            "items": [],
        },
        "telegram_sent": False,
        "delivery": "dashboard",
        "decisions": decisions,
        "history_store": "cio.operator_product.history",
        "hidden_alternative_calculation": False,
        "authority": AUTHORITY,
        "financial_action": False,
        "provenance_footer": provenance,
        "model_produced": False,
    }


def telegram_text(product: dict[str, Any]) -> str:
    return render_product(product)


def deliver_morning(*, root: Path | str, supplemental_bundle: dict[str, Any] | None = None,
                    send: bool = True, now: datetime | None = None) -> dict[str, Any]:
    product = _product(root, supplemental_bundle)
    gen = str(product.get("generation_id") or product.get("status") or "unavailable")
    sess = session_date(now)
    claim_res = claim(kind="MORNING", session=sess, material_generation=gen, root=root)
    text = morning_text(product)
    published = bool(claim_res.get("published"))
    sent = False
    if published and send:
        try:
            from telegram_alert import send_telegram
            sent = bool(send_telegram(text, bypass_router=True))
        except Exception as exc:
            return {
                "handled": True,
                "published": False,
                "ok": False,
                "reason": f"send_failed:{type(exc).__name__}",
                "text": text,
                "product_status": product.get("status"),
                "key": claim_res.get("key"),
                "consumer": "morning",
                "authority": AUTHORITY,
                "financial_action": False,
            }
    return {
        "handled": True,
        "published": published,
        "ok": True,
        "sent": sent,
        "reason": claim_res.get("reason"),
        "key": claim_res.get("key"),
        "text": text,
        "product_status": product.get("status"),
        "consumer": "morning",
        "source": "cio.operator_product.current",
        "authority": AUTHORITY,
        "financial_action": False,
    }


def deliver_eod(*, root: Path | str, send: bool = False, now: datetime | None = None) -> dict[str, Any]:
    product = _product(root)
    gen = str(product.get("generation_id") or product.get("status") or "unavailable")
    sess = session_date(now)
    claim_res = claim(kind="EOD", session=sess, material_generation=gen, root=root)
    text = eod_text(product)
    published = bool(claim_res.get("published"))
    sent = False
    if published and send:
        try:
            from telegram_alert import send_telegram
            sent = bool(send_telegram(text, bypass_router=True))
        except Exception:
            sent = False
    return {
        "handled": True,
        "published": published,
        "ok": True,
        "sent": sent,
        "reason": claim_res.get("reason"),
        "key": claim_res.get("key"),
        "text": text,
        "consumer": "eod",
        "source": "cio.operator_product.current",
        "authority": AUTHORITY,
        "financial_action": False,
    }


def render_research_message(row: dict[str, Any]) -> str:
    return render_research(from_research_result(row))
