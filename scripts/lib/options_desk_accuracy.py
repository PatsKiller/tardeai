"""Options Desk served-field accuracy (2026-10-22). Pure functions; advisory only (MBI_BEHAVIOR = 0).

The 2026-10-22 audit found the desk telling the operator things that were not true at the
moment of reading: every card said PRE_MARKET because the run started at 09:29; quote ages
were invisible; "Next" said "Review" on an idea whose CIO review had stopped after three policy
refusals; a 165%-wide quote kept its full edge score; CSP yield was computed on the mid; the
operator's earnings estimate was silently replaced by the provider date; and "pending
evaluation" counted 5,642 inventory symbols that no worker would ever scan.

Everything here is computed from data the caller already holds (the proposal snapshot, the
thesis-store timeline on the card, the standing intents, the crontab / lane registry text and
the existing read-only arm status). Nothing here reads a broker, writes a store, changes a flag
or touches an order path. Field contract: docs/ops/OPTIONS_DESK_FIELDS.md.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 -- tzdata missing: fixed EDT offset, coarse like canonical_observation
    ET = timezone(timedelta(hours=-4))  # type: ignore[assignment]

SCHEMA = "OptionsDeskAccuracy@v1"
DEFAULT_MAX_REVIEW_FAILURES = 3
DEFAULT_QUOTE_MAX_AGE_S = 120
PROPOSALS_PRODUCER = {"lane": "run-options-monitor", "match": "run_options_monitor.sh"}
LIFECYCLE_PRODUCER = {"lane": "options-lifecycle-run", "match": "options_lifecycle_run.py",
                      "cadence_s": 20 * 60}
HEDGE_STRATEGIES = frozenset({"protective_put", "long_put", "collar"})
ACCUMULATE_STRATEGIES = frozenset({"cash_secured_put", "long_call"})
ACCUMULATE_GOALS = frozenset({"accumulate", "income", "add", "build"})
HEDGE_GOALS = frozenset({"hedge", "protect", "reduce", "exit", "trim", "insure"})
EARNINGS_CONFLICT_DAYS = 3
NOT_SCANNED = "NOT_SCANNED_EXPANDED_SCAN_DISABLED"

STAGE_LABELS = {
    "CREATED": "Idea created; thesis work not started",
    "RESEARCH_QUEUED": "Research requested; waiting for answers",
    "RESEARCH_COMPLETE": "Research answered; waiting for CIO review",
    "CIO_REVIEW_QUEUED": "Waiting for CIO review",
    "CIO_REVIEW_FAILED": "CIO review failed; the desk will retry",
    "REVIEW_FAILURE_CAP": "CIO review stopped after repeated failures",
    "DECISION_ISSUED": "CIO decision issued",
    "CIO_FOLLOWUP_RESEARCH": "CIO asked for follow-up research",
    "FOLLOWUP_COMPLETE": "Follow-up research delivered; CIO re-review due",
    "EXTERNAL_RESEARCH": "Escalated to external research",
    "REOPENED": "Reopened by the operator",
    "ARCHIVED_ABANDONED": "Archived: thesis not completed in time",
    "UNKNOWN": "No lifecycle record on this card",
}


# ── time and session ─────────────────────────────────────────────────────────

def parse_ts(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def age_s(ts: Any, now: datetime) -> Optional[float]:
    dt = parse_ts(ts)
    if dt is None:
        return None
    return round((now - dt).total_seconds(), 1)


def session_at(ts: Any) -> Optional[str]:
    """US-equity session label for an instant, in America/New_York (holidays not modelled).

    Same boundaries as lib.canonical_observation.market_session, DST-correct."""
    dt = parse_ts(ts)
    if dt is None:
        return None
    local = dt.astimezone(ET)
    if local.weekday() >= 5:
        return "WEEKEND"
    m = local.hour * 60 + local.minute
    if m < 4 * 60:
        return "CLOSED"
    if m < 9 * 60 + 30:
        return "PRE_MARKET"
    if m < 16 * 60:
        return "REGULAR"
    if m < 20 * 60:
        return "AFTER_HOURS"
    return "CLOSED"


def quote_time_of(p: dict) -> Optional[str]:
    """The card's option quote time: the OLDEST leg on a spread, else quote_time / quotes_as_of."""
    legs = [leg.get("quote_time") for leg in (p.get("legs_liquidity") or []) if isinstance(leg, dict)]
    legs += [leg.get("quote_time") for leg in ((p.get("spread_quote") or {}).get("legs") or [])
             if isinstance(leg, dict)]
    parsed = [parse_ts(x) for x in legs if x]
    parsed = [x for x in parsed if x]
    if parsed:
        return iso(min(parsed))
    for k in ("quote_time", "quotes_as_of"):
        if p.get(k):
            return str(p[k])
    return None


def quote_session_of(*contracts: Optional[dict], fallback: Optional[str] = None) -> Optional[str]:
    """Session of the oldest quote among ``contracts``; ``fallback`` when none carries a time."""
    times = [parse_ts((c or {}).get("quote_time")) for c in contracts]
    times = [t for t in times if t]
    return session_at(min(times)) if times else fallback


def _human_age(s: Optional[float]) -> str:
    if s is None:
        return "unknown age"
    s = abs(s)
    if s < 90:
        return f"{int(s)}s"
    if s < 5400:
        return f"{int(s // 60)} min"
    if s < 172800:
        return f"{s / 3600:.1f} h"
    return f"{s / 86400:.1f} days"


# ── item 2: per-card quote clock ─────────────────────────────────────────────

def stamp_quote_clock(p: dict, *, now: datetime, quote_max_age_s: float = DEFAULT_QUOTE_MAX_AGE_S) -> dict:
    qt = quote_time_of(p)
    q_age = age_s(qt, now)
    ps = p.get("price_source") or {}
    u_time = ps.get("quote_time") or ps.get("as_of")
    p["quote_age_s"] = q_age
    p["quote_session"] = session_at(qt)
    p["underlying_price_source"] = ps.get("source") or ("captured" if p.get("underlying_price") else None)
    p["underlying_price_time"] = u_time
    p["underlying_price_time_basis"] = ("provider_quote_time" if ps.get("quote_time")
                                        else ("fetch_time" if ps.get("as_of") else None))
    p["underlying_price_age_s"] = age_s(u_time, now)
    p["chain_age_s"] = age_s(p.get("chain_fetched_at"), now)
    p["quote_stale"] = bool(q_age is None or q_age > float(quote_max_age_s))
    return p


# ── snapshot / producer schedule ─────────────────────────────────────────────

_PAUSED_RE = re.compile(r"^\s*#\s*PAUSED\s+(\d{4}-\d{2}-\d{2})\s*(.*)$")
_CRON5 = re.compile(r"^\s*((?:\S+\s+){4}\S+)\s+")


def _active_lines(text: str) -> list[str]:
    return [ln for ln in (text or "").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def paused_from_crontab(text: Optional[str], match: str) -> Optional[dict]:
    """``# PAUSED <date> <note> <schedule> <command>`` for ``match`` with no active line → pause record."""
    if not text:
        return None
    if any(match in ln for ln in _active_lines(text)):
        return None
    for ln in text.splitlines():
        m = _PAUSED_RE.match(ln)
        if m and match in ln:
            note = m.group(2)
            cut = re.search(r"\s(?:\*|\d)[\d*/,\-]*\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s+[\d*/,\-]+\s", " " + note)
            reason = (" " + note)[:cut.start()].strip() if cut else note.split(" cd ")[0].strip()
            return {"since": m.group(1), "note": reason[:160] or None}
    return None


def producer_schedule(*, match: str, lane: str, crontab_text: Optional[str] = None,
                      crontab_source: str = "crontab", registry: Optional[dict] = None) -> dict:
    """Active cron expressions for the producer: the crontab when readable, else the lane registry."""
    if crontab_text:
        exprs = []
        for ln in _active_lines(crontab_text):
            if match in ln:
                m = _CRON5.match(ln)
                if m:
                    exprs.append(m.group(1))
        return {"lane": lane, "schedules": exprs, "source": crontab_source,
                "paused": paused_from_crontab(crontab_text, match)}
    rows = (registry or {}).get("lanes") if isinstance(registry, dict) else registry
    for r in rows or []:
        if isinstance(r, dict) and r.get("lane_id") == lane:
            sch = r.get("scheduler") or {}
            exprs = list(sch.get("schedules") or ([sch["expression"]] if sch.get("expression") else []))
            return {"lane": lane, "schedules": [e for e in exprs if e], "source": "lane_registry",
                    "paused": None, "registry_state": r.get("state")}
    return {"lane": lane, "schedules": [], "source": "none", "paused": None}


def next_scheduled(schedules: Iterable[str], now: datetime) -> Optional[str]:
    """Next fire after ``now`` of any cron expression (host wall clock = America/New_York)."""
    try:
        from lib.cron_schedule import next_run_any
    except ImportError:  # pragma: no cover - repo-root import path
        from scripts.lib.cron_schedule import next_run_any  # type: ignore
    exprs = [e for e in schedules or [] if e]
    if not exprs:
        return None
    local = now.astimezone(ET).replace(tzinfo=None)
    nxt = next_run_any(exprs, local)
    if nxt is None:
        return None
    try:
        return nxt.replace(tzinfo=ET).isoformat()
    except Exception:  # noqa: BLE001
        return None


def snapshot_block(generated_at: Any, *, now: datetime, schedule: dict) -> dict:
    return {
        "generated_at": generated_at,
        "age_s": age_s(generated_at, now),
        "session_at_generation": session_at(generated_at),
        "next_scheduled_refresh": (None if schedule.get("paused")
                                   else next_scheduled(schedule.get("schedules") or [], now)),
        "refresh_lane": schedule.get("lane"),
        "refresh_schedule": list(schedule.get("schedules") or []),
        "refresh_schedule_source": schedule.get("source"),
        "refresh_paused": schedule.get("paused"),
    }


# ── item 3: lifecycle stage ──────────────────────────────────────────────────

def lifecycle_stage(p: dict, *, max_failures: Optional[int] = None) -> dict:
    """{stage, label, review_failures, review_failure_cap, review_failure_reason} from the card."""
    life = p.get("lifecycle") or {}
    cap = int(life.get("review_failure_cap") or max_failures or DEFAULT_MAX_REVIEW_FAILURES)
    timeline = [t for t in life.get("timeline") or [] if isinstance(t, dict)]
    floor = ""
    for t in timeline:
        if t.get("stage") in ("DECISION_ISSUED", "REOPENED"):
            floor = max(floor, str(t.get("at") or ""))
    fails = [t for t in timeline if t.get("stage") == "CIO_REVIEW_FAILED" and str(t.get("at") or "") > floor]
    n = int(life["review_failures"]) if life.get("review_failures") is not None else len(fails)
    reason = next((str(t.get("reason") or t.get("status")) for t in reversed(fails)
                   if t.get("reason") or t.get("status")), None)
    stage = str(life.get("stage") or "").upper() or "UNKNOWN"
    if p.get("thesis_abandoned"):
        stage = "ARCHIVED_ABANDONED"
    elif stage == "CIO_REVIEW_FAILED" and n >= cap:
        stage = "REVIEW_FAILURE_CAP"
    return {"stage": stage, "label": STAGE_LABELS.get(stage, stage.replace("_", " ").capitalize()),
            "review_failures": n, "review_failure_cap": cap, "review_failure_reason": reason}


def stamp_lifecycle_stage(p: dict, *, max_failures: Optional[int] = None) -> dict:
    ls = lifecycle_stage(p, max_failures=max_failures)
    p["lifecycle_stage"] = ls["stage"]
    p["lifecycle_stage_label"] = ls["label"]
    p["review_failures"] = ls["review_failures"]
    p["review_failure_reason"] = ls["review_failure_reason"]
    return ls


def review_cap_text(ls: dict) -> str:
    why = ls.get("review_failure_reason")
    kind = "policy refusal" if why and "POLICY" in why.upper() else "last failure"
    detail = f" ({kind} {why})" if why else ""
    return f"CIO review stopped after {ls.get('review_failures')} failures{detail} · operator reopen needed"


# ── item 4: liquidity-aware edge ─────────────────────────────────────────────

def edge_liquidity_penalty(spread_pct: Optional[float], oi: Optional[float], volume: Optional[float],
                           *, min_oi: float = 50) -> float:
    pen = 0.0
    if spread_pct is not None:
        pen += min(15.0, 0.75 * max(0.0, float(spread_pct)))
    if oi is not None and float(oi) < 2 * float(min_oi):
        pen += 3.0
    if volume is not None and float(volume) <= 0:
        pen += 2.0
    return round(pen, 1)


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def apply_edge_liquidity(p: dict, cfg: Optional[dict] = None) -> dict:
    """Idempotent: the raw heuristic is kept once in edge_score_raw; edge_score is recomputed."""
    cfg = cfg or {}
    raw = p.get("edge_score_raw")
    if raw is None:
        raw = p.get("edge_score")
        p["edge_score_raw"] = raw
    liq = (p.get("enterprise") or {}).get("liquidity") or {}
    spread = _num(liq.get("bid_ask_spread_pct"))
    if spread is None:
        spread = _num(p.get("bid_ask_spread_pct"))
    oi = _num(liq.get("oi") if liq.get("oi") is not None else p.get("oi"))
    vol = _num(liq.get("volume") if liq.get("volume") is not None else p.get("volume"))
    pen = edge_liquidity_penalty(spread, oi, vol, min_oi=float(cfg.get("min_open_interest") or 50))
    p["edge_liquidity_penalty"] = pen
    if liq.get("pass") is False:
        issues = [str(i) for i in (liq.get("issues") or [])] or ["quote/liquidity failed"]
        p["edge_score"] = None
        p["edge_status"] = "WITHHELD_LIQUIDITY"
        p["edge_withheld_reason"] = "liquidity gate failed: " + "; ".join(issues[:3])
        return p
    rawf = _num(raw)
    p["edge_score"] = None if rawf is None else round(max(0.0, rawf - pen), 1)
    p["edge_status"] = "SCORED" if rawf is not None else "UNSCORED"
    p["edge_withheld_reason"] = None
    if str(p.get("strategy") or "") == "protective_put":
        p["edge_inputs"] = {"conviction": 0.55,
                            "conviction_basis": "fixed placeholder for hedges; not a per-symbol signal"}
    return p


# ── item 5: cash-secured put metrics ─────────────────────────────────────────

CSP_YIELD_BASIS = ("premium at the bid over the cash set aside (strike x 100); simple annualization "
                   "x 365/DTE assumes the same trade repeats all year at the same price; not repeatable, "
                   "not expected return")


def csp_bid_metrics(bid: Any, strike: Any, dte: Any) -> dict:
    b, k = _num(bid), _num(strike)
    d = max(int(_num(dte) or 1), 1)
    if b is None or k is None or k <= 0:
        return {"premium_over_collateral_pct": None, "simple_annualized_yield_pct": None}
    poc = b / k * 100.0
    return {"premium_over_collateral_pct": round(poc, 3),
            "simple_annualized_yield_pct": round(poc * 365.0 / d, 1)}


def apply_csp_metrics(p: dict) -> dict:
    if str(p.get("strategy") or "") != "cash_secured_put":
        return p
    bid = _num(p.get("bid"))
    if bid is None and p.get("premium_basis") == "bid":
        bid = _num(p.get("premium"))
    p.update(csp_bid_metrics(bid, p.get("strike"), p.get("dte")))
    p["yield_basis"] = CSP_YIELD_BASIS
    p["risk_reward"] = None
    p["not_applicable_metrics"] = ["risk_reward", "max_loss_to_zero"]
    return p


# ── item 6: earnings dates ───────────────────────────────────────────────────

def earnings_dates(provider_date: Any, provider_source: Optional[str], operator_estimate: Any) -> dict:
    pd_ = str(provider_date)[:10] if provider_date else None
    oe_ = str(operator_estimate)[:10] if operator_estimate else None
    days = None
    if pd_ and oe_:
        try:
            days = abs((date.fromisoformat(pd_) - date.fromisoformat(oe_)).days)
        except ValueError:
            days = None
    conflict = bool(days is not None and days > EARNINGS_CONFLICT_DAYS)
    eff = min(d for d in (pd_, oe_) if d) if (pd_ or oe_) else None
    return {"provider_date": pd_, "provider_source": provider_source if pd_ else None,
            "operator_estimate": oe_, "operator_source": "operator standing intent" if oe_ else None,
            "conflict": conflict, "conflict_days": days, "effective_date": eff,
            "effective_basis": "earlier of the two dates" if (pd_ and oe_) else ("provider" if pd_ else
                                                                                   ("operator estimate" if oe_ else None))}


# ── item 7: execution state ──────────────────────────────────────────────────

def execution_state(armed: Optional[bool], proposals: list[dict]) -> dict:
    total = len(proposals or [])
    eligible = sum(1 for p in proposals or [] if (p.get("enterprise") or {}).get("live_eligible") is True
                   and p.get("approvable") is True)
    tail = f"Nothing trades automatically. {eligible} of {total} ideas eligible now."
    if armed is True:
        state = "MANUAL_ONLY"
        text = ("Manual only: you can send an approved option order yourself with per-order 2FA. " + tail)
    elif armed is False:
        state = "OFF"
        text = ("Off: live option orders are disarmed, so no option order can be sent from the desk. "
                "Ideas are advisory. " + tail)
    else:
        state = "UNKNOWN"
        text = ("Unknown: the execution status could not be read; treat live option orders as off. " + tail)
    return {"state": state, "armed": armed, "automatic_trading": False, "per_order_2fa_required": True,
            "eligible_now": eligible, "total": total, "text": text,
            "basis": "read-only: options_pilot_arm.status().armed_for_execution and card live_eligible; "
                     "the options desk has no automatic submit path"}


# ── item 8: intent vs desk conflicts ─────────────────────────────────────────

_GOAL_WORDS = {"accumulate": "accumulate shares", "income": "earn income", "add": "add shares",
               "build": "build the position", "hedge": "hedge", "protect": "protect the position",
               "reduce": "reduce the position", "exit": "exit", "trim": "trim", "insure": "insure the position"}


def _goal_words(goals: Iterable[str]) -> str:
    return " and ".join(_GOAL_WORDS.get(g, g) for g in sorted(goals))


def intent_conflicts(proposals: list[dict], intents: list[dict]) -> list[dict]:
    by_sym: dict[str, dict] = {}
    for it in intents or []:
        if str(it.get("status") or "active").lower() != "active":
            continue
        sym = str(it.get("symbol") or "").upper()
        if sym:
            by_sym[sym] = it
    out = []
    for p in proposals or []:
        sym = str(p.get("symbol") or "").upper()
        it = by_sym.get(sym)
        if not it:
            continue
        goals = {str(g).lower() for g in it.get("goals") or []}
        plays = {str(k).lower() for k in (it.get("plays") or {})}
        strat = str(p.get("strategy") or "")
        kind = None
        if strat in HEDGE_STRATEGIES and (goals & ACCUMULATE_GOALS or plays & {"cash_secured_put", "leap_call"}):
            kind = "HEDGE_VS_ACCUMULATE"
            text = (f"{sym}: the desk proposes a {strat.replace('_', ' ')} (downside insurance) while your "
                    f"standing plan is to {_goal_words(goals & ACCUMULATE_GOALS) or 'accumulate shares'}. "
                    "Decide which one holds before acting.")
        elif strat in ACCUMULATE_STRATEGIES and goals & HEDGE_GOALS:
            kind = "ACCUMULATE_VS_HEDGE"
            text = (f"{sym}: the desk proposes a {strat.replace('_', ' ')} (adds exposure) while your standing "
                    f"plan is to {_goal_words(goals & HEDGE_GOALS)}. Decide which one holds before acting.")
        if kind:
            out.append({"proposal_id": p.get("id"), "symbol": sym, "account": p.get("account"),
                        "strategy": strat, "directive_id": it.get("directive_id"),
                        "intent_goals": sorted(goals), "kind": kind, "text": text})
    return out


# ── item 9: per-account grouping ─────────────────────────────────────────────

def group_key(p: dict) -> str:
    sym = str(p.get("symbol") or "").upper()
    strat = str(p.get("strategy") or "")
    contract = p.get("contract_guid") or "|".join(
        str(x) for x in (p.get("option_type"), p.get("strike"), str(p.get("expiration") or "")[:10],
                         p.get("short_strike"), p.get("long_strike")) if x not in (None, ""))
    return f"{sym}|{strat}|{contract}"


def proposal_groups(proposals: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for p in proposals or []:
        k = group_key(p)
        g = groups.setdefault(k, {"group_key": k, "symbol": str(p.get("symbol") or "").upper(),
                                  "strategy": p.get("strategy"),
                                  "contract": {"option_type": p.get("option_type"), "strike": p.get("strike"),
                                               "expiration": p.get("expiration"),
                                               "contract_guid": p.get("contract_guid")},
                                  "legs": []})
        g["legs"].append({"proposal_id": p.get("id"), "account": p.get("account"),
                          "contracts": p.get("contracts"), "shares_held": p.get("shares_held"),
                          "premium_total": p.get("premium_total")})
    for p in proposals or []:
        g = groups[group_key(p)]
        p["group_key"] = g["group_key"]
        p["group_size"] = len({leg.get("account") for leg in g["legs"]})
    out = []
    for g in groups.values():
        g["account_count"] = len({leg.get("account") for leg in g["legs"]})
        if g["account_count"] >= 2:
            out.append(g)
    return out


# ── item 10: honest coverage ─────────────────────────────────────────────────

def honest_coverage(coverage: dict, *, scan_enabled: bool) -> dict:
    """Split PENDING into real pending work (held symbols the legacy pass evaluates) and
    NOT_SCANNED_EXPANDED_SCAN_DISABLED. Idempotent; status_counts_raw keeps the producer's counts."""
    cov = dict(coverage or {})
    raw = dict(cov.get("status_counts_raw") or cov.get("status_counts") or {})
    cov["status_counts_raw"] = raw
    if scan_enabled:
        cov["pending_evaluation_count"] = int(raw.get("PENDING", 0))
        cov["not_scanned"] = None
        cov["status_counts"] = raw
        return cov
    rows = cov.get("rows")
    pending_rows = [r for r in rows or [] if r.get("status") == "PENDING"]
    if rows is not None:
        held = sum(1 for r in pending_rows if r.get("accounts") or "holdings" in (r.get("source_lanes") or []))
    else:  # rows stripped: a held count is unknowable here, so claim no pending work
        held = int(cov.get("pending_evaluation_count") or 0)
    not_scanned = int(raw.get("PENDING", 0)) - held
    counts = {k: v for k, v in raw.items() if k != "PENDING"}
    if held:
        counts["PENDING"] = held
    if not_scanned > 0:
        counts[NOT_SCANNED] = not_scanned
    cov["status_counts"] = counts
    cov["pending_evaluation_count"] = held
    cov["not_scanned"] = ({"count": not_scanned, "reason": "not scanned (expanded scan disabled)"}
                          if not_scanned > 0 else None)
    if rows is not None:
        for r in pending_rows:
            if not (r.get("accounts") or "holdings" in (r.get("source_lanes") or [])):
                r["status"] = NOT_SCANNED
    return cov


# ── item 15: averages that are not zero by default ───────────────────────────

def honest_overview(ov: dict, proposals: list[dict]) -> dict:
    ov = dict(ov or {})
    pops = [_num(p.get("pop_pct")) for p in proposals or []]
    pops = [x for x in pops if x is not None]
    edges = [_num(p.get("edge_score")) for p in proposals or []]
    edges = [x for x in edges if x is not None]
    ov["avg_pop"] = round(sum(pops) / len(pops), 1) if pops else None
    ov["avg_pop_n"] = len(pops)
    ov["total_edge_avg"] = round(sum(edges) / len(edges), 1) if edges else None
    ov["total_edge_n"] = len(edges)
    return ov


def avg_or_none(values: Iterable[Any]) -> Optional[float]:
    xs = [x for x in (_num(v) for v in values) if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


# ── serve-time context (cached reads of the crontab and lane registry) ──────

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL_S = 60.0


def crontab_cached(*, now_mono: Optional[float] = None) -> tuple[Optional[str], str]:
    """(text, source) of the user crontab via lib.crontab_snapshot; (None, 'none') when unreadable."""
    import time
    t = time.monotonic() if now_mono is None else now_mono
    hit = _CACHE.get("crontab")
    if hit and t - hit[0] < _CACHE_TTL_S:
        return hit[1]
    try:
        try:
            from lib.crontab_snapshot import read_crontab
        except ImportError:
            from scripts.lib.crontab_snapshot import read_crontab  # type: ignore
        cr = read_crontab()
        val = ((cr.text, "crontab_snapshot" if cr.source == "snapshot" else "crontab") if cr.ok
               else (None, "none"))
    except Exception:  # noqa: BLE001
        val = (None, "none")
    _CACHE["crontab"] = (t, val)
    return val


def lane_registry_cached(root: Any) -> Optional[dict]:
    import json
    import time
    from pathlib import Path
    t = time.monotonic()
    hit = _CACHE.get("registry")
    if hit and t - hit[0] < 600:
        return hit[1]
    try:
        reg = json.loads((Path(root) / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        reg = None
    _CACHE["registry"] = (t, reg)
    return reg


def proposals_schedule(root: Any) -> dict:
    text, source = crontab_cached()
    return producer_schedule(match=PROPOSALS_PRODUCER["match"], lane=PROPOSALS_PRODUCER["lane"],
                             crontab_text=text, crontab_source=source,
                             registry=None if text else lane_registry_cached(root))


# ── one serve-time pass over the proposals payload ───────────────────────────

def restamp_session_if_stale(row: dict) -> bool:
    """Re-price a cached card whose economics name a session other than its quote's.

    Cards written before 2026-10-22 carry the run-start session (PRE_MARKET on a 16:00 close
    quote). stamp_payoff is idempotent (it keeps premium_midpoint), so re-running it with the
    quote's own session only corrects the labels and the withheld/modelled status."""
    if row.get("workflow_version") or row.get("data_source") != "schwab_chain":
        return False
    qs = session_at(quote_time_of(row))
    recorded = (row.get("economics") or {}).get("market_session")
    if not qs or recorded == qs:
        return False
    try:
        try:
            from lib.options_economics import stamp_payoff
        except ImportError:
            from scripts.lib.options_economics import stamp_payoff  # type: ignore
        liq = (row.get("enterprise") or {}).get("liquidity") or {}
        stamp_payoff(row, session=qs,
                     quote_issues=list(liq.get("issues") or []) if liq.get("pass") is False else None)
        return True
    except Exception:  # noqa: BLE001
        return False


def stamp_card(row: dict, *, now: datetime, cfg: Optional[dict] = None) -> dict:
    cfg = cfg or {}
    restamp_session_if_stale(row)
    stamp_quote_clock(row, now=now, quote_max_age_s=float(cfg.get("hard_quote_max_age_seconds") or
                                                          DEFAULT_QUOTE_MAX_AGE_S))
    stamp_lifecycle_stage(row)
    apply_csp_metrics(row)
    apply_edge_liquidity(row, cfg)
    return row


def stamp_card_earnings(rows: list[dict], intents: list[dict]) -> None:
    est = {str(i.get("symbol") or "").upper(): i for i in intents or []
           if str(i.get("status") or "active").lower() == "active"}
    for p in rows or []:
        it = est.get(str(p.get("symbol") or "").upper())
        if not it:
            continue
        e = (p.get("enterprise") or {}).get("earnings") or {}
        p["earnings_dates"] = earnings_dates(e.get("event_date"), "options desk earnings gate" if e.get("event_date")
                                             else None, it.get("earnings_estimate"))


def apply_served_accuracy(data: dict, proposals: list[dict], *, now: datetime, armed: Optional[bool],
                          intents: list[dict], scan_enabled: bool, schedule: dict) -> dict:
    """Top-level served fields. ``proposals`` is the full (unpaginated) card list."""
    data["market_session"] = session_at(now)
    data["market_session_as_of"] = now.isoformat()
    data["snapshot"] = snapshot_block(data.get("generated_at"), now=now, schedule=schedule)
    es = execution_state(armed, proposals)
    data["execution_state"] = es
    data["execution_state_text"] = es["text"]
    conflicts = intent_conflicts(proposals, intents)
    data["intent_conflicts"] = conflicts
    by_id = {c["proposal_id"]: c for c in conflicts}
    for p in proposals:
        p["intent_conflict"] = by_id.get(p.get("id"))
    stamp_card_earnings(proposals, intents)
    data["proposal_groups"] = proposal_groups(proposals)
    if isinstance(data.get("coverage"), dict):
        data["coverage"] = honest_coverage(data["coverage"], scan_enabled=scan_enabled)
    data["strategy_overview"] = honest_overview(data.get("strategy_overview") or {}, proposals)
    data["accuracy_schema"] = SCHEMA
    return data


def holding_flags(intent: dict, match: Optional[dict], holdings: Optional[list[dict]]) -> dict:
    sym = str(intent.get("symbol") or "").upper()
    if match and isinstance(match.get("shares_by_account"), dict):
        total = sum(float(v or 0) for v in match["shares_by_account"].values())
        src = "match.shares_by_account"
    elif holdings is not None:
        total = sum(float(h.get("shares") or h.get("quantity") or 0) for h in holdings
                    if str(h.get("symbol") or "").upper() == sym and not h.get("is_cash"))
        src = "holdings.json"
    else:
        return {"held": None, "shares_held_total": None, "watch_only": None, "held_source": "unknown"}
    held = total > 0
    return {"held": held, "shares_held_total": round(total, 4), "watch_only": not held, "held_source": src}


# ── item 11: lifecycle payload freshness ─────────────────────────────────────

def lifecycle_freshness(payload: dict, *, now: datetime, crontab_text: Optional[str] = None,
                        crontab_source: str = "crontab", registry: Optional[dict] = None) -> dict:
    gen = payload.get("generated_at")
    a = age_s(gen, now)
    sch = producer_schedule(match=LIFECYCLE_PRODUCER["match"], lane=LIFECYCLE_PRODUCER["lane"],
                            crontab_text=crontab_text, crontab_source=crontab_source, registry=registry)
    paused = sch.get("paused")
    cadence = LIFECYCLE_PRODUCER["cadence_s"]
    if gen is None or a is None:
        state, text = "UNKNOWN", "no lifecycle payload timestamp"
    elif paused:
        state = "PAUSED"
        text = (f"PAUSED since {paused['since']}" + (f" ({paused['note']})" if paused.get("note") else "")
                + f"; last payload {_human_age(a)} old")
    elif a > 2 * cadence and session_at(now) == "REGULAR":
        state, text = "STALE", f"last payload {_human_age(a)} old; producer runs every 20 min in market hours"
    else:
        state, text = "FRESH", f"last payload {_human_age(a)} old"
    payload["age_s"] = a
    payload["freshness"] = {"state": state, "text": text, "producer_lane": LIFECYCLE_PRODUCER["lane"],
                            "paused_since": (paused or {}).get("since"), "paused_note": (paused or {}).get("note"),
                            "schedule_source": sch.get("source"),
                            "next_scheduled_run": None if paused else next_scheduled(sch.get("schedules") or [], now)}
    health = []
    for h in payload.get("health") or []:
        if isinstance(h, dict) and h.get("check") == "monitor_freshness":
            h = dict(h)
            h.setdefault("detail_at_write", h.get("detail"))
            h["ok"] = state == "FRESH"
            h["detail"] = text + " (computed when served)"
        health.append(h)
    if "health" in payload:
        payload["health"] = health
    return payload
