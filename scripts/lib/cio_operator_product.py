"""CIOOperatorProduct@v1 — one operator-facing product, many renderers."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.atomic_json_store import append_jsonl, atomic_write_json
from scripts.lib.canonical_cognition_bind import bind_market_context
from scripts.lib.canonical_store_registry import load_json_store, resolve_store
from scripts.lib.operator_decision_contract import (
    STANDING_CADENCE_TEMPLATE,
    completeness,
    normalize_decision,
)
from scripts.lib.product_availability import AVAILABLE, UNAVAILABLE_REASONS, availability_payload, canonicalize_reason

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CIOOperatorProduct@v1"
ACTIONS = ("HOLD", "WATCH", "REVIEW", "TRIM", "REENTER", "AVOID", "NO_ACTION", "HOLD_CASH", "WAIT", "INSUFFICIENT_DATA")
WHEN = ("NOW", "TODAY", "NEXT_SESSION", "WATCH_ONLY", "NOTHING", "NONE")
REQUIRED_SECTIONS = (
    "product_id",
    "generation_id",
    "as_of",
    "executive_summary",
    "action_now",
    "decisions",
    "standing_decisions",
    "portfolio",
    "cash",
    "risk",
    "watch",
    "reentry",
    "sector",
    "industry",
    "themes",
    "catalysts",
    "earnings",
    "case_summaries",
    "macro",
    "research_changes",
    "research_gaps",
    "specialist_disagreements",
    "outcomes_learning",
    "data_quality",
    "policy_gaps",
    "next_reviews",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _map_action(raw: str) -> str:
    a = str(raw or "").upper().replace(" ", "_")
    aliases = {
        "RE_ENTER": "REENTER", "HOLD_POSTURE": "HOLD", "WAIT": "WAIT",
        "DO_NOW": "REVIEW", "WATCH_CLOSELY": "WATCH",
    }
    a = aliases.get(a, a)
    return a if a in ACTIONS else "REVIEW"


def _entry_from_rec(row: dict[str, Any], *, generation_id: str | None = None, as_of: str | None = None) -> dict[str, Any]:
    return normalize_decision(row, generation_id=generation_id, as_of=as_of)


def _last_valid_ref(root: Path | str | None) -> dict[str, Any] | None:
    loc = load_json_store("cio.operator_product.current", root=root)
    if loc.get("available") and isinstance(loc.get("data"), dict):
        d = loc["data"]
        if d.get("available") and d.get("schema") == SCHEMA:
            return {
                "product_id": d.get("product_id"),
                "generation_id": d.get("generation_id"),
                "as_of": d.get("as_of"),
                "path": loc.get("path"),
            }
    return None


def unavailable(*, reason: str, detail: str | None = None, path: str | None = None,
                last_valid_product: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = availability_payload(
        reason=reason,
        detail=detail,
        path=path,
        last_valid_product=last_valid_product,
    )
    payload.update({
        "schema": SCHEMA,
        "entries": [],
        "decisions": [],
        "action_now": [],
        "action_now_class": "D",
        "executive_summary_class": "T",
        "earnings": [],
        "case_summaries": {
            "banner": "A-context · NON_AUTHORITATIVE · does not change action",
            "class": "A",
            "count": 0,
            "items": [],
            "changes_action": False,
        },
        "canonical": True,
        "gui_is_projection": True,
    })
    # Preserve explicit INVALID_SCHEMA contract.
    if payload["status"] == "INVALID_SCHEMA":
        payload["operator_data_quality"] = "DEGRADED"
    return payload


def _cash_block_as_of(cash_rows: list[dict[str, Any]], doc: dict[str, Any]) -> dict[str, Any]:
    """Cash block age = oldest contributing balance, never composition time.

    Reuses the capital-plan evidence clock so OP.cash / home.cash / capital_plan
    share one rule. Dollar amounts are not touched here — labelling only (B4).
    """
    try:
        from scripts.lib.cio_capital_plan import cash_evidence_as_of
        return cash_evidence_as_of(cash_rows, doc)
    except Exception:  # noqa: BLE001
        return {
            "as_of": None,
            "oldest_row_as_of": None,
            "newest_row_as_of": None,
            "mixed_ages": False,
            "distinct_stamps": 0,
            "unstamped": True,
            "unstamped_accounts": [],
            "by_account": [],
            "document_as_of": doc.get("as_of") or doc.get("generated_at"),
            "source": "holdings rows where is_cash, oldest stamp wins",
            "note": (
                "The block is as current as its stalest account, never the moment "
                "the builder ran."
            ),
        }


def _holdings_sections(root: Path | str | None) -> dict[str, Any]:
    hloc = load_json_store("portfolio.holdings.current", root=root)
    data_quality = {"state": "OK", "labels": []}
    portfolio: dict[str, Any] = {"holdings_n": 0, "source": "portfolio.holdings.current"}
    cash: dict[str, Any] = {
        "status": "UNKNOWN",
        "as_of": None,
        "cash_as_of": {
            "as_of": None,
            "unstamped": True,
            "note": "holdings unavailable; do not read product as_of as cash age",
        },
        "class": "D",
        "provenance_class": "D",
    }
    if not hloc.get("available"):
        data_quality = {
            "state": "MISSING_REQUIRED_INPUT" if hloc.get("reason") == "PRODUCER_NOT_RUN" else hloc.get("status") or "UNAVAILABLE",
            "labels": ["HOLDINGS_UNAVAILABLE"],
            "note": "LAST_KNOWN_GOOD not present — consumers must not treat this as an empty book.",
        }
        return {"portfolio": portfolio, "cash": cash, "data_quality": data_quality}
    doc = hloc["data"] if isinstance(hloc.get("data"), dict) else {}
    holds = [h for h in (doc.get("holdings") or []) if isinstance(h, dict)]
    if doc.get("write_rejected") or doc.get("sanity_floor_blocked"):
        data_quality = {
            "state": "LAST_KNOWN_GOOD",
            "labels": ["WRITE_REJECTED", "LAST_KNOWN_GOOD"],
            "note": "Incoming holdings write rejected; prior snapshot preserved.",
        }
    cash_rows = [h for h in holds if h.get("is_cash")]
    equity = [h for h in holds if not h.get("is_cash")]
    cash_usd = sum(float(h.get("market_value") or 0) for h in cash_rows)
    equity_usd = sum(float(h.get("market_value") or 0) for h in equity)
    portfolio = {
        "holdings_n": len(equity),
        "equity_usd": round(equity_usd, 2),
        "source": "portfolio.holdings.current",
        "as_of": doc.get("as_of") or doc.get("generated_at"),
        "freshness_note": doc.get("_freshness_note"),
        "class": "D",
        "provenance_class": "D",
    }
    cash_as_of = _cash_block_as_of(cash_rows, doc)
    cash = {
        "cash_usd": round(cash_usd, 2),
        "cash_n": len(cash_rows),
        "status": "PRESENT" if cash_rows else "UNCONFIRMED",
        # B4: own evidence clock — oldest contributing balance, not product as_of.
        "as_of": cash_as_of.get("as_of"),
        "cash_as_of": cash_as_of,
        "class": "D",
        "provenance_class": "D",
    }
    return {"portfolio": portfolio, "cash": cash, "data_quality": data_quality}


def _temperament_display(temp: dict[str, Any], cash: dict[str, Any]) -> dict[str, Any]:
    """Provenance at display for temperament (B5 / W3 3b).

    `portfolio_implication` is a standing-policy constant (class T). It must not
    render as situation guidance. Cash on temperament inherits the cash block's
    own as_of — never the product composition stamp.

    W3 3b: the constant is unconditional across inputs — that is honest only
    when it lives on ``standing_policy_template``, never on a guidance-shaped
    field. Source may already have demoted; this path is idempotent.
    """
    out = dict(temp or {})
    implication = out.get("portfolio_implication")
    already = out.get("standing_policy_template")
    if implication and not out.get("portfolio_implication_is_guidance"):
        out["standing_policy_template"] = implication
        out["standing_policy_template_class"] = out.get("portfolio_implication_class") or "T"
        out["portfolio_implication_is_guidance"] = False
        out["portfolio_implication_role"] = "standing_policy_template"
        # Stop rendering the constant in the guidance-shaped field.
        out["portfolio_implication"] = None
    elif already and not out.get("portfolio_implication_is_guidance"):
        out["standing_policy_template_class"] = out.get(
            "standing_policy_template_class"
        ) or out.get("portfolio_implication_class") or "T"
        out["portfolio_implication"] = None
        out["portfolio_implication_is_guidance"] = False
        out["portfolio_implication_role"] = "standing_policy_template"
    cash_as_of = cash.get("cash_as_of") if isinstance(cash, dict) else None
    if isinstance(cash_as_of, dict):
        out["cash_as_of"] = cash_as_of
        if out.get("cash") is not None or out.get("cash_pct") is not None:
            out.setdefault("as_of", cash_as_of.get("as_of"))
    out.setdefault("cash_class", "D")
    return out


def _ops_degradation(root: Path | str | None) -> dict[str, Any] | None:
    """Ops health enters the product only when it changes investment reliability."""
    from scripts.lib.ops_health_routing import cio_capability_impact
    loc = resolve_store("ops.health", root=root)
    path = Path(loc.get("path") or loc.get("primary_path") or "")
    if not path.exists():
        return None
    return cio_capability_impact(path)


def _generation_id(brief: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    payload = {
        "product_id": brief.get("product_id") or brief.get("decision_id"),
        "final_position": brief.get("final_position"),
        "summary": brief.get("summary") if isinstance(brief.get("summary"), str) else (
            (brief.get("summary") or {}) if isinstance(brief.get("summary"), dict) else None
        ),
        "actions": [(e.get("symbol"), e.get("cio_decision"), e.get("what_should_i_do")) for e in entries],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def build_operator_product(*, root: Path | str | None = None, persist: bool = False,
                           supplemental: dict[str, Any] | None = None) -> dict[str, Any]:
    loc = load_json_store("cio.product.current", root=root)
    last_valid = _last_valid_ref(root)
    if loc.get("reason") == "INVALID_SCHEMA" or loc.get("status") == "INVALID_SCHEMA":
        return unavailable(
            reason="INVALID_SCHEMA",
            detail=str(loc.get("error") or loc.get("reason")),
            path=loc.get("path"),
            last_valid_product=last_valid,
        )
    if not loc.get("available"):
        reason = canonicalize_reason(loc.get("reason") or "PRODUCER_NOT_RUN")
        return unavailable(reason=reason, detail=str(loc.get("reason")), path=loc.get("path"),
                           last_valid_product=last_valid)
    brief = loc["data"] if isinstance(loc.get("data"), dict) else {}
    recs = list(brief.get("recommendations") or [])
    as_of = brief.get("as_of") or _now()
    proto = [_map_action(r.get("recommended_action") or r.get("action") or r.get("title")) for r in recs if isinstance(r, dict)]
    gen = _generation_id(brief, [{"symbol": r.get("symbol"), "cio_decision": a, "what_should_i_do": ""} for r, a in zip((x for x in recs if isinstance(x, dict)), proto)])
    from scripts.lib.cio_advisory_admissibility import gate_recommendation_rows
    hloc = load_json_store("portfolio.holdings.current", root=root)
    holdings_payload = hloc.get("data") if hloc.get("available") and isinstance(hloc.get("data"), dict) else {}
    recs = gate_recommendation_rows(
        [r for r in recs if isinstance(r, dict)],
        holdings=holdings_payload,
    )
    entries = [_entry_from_rec(r, generation_id=gen, as_of=as_of) for r in recs]
    if not entries:
        summary = brief.get("summary")
        if isinstance(summary, dict):
            entries.append(_entry_from_rec({
                "title": summary.get("headline") or "CIO posture",
                "description": summary.get("narrative") or json.dumps(summary, default=str)[:240],
                "recommended_action": brief.get("final_position") or "HOLD",
            }, generation_id=gen, as_of=as_of))
        elif summary:
            entries.append(_entry_from_rec({
                "title": "CIO posture",
                "description": str(summary),
                "recommended_action": brief.get("final_position") or "HOLD",
            }, generation_id=gen, as_of=as_of))

    holdings = _holdings_sections(root)
    ctx = bind_market_context(root=Path(root) if root else Path("."))
    action_now = [e for e in entries if e.get("urgency") == "NOW"]
    standing = [e for e in entries if e.get("decision") in {"HOLD", "HOLD_CASH", "WATCH", "WAIT", "NO_ACTION"}]
    exec_summary = brief.get("summary")
    if isinstance(exec_summary, dict):
        exec_summary = exec_summary.get("headline") or exec_summary.get("narrative") or json.dumps(exec_summary)[:280]
    if not exec_summary:
        exec_summary = brief.get("temperament") or "CIO standing posture."

    reentry = brief.get("reentry_book") if isinstance(brief.get("reentry_book"), dict) else {}
    opportunity = brief.get("opportunity_book") if isinstance(brief.get("opportunity_book"), dict) else {}
    thesis_changes = brief.get("thesis_changes_today") or []
    earnings = brief.get("earnings")
    if isinstance(earnings, dict):
        earnings_items = list(earnings.get("items") or [])
    else:
        earnings_items = list(earnings or [])
    earnings_quality = brief.get("earnings_quality") if isinstance(brief.get("earnings_quality"), dict) else {}
    if not earnings_items:
        try:
            from scripts.lib.cio_investment_product import collect_earnings_events
            # Pass holdings + watch so held names rank first and scope is honest.
            # A bare collect_earnings_events(root=...) labels everything "watch".
            watch_syms: list[str] = []
            for bucket in (
                opportunity.get("watch") if isinstance(opportunity, dict) else None,
                brief.get("watch"),
                ((brief.get("opportunity_book") or {}).get("top") if isinstance(brief.get("opportunity_book"), dict) else None),
            ):
                if not isinstance(bucket, list):
                    continue
                for it in bucket:
                    if isinstance(it, dict) and it.get("symbol"):
                        watch_syms.append(str(it["symbol"]).upper())
                    elif isinstance(it, str) and it.strip():
                        watch_syms.append(it.strip().upper())
            earn = collect_earnings_events(
                root=root,
                holdings=holdings_payload if isinstance(holdings_payload, dict) else None,
                watch_symbols=watch_syms or None,
            )
            earnings_items = list(earn.get("items") or [])
            if not earnings_quality:
                earnings_quality = {
                    "quality": earn.get("quality"),
                    "reason": earn.get("reason"),
                    "as_of": earn.get("as_of"),
                    "source": earn.get("source"),
                    "class": "D",
                }
        except Exception:
            if not earnings_quality:
                earnings_quality = {
                    "quality": "DATA_UNAVAILABLE",
                    "reason": "earnings_collector_unavailable",
                    "class": "D",
                }
    case_summaries = brief.get("case_summaries") or brief.get("research_cases")
    if not isinstance(case_summaries, dict) or not (case_summaries.get("items") or case_summaries.get("count")):
        try:
            from scripts.lib.cio_investment_product import collect_case_summaries
            case_summaries = collect_case_summaries(root=root)
        except Exception:
            case_summaries = {
                "banner": "A-context · NON_AUTHORITATIVE · does not change action",
                "authority_class": "NON_AUTHORITATIVE_CONTEXT",
                "class": "A",
                "source": "durable CASE_SUMMARY ACTIVE",
                "count": 0,
                "items": [],
                "financial_action": False,
                "changes_action": False,
            }

    cov = brief.get("holdings_thesis_coverage")
    # A persisted brief can predate the current coverage schema. Wave 2 slice 12a
    # added dust exclusion, and the old freshness check ("held_n is None") passed
    # happily on a pre-12a block — so /v3/cio/home kept serving held_n=19 with
    # SCHG counted as a hold, hours after the code that excludes it shipped.
    # Treat a block missing the 12a keys as stale and recompute it.
    _cov_is_stale = (
        not isinstance(cov, dict)
        or cov.get("held_n") is None
        or "dust_tickers" not in cov
        or "held_n_including_dust" not in cov
    )
    if _cov_is_stale:
        try:
            from scripts.lib.cio_investment_product import (
                collect_holdings,
                collect_holdings_thesis_coverage,
            )
            cov = collect_holdings_thesis_coverage(holdings=collect_holdings(root), root=root)
        except Exception:
            cov = {
                "held_n": 0,
                "current_n": 0,
                "unavailable_n": 0,
                "items": [],
                "dust_tickers": [],
                "dust_n": 0,
                "held_n_including_dust": 0,
                "instrument_id_n": 0,
                "no_fake_thesis": True,
                "class": "D",
            }

    surface_a = brief.get("surface_a_status")
    if not isinstance(surface_a, dict) or not surface_a.get("items"):
        try:
            from scripts.lib.cio_investment_product import collect_surface_a_status
            surface_a = collect_surface_a_status()
        except Exception:
            surface_a = {
                "schema": "SurfaceAStatus@v1",
                "items": [],
                "counts": {"HELD": 0, "EXITED": 0, "UNAVAILABLE": 0},
                "class": "D",
            }

    data_quality = dict(holdings["data_quality"])
    ops = _ops_degradation(root)
    policy_gaps: list[Any] = []
    if ops and ops.get("affects_investment_reliability"):
        data_quality.setdefault("labels", []).append("CIO_DATA_GAP")
        data_quality["ops_impact"] = ops.get("prose")
        policy_gaps.append(ops.get("prose"))

    if supplemental:
        # Fold Trade AI Brief / morning ops facts — not competing CIO truth.
        extra_ops = {k: supplemental[k] for k in supplemental if k in {
            "health", "stops", "dividends", "paper", "overnight", "closed_trades",
        }}
        if extra_ops:
            data_quality["supplemental_ops"] = extra_ops

    # W3 3b — next_reviews is a judgment register. Only dated catalysts belong.
    # Standing cadence (byte-identical across inputs) is demoted to
    # standing_cadence_template so a constant is not rendered as a schedule.
    dated_reviews = [
        e.get("next_review_at") or e.get("next_review")
        for e in entries
        if e.get("next_review_is_dated_catalyst")
    ]
    has_standing_cadence = any(
        e.get("next_review_role") == "standing_cadence_template"
        or (
            not e.get("next_review_is_dated_catalyst")
            and e.get("standing_cadence_template")
        )
        for e in entries
    )

    product = {
        "schema": SCHEMA,
        "available": True,
        "status": AVAILABLE,
        "reason": None,
        "product_id": brief.get("product_id") or brief.get("decision_id") or f"op_{gen}",
        "generation_id": gen,
        "as_of": brief.get("as_of") or _now(),
        "source_store": "cio.product.current",
        "source_path": loc.get("path"),
        "executive_summary": str(exec_summary),
        "executive_summary_class": "T",
        "action_now": action_now,
        "action_now_class": "D",
        "decisions": entries,
        "standing_decisions": standing,
        "portfolio": holdings["portfolio"],
        "cash": holdings["cash"],
        "risk": brief.get("risk") or {"note": "risk surface is the standing decision list plus holdings last-known-good"},
        "watch": opportunity.get("watch") or brief.get("watch") or [],
        "watch_block_summary": brief.get("watch_block_summary") if isinstance(brief.get("watch_block_summary"), dict) else {},
        "new_position_if": list(
            ((brief.get("action_book") or {}).get("NEW_POSITION_IF") if isinstance(brief.get("action_book"), dict) else None)
            or brief.get("new_position_if")
            or []
        ),
        "holdings_thesis_coverage": cov,
        "surface_a_status": surface_a,
        "temperament": _temperament_display(
            brief.get("temperament") if isinstance(brief.get("temperament"), dict) else {},
            holdings["cash"],
        ),
        "reentry": {
            "count": reentry.get("count"),
            "counts": reentry.get("counts"),
            "note": reentry.get("note"),
            "surface": reentry.get("surface") or "A",
            "scope": reentry.get("scope") or "former holdings vs exit trigger",
            "question": reentry.get("question"),
            "population": reentry.get("population"),
            "precedence": reentry.get("precedence"),
            "not_this_book": reentry.get("not_this_book"),
        },
        "sector": ctx.get("sector") or [],
        "industry": ctx.get("industry") or [],
        "sector_reason": ctx.get("sector_reason"),
        "industry_reason": ctx.get("industry_reason"),
        "catalysts_reason": ctx.get("catalysts_reason"),
        "themes": list(brief.get("themes") or []),
        "catalysts": ctx.get("catalysts") or list(brief.get("catalysts") or []),
        "earnings": earnings_items,
        "earnings_quality": earnings_quality or {"quality": "OK" if earnings_items else "DATA_UNAVAILABLE", "class": "D"},
        "case_summaries": case_summaries,
        "research_cases": case_summaries,
        "macro": brief.get("macro") or brief.get("temperament"),
        "research_changes": thesis_changes if isinstance(thesis_changes, list) else [],
        "research_gaps": list(brief.get("research_gaps") or []),
        "specialist_disagreements": list(brief.get("specialist_disagreements") or []),
        "outcomes_learning": {"source": "cio.outcomes", "influence_from_bug_duplicates": 0},
        "data_quality": data_quality,
        "policy_gaps": policy_gaps,
        "next_reviews": dated_reviews,
        "standing_cadence_template": (
            STANDING_CADENCE_TEMPLATE if has_standing_cadence else None
        ),
        "next_reviews_role": (
            "dated_catalysts" if dated_reviews else "standing_cadence_template"
        ),
        "next_reviews_is_judgment": bool(dated_reviews),
        "entries": entries[:20],
        "competing_products": [],
        "competing_products_removed": True,
        "canonical": True,
        "material": bool(action_now) or any(
            e.get("cio_decision") in {"TRIM", "REENTER", "AVOID", "REVIEW"} for e in entries
        ),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "gui_is_projection": True,
        "operator_data_quality": data_quality.get("state") or "OK",
        "standing_decisions_complete": True,
        # B4/B5 — per-block clocks + display provenance. Product as_of above is
        # composition/brief time; block ages are independent.
        "block_as_of": {
            "cash": (holdings["cash"] or {}).get("as_of"),
            "portfolio": (holdings["portfolio"] or {}).get("as_of"),
            "product_composition": brief.get("as_of") or _now(),
            "note": (
                "Block age is the oldest contributing evidence for that block. "
                "product_composition is when the brief/product was composed — "
                "never read it as cash age."
            ),
        },
        "provenance_footer": {
            "model_produced": False,
            "classes": "D counts/sums · T templates · A case-summary context",
            "writer_means": "author",
            "note": (
                "Deterministic projection of cio.product.current + holdings. "
                "No model produced this operator product. "
                "writer names the author, not the copy step."
            ),
        },
    }
    from scripts.lib.cio_p90_voice import apply_operator_voice
    product = apply_operator_voice(product)
    product["completeness"] = completeness(product)
    product["standing_decisions_complete"] = product["completeness"]["grade"] in {
        "OPERATOR_PRODUCT_COMPLETE", "OPERATOR_PRODUCT_PARTIAL",
    } and not any(f.startswith("decisions") and f.endswith("decision_id") for f in product["completeness"].get("missing") or [])
    if persist:
        out = resolve_store("cio.operator_product.current", root=root)
        path = Path(out["primary_path"])
        atomic_write_json(path, product)
        hist = resolve_store("cio.operator_product.history", root=root)
        append_jsonl(Path(hist["primary_path"]), {
            "as_of": product.get("as_of"),
            "product_id": product.get("product_id"),
            "generation_id": product.get("generation_id"),
            "material": product.get("material"),
        })
        product["persisted_path"] = str(path)
    return product


def persist_operator_product_if_available(
    *,
    root: Path | str | None = None,
    supplemental: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write cio.operator_product.current only when the product is AVAILABLE.

    Refuse persist of UNAVAILABLE so last-good is not overwritten. Probe then
    persist is two builds, one write.
    """
    probe = build_operator_product(root=root, persist=False, supplemental=supplemental)
    receipt: dict[str, Any] = {
        "schema": "OperatorProductRefresh@v1",
        "authority": AUTHORITY,
        "available": bool(probe.get("available")),
        "status": probe.get("status"),
        "product_id": probe.get("product_id"),
        "as_of": probe.get("as_of"),
        "persisted": False,
        "persisted_path": None,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
    if not probe.get("available"):
        receipt["skipped_reason"] = (
            f"product not AVAILABLE (status={probe.get('status')}); "
            "preserving the existing last-valid snapshot"
        )
        return receipt
    written = build_operator_product(root=root, persist=True, supplemental=supplemental)
    receipt["persisted"] = True
    receipt["persisted_path"] = written.get("persisted_path")
    receipt["product_id"] = written.get("product_id")
    receipt["as_of"] = written.get("as_of")
    receipt["status"] = written.get("status")
    return receipt


def render_human(product: dict[str, Any]) -> str:
    from scripts.lib.operator_human_renderer import render_product
    return render_product(product)
