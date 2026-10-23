"""home_do_now.py — the Home "Do now" queue, HomeDoNow@v1 (operator-approved Home redesign, 2026-10-22).

GET /api/v2/home/do-now. One queue replaces five Home boxes (Needs action, Requires attention, Operator inbox,
Top risks, Platform). It is a READ projection over sources that already exist; it adds no store and no writer:

  source        read through                                             what it contributes
  ------------  -------------------------------------------------------  -----------------------------------------
  needs_action  api_v2._needs_action (NeedsAction@v1, 30 s cache)        system/data/approval items (fix, decide)
  inbox         api_v2._inbox (operator inbox)                           stop alerts, SIEM, escalations, CIO review
  risk          data_broker.risk_snapshot.get_risk_snapshot              triggered / near / no-stop positions, heat
  desk_truth    needs_action.probe_desk_truth (lane receipts, files)     no WORKING stop findings (held-exit-coverage)
  proposals     paper_trade_proposals COUNT (read-only, this module)     pending paper proposals
  deploy        api_v2._deploy_events (open post-sale redeploys)         redeploy decisions

Each item: ``{id, category: protect|decide|fix, severity: P0..P3, title, why, action: {label, where}, money_at_risk_usd,
money_basis, sources[], since, evidence}``. ``id`` is the dedupe key: the same fact from two sources (a symbol with no
working stop seen by the risk snapshot, the desk-truth monitor and an inbox stop alert) is ONE item that lists every
source. Sort: items with money at risk first (largest first), then severity, then category, then title.

Freshness is per source: ``sources[name] = {status, as_of, as_of_basis, age_s, stale, error, ms}``. A source that
raises, times out or answers malformed becomes one P2 "fix" item and ``all_sources_answered`` is false — the page
never shows an all-clear it did not measure (the needs-action invariant, tests/test_cc_needs_action_20261021.py).

Positions come from the risk snapshot (the holdings file: values, stops, heat), filtered by the positions_store reader
batch #3 (operator 2026-10-22, "approve all" item G; config/data_source_authority.json positions_store
approved_readers batch 3): when watch_domains.held_positions(surface=HOME_SURFACE) answers fresh from
positions_current, a symbol the broker no longer holds is not a Home item. A stale, empty or unreadable store falls
back to the holdings file with an explicit fallback_reason. Every number names that basis.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0: nothing here sizes, orders, stops, weights, sends, writes or calls a
broker. The risk snapshot is read without the /api/v2/risk broker-stop overlay on purpose — working-stop truth comes
from the desk-truth monitor's receipt, so this projection never causes a broker read.
"""

from __future__ import annotations

import concurrent.futures as cf
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

SCHEMA = "HomeDoNow@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
SEVERITIES = ("P0", "P1", "P2", "P3")
CATEGORIES = ("protect", "decide", "fix")
DEFAULT_TIMEOUT_S = 8.0
TOP_N = 7

NEAR_STOP_PCT = 2.0
UNPROTECTED_ITEM_MIN_USD = 10_000.0
UNPROTECTED_ITEMS_MAX = 3
HEAT_LIMIT_PCT = 5.0
COVERAGE_LANE = "held-exit-coverage-monitor"
COVERAGE_STALE_H = 26.0

# Per-source age after which the source is labelled STALE (seconds).
STALE_AFTER_S = {
    "needs_action": 300,
    "inbox": 300,
    "risk": 900,
    "desk_truth": int(COVERAGE_STALE_H * 3600),
    "proposals": 300,
    "deploy": 3600,
    "held": 259200,  # positions_store reader batch #3: the held reader carries its own stale verdict (used below)
}

# Inbox SQL row limits (api_v2._inbox): a count equal to its limit is a floor, never a total.
INBOX_LIMITS = {"stops": 25, "siem": 15, "escalations": 60, "cio_review": 40, "auto_research": 12}

# needs-action sources that roll up into one item per (source, severity) when they produce more than one item.
ROLLUP_SOURCES = {
    "data_sources": "data sources down or erroring",
    "pipelines": "pipelines failing",
    "pr_hygiene": "pull requests need hygiene",
    "approvals": "approvals expired or expiring",
}

ACTION_LABEL = {
    "health": "Open Health",
    "systemd": "Open Jobs",
    "n8n": "Open n8n",
    "approvals": "Decide",
    "queue": "Open queue",
    "data_plausibility": "Data checks",
    "data_sources": "Data sources",
    "comms": "Open comms",
    "pipelines": "Diagnose",
    "pr_hygiene": "Open PRs",
    "desk_truth": "Data sources",
    "release_window": "Release train",
    "macro_calendar": "Release train",
}

R_RISK = "/v3/risk"
R_PROPOSALS = "/v3/trading?tab=Proposals"
R_REDEPLOY = "/v3/portfolio?tab=Redeploy"
R_SYSTEM = "/v3/system"
R_HEALTH = "/v3/health"
R_COORD = "/v3/coordination"


class SourceUnavailable(Exception):
    """The source answered, but the answer cannot be used."""


# ── small helpers ──────────────────────────────────────────────────────────────────────────────────────────────


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN -> None


def _usd(v: float) -> str:
    return f"${abs(v):,.0f}"


def _unwrap(p: Any) -> Any:
    if isinstance(p, dict) and isinstance(p.get("data"), dict) and "ok" in p:
        return p["data"]
    return p


def _floor(n: int, limit: int) -> str:
    return f"{n}+" if n >= limit else str(n)


def item(
    key: str,
    category: str,
    severity: str,
    title: str,
    why: str,
    action_label: str,
    where: str,
    source: str,
    *,
    money: Optional[float] = None,
    money_basis: Optional[str] = None,
    since: Optional[str] = None,
    evidence: Any = None,
) -> dict[str, Any]:
    assert category in CATEGORIES, category
    assert severity in SEVERITIES, severity
    return {
        "id": key,
        "category": category,
        "severity": severity,
        "title": title,
        "why": why,
        "action": {"label": action_label, "where": where},
        "money_at_risk_usd": round(money, 2) if money else None,
        "money_basis": money_basis if money else None,
        "sources": [source],
        "since": since,
        "evidence": evidence,
    }


# ── rules (pure: payload -> items) ─────────────────────────────────────────────────────────────────────────────


def coverage_from_receipts(receipts: Any, now: datetime) -> dict[str, Any]:
    """Working-stop coverage from the held-exit-coverage-monitor receipt.

    Returns {measured, verdict, as_of, uncovered: {SYM: [accounts]}, reason}. ``measured`` is true only when the
    receipt exists, the run succeeded, it is younger than COVERAGE_STALE_H and its verdict is COVERED or GAPS; a
    NOT_MEASURED verdict (stale stop snapshot) or a missing receipt is never treated as coverage."""
    if not isinstance(receipts, dict):
        raise SourceUnavailable("desk truth receipts are not an object")
    r = receipts.get(COVERAGE_LANE)
    if not isinstance(r, dict) or r.get("status") == "NO_RECEIPT":
        return {"measured": False, "verdict": "NO_RECEIPT", "as_of": None, "uncovered": {},
                "reason": "no held-exit-coverage receipt yet (the lane runs dry at shadow)"}
    summary = r.get("summary") if isinstance(r.get("summary"), dict) else {}
    as_of = summary.get("as_of") or r.get("ok_at") or r.get("finished_at")
    ok_at = _parse(r.get("ok_at"))
    verdict = str(summary.get("coverage_verdict") or "UNKNOWN")
    uncovered: dict[str, list[str]] = {}
    for f in summary.get("findings") or []:
        if not isinstance(f, dict) or f.get("code") != "UNCOVERED":
            continue
        parts = str(f.get("key") or "").split(":")
        if len(parts) >= 3:
            uncovered.setdefault(parts[-1].upper(), []).append(":".join(parts[1:-1]))
    reason = None
    if r.get("status") != "ok":
        reason = f"last run failed: {str(r.get('error') or 'unknown')[:120]}"
    elif ok_at is None or (now - ok_at).total_seconds() / 3600.0 > COVERAGE_STALE_H:
        reason = f"no completed run in {COVERAGE_STALE_H:g} h"
    elif verdict not in ("COVERED", "GAPS"):
        reason = f"verdict {verdict}"
    return {"measured": reason is None, "verdict": verdict, "as_of": as_of, "uncovered": uncovered,
            "reason": reason, "held": summary.get("held"), "covered": summary.get("covered")}


def held_filter(held: Any) -> tuple[Optional[set[str]], str, Optional[str]]:
    """(held symbols or None, positions_source label, fallback_reason) from the positions_store reader batch #3.

    Operator 2026-10-22, verbatim: "yes i approve 'approve all' (A–L)" (item G: Home reads positions through the
    broker-synced store, reader batch #3; config/data_source_authority.json positions_store approved_readers batch 3).
    Only a fresh positions_current answer filters the risk snapshot (a symbol the broker no longer holds — e.g. a
    stop that filled after the holdings file was written — is not a Home item). A stale, empty or unreadable store
    falls back to the holdings file with the reader's explicit fallback_reason, never silently."""
    if not isinstance(held, dict):
        return None, "the holdings file via data_broker.risk_snapshot (held reader not answered)", "held_reader_unavailable"
    src = held.get("source")
    if src == "positions_store.positions_current" and not held.get("stale"):
        syms = {str(x).upper() for x in (held.get("symbols") or ())}
        return syms, f"positions_store.positions_current (reader batch #3, as of {held.get('as_of')}) filtering the risk snapshot", None
    reason = held.get("fallback_reason") or ("holdings_stale" if held.get("stale") else "positions_store_reader_off")
    return None, f"the holdings file via data_broker.risk_snapshot (fallback: {reason})", reason


def rule_risk(snapshot: Any, coverage: Optional[dict], now: datetime, held: Any = None) -> tuple[list[dict], dict]:
    """Protect items from the risk snapshot (+ working-stop coverage when measured). Returns (items, numbers).
    ``held`` is the positions_store reader batch #3 answer (watch_domains.held_positions(surface=HOME_SURFACE))."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("positions"), list):
        raise SourceUnavailable("risk snapshot has no positions list")
    as_of = snapshot.get("computed_at")
    cov = coverage or {"measured": False, "uncovered": {}, "reason": "desk truth not read"}
    held_syms, positions_source, held_fallback = held_filter(held) if held is not None else (
        None, "the holdings file via data_broker.risk_snapshot (held reader not wired)", "held_reader_not_wired")
    not_held: list[str] = []
    by_sym: dict[str, dict[str, Any]] = {}
    for p in snapshot["positions"]:
        if not isinstance(p, dict) or p.get("risk_excluded"):
            continue
        sym = str(p.get("symbol") or "").upper()
        if not sym:
            continue
        if held_syms is not None and sym not in held_syms:
            if sym not in not_held:
                not_held.append(sym)
            continue
        row = by_sym.setdefault(sym, {"value": 0.0, "accounts": [], "stop": False, "triggered": False,
                                      "near": None, "max_loss": 0.0, "day_pct": None})
        row["value"] += _num(p.get("market_value")) or 0.0
        acct = str(p.get("account") or "")
        if acct and acct not in row["accounts"]:
            row["accounts"].append(acct)
        if p.get("stop_price") is not None:
            row["stop"] = True
        if p.get("triggered"):
            row["triggered"] = True
        dist = _num(p.get("distance_to_stop_pct"))
        if dist is not None and 0 <= dist <= NEAR_STOP_PCT:
            row["near"] = dist if row["near"] is None else min(row["near"], dist)
            row["max_loss"] += abs(_num(p.get("max_loss_dollar")) or 0.0)
        if row["day_pct"] is None:
            row["day_pct"] = _num(p.get("day_change_pct"))

    out: list[dict] = []
    for sym, r in by_sym.items():
        accts = ", ".join(r["accounts"]) or "account unknown"
        if r["triggered"]:
            out.append(item(f"stop:{sym}", "protect", "P0", f"{sym} is below its stop",
                            f"Price is through the stop on record ({accts}). Verify the broker executed it.",
                            f"Review {sym}", f"{R_RISK}?symbol={sym}", "risk", money=r["value"],
                            money_basis="market value of the position", since=as_of,
                            evidence={"symbol": sym, "accounts": r["accounts"]}))
        elif r["near"] is not None:
            out.append(item(f"stop:{sym}", "protect", "P2", f"{sym} stop {r['near']:.1f}% away",
                            f"Stop on record is within {NEAR_STOP_PCT:g}% of price ({accts}).", f"Open {sym}",
                            f"{R_RISK}?symbol={sym}", "risk", money=r["max_loss"] or None,
                            money_basis="loss if the stop fills (max_loss_dollar)", since=as_of,
                            evidence={"symbol": sym, "distance_pct": r["near"]}))

    # No-stop items. When working-stop coverage is measured, it is the truth (§26: one fact, one source): only
    # its UNCOVERED symbols are items. Otherwise fall back to "no stop on record" from the snapshot, labelled.
    total_value = sum(r["value"] for r in by_sym.values()) or None
    if cov.get("measured"):
        no_stop = {s: by_sym.get(s, {"value": 0.0, "accounts": a, "day_pct": None}) for s, a in cov["uncovered"].items()}
        basis = "no WORKING stop at the broker (held-exit-coverage monitor"
        basis += f", as of {cov.get('as_of')})" if cov.get("as_of") else ")"
        src = "desk_truth"
    else:
        no_stop = {s: r for s, r in by_sym.items() if not r["stop"]}
        basis = "no stop on record (risk snapshot); working-stop coverage not measured"
        basis += f" — {cov.get('reason')}" if cov.get("reason") else ""
        src = "risk"
    ranked = sorted(no_stop.items(), key=lambda kv: -(kv[1].get("value") or 0.0))
    for sym, r in ranked[:UNPROTECTED_ITEMS_MAX]:
        v = r.get("value") or 0.0
        if v < UNPROTECTED_ITEM_MIN_USD:
            continue
        share = f", {v / total_value * 100:.1f}% of invested value" if total_value else ""
        day = r.get("day_pct")
        day_txt = f" · {day:+.2f}% today" if day is not None else ""
        accts = ", ".join(r.get("accounts") or []) or "account unknown"
        out.append(item(f"stop:{sym}", "protect", "P1", f"{sym} {_usd(v)} has no stop",
                        f"{accts}{share}{day_txt}. Basis: {basis}.", f"Review {sym}",
                        f"{R_RISK}?symbol={sym}", src, money=v, money_basis="market value with no stop",
                        since=cov.get("as_of") if src == "desk_truth" else as_of,
                        evidence={"symbol": sym, "accounts": r.get("accounts")}))
    if no_stop:
        unprot_value = sum(r.get("value") or 0.0 for r in no_stop.values())
        syms = [s for s, _ in ranked]
        shown = ", ".join(syms[:6]) + (f" and {len(syms) - 6} more" if len(syms) > 6 else "")
        out.append(item("stops:unprotected", "protect", "P1",
                        f"{len(no_stop)} position{'s' if len(no_stop) != 1 else ''} with no stop",
                        f"{shown} · {_usd(unprot_value)} in total. Basis: {basis}.", "Set stops", R_RISK, src,
                        money=unprot_value, money_basis="combined market value with no stop",
                        since=cov.get("as_of") if src == "desk_truth" else as_of,
                        evidence={"symbols": syms, "count": len(no_stop)}))
    port = snapshot.get("portfolio") if isinstance(snapshot.get("portfolio"), dict) else {}
    numbers = {
        "unprotected_positions": len(no_stop),
        "unprotected_value_usd": round(sum(r.get("value") or 0.0 for r in no_stop.values()), 2),
        "unprotected_basis": basis,
        "unprotected_source": src,
        "positions_counted": len(by_sym),
        "heat_pct": _num(port.get("heat_pct")),
        "heat_limit_pct": HEAT_LIMIT_PCT,
        "heat_basis": "risk_management.json portfolio_heat_pct via the risk snapshot: summed loss-to-stop as % of book",
        "as_of": as_of,
        "positions_source": positions_source,
        "positions_store_fallback_reason": held_fallback,
        "not_held_per_store": sorted(not_held),
    }
    return out, numbers


def rule_needs_action(p: Any, now: datetime) -> list[dict]:
    p = _unwrap(p)
    if not isinstance(p, dict) or not isinstance(p.get("items"), list):
        raise SourceUnavailable("needs-action payload has no items list")
    out: list[dict] = []
    groups: dict[tuple[str, str], list[dict]] = {}
    for i in p["items"]:
        if not isinstance(i, dict) or i.get("severity") not in SEVERITIES:
            continue
        src = str(i.get("source") or "needs_action")
        ev = i.get("evidence") if isinstance(i.get("evidence"), dict) else {}
        key_ev = str(ev.get("key") or "")
        if src == "desk_truth" and key_ev.startswith("uncovered:"):
            # The same finding the risk rule reads straight from the receipt: merged there, not repeated here.
            sym = key_ev.split(":")[-1].upper()
            out.append(item(f"stop:{sym}", "protect", "P2", f"{sym} has no working stop", str(i.get("why") or ""),
                            f"Review {sym}", f"{R_RISK}?symbol={sym}", "needs_action:desk_truth",
                            since=i.get("since"), evidence=ev))
            continue
        title = str(i.get("title") or "")
        cat = "fix"
        if src == "approvals":
            cat = "decide"
        elif src == "health" and (ev.get("category") == "risk_protection" or "kill switch" in title.lower()):
            cat = "protect"
        if src in ROLLUP_SOURCES:
            groups.setdefault((src, i["severity"]), []).append(i)
            continue
        out.append(item(f"na:{src}:{title}", cat, i["severity"], title, str(i.get("why") or ""),
                        ACTION_LABEL.get(src, "Open"), str(i.get("where") or R_HEALTH), f"needs_action:{src}",
                        since=i.get("since"), evidence=ev or None))
    for (src, sev), rows in groups.items():
        cat = "decide" if src == "approvals" else "fix"
        if len(rows) == 1:
            r = rows[0]
            out.append(item(f"na:{src}:{r.get('title')}", cat, sev, str(r.get("title") or ""), str(r.get("why") or ""),
                            ACTION_LABEL.get(src, "Open"), str(r.get("where") or R_HEALTH), f"needs_action:{src}",
                            since=r.get("since"), evidence=r.get("evidence")))
            continue
        titles = [str(r.get("title") or "") for r in rows]
        why = "; ".join(t[:60] for t in titles[:3]) + (f"; and {len(titles) - 3} more" if len(titles) > 3 else "")
        since = max((str(r.get("since")) for r in rows if r.get("since")), default=None)
        out.append(item(f"na:{src}:{sev}", cat, sev, f"{len(rows)} {ROLLUP_SOURCES[src]}", why,
                        ACTION_LABEL.get(src, "Open"), str(rows[0].get("where") or R_HEALTH), f"needs_action:{src}",
                        since=since, evidence={"rolled_up": len(rows)}))
    return out


def rule_inbox(p: Any, now: datetime) -> list[dict]:
    p = _unwrap(p)
    if not isinstance(p, dict) or not isinstance(p.get("items"), list):
        raise SourceUnavailable("inbox payload has no items list")
    out: list[dict] = []
    stops: dict[str, list[dict]] = {}
    for i in p["items"]:
        if isinstance(i, dict) and i.get("type") == "stop" and i.get("symbol"):
            stops.setdefault(str(i["symbol"]).upper(), []).append(i)
    for sym, rows in stops.items():
        latest = max(rows, key=lambda r: str(r.get("at") or ""))
        out.append(item(f"stop:{sym}", "protect", "P0", f"{sym} stop alert",
                        f"Stop alert in the last 2 days: {str(latest.get('detail') or '')[:120]}. Verify at the broker.",
                        f"Review {sym}", f"{R_RISK}?symbol={sym}", "inbox", since=latest.get("at"),
                        evidence={"alerts": len(rows)}))

    def lane(kind: str) -> list[dict]:
        return [i for i in p["items"] if isinstance(i, dict) and i.get("type") == kind]

    siem = lane("siem")
    if siem:
        n = int(p.get("siem") or len(siem))
        sev = "P0" if any(i.get("priority") == "P0" for i in siem) else "P1"
        comps = sorted({str(i.get("detail") or "").split(" — ")[0] for i in siem})
        out.append(item("inbox:siem", "fix", sev, f"{_floor(n, INBOX_LIMITS['siem'])} critical system events (24 h)",
                        "Unresolved SIEM events: " + ", ".join(comps[:4]) + ("…" if len(comps) > 4 else ""),
                        "Open SIEM", f"{R_SYSTEM}?tab=SIEM", "inbox",
                        since=max((str(i.get("at")) for i in siem if i.get("at")), default=None)))
    esc = lane("escalation")
    if esc:
        n = int(p.get("escalations") or len(esc))
        syms = sorted({str(i.get("symbol")) for i in esc if i.get("symbol")})
        out.append(item("inbox:escalations", "decide", "P1",
                        f"{_floor(n, INBOX_LIMITS['escalations'])} agent escalations (14 d)",
                        ("Symbols: " + ", ".join(syms[:5]) + ("…" if len(syms) > 5 else "")) if syms else
                        "Agents escalated these to you.", "Open agents", "/v3/agents", "inbox",
                        since=max((str(i.get("at")) for i in esc if i.get("at")), default=None)))
    cio = lane("cio_review")
    if cio:
        n = int(p.get("cio_review") or len(cio))
        syms = sorted({str(i.get("symbol")) for i in cio if i.get("symbol")})
        out.append(item("inbox:cio_review", "decide", "P2",
                        f"{_floor(n, INBOX_LIMITS['cio_review'])} CIO decisions need your review (14 d)",
                        ("Symbols: " + ", ".join(syms[:5]) + ("…" if len(syms) > 5 else "")) if syms else
                        "Marked human_review_required.", "Open CIO desk", "/v3/intelligence", "inbox",
                        since=max((str(i.get("at")) for i in cio if i.get("at")), default=None)))
    ar = lane("auto_research")
    if ar:
        n = int(p.get("auto_research") or len(ar))
        out.append(item("inbox:auto_research", "decide", "P3",
                        f"{_floor(n, INBOX_LIMITS['auto_research'])} auto-research briefs (7 d)",
                        "Read when convenient; none asks for an action.", "Read briefs",
                        "/v3/intelligence?tab=research", "inbox",
                        since=max((str(i.get("at")) for i in ar if i.get("at")), default=None)))
    props = lane("proposal")
    if props:
        # Merged into the proposals item (id proposals:pending); the proposals source owns the count.
        syms = [str(i.get("symbol")) for i in props if i.get("symbol")]
        out.append(item("proposals:pending", "decide", "P2", f"{len(props)}+ paper proposals waiting",
                        "Symbols: " + ", ".join(syms[:5]), "Review proposals", R_PROPOSALS, "inbox",
                        since=min((str(i.get("at")) for i in props if i.get("at")), default=None),
                        evidence={"inbox_rows": len(props), "inbox_limit": 30}))
    return out


def rule_proposals(p: Any, now: datetime) -> list[dict]:
    if not isinstance(p, dict) or _num(p.get("pending")) is None:
        raise SourceUnavailable("pending-proposal count unavailable")
    n = int(p["pending"])
    if n <= 0:
        return []
    oldest = _parse(p.get("oldest_at"))
    age = ""
    if oldest is not None:
        h = (now - oldest).total_seconds() / 3600.0
        age = f" Oldest {h / 24:.0f} d." if h >= 48 else f" Oldest {h:.0f} h."
    syms = [str(s) for s in p.get("symbols") or [] if s]
    shown = ", ".join(syms[:5]) + (f" and {n - min(len(syms), 5)} more" if n > min(len(syms), 5) else "")
    return [item("proposals:pending", "decide", "P2", f"{n} paper proposal{'s' if n != 1 else ''} waiting",
                 f"{shown}.{age} Count as stored; stale ones expire when the Proposals page loads.",
                 "Review proposals", R_PROPOSALS, "proposals", since=p.get("oldest_at"),
                 evidence={"pending": n})]


def rule_deploy(p: Any, now: datetime) -> list[dict]:
    if not isinstance(p, dict) or p.get("ok") is False:
        raise SourceUnavailable(str((p or {}).get("error") if isinstance(p, dict) else "deploy events missing"))
    events = [e for e in p.get("events") or [] if isinstance(e, dict)]
    n = int(p.get("recent_14d_count") or 0)
    if not events or n <= 0:
        return []
    top = events[0]
    proceeds = _num(top.get("proceeds_usd")) or 0.0
    title = (f"Redeploy {_usd(proceeds)} from the {top.get('symbol')} sale" if top.get("symbol") and proceeds
             else f"{n} post-sale redeploy decisions open")
    return [item("deploy:open", "decide", "P2", title,
                 f"{n} post-sale redeploy event{'s' if n != 1 else ''} in 14 days; advisory only.", "Redeploy",
                 R_REDEPLOY, "deploy", since=str(top.get("sold_at") or "") or None,
                 evidence={"events": n, "material_proceeds_usd": p.get("material_proceeds_usd")})]


# ── merge, sort, freshness ─────────────────────────────────────────────────────────────────────────────────────


def merge(items: list[dict]) -> list[dict]:
    """One item per id. Most severe severity, largest money, first title of the most severe, every source listed."""
    order = {s: i for i, s in enumerate(SEVERITIES)}
    out: dict[str, dict] = {}
    for it in items:
        cur = out.get(it["id"])
        if cur is None:
            out[it["id"]] = {**it, "sources": list(it["sources"]), "merged": 1}
            continue
        cur["merged"] += 1
        for s in it["sources"]:
            if s not in cur["sources"]:
                cur["sources"].append(s)
        if order[it["severity"]] < order[cur["severity"]]:
            for k in ("severity", "title", "category", "action"):
                cur[k] = it[k]
            cur["why"] = it["why"] + (" · " + cur["why"] if cur["why"] and cur["why"] != it["why"] else "")
        elif it["why"] and it["why"] not in cur["why"]:
            cur["why"] = (cur["why"] + " · " + it["why"]) if cur["why"] else it["why"]
        if (it.get("money_at_risk_usd") or 0) > (cur.get("money_at_risk_usd") or 0):
            cur["money_at_risk_usd"], cur["money_basis"] = it["money_at_risk_usd"], it["money_basis"]
        if it.get("since") and (not cur.get("since") or str(it["since"]) > str(cur["since"])):
            cur["since"] = it["since"]
    return list(out.values())


def sort_items(items: list[dict]) -> list[dict]:
    sev = {s: i for i, s in enumerate(SEVERITIES)}
    cat = {c: i for i, c in enumerate(CATEGORIES)}
    return sorted(items, key=lambda i: (0 if (i.get("money_at_risk_usd") or 0) > 0 else 1,
                                        -(i.get("money_at_risk_usd") or 0), sev[i["severity"]], cat[i["category"]],
                                        i["title"]))


def source_meta(name: str, payload: Any, now: datetime, read_at: datetime) -> dict[str, Any]:
    """as_of + basis + age + stale for one answered source. Sources with no clock of their own use the read time
    and say so (``as_of_basis: read_at``) — a live DB read, not a cached file."""
    as_of, basis = None, "read_at"
    p = _unwrap(payload)
    if name == "needs_action" and isinstance(p, dict):
        as_of, basis = p.get("as_of"), "payload.as_of"
    elif name == "risk" and isinstance(p, dict):
        as_of, basis = p.get("computed_at"), "risk_snapshot.computed_at"
    elif name == "held" and isinstance(p, dict):
        as_of, basis = p.get("as_of"), f"held.{p.get('source') or 'unavailable'}"
    elif name == "desk_truth" and isinstance(p, dict):
        r = p.get(COVERAGE_LANE) or {}
        if isinstance(r, dict) and r.get("status") != "NO_RECEIPT":
            as_of, basis = r.get("ok_at") or r.get("finished_at"), "receipt.ok_at"
        else:
            basis = "no receipt"
    meta: dict[str, Any] = {"status": "OK", "as_of": as_of or (read_at.isoformat() if basis == "read_at" else None),
                            "as_of_basis": basis, "age_s": None, "stale": False}
    t = _parse(meta["as_of"])
    if t is not None:
        meta["age_s"] = max(0, int((now - t).total_seconds()))
        meta["stale"] = meta["age_s"] > STALE_AFTER_S.get(name, 600)
    if name == "needs_action" and isinstance(p, dict) and p.get("all_sources_answered") is False:
        meta["status"] = "PARTIAL"
        meta["unavailable"] = sorted(k for k, v in (p.get("sources") or {}).items()
                                     if isinstance(v, dict) and v.get("status") != "OK")
    if name == "held" and isinstance(p, dict):
        meta["stale"] = bool(p.get("stale"))  # the reader's own freshness contract (positions_sync / holdings age)
        meta["fallback_reason"] = p.get("fallback_reason")
    if name == "desk_truth" and basis == "no receipt":
        meta["status"] = "NO_RECEIPT"
    return meta


_EXECUTOR: Optional[cf.ThreadPoolExecutor] = None


def _executor() -> cf.ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix="home-do-now")
    return _EXECUTOR


def build(
    probes: dict[str, Callable[[], Any]],
    *,
    now: Optional[datetime] = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    executor: Optional[cf.Executor] = None,
    top_n: int = TOP_N,
) -> dict[str, Any]:
    """Run every probe concurrently with one shared deadline, apply the rules, merge, sort. Never drops a source."""
    now = now or datetime.now(timezone.utc)
    ex = executor or _executor()
    started = time.monotonic()
    futures = {name: ex.submit(fn) for name, fn in probes.items()}
    payloads: dict[str, Any] = {}
    sources: dict[str, dict] = {}
    for name, fut in futures.items():
        t0 = time.monotonic()
        try:
            payloads[name] = fut.result(timeout=max(0.0, timeout_s - (time.monotonic() - started)))
            sources[name] = source_meta(name, payloads[name], now, datetime.now(timezone.utc))
        except cf.TimeoutError:
            fut.cancel()
            sources[name] = {"status": "UNAVAILABLE", "error": f"timed out after {timeout_s:g} s"}
        except Exception as exc:  # noqa: BLE001 — the reason is shown
            sources[name] = {"status": "UNAVAILABLE", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        sources[name]["ms"] = int((time.monotonic() - t0) * 1000)

    raw: list[dict] = []
    numbers: dict[str, Any] = {"status": "UNAVAILABLE"}

    def run(name: str, fn: Callable[[], list[dict]]) -> None:
        if name not in payloads:
            return
        try:
            got = fn()
            sources[name]["items"] = len(got)
            raw.extend(got)
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:200] if isinstance(exc, SourceUnavailable) else f"{type(exc).__name__}: {str(exc)[:160]}"
            sources[name].update(status="UNAVAILABLE", error=err)
            payloads.pop(name, None)

    coverage: Optional[dict] = None
    if "desk_truth" in payloads:
        try:
            coverage = coverage_from_receipts(payloads["desk_truth"], now)
            sources["desk_truth"]["coverage"] = {k: coverage.get(k) for k in ("measured", "verdict", "reason")}
        except Exception as exc:  # noqa: BLE001
            sources["desk_truth"].update(status="UNAVAILABLE", error=str(exc)[:200])
    if "risk" in payloads:
        def _risk() -> list[dict]:
            nonlocal numbers
            got, numbers = rule_risk(payloads["risk"], coverage, now, held=payloads["held"] if "held" in payloads else ("unavailable" if "held" in sources else None))
            numbers = {**numbers, "status": "OK", "stale": sources["risk"].get("stale", False)}
            return got
        run("risk", _risk)
    run("needs_action", lambda: rule_needs_action(payloads["needs_action"], now))
    # proposals before inbox: on a merge the first title of equal severity wins, and the count belongs to proposals.
    run("proposals", lambda: rule_proposals(payloads["proposals"], now))
    run("deploy", lambda: rule_deploy(payloads["deploy"], now))
    run("inbox", lambda: rule_inbox(payloads["inbox"], now))

    for name, s in sources.items():
        if s.get("status") == "UNAVAILABLE":
            raw.append(item(f"source:{name}", "fix", "P2", f"Do-now source {name} unavailable",
                            f"Anything this source would report is unknown: {s.get('error')}",
                            "Open Health", R_HEALTH, name, since=now.isoformat(), evidence={"error": s.get("error")}))

    merged = sort_items(merge(raw))
    counts = {"all": len(merged), **{c: sum(1 for i in merged if i["category"] == c) for c in CATEGORIES}}
    by_sev = {s: sum(1 for i in merged if i["severity"] == s) for s in SEVERITIES}
    # NO_RECEIPT answered (the lane has not run; coverage is labelled not measured). PARTIAL did not.
    answered = all(s.get("status") in ("OK", "NO_RECEIPT") for s in sources.values())
    inbox_p = _unwrap(payloads.get("inbox")) if isinstance(payloads.get("inbox"), dict) else {}
    na_p = _unwrap(payloads.get("needs_action")) if isinstance(payloads.get("needs_action"), dict) else {}
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.isoformat(),
        "status": "OK" if answered else "PARTIAL",
        "all_sources_answered": answered,
        "any_source_stale": any(s.get("stale") for s in sources.values()),
        "sort": "money at risk (largest first), then severity P0..P3, then protect > decide > fix",
        "top_n": top_n,
        "counts": counts,
        "severity_counts": by_sev,
        "items": merged,
        "rolled_up": {
            "raw_items": len(raw),
            "after_dedupe": len(merged),
            "inbox_total": inbox_p.get("total_count") if isinstance(inbox_p, dict) else None,
            "needs_action_total": na_p.get("total") if isinstance(na_p, dict) else None,
        },
        "numbers": numbers,
        "sources": sources,
        "timeout_s": timeout_s,
    }


# ── probes that live here (read-only) ─────────────────────────────────────────────────────────────────────────


def probe_pending_proposals(db_query: Callable[..., Any]) -> dict[str, Any]:
    """COUNT of PENDING paper proposals + oldest + five newest symbols. ``db_query`` returns None on failure, which
    is UNAVAILABLE — never zero. Read-only SELECTs."""
    row = db_query(
        "SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM paper_trade_proposals WHERE status = 'PENDING'",
        None, fetch="one")
    if not isinstance(row, dict) or row.get("n") is None:
        raise SourceUnavailable("paper_trade_proposals count unreadable")
    syms = db_query(
        "SELECT symbol FROM paper_trade_proposals WHERE status = 'PENDING' ORDER BY created_at DESC LIMIT 5",
        None, fetch="all")
    oldest = row.get("oldest")
    return {"pending": int(row["n"]), "oldest_at": oldest.isoformat() if hasattr(oldest, "isoformat") else oldest,
            "symbols": [r.get("symbol") for r in (syms or []) if isinstance(r, dict)]}
