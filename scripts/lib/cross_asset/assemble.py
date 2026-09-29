"""Assemble SymbolDecisionObject from existing store snapshots (best-effort)."""
from __future__ import annotations

from typing import Any

from .expression_router import route_expressions
from .security_research_spine import load_latest as load_spine
from .symbol_decision_object import attach_audit, new_symbol_decision


def assemble_symbol_decision(
    symbol: str,
    *,
    provenance: dict[str, Any] | None = None,
    hermes_result: dict[str, Any] | None = None,
    holdings_row: dict[str, Any] | None = None,
    signal: dict[str, Any] | None = None,
    cio: dict[str, Any] | None = None,
    options_packet: dict[str, Any] | None = None,
    route: bool = True,
    spine_path=None,
    prefer_shared_spine: bool = True,
) -> dict[str, Any]:
    prov = provenance or {}
    hermes = hermes_result or {}
    hold = holdings_row or {}
    sig = signal or {}
    cio_in = cio or {}

    # CIO-owned shared spine wins over silo-local copies when present.
    shared = None
    if prefer_shared_spine:
        shared = load_spine(symbol, path=spine_path)
        if shared is None and hermes:
            # Caller may pass Hermes before spine upsert; still assemble.
            shared = None

    subject = (
        (shared or {}).get("subject_guid")
        or prov.get("subject_guid")
        or hermes.get("subject_guid")
        or cio_in.get("subject_guid")
    )
    issuer = prov.get("issuer_guid") or hermes.get("issuer_guid")

    obj = new_symbol_decision(symbol, subject_guid=subject, issuer_guid=issuer)

    if shared and (shared.get("thesis") or {}).get("summary") and not hermes.get("summary"):
        # Promote shared spine thesis into hermes-shaped fields for one path below.
        hermes = {
            **hermes,
            "summary": (shared.get("thesis") or {}).get("summary"),
            "thesis_stance": (shared.get("thesis") or {}).get("stance"),
            "confidence": (shared.get("thesis") or {}).get("conviction"),
            "result_id": (shared.get("latest_hermes") or {}).get("result_id"),
            "research_id": (shared.get("latest_hermes") or {}).get("research_id"),
            "status": (shared.get("latest_hermes") or {}).get("status") or "completed",
            "subject_guid": shared.get("subject_guid"),
            "as_of": shared.get("as_of"),
        }
        obj["cio_state"]["product_refs"] = list(obj["cio_state"].get("product_refs") or []) + [
            "security_research_spine"
        ]

    # Research / thesis from Hermes result when present
    if hermes:
        obj["research_state"] = {
            "status": hermes.get("status") or "completed",
            "research_id": hermes.get("research_id"),
            "result_id": hermes.get("result_id"),
            "age_hours": None,
            "as_of": hermes.get("as_of") or hermes.get("completed_ts"),
        }
        stance = hermes.get("thesis_stance")
        summary = hermes.get("summary") or hermes.get("recommendation")
        obj["equity_thesis"] = {
            "stance": stance,
            "summary": (str(summary)[:1200] if summary else None),
            "conviction": hermes.get("confidence"),
            "invalidation": list(hermes.get("research_gaps_remaining") or [])[:12],
            "source_refs": [hermes.get("result_id")] if hermes.get("result_id") else [],
            "state": "POPULATED" if summary else "INSUFFICIENT_DATA",
        }
        findings = hermes.get("findings") or []
        regimes = [
            f.get("text")
            for f in findings
            if isinstance(f, dict) and f.get("kind") == "regime"
        ]
        obj["event_state"]["regime"] = regimes[0] if regimes else None
        obj["event_state"]["material_flags"] = [
            str(f.get("id"))
            for f in findings
            if isinstance(f, dict) and f.get("id")
        ][:20]

    # Position
    shares = float(hold.get("shares") or hold.get("qty") or hold.get("quantity") or 0.0)
    obj["position_state"] = {
        "held_shares": shares,
        "accounts": list(hold.get("accounts") or ([hold.get("account")] if hold.get("account") else [])),
        "coverage_100": shares >= 100,
        "cash_available": hold.get("cash_available"),
    }

    # Signal
    kind = str(sig.get("kind") or sig.get("signal_kind") or "none").lower()
    obj["signal_state"] = {
        "kind": kind if kind in {"buy", "hold", "sell", "reentry", "none"} else "none",
        "lane": sig.get("lane"),
        "signal_id": sig.get("signal_id") or sig.get("id"),
        "fired_at": sig.get("fired_at") or sig.get("ts"),
    }

    # CIO passthrough (preserve spine provenance refs)
    product_refs = list(cio_in.get("product_refs") or [])
    if shared and "security_research_spine" not in product_refs:
        if (shared.get("thesis") or {}).get("summary") or shared.get("latest_hermes"):
            product_refs.append("security_research_spine")
    obj["cio_state"] = {
        "situation_ids": list(cio_in.get("situation_ids") or []),
        "product_refs": product_refs,
        "advisory_stance": cio_in.get("advisory_stance"),
    }

    # Options packet embed (reference, not rewrite)
    if options_packet:
        obj["options_state"]["packets"] = [
            {
                "schema": options_packet.get("schema"),
                "symbol": symbol.upper(),
                "cio_status": (options_packet.get("cio") or {}).get("status"),
            }
        ]

    if route and obj["signal_state"]["kind"] != "none":
        ranked = route_expressions(
            obj["signal_state"]["kind"],
            position_state=obj["position_state"],
            options_hints={"has_packet": bool(options_packet)},
        )
        obj["expression_comparison"] = {
            "ranked": ranked,
            "top_family": (ranked[0]["family"] if ranked else None),
            "shadow_only": True,
            "as_of": obj["identity"]["as_of"],
        }

    return attach_audit(obj, actor="cross_asset.assemble", action="assembled")
