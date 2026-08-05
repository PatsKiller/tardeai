"""Live multi-symbol Rockville projection from decision_packets + canonical sources.

Production path must NOT inject fixtures. Fixtures stay in tests only.
Uses db_adapter (same as portfolio server), not ad-hoc .env password parsing.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Bounded default operator set for foundation acceptance
DEFAULT_PRIORITY_SYMBOLS = ("FTH", "NUAI", "AXTI", "SWBI", "CECO", "PFLT")

# Hard identity guard: FTH is Faeth, never Fate (FATE)
FTH_CANONICAL_COMPANY = "Faeth Therapeutics, Inc."
FTH_FORBIDDEN_NAMES = frozenset({
    "fate therapeutics",
    "fate therapeutics inc",
    "fate therapeutics, inc.",
    "fate therapeutics inc.",
})


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _sha(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _canonical_company_name(desc: str | None, symbol: str = "") -> str | None:
    """Legal/display name only — never full description_1s prose."""
    d = (desc or "").strip()
    if not d:
        return None
    low = d.lower()
    if low.startswith("faeth therapeutics") or symbol.upper() == "FTH":
        return FTH_CANONICAL_COMPANY
    # Cut at common company-description continuations
    for sep in (
        ", a ", ", an ", " provides ", " is a ", " is an ", " engages ",
        " specializes ", " operates ", " develops ", " focuses ",
    ):
        i = low.find(sep)
        if i > 8:
            return d[:i].strip().rstrip(",")
    if ". " in d:
        first = d.split(". ", 1)[0].strip().rstrip(".")
        if len(first) <= 80:
            return first
    # First comma clause if short enough to be a name
    head = d.split(",", 1)[0].strip()
    if 2 <= len(head) <= 80 and " provides " not in head.lower():
        return head
    return head[:80] if head else None


def batch_identity(symbols: list[str]) -> dict[str, dict]:
    """One query for company/sector/industry from symbol_profiles."""
    out: dict[str, dict] = {s.upper(): {} for s in symbols}
    if not symbols:
        return out
    try:
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT upper(symbol), description_1s, sector, industry
              FROM symbol_profiles
             WHERE upper(symbol) = ANY(%s)
            """,
            ([s.upper() for s in symbols],),
        )
        for sym, desc, sector, industry in cur.fetchall() or []:
            d = (desc or "").strip()
            company = _canonical_company_name(d, sym)
            out[sym] = {
                "company": company,
                "company_summary": d[:280] if d else None,
                "sector": sector,
                "industry": industry,
                "identity_source": "symbol_profiles",
            }
    except Exception as e:
        for s in out:
            out[s]["identity_error"] = type(e).__name__
    # FTH guard
    if "FTH" in out:
        c = (out["FTH"].get("company") or "").strip().lower()
        if not c or c in FTH_FORBIDDEN_NAMES or c.startswith("fate "):
            out["FTH"]["company"] = FTH_CANONICAL_COMPANY
            out["FTH"]["identity_source"] = "canonical_fth_guard"
        out["FTH"].setdefault("sector", "Healthcare")
        out["FTH"].setdefault("industry", "Biotechnology")
    return out


def batch_market(symbols: list[str]) -> dict[str, dict]:
    """Canonical Watch quote artifact — shared CASE-bound selector.

    See scripts/lib/watch_canonical_quote.py. Identity always matches the winning branch.
    """
    from lib.watch_canonical_quote import batch_canonical_quotes
    try:
        return batch_canonical_quotes(symbols)
    except Exception as e:
        return {
            s.upper(): {
                "last": None,
                "day_change_pct": None,
                "price_source": None,
                "price_as_of": None,
                "quote_id": None,
                "source_record_id": None,
                "market_session": None,
                "freshness_state": "DATA_UNAVAILABLE",
                "market_state": "DATA_UNAVAILABLE",
                "missing": ["canonical_market_quote"],
                "market_error": type(e).__name__,
            }
            for s in symbols
        }


def _verification_stages(packet: dict) -> dict[str, Any]:
    """Independent pipeline stage fields for ticket verification truthfulness."""
    tr = packet.get("ticket_review") or {}
    rec = tr.get("reconciled") or {}
    cap = packet.get("current_actionable_plan")
    tv = (cap or {}).get("ticket_validation") or {}
    # quality may live on validation or packet
    q = tv.get("quality_admission") or packet.get("quality_admission") or {}
    if not q and rec.get("detail") and "quality admission" in str(rec.get("detail") or "").lower():
        q = {"state": "FAIL", "reasons": [rec.get("detail")]}

    # Compilation: packet exists with plan families → PASS
    has_fams = bool(packet.get("plan_families"))
    compilation = "PASS" if has_fams else "NOT_RUN"

    tv_state = str(tv.get("state") or "").upper()
    if not tv and rec.get("deterministic") == "FAIL":
        # Failure may be quality-only without ticket_validation object
        ticket_validation_status = "NOT_APPLICABLE"
    elif not tv_state:
        ticket_validation_status = "NOT_RUN"
    else:
        ticket_validation_status = tv_state

    q_state = str(q.get("state") or q.get("admission") or q.get("verdict") or "").upper()
    detail = str(rec.get("detail") or "").lower()
    if not q_state:
        if "quality admission" in detail or "float" in detail or "atr" in detail:
            q_state = "FAIL"
        elif rec.get("state") == "DETERMINISTIC_FAIL" and ticket_validation_status == "FAIL":
            q_state = "UNKNOWN"
        else:
            q_state = "NOT_RUN"
    quality_admission_status = q_state if q_state else "NOT_RUN"

    rec_state = str(rec.get("state") or "").upper()
    if rec_state == "DETERMINISTIC_FAIL":
        reconciliation_status = "FAIL_CLOSED"
    elif rec_state:
        reconciliation_status = rec_state
    else:
        reconciliation_status = "NOT_RUN"

    # Reason codes
    reasons: list[str] = []
    blob = " ".join(
        [
            str(rec.get("detail") or ""),
            " ".join(str(x) for x in (tv.get("hard_failures") or [])),
            " ".join(str(x) for x in (q.get("reasons") or q.get("blockers") or [])),
        ]
    ).lower()
    if "float" in blob and ("20" in blob or "low-float" in blob or "below" in blob):
        reasons.append("LOW_FLOAT_EXCLUSION")
    if "atr" in blob or "volatility" in blob or "extreme" in blob:
        reasons.append("EXTREME_VOLATILITY_EXCLUSION")
    for hf in (tv.get("hard_failures") or []):
        code = re.sub(r"[^A-Z0-9]+", "_", str(hf).upper())[:48]
        if code and code not in reasons:
            reasons.append(code)

    # Which stage drove fail-closed
    primary_failed_stage = None
    if quality_admission_status == "FAIL":
        primary_failed_stage = "quality_admission"
    elif ticket_validation_status == "FAIL":
        primary_failed_stage = "ticket_validation"
    elif reconciliation_status == "FAIL_CLOSED":
        primary_failed_stage = "reconciliation"

    return {
        "deterministic_compilation_status": compilation,
        "ticket_validation_status": ticket_validation_status,
        "quality_admission_status": quality_admission_status,
        "reconciliation_status": reconciliation_status,
        "primary_failed_stage": primary_failed_stage,
        "primary_reason_codes": reasons,
        "reconciled_state": rec_state or None,
        "reconciled_detail": (rec.get("detail") or None),
    }


def _selection_reason(symbol: str, decision: dict, held: bool) -> str:
    st = decision.get("primary_state")
    if symbol == "FTH":
        return "foundation_acceptance_symbol + DETERMINISTIC_FAIL regression"
    if held:
        return "held_position_attention"
    if st == "DETERMINISTIC_FAIL":
        return "deterministic_fail_queue"
    if st == "READY":
        return "proposal_eligible"
    if st == "WAIT":
        return "conditional_watch"
    if st == "STALE":
        return "stale_inputs"
    return "bounded_priority_set"


def build_live_cards(
    symbols: list[str] | None = None,
    *,
    include_held: bool = True,
) -> dict[str, Any]:
    """Build Rockville priority cards from live decision_packets only."""
    import shadow_decision_service as svc
    from lib.rockville.decision_projection import project_watch_decision
    from lib.rockville.material_fingerprint import (
        build_symbol_material_fingerprint,
        build_watchlist_material_hash,
    )

    syms = list(symbols or DEFAULT_PRIORITY_SYMBOLS)
    # Ensure one held if requested
    held_set: set[str] = set()
    try:
        hpath = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
        if hpath.exists():
            hd = json.loads(hpath.read_text())
            for h in hd.get("holdings") or []:
                if h.get("is_cash"):
                    continue
                s = str(h.get("symbol") or "").upper()
                if s:
                    held_set.add(s)
    except Exception:
        pass
    if include_held and held_set and not any(s in held_set for s in syms):
        # prefer PFLT if held else first held equity-like
        pick = "PFLT" if "PFLT" in held_set else sorted(held_set)[0]
        if pick not in syms:
            syms.append(pick)

    identity = batch_identity(syms)
    market = batch_market(syms)

    cards = []
    fps = []
    errors = []
    for rank, sym in enumerate(syms, start=1):
        try:
            rb = svc.readback(sym)
        except Exception as e:
            errors.append({"symbol": sym, "error": type(e).__name__})
            continue
        if not rb.get("ok"):
            errors.append({"symbol": sym, "error": rb.get("error") or "no_packet"})
            # Explicit missing — do not fixture-fill
            cards.append({
                "symbol": sym,
                "priority_rank": rank,
                "selection_reason": "requested_but_no_live_packet",
                "missing_components": ["decision_packet"],
                "packet_id": None,
                "decision": {
                    "schema_version": "watch_decision.v1",
                    "symbol": sym,
                    "primary_state": "DATA_UNAVAILABLE",
                    "operator_meaning": "No live decision packet",
                    "allowed_action_now": "REFRESH INPUTS",
                    "proposal_allowed": False,
                    "current_mechanics_visible": False,
                    "blockers": [{"code": "NO_PACKET", "message": str(rb.get("error") or "no packet"), "source": "readback"}],
                    "current_mechanics": None,
                    "wait_contract": None,
                    "visibility": {
                        "trigger_visible": False,
                        "entry_visible": False,
                        "stop_or_invalidation_visible": False,
                        "targets_visible": False,
                        "risk_reward_visible": False,
                    },
                    "verification_stages": {
                        "deterministic_compilation_status": "NOT_RUN",
                        "ticket_validation_status": "NOT_RUN",
                        "quality_admission_status": "NOT_RUN",
                        "reconciliation_status": "NOT_RUN",
                    },
                    "provenance": {"source": "rockville.live_projection", "projection_version": "rockville-live-v1"},
                },
                "company": identity.get(sym, {}).get("company"),
                "sector": identity.get(sym, {}).get("sector"),
                "last": market.get(sym, {}).get("last"),
                "day_change_pct": market.get(sym, {}).get("day_change_pct"),
                "price_source": market.get(sym, {}).get("price_source"),
                "price_as_of": market.get(sym, {}).get("price_as_of"),
                "market_ts": market.get(sym, {}).get("price_as_of"),
                "held": sym in held_set,
                "live": True,
                "fixture": False,
            })
            continue

        packet = rb["packet"]
        packet_id = rb.get("packet_id")
        # action policy optional
        ap = None
        try:
            import decision_action_policy as dap
            ap = dap.evaluate_action(packet, packet_id=packet_id)
        except Exception:
            ap = packet.get("action_policy")

        held = sym in held_set or bool((packet.get("ownership") or {}).get("held"))
        packet = dict(packet)
        if held:
            own = dict(packet.get("ownership") or {})
            own["held"] = True
            packet["ownership"] = own

        stages = _verification_stages(packet)
        packet["verification_stages"] = stages

        # Recompute presentation into packet for consistency (does not mutate DB)
        try:
            import operator_presentation as opres
            op = opres.build(packet, ap)
            op["verification_stages"] = stages
            packet["operator_presentation"] = op
        except Exception:
            pass

        dec = project_watch_decision(packet, ap, symbol=sym)
        dec["verification_stages"] = stages
        if dec.get("primary_state") == "DETERMINISTIC_FAIL" and stages.get("primary_reason_codes"):
            dec["primary_reason_codes"] = stages["primary_reason_codes"]
        if dec.get("primary_state") == "DETERMINISTIC_FAIL" and not dec.get("blockers"):
            detail = stages.get("reconciled_detail") or ""
            parts = [p.strip() for p in re.split(r"[;|]", detail) if p.strip()]
            dec["blockers"] = [
                {"code": "QUALITY_ADMISSION", "message": p, "source": "reconciled"}
                for p in parts[:4]
            ] or [{"code": "DETERMINISTIC_FAIL", "message": "Deterministic validation failed", "source": "reconciled"}]
            dec["blocking_drivers"] = [b["message"] for b in dec["blockers"]][:3]

        ident = identity.get(sym) or {}
        mkt = market.get(sym) or {}
        company = ident.get("company")
        if sym == "FTH" and (not company or str(company).lower() in FTH_FORBIDDEN_NAMES or str(company).lower().startswith("fate ")):
            company = FTH_CANONICAL_COMPANY

        missing = list(mkt.get("missing") or [])
        if not company:
            missing.append("identity")
        if mkt.get("last") is None or mkt.get("price_as_of") is None:
            if "canonical_market_quote" not in missing:
                missing.append("canonical_market_quote")
        if not packet.get("technical_state"):
            missing.append("technicals")
        if not (packet.get("fundamentals") or packet.get("fundamental_state")):
            missing.append("fundamentals")

        fp_payload = {
            "symbol": sym,
            "decision": dec,
            "validation": (packet.get("current_actionable_plan") or {}).get("ticket_validation") or {},
            "quality": packet.get("quality_admission") or {},
            "ownership": {"held": held},
            "freshness": packet.get("freshness") or {},
            "technical": packet.get("technical_state") or {},
            "fundamentals": packet.get("fundamentals") or {},
            "catalysts": packet.get("event_state") or {},
            "contract": packet.get("current_actionable_plan") or {},
            "quote_id": mkt.get("quote_id"),
            "last": mkt.get("last"),
            "price_as_of": mkt.get("price_as_of"),
        }
        fp = build_symbol_material_fingerprint(fp_payload)
        fps.append(fp)

        cards.append({
            "symbol": sym,
            "priority_rank": rank,
            "selection_reason": _selection_reason(sym, dec, held),
            "packet_id": packet_id,
            "snapshot_id": (packet.get("current_input_snapshot") or {}).get("snapshot_id") or packet.get("input_snapshot_id"),
            "validation_id": ((packet.get("current_actionable_plan") or {}).get("ticket_validation") or {}).get("ticket_hash"),
            "material_fingerprint": fp.get("material_fingerprint"),
            "current_state": dec.get("primary_state"),
            "next_review": dec.get("next_deterministic_review_condition") or (ap or {}).get("next_review"),
            "missing_components": missing,
            "company": company,
            "company_summary": ident.get("company_summary"),
            "sector": ident.get("sector"),
            "industry": ident.get("industry"),
            "identity_source": ident.get("identity_source"),
            "last": mkt.get("last"),
            "day_change_pct": mkt.get("day_change_pct"),
            "price_source": mkt.get("price_source"),
            "price_as_of": mkt.get("price_as_of"),
            "market_ts": mkt.get("price_as_of"),
            "quote_id": mkt.get("quote_id"),
            "source_record_id": mkt.get("source_record_id"),
            "market_session": mkt.get("market_session"),
            "freshness_state": mkt.get("freshness_state"),
            "market_state": mkt.get("market_state"),
            "held": held,
            "decision": dec,
            "verification_stages": stages,
            "live": True,
            "fixture": False,
            "packet_generated_at": rb.get("generated_at"),
        })

    return {
        "ok": True,
        "schema": "watch_priority.v1",
        "source": "live_decision_packets",
        "fixture_injected": False,
        "generated_at": datetime.now(ET).isoformat(),
        "watchlist_material_hash": build_watchlist_material_hash(fps) if fps else None,
        "cards": cards,
        "count": len(cards),
        "errors": errors,
    }


def build_live_symbol(symbol: str) -> dict[str, Any]:
    res = build_live_cards([symbol.upper()], include_held=False)
    cards = res.get("cards") or []
    if not cards:
        return {
            "ok": False,
            "error": "symbol_not_available",
            "symbol": symbol.upper(),
            "detail": (res.get("errors") or [{}])[0],
        }
    card = cards[0]
    return {
        "ok": True,
        "symbol": card["symbol"],
        "company": card.get("company"),
        "company_summary": card.get("company_summary"),
        "sector": card.get("sector"),
        "industry": card.get("industry"),
        "last": card.get("last"),
        "day_change_pct": card.get("day_change_pct"),
        "price_source": card.get("price_source"),
        "price_as_of": card.get("price_as_of"),
        "market_ts": card.get("market_ts"),
        "quote_id": card.get("quote_id"),
        "source_record_id": card.get("source_record_id"),
        "market_session": card.get("market_session"),
        "freshness_state": card.get("freshness_state"),
        "market_state": card.get("market_state"),
        "identity_source": card.get("identity_source"),
        "held": card.get("held"),
        "packet_id": card.get("packet_id"),
        "material_fingerprint": card.get("material_fingerprint"),
        "decision": card.get("decision"),
        "verification_stages": card.get("verification_stages"),
        "missing_components": card.get("missing_components"),
        "live": True,
        "fixture": False,
        "flags": None,  # filled by API layer
    }
