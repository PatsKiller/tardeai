"""Research completion → parent CIO product reassessment.

Missing link from R6.8 certification. NOT a second CIO.

on_hermes_completed already critiques, admits memory, and expires overlay.
This module is the missing persist_product + what_changed + notification step.

READ_ONLY_ADVISORY. MEMORY_BEHAVIOR_INFLUENCE stays 0.
Research completion is never RE_ENTER authorization.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Overnight units put scripts/lib on sys.path, not the repo root.
# CIO modules import scripts.lib.* — ensure the repo root is visible.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

log = logging.getLogger("tradeai.cio_product_reassessment")

AUTHORITY = "READ_ONLY_ADVISORY"
WHAT_CHANGED_SCHEMA = "CIOWhatChanged@v1"
IMPACT_SCHEMA = "ResearchImpact@v1"
REASSESS_SCHEMA = "CIOReassessment@v1"
MAX_PENDING_RETRIES = 3

_RANK = {"AVOID": 0, "WAIT": 1, "NEAR": 2, "READY": 3, "REENTER": 4}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _cio_dir(root: Path | str | None = None) -> Path:
    if root:
        return Path(root) / "data" / "cio"
    try:
        try:
            from maturity_control.store import resolve_root
        except ImportError:
            from scripts.lib.maturity_control.store import resolve_root
        return resolve_root(None) / "data" / "cio"
    except Exception:
        return Path("data/cio")


def _paths(root: Path | str | None = None) -> dict[str, Path]:
    base = _cio_dir(root)
    return {
        "index": base / "cio_reassessment_index.json",
        "log": base / "cio_reassessments.jsonl",
        "impacts": base / "cio_research_impacts.jsonl",
        "pending": base / "cio_reassessment_pending.jsonl",
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")


def _digest(*parts: Any) -> str:
    blob = "|".join(str(p or "") for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def reassessment_id(*, parent_key: str, result_id: str) -> str:
    return f"reassessment:{parent_key}:{result_id}"


def recover_parent(request: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Recover plan/run/product identity. Never invent a run from symbol alone."""
    req = request if isinstance(request, dict) else {}
    res = result if isinstance(result, dict) else {}
    md = req.get("metadata") if isinstance(req.get("metadata"), dict) else {}
    extra = req.get("extra") if isinstance(req.get("extra"), dict) else {}
    plan_id = str(
        req.get("plan_id") or res.get("plan_id") or md.get("plan_id") or extra.get("plan_id") or ""
    )
    parent_run_id = str(
        req.get("parent_run_id")
        or res.get("parent_run_id")
        or md.get("parent_run_id")
        or md.get("cio_run_id")
        or extra.get("parent_run_id")
        or ""
    )
    research_id = str(res.get("research_id") or req.get("research_id") or "")
    result_id = str(res.get("result_id") or req.get("result_id") or "")
    symbol = str(res.get("symbol") or req.get("symbol") or md.get("symbol") or "").upper()
    if plan_id or parent_run_id:
        status = "RECOVERED"
        parent_key = parent_run_id or plan_id
    else:
        status = "ORPHANED_LEGACY"
        parent_key = "global_product"
    return {
        "status": status,
        "parent_key": parent_key,
        "parent_run_id": parent_run_id or None,
        "plan_id": plan_id or None,
        "research_id": research_id or None,
        "result_id": result_id or None,
        "symbol": symbol or None,
        "authority": AUTHORITY,
    }


def load_index(root: Path | str | None = None) -> dict[str, Any]:
    return _read_json(_paths(root)["index"])


def already_completed(rid: str, *, root: Path | str | None = None) -> dict[str, Any]:
    rec = (load_index(root).get("completed") or {}).get(rid)
    return rec if isinstance(rec, dict) else {}


def _mark(kind: str, rid: str, rec: dict[str, Any], *, root: Path | str | None = None) -> None:
    idx = load_index(root)
    bucket = dict(idx.get(kind) or {})
    bucket[rid] = rec
    if kind == "completed":
        pending = dict(idx.get("pending") or {})
        pending.pop(rid, None)
        idx["pending"] = pending
    idx[kind] = bucket
    idx["updated_at"] = _now()
    _write_json(_paths(root)["index"], idx)


def _symbols(book: dict[str, Any], key: str = "names") -> dict[str, str]:
    out: dict[str, str] = {}
    rows = (book or {}).get(key) or (book or {}).get("top") or []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").upper()
        if sym:
            out[sym] = str(r.get("status") or r.get("verdict") or r.get("state") or "")
    return out


def _opp_rank(book: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in (book or {}).get("top") or []:
        if isinstance(r, dict) and r.get("symbol"):
            try:
                out[str(r["symbol"]).upper()] = int(r.get("rank") or 0)
            except (TypeError, ValueError):
                out[str(r["symbol"]).upper()] = 0
    return out


def _action_pairs(actions: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for bucket, rows in (actions or {}).items():
        if not isinstance(rows, list):
            continue
        for r in rows:
            if isinstance(r, dict) and r.get("symbol"):
                pairs.add((str(r.get("symbol")).upper(), str(bucket)))
    return pairs


def diff_products(prior: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Semantic what_changed. Timestamp-only churn is not material."""
    try:
        from scripts.lib.cio_investment_product import NON_TICKER_SYMBOLS
    except ImportError:  # pragma: no cover
        from cio_investment_product import NON_TICKER_SYMBOLS  # type: ignore

    items: list[dict[str, Any]] = []
    p_re = _symbols((prior or {}).get("reentry_book") or {})
    n_re = _symbols((new or {}).get("reentry_book") or {})
    for sym in sorted(set(p_re) | set(n_re)):
        if sym in NON_TICKER_SYMBOLS:
            continue
        a, b = p_re.get(sym), n_re.get(sym)
        if a is None and b is not None:
            # Demote pure AVOID adds — noise, not a material paging event
            to_state = str(b or "").upper()
            material = to_state != "AVOID"
            items.append({
                "kind": "reentry_added", "symbol": sym, "to": b,
                "material": material,
                **({"demoted_reason": "reentry_added_to_AVOID"} if not material else {}),
            })
        elif b is None and a is not None:
            items.append({"kind": "reentry_removed", "symbol": sym, "from": a, "material": True})
        elif a != b:
            up = _RANK.get(str(b).upper(), 1) > _RANK.get(str(a).upper(), 1)
            items.append({
                "kind": "reentry_upgrade" if up else "reentry_downgrade",
                "symbol": sym, "from": a, "to": b, "material": True,
            })

    p_op, n_op = _opp_rank((prior or {}).get("opportunity_book") or {}), _opp_rank((new or {}).get("opportunity_book") or {})
    for sym in sorted(set(p_op) | set(n_op)):
        if sym in NON_TICKER_SYMBOLS:
            continue
        if sym not in p_op:
            items.append({"kind": "opportunity_added", "symbol": sym, "to": n_op[sym], "material": True})
        elif sym not in n_op:
            items.append({"kind": "opportunity_removed", "symbol": sym, "from": p_op[sym], "material": True})
        elif p_op[sym] != n_op[sym]:
            items.append({
                "kind": "opportunity_rank_change", "symbol": sym,
                "from": p_op[sym], "to": n_op[sym], "material": abs(p_op[sym] - n_op[sym]) >= 3,
            })

    p_act, n_act = _action_pairs((prior or {}).get("action_book") or {}), _action_pairs((new or {}).get("action_book") or {})
    for pair in sorted(n_act - p_act):
        if pair[0] in NON_TICKER_SYMBOLS:
            continue
        items.append({"kind": "action_added", "symbol": pair[0], "to": pair[1], "material": pair[1] in {"DO_NOW", "AVOID"}})
    for pair in sorted(p_act - n_act):
        if pair[0] in NON_TICKER_SYMBOLS:
            continue
        items.append({"kind": "action_removed", "symbol": pair[0], "from": pair[1], "material": pair[1] in {"DO_NOW", "AVOID"}})

    p_t = str(((prior or {}).get("temperament") or {}).get("title") or "")
    n_t = str(((new or {}).get("temperament") or {}).get("title") or "")
    if p_t and n_t and p_t != n_t:
        items.append({"kind": "temperament_changed", "from": p_t, "to": n_t, "material": True})

    material = any(i.get("material") for i in items)
    return {
        "schema": WHAT_CHANGED_SCHEMA,
        "as_of": (new or {}).get("as_of") or _now(),
        "material": material,
        "item_count": len(items),
        "items": items,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def material_notification_items(changed: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Material diff lines for paging — NON_TICKER already filtered in diff_products."""
    try:
        from scripts.lib.cio_investment_product import NON_TICKER_SYMBOLS
    except ImportError:  # pragma: no cover
        from cio_investment_product import NON_TICKER_SYMBOLS  # type: ignore
    items = []
    for i in ((changed or {}).get("items") or []):
        if not isinstance(i, dict) or not i.get("material"):
            continue
        sym = str(i.get("symbol") or "").upper()
        if sym and sym in NON_TICKER_SYMBOLS:
            continue
        items.append(i)
    return items


def notification_attribution_symbol(
    changed: dict[str, Any] | None,
    trigger_symbol: str | None,
) -> str:
    """Label BOOK when the trigger symbol's own row did not materially change."""
    trigger = str(trigger_symbol or "").strip().upper()
    items = material_notification_items(changed)
    if not trigger:
        return "BOOK"
    for it in items:
        if str(it.get("symbol") or "").upper() == trigger:
            return trigger
    return "BOOK"


def research_impact(
    *,
    symbol: str,
    result_id: str,
    research_id: str,
    prior: dict[str, Any],
    new: dict[str, Any],
    critique: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    verdict = str((critique or {}).get("verdict") or "").upper()
    p_st = _symbols((prior or {}).get("reentry_book") or {}).get(symbol) or _symbols(
        (prior or {}).get("opportunity_book") or {}, "top"
    ).get(symbol)
    n_st = _symbols((new or {}).get("reentry_book") or {}).get(symbol) or _symbols(
        (new or {}).get("opportunity_book") or {}, "top"
    ).get(symbol)
    if verdict == "INSUFFICIENT":
        impact = "INSUFFICIENT"
    elif p_st is None and n_st is None:
        impact = "NO_MATERIAL_CHANGE"
    elif p_st == n_st:
        impact = "NO_MATERIAL_CHANGE"
    elif _RANK.get(str(n_st).upper(), 1) > _RANK.get(str(p_st or "").upper(), 1):
        impact = "STRENGTHENED"
    elif _RANK.get(str(n_st).upper(), 1) < _RANK.get(str(p_st or "WAIT").upper(), 1):
        impact = "WEAKENED" if str(n_st).upper() != "AVOID" else "BROKEN"
    else:
        impact = "UNKNOWN"
    return {
        "schema": IMPACT_SCHEMA,
        "symbol": symbol,
        "research_request_id": research_id,
        "result_id": result_id,
        "prior_product_id": (prior or {}).get("product_id") or (prior or {}).get("decision_id"),
        "new_product_id": (new or {}).get("product_id") or (new or {}).get("decision_id"),
        "prior_state": p_st,
        "new_state": n_st,
        "impact": impact,
        "reason": f"{p_st or 'absent'} → {n_st or 'absent'}",
        "evidence_refs": [result_id] if result_id else [],
        "as_of": (new or {}).get("as_of") or _now(),
        "quality": verdict or "UNKNOWN",
        "confidence": (critique or {}).get("confidence"),
        "authority": AUTHORITY,
        "financial_action": False,
    }


def _annotate_research(product: dict[str, Any], result: dict[str, Any], critique: Optional[dict[str, Any]]) -> None:
    """Surface completed research on the matching book row. Does not grant RE_ENTER."""
    symbol = str(result.get("symbol") or "").upper()
    if not symbol:
        return
    rid = str(result.get("result_id") or "")
    verdict = str((critique or {}).get("verdict") or result.get("status") or "")
    summary = str(result.get("summary") or "")[:180]
    note = f"completed {rid} verdict={verdict or 'n/a'} {summary}".strip()
    for row in ((product.get("reentry_book") or {}).get("names") or []):
        if str(row.get("symbol") or "").upper() == symbol:
            row["research_change"] = note
            row["last_research_result_id"] = rid
            return
    for row in ((product.get("opportunity_book") or {}).get("top") or []):
        if str(row.get("symbol") or "").upper() == symbol:
            row["research_change"] = note
            row["last_research_result_id"] = rid
            return


THESIS_VERSION_ONLY_KINDS = frozenset({
    "thesis_version", "thesis_version_changed", "symbol_thesis_version",
})


def should_enqueue_product_notification(changed: dict[str, Any] | None) -> bool:
    """Material product what_changed only. Thesis-version bumps do not page Telegram."""
    ch = changed or {}
    if not ch.get("material"):
        return False
    items = material_notification_items(ch)
    if not items:
        return False
    kinds = {str(i.get("kind") or "") for i in items}
    if kinds and kinds <= THESIS_VERSION_ONLY_KINDS:
        return False
    return True


def _outbox_for_root(root: Path | str | None = None):
    from scripts.lib.cio_notification_outbox import NotificationOutbox
    if root:
        p = Path(root) / "data" / "cio" / "cio_notification_outbox.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        return NotificationOutbox(event_store_path=p)
    return NotificationOutbox()


def _enqueue_material_product_outbox(
    product: dict[str, Any],
    changed: dict[str, Any],
    parent: dict[str, Any],
    *,
    root: Path | str | None = None,
    outbox=None,
    max_cards: int = 3,
) -> dict[str, Any]:
    """Durable outbox enqueue — one Investment Intelligence Card per material ticker.

    Does not switch the delivery worker to live. Replaces raw kind/from→to dumps.
    """
    try:
        import hashlib
        from scripts.lib.cio_notification_outbox import NotificationOutbox  # noqa: F401
        from scripts.lib.cio_symbol_intelligence import (
            cards_for_product_change,
            render_telegram_card,
        )

        outbox = outbox or _outbox_for_root(root)
        pid = str(product.get("product_id") or product.get("decision_id") or "product")
        items = material_notification_items(changed)
        trigger_symbol = str(parent.get("symbol") or "").upper() or None
        cards = cards_for_product_change(
            product,
            changed,
            parent,
            root=root,
            max_cards=max_cards,
            material_items=items,
        )
        try:
            from scripts.lib.cio_notification_delivery import is_raw_product_dump_body
        except ImportError:  # pragma: no cover
            from cio_notification_delivery import is_raw_product_dump_body  # type: ignore

        def _muted_book_digest(label: str) -> tuple[str, str]:
            """Short HTML book digest (no Markdown asterisks)."""
            trigger = trigger_symbol or "NONE"
            causality = product.get("trigger") or "RESEARCH_COMPLETED"
            body = (
                f"⚪ <b>CIO book update</b>\n"
                f"Causality: <code>{trigger}</code> · {causality}\n"
                f"Attribution: <code>{label}</code>\n"
                "No single-ticker material rows to card.\n"
                f"{AUTHORITY}"
            )
            subject = f"CIO book update · {label}"
            return subject, body

        if not cards:
            # Fallback: book-level digest (temperament-only etc.)
            label = notification_attribution_symbol(changed, trigger_symbol)
            subject, body = _muted_book_digest(label)
            note = {
                "notification_id": "ntf_prod_" + _digest(pid, changed.get("as_of") or _now()),
                "idempotency_key": f"product_what_changed:{pid}",
                "dedupe_key": f"product_what_changed:{pid}:{changed.get('as_of') or ''}",
                "message_class": "advisory",
                "channel_targets": ["telegram", "command_center"],
                "subject": subject,
                "trigger_symbol": trigger_symbol,
                "attribution_symbol": label,
                "body": body,
                "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "card_schema": "InvestmentIntelligenceCard@v1",
                "parse_mode": "HTML",
            }
            event = outbox.enqueue(note, actor_id="cio_product_reassessment")
            return {
                "outbox_enqueued": True,
                "outbox_notification_id": note["notification_id"],
                "outbox_event_type": (event or {}).get("event_type"),
                "live_delivery": False,
                "trigger_symbol": trigger_symbol,
                "attribution_symbol": label,
                "cards_enqueued": 0,
            }

        enqueued_ids: list[str] = []
        last_event = None
        for card in cards:
            sym = str(card.get("symbol") or "").upper()
            body = render_telegram_card(card)
            # Belt-and-suspenders: never enqueue a legacy raw dump body.
            if is_raw_product_dump_body(body):
                log.warning(
                    "raw product dump body detected for symbol=%s; replacing with muted book digest",
                    sym,
                )
                label = notification_attribution_symbol(changed, trigger_symbol)
                subject, body = _muted_book_digest(label)
                note = {
                    "notification_id": "ntf_prod_" + _digest(pid, changed.get("as_of") or _now()),
                    "idempotency_key": f"product_what_changed:{pid}",
                    "dedupe_key": f"product_what_changed:{pid}:{changed.get('as_of') or ''}",
                    "message_class": "advisory",
                    "channel_targets": ["telegram", "command_center"],
                    "subject": subject,
                    "trigger_symbol": trigger_symbol,
                    "attribution_symbol": label,
                    "body": body,
                    "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "card_schema": "InvestmentIntelligenceCard@v1",
                    "parse_mode": "HTML",
                }
                last_event = outbox.enqueue(note, actor_id="cio_product_reassessment")
                return {
                    "outbox_enqueued": True,
                    "outbox_notification_id": note["notification_id"],
                    "outbox_event_type": (last_event or {}).get("event_type"),
                    "live_delivery": False,
                    "trigger_symbol": trigger_symbol,
                    "attribution_symbol": label,
                    "cards_enqueued": 0,
                    "raw_dump_suppressed": True,
                }
            reply_markup = None
            try:
                from scripts.lib.cio_telegram_keyboard import (
                    build_intelligence_inline_keyboard,
                )
                reply_markup = build_intelligence_inline_keyboard(card)
            except Exception:
                reply_markup = None
            note = {
                "notification_id": "ntf_prod_" + _digest(pid, sym, changed.get("as_of") or _now()),
                "idempotency_key": f"product_what_changed:{pid}:{sym}",
                "dedupe_key": f"product_what_changed:{pid}:{sym}:{changed.get('as_of') or ''}",
                "message_class": "advisory",
                "channel_targets": ["telegram", "command_center"],
                "subject": str(card.get("headline") or f"CIO · {sym}"),
                "trigger_symbol": trigger_symbol,
                "attribution_symbol": sym,
                "symbol": sym,
                "object_id": card.get("object_id"),
                "body": body,
                "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "card_schema": "InvestmentIntelligenceCard@v1",
                "parse_mode": "HTML",
                "intelligence": {
                    "provenance": (card.get("provenance") or {}),
                    "change": (card.get("change") or {}),
                },
            }
            if reply_markup is not None:
                note["reply_markup"] = reply_markup
            last_event = outbox.enqueue(note, actor_id="cio_product_reassessment")
            enqueued_ids.append(note["notification_id"])
            # Phase 1: DecisionPayload@v1 — flag-gated, fail-soft.
            try:
                from scripts.lib.agent_decision_payload import (
                    emit_decision_payload,
                    payload_from_symbol_intelligence,
                )

                wake_id = f"wake_prod_{pid}_{sym}"
                pl = payload_from_symbol_intelligence(
                    card,
                    wake_id=wake_id,
                    change_item=(card.get("change") if isinstance(card.get("change"), dict) else None),
                )
                emit_decision_payload(pl, role="product_notify")
            except Exception:
                pass

        primary = str(cards[0].get("symbol") or "").upper()
        return {
            "outbox_enqueued": True,
            "outbox_notification_id": enqueued_ids[0] if enqueued_ids else None,
            "outbox_notification_ids": enqueued_ids,
            "outbox_event_type": (last_event or {}).get("event_type"),
            "live_delivery": False,
            "trigger_symbol": trigger_symbol,
            "attribution_symbol": primary,
            "cards_enqueued": len(enqueued_ids),
        }
    except Exception as exc:
        return {
            "outbox_enqueued": False,
            "outbox_error": f"{type(exc).__name__}:{exc}"[:200],
            "live_delivery": False,
        }


def _notify(
    product: dict[str, Any],
    changed: dict[str, Any],
    parent: dict[str, Any],
    *,
    root: Path | str | None = None,
    outbox=None,
) -> dict[str, Any]:
    try:
        try:
            from cio_notification_signal import NotificationStateStore, decide_notification
        except ImportError:
            from scripts.lib.cio_notification_signal import (
                NotificationStateStore,
                decide_notification,
            )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}", "notification_class": "COMMAND_CENTER_ONLY"}
    do_now = bool((product.get("action_book") or {}).get("DO_NOW"))
    reenter = any(
        r.get("governed_verdict") == "RE_ENTER"
        for r in ((product.get("reentry_book") or {}).get("names") or [])
    )
    trigger_symbol = str(parent.get("symbol") or "").upper() or None
    label = notification_attribution_symbol(changed, trigger_symbol)
    decision = {
        "decision_id": product.get("decision_id") or product.get("product_id"),
        "symbol": label,
        "trigger_symbol": trigger_symbol,
        "standing_recommendation": "RESEARCH" if not reenter else "RE_ENTER",
        "current_action": "DO_NOW" if do_now else ("RE_ENTER" if reenter else "WAIT"),
        "act_now": bool(do_now and reenter),
        "blocking_state": None,
        "operator_disposition": "",
    }
    if not changed.get("material"):
        decision["current_action"] = "WAIT"
        decision["act_now"] = False
    nd = decide_notification(decision)
    try:
        NotificationStateStore().record(nd)
    except Exception:
        pass
    enqueue = should_enqueue_product_notification(changed)
    nd["outbox_enqueued"] = False
    nd["live_delivery"] = False
    if not enqueue:
        nd["outbox_skip_reason"] = (
            "non_material_what_changed" if not changed.get("material")
            else "thesis_version_only"
        )
        return nd
    extra = _enqueue_material_product_outbox(
        product, changed, parent, root=root, outbox=outbox,
    )
    nd.update(extra)
    return nd


def reassess_on_research_completed(
    request: dict[str, Any],
    result: dict[str, Any],
    *,
    critique: Optional[dict[str, Any]] = None,
    root: Path | str | None = None,
    env: Optional[dict[str, str]] = None,
    queue: Optional[dict[str, Any]] = None,
    previously_traded: Optional[list[dict[str, Any]]] = None,
    holdings: Optional[dict[str, Any]] = None,
    notify: bool = True,
) -> dict[str, Any]:
    """Reload canonical truth, persist a new product, diff, notify. Idempotent."""
    try:
        from cio_investment_product import build_product, load_brief, persist_product
    except ImportError:
        from scripts.lib.cio_investment_product import build_product, load_brief, persist_product

    parent = recover_parent(request, result)
    result_id = parent.get("result_id") or "missing_result"
    rid = reassessment_id(parent_key=str(parent["parent_key"]), result_id=str(result_id))
    prior_done = already_completed(rid, root=root)
    if prior_done:
        return {
            "ok": True,
            "duplicate": True,
            "reassessment_id": rid,
            "parent": parent,
            "product_id": prior_done.get("product_id"),
            "notification": {"notification_class": "SUPPRESSED", "suppressed_reason": "duplicate_reassessment"},
            "authority": AUTHORITY,
            "financial_action": False,
        }

    out: dict[str, Any] = {
        "ok": False,
        "reassessment_id": rid,
        "parent": parent,
        "duplicate": False,
        "authority": AUTHORITY,
        "financial_action": False,
        "memory_behavior_influence": (env or os.environ).get("MEMORY_BEHAVIOR_INFLUENCE", "0"),
    }
    prior = load_brief(root)
    try:
        # Closed-loop §K: research result → SYMBOL THESIS REASSESSMENT (before product rebuild).
        # Idempotent via reassessment_id; publish only on material content change.
        thesis_review: dict[str, Any] = {"skipped": True}
        sym_for_thesis = str(parent.get("symbol") or result.get("symbol") or "").upper()
        if sym_for_thesis:
            try:
                from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis
                critique_v = str((critique or {}).get("verdict") or "").upper()
                summary = str(result.get("summary") or result.get("answer") or "").strip()
                # Only feed research into thesis when critique is not INSUFFICIENT
                evidence: dict[str, Any] = {
                    "research_result_id": result_id,
                    "result_id": result_id,
                    "financial_truth_refs": list(result.get("evidence_refs") or [])[:12],
                    "fs_receipts": list(result.get("fs_receipts") or [])[:8],
                    "ratified_lessons": list(result.get("lessons") or [])[:8],
                    "memory_refs": list(result.get("memory_refs") or [])[:8],
                }
                if summary and critique_v not in {"INSUFFICIENT", "REJECT", "REJECTED"}:
                    # Append research as evidence_for; do not invent stance
                    evidence["evidence_for"] = [f"research:{result_id}: {summary[:240]}"]
                    # Optional explicit stance/summary only if research payload provides them
                    if result.get("thesis_summary"):
                        evidence["summary"] = str(result.get("thesis_summary"))[:2000]
                    if result.get("thesis_stance"):
                        evidence["stance"] = str(result.get("thesis_stance"))
                    if result.get("research_gaps") is not None:
                        evidence["research_gaps"] = list(result.get("research_gaps") or [])
                    if result.get("counter_evidence") is not None:
                        evidence["counter_evidence"] = list(result.get("counter_evidence") or [])
                thesis_review = reconcile_symbol_thesis(
                    sym_for_thesis,
                    trigger="research_completion",
                    evidence=evidence,
                    root=root,
                    publish=True,
                    notify=False,  # notification governed by product what_changed below
                    actor_id="cio_product_reassessment",
                )
            except Exception as thesis_exc:
                thesis_review = {
                    "ok": False,
                    "error": f"{type(thesis_exc).__name__}:{thesis_exc}",
                    "skipped": False,
                }

        product = build_product(
            root=root,
            env=env,
            queue=queue,
            previously_traded=previously_traded,
            holdings=holdings,
        )
        product["product_id"] = "prod_" + _digest(rid, _now())
        product["previous_product_id"] = (prior or {}).get("product_id") or (prior or {}).get("decision_id")
        product["trigger"] = "RESEARCH_COMPLETED"
        product["source_research_ids"] = [i for i in (parent.get("result_id"), parent.get("research_id")) if i]
        product["parent_run_id"] = parent.get("parent_run_id")
        product["parent_plan_id"] = parent.get("plan_id")
        product["parent_recovery"] = parent.get("status")
        product["symbol_thesis_review"] = {
            k: thesis_review.get(k)
            for k in (
                "classification", "version_published", "old_version", "new_version",
                "thesis_id", "symbol", "error", "skipped",
            )
            if k in thesis_review or thesis_review.get(k) is not None
        }
        _annotate_research(product, result, critique)
        try:
            from scripts.lib.cio_production_eligibility import prior_visible_for_what_changed
            prior_cmp = prior_visible_for_what_changed(prior, product)
        except Exception:
            prior_cmp = prior
        changed = diff_products(prior_cmp, product)
        product["what_changed"] = changed
        persist_product(product, root=root)
        impact = research_impact(
            symbol=str(parent.get("symbol") or ""),
            result_id=str(result_id),
            research_id=str(parent.get("research_id") or ""),
            prior=prior,
            new=product,
            critique=critique,
        )
        _append_jsonl(_paths(root)["impacts"], impact)
        nd = (
            _notify(product, changed, parent, root=root)
            if notify
            else {"notification_class": "COMMAND_CENTER_ONLY", "skipped": True, "outbox_enqueued": False}
        )
        rec = {
            "schema": REASSESS_SCHEMA,
            "reassessment_id": rid,
            "status": "COMPLETED",
            "as_of": product.get("as_of"),
            "product_id": product.get("product_id"),
            "previous_product_id": product.get("previous_product_id"),
            "parent": parent,
            "what_changed_material": changed.get("material"),
            "impact": impact.get("impact"),
            "notification_class": nd.get("notification_class"),
            "authority": AUTHORITY,
        }
        _append_jsonl(_paths(root)["log"], rec)
        _mark("completed", rid, rec, root=root)
        lineage_id = None
        try:
            try:
                from lib.intelligence_lineage import attach_advisory_use
            except Exception:
                from scripts.lib.intelligence_lineage import attach_advisory_use  # type: ignore
            lin = attach_advisory_use(
                research_id=str(parent.get("research_id") or result.get("research_id") or "") or None,
                result_id=str(result_id or "") or None,
                lineage_id=str(result.get("lineage_id") or "") or None,
                product_id=str(product.get("product_id") or "") or None,
                reassessment_id=rid,
                decision_id=str(product.get("decision_id") or "") or None,
                what_changed_material=bool(changed.get("material")),
            )
            lineage_id = lin.get("lineage_id")
            if lineage_id:
                rec["lineage_id"] = lineage_id
                product["lineage_id"] = lineage_id
        except Exception as lin_exc:
            out["lineage_error"] = f"{type(lin_exc).__name__}:{lin_exc}"
        out.update({
            "ok": True,
            "status": "COMPLETED",
            "lineage_id": lineage_id,
            "product": {k: product.get(k) for k in (
                "product_id", "previous_product_id", "decision_id", "as_of",
                "trigger", "what_changed", "summary", "parent_recovery", "lineage_id",
            ) if k in product},
            "impact": impact,
            "notification": nd,
        })
        return out
    except Exception as exc:
        pending = {
            "schema": REASSESS_SCHEMA,
            "reassessment_id": rid,
            "status": "REASSESSMENT_PENDING",
            "as_of": _now(),
            "parent": parent,
            "request": {"plan_id": parent.get("plan_id"), "research_id": parent.get("research_id")},
            "result": {
                "result_id": result.get("result_id"),
                "research_id": result.get("research_id"),
                "symbol": result.get("symbol"),
                "summary": result.get("summary"),
                "status": result.get("status"),
            },
            "critique": critique,
            "retries": 0,
            "error": f"{type(exc).__name__}:{exc}",
            "authority": AUTHORITY,
        }
        _append_jsonl(_paths(root)["pending"], pending)
        _mark("pending", rid, pending, root=root)
        out.update({"ok": False, "status": "REASSESSMENT_PENDING", "error": pending["error"]})
        return out


def retry_pending_reassessments(*, root: Path | str | None = None, limit: int = 5) -> dict[str, Any]:
    """Cheap retry of REASSESSMENT_PENDING. Never reruns paid research."""
    idx = load_index(root)
    pending = dict(idx.get("pending") or {})
    done = 0
    errors = 0
    skipped = 0
    for rid, rec in list(pending.items())[:limit]:
        if already_completed(rid, root=root):
            skipped += 1
            continue
        retries = int(rec.get("retries") or 0)
        if retries >= MAX_PENDING_RETRIES:
            skipped += 1
            continue
        rec["retries"] = retries + 1
        _mark("pending", rid, rec, root=root)
        req = rec.get("request") or {}
        res = rec.get("result") or {}
        parent = rec.get("parent") or {}
        req = {**req, "plan_id": parent.get("plan_id"), "parent_run_id": parent.get("parent_run_id")}
        res = {**res, "result_id": parent.get("result_id") or res.get("result_id")}
        out = reassess_on_research_completed(
            req, res, critique=rec.get("critique"), root=root, notify=True,
        )
        if out.get("ok"):
            done += 1
        else:
            errors += 1
    return {
        "ok": True,
        "retried_ok": done,
        "errors": errors,
        "skipped": skipped,
        "pending_before": len(pending),
        "authority": AUTHORITY,
        "paid_research_repeated": False,
    }


def notify_from_flash_row(
    *,
    symbol: str,
    row_id: Any,
    summary: str = "",
    model: str = "",
    research_type: str = "",
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Cheap CIO product wake after an overnight Flash commit. Never calls a paid LLM."""
    result = {
        "result_id": f"flash_{row_id}",
        "research_id": f"flash_{row_id}",
        "symbol": str(symbol or "").upper(),
        "summary": summary,
        "status": "completed",
        "model_used": model,
        "research_type": research_type,
    }
    return reassess_on_research_completed(
        {}, result, critique={"verdict": "VALID", "confidence": None}, root=root,
    )


def latest_reassessments(*, root: Path | str | None = None, n: int = 12) -> list[dict[str, Any]]:
    path = _paths(root)["log"]
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return list(reversed(rows))
