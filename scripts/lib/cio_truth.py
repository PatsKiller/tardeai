"""CIO display truth over existing registered projections; no store or authority.

All functions are read-only. Callers may inject projections for fixture rendering.
Missing evidence stays None with a reason. No provider, broker or execution calls.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import hashlib
import math
from pathlib import Path
from typing import Any

from .account_display import canonical_key, account_label, location_facts


def _number(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _timestamp(value) -> datetime | None:
    if value is None:
        return None
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _evidence(source, as_of, now, *, reason=None, max_age_h=26) -> dict:
    at = _timestamp(as_of)
    age = (now - at).total_seconds() / 3600 if at else None
    return {"source": source, "as_of": at.isoformat() if at else None,
            "age_hours": round(age, 3) if age is not None else None,
            "stale": age is None or age < 0 or age > max_age_h,
            "gap": {"reason": reason} if reason else None}


def _sum_known(rows, key) -> float | None:
    values = [_number(r.get(key)) for r in rows]
    return round(sum(values), 2) if all(v is not None for v in values) else None


def portfolio_for(holdings_doc: dict, *, now: datetime | None = None) -> dict:
    """One holdings aggregate for every display, including all account rows.

    Total/value/day P&L come from holdings rows, not stale account summaries or
    another quote clock. A missing non-cash day change is unknown, not zero.
    Position count is distinct held account+symbol, non-cash, value >= $100.
    """
    from .portfolio_positions import is_cash
    now = now or datetime.now(timezone.utc)
    rows = []
    for raw in holdings_doc.get("holdings") or []:
        r = deepcopy(raw)
        r["account_id"] = canonical_key(r.get("account") or r.get("account_id"))
        r["account_label"] = account_label(r["account_id"])
        r["is_cash"] = is_cash(r)
        if r["is_cash"] and r.get("day_change") is None:
            r["day_change"] = 0.0
        rows.append(r)
    total = _sum_known(rows, "market_value") if rows else None
    cash = _sum_known([r for r in rows if r["is_cash"]], "market_value") if rows else None
    day = _sum_known(rows, "day_change") if rows else None
    at = holdings_doc.get("last_repriced") or holdings_doc.get("generated_at") or holdings_doc.get("as_of")
    noncash = [r for r in rows if not r["is_cash"] and not r.get("is_loan")]
    held = [r for r in noncash if (_number(r.get("shares", r.get("quantity"))) or 0) > 0]
    counted = [r for r in held if (_number(r.get("market_value")) or 0) >= 100]
    keys = {(r["account_id"], str(r.get("symbol") or "").upper()) for r in counted}
    accounts = []
    summaries = {canonical_key(k): v for k, v in (holdings_doc.get("account_summaries") or {}).items()}
    for account in sorted({r["account_id"] for r in rows}):
        group = [r for r in rows if r["account_id"] == account]
        summary = summaries.get(account) or {}
        dates = [_timestamp(r.get("broker_position_as_of_at") or r.get("broker_position_as_of") or r.get("as_of")) for r in group]
        dates = [d for d in dates if d]
        accounts.append({"account_id": account, "account_label": account_label(account),
                         "total_usd": _sum_known(group, "market_value"),
                         "cash_usd": _sum_known([r for r in group if r["is_cash"]], "market_value"),
                         "day_pl_usd": _sum_known(group, "day_change"),
                         "status": summary.get("state") or "UNCLASSIFIED",
                         "as_of": min(dates).isoformat() if dates else None})
    reason = "holdings unavailable" if not rows else (
        "holding value or day P&L missing" if total is None or day is None else None)
    return {"total_usd": total, "cash_usd": cash, "day_pl_usd": day,
            "positions_as_of": holdings_doc.get("positions_built_at") or holdings_doc.get("data_as_of"),
            "valuation_as_of": holdings_doc.get("generated_at"), "quote_as_of": holdings_doc.get("last_repriced"),
            "quote_source": holdings_doc.get("reprice_source"),
            "day_pl_pct": round(day / (total - day) * 100, 3)
            if total is not None and day is not None and total - day > 0 else None,
            "position_count": len(keys) if rows else None,
            "position_counts": {"definition": "held non-cash account+symbol with market_value >= 100",
                                "all_rows": len(rows), "cash_rows": sum(r["is_cash"] for r in rows),
                                "non_cash_rows": len(noncash), "held_rows": len(held),
                                "below_100": len(held) - len(counted), "counted": len(keys),
                                "excluded_cusip_zero": sum(1 for r in noncash if len(str(r.get("symbol") or "")) == 9
                                                           and (_number(r.get("market_value")) or 0) == 0)},
            "accounts": accounts, "holdings": rows,
            "stored_totals": deepcopy(holdings_doc.get("portfolio_totals") or {}),
            **_evidence("portfolio_positions.load_store canonical holdings", at, now, reason=reason)}


_ACTIVE_STOP_STATES = {"active", "working", "open", "new", "accepted", "partially_filled"}
_PENDING_STOP_STATES = {"pending_activation", "pending", "awaiting_parent_order", "awaiting_condition",
                        "pending_new", "queued", "awaiting_manual_review"}
_DEAD_STOP_STATES = {"canceled", "cancelled", "rejected", "expired", "replaced", "not_in_read"}


def stop_for(account: str, symbol: str, *, broker_rows=None, planned=None, now=None) -> dict:
    """Display-only stop precedence by canonical account+symbol, including state.

    ``broker_rows`` are persisted stop_last_known observations, never a broker
    request. Terminal observations cannot become active protection. A planned
    level is displayed but does not prove a resting broker order exists.
    """
    now = now or datetime.now(timezone.utc)
    account, symbol = canonical_key(account), str(symbol or "").upper()
    matches = [r for r in (broker_rows or []) if canonical_key(r.get("account")) == account
               and str(r.get("symbol") or "").upper() == symbol]
    # The newest observation for each order wins. Retain a filled observation
    # when no working or pending order remains, so awaiting sync stays visible.
    latest = {}
    for r in matches:
        key = str(r.get("order_id") or "position")
        if key not in latest or str(r.get("captured_at") or "") > str(latest[key].get("captured_at") or ""):
            latest[key] = r
    viable = [r for r in latest.values() if str(r.get("status") or "").lower() not in _DEAD_STOP_STATES]
    row = max(viable, key=lambda r: str(r.get("captured_at") or ""), default={})
    raw_state = str(row.get("status") or "").lower().replace(" ", "_")
    state = ("active" if raw_state in _ACTIVE_STOP_STATES else "pending_activation" if raw_state in _PENDING_STOP_STATES
             else "filled" if raw_state == "filled" else "unknown" if row else "none")
    sp = _number(row.get("stop_price"))
    source = "broker_resting" if row else "none"
    at = row.get("captured_at")
    if not row and planned:
        for key in (f"{symbol}:{account}", symbol):
            candidates = [(k, v) for k, v in planned.items() if str(k).split(":")[0].upper() == symbol
                          and (k == key or (":" in str(k) and canonical_key(str(k).split(":", 1)[1]) == account))]
            for _, p in candidates:
                if isinstance(p, dict) and canonical_key(p.get("account")) in ("", "all", account):
                    sp = _number(p.get("stop_price", p.get("stop")))
                    if sp is not None:
                        source, at = "planned", p.get("set_date") or p.get("as_of")
                        break
            if source == "planned":
                break
    meta = _evidence("stop_last_known" if row else "stops.json", at, now,
                     reason="stop state not recorded" if state == "unknown" else None)
    return {"account_id": account, "account_label": account_label(account), "symbol": symbol,
            "stop_price": sp, "stop_source": source, "stop_state": state,
            "stop_status_raw": row.get("status"), "stop_captured_at": meta["as_of"],
            "broker_protected": state == "active" and sp is not None and sp > 0,
            "stop_qty": _number(row.get("qty")), "order_id": row.get("order_id"), **meta}


_SOURCE_LABELS = {"cio_opportunity_projection": "CIO opportunity review", "cio_decisions": "CIO decision",
                  "cio_entry_states": "Trade AI entry check", "security_research_spine": "CIO research memory",
                  "hermes_watchlist_lifecycle": "Research watch review", "cio_instrument_records": "CIO record",
                  "decision_engine": "CIO decision engine", "watch_review": "Watch review"}


def _conflict_view(guid, row, raw, review) -> dict:
    field = str(raw.get("field") or "stance")
    values = deepcopy(raw.get("values") or [])
    if not values:
        values = [{"source": "cio_instrument_records", "value": row.get(field, row.get("stance")),
                   "at": row.get("as_of")},
                  {"source": raw.get("source"), "value": raw.get("value", raw.get("stance")),
                   "at": raw.get("as_of") or raw.get("at")}]
    sides = [{"source": v.get("source"), "source_label": _SOURCE_LABELS.get(v.get("source"),
               str(v.get("source") or "Source unavailable").replace("_", " ")),
              "value": v.get("value"), "as_of": v.get("at") or v.get("as_of")} for v in values]
    stable = json.dumps([guid, field, [(v["source"], v["value"]) for v in sides]], sort_keys=True, default=str)
    cid = raw.get("conflict_id") or raw.get("id") or "conflict-" + hashlib.sha256(stable.encode()).hexdigest()[:20]
    resolved = bool(raw.get("resolved") and review.get("resolution_proven") and review.get("conflict_id") in (None, cid))
    severity = raw.get("severity")
    if severity not in ("P0", "P1", "P2", "P3"):
        severity = None  # Classification belongs exclusively to the conflict engine.
    summary = " · ".join(f"{s['source_label']}: {s['value'] if s['value'] is not None else 'not recorded'}" for s in sides)
    return {"id": cid, "security_guid": guid, "field": field, "label": field.replace("_", " ").capitalize(),
            "severity": severity, "summary": summary, "sides": sides,
            "source_a": sides[0] if sides else None, "source_b": sides[1] if len(sides) > 1 else None,
            "blocker": raw.get("blocker") or raw.get("note") or "Sources disagree; a recorded CIO review is needed.",
            "clear_condition": raw.get("clear_condition") or "A CIO decision that cites the conflicting evidence and confirms the record.",
            "resolved": resolved, "blocks_action": not resolved,
            "evidence_refs": deepcopy(raw.get("evidence_refs") or []), "gap": {"reason": "source value or timestamp unavailable"}
            if any(s["value"] is None or not s["as_of"] for s in sides) else None}


def _review_view(row) -> dict:
    raw = (row.get("research") or {}).get("review_lifecycle") or row.get("review_lifecycle") or {}
    fields = ("status", "request_id", "created_at", "requested_at", "researching_at", "answered_at", "completed_at",
              "conflict_resolved_at", "updated_at", "research_id", "old_stance", "new_stance", "reason", "evidence_refs", "conflict_id",
              "readback_verification")
    out = {k: deepcopy(raw.get(k)) for k in fields}
    proven = bool(out["status"] == "CONFLICT_RESOLVED" and out["request_id"]
                  and out["conflict_resolved_at"] and out["evidence_refs"]
                  and out["readback_verification"] == "CIO-owned linked publication and canonical record agree"
                  and str(out["new_stance"] or "").upper() == str(row.get("stance") or "").upper()
                  and all(c.get("resolved") for c in row.get("conflicts") or []))
    out["resolution_proven"] = proven
    out["state"] = ("decided" if proven else "researching" if out["status"] == "RESEARCHING"
                    else "awaiting_decision" if out["status"] == "ANSWERED_PENDING_CIO"
                    else "queued" if out["status"] == "REQUESTED" else "failed" if out["status"] == "FAILED"
                    else "blocked" if out["status"] == "BLOCKED" else "unknown")
    out["gap"] = {"reason": "canonical review lifecycle unavailable"} if not raw else None
    return out


def _material_clock(row) -> tuple[str | None, list[dict], str | None]:
    """Oldest material evidence clock, never the projection's assembly time.

    W10 owns freshness thresholds. Naive/unreadable input times remain missing
    so its T1/R1 adapter can emit DATA_ERROR rather than invent a UTC offset.
    """
    from .cio_company_facts import timestamp
    explicit = row.get("inputs_as_of")
    components = [{"source": c.get("source"), "value": c.get("value"),
                   "as_of": c.get("evidence_at"), "weight": c.get("weight")}
                  for c in (row.get("conviction_components") or {}).values()
                  if isinstance(c, dict) and c.get("value") is not None and (_number(c.get("weight")) or 0) > 0]
    raw = [explicit] if explicit is not None else [c["as_of"] for c in components] if components else [row.get("evidence_at")]
    dates = [timestamp(value) for value in raw]
    if not dates or any(value is None for value in dates):
        return None, components, "oldest material input time unavailable or lacks timezone"
    return min(dates).isoformat(), components, None


def stance_for(security_guid: str, *, db_query=None, now: datetime | None = None,
               projection: dict[str, Any] | None = None, **projection_kwargs) -> dict[str, Any]:
    """One GUID's CIO stance/conviction, conflicts and provenance.

    Wraps data_broker.cio_prospect, including its store/shadow admission and
    freshness rules. A symbol match is never a substitute for a GUID match.
    ``projection`` is the unmodified get_prospects response for batch consumers.
    Lower-level advice remains in conflicts; it never replaces the CIO stance.
    """
    guid = str(security_guid or "").strip()
    if projection is None and guid:
        from .data_broker.cio_prospect import get_prospects
        projection = get_prospects(db_query=db_query, symbols=[guid], now=now, **projection_kwargs)
    doc = projection or {}
    rows = [r for r in doc.get("prospects", []) if str(r.get("security_guid") or "") == guid and guid]
    row = max(rows, key=lambda r: (int(r.get("revision") or 0), str(r.get("as_of") or "")), default={})
    missing = not row or row.get("stance") is None or row.get("conviction") is None
    material_at, material_inputs, material_gap = _material_clock(row)
    review = _review_view(row)
    conflicts = [_conflict_view(guid, row, c, review) for c in row.get("conflicts") or [] if isinstance(c, dict)]
    conflicts = sorted({c["id"]: c for c in conflicts}.values(), key=lambda c: (c["resolved"], c["severity"] or "Z", c["id"]))
    return {
        "security_guid": guid or None,
        "symbol": row.get("symbol"),
        "stance": row.get("stance"),
        "conviction": row.get("conviction"),
        "conflicts": conflicts,
        "conflict_source": "saved CIO record diagnostics; engine findings classify flags",
        "review": review,
        "revision": row.get("revision"),
        "as_of": row.get("as_of") or doc.get("as_of"),
        "inputs_as_of": material_at,
        "material_inputs": material_inputs,
        "input_time_gap": {"reason": material_gap} if material_gap else None,
        "age_hours": row.get("age_hours", doc.get("age_hours")),
        "stale": bool(row.get("stale", doc.get("stale", True))),
        "source": deepcopy(doc.get("source") or {}),
        "gap": {"reason": "CIO stance or conviction unavailable for this security GUID"} if missing else None,
    }


def conflicts_for(security_guid: str, **kwargs) -> dict:
    """Typed conflict list from the same strict GUID stance lookup; no resolution action."""
    stance = stance_for(security_guid, **kwargs)
    return {k: stance[k] for k in ("security_guid", "symbol", "stance", "conviction", "conflicts", "review",
                                   "source", "as_of", "stale", "gap")}


def stances_for_symbols(symbols, *, root=None, db_query=None, projection=None, now=None,
                        identity_resolver=None, **projection_kwargs) -> dict:
    """One batch projection and confirmed registry lookups; no ticker/GUID guess."""
    from .identity_carriage import resolve_security_identity
    from .data_broker.cio_prospect import get_prospects
    resolve_identity = identity_resolver or resolve_security_identity
    names = list(dict.fromkeys(str(s).upper() for s in symbols if str(s).strip()))
    if projection is None:
        if root is not None:
            projection_kwargs.setdefault("shadow_base", Path(root) / "data/cio/cio_prospect_shadow.json")
        projection = get_prospects(db_query=db_query, now=now, **projection_kwargs)
    result = {}
    for symbol in names:
        identity = resolve_identity(symbol, root=root)
        guid = identity.get("security_guid") if identity.get("identity_status") == "CONFIRMED" else None
        result[symbol] = {**stance_for(guid, projection=projection, now=now),
                          "identity_status": identity.get("identity_status", "UNRESOLVED")}
    return result


def conflict_inputs_payload(query=None, *, db_query=None, now=None, projection=None) -> dict:
    q = query or {}
    guid = q.get("security_guid")
    guid = guid[0] if isinstance(guid, list) and guid else guid
    result = conflicts_for(guid, db_query=db_query, now=now, projection=projection)
    return {"ok": not bool(result["gap"]), "read_only": True, **result}


def conflict_payload(query=None, *, root=None, db_query=None, now=None, projection=None, engine_reader=None) -> dict:
    """Pass the engine read projection unchanged; never reinterpret old flags.

    W10 owns the registered reader and query filtering. It may be injected after
    that source is accepted. Until then absence is an explicit service gap.
    """
    now = now or datetime.now(timezone.utc)
    if projection is None and engine_reader is not None:
        projection = engine_reader(root=root, query=query or {}, now=now)
    if isinstance(projection, dict):
        return deepcopy(projection)
    return {"ok": False, "read_only": True, "findings": [],
            **_evidence("conflict engine read projection", None, now,
                        reason="conflict engine accepted source not yet integrated")}


def security_inputs_for(security_guid, *, document, projection=None, db_query=None, now=None) -> dict:
    """Canonical facts for W10's Input/Subject adapters; no comparison rules."""
    stance = stance_for(security_guid, projection=projection, db_query=db_query, now=now)
    positions = [r for r in document["positions"]["rows"] if (_number(r.get("market_value")) or 0) >= 100]
    held_rows = [r for r in positions if r.get("security_guid") == security_guid]
    complete = bool(document["portfolio"]["holdings"]) and all(r.get("security_guid") for r in positions)
    held = True if held_rows else False if complete else None
    return {"security_guid": security_guid, "symbol": stance["symbol"],
            "canonical": {"source": "CIO record", "value": stance["stance"], "as_of": stance["inputs_as_of"],
                          "subject_id": security_guid, "role": "claim"},
            "record_as_of": stance["as_of"], "material_inputs": stance["material_inputs"],
            "conviction": stance["conviction"], "context": {"held": held,
                "accounts": [r["account_id"] for r in held_rows]},
            "protection_inputs": [{"source": "stop_last_known", "value": r["stop_state"],
                                   "as_of": r.get("stop_captured_at"), "account": r["account_id"],
                                   "subject_id": security_guid, "role": "protection"} for r in held_rows],
            "saved_diagnostics": stance["conflicts"], "review": stance["review"],
            "gap": stance["gap"] or stance["input_time_gap"] or ({"reason": "held identity coverage incomplete"} if held is None else None)}


def _read_json(path: Path) -> dict:
    try:
        # A display resolver never loads a whole growing research/plan archive.
        if path.stat().st_size > 4 * 1024 * 1024:
            return {}
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _query_rows(db_query, sql, params=None) -> list[dict] | None:
    if db_query is None:
        return None
    try:
        rows = db_query(sql, params, fetch="all")
        return [dict(r) for r in rows] if isinstance(rows, (list, tuple)) else None
    except Exception:
        return None


def approvals_for(*, db_query=None, rows=None, projection=None, now=None) -> dict:
    """Typed queue counts; paper/broker proposals are disjoint account groups.

    All counts use complete COUNT queries, never page lengths. A missing queue
    makes the combined total unknown while preserving other measured counts.
    """
    now = now or datetime.now(timezone.utc)
    if projection is not None:
        # W11's unified operator queue owns de-duplication and typed counts.
        # Never add its total to legacy queue counts at the display layer.
        return deepcopy(projection)
    if rows is None:
        rows = _query_rows(db_query, """
            SELECT 'actions' AS kind, COUNT(*) AS count, NULL::text AS account FROM action_queue WHERE status='pending'
            UNION ALL SELECT 'decisions', COUNT(*), NULL::text FROM john_decision_queue WHERE status='pending_john'
            UNION ALL SELECT 'proposals', COUNT(*), COALESCE(target_account,account)
                      FROM paper_trade_proposals WHERE status='PENDING' GROUP BY 3
            UNION ALL SELECT 'options', COUNT(*), NULL::text FROM options_approval_queue WHERE status='pending'
        """)
    by_type = {k: None for k in ("actions", "decisions", "paper", "broker", "options", "unclassified_proposals")}
    if rows is not None:
        by_type = {k: 0 for k in by_type}
        for r in rows:
            kind = r.get("kind")
            if kind == "proposals":
                account_type = location_facts(r)["account_type"]
                kind = "paper" if account_type == "paper" else "unclassified_proposals" if account_type == "unknown" else "broker"
            if kind in by_type:
                n = _number(r.get("count"))
                by_type[kind] = by_type[kind] + int(n) if n is not None and by_type[kind] is not None else None
    total = sum(by_type.values()) if all(v is not None for v in by_type.values()) else None
    return {"total": total, "by_type": by_type,
            **_evidence("action_queue / john_decision_queue / paper_trade_proposals / options_approval_queue",
                        now if rows is not None else None, now, reason="approval queues unavailable" if total is None else None)}


def financial_queue_items(*, db_query=None, now=None, limit=200) -> dict:
    """Bounded source rows for W11's unified queue; no decision capability.

    Source IDs and explicit recommendation/proposal references support causal
    de-duplication. A symbol or similar title is never an entity identifier.
    Missing sources and truncation keep global completeness false.
    """
    now = now or datetime.now(timezone.utc)
    limit = max(1, min(200, int(limit)))
    sources = {
        "action_queue": ("actions", "SELECT id,recommendation_id,symbol,action,status,created_at,expires_at,dedupe_key "
                         "FROM action_queue WHERE status='pending' ORDER BY id LIMIT %s"),
        "john_decision_queue": ("decisions", "SELECT id,category,title,status,created_at,provenance "
                                "FROM john_decision_queue WHERE status='pending_john' ORDER BY id LIMIT %s"),
        "paper_trade_proposals": ("proposals", "SELECT id,symbol,account,target_account,status,created_at "
                                  "FROM paper_trade_proposals WHERE status='PENDING' ORDER BY id LIMIT %s"),
        "options_approval_queue": ("options", "SELECT id,proposal_id,symbol,status,created_at "
                                  "FROM options_approval_queue WHERE status='pending' ORDER BY id LIMIT %s"),
    }
    items, gaps = [], []
    for table, (kind, sql) in sources.items():
        rows = _query_rows(db_query, sql, (limit+1,))
        if rows is None:
            gaps.append({"source": table, "reason": "source unreadable"})
            continue
        if len(rows) > limit:
            gaps.append({"source": table, "reason": "source exceeds bounded page; total not established"})
        for row in rows[:limit]:
            identifier = row.get("id")
            if identifier is None:
                gaps.append({"source": table, "reason": "stable source id unavailable"})
                continue
            source_key = f"{table}:{identifier}"
            item_kind = kind
            account = canonical_key(row.get("target_account") or row.get("account"))
            if kind == "proposals":
                account_type = location_facts({"account": account})["account_type"]
                item_kind = "paper" if account_type == "paper" else "unclassified_proposals" if account_type == "unknown" else "broker"
            refs = [{"source": table, "id": str(identifier)}]
            if row.get("recommendation_id") is not None:
                refs.append({"source": "recommendation_registry", "id": str(row["recommendation_id"])})
            if row.get("proposal_id") is not None:
                refs.append({"source": "options_proposal", "id": str(row["proposal_id"])})
            provenance = row.get("provenance")
            if isinstance(provenance, str):
                try:
                    provenance = json.loads(provenance)
                except ValueError:
                    provenance = {}
            if isinstance(provenance, dict):
                for ref in provenance.get("source_refs") or []:
                    if isinstance(ref, dict) and ref.get("source") and ref.get("id") is not None:
                        refs.append({"source": str(ref["source"]), "id": str(ref["id"])})
            items.append({"key": source_key, "source": table, "source_id": str(identifier),
                          "canonical_entity_id": source_key, "source_refs": refs, "kind": item_kind,
                          "symbol": row.get("symbol"), "account_id": account or None,
                          "account_label": account_label(account) if account else None,
                          "status": row.get("status"), "created_at": row.get("created_at"),
                          "expires_at": row.get("expires_at"), "category": row.get("category"),
                          "title": row.get("title"), "action": row.get("action"),
                          "read_only": True, "can_decide": False})
    return {"items": items, "complete": not gaps, "gaps": gaps, "scope": "financial_source_rows",
            "as_of": now.isoformat(), "source": "existing approval queue rows", "limit_per_source": limit}


def paper_win_rate(*, db_query=None, stats=None, now=None) -> dict:
    """Same closed-trade denominator as live_trading_gate, including flat rows.

    Display only: the execution gate is never called or changed here.
    """
    now = now or datetime.now(timezone.utc)
    if stats is None:
        rows = _query_rows(db_query, "SELECT COUNT(*) AS closed, COUNT(*) FILTER (WHERE pnl > 0) AS wins "
                           "FROM paper_trades WHERE status='closed'")
        stats = rows[0] if rows else {}
    closed, wins = _number(stats.get("closed")), _number(stats.get("wins"))
    valid = closed is not None and wins is not None and 0 <= wins <= closed
    return {"closed": int(closed) if valid else None, "wins": int(wins) if valid else None,
            "win_rate": round(wins / closed, 4) if valid and closed else None,
            "win_rate_pct": round(100 * wins / closed, 1) if valid and closed else None,
            **_evidence("paper_trades status=closed", now if valid else None, now,
                        reason="no closed paper trades" if valid and not closed else "paper result counts unavailable" if not valid else None)}


def regime_for(*, db_query=None, projection=None, now=None) -> dict:
    """Regime and VIX from one classifier snapshot's input, with its clock."""
    now = now or datetime.now(timezone.utc)
    if projection is None:
        from .data_broker.market_regime import get_market_regime
        projection = get_market_regime(db_query, history=1, now=now) if db_query else {}
    row = projection.get("regime") or {}
    vix = _number(row.get("vix"))
    vix_at = row.get("generated_at") or row.get("created_at")
    if vix is None and row.get("snapshot_id"):
        values = _query_rows(db_query, "SELECT value, created_at FROM market_regime_indicators "
                             "WHERE snapshot_id=%s AND indicator_key='vix_close' ORDER BY created_at DESC LIMIT 1",
                             (row["snapshot_id"],))
        if values:
            vix, vix_at = _number(values[0].get("value")), values[0].get("created_at")
    reason = "classifier output unavailable" if not row else "VIX input unavailable for classifier snapshot" if vix is None else None
    return {"label": row.get("regime_label"), "vix": vix,
            "vix_as_of": _timestamp(vix_at).isoformat() if _timestamp(vix_at) else None,
            "snapshot_id": row.get("snapshot_id"), "confidence": _number(row.get("confidence")),
            "parts": {k: row.get(k) for k in ("volatility_state", "trend_state", "breadth_state", "macro_state")},
            **_evidence("market_regime_snapshots + matching market_regime_indicators.snapshot_id",
                        row.get("generated_at") or row.get("created_at"), now, reason=reason)}


def capital_for(portfolio: dict, *, plan=None, policy=None, now=None) -> dict:
    """Display waterfall only; never feeds a sizing or order path.

    Earmarked dollars remain part of current cash and are excluded from free
    investable cash. Future raise is a distinct figure, never added twice.
    Policy limits are read; no unconfirmed default becomes operator policy.
    """
    now = now or datetime.now(timezone.utc)
    plan, policy = plan or {}, policy or {}
    cash = portfolio.get("cash_usd")
    posture = plan.get("cash_posture") or plan.get("cash_policy_band") or plan.get("cash") or {}
    sources = plan.get("capital_sources") or plan.get("sources") or {}
    reserved = _number(posture.get("reserve_usd", plan.get("reserved_capital_usd")))
    earmarked = _number(sources.get("earmarked_redeploy_usd", plan.get("earmarked_redeploy_usd")))
    future = _number(sources.get("total_prospective_raise_usd", plan.get("prospective_raise_usd")))
    fields = policy.get("fields") or {}
    def confirmed(name):
        field = fields.get(name) or {}
        return field.get("value") if field.get("operator_confirmed") else None
    hierarchy = confirmed("concentration_hierarchy") or {}
    cash_band = confirmed("cash_target_range_pct")
    if reserved is None and cash_band is not None and portfolio.get("total_usd") is not None:
        minimum = _number(cash_band.get("min"))
        floor = _number(confirmed("minimum_liquidity_reserve_usd"))
        if minimum is not None:
            reserved = round(max(portfolio["total_usd"] * minimum / 100, floor or 0), 2)
    policy_max = _number(hierarchy.get("max_single_position_pct", hierarchy.get("max_single_name_pct")))
    # Alert thresholds are operational metadata, distinct from the policy cap.
    alert = _number((plan.get("policy") or {}).get("concentration_fire_pct", plan.get("concentration_fire_pct")))
    free = max(0, cash - reserved - earmarked) if all(v is not None for v in (cash, reserved, earmarked)) else None
    gaps = []
    if free is None:
        gaps.append("cash reserve or earmark evidence unavailable")
    if cash_band is None or policy_max is None:
        gaps.append("confirmed policy limits unavailable")
    if cash is not None and earmarked is not None and earmarked > cash:
        gaps.append("earmarked cash exceeds current cash")
        free = None
    return {"cash_usd": cash, "reserved_usd": reserved, "earmarked_usd": earmarked,
            "investable_usd": round(free, 2) if free is not None else None,
            "prospective_raise_usd": future, "policy_max_pct": policy_max,
            "alert_level_pct": alert, "cash_band": cash_band,
            "current_cash_pct": round(100 * cash / portfolio["total_usd"], 2)
            if cash is not None and portfolio.get("total_usd") else None,
            "post_plan_cash_usd": _number(plan.get("post_plan_cash_usd")),
            "post_plan_cash_pct": _number(plan.get("post_plan_cash_pct")),
            **_evidence("canonical holdings + CIO capital plan + operator investment policy",
                        plan.get("as_of") or portfolio.get("as_of"), now, reason="; ".join(gaps) or None)}


def status_for(root, *, now=None, db_query=None, scorecard=None) -> dict:
    """One evaluation set shared by CIO Overview, observability and scorecard.

    Existing lightweight scorecard collectors remain the domain evaluators.
    Measured DeepSeek completions come from the raw research ledger, evaluated
    by the existing non-error predicate. Missing ledger access stays unknown.
    """
    now = now or datetime.now(timezone.utc)
    if scorecard is None:
        from .cio_scorecard import get_cio_scorecard
        try:
            scorecard = get_cio_scorecard(root=Path(root), materialized_only=True)
        except Exception:
            scorecard = {}
    evaluations = deepcopy(scorecard.get("tiles") or [])
    rows = _query_rows(db_query, "SELECT recommendation,status,created_at FROM hermes_external_research "
                       "WHERE lane='deepseek' AND created_at >= %s", (now - timedelta(hours=24),))
    completed = None
    if rows is not None:
        from .research_lane_health import non_error_count
        completed = non_error_count(rows)
    for row in evaluations:
        if row.get("id") == "hermes_research":
            metrics = [m for m in row.get("metrics", []) if m.get("label") != "DeepSeek ok 24h"]
            row["metrics"] = [{"label": "DeepSeek ok 24h", "value": completed}, *metrics]
            # Do not turn an operational blocker green from throughput alone.
            # A blocked/dark zero-success verdict is corrected when the ledger
            # proves delivery; any other blocker remains visible.
            if completed and row.get("status") in ("dark", "blocked") and any(
                    word in str(row.get("verdict") or "").lower() for word in ("zero", "no recent", "non-error")):
                row.update(status="degraded", working=None,
                           verdict=f"{completed} DeepSeek completions in the ledger; monitor evaluation needs review.")
    return {"evaluations": evaluations, "deepseek_ok_24h": completed,
            "summary": {state: sum(r.get("status") == state for r in evaluations)
                        for state in ("working", "degraded", "blocked", "dark")},
            **_evidence("CIO scorecard evaluations + hermes_external_research", scorecard.get("as_of"), now,
                        reason="DeepSeek completion ledger unavailable" if completed is None else None)}


def apply_status_evaluations(scorecards, canonical_status) -> list[dict]:
    """Format one evaluation set into observability's existing domain shape."""
    ids = {"Desk / Telegram": "desk_telegram", "Hermes / Research": "hermes_research",
           "Shared Spine": "shared_spine", "Decisions": "decisions",
           "Outcomes / Learning": "outcomes_learning", "Platform / Pin": "platform_pin"}
    evaluations = {r.get("id"): r for r in canonical_status.get("evaluations") or []}
    result = []
    for raw in scorecards:
        row = deepcopy(raw)
        evaluation = evaluations.get(ids.get(row.get("name")))
        if evaluation:
            state = evaluation.get("status")
            row.update(status={"working": "WORKING", "degraded": "DEGRADED",
                               "blocked": "BLOCKED", "dark": "BLOCKED"}.get(state, "BLOCKED"),
                       value=evaluation.get("verdict"), blocker=evaluation.get("verdict") if state != "working" else None,
                       metrics=deepcopy(evaluation.get("metrics") or []),
                       source="cio_truth.status_for", last_success=evaluation.get("last_success"),
                       observed_at=canonical_status.get("as_of"))
        result.append(row)
    return result


def scorecard_payload(*, root=None, now=None, db_query=None, canonical_status=None) -> dict:
    if root is None:
        from .canonical_store_registry import production_state_root
        root = production_state_root()
    status = canonical_status or status_for(root, now=now, db_query=db_query)
    summary = status["summary"]
    return {"ok": True, "authority": "READ_ONLY_ADVISORY", "as_of": status.get("as_of"),
            "tiles": deepcopy(status["evaluations"]),
            "summary": {"working": summary["working"], "degraded": summary["degraded"],
                        "blocked_or_dark": summary["blocked"] + summary["dark"],
                        "tile_count": len(status["evaluations"])}, "truth": status}


def observability_payload(*, root=None, now=None, db_query=None, canonical_status=None) -> dict:
    """Read-only replacement without the heavy get_home attention writer."""
    from .cio_observability import build_observability
    from .cio_scorecard import _light_home, _light_brain, _light_health
    if root is None:
        from .canonical_store_registry import production_state_root
        root = production_state_root()
    root = Path(root)
    status = canonical_status or status_for(root, now=now, db_query=db_query)
    out = build_observability(home=_light_home(root), brain=_light_brain(root, materialized_only=True), research_ops={},
                              data_health=_light_health(root), now=status.get("as_of"), canonical_status=status)
    out["truth"] = status
    return out


def risk_payload(*, root=None, now=None, db_query=None, inputs=None, document=None) -> dict:
    """Current read-only Risk endpoint. No second stop lookup or cache publish."""
    doc = document or resolve(root, now, db_query=db_query, inputs=inputs)
    portfolio, risk, stops = doc["portfolio"], doc["positions"], doc["stops"]
    positions = []
    for raw in risk["rows"]:
        p = deepcopy(raw)
        price, sp = _number(p.get("price")), p.get("stop_price")
        p.update(current_price=price, has_stop=sp is not None,
                 distance_to_stop_pct=round(100 * (price - sp) / price, 2) if price and sp else None,
                 max_loss_dollar=round(max(0, price-sp) * (_number(p.get("shares")) or 0), 2) if price and sp else None,
                 risk_excluded=False, environment=p.get("environment") or "real")
        positions.append(p)
    denominator = _sum_known(positions, "market_value") if positions else None
    unprotected = risk.get("unprotected_value_usd")
    return {"portfolio_heat_pct": risk.get("portfolio_heat_pct"), "total_risk_dollars": risk.get("loss_at_stop_usd"),
            "pct_protected": round(100 * (denominator-unprotected) / denominator, 2)
            if denominator and unprotected is not None else None,
            "total_protected_mv": round(denominator-unprotected, 2) if denominator is not None and unprotected is not None else None,
            "total_unprotected_mv": unprotected, "position_count": portfolio.get("position_count"),
            "position_counts": portfolio.get("position_counts"), "paper_position_count": None,
            "positions": positions, "stops": {f"{p['account_id']}:{p['symbol']}": p for p in stops["rows"]},
            "positions_basis": "holdings_live", "positions_as_of": portfolio.get("positions_as_of"),
            "stop_health": {"protected_count": stops["active_count"], "pending_count": stops["pending_count"],
                            "filled_count": stops["filled_count"], "unprotected_count": stops["unprotected_count"]},
            "correlation": [], "escalation": {}, "source": "cio_truth", "truth": {k: portfolio[k] for k in
                                                                                      ("source", "as_of", "stale", "gap")}}


def overview_payload(payload, *, root=None, now=None, db_query=None, inputs=None, document=None) -> dict:
    """Preserve unrelated Overview fields, replace shared financial/display facts."""
    doc = document or resolve(root, now, db_query=db_query, inputs=inputs)
    out = deepcopy(payload)
    p = doc["portfolio"]
    out.update(portfolio_value=p["total_usd"], total_cash=p["cash_usd"], today_change=p["day_pl_usd"],
               today_pct=p["day_pl_pct"], position_count=p["position_count"], position_counts=p["position_counts"],
               pending_approvals=doc["approvals"]["total"], approval_counts=doc["approvals"],
               paper=doc["paper"], truth={k: p[k] for k in ("source", "as_of", "stale", "gap")})
    out["derived_total_value"] = p["total_usd"]
    pricing = out.setdefault("pricing", {})
    pricing.update(canonical_total_value=p["total_usd"], derived_total_value=p["total_usd"],
                   last_repriced=p["quote_as_of"], reprice_source=p["quote_source"])
    today_pnl = out.setdefault("today_pnl", {})
    today_pnl.update(total_change=p["day_pl_usd"], calculated_at=p["valuation_as_of"],
                     session_date=str(p["quote_as_of"])[:10] if p["quote_as_of"] else None,
                     mark_source=p["quote_source"])
    out.setdefault("periods", {})["1D"] = {"change": p["day_pl_usd"], "change_pct": p["day_pl_pct"],
                                           "estimated": False, "source": p["source"]}
    out["today_by_account"] = {r["account_id"]: {"value": r["total_usd"], "change": r["day_pl_usd"],
                                                 "account_label": r["account_label"], "as_of": r["as_of"]}
                               for r in p["accounts"]}
    aggregate = out.setdefault("portfolio_aggregate", {})
    aggregate["aggregate_value"] = p["total_usd"]
    aggregate.update(valuation_time=p["valuation_as_of"], quote_observation_time=p["quote_as_of"],
                     quote_source=p["quote_source"])
    old_accounts = {canonical_key(r.get("account")): r for r in aggregate.get("accounts") or []}
    aggregate["accounts"] = [{**old_accounts.get(r["account_id"], {}), **r,
                              "account": r["account_id"], "total_value": r["total_usd"], "display_value": r["total_usd"]}
                             for r in p["accounts"]]
    out.setdefault("trade_ai", {}).update(market_regime=doc["regime"]["label"], vix=doc["regime"]["vix"],
                                           vix_observation_time=doc["regime"]["vix_as_of"], regime_truth=doc["regime"])
    return out


def basis_for(position: dict, *, mark=None) -> dict:
    """Read the declared broker basis; partial/pre-window basis stays unknown."""
    broker = _number(position.get("cost_basis_broker"))
    stored = _number(position.get("cost_basis"))
    source = position.get("cost_basis_source")
    if broker is None and source == "broker_api":
        broker = stored
    basis = broker if broker is not None else stored
    reason = None
    if ((position.get("basis_partial") or position.get("basis_unknown")) and broker is None) or (basis is not None and basis <= 0):
        basis, reason = None, "basis unknown — incomplete or pre-window lot history"
    elif basis is None:
        reason = "basis unknown — no recorded acquisition cost"
    value = _number(position.get("market_value"))
    if mark is not None:
        shares = _number(position.get("shares"))
        value = round(mark * shares, 2) if shares is not None else None
    pnl = round(value-basis, 2) if value is not None and basis is not None else None
    conflicts = []
    if broker is not None and stored is not None and abs(broker-stored) > 1:
        conflicts.append({"field": "cost_basis", "broker": broker, "stored": stored,
                          "reason": "declared broker basis differs from the stored alternative"})
    return {"cost_basis_usd": basis, "unrealized_pl_usd": pnl,
            "unrealized_pl_pct": round(100*pnl/basis, 2) if pnl is not None and basis else None,
            "source": "broker_api" if broker is not None else source,
            "status": "unknown" if reason else "recorded", "gap": {"reason": reason} if reason else None,
            "conflicts": conflicts}


def holdings_payload(payload, *, root=None, now=None, db_query=None, inputs=None, document=None) -> dict:
    """Keep enrichment fields; quote, valuation, basis and stops share CIO truth."""
    doc = document or resolve(root, now, db_query=db_query, inputs=inputs)
    out = deepcopy(payload)
    previous = {(canonical_key(r.get("account") or r.get("account_id")), str(r.get("symbol") or "").upper()): r
                for r in out.get("holdings") or []}
    stop_by_key = {(r["account_id"], r["symbol"]): r for r in doc["stops"]["rows"]}
    rows = []
    for fact in doc["portfolio"]["holdings"]:
        key = fact["account_id"], str(fact.get("symbol") or "").upper()
        row = {**previous.get(key, {}), **deepcopy(fact)}
        # current_price is a legacy display alias, never a second quote read.
        row["current_price"] = row.get("price")
        basis = basis_for(row, mark=_number(row.get("price")))
        if not row.get("is_cash"):
            row.update(cost_basis=basis["cost_basis_usd"], gain_loss=basis["unrealized_pl_usd"],
                       gain_loss_pct=basis["unrealized_pl_pct"], basis_truth=basis)
        row.update(stop_by_key.get(key) or {})
        rows.append(row)
    p = doc["portfolio"]
    out.update(holdings=rows, count=len(rows), position_count=p["position_count"], total_value=p["total_usd"],
               total_cash=p["cash_usd"], today_change=p["day_pl_usd"], position_counts=p["position_counts"],
               truth={k: p[k] for k in ("source", "as_of", "stale", "gap")})
    return out


def realized_for_sale(event: dict, *, round_trips=None, db_query=None) -> dict:
    """FIFO journal P&L for this exact sale's account/date/quantity.

    The journal writer already performs FIFO matching. A partial window or
    unmatched sale is unknown; proceeds are never a realized profit fallback.
    """
    from zoneinfo import ZoneInfo
    sold_at = _timestamp(event.get("sold_at"))
    if len(str(event.get("sold_at") or "")) == 10 and sold_at is not None:
        # deploy_events carries an ET business DATE, not UTC midnight.
        sold_at = sold_at.replace(tzinfo=ZoneInfo("America/New_York"))
    account = canonical_key(event.get("account"))
    symbol = str(event.get("symbol") or "").upper()
    qty = _number(event.get("shares_sold"))
    if round_trips is None and sold_at is not None:
        start = sold_at.astimezone(ZoneInfo("America/New_York")).replace(hour=0, minute=0, second=0, microsecond=0)
        round_trips = _query_rows(db_query, "SELECT account,symbol,qty,entry_price,exit_price,exit_time,net_pnl,basis_status "
                                 "FROM schwab_round_trips WHERE upper(symbol)=%s AND exit_time >= %s "
                                 "AND exit_time < %s AND canary IS NOT TRUE",
                                 (symbol, start, start+timedelta(days=1)))
    rows = []
    if sold_at and qty is not None:
        date = sold_at.astimezone(ZoneInfo("America/New_York")).date()
        rows = [r for r in round_trips or [] if canonical_key(r.get("account")) == account
                and str(r.get("symbol") or "").upper() == symbol and _timestamp(r.get("exit_time"))
                and _timestamp(r["exit_time"]).astimezone(ZoneInfo("America/New_York")).date() == date]
    matched = _sum_known(rows, "qty") if rows else None
    known = bool(rows and matched is not None and qty is not None and abs(matched-qty) < 0.000001
                 and all(_number(r.get("entry_price")) is not None and _number(r.get("entry_price")) > 0
                         and _number(r.get("net_pnl")) is not None for r in rows))
    return {"realized_pnl": _sum_known(rows, "net_pnl") if known else None,
            "cost_basis_usd": round(sum(float(r["qty"])*float(r["entry_price"]) for r in rows), 2) if known else None,
            "basis_status": "known_fifo" if known else "unknown", "source": "schwab_round_trips FIFO journal",
            "gap": None if known else {"reason": "basis unknown — exact sale not fully matched in FIFO ledger"}}


def redeploy_payload(payload, *, db_query=None, round_trips=None) -> dict:
    """Correct the event's displayed realized P&L without rewriting its store."""
    out = deepcopy(payload)
    events = out.get("events") or []
    if round_trips is None and events:
        symbols = sorted({str(e.get("symbol") or "").upper() for e in events})
        dates = [_timestamp(e.get("sold_at")) for e in events]
        dates = [d for d in dates if d]
        round_trips = _query_rows(db_query, "SELECT account,symbol,qty,entry_price,exit_price,exit_time,net_pnl,basis_status "
                                  "FROM schwab_round_trips WHERE upper(symbol)=ANY(%s) AND exit_time >= %s "
                                  "AND exit_time < %s AND canary IS NOT TRUE",
                                  (symbols, min(dates)-timedelta(days=1), max(dates)+timedelta(days=2))) if dates else []
    for event in events:
        basis = realized_for_sale(event, round_trips=round_trips or [])
        event.update(realized_pnl=basis["realized_pnl"], basis_truth=basis,
                     account_id=canonical_key(event.get("account")), account_label=account_label(event.get("account")))
    return out


def positions_payload(payload, *, root=None, now=None, db_query=None, inputs=None, document=None) -> dict:
    """Shared current position facts for Open Trades/stop display readers.

    Other intelligence fields and historical rows retain their existing scope.
    No execution module is imported or called by this adapter.
    """
    doc = document or resolve(root, now, db_query=db_query, inputs=inputs)
    out = deepcopy(payload)
    facts = {(r["account_id"], str(r.get("symbol") or "").upper()): r for r in doc["positions"]["rows"]}
    for key in ("trades", "positions", "rows"):
        for row in out.get(key) or []:
            account = canonical_key(row.get("account") or row.get("account_id"))
            fact = facts.get((account, str(row.get("symbol") or "").upper()))
            row.update(account_id=account, account_label=account_label(account))
            if fact:
                for field in ("price", "shares", "market_value", "stop_price", "stop_source", "stop_state",
                              "stop_captured_at", "broker_protected", "basis_truth", "distance_to_stop_pct", "loss_at_stop_usd"):
                    row[field] = deepcopy(fact.get(field))
                row["current_price"] = row["price"]
                row["cost_basis"] = fact["basis_truth"]["cost_basis_usd"]
                row["gain_loss"] = fact["basis_truth"]["unrealized_pl_usd"]
                row["gain_loss_pct"] = fact["basis_truth"]["unrealized_pl_pct"]
    out.update(position_count=doc["portfolio"]["position_count"], position_counts=doc["portfolio"]["position_counts"])
    return out


def execution_status(payload: dict) -> dict:
    """Display text from supplied gate flags. Never imports or changes a gate."""
    out = deepcopy(payload)
    live = out.get("live_unlock") or {}
    unlocked = live.get("live_unlocked", out.get("live_unlocked"))
    blockers = out.get("current_blockers") or out.get("blockers") or []
    allowed = unlocked is True and not blockers and out.get("operator_approved_live_submit_possible") is True
    out["execution_model"] = ("Operator approval and per-order confirmation required; live execution gates currently allow this path."
                              if allowed else "Live execution is locked or blocked by the current execution gates."
                              if unlocked is False or blockers else "Live execution status is not fully measured.")
    out["execution_display_status"] = "eligible_for_operator_confirmation" if allowed else "locked" if unlocked is False or blockers else "unknown"
    if "armed_for_execution" in out:
        out["armed_for_execution"] = bool(out["armed_for_execution"] and allowed)
    return out


def _capital_inputs(root, db_query, now) -> dict:
    """Read published plan + open event balances; never invoke plan materializers."""
    from .jsonl_bounded import tail_jsonl_lines
    plan = {}
    for line in reversed(tail_jsonl_lines(Path(root) / "data/cio/cio_capital_plans.jsonl", 30,
                                         max_bytes=1024 * 1024)):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("record_type") == "CAPITAL_PLAN_PUBLISHED":
            plan = deepcopy(record.get("plan") or {})
            break
    events = _query_rows(db_query, """SELECT e.id,e.account,e.symbol,
        COALESCE(e.deployable_cash_usd,e.net_proceeds_usd,e.proceeds_usd)
          - COALESCE((SELECT SUM(filled_dollars) FROM redeploy_stage_fills f
                      WHERE f.deploy_event_id=e.id AND f.environment='production'),0) AS remaining_usd
        FROM deploy_events e WHERE e.status IN ('open','partial','locked')""")
    if events is not None and all(_number(r.get("remaining_usd")) is not None for r in events):
        sources = dict(plan.get("capital_sources") or {})
        sources["earmarked_redeploy_usd"] = round(sum(max(0, float(r["remaining_usd"])) for r in events), 2)
        plan["capital_sources"] = sources
    return plan


def _policy_inputs(root) -> dict:
    """Latest recorded policy fields without constructing the writable store.

    OperatorProfile's constructor creates directories. This streaming read
    applies its exact latest-field event rule and never initializes a store.
    """
    from .cio_operator_investment_policy import FIELD_SPECS
    fields = {}
    try:
        with (Path(root) / "data/cio/operator_profile.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    payload = json.loads(line).get("payload") or {}
                except ValueError:
                    continue
                name = payload.get("field_name")
                if name in FIELD_SPECS and payload.get("domain") == FIELD_SPECS[name]["domain"]:
                    field = payload.get("field") or {}
                    confirmed = field.get("status") == "OPERATOR_CONFIRMED"
                    fields[name] = {"value": field.get("value") if confirmed else None,
                                    "operator_confirmed": confirmed, "source": field.get("source"),
                                    "confirmed_at": field.get("confirmed_at"), "status": field.get("status")}
    except OSError:
        pass
    return {"fields": fields}


def do_now_for(positions, approvals, *, now=None) -> dict:
    """Existing Home queue ordering over the shared CIO display facts only."""
    from .data_broker.home_do_now import item, merge, sort_items
    now = now or datetime.now(timezone.utc)
    items = []
    for p in positions:
        if p.get("broker_protected") or (_number(p.get("market_value")) or 0) < 100:
            continue
        state = p.get("stop_state")
        reason = "Stop awaiting activation" if state == "pending_activation" else "No active broker stop observed"
        items.append(item(f"protection:{p['account_id']}:{p['symbol']}", "protect", "P1",
                          f"{p['symbol']} · {p['account_label']}", reason,
                          "Review protection", "/v3/risk", "cio_truth.stops",
                          money=p.get("market_value"), evidence={"account_id": p["account_id"], "stop_state": state}))
    if approvals.get("total"):
        items.append(item("approvals:pending", "decide", "P2", f"{approvals['total']} approvals waiting",
                          "Review the typed approval queues", "Review approvals", "/v3/trading?tab=Proposals",
                          "cio_truth.approvals", evidence={"counts": approvals["by_type"]}))
    ranked = sort_items(merge(items))
    return {"items": ranked[:7], "total": len(ranked), "ranking": "home_do_now.sort_items",
            **_evidence("CIO shared protection + typed approval queues", now, now,
                        reason="approval count unavailable" if approvals.get("total") is None else None)}


def resolve(root=None, now=None, *, db_query=None, inputs=None) -> dict:
    """Shared display document; root is a persistent state root containing data/.

    ``inputs`` injects already-read canonical projections for batching/fixtures:
    holdings, broker_stops, planned_stops, regime, approvals, paper_stats,
    capital_plan, policy, cio_status, do_now, companies, sectors, risk_snapshot.
    An explicitly supplied root never falls back to another root or live DB.
    No job runs, broker calls, store writes, new stores or execution imports.
    """
    now = now or datetime.now(timezone.utc)
    inputs = inputs or {}
    if root is None:
        from .canonical_store_registry import production_state_root
        root = production_state_root()
    root = Path(root)
    state = root / "data" / "portfolios" / "state"
    from .portfolio_positions import load_store, store_path
    portfolio = portfolio_for(inputs.get("holdings") if "holdings" in inputs else load_store(store_path(root)), now=now)
    broker = inputs.get("broker_stops") if "broker_stops" in inputs else _query_rows(
        db_query, "SELECT account,symbol,order_id,stop_price,qty,status,captured_at FROM stop_last_known")
    planned = inputs.get("planned_stops") if "planned_stops" in inputs else _read_json(state / "stops.json")
    positions = []
    for r in portfolio["holdings"]:
        if r["is_cash"] or r.get("is_loan") or (_number(r.get("shares", r.get("quantity"))) or 0) <= 0:
            continue
        p = deepcopy(r)
        p["basis_truth"] = basis_for(p, mark=_number(p.get("price")))
        stop = stop_for(r["account_id"], r.get("symbol"), broker_rows=broker, planned=planned, now=now)
        p.update({k: v for k, v in stop.items() if k not in ("source", "as_of", "age_hours", "stale", "gap")})
        p["stop_evidence"] = {k: stop[k] for k in ("source", "as_of", "age_hours", "stale", "gap")}
        positions.append(p)
    counted_positions = [p for p in positions if (_number(p.get("market_value")) or 0) >= 100]
    counts = {state: sum(p["stop_state"] == state for p in counted_positions) for state in ("active", "pending_activation", "filled")}
    stop_rows = [{k: p.get(k) for k in ("account_id", "account_label", "symbol", "stop_price", "stop_source", "stop_state",
                                      "stop_captured_at", "broker_protected", "stop_qty", "stop_evidence")} for p in positions]
    stop_times = [p.get("stop_captured_at") for p in positions if p.get("stop_captured_at")]
    stops = {"rows": stop_rows, "active_count": counts["active"], "pending_count": counts["pending_activation"],
             "filled_count": counts["filled"], "unprotected_count": sum(not p["broker_protected"] for p in counted_positions),
             "position_count": portfolio["position_count"],
             "nearest": None, "awaiting_fill": [],
             **_evidence("stop_last_known > stops.json, per account+symbol", min(stop_times) if stop_times else None,
                         now, reason="persisted broker stop observations unavailable" if broker is None else None)}
    if broker is None:
        for key in ("active_count", "pending_count", "filled_count", "unprotected_count"):
            stops[key] = None
    # Current holdings and the same stop states supply the display risk summary;
    # stale pre-market risk rows never substitute for the current position set.
    losses = []
    for p in positions:
        price, shares, sp = _number(p.get("price")), _number(p.get("shares")), p.get("stop_price")
        p["distance_to_stop_pct"] = round(100 * (price-sp) / price, 2) if p["broker_protected"] and price and sp else None
        p["loss_at_stop_usd"] = round(max(0, price-sp) * shares, 2) if (
            p["broker_protected"] and price is not None and sp is not None and shares is not None) else None
        if p["broker_protected"]:
            losses.append(p["loss_at_stop_usd"])
    protected_loss = round(sum(losses), 2) if portfolio["holdings"] and broker is not None and all(v is not None for v in losses) else None
    unprotected_mv = _sum_known([p for p in positions if not p["broker_protected"]], "market_value") if portfolio["holdings"] and broker is not None else None
    position_section = {"rows": positions, "loss_at_stop_usd": protected_loss,
                        "portfolio_heat_pct": round(protected_loss / portfolio["total_usd"] * 100, 3)
                        if portfolio.get("total_usd") and protected_loss is not None else None,
                        "unprotected_value_usd": unprotected_mv, "largest_name": None,
                        "loss_basis": "loss to observed active stops; unprotected downside is not bounded",
                        **{k: portfolio[k] for k in ("source", "as_of", "stale", "gap")}}
    position_section["as_of"] = portfolio["positions_as_of"]
    by_symbol = {}
    for p in positions:
        by_symbol[p["symbol"]] = by_symbol.get(p["symbol"], 0) + (_number(p.get("market_value")) or 0)
    if by_symbol and portfolio.get("total_usd"):
        symbol = max(by_symbol, key=by_symbol.get)
        position_section["largest_name"] = {"symbol": symbol, "pct": round(100 * by_symbol[symbol] / portfolio["total_usd"], 3)}
    position_section["concentration"] = [{"symbol": symbol, "value_usd": value,
                                           "pct": round(100 * value / portfolio["total_usd"], 3)
                                           if portfolio.get("total_usd") else None}
                                          for symbol, value in sorted(by_symbol.items(), key=lambda r: -r[1])]
    # No protection inference from a crossed mark: fills remain a separate sync.
    distances = []
    for p in positions:
        price, sp = _number(p.get("price")), p.get("stop_price")
        if price and sp and p["stop_state"] == "active":
            distance = round(100 * (price - sp) / price, 2)
            distances.append({"symbol": p["symbol"], "account_id": p["account_id"], "distance_pct": distance})
            if distance <= 0:
                stops["awaiting_fill"].append({"symbol": p["symbol"], "account_id": p["account_id"], "stop_price": sp,
                                               "reason": "mark at or below observed stop; fill not yet confirmed"})
    stops["nearest"] = min(distances, key=lambda r: abs(r["distance_pct"]), default=None)
    stops["awaiting_fill_count"] = len(stops["awaiting_fill"])
    companies = inputs.get("companies")
    if companies is None:
        try:
            from .data_broker.cio_company_facts import load_snapshot
            companies = load_snapshot(root)
        except Exception:
            companies = {}
    companies = {guid: {"symbol": (v.get("company_facts") or {}).get("symbol"), **v}
                 for guid, v in companies.items()}
    identity_by_symbol = {}
    for guid, record in companies.items():
        if record.get("symbol"):
            identity_by_symbol.setdefault(str(record["symbol"]).upper(), []).append(guid)
    for row in [*portfolio["holdings"], *positions]:
        ids = identity_by_symbol.get(str(row.get("symbol") or "").upper()) or []
        if not row.get("security_guid") and len(ids) == 1:
            row["security_guid"] = ids[0]
            row["security_guid_source"] = "CIO InstrumentRecord company_facts"
    capital_plan = inputs.get("capital_plan") if "capital_plan" in inputs else _capital_inputs(root, db_query, now)
    policy = inputs.get("policy")
    if policy is None:
        policy = _policy_inputs(root)
    sectors = inputs.get("sectors")
    if sectors is None and db_query:
        try:
            from .data_broker.sector_momentum import get_sector_signals
            sectors = get_sector_signals(db_query)
        except Exception:
            sectors = None
    approval_input = inputs.get("approvals")
    approvals = approvals_for(db_query=db_query, rows=approval_input if isinstance(approval_input, list) else None,
                              projection=approval_input if isinstance(approval_input, dict) else None, now=now)
    status = inputs.get("cio_status") if "cio_status" in inputs else status_for(root, now=now, db_query=db_query)
    do_now = inputs.get("do_now") if "do_now" in inputs else do_now_for(positions, approvals, now=now)
    return {"read_only": True, "financial_action": False, "as_of": now.isoformat(),
            "portfolio": portfolio, "positions": position_section, "stops": stops,
            "regime": regime_for(db_query=db_query, projection=inputs.get("regime"), now=now),
            "approvals": approvals,
            "paper": paper_win_rate(db_query=db_query, stats=inputs.get("paper_stats"), now=now),
            "capital": capital_for(portfolio, plan=capital_plan, policy=policy, now=now),
            "cio_status": status,
            "do_now": do_now,
            "companies": {"by_guid": companies, **_evidence("CIO InstrumentRecord research.company_facts", None, now,
                          reason="CIO company facts unavailable" if not companies else None)},
            "conflicts": deepcopy(inputs["conflicts"]) if "conflicts" in inputs else {
                "findings": [], **_evidence("conflict engine read projection", None, now,
                                            reason="conflict engine accepted source not yet integrated")},
            "sectors": sectors or {"sectors": {}, **_evidence("sector_momentum.get_sector_signals", None, now,
                          reason="multi-horizon sector projection unavailable")}}
