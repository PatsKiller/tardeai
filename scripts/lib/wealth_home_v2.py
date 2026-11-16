"""Stored Home v2 presentation contract. Financial aggregation runs ONLY in dp-live.

GET reads one already-published Home slice; only calendar and source ages move at serve time.
No providers, broker subsystem, advice generation, scheduler, or durable write is reachable here.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import json
import math
from urllib.parse import urlencode, urlsplit

from scripts.lib.market_risk import sessions

UTC = timezone.utc
COLORS = {"known": "green", "partial": "amber", "stale": "amber", "unknown": "grey"}
TODAY = {
    "stance": "Daily decision",
    "tiles": "Portfolio snapshot",
    "movers": "Top movers",
    "stops": "Protection review",
    "week": "This week",
    "news": "What to read first",
    "accounts": "Accounts",
    "setups": "Latest finished setups",
    "watch": "Re-entry watch",
    "brief": "Historical CIO brief",
    "pulse": "System pulse",
}
OUTLOOK = {
    "temperature": "Market temperature",
    "regime": "Market regime",
    "disagreements": "Engine disagreements",
    "gates": "Policy gates",
    "dataQuality": "Data-quality findings",
    "otherFindings": "Other retained findings",
    "sectors": "Sector states",
    "hedge": "Hedge and rotation",
    "week": "Week ahead",
    "futures": "Futures and overseas",
    "headlines": "Market headlines",
    "marketMovers": "Scanner movers",
}
NEEDS = {
    "summary": "Review queue",
    "protect": "Protect",
    "decide": "Decide",
    "reentry": "Re-entry watch",
    "protectionInventory": "Protection inventory",
    "sourceNotices": "Source-quality notices",
    "fix": "Fix",
    "incidents": "Incident history",
}


def number(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) else None


def gap_reason(value):
    return value.get("reason") if isinstance(value, dict) else str(value) if value else None


def count(value):
    n = number(value)
    return int(n) if n is not None and n >= 0 and n.is_integer() else None


def timestamp(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def iso(value):
    at = timestamp(value)
    return at.isoformat().replace("+00:00", "Z") if at else None


def money(value, signed=False):
    n = number(value)
    if n is None:
        return None
    return ("+" if signed and n > 0 else "-" if n < 0 else "") + f"${abs(n):,.2f}"


def pct(value, signed=False):
    n = number(value)
    return None if n is None else f"{n:+.2f}%" if signed and n != 0 else f"{n:.2f}%"


def tone(value):
    n = number(value)
    return "grey" if n is None or n == 0 else "green" if n > 0 else "red"


def source_meta(source, clock=None, stale_after_s=None, *, now=None, reason=None, stale=False):
    now = now or datetime.now(UTC)
    at = timestamp(clock)
    age = (now - at).total_seconds() if at else None
    valid = age is not None and age >= -5
    old = stale or (valid and stale_after_s is not None and age > stale_after_s)
    verdict = "unknown" if not valid else "stale" if old else "known"
    return {
        "source": source,
        "clock": iso(clock),
        "as_of": iso(clock),
        "evaluated_at": iso(now),
        "clock_delta_s": round(age, 3) if age is not None else None,
        "age_s": max(0, int(age)) if valid else None,
        "stale_after_s": stale_after_s,
        "verdict": verdict,
        "state": COLORS[verdict],
        "reason": reason
        or (
            "Source clock is in the future beyond existing 5s tolerance"
            if at and age < -5
            else "Source clock missing or timezone unqualified"
            if not valid
            else "Stored observation is stale"
            if old
            else None
        ),
    }


def session_clock(now):
    local = now.astimezone(sessions.ET)
    key = sessions.session_label(now)
    key = {"premarket": "pre_market", "afterhours": "after_hours", "overnight": "closed"}.get(key, key)
    day = local.date()
    candidate = datetime.combine(day, time(9, 30), sessions.ET)
    while not sessions.is_trading_day(day) or candidate <= local:
        day += timedelta(days=1)
        candidate = datetime.combine(day, time(9, 30), sessions.ET)
    last = sessions.last_closed_session(now)
    return {
        "key": key,
        "label": {
            "pre_market": "Pre-market",
            "regular": "Regular session",
            "after_hours": "After-hours",
            "closed": "Closed",
        }[key],
        "last_session_date": last.isoformat(),
        "next_open": iso(candidate),
        "regular_close": iso(datetime.combine(local.date(), sessions.close_time(local.date()), sessions.ET))
        if sessions.is_trading_day(local.date())
        else None,
        "timezone": "America/New_York",
    }


def cell(label, display=None, *, value=None, secondary=None, meta=None, state=None, tooltip=None):
    meta = meta or source_meta("not served")
    verdict = meta["verdict"] if display is not None else "unknown"
    return {
        **meta,
        "label": label,
        "verdict": verdict,
        "state": state or COLORS[verdict],
        "value": value,
        "display": display,
        "secondary": secondary or [],
        "tooltip": tooltip or meta.get("reason") or meta["source"],
    }


def section(title, *, meta=None, metrics=None, rows=None, notes=None, links=None, reason=None):
    meta = meta or source_meta("not served")
    available = bool(metrics or rows)
    return {
        **meta,
        "title": title,
        "available": available,
        "metrics": metrics or [],
        "rows": rows or [],
        "notes": notes or [],
        "links": links or [],
        "reason": reason
        or meta.get("reason")
        or (None if available else "Stored producer coverage is not available for this panel"),
    }


def fact(label, value, *, state="grey", **extra):
    return {"label": label, "value": value, "state": state, **extra}


def holding_href(symbol, account=None):
    query = {"hv_query": symbol}
    if account:
        query["hv_account"] = account
    return "/wealth/portfolio/holdings?" + urlencode(query)


def unique_positions(rows):
    """Canonical account+instrument identity once; conflicting duplicates are excluded, never divided.

    Same-source duplicates and parent/child joins cannot amplify a position. Rows missing account identity
    never collapse under symbol alone: they are rejected and named in coverage instead.
    """
    grouped, rejected = {}, []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            rejected.append("malformed position")
            continue
        account = str(row.get("account_id") or "").strip()
        instrument = (
            str(row.get("instrument_id") or row.get("instrument_guid") or row.get("symbol") or "").strip().upper()
        )
        if not account or not instrument:
            rejected.append("position identity missing")
            continue
        key = (account, instrument)
        if key not in grouped:
            grouped[key] = row
        elif grouped[key] is not None:
            previous = grouped[key]
            fields = {
                "market_value",
                "shares",
                "quantity",
                "day_change",
                "day_change_pct",
                "broker_protected",
                "observation",
            }
            fields.update(k for k in previous.keys() | row.keys() if k.startswith(("protection", "stop_", "resting_")))
            if any(previous.get(k) != row.get(k) for k in fields):
                grouped[key] = None
    for key, value in grouped.items():
        if value is None:
            rejected.append("conflicting position identity")
    return [v for v in grouped.values() if v is not None], rejected


def exposure_by_symbol(rows):
    unique, rejected = unique_positions(rows)
    out = {}
    for row in unique:
        sym = str(row.get("symbol") or "").upper()
        rec = out.setdefault(sym, {"value": 0.0, "known": 0, "total": 0})
        rec["total"] += 1
        value = number(row.get("market_value"))
        if value is not None:
            rec["known"] += 1
            rec["value"] += value
    for rec in out.values():
        rec["coverage"] = f"{rec['known']}/{rec['total']} account positions with value"
        rec["complete"] = rec["known"] == rec["total"]
        if rec["known"] == 0:
            rec["value"] = None
    return out, rejected


def safe_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        return (
            str(value)
            if parsed.scheme in ("https", "http") and parsed.netloc and not parsed.username and not parsed.password
            else None
        )
    except ValueError:
        return None


def owner_href(value):
    """Only retained working owning desks; no mutation/API URL or unfinished Wealth Ops page."""
    if not isinstance(value, str) or not value.startswith("/v3/") or value.startswith("//"):
        return None
    parsed = urlsplit(value)
    path = parsed.path
    allowed = path in ("/v3/health", "/v3/approvals", "/v3/ops/jobs-n8n") or (
        path.startswith("/v3/approvals/")
        and bool(path.removeprefix("/v3/approvals/"))
        and "/" not in path.removeprefix("/v3/approvals/")
    )
    # Exact retained queue owners, verified against the registered classic routes. No arbitrary subpaths/tabs.
    allowed = allowed or path in ("/v3/risk", "/v3/system", "/v3/coordination", "/v3/agents") and not parsed.query
    allowed = allowed or (path, parsed.query) in (
        ("/v3/trading", "tab=Proposals"),
        ("/v3/portfolio", "tab=Redeploy"),
        ("/v3/intelligence", "tab=research"),
    )
    return value if allowed and not parsed.netloc and not parsed.scheme else None


def queue_model(queue, now):
    """One retained task-group population, not position or approval-record counts."""
    meta = source_meta("cio.pages.do_now", queue.get("as_of"), now=now, stale=bool(queue.get("stale")))
    raw = queue.get("all_items") if isinstance(queue.get("all_items"), list) else queue.get("items")
    observed = isinstance(raw, list) and meta["verdict"] != "unknown" and queue.get("state") != "UNKNOWN"
    rows = []
    for i, it in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(it, dict):
            continue
        action = it.get("action") if isinstance(it.get("action"), dict) else {}
        evidence = it.get("evidence") if isinstance(it.get("evidence"), dict) else {}
        href = owner_href(action.get("where"))
        if href is None and str(it.get("id") or "").startswith("approvals:"):
            href = "/v3/approvals"
        if href is None and it.get("category") == "protect":
            href = "/wealth/portfolio/holdings"
        facts = [
            fact("Category", it.get("category")),
            fact("Severity", it.get("severity")),
            fact("Since", iso(it.get("since"))),
        ]
        if isinstance(evidence.get("counts"), dict):
            facts += [
                fact(str(k) + " approval records", str(count(v)) if count(v) is not None else None)
                for k, v in evidence["counts"].items()
            ]
        rows.append(
            {
                "id": str(it.get("id") or "unidentified:" + str(i)),
                "label": str(it.get("title") or it.get("label") or "Task group"),
                "detail": str(it.get("why") or it.get("reason") or "Reason not supplied by owning queue"),
                "summary": str(it.get("why") or it.get("reason") or "Reason unavailable"),
                "category": it.get("category"),
                "severity": it.get("severity"),
                "owner": action.get("label"),
                "source": "cio.pages.do_now",
                "clock": iso(queue.get("as_of")),
                "state": "amber",
                "href": href,
                "facts": facts,
                "summaryFacts": facts[:2],
                "evidence": {
                    "task_id": it.get("id"),
                    "unit": "task group",
                    "approval_counts": evidence.get("counts"),
                    "individual_approval_ids_served": False,
                },
                "links": [{"label": action.get("label") or "Review at owning desk", "href": href}] if href else [],
            }
        )
    counts = {k: sum(r.get("category") == k for r in rows) for k in ("protect", "decide", "fix")} if observed else {}
    total = len(rows) if observed else None
    if observed and meta["stale_after_s"] is None and meta["verdict"] == "known":
        meta.update(
            verdict="partial",
            state="amber",
            reason="Queue observation is dated; per-source currentness/freshness policy is not retained",
        )
    declared = count(queue.get("total"))
    complete = observed and isinstance(queue.get("all_items"), list) and (declared is None or declared == len(rows))
    return meta, rows, counts, total, complete


def conflict_groups(document, now):
    """Registered ConflictFinding/Record fields, canonical tier/kind/key ordering, no keyword classifier."""
    from scripts.lib.conflicts.engine import SEVERITY_ORDER

    meta = source_meta("cio.pages.conflicts", document.get("as_of"), now=now, stale=bool(document.get("stale")))
    groups = {k: [] for k in ("disagreements", "gates", "dataQuality", "otherFindings")}
    bykind = {"CONFLICT": "disagreements", "GATE": "gates", "DATA_ERROR": "dataQuality"}
    seen = set()
    duplicates = 0
    findings = [it for it in document.get("findings") or [] if isinstance(it, dict)]
    findings.sort(
        key=lambda it: (
            count(it.get("tier")) if count(it.get("tier")) is not None else 4,
            SEVERITY_ORDER.get(it.get("kind"), 99),
            str(it.get("key") or ""),
        )
    )
    for i, it in enumerate(findings):
        # Only byte-equivalent records of the same stable key/revision collapse.
        identity = (it.get("key"), it.get("revision"), json.dumps(it, sort_keys=True, default=str))
        if it.get("key") and identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        key = str(it.get("key") or "missing-key:" + str(i))
        kind = str(it.get("kind") or "UNKNOWN")
        subject = it.get("subject") if isinstance(it.get("subject"), dict) else {}
        # A conflict key alone cannot mount Watch's selected-symbol drawer. Use an honest broad desk.
        href = owner_href(it.get("href")) or "/v3/health"
        facts = [
            fact("Kind", kind),
            fact("Subject", subject.get("label") or subject.get("id")),
            fact("Severity", it.get("severity")),
            fact("Rule", it.get("rule")),
            fact("Clears when", it.get("clears_when")),
            fact("Owner", it.get("owner")),
            fact("Next step", it.get("action")),
            fact("Lifecycle", it.get("state")),
            fact("Revision", str(it["revision"]) if it.get("revision") is not None else None),
        ]
        for side in it.get("sides") or []:
            if isinstance(side, dict):
                facts.append(
                    fact(
                        str(side.get("source") or "Unidentified engine"),
                        str(side.get("value")) if side.get("value") is not None else None,
                        clock=iso(side.get("as_of")),
                        source=side.get("source"),
                        qualifier=side.get("detail"),
                    )
                )
        groups[bykind.get(kind, "otherFindings")].append(
            {
                "id": key + ":" + str(it.get("revision") or "unversioned") + ":" + str(i),
                "label": str(it.get("summary") or "Registered finding summary unavailable"),
                "detail": str(it.get("clears_when") or "Clearance condition not supplied"),
                "summary": str(it.get("summary") or "Summary contract missing"),
                "kind": kind,
                "category": kind,
                "severity": it.get("severity"),
                "owner": it.get("owner"),
                "version": str(it.get("revision")) if it.get("revision") is not None else None,
                "clock": iso(it.get("updated_at") or document.get("as_of")),
                "source": "conflict_events.jsonl",
                "state": "amber",
                "href": href,
                "facts": facts,
                "summaryFacts": facts[:3],
                "links": [
                    {"label": "Open owning desk" if owner_href(it.get("href")) else "Open health desk", "href": href}
                ]
                if href
                else [],
                "evidence": {
                    "key": it.get("key"),
                    "subject": subject,
                    "schema": it.get("schema"),
                    "history_gap": it.get("history_gap"),
                    "missing_fields": [k for k in ("key", "summary", "clears_when", "subject") if not it.get(k)],
                },
            }
        )
    return meta, groups, duplicates


def week_window(rows, now):
    """Seven NY calendar dates, [local midnight today, midnight seven dates later)."""
    start = now.astimezone(sessions.ET).date()
    end = start + timedelta(days=7)
    inside = []
    later = []
    invalid = 0
    for row in rows:
        value = row.get("event_at") or row.get("event_date")
        at = timestamp(value)
        try:
            day = (
                at.astimezone(sessions.ET).date()
                if at
                else date.fromisoformat(value)
                if isinstance(value, str) and len(value) == 10
                else None
            )
        except ValueError:
            day = None
        if day is None:
            invalid += 1
            continue
        item = {**row, "_date": day.isoformat()}
        if start <= day < end:
            inside.append(item)
        elif day >= end:
            later.append(item)
    for population in (inside, later):
        population.sort(key=lambda r: (r["_date"], str(r.get("event_at") or ""), r.get("label", ""), r["id"]))
        for row in population:
            row.pop("_date", None)
    return (
        inside,
        later,
        {
            "timezone": "America/New_York",
            "from": start.isoformat(),
            "to_exclusive": end.isoformat(),
            "label": start.isoformat() + " 00:00 ET to " + end.isoformat() + " 00:00 ET (end excluded)",
            "invalid_dates": invalid,
        },
    )


def held_movers(eligible, document, now):
    """Join canonical account/instrument once, retaining stored row-estimate semantics and missing clocks."""
    raw = [
        {**r, "account_id": r.get("account_id") or r.get("account")}
        for r in document.get("holdings") or []
        if isinstance(r, dict)
    ]
    stored, rejected = unique_positions(raw)
    if not isinstance(document.get("holdings"), list):
        return (
            [],
            {
                "matched_account_positions": 0,
                "eligible_account_positions": len(eligible),
                "known_contribution_positions": 0,
                "rejected_identities": 0,
                "stored_estimate_total": None,
                "complete": False,
                "document_source": document.get("document_source"),
                "fallback_reason": "Full held document not served",
            },
            {},
        )

    # Exact account+instrument identity. A symbol fallback is only used when both sources lack instrument GUIDs.
    def key(row):
        return (
            str(row.get("account_id") or ""),
            str(row.get("instrument_id") or row.get("instrument_guid") or row.get("symbol") or "").upper(),
        )

    bykey = {key(r): r for r in stored}
    groups = {}
    matched = 0
    eligible_count = 0
    for pos in eligible:
        row = bykey.get(key(pos))
        if row is not None and row.get("is_cash") is True:
            continue
        eligible_count += 1
        if row is not None:
            matched += 1
        sym = str(pos.get("symbol") or "").upper()
        groups.setdefault(sym, []).append(row if row is not None else {"symbol": sym})
    output = []
    known = 0
    contribution_total = 0.0
    for sym, members in groups.items():
        changes = [number(r.get("day_change")) for r in members]
        complete = all(v is not None for v in changes)
        amount = sum(changes) if complete else None
        known += sum(v is not None for v in changes)
        if complete:
            contribution_total += amount
        percentage_inputs = [number(r.get("day_change_pct")) for r in members]
        percentages = set(percentage_inputs)
        percent = next(iter(percentages)) if None not in percentages and len(percentages) == 1 else None
        clocks = [iso((r.get("observation") or {}).get("day_change_as_of")) for r in members]
        # Stored row day_change has no declared observation time in today's canonical contract.
        clock = min(clocks) if clocks and all(clocks) else None
        meta = source_meta(
            "holdings document stored row day_change",
            clock,
            now=now,
            reason="Stored current-holdings estimate; economic P/L interval and observation time unproven"
            if not clock
            else None,
        )
        facts = [
            fact(
                "Stored row estimate",
                money(amount, True),
                state=tone(amount),
                signed=True,
                qualifier="Current holdings price movement, not economic P/L",
            ),
            fact("Change", pct(percent, True), state=tone(percent), signed=True),
            fact("Account-position coverage", str(sum(v is not None for v in changes)) + " / " + str(len(members))),
            fact("Observation time", clock),
            fact("Mark batch", iso(document.get("last_repriced"))),
            fact(
                "Reference session",
                (document.get("measures") or {}).get("session", {}).get("date")
                if isinstance((document.get("measures") or {}).get("session"), dict)
                else None,
            ),
        ]
        output.append(
            {
                **meta,
                "id": "held:" + sym,
                "label": sym,
                "symbol": sym,
                "scope": "held",
                "href": holding_href(sym),
                "detail": "Stored current-holdings row estimate · interval unproven",
                "facts": facts,
                "summaryFacts": facts[:3],
                "_rank": abs(amount) if amount is not None else None,
            }
        )
    output.sort(key=lambda r: (r["_rank"] is None, -(r["_rank"] or 0), r["symbol"]))
    for row in output:
        row.pop("_rank")
    return (
        output,
        {
            "matched_account_positions": matched,
            "eligible_account_positions": eligible_count,
            "known_contribution_positions": known,
            "rejected_identities": len(rejected),
            "stored_estimate_total": contribution_total
            if matched == eligible_count and known == matched and matched
            else None,
            "complete": matched == eligible_count and known == matched,
            "document_source": document.get("document_source"),
            "fallback_reason": document.get("document_fallback_reason"),
        },
        bykey,
    )


def build(
    *,
    cio=None,
    market=None,
    overview=None,
    scanner=None,
    slices=None,
    health=None,
    cio_card=None,
    holdings=None,
    now=None,
    stop_stale_after_s=None,
):
    """Pure producer-side composer over stored read models; arguments are synthetic-testable."""
    now = now or datetime.now(UTC)
    cio_card = cio_card if isinstance(cio_card, dict) else {}
    holdings = holdings if isinstance(holdings, dict) else {}
    cio, market, overview, scanner, slices = (
        v if isinstance(v, dict) else {} for v in (cio, market, overview, scanner, slices)
    )
    portfolio = cio.get("portfolio") or {}
    positions = cio.get("positions") or {}
    stop_contract = cio.get("stops") or {}
    if stop_stale_after_s is None and number(stop_contract.get("stale_after_hours")) is not None:
        stop_stale_after_s = number(stop_contract["stale_after_hours"]) * 3600
    rows, rejected = unique_positions(positions.get("rows") or [])
    exposure, _ = exposure_by_symbol(rows)
    held_rows, held_coverage, holding_by_identity = held_movers(rows, holdings, now)
    pm = source_meta(
        "cio.pages.portfolio",
        portfolio.get("quote_as_of") or portfolio.get("positions_as_of"),
        now=now,
        stale=bool(portfolio.get("stale")),
        reason=gap_reason(portfolio.get("gap")),
    )
    rm = source_meta(
        "market_risk.latest.projection", market.get("as_of"), 3600, now=now, stale=bool(market.get("stale"))
    )
    sm = source_meta(
        "cio.pages.positions",
        positions.get("as_of"),
        now=now,
        stale=bool(positions.get("stale")),
        reason=gap_reason(positions.get("gap")),
    )
    regime = cio.get("regime") or {}
    regime_row = regime.get("regime") or regime.get("data") or regime
    if regime.get("label") and not regime_row.get("regime_label"):
        regime_row = {**regime_row, "regime_label": regime["label"]}
    scanner = {
        **{
            k: v
            for k, v in (
                ("vix", regime.get("vix")),
                ("vix_source", regime.get("vix_source")),
                ("vix_observation_time", regime.get("vix_as_of")),
                ("vix_stale_after_hours", regime.get("vix_stale_after_hours")),
            )
            if v is not None
        },
        **scanner,
    }
    gm = source_meta(
        "cio.pages.regime",
        regime.get("as_of") or regime_row.get("generated_at"),
        number(regime.get("stale_after_hours")) * 3600 if number(regime.get("stale_after_hours")) is not None else None,
        now=now,
        stale=bool(regime.get("stale")),
        reason=gap_reason(regime.get("gap")),
    )
    vm = source_meta(
        scanner.get("vix_source") or "trade_ai_cache.vix",
        scanner.get("vix_observation_time"),
        number(scanner.get("vix_stale_after_hours")) * 3600
        if number(scanner.get("vix_stale_after_hours")) is not None
        else None,
        now=now,
    )
    value, cash = number(portfolio.get("total_usd")), number(portfolio.get("cash_usd"))
    cash_pct = cash / value * 100 if cash is not None and value is not None and value > 0 else None
    covariance = portfolio.get("day_pl_coverage") or {}
    day = number(portfolio.get("day_pl_usd"))
    day_clock = (portfolio.get("clock_provenance") or {}).get("day_pnl") or {}
    day_meta = source_meta(
        "cio.pages.portfolio.stored_day_change",
        day_clock.get("as_of"),
        now=now,
        reason=gap_reason(day_clock.get("gap")) or "Stored row day-change observation clock is not supplied",
    )
    if day is not None:
        day_meta.update(
            verdict="partial", state="amber", reason="Current-holdings estimate; source interval is unproven"
        )
    if not portfolio.get("day_pl_complete") and day is not None:
        day_meta.update(
            verdict="partial",
            state="amber",
            reason=portfolio.get("day_pl_gap") or "Current-holdings price movement has incomplete coverage",
        )
    tier = str(market.get("tier") or "UNKNOWN")
    tier_state = {"BLUE": "grey", "GREEN": "green", "YELLOW": "amber", "ORANGE": "amber", "RED": "red"}.get(
        tier, "grey"
    )
    temp_display = (
        f"{tier} · {number(market['score']):.1f}".rstrip("0").rstrip(".")
        if number(market.get("score")) is not None
        else None
    )
    session = session_clock(now)
    cells = {
        "session": cell(
            "Session",
            session["label"],
            value=session,
            meta=source_meta("NYSE exchange calendar", now, now=now),
            state="grey",
            secondary=[
                "Last session " + session["last_session_date"],
                "Next open " + timestamp(session["next_open"]).astimezone(sessions.ET).strftime("%a %b %d %H:%M ET"),
            ],
        ),
        "session_pl": cell(
            "Session P/L estimate",
            money(day, True),
            value={
                "amount": day,
                "usd": day,
                "pct": number(portfolio.get("day_pl_pct")),
                "coverage": covariance,
                "method": "Stored current-holdings price movement; not verified account return",
                "interval": {
                    "source": "cio.pages.portfolio",
                    "from": None,
                    "to": portfolio.get("quote_as_of"),
                    "session_date": None,
                },
                "verified": False,
            },
            meta=day_meta,
            secondary=[
                pct(portfolio.get("day_pl_pct"), True) or "Percentage unknown",
                "Current-holdings estimate · interval not served",
            ],
            tooltip="Stored current-holdings estimate; account performance may use another method/interval. Extended-only coverage is not served and is never inferred.",
        ),
        "account_value": cell(
            "Household value",
            money(value),
            value={
                "usd": value,
                "cash_usd": cash,
                "cash_pct": cash_pct,
                "approx_ytd": None,
                "batch_built_at": iso(portfolio.get("valuation_as_of")),
                "quote_as_of": iso(portfolio.get("quote_as_of")),
                "positions_as_of": iso(portfolio.get("positions_as_of")),
            },
            meta=pm,
            secondary=[
                "Cash " + (money(cash) or "Unknown") + " · " + (pct(cash_pct) or "Unknown") + " derived",
                "Approximate YTD not served",
            ],
        ),
        "temperature": cell(
            "Temperature",
            temp_display,
            value={"tier": tier, "score": market.get("score"), "stance": market.get("reason")},
            meta=rm,
            state=tier_state if rm["verdict"] == "known" else "grey",
            secondary=[str(market.get("reason") or "Stance not served")],
        ),
        "regime": cell(
            "Regime",
            regime_row.get("regime_label") or regime.get("label"),
            value={
                "label": regime_row.get("regime_label"),
                "score": regime_row.get("regime_score"),
                "confidence": regime_row.get("confidence"),
            },
            meta=gm,
        ),
        "vix": cell(
            "VIX",
            str(scanner["vix"]) if number(scanner.get("vix")) is not None else None,
            value={"index": number(scanner.get("vix")), "source": scanner.get("vix_source")},
            meta=vm,
            state="grey",
        ),
        "operating_mode": cell(
            "Operating mode",
            None,
            meta=source_meta("Typed operating-mode flags not in stored Home product", now=now),
            tooltip="Buy-risk stance, kill and live-submit flags require a reviewed stored read model; no flag is inferred or changed.",
        ),
        "health": cell(
            "Health",
            None,
            meta=source_meta("Health findings not in stored Home product", now=now),
            tooltip="Incident history and component checks are different populations from current critical/total health findings.",
        ),
    }
    today = {k: section(v) for k, v in TODAY.items()}
    outlook = {k: section(v) for k, v in OUTLOOK.items()}
    needs = {k: section(v) for k, v in NEEDS.items()}
    temp_metrics = [
        fact("Tier", tier, state=tier_state),
        fact(
            "Score",
            f"{number(market['score']):.1f}".rstrip("0").rstrip(".")
            if number(market.get("score")) is not None
            else None,
        ),
        fact("Evaluation", rm["clock"]),
        fact(
            "Episode", str((market.get("episode") or {}).get("id")) if (market.get("episode") or {}).get("id") else None
        ),
    ]
    today["stance"] = section(
        TODAY["stance"],
        meta=rm,
        metrics=temp_metrics
        + [
            fact("Buys", None, qualifier="Stored buy-risk stance not served"),
            fact("Stops to decide", None, qualifier="Typed decision subset not served"),
            fact("Unprotected", None, qualifier="Applicable current protection population not supplied"),
            fact("Re-entry", None, qualifier="Ready/near/total stage contract not served"),
        ],
        notes=[
            str(market.get("reason") or "No stored dated stance"),
            "Saved engine evidence, not a new synthesized recommendation",
        ],
        links=[{"label": "Needs your review", "href": "/wealth/home/needs"}],
    )
    today["tiles"] = section(
        TODAY["tiles"],
        meta=pm,
        metrics=[
            fact("Portfolio", money(value)),
            fact("Session estimate", money(day, True), state=tone(day), signed=True),
            fact("Approximate YTD", None, qualifier="Compatible stored flow-adjusted period not served"),
            fact("Realized P/L", None, qualifier="Partial basis/ledger coverage not served"),
            fact("Trading record", None, qualifier="Comparable finished-trade population not served"),
        ],
        notes=["Session estimate: current holdings, not verified return; raw NAV growth is not investment profit."],
    )
    account_rows = [
        {
            "id": str(a.get("account_id") or i),
            "label": a.get("account_label") or "Account label unavailable",
            "facts": [
                fact("Value", money(a.get("total_usd"))),
                fact("Cash", money(a.get("cash_usd"))),
                fact(
                    "Session estimate", money(a.get("day_pl_usd"), True), state=tone(a.get("day_pl_usd")), signed=True
                ),
            ],
            "clock": iso(a.get("as_of") or pm["clock"]),
            "source": pm["source"],
            "href": "/wealth/portfolio/holdings?" + urlencode({"hv_account": a.get("account_id") or ""}),
        }
        for i, a in enumerate(portfolio.get("accounts") or [])
        if isinstance(a, dict)
    ]
    today["accounts"] = section(
        TODAY["accounts"],
        meta=pm,
        rows=account_rows,
        notes=[
            "Household and account results retain their own eligible population; missing account results remain unknown."
        ],
    )
    protect = []
    for i, row in enumerate(rows):
        # Use the retained canonical verdict only. stop_state alone cannot establish applicability.
        proof = row.get("protection") if isinstance(row.get("protection"), dict) else {}
        canonical = str(row.get("protection_state") or proof.get("state") or "UNKNOWN").upper()
        identity = (
            str(row.get("account_id") or ""),
            str(row.get("instrument_id") or row.get("instrument_guid") or row.get("symbol") or "").upper(),
        )
        asset = holding_by_identity.get(identity, {})
        # Applicability is separate from freshness; only a retained canonical exemption grants N/A.
        not_applicable = canonical == "EXEMPT"
        pending = row.get("stop_state") == "pending_activation"
        stop_meta = source_meta(
            row.get("stop_source") or "cio.pages.positions.stop evidence",
            row.get("stop_captured_at"),
            stop_stale_after_s,
            now=now,
            stale=sm["verdict"] != "known",
        )
        proven = (
            not pending
            and canonical == "PROTECTED"
            and row.get("broker_protected") is True
            and number(row.get("stop_price")) is not None
            and number(row.get("stop_price")) > 0
            and bool(row.get("stop_source"))
            and stop_stale_after_s is not None
            and stop_meta["verdict"] == "known"
        )
        shortfall = number(row.get("resting_coverage_shortfall_qty"))
        partial = proven and shortfall is not None and shortfall > 0
        status = (
            "Not applicable"
            if not_applicable
            else "Partial resting coverage"
            if partial
            else "Recorded active"
            if proven
            else "Pending activation"
            if pending
            else "Not applicable"
            if canonical == "EXEMPT"
            else "Gap"
            if canonical == "GAP" and stop_meta["verdict"] == "known"
            else "Current protection proof unavailable"
        )
        state = (
            "grey"
            if not_applicable
            else "amber"
            if partial
            else "green"
            if proven
            else "amber"
            if pending
            else "red"
            if status == "Gap"
            else "grey"
        )
        if stop_meta["verdict"] == "stale" and not not_applicable:
            state = "amber"
        detail = f"{row.get('account_label') or 'Account unavailable'} · {status} · canonical applicability {'served' if canonical != 'UNKNOWN' else 'not retained in stored projection'}"
        protect.append(
            {
                **stop_meta,
                "id": str(i),
                "symbol": row.get("symbol"),
                "label": str(row.get("symbol") or "Unknown instrument"),
                "detail": detail,
                "state": state,
                "href": holding_href(str(row.get("symbol") or ""), row.get("account_id")),
                "facts": [
                    fact(
                        "Protection",
                        status,
                        state=state,
                        current_status=not not_applicable,
                        applicability=not_applicable,
                    ),
                    fact("Canonical order verdict", canonical),
                    fact("Asset type", asset.get("asset_type")),
                    fact(
                        "Applicability",
                        "Canonical exemption" if not_applicable else "Canonical verdict retained",
                        applicability=True,
                    ),
                    fact("Recorded advisory/order level", money(row.get("stop_price"))),
                    fact("Distance", pct(row.get("resting_stop_distance_pct"))),
                    fact(
                        "Covered shares",
                        str(row["resting_loss_qty"]) if number(row.get("resting_loss_qty")) is not None else None,
                    ),
                    fact("Uncovered shares", str(shortfall) if shortfall is not None else None),
                    fact("Shares", str(row["shares"]) if number(row.get("shares")) is not None else None),
                ],
                "evidence": row.get("stop_evidence") or {},
            }
        )
    today["stops"] = section(
        TODAY["stops"],
        meta=sm,
        rows=protect,
        notes=[
            "Pending activation is not active protection. Observation age and account scope remain explicit. Historical incidents are separate."
        ]
        + ([f"Rejected {len(rejected)} ambiguous position identity rows"] if rejected else []),
    )
    needs["protectionInventory"] = deepcopy(today["stops"])
    needs["protectionInventory"].update(
        title=NEEDS["protectionInventory"],
        populationLabel="All retained account-position observations; not action tasks",
        unit="account positions",
        totalCount=len(protect),
    )
    queue = cio.get("do_now") or {}
    qm, qrows, counts, queue_total, queue_complete = queue_model(queue, now)
    coverage = (
        str(len(qrows))
        + " retained task groups; source declared "
        + str(count(queue.get("total")))
        + "; "
        + ("complete returned population" if queue_complete else "full population not proven")
    )
    needs["summary"] = section(
        NEEDS["summary"],
        meta=qm,
        metrics=[
            fact("Money decisions today", None, qualifier="Task groups are not individual money decisions"),
            fact("Protect money", str(counts["protect"]) if counts.get("protect") is not None else None),
            fact("Decide", str(counts["decide"]) if counts.get("decide") is not None else None),
            fact("Fix system", str(counts["fix"]) if counts.get("fix") is not None else None),
            fact(
                "Queue freshness",
                qm["verdict"],
                state=qm["state"],
                clock=qm["clock"],
                qualifier="Observation timestamp known; source product freshness separately qualified",
            ),
        ],
        rows=qrows,
        notes=[
            "Counts and navigation badge use the same task-group population. Approval records, position inventory, source notices and platform health findings are separate units."
        ],
    )
    needs["summary"].update(
        populationLabel="Stored action task groups",
        unit="task groups",
        totalCount=queue_total,
        complete=queue_complete,
        coverage=coverage,
    )
    for category in ("protect", "decide", "fix"):
        selected = [r for r in qrows if r.get("category") == category]
        needs[category] = section(
            NEEDS[category],
            meta=qm,
            rows=selected,
            notes=["Read-only review in the owning desk; this list contains task groups, not all account positions."],
        )
        needs[category].update(
            populationLabel="Stored action task groups",
            unit="task groups",
            totalCount=counts.get(category),
            complete=queue_complete,
            coverage=coverage,
        )
    inc = slices.get("incidents") or {}
    im = source_meta("home.incidents", (inc.get("snapshot") or {}).get("computed_at"), 180, now=now)
    incidents = [
        {
            "id": str(it.get("incident_id") or i),
            "label": str(it.get("category") or it.get("alert_type") or "Unclassified"),
            "detail": str(it.get("cause") or it.get("reason") or "Recorded incident"),
            "clock": iso(it.get("last_seen_at")),
            "source": str(it.get("alert_type") or "home.incidents"),
            "state": "grey",
            "facts": [fact("First seen", iso(it.get("first_seen_at"))), fact("Last seen", iso(it.get("last_seen_at")))],
        }
        for i, it in enumerate(inc.get("items") or [])
        if isinstance(it, dict)
    ]
    needs["incidents"] = section(
        NEEDS["incidents"],
        meta=im,
        rows=incidents,
        notes=[
            "Recorded incident history, not a current protection verdict. Category is retained from the registered incident type; message fallback is not classification evidence."
        ],
    )
    needs["incidents"]["collapsed"] = True
    outlook["temperature"] = section(
        OUTLOOK["temperature"],
        meta=rm,
        metrics=temp_metrics,
        rows=[
            {
                "id": str(i),
                "label": str(c.get("label") or c.get("category") or c.get("name") or i),
                "detail": str(c.get("reason") or ""),
                "facts": [fact("Score", str(c["score"]) if number(c.get("score")) is not None else None)],
            }
            for i, c in enumerate(market.get("categories") or [])
            if isinstance(c, dict)
        ],
        notes=["Engine cutoffs are not supplied in this stored contract; no invented gauge boundaries."],
    )
    outlook["regime"] = section(
        OUTLOOK["regime"],
        meta=gm,
        metrics=[
            fact("Regime", regime_row.get("regime_label") or regime.get("label")),
            fact(
                "Confidence",
                str(regime_row["confidence"]) if number(regime_row.get("confidence")) is not None else None,
            ),
            fact(
                "Score", str(regime_row["regime_score"]) if number(regime_row.get("regime_score")) is not None else None
            ),
        ],
        rows=[
            {"id": k, "label": k.replace("_state", " ").replace("_", " "), "detail": str(regime_row[k])}
            for k in (
                "volatility_state",
                "trend_state",
                "breadth_state",
                "liquidity_state",
                "leadership_state",
                "risk_appetite_state",
                "macro_state",
                "data_freshness_state",
            )
            if regime_row.get(k) is not None
        ],
    )
    news = []
    for i, item in enumerate((market.get("material_news") or {}).get("items") or []):
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").upper()
        headlines = item.get("headlines") or [item]
        for j, headline in enumerate(headlines if isinstance(headlines, list) else []):
            if not isinstance(headline, dict):
                continue
            title = headline.get("title") or headline.get("headline")
            if not title:
                continue
            link = safe_url(headline.get("source_url") or headline.get("url"))
            news.append(
                {
                    "id": f"{i}:{j}",
                    "label": str(title),
                    "symbol": sym,
                    "candidate": True,
                    "issuerVerified": False,
                    "source": headline.get("source") or "market_risk.material_news",
                    "clock": iso(headline.get("published_at")),
                    "state": "grey",
                    "href": holding_href(sym) if sym in exposure else "/v3/watch/intelligence/" + sym,
                    "facts": [
                        fact("Entity match", "Unverified source-tagged candidate"),
                        fact("Publisher", headline.get("source")),
                        fact("Publication", iso(headline.get("published_at"))),
                    ],
                    "links": [{"label": "Original source", "href": link}] if link else [],
                }
            )
    today["news"] = section(
        TODAY["news"],
        meta=rm,
        rows=news,
        notes=[
            "Ticker tags and headline substrings do not prove issuer relevance. Candidates do not carry personalized exposure claims or ranked advice."
        ],
    )
    outlook["headlines"] = deepcopy(today["news"])
    outlook["headlines"]["title"] = OUTLOOK["headlines"]
    context = market.get("home_v007") or {}
    symbol_context = context.get("symbols") if isinstance(context.get("symbols"), dict) else {}
    reentry = market.get("reentry_watch") if isinstance(market.get("reentry_watch"), dict) else {}

    def measured(raw):
        return raw if isinstance(raw, dict) and raw.get("state") == "measured" else {}

    def meta_for(raw, fallback):
        return source_meta(
            raw.get("source") or fallback,
            raw.get("as_of"),
            now=now,
            stale=raw.get("state") != "measured",
            reason=raw.get("reason"),
        )

    mover_rows = []
    event_rows = []
    context_news = []
    for sym, data in sorted(symbol_context.items()):
        if not isinstance(data, dict):
            continue
        scope = "held" if sym in exposure else "watch" if sym in reentry else "unknown"
        href = holding_href(sym) if scope == "held" else "/v3/watch/intelligence/" + sym
        quote, change = measured(data.get("quote")), measured(data.get("day_change"))
        change_value = change.get("value") if isinstance(change.get("value"), dict) else {}
        if scope != "unknown" and (quote or change):
            delta = number(change_value.get("pct"))
            mover_rows.append(
                {
                    **meta_for(quote or change, "market_risk.home_v007"),
                    "id": sym,
                    "symbol": sym,
                    "label": sym,
                    "scope": scope,
                    "href": href,
                    "_rank": delta,
                    "facts": [
                        fact("Price", money(quote.get("value"))),
                        fact("Change", pct(delta, True), state=tone(delta), signed=True),
                        fact("Reference session", change.get("reference_session_date")),
                    ],
                    "detail": "Stored guarded quote; change versus previous completed NYSE session close",
                }
            )
        event = data.get("next_event") or {}
        ev = event.get("value") if isinstance(event.get("value"), dict) else {}
        if scope != "unknown" and ev:
            event_rows.append(
                {
                    "event_date": ev.get("date"),
                    "event_at": ev.get("at"),
                    **meta_for(event, "canonical_symbol_calendar"),
                    "id": sym,
                    "symbol": sym,
                    "label": sym + " · " + str(ev.get("kind") or "Recorded event"),
                    "href": href,
                    "scope": scope,
                    "facts": [fact("Recorded date", ev.get("date")), fact("Timing", "Unconfirmed date-only event")],
                    "detail": "Stored calendar date; exchange time and confirmed/estimated status are not supplied",
                }
            )
        headlines = data.get("headlines") or {}
        for j, h in enumerate(headlines.get("value") if isinstance(headlines.get("value"), list) else []):
            if not isinstance(h, dict) or not isinstance(h.get("title"), str):
                continue
            url = safe_url(h.get("source_url") or h.get("url"))
            context_news.append(
                {
                    **meta_for(headlines, "guarded_symbol_headlines"),
                    "id": sym + ":" + str(j),
                    "symbol": sym,
                    "label": h["title"],
                    "scope": scope,
                    "candidate": True,
                    "issuerVerified": False,
                    "href": href,
                    "facts": [
                        fact("Entity match", "Unverified source-tagged candidate"),
                        fact("Publisher", h.get("source")),
                        fact("Publication", iso(h.get("published_at"))),
                        fact("Ingest/read clock", iso(headlines.get("as_of"))),
                    ],
                    "links": [{"label": "Original source", "href": url}] if url else [],
                }
            )
    mover_rows.sort(key=lambda r: (r.get("_rank") is None, -abs(r.get("_rank") or 0), r["symbol"]))
    for row in mover_rows:
        row.pop("_rank", None)
    watch_movers = [r for r in mover_rows if r.get("scope") == "watch"]
    # If canonical stored rows are not available, retain the percentage sample and name its missing coverage.
    full_movers = held_rows + watch_movers if held_rows else mover_rows
    today["movers"] = section(
        "Held row estimates and watch percentage sample" if held_rows else "Retained held/watch percentage sample",
        meta=sm if held_rows else rm,
        rows=full_movers,
        notes=[
            "Held estimates rank by absolute summed stored row day_change, not economic account P/L. Watch sample ranks by absolute served percentage. No duplicate account rows are multiplied."
        ],
    )
    today["movers"].update(
        populationLabel="Held eligible account positions plus separately tagged watch sample",
        coverage=str(held_coverage["matched_account_positions"])
        + " / "
        + str(held_coverage["eligible_account_positions"])
        + " eligible account positions joined; "
        + str(held_coverage["known_contribution_positions"])
        + " stored row changes; economic interval unproven",
        coverageEvidence=held_coverage,
        complete=held_coverage["complete"],
        totalCount=len(full_movers),
        unit="securities",
    )
    # Existing since-close calendar already distinguishes macro/earnings/ex-dividend source kinds.
    saved_calendar = (slices.get("since_close") or {}).get("week_ahead") or {}
    for i, event in enumerate(saved_calendar.get("events") or []):
        if not isinstance(event, dict):
            continue
        symbols = [str(sym).upper() for sym in event.get("symbols") or [] if isinstance(sym, str)]
        meta = source_meta(
            "Saved since-close calendar",
            (slices.get("since_close") or {}).get("generated_at"),
            now=now,
            stale=bool(((slices.get("since_close") or {}).get("freshness") or {}).get("stale")),
        )
        event_rows.append(
            {
                **meta,
                "id": "saved-calendar:" + str(i),
                "label": str(event.get("label") or event.get("kind") or "Recorded event"),
                "event_date": event.get("date"),
                "event_kind": event.get("kind"),
                "scope": "held" if event.get("held") is True else "watch" if symbols else "macro",
                "symbol": symbols[0] if len(symbols) == 1 else None,
                "href": holding_href(symbols[0])
                if len(symbols) == 1 and event.get("held") is True
                else "/v3/watch/intelligence/" + symbols[0]
                if len(symbols) == 1
                else None,
                "facts": [
                    fact("Recorded date", event.get("date")),
                    fact("Kind", event.get("kind")),
                    fact("Source ET time", event.get("time_et")),
                    fact("Confirmation", "Unconfirmed stored calendar observation"),
                ],
            }
        )
    near_events, later_events, window = week_window(event_rows, now)
    today["week"] = section(
        TODAY["week"],
        meta=rm,
        rows=near_events,
        notes=[
            "Seven New York calendar dates beginning today; date-only events remain unconfirmed. Farther-out retained dates do not substitute for this window.",
            str(len(later_events)) + " farther-out retained dates; complete calendar coverage not served.",
        ],
    )
    today["week"].update(
        windowLabel=window["label"],
        window=window,
        totalCount=len(near_events),
        complete=False,
        coverage="Bounded stored held/watch calendar; full event coverage unproven",
        recordedUpcoming=later_events,
    )
    outlook["week"] = deepcopy(today["week"])
    outlook["week"]["title"] = OUTLOOK["week"]
    if context_news:
        today["news"] = section(
            TODAY["news"],
            meta=rm,
            rows=context_news,
            notes=[
                "Source-tagged candidates; issuer/entity match remains unverified. No personalized financial consequence is asserted."
            ],
        )
        outlook["headlines"] = deepcopy(today["news"])
        outlook["headlines"]["title"] = OUTLOOK["headlines"]
    watch_rows = []
    for sym, card in sorted(reentry.items()):
        if sym.startswith("_") or not isinstance(card, dict):
            continue
        conditions = card.get("conditions") or []
        progress = [c["met"] for c in conditions if isinstance(c, dict) and isinstance(c.get("met"), bool)]
        facts = [
            fact("Stage", card.get("status"), qualifier="Retained engine stage, not permission to buy"),
            fact("Exit date", card.get("exit_date")),
            fact("Source session date", card.get("as_of")),
            fact(
                "Conditions",
                str(card.get("met")) + " / " + str(card.get("of"))
                if count(card.get("met")) is not None and count(card.get("of")) is not None
                else None,
            ),
        ]
        watch_rows.append(
            {
                "id": sym,
                "label": sym,
                "symbol": sym,
                "scope": "held" if sym in exposure else "watch",
                "href": holding_href(sym) if sym in exposure else "/v3/watch/intelligence/" + sym,
                "source": "market_risk.reentry_watch",
                "clock": None,
                "state": "grey",
                "detail": str(card.get("headline") or card.get("error") or "Stored re-entry evidence"),
                "reason": card.get("error"),
                "facts": facts
                + [
                    fact("Exit cause", card.get("exit_reason"), qualifier="Not inferred from re-entry membership"),
                    fact("Closed-position linkage", card.get("closed_position_id")),
                    fact(
                        "Blockers",
                        str(card.get("blockers")) if card.get("blockers") else None,
                        qualifier="Blocker evidence unavailable when absent",
                    ),
                ],
                "summaryFacts": facts[:2],
                **({"progress": progress} if len(progress) == 5 else {}),
            }
        )
    today["watch"] = section(
        TODAY["watch"],
        meta=rm,
        rows=watch_rows,
        notes=[
            "Retained re-entry conditions, not a new recommendation. Source session dates are not fabricated UTC observation clocks."
        ],
    )
    needs["reentry"] = deepcopy(today["watch"])
    needs["reentry"]["title"] = NEEDS["reentry"]
    groups = (market.get("sectors") or {}).get("groups") or []
    from scripts.lib.market_risk.risk_budget import PROFILE_SECTOR_LABELS, GROUP_TO_SECTOR

    by_sector = {
        GROUP_TO_SECTOR.get(g.get("key"), g.get("label")): g
        for g in groups
        if isinstance(g, dict) and g.get("kind", "sector") == "sector"
    }
    sector_rows = []
    for label in PROFILE_SECTOR_LABELS:
        g = by_sector.get(label)
        if g is None:
            sector_rows.append(
                {
                    "id": label,
                    "label": label,
                    "source": "market_risk canonical sector universe",
                    "clock": None,
                    "state": "grey",
                    "detail": "Not measured in the stored sector projection",
                    "facts": [fact("State", None, qualifier="Stored sector evidence not served")],
                }
            )
        else:
            sector_rows.append(
                {
                    "id": str(g.get("key") or label),
                    "label": label,
                    "source": "market_risk.sectors",
                    "clock": iso(g.get("as_of")),
                    "state": {"STRESS": "red", "WEAK": "amber", "RESILIENT": "green"}.get(g.get("state"), "grey"),
                    "facts": [
                        fact("State", g.get("state")),
                        fact("Five-session return", pct(g.get("r5"), True), state=tone(g.get("r5")), signed=True),
                        fact("Relative strength", pct(g.get("rs5"), True), state=tone(g.get("rs5")), signed=True),
                    ],
                }
            )
    outlook["sectors"] = section(
        OUTLOOK["sectors"],
        meta=rm,
        rows=sector_rows,
        notes=["Canonical eleven-sector universe; missing observations remain grey, with no invented momentum."],
    )
    parts = regime_row.get("parts") or {}
    outlook["regime"]["rows"] += [
        {"id": k, "label": k.replace("_state", "").replace("_", " "), "detail": str(v)}
        for k, v in parts.items()
        if v is not None
    ]
    futures = market.get("overnight_markets") or {}
    future_rows = []
    for i, row in enumerate(futures.get("items") or []):
        if not isinstance(row, dict):
            continue
        fm = source_meta(
            "market_risk.overnight_markets",
            row.get("as_of"),
            number(futures.get("stale_after_hours")) * 3600
            if number(futures.get("stale_after_hours")) is not None
            else None,
            now=now,
            stale=bool(row.get("stale")),
            reason=row.get("stale_reason"),
        )
        future_rows.append(
            {
                **fm,
                "id": str(row.get("symbol") or i),
                "symbol": row.get("symbol"),
                "label": str(row.get("label") or row.get("symbol") or "Market"),
                "facts": [
                    fact("Level", str(row["price"]) if number(row.get("price")) is not None else None),
                    fact(
                        "Change",
                        None if row.get("level_only") else pct(row.get("change_pct"), True),
                        state=tone(row.get("change_pct")),
                        signed=True,
                    ),
                    fact("Session", row.get("session")),
                    fact("Session date", row.get("session_date")),
                    fact("Reference", row.get("reference_date")),
                    fact("Basis", row.get("reference_basis")),
                ],
            }
        )
    outlook["futures"] = section(
        OUTLOOK["futures"],
        meta=rm,
        rows=future_rows,
        notes=["Level-only prints do not imply a measured change. Each print retains its session/reference interval."],
    )
    hedge = context.get("hedge") or {}
    hedge_metrics = []
    for key, label in (("lagging_progress", "Lagging sectors"), ("exposure_progress", "Weakening exposure")):
        raw = hedge.get(key) or {}
        val = raw.get("value") if isinstance(raw.get("value"), dict) else {}
        hedge_metrics.append(
            fact(
                label,
                str(val["current"]) + " / " + str(val["threshold"]) + " " + str(val.get("unit") or "")
                if number(val.get("current")) is not None
                and number(val.get("threshold")) is not None
                and raw.get("state") == "measured"
                else None,
                clock=iso(raw.get("as_of")),
                source=raw.get("source"),
                qualifier=raw.get("reason"),
            )
        )
    outlook["hedge"] = section(
        OUTLOOK["hedge"],
        meta=rm,
        metrics=hedge_metrics,
        notes=[
            "Existing engine thresholds only. Independent rotation trigger is not served; progress is descriptive advisory evidence."
        ],
    )
    conflicts = cio.get("conflicts") or {}
    conflict_meta = source_meta(
        "cio.pages.conflicts", conflicts.get("as_of"), now=now, stale=bool(conflicts.get("stale"))
    )
    conflict_meta, grouped_findings, deduplicated = conflict_groups(conflicts, now)
    for key, finding_rows in grouped_findings.items():
        outlook[key] = section(
            OUTLOOK[key],
            meta=conflict_meta,
            rows=finding_rows,
            notes=[
                "Registered finding kinds remain separate; priority follows the existing tier/kind/key policy. No independent engine verdict is adjudicated here."
            ],
        )
        outlook[key].update(
            unit="registered findings",
            populationLabel=OUTLOOK[key],
            totalCount=len(finding_rows),
            complete=isinstance(conflicts.get("findings"), list)
            and conflict_meta["verdict"] != "unknown"
            and not bool(conflicts.get("gap")),
            coverage=str(sum(len(v) for v in grouped_findings.values()))
            + " returned findings across categories; source cap 200; "
            + ("full source population unproven: " + str(gap_reason(conflicts.get("gap"))))
            if conflicts.get("gap")
            else str(sum(len(v) for v in grouped_findings.values()))
            + " returned findings across categories; source cap 200; no source truncation flag",
            coverageEvidence={"source_gap": conflicts.get("gap"), "exact_duplicate_records": deduplicated},
        )
    scanclock = scanner.get("latest_run_timestamp") or scanner.get("latest_scan_at")
    scanmeta = source_meta("trade_ai_cache.run_receipt", scanclock, now=now)
    if scanmeta["verdict"] == "known":
        scanmeta.update(
            verdict="partial",
            state="amber",
            reason="Stored scanner receipt; completed-run eligibility and source freshness policy are not served",
        )
    today["setups"] = section(
        TODAY["setups"],
        meta=scanmeta,
        metrics=[
            fact("Run", str(scanner["run_id"]) if scanner.get("run_id") else None),
            fact(
                "Scanned",
                str(count(scanner.get("current_run_scanned")))
                if count(scanner.get("current_run_scanned")) is not None
                else None,
            ),
            fact(
                "GO",
                str(count(scanner.get("latest_run_go_count")))
                if count(scanner.get("latest_run_go_count")) is not None
                else None,
            ),
        ],
        notes=[
            "Stored run receipt; a ranked latest-finished setup population with completed-run proof is not supplied. No ticker is promoted from a different run."
        ],
    )
    scanner_rows = []
    for bucket, key, reverse in (("Up sample", "top_gainers", True), ("Down sample", "top_losers", False)):
        sample = [g for g in (scanner.get(key) or []) if isinstance(g, dict)]
        sample.sort(
            key=lambda g: (
                number(g.get("change_pct")) is None,
                (-1 if reverse else 1) * (number(g.get("change_pct")) or 0),
                str(g.get("symbol") or ""),
            )
        )
        for i, g in enumerate(sample[:5]):
            scanner_rows.append(
                {
                    "id": key + ":" + str(i),
                    "label": str(g.get("symbol") or "Unknown"),
                    "symbol": g.get("symbol"),
                    "detail": bucket,
                    "source": str(g.get("source") or "trade_ai_cache." + key),
                    "clock": iso(g.get("captured_at")),
                    "state": "grey",
                    "facts": [
                        fact("Direction", bucket),
                        fact("Change", pct(g.get("change_pct"), True), signed=True, state=tone(g.get("change_pct"))),
                        fact("Price", money(g.get("price"))),
                        fact("Relative volume", str(g["rvol"]) if number(g.get("rvol")) is not None else None),
                    ],
                }
            )
    outlook["marketMovers"] = section(
        OUTLOOK["marketMovers"],
        meta=scanmeta,
        rows=scanner_rows,
        notes=[
            "At most five stored gainers and five stored losers; separate scanner population from held/watch and ranked setups.",
            "Down sample not served"
            if not isinstance(scanner.get("top_losers"), list)
            else "Down sample follows the stored losers list; missing is not an empty observation.",
        ],
    )
    health = health if isinstance(health, dict) else {}
    hm = source_meta("health_agent snapshot", health.get("captured_at"), 3 * 3600, now=now)
    findings = health.get("findings")
    if isinstance(findings, list) and hm["verdict"] != "unknown":
        critical = sum(
            1 for f in findings if isinstance(f, dict) and str(f.get("severity") or "").upper() == "CRITICAL"
        )
        healthstate = "grey" if hm["verdict"] != "known" else "red" if critical else "amber" if findings else "green"
        cells["health"] = cell(
            "Health",
            str(critical) + " critical / " + str(len(findings)) + " total",
            value={"critical": critical, "total": len(findings)},
            meta=hm,
            state=healthstate,
            tooltip="Same stored Health Agent findings population; snapshot threshold is needs_action.HEALTH_STALE_H=3 hours",
        )
    cells["health"]["href"] = "/v3/health"
    since = slices.get("since_close") or {}
    cio_brief = since.get("cio_brief") if isinstance(since.get("cio_brief"), dict) else {}
    own_summary = cio_brief.get("summary")
    own_narrative = (
        isinstance(own_summary, str)
        and bool(own_summary.strip())
        or isinstance(own_summary, dict)
        and bool(own_summary.get("text") or own_summary.get("lines"))
    )
    summary = own_summary if own_narrative else since.get("summary")
    text = summary.get("text") if isinstance(summary, dict) else summary if isinstance(summary, str) else None
    lines = (
        [line for line in (summary.get("lines") or []) if isinstance(line, str)] if isinstance(summary, dict) else []
    )
    if not text and lines:
        text = "Recorded deterministic lines: " + " · ".join(lines)
    summary_clock = summary.get("generated_at") if isinstance(summary, dict) else None
    brief_clock = (
        summary_clock or cio_brief.get("generated_at") or cio_brief.get("as_of")
        if own_narrative
        else summary_clock or since.get("generated_at")
    )
    bm = source_meta(
        "Saved CIO brief" if own_narrative else "Saved market-context summary",
        brief_clock,
        now=now,
        stale=bool((since.get("freshness") or {}).get("stale")),
    )
    today["brief"] = section(
        TODAY["brief"],
        meta=bm,
        notes=["Last saved narrative; its own generation snapshot is historical, not today's new answer.", text]
        if isinstance(text, str) and text.strip()
        else ["Saved snapshot found, but summary.text is absent; a timestamp-only receipt is not a narrative."],
        metrics=[fact("Generated", bm["clock"])] if bm["clock"] else [],
    )
    # Reuse exactly the same stored HomeCioCard facts/gate read by the CIO context drawer.
    card = (
        cio_card.get("card")
        if cio_card.get("schema") == "HomeCioCard@v1" and isinstance(cio_card.get("card"), dict)
        else {}
    )
    advice = cio_card.get("advice") if isinstance(cio_card.get("advice"), dict) else {}
    posture = card.get("posture") if isinstance(card.get("posture"), dict) else {}
    eligible = (
        advice.get("ok") is True
        and (cio_card.get("_product") or {}).get("status", "OK") == "OK"
        and source_meta("Saved stance", posture.get("as_of"), now=now)["verdict"] == "known"
    )
    stance_meta = source_meta(
        posture.get("source_id") or "Saved CIO synopsis",
        posture.get("as_of"),
        now=now,
        stale=not eligible,
        reason=advice.get("reason") if not eligible else None,
    )
    if posture.get("value") is not None:
        stance_facts = []
        for key, label in (("buys_line", "Buys"), ("stops_actionable", "Stops to decide")):
            raw = card.get(key) if isinstance(card.get(key), dict) else {}
            stance_facts.append(
                fact(
                    label,
                    str(raw["value"]) if raw.get("value") is not None else None,
                    clock=iso(raw.get("as_of")),
                    source=raw.get("source_id"),
                    advice=True,
                    qualifier="Current eligible stored stance"
                    if eligible
                    else "Historical only; current advice gate not satisfied",
                )
            )
        re = card.get("reentry") if isinstance(card.get("reentry"), dict) else {}
        stance_facts += [
            fact("Unprotected", None, qualifier="Largest historical example is not a complete current gap population"),
            fact(
                "Re-entry",
                str(re.get("ready"))
                + " ready / "
                + str(re.get("near"))
                + " near / "
                + str(re.get("tracked"))
                + " tracked"
                if all(count(re.get(k)) is not None for k in ("ready", "near", "tracked"))
                else None,
                clock=iso(re.get("as_of")),
            ),
        ]
        today["stance"] = section(
            "Daily decision" if eligible else "Last available CIO stance",
            meta=stance_meta,
            metrics=temp_metrics + stance_facts,
            notes=[
                (
                    "Current eligible stored stance: "
                    if eligible
                    else "Last available stance (historical, not currently eligible): "
                )
                + str(posture["value"]),
                advice.get("reason") or "Existing advice eligibility gate satisfied",
            ],
            links=[{"label": "Review queue", "href": "/wealth/home/needs"}],
        )
        today["stance"].update(
            eligibility="current" if eligible else "historical",
            stanceText=str(posture["value"]),
            sourceBuildClock=iso(cio_card.get("generated_at")),
        )
        cells["temperature"]["secondary"] = [
            ("Stance: " if eligible else "Last stance: ") + str(posture["value"]),
            "Stance source " + str(iso(posture.get("as_of"))),
        ]
    elif cio_card and cio_card.get("schema") != "HomeCioCard@v1":
        today["stance"]["notes"] = ["Saved stance schema unsupported; no current decision can be mapped"]
    else:
        today["stance"]["notes"] = [
            "No dated posture fact in the saved CIO card; current decision missing",
            advice.get("reason") or "No source stance record available",
        ]
    sources = {
        "portfolio": pm,
        "positions": sm,
        "temperature": rm,
        "regime": gm,
        "vix": vm,
        "queue": qm,
        "incidents": im,
        "brief": bm,
    }
    source_rows = [
        {
            "id": k,
            "label": k,
            "detail": v["reason"] or "Stored source answered",
            "clock": v["clock"],
            "source": v["source"],
            "state": v["state"],
            "href": "/v3/health",
            "links": [{"label": "Review source health", "href": "/v3/health"}],
        }
        for k, v in sources.items()
    ]
    today["pulse"] = section(
        TODAY["pulse"],
        meta=source_meta("Home v2 read coverage", now, now=now),
        rows=source_rows,
        notes=["These are Home source-read states, not platform health findings."],
    )
    needs["sourceNotices"] = section(
        NEEDS["sourceNotices"],
        meta=source_meta("Home v2 source gaps", now, now=now),
        rows=[r for r in source_rows if r["state"] != "green"],
        notes=["Fix-feed review only; this page does not schedule or mutate jobs."],
    )
    return {
        "schema": "WealthHome@v2",
        "contract_revision": "home-corrective@v1",
        "built_at": iso(now),
        "queue_total": queue_total,
        "header": {
            "schema": "WealthOperatingHeader@v1",
            "contract_revision": "home-corrective@v1",
            "as_of": iso(now),
            "session": session,
            "poll_after_s": 300 if session["key"] == "closed" else 60,
            "queue_total": queue_total,
            "cells": cells,
        },
        "today": today,
        "outlook": outlook,
        "needs": needs,
        "sources": sources,
    }


def collect(ctx, slices, *, now=None):
    """Existing Home producer extension: bounded stored reads, never an inline legacy API build."""
    now = now or datetime.now(UTC)
    from scripts.lib.cc_products import cio_pages_route, product_route

    upstream_fetch = cio_pages_route.make_pg_fetch_row(ctx.db_query_raising)
    cache = {}

    def fetch(product_id, scope_key):
        key = (product_id, scope_key)
        if key not in cache:
            cache[key] = upstream_fetch(product_id, scope_key)
        return cache[key]

    def stored_file(path):
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                return {}
            body = json.loads(path.read_bytes())
            return body if isinstance(body, dict) else {}
        except (OSError, ValueError):
            return {}

    cio = cio_pages_route.serve_cio_pages(fetch_row=fetch, now=now)
    market = product_route.serve_market_risk_latest(fetch_row=fetch, now=now)
    cio_card = product_route.serve_home_cio_card(fetch_row=fetch, now=now)
    # Canonical SELECT-only document used by existing approved readers; no broker/API path.
    from scripts.lib.holdings_document import load_document

    holdings = (
        load_document(store=ctx.portfolio_state_dir / ("holdings" + ".json"), db_query=ctx.db_query)
        if callable(getattr(ctx, "db_query", None))
        else {}
    )
    runtime = getattr(ctx, "runtime_dir", None)
    overview = stored_file(runtime / "overview_projection.json").get("body") or {} if runtime is not None else {}
    scanner = stored_file(runtime / "trade_ai_cache.json") if runtime is not None else {}
    state_dir = getattr(ctx, "portfolio_state_dir", None)
    health = stored_file(state_dir / "health_agent_status.json") if state_dir is not None else {}
    result = build(
        cio=cio,
        market=market,
        overview=overview,
        scanner=scanner,
        slices=slices,
        health=health,
        cio_card=cio_card,
        holdings=holdings,
        now=now,
    )
    for key, document in (("cio.pages", cio), ("market_risk.latest", market)):
        result["sources"][key] = {
            **{
                k: v
                for k, v in (document.get("_product") or {}).items()
                if k in ("status", "greyed", "as_of", "built_at", "seq", "reason", "stale_after_s", "hard_expiry_s")
            },
            "source": key,
        }
    # Envelope status qualifies every dependent field, not just the operating header.
    for document, dependencies, cells in (
        (cio, ("portfolio", "positions", "regime", "queue"), ("account_value", "session_pl", "regime")),
        (market, ("temperature",), ("temperature",)),
    ):
        if (document.get("_product") or {}).get("status") != "OK":
            reason = "Stored source product is not current; retained evidence only"
            for key in dependencies:
                invalidate(result["sources"][key], reason)
            for key in cells:
                invalidate(result["header"]["cells"][key], reason)
            sources = {result["sources"][k]["source"] for k in dependencies}
            for group in ("today", "outlook", "needs"):
                for panel in result[group].values():
                    if (
                        panel.get("source") in sources
                        or (document is cio and panel.get("source", "").startswith("cio.pages"))
                        or (document is market and panel.get("source", "").startswith("market_risk"))
                    ):
                        invalidate(panel, reason)
    validate_contract(result)
    return result


def invalidate(item, reason):
    """Withdraw the owning observation's currentness without contaminating unrelated/static facts."""
    if not isinstance(item, dict):
        return
    item.update(verdict="stale", reason=reason)
    if not item.get("signed"):
        item["state"] = "grey"
    item["qualifier"] = reason
    if item.get("eligibility") in ("current", "historical"):
        item.update(eligibility="historical", title="Last available CIO stance")
        item["notes"] = [
            "Last available stance (historical, not currently eligible): "
            + str(item.get("stanceText") or "Retained dated stance"),
            reason,
        ]
        for metric in item.get("metrics") or []:
            if isinstance(metric, dict) and metric.get("advice"):
                metric.update(state="grey", qualifier="Historical only; current advice gate not satisfied")

    def withdraw_status(node):
        if not isinstance(node, dict) or node.get("applicability"):
            return
        if node.get("current_status"):
            node.update(verdict="stale", state="grey", qualifier="Current proof unavailable; retained observation")
        for key in ("metrics", "rows", "facts"):
            for child in node.get(key) or []:
                withdraw_status(child)

    withdraw_status(item)


def validate_contract(body):
    """Required slice presence gate in the existing Home producer; malformed output never publishes."""
    if body.get("schema") != "WealthHome@v2":
        raise ValueError("Wealth Home schema missing")
    expected = {"session", "session_pl", "account_value", "temperature", "regime", "vix", "operating_mode", "health"}
    if set(body.get("header", {}).get("cells", {})) != expected:
        raise ValueError("Home operating header requires eight cells")
    for group, keys in (("today", TODAY), ("outlook", OUTLOOK), ("needs", NEEDS)):
        if set(body.get(group, {})) != set(keys):
            raise ValueError("Home panel coverage missing: " + group)
        for panel in body[group].values():
            if not isinstance(panel.get("rows"), list) or not isinstance(panel.get("metrics"), list):
                raise ValueError("Home panel rows/metrics malformed")
    for c in body["header"]["cells"].values():
        if c.get("state") not in {"green", "amber", "red", "grey"}:
            raise ValueError("Home state must be a color")
        if c.get("display") is not None and c.get("value") is None:
            raise ValueError("Served header display requires typed value")
    return body


def serve(stored, *, now=None, header_only=False):
    """Age stored results and refresh calendar only. Does not call collect/build or any DB/provider."""
    now = now or datetime.now(UTC)
    if not isinstance(stored, dict) or stored.get("schema") != "WealthHome@v2":
        stored = {
            "schema": "WealthHome@v2",
            "header": {
                "schema": "WealthOperatingHeader@v1",
                "cells": {
                    k: cell(label)
                    for k, label in (
                        ("session", "Session"),
                        ("session_pl", "Session P/L estimate"),
                        ("account_value", "Household value"),
                        ("temperature", "Temperature"),
                        ("regime", "Regime"),
                        ("vix", "VIX"),
                        ("operating_mode", "Operating mode"),
                        ("health", "Health"),
                    )
                },
            },
            "today": {k: section(v) for k, v in TODAY.items()},
            "outlook": {k: section(v) for k, v in OUTLOOK.items()},
            "needs": {k: section(v) for k, v in NEEDS.items()},
            "sources": {},
        }
    out = deepcopy(stored)
    product = stored.get("_product") or {}
    product_stale = bool(product) and (
        product.get("status") != "OK" or product.get("greyed") or product.get("slice_stale")
    )

    def age(item, inherited_stale=False, root=True):
        if not isinstance(item, dict):
            return
        stale = inherited_stale
        if "verdict" in item and item.get("source"):
            meta = source_meta(
                item["source"],
                item.get("clock"),
                item.get("stale_after_s"),
                now=now,
                reason=item.get("reason"),
                stale=item.get("verdict") == "stale",
            )
            item.update(age_s=meta["age_s"], evaluated_at=meta["evaluated_at"], clock_delta_s=meta["clock_delta_s"])
            stale = stale or meta["verdict"] in ("unknown", "stale")
            if stale:
                item.update(verdict=meta["verdict"], reason=meta["reason"])
                if not item.get("signed"):
                    item["state"] = COLORS[meta["verdict"]]
        if (product_stale and root) or inherited_stale:
            invalidate(item, "Stored Home/source product is not current; retained evidence only")
        elif stale:
            item["qualifier"] = item.get("reason") or "Source freshness is unproven"
            for child in item.get("facts") or []:
                if isinstance(child, dict) and child.get("current_status") and not child.get("applicability"):
                    child.update(state="grey", qualifier="Current proof unavailable; retained observation")
        for key in ("metrics", "rows", "facts"):
            for child in item.get(key) or []:
                age(child, False, False)

    for name in ("today", "outlook", "needs", "sources"):
        for item in out.get(name, {}).values():
            age(item)
    header = out["header"]
    stance = (out.get("today") or {}).get("stance") or {}
    if stance.get("eligibility") == "historical" and stance.get("stanceText"):
        header["cells"]["temperature"]["secondary"] = [
            "Last stance: " + stance["stanceText"],
            "Stance source " + str(stance.get("clock")),
        ]
    for item in header["cells"].values():
        age(item)
    session = session_clock(now)
    header.update(as_of=iso(now), session=session, poll_after_s=300 if session["key"] == "closed" else 60)
    header["cells"]["session"] = cell(
        "Session",
        session["label"],
        value=session,
        meta=source_meta("NYSE exchange calendar", now, now=now),
        state="grey",
        secondary=[
            "Last session " + session["last_session_date"],
            "Next open " + timestamp(session["next_open"]).astimezone(sessions.ET).strftime("%a %b %d %H:%M ET"),
        ],
    )
    return header if header_only else out
