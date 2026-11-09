#!/usr/bin/env python3
"""CIO overnight brief generator (LQ-20261107-1257).

**ADVISORY ONLY.** This lane never sizes, orders, stops, weights or writes to a broker. Every
action string it emits is a suggestion for the CIO, who remains the single verdict owner per
account. It opens the database read-only, and the only writes it makes are its own JSON output
and the receipts/accounting rows of the sanctioned research path it calls.

What it assembles, for each held name with a move above 3% or news since the last close:

  * the move, price, shares and dollars held            — ticker snapshot + holdings store
  * the news since the close, with sources              — news_articles
  * related Form 4 / Form 144 filings                   — sec_form4 + sec_filing_documents
  * every working stop, the uncovered shares and the
    cushion (price - stop)/price against ATR(14)        — stop_last_known + market_ohlcv_bars
  * the latest recorded CIO decision for the symbol     — cio_decisions
  * a research answer (WHO / WHY / IMPACT, cited)       — hermes_external_researcher, --no-store
  * an advisory action from the cushion rule            — deterministic, never the model's

plus the risk tier (market_regime_snapshots / risk_regime_run_log) and the next five sessions of
the macro and earnings calendar.

The LLM writes prose only (summary sentences, WHAT/WHY and IMPACT for each flagged name). Numbers
and actions are computed here, so a model outage degrades the wording, never the advice.

Output: ``<state root>/data/runtime/cio_overnight_brief/latest.json`` and a dated copy
``<YYYY-MM-DD>.json`` beside it. ``data/runtime`` is a symlink to the persistent state root on the
served release, so the path the queue names and this one are the same file.

Scheduling: an n8n lane (see the lane spec delivered with LQ-1257), two runs a day — one that
finishes by 05:50 ET and a 17:30 ET post-close run. Never crontab.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.account_display import account_label  # noqa: E402  (LQ-1391 one name per account)
from lib.cio_buys_gate import buys_block  # noqa: E402  (LQ-1311 synopsis buy gate)
from lib.cio_regime import reader as regime_reader  # noqa: E402  (LQ-1317 regime block)
from lib.cio_regime import build as build_regime  # noqa: E402

LANE_ID = "cio-overnight-brief"
SCHEMA = "CIOOvernightBrief@v1"
ET = ZoneInfo("America/New_York")

MOVE_THRESHOLD_PCT = 3.0
NEWS_LOOKBACK_HOURS = 96
FILING_LOOKBACK_DAYS = 7
WEEK_AHEAD_SESSIONS = 5
MAX_NEWS_PER_NAME = 8

#: Below this market value a held row is a fractional remnant, not a position: a stop on 0.13
#: shares of a $25 holding is not an actionable instruction, and it would bury the real names.
MIN_POSITION_MARKET_VALUE = 500.0

#: stop_last_known statuses that mean the order is resting at the broker right now. Everything
#: else (filled, canceled, expired, rejected, replaced, not_in_read) is a historical record and
#: counts toward NO coverage. ``replaced`` is deliberately excluded: its successor is a different
#: order_id, so counting it would double-count a single protective order.
WORKING_STOP_STATUSES = frozenset(
    {"pending_activation", "active", "working", "open", "placed", "accepted", "new", "queued"}
)

#: Research budget reserved for the brief. The questions are asked with trigger ``holdings`` so
#: they draw on the T0 tier (600 calls/day) rather than the T1 ``due_diligence_question`` tier
#: whose 200/day breaker is open (LQ-1104 fixes that). Held names are researched first and the
#: run stops at ``--max-research``; the day counter below is the reservation, so a busy day of
#: other T0 work cannot starve the brief.
RESEARCH_RESERVATION_PER_DAY = 60
RESEARCH_PER_RUN_DEFAULT = 8
RESEARCH_LANES_DEFAULT = "chatgpt,grok,deepseek"
RESEARCH_TIMEOUT_S = 300
RESEARCH_TRIGGER = "holdings"

#: The five answers `stop_advice[]` may carry (LQ-1257 AMENDMENT 1, 17:48 ET). They are advisory
#: labels, not orders: nothing in this process calls an order or stop-write path.
STOP_ADVICE_ANSWERS = ("RAISE", "ADD_STOP", "FIX_QTY", "HOLD", "NO_ACTION")
#: A stop moves on price and structure, never on a headline: the raise needs a day gain, a price
#: at least 5% above the stop, and a target that stays 3% under the close.
RAISE_MIN_DAY_GAIN_PCT = 3.0
RAISE_MIN_PRICE_OVER_STOP = 1.05
RAISE_MIN_DISTANCE_BELOW_CLOSE = 0.03
NO_ACTION_MAX_VALUE_USD = 100.0
#: A stop order covers whole shares. A quantity gap under one share is a fractional remainder,
#: not an uncovered quantity: calling it ADD_STOP (or FIX_QTY) would ask for an impossible order.
MIN_STOP_QTY_DELTA = 1.0

#: Synopsis posture by market-risk tier (LQ-1257 AMENDMENT 2, 18:00 ET). The tier is read from
#: runtime/market_risk/latest.json; the model never decides it. Unknown tier is not guessed into a
#: posture: it says the read is missing.
POSTURE_BY_TIER = {
    "RED": ("DEFENSIVE", "HOLD CASH"),
    "ORANGE": ("DEFENSIVE", "TRIM, DO NOT ADD"),
    "YELLOW": ("NEUTRAL", "SELECTIVE, SMALL SIZES"),
    "GREEN": ("OFFENSIVE", "DEPLOY SLOWLY"),
}
POSTURE_UNKNOWN = ("NEUTRAL", "AWAIT RISK READ")
#: Re-entry stages. The states are the canonical ones from lib/reentry_rules.derive_intel_state,
#: which the decision desk writes to each row's ``intel.state``: stage 1 is waiting, stage 2 is
#: prepare the review, stage 3 is review now. "Don't buy back yet" holds until any name is past 1.
REENTRY_STAGE = {
    "WAIT": 1,
    "OVERBOUGHT WAIT": 1,
    "MISSING PLAN": 1,
    "MISSING MARKET": 1,
    "STALE": 1,
    "WASH BLOCK": 1,
    "CURRENTLY HELD": 1,
    "NEAR ENTRY": 2,
    "OVERSOLD REVIEW": 2,
    "READY TO REVIEW": 3,
}
VERDICT_MAX_CHARS = 140
#: A source more than this many completed sessions behind ``as_of`` says so in its line.
STALE_AFTER_SESSIONS = 1


# ── small helpers ────────────────────────────────────────────────────────────────────────────


def _f(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _r(value: Optional[float], nd: int = 2) -> Optional[float]:
    return None if value is None else round(float(value), nd)

def _acct(account: Any) -> str:
    """The account's one human display name in prose (LQ-1391).

    Structured fields keep the canonical key (``schwab_taxable``) because links and joins need it;
    a sentence an operator reads must not. ``config/account_display_names.json`` owns the names
    (``schwab_taxable`` → "Schwab Individual"), so this prose and the account table agree.
    """
    return account_label(account)


def _latest(values: Iterable[Any]) -> Optional[str]:
    """The newest ISO timestamp among ``values`` (all are written by this repo in one offset)."""
    clean = [str(v) for v in values if v]
    return max(clean) if clean else None


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def runtime_dir(root: Optional[Path] = None) -> Path:
    return Path(root or state_root()) / "data" / "runtime" / "cio_overnight_brief"


def _parse_as_of(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt


def last_close_at(as_of: datetime, service: Any = None) -> tuple[date, datetime]:
    """The most recent exchange close at or before ``as_of`` (exchange tz)."""
    if service is None:
        from scripts.lib.cio_market_session import get_session_service

        service = get_session_service()
    et = as_of.astimezone(ET)
    day = et.date()
    for back in range(0, 12):
        cand = day - timedelta(days=back)
        if not service.is_trading_day(cand):
            continue
        _open, close_dt, _early = service.official_bounds(cand)
        if close_dt is not None and close_dt <= et:
            return cand, close_dt
    raise RuntimeError("no exchange close found in the last 12 days")


def next_sessions(as_of: datetime, n: int = WEEK_AHEAD_SESSIONS, service: Any = None) -> list[date]:
    if service is None:
        from scripts.lib.cio_market_session import get_session_service

        service = get_session_service()
    out: list[date] = []
    day = as_of.astimezone(ET).date()
    for step in range(0, 30):
        cand = day + timedelta(days=step)
        if not service.is_trading_day(cand):
            continue
        _open, close_dt, _early = service.official_bounds(cand)
        if close_dt is not None and close_dt > as_of.astimezone(ET) - timedelta(seconds=1):
            out.append(cand)
        if len(out) >= n:
            break
    return out


def previous_close_at(close_date: date, service: Any = None) -> datetime:
    """The close of the session *before* ``close_date`` — where the overnight window starts.

    The brief covers the last completed session and the time since it: a Monday 05:50 brief
    must see Friday's session (its news was published before Friday's close) and the weekend.
    Starting at the last close would drop the very session that produced the move.
    """
    if service is None:
        from scripts.lib.cio_market_session import get_session_service

        service = get_session_service()
    for back in range(1, 15):
        cand = close_date - timedelta(days=back)
        if not service.is_trading_day(cand):
            continue
        _open, close_dt, _early = service.official_bounds(cand)
        if close_dt is not None:
            return close_dt
    return datetime.combine(close_date, datetime.min.time(), tzinfo=ET)


# ── deterministic analysis ───────────────────────────────────────────────────────────────────


def aggregate_holdings(holdings: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse the holdings rows (one per account) into one entry per symbol."""
    out: dict[str, dict[str, Any]] = {}
    for row in holdings:
        if row.get("is_cash"):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        shares = _f(row.get("broker_shares"), _f(row.get("shares"), 0.0)) or 0.0
        if abs(shares) < 1e-9:
            continue
        mv = _f(row.get("market_value"), _f(row.get("broker_market_value"), 0.0)) or 0.0
        ent = out.setdefault(
            symbol,
            {"symbol": symbol, "shares": 0.0, "market_value": 0.0, "accounts": [], "per_account": {}},
        )
        ent["shares"] += shares
        ent["market_value"] += mv
        acct = str(row.get("account") or row.get("account_key") or "unknown")
        if acct not in ent["accounts"]:
            ent["accounts"].append(acct)
        ent["per_account"][acct] = ent["per_account"].get(acct, 0.0) + shares
    return out


def working_stops(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Resting stops per symbol. ``rows`` is the full stop_last_known picture for the symbols."""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        status = str(row.get("status") or "").strip().lower()
        if status not in WORKING_STOP_STATUSES:
            continue
        price = _f(row.get("stop_price"))
        qty = _f(row.get("qty"), 0.0) or 0.0
        if price is None or qty <= 0:
            continue
        symbol = str(row.get("symbol") or "").upper()
        out.setdefault(symbol, []).append(
            {
                "account": row.get("account"),
                "order_id": row.get("order_id"),
                "stop": _r(price),
                "qty": _r(qty, 4),
                "status": status,
                "captured_at": row.get("captured_at").isoformat()
                if isinstance(row.get("captured_at"), datetime)
                else row.get("captured_at"),
                "origin": row.get("origin"),
            }
        )
    for stops in out.values():
        stops.sort(key=lambda s: (-(s["stop"] or 0), s["account"] or ""))
    return out


def stop_coverage(
    held: Mapping[str, Any], stops: Sequence[Mapping[str, Any]], materiality_frac: float = 0.05
) -> dict[str, Any]:
    """Coverage per account: resting stop shares against shares actually held.

    A gap of more than 5% of the position (never less than one share) is uncovered exposure and
    is named as such. A smaller gap is a reconciliation: a 100-share stop against 101.29 shares
    held is a rounding artifact of fractional shares, not a position anyone can protect.
    """
    covered: dict[str, float] = {}
    for s in stops:
        # Only a resting order covers shares. Filtering here as well as in working_stops() keeps
        # the invariant true for every caller: a filled or replaced order is a historical record.
        if str(s.get("status") or "").strip().lower() not in WORKING_STOP_STATUSES:
            continue
        acct = str(s.get("account") or "")
        covered[acct] = covered.get(acct, 0.0) + float(s.get("qty") or 0)
    per_account = held.get("per_account") or {}
    uncovered: dict[str, float] = {}
    reconcile: dict[str, float] = {}
    for acct, shares in per_account.items():
        gap = max(0.0, float(shares) - covered.get(acct, 0.0))
        if gap <= 0:
            continue
        if gap > max(1.0, materiality_frac * float(shares)):
            uncovered[acct] = gap
        else:
            reconcile[acct] = gap
    # A stop can rest in an account that no longer holds the name (e.g. a fill moved it); that is
    # a reconciliation item, not coverage.
    orphaned = [a for a in covered if a not in per_account and covered[a] > 0]
    return {
        "covered_shares": _r(sum(covered.values()), 4),
        "uncovered_shares": _r(sum(uncovered.values()), 4),
        "uncovered_by_account": {a: _r(v, 4) for a, v in uncovered.items()},
        "reconcile_by_account": {a: _r(v, 4) for a, v in reconcile.items()},
        "stops_in_accounts_without_holding": orphaned,
        "fully_covered": not uncovered,
    }


def atr14(bars: Sequence[Mapping[str, Any]], window: int = 14) -> Optional[float]:
    """ATR(14) over daily bars, oldest first. True range uses the previous close."""
    clean = [
        (_f(b.get("high")), _f(b.get("low")), _f(b.get("close")))
        for b in bars
        if _f(b.get("high")) is not None and _f(b.get("low")) is not None and _f(b.get("close")) is not None
    ]
    if len(clean) < window + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(clean)):
        high, low, _close = clean[i]
        prev_close = clean[i - 1][2]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(trs[-window:]) / window


def tightest_stop(stops: Sequence[Mapping[str, Any]], price: Optional[float]) -> Optional[Mapping[str, Any]]:
    """The stop nearest the price from below (the one that would fire first in a fall).

    A resting stop above the market is a sell-stop that should have triggered; it is returned
    only when nothing below the price exists, because it is not protecting a fall.
    """
    if not stops:
        return None
    below = [s for s in stops if price is None or float(s.get("stop") or 0) <= float(price)]
    pool = below or list(stops)
    return max(pool, key=lambda s: float(s.get("stop") or 0))


def cushion(price: Optional[float], stops: Sequence[Mapping[str, Any]], atr: Optional[float]) -> dict[str, Any]:
    """Cushion between the last price and the tightest resting stop below it.

    Two spellings of one number, because two readers want opposite signs: ``cushion_pct`` is the
    queue's ``(price - stop)/price`` (positive = room to fall), ``stop_pct`` is the blueprint's
    ``(stop - price)/price`` (negative = the stop sits below the market).
    """
    stop = tightest_stop(stops, price)
    if price is None or stop is None or not price:
        return {
            "stop": None,
            "stop_pct": None,
            "cushion_pct": None,
            "atr14": _r(atr),
            "atr_pct": None,
            "multiple": None,
            "band": "unresolved",
        }
    p = float(price)
    s = float(stop.get("stop") or 0)
    room = p - s
    cushion_pct = room / p * 100.0
    atr_pct = (atr / p * 100.0) if atr else None
    multiple = (room / atr) if atr else None
    if atr and multiple is not None:
        band = "tight" if multiple < 1.0 else ("moderate" if multiple < 2.0 else "wide")
    else:
        band = "unknown"
    return {
        "stop": _r(s),
        "stop_pct": _r(-cushion_pct),
        "cushion_pct": _r(cushion_pct),
        "atr14": _r(atr),
        "atr_pct": _r(atr_pct),
        "multiple": _r(multiple, 2),
        "band": band,
        "account": stop.get("account"),
        "status": stop.get("status"),
    }


def advisory_action(
    price: Optional[float],
    cov: Mapping[str, Any],
    cush: Mapping[str, Any],
    atr: Optional[float],
) -> str:
    """The action, computed here and never by the model. Advisory only.

    A stop is never advised to move *down*: a raise is only offered when the computed level is
    above the stop already resting, because lowering a protective stop to fit a rule is how a
    risk control turns into a risk.
    """
    bits: list[str] = []
    uncovered = float(cov.get("uncovered_shares") or 0)
    if uncovered > 0.5:
        bits.append(
            f"cover the {uncovered:g} sh with no resting stop"
            + (f" (accounts: {', '.join(_acct(a) for a in sorted(cov.get('uncovered_by_account') or {}))})"
               if cov.get("uncovered_by_account") else "")
        )
    if cov.get("reconcile_by_account") or cov.get("stops_in_accounts_without_holding"):
        bits.append("reconcile the stop quantity against the holding (a fractional or orphaned gap, not exposure)")
    current = cush.get("stop")
    if cush.get("band") == "tight" and price:
        bits.append(
            f"the stop is only {cush.get('multiple')}x ATR below the last price, inside a normal "
            f"day's range — keep it where it is and, if the exposure is larger than you want, "
            f"consider a trim rather than moving the stop down"
        )
    elif cush.get("band") == "moderate":
        bits.append("hold the stop; the cushion is one to two ATRs, a normal week's range")
    elif cush.get("band") == "wide" and price and atr:
        target = price - 2.0 * atr
        if current is not None and target > float(current):
            bits.append(
                f"the stop is more than two ATRs away; a raise to about {target:.2f} "
                f"(2 ATR below the last price) would keep the position protected"
            )
        else:
            bits.append("hold; the stop is more than two ATRs away and is not the binding risk")
    if not bits:
        bits.append("hold; no resting stop and no computable cushion — reconcile the stop read before acting")
    return "; ".join(bits) + ". Advisory only — the CIO decides."


def classify_news(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        published = row.get("published_at")
        out.append(
            {
                "id": row.get("id"),
                "title": (row.get("title") or "").strip()[:300],
                "source": (row.get("source") or "").strip(),
                "url": (row.get("source_url") or "").strip(),
                "published_at": published.isoformat() if isinstance(published, datetime) else published,
                "summary": (row.get("summary") or "").strip()[:600],
            }
        )
    out.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
    return out


_PCT_OF_STAKE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*of\s+(?:his|her|their|the)\s+(?:stake|holding|shares|position)", re.I)
#: A sale on the record, in a headline: Form 144, a 10b5-1 plan, or "plans to sell N shares".
_INSIDER_NEWS_RE = re.compile(
    r"form\s*144|10b5-?1|insider\s+(?:sale|selling)|plans?\s+to\s+sell|(?:ceo|cfo|founder|director)\s+(?:sells|sold)",
    re.I,
)


def classify_event(
    sig: Mapping[str, Any],
    filings: Sequence[Mapping[str, Any]],
    research_text: str,
) -> dict[str, Any]:
    """What the overnight event is, whether it is neutral, and any premise to correct.

    Deterministic: it reads the filing rows and the words already in the store and the research
    answer. The model never decides the answer; this decides what the answer is *about*.
    """
    texts = [research_text or ""]
    texts += [str(n.get("title") or "") + " " + str(n.get("summary") or "") for n in (sig.get("news") or [])]
    blob = " ".join(texts).lower()
    has_144 = any(str(f.get("form") or "").upper().startswith("144") for f in filings)
    has_plan = "10b5-1" in blob or "10b5‑1" in blob or "10b5–1" in blob
    pct_match = _PCT_OF_STAKE.search(" ".join(texts))
    pct = float(pct_match.group(1)) if pct_match else None
    insider_rows = [f for f in filings if str(f.get("form") or "").upper().startswith("4") and (f.get("shares") or 0) > 0]
    # The store's filing rows for a held name are often issuer boilerplate; the sale itself is in
    # the news. Without this, ANET's Bechtolsheim headline would be summarized as a fair-value note.
    insider_news = [n for n in (sig.get("news") or []) if _INSIDER_NEWS_RE.search(str(n.get("title") or ""))]

    if has_144 or has_plan or insider_rows or insider_news:
        kind = "insider_plan_sale" if (has_plan or has_144) else "insider_sale"
        neutral = bool(has_plan or (pct is not None and pct < 1.0))
        if has_plan and pct is not None:
            correction = (
                f"a {pct:g}% sale under a pre-arranged 10b5-1 plan — under 1% of the holder's stake, "
                f"not a 10% exit"
            )
        elif has_plan:
            correction = "a pre-arranged 10b5-1 plan sale, not a discretionary exit"
        elif has_144:
            correction = "a Form 144 notice of intent to sell — intent, not an executed sale"
        else:
            correction = None
        headline = str((insider_news[0] if insider_news else {}).get("title") or "")[:160]
        summary = headline or ("insider selling on the record" + (f" ({pct:g}% of the holder's stake)" if pct is not None else ""))
    elif sig.get("news"):
        kind = "news"
        neutral = False
        correction = None
        summary = str((sig["news"][0] or {}).get("title") or "")[:160]
    else:
        kind = "move"
        neutral = False
        correction = None
        summary = f"a {sig.get('move_pct')}% move with no news in the store"
    return {"kind": kind, "neutral": neutral, "summary": summary, "premise_correction": correction}


def stop_advice_for_account(
    *,
    symbol: str,
    account: str,
    held_qty: float,
    price: Optional[float],
    move_pct: Optional[float],
    atr: Optional[float],
    stops: Sequence[Mapping[str, Any]],
    event: Mapping[str, Any],
    source_ids: Sequence[str],
    as_of: str,
) -> dict[str, Any]:
    """One advisory entry per account per holding (LQ-1257 AMENDMENT 1).

    Order of precedence: a position too small to act on, then a quantity mismatch in either
    direction, then — only on price and structure — a raise, else hold. The insider event can
    never move the answer: it is recorded, and a plan sale is marked neutral.
    """
    in_account = [
        s
        for s in stops
        if str(s.get("account") or "") == account and str(s.get("status") or "") in WORKING_STOP_STATUSES
    ]
    stop_qty = sum(float(s.get("qty") or 0) for s in in_account)
    stop_now = None
    if in_account and price:
        below = [s for s in in_account if float(s.get("stop") or 0) <= price]
        pool = below or in_account
        stop_now = max(float(s.get("stop") or 0) for s in pool)
    value = (held_qty * price) if price else None
    base = {
        "symbol": symbol,
        "account": account,
        # The row's one human name (LQ-1391). ``account`` stays the canonical key the UI joins on;
        # this is what the row prints, so no surface has to title-case a key itself.
        "account_label": _acct(account),
        "event_summary": event.get("summary"),
        "answer": "HOLD",
        "stop_now": _r(stop_now),
        "stop_qty": _r(stop_qty, 4),
        "held_qty": _r(held_qty, 4),
        "suggested_stop": None,
        "reason": "",
        "premise_correction": event.get("premise_correction"),
        "source_ids": list(source_ids),
        "as_of": as_of,
    }
    tol = MIN_STOP_QTY_DELTA

    if value is not None and value < NO_ACTION_MAX_VALUE_USD:
        base["answer"] = "NO_ACTION"
        base["reason"] = f"position is worth about ${value:,.2f}, under the $100 floor where a stop change is meaningful"
        return base

    if 0 < held_qty < 1:
        # A stop order covers whole shares; a fractional remnant cannot carry one.
        base["answer"] = "NO_ACTION"
        base["reason"] = f"{held_qty:g} sh is a fractional remnant — a stop order covers whole shares only"
        return base

    if stop_qty > held_qty + tol:
        base["answer"] = "FIX_QTY"
        base["reason"] = (
            f"the working stop covers {stop_qty:g} sh against {held_qty:g} sh held in {_acct(account)}; "
            f"reduce the stop quantity to the holding before anything else"
        )
        return base

    if stop_qty <= 0 or stop_qty < held_qty - tol:
        base["answer"] = "ADD_STOP"
        suggested = stop_now
        if suggested is None and price and atr:
            suggested = min(price - atr, price * (1 - RAISE_MIN_DISTANCE_BELOW_CLOSE))
        base["suggested_stop"] = _r(suggested)
        if stop_qty <= 0:
            base["reason"] = f"{held_qty:g} sh in {_acct(account)} have no working stop"
        else:
            base["reason"] = f"the working stop covers {stop_qty:g} of {held_qty:g} sh in {_acct(account)}"
        if suggested is not None:
            base["reason"] += f"; a stop near {suggested:.2f} would cover the difference"
        return base

    # Covered. A raise needs the price above the stop and a real day gain — never the headline.
    if stop_now and price and atr:
        day_gain = move_pct if move_pct is not None else 0.0
        target = min(price - atr, price * (1 - RAISE_MIN_DISTANCE_BELOW_CLOSE))
        if price >= stop_now * RAISE_MIN_PRICE_OVER_STOP and day_gain >= RAISE_MIN_DAY_GAIN_PCT and target > stop_now:
            base["answer"] = "RAISE"
            base["suggested_stop"] = _r(target)
            base["reason"] = (
                f"price {price:.2f} is {(price / stop_now - 1) * 100:.1f}% above the stop and the day is "
                f"{day_gain:+.2f}%; a stop near {target:.2f} (one ATR below the close, at least 3% under it) "
                f"keeps the gain without sitting in the noise"
            )
            if event.get("neutral"):
                base["reason"] += "; the insider event is neutral and did not drive this"
            return base

    base["answer"] = "HOLD"
    if event.get("neutral"):
        base["reason"] = (
            "the insider event is neutral (a pre-arranged plan or under 1% of the holder's stake); "
            "price and structure do not justify moving the stop"
        )
    elif stop_now:
        base["reason"] = "the position is covered and price and structure do not justify moving the stop"
    else:
        base["reason"] = "no resting stop and no computable level — reconcile the stop read"
    return base


def select_names(
    held: Mapping[str, Mapping[str, Any]],
    quotes: Mapping[str, Mapping[str, Any]],
    news_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    threshold: float = MOVE_THRESHOLD_PCT,
    min_market_value: float = MIN_POSITION_MARKET_VALUE,
) -> list[dict[str, Any]]:
    """Held names that moved more than ``threshold`` or have news since the window opened.

    A position below ``min_market_value`` is a fractional remnant, not a holding: a stop on 0.13
    shares of a $25 position is not an actionable instruction, and flagging it buries the real
    names. Those are counted, not silently dropped (``excluded_reasons``).
    """
    selected: list[dict[str, Any]] = []
    for symbol, pos in held.items():
        quote = quotes.get(symbol) or {}
        price = _f(quote.get("price"))
        shares = _f(pos.get("shares"), 0.0) or 0.0
        mv = _f(pos.get("market_value"), 0.0) or 0.0
        # A store row can carry shares without a value; price x shares is the honest fallback and
        # the floor check uses whichever is larger, so a large position never drops out on a stale
        # market_value field.
        implied = (shares * price) if price else 0.0
        value = max(mv, implied)
        if value < min_market_value:
            continue
        move = _f(quote.get("change_pct"))
        news = list(news_by_symbol.get(symbol) or [])
        reasons = []
        if move is not None and abs(move) >= threshold:
            reasons.append("move")
        if news:
            reasons.append("news")
        if not reasons:
            continue
        selected.append(
            {
                "symbol": symbol,
                "reasons": reasons,
                "move_pct": _r(move),
                "price": _r(price),
                "shares": _r(shares, 4),
                "market_value": _r(value),
                "accounts": list(pos.get("accounts") or []),
                "quote_source": quote.get("source"),
                "news": classify_news(news)[:MAX_NEWS_PER_NAME],
                "news_total": len(news),
            }
        )
    selected.sort(key=lambda r: (-(abs(r["move_pct"] or 0.0)), -float(r["market_value"] or 0.0)))
    return selected


def selection_exclusions(
    held: Mapping[str, Mapping[str, Any]], min_market_value: float = MIN_POSITION_MARKET_VALUE
) -> dict[str, int]:
    small = sum(1 for p in held.values() if (_f(p.get("market_value"), 0.0) or 0.0) < min_market_value)
    return {"below_position_floor": small} if small else {}


# ── synopsis: the CIO's bottom line (AMENDMENT 2, 18:00 ET) ─────────────────────────────────
#
# Everything here is deterministic and every figure names the store it came from. The model does
# not write the synopsis: a bottom line with an invented number would be worse than no bottom line.


def _one_line(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _clip(text: Any, limit: int) -> str:
    s = _one_line(text)
    if len(s) <= limit:
        return s
    cut = s[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + "…"


def _ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=ET)


def sessions_between(older: datetime, newer: datetime, service: Any = None) -> int:
    """Completed NYSE sessions strictly after ``older`` and before ``newer`` (holidays excluded)."""
    if service is None:
        from scripts.lib.cio_market_session import get_session_service

        service = get_session_service()
    a, b = older.astimezone(ET).date(), newer.astimezone(ET).date()
    n = 0
    day = a + timedelta(days=1)
    while day < b:
        if service.is_trading_day(day):
            n += 1
        day += timedelta(days=1)
    return n


def stale_note(when: Any, as_of: datetime, service: Any = None, label: str = "source") -> str:
    """``" (stale: ...)"`` when a source is more than one completed session old, else ``""``."""
    ts = _ts(when)
    if ts is None:
        return f" ({label} timestamp unavailable)"
    n = sessions_between(ts, as_of, service)
    if n > STALE_AFTER_SESSIONS:
        return f" (stale: {label} is {n} sessions old, last {ts.astimezone(ET):%Y-%m-%d %H:%M} ET)"
    return ""


def market_summary(risk_market: Optional[Mapping[str, Any]], as_of: datetime, service: Any = None) -> dict[str, Any]:
    """The market line: tier, score, and whether the selloff is sector-wide or market-wide."""
    if not risk_market:
        return {
            "line": "no market-risk read is available" + stale_note(None, as_of, service, "market_risk"),
            "tier": None,
            "score": None,
            "shock_class": None,
            "market_wide": None,
            "source_ids": [],
        }
    tier = str(risk_market.get("tier") or "").upper() or None
    score = _f(risk_market.get("score"))
    shock = risk_market.get("shock") or {}
    shock_class = str(shock.get("class") or "").upper() or None
    market_wide = None if shock_class is None else shock_class not in ("SECTOR",)
    if market_wide is False:
        kind = "sector selloff, not market-wide"
    elif market_wide is True:
        kind = "market-wide selloff"
    else:
        kind = "shock class not stated"
    head = _one_line(shock.get("headline"))
    bits = [f"Risk tier {tier or 'UNKNOWN'}"]
    if score is not None:
        bits[0] += f" (score {score:.1f})"
    bits.append(kind)
    line = ", ".join(bits) + (f": {_clip(head, 180)}" if head else "")
    return {
        "line": line + stale_note(risk_market.get("as_of"), as_of, service, "market_risk"),
        "tier": tier,
        "score": _r(score),
        "shock_class": shock_class,
        "market_wide": market_wide,
        "as_of": risk_market.get("as_of"),
        "source_ids": [f"market_risk:{risk_market.get('as_of')}"],
    }


def book_summary(
    *,
    positions: Optional[Mapping[str, Any]],
    holdings_doc: Mapping[str, Any],
    held: Mapping[str, Mapping[str, Any]],
    quotes: Mapping[str, Mapping[str, Any]],
    stops_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    as_of: datetime,
    service: Any = None,
) -> dict[str, Any]:
    """Positions, cash, and the largest dollar exposure with no working stop.

    positions_current is the read (it is the broker sync); the holdings document is the stated
    fallback when the table has no rows, and the line says which one produced the numbers.
    """
    rows: list[Mapping[str, Any]] = []
    source = ""
    if positions and positions.get("rows"):
        rows = list(positions["rows"])
        source = f"positions_current:{positions.get('as_of')}"
        when = positions.get("as_of")
    else:
        rows = list(holdings_doc.get("holdings") or [])
        source = "holdings.json:" + str(holdings_doc.get("generated_at"))
        when = holdings_doc.get("generated_at")

    def qty(r: Mapping[str, Any]) -> float:
        return _f(r.get("qty"), _f(r.get("broker_shares"), 0.0)) or 0.0

    equities = [r for r in rows if not r.get("is_cash") and qty(r) > 0]
    cash = sum(_f(r.get("market_value"), 0.0) or 0.0 for r in rows if r.get("is_cash"))
    accounts = sorted({str(r.get("account") or "") for r in equities if r.get("account")})

    worst: Optional[dict[str, Any]] = None
    for symbol, pos in held.items():
        cov = stop_coverage(pos, list(stops_by_symbol.get(symbol) or []))
        uncovered = _f(cov.get("uncovered_shares"), 0.0) or 0.0
        if uncovered <= 0:
            continue
        price = _f((quotes.get(symbol) or {}).get("price"))
        if price is None and (_f(pos.get("shares"), 0.0) or 0.0) > 0:
            price = (_f(pos.get("market_value"), 0.0) or 0.0) / float(pos["shares"])
        value = uncovered * (price or 0.0)
        per_acct = cov.get("uncovered_by_account") or {}
        account = max(per_acct, key=lambda k: per_acct[k]) if per_acct else None
        if worst is None or value > worst["value"]:
            worst = {
                "symbol": symbol,
                "account": account,
                "shares": _r(uncovered, 4),
                "price": _r(price),
                "value": _r(value),
                "source_id": f"stop_last_known:{symbol}",
            }

    if worst:
        tail = (
            f"largest unprotected: {worst['symbol']} {worst['shares']:g} sh "
            f"(~${worst['value']:,.0f}) in {_acct(worst['account']) if worst.get('account') else 'an unnamed account'}"
        )
    else:
        tail = "every held share is covered by a working stop"
    line = (
        f"{len(equities)} position(s) in {len(accounts)} account(s), ${cash:,.0f} cash; {tail}"
    )
    return {
        "line": line + stale_note(when, as_of, service, "positions"),
        "positions": len(equities),
        "symbols": len(held),
        "accounts": len(accounts),
        "cash": _r(cash),
        "largest_unprotected_risk": worst,
        "as_of": when,
        "source_ids": [source] + ([worst["source_id"]] if worst else []),
    }


def reentry_summary(desk: Optional[Mapping[str, Any]], as_of: datetime, service: Any = None) -> dict[str, Any]:
    """Re-entry stages, from the desk's own intel states. Stage 1 is 'wait'; past 1 is a review."""
    rows = list((desk or {}).get("rows") or [])
    states: dict[str, int] = {}
    stage2: list[str] = []
    stage3: list[str] = []
    for r in rows:
        state = str((r.get("intel") or {}).get("state") or "UNKNOWN")
        states[state] = states.get(state, 0) + 1
        stage = REENTRY_STAGE.get(state)
        if stage == 2:
            stage2.append(str(r.get("symbol") or ""))
        elif stage == 3:
            stage3.append(str(r.get("symbol") or ""))
    max_stage = max([REENTRY_STAGE.get(k, 1) for k in states] or [1])
    if not rows:
        line = "no re-entry desk read is available"
    elif not stage2 and not stage3:
        line = "Don't buy back yet: no name is past stage 1 of its re-entry conditions"
    else:
        line = (
            f"{len(stage2)} name(s) are past stage 1 (NEAR ENTRY) and {len(stage3)} are READY TO REVIEW "
            f"of {len(rows)} tracked — a review is open, not a buy call"
        )
        named = (stage3 + stage2)[:5]
        if named:
            line += f": {', '.join(named)}"
    return {
        "line": line + stale_note((desk or {}).get("computed_at"), as_of, service, "re-entry desk"),
        "stage2": len(stage2),
        "stage3": len(stage3),
        "max_stage": max_stage,
        "tracked": len(rows),
        "states": states,
        "as_of": (desk or {}).get("computed_at"),
        "source_ids": [f"reentry_decision_desk:{(desk or {}).get('computed_at')}"],
    }


def _day_label(day: Any) -> str:
    s = str(day or "")
    if len(s) >= 10:
        try:
            return f"{datetime.fromisoformat(s):%a %m-%d}"
        except ValueError:
            return s
    return s


def week_line(week_ahead: Mapping[str, Any], limit: int = 6) -> str:
    """This week's macro events and held/watch earnings, short enough for a card."""
    parts: list[str] = []
    for e in week_ahead.get("macro") or []:
        clock = f" {e['time_et']}" if e.get("time_et") else ""
        parts.append(f"{e.get('event')} {_day_label(e.get('date'))}{clock}")
    for e in week_ahead.get("earnings") or []:
        parts.append(f"{e.get('symbol')} earnings {_day_label(e.get('date'))}")
    if not parts:
        return "no scheduled macro events or held/watch earnings in the window"
    shown = parts[:limit]
    more = len(parts) - len(shown)
    return "; ".join(shown) + (f"; +{more} more" if more > 0 else "")


def synopsis_verdict(
    *,
    posture_label: str,
    market: Mapping[str, Any],
    book: Mapping[str, Any],
    stop_advice: Sequence[Mapping[str, Any]],
    reentry: Mapping[str, Any],
    buys: Optional[Mapping[str, Any]] = None,
    regime: Optional[Mapping[str, Any]] = None,
) -> str:
    """One sentence, at most ``VERDICT_MAX_CHARS`` — every figure is already sourced above.

    LQ-20261107-1317 (operator 2026-11-08 20:23 ET): the bottom line must cite the regime it is drawn under —
    "RED sector tape after the 11-04 selloff; futures +0.30%; no buys before CPI Tue". The event date comes from
    the open market-event episode and the futures percent only from a print measured against a settle, so a
    missing input shortens the sentence instead of inventing a clause for it.
    """
    kind = "sector" if market.get("market_wide") is False else ("market-wide" if market.get("market_wide") else "")
    if market.get("tier"):
        head = f"{market['tier']}{(' ' + kind) if kind else ''} tape"
    else:
        head = "no market-risk read"
    regime = regime if isinstance(regime, Mapping) else {}
    event_short = (regime.get("event") or {}).get("short")
    if event_short:
        head += f" {event_short}"
    parts = [head, posture_label.lower()]
    # LQ-1311 (operator 2026-11-08): the buy gate is part of the bottom line, not only a row below it.
    if buys and buys.get("gate") == "NONE" and buys.get("until_short"):
        parts[1] += f", no buys before {buys['until_short']}"
    # Only a percent the Regime block measured against a settle it can name; a level-only print adds no clause.
    futures_short = (regime.get("futures") or {}).get("short")
    if futures_short:
        parts.append(str(futures_short))
    need = [e for e in stop_advice if e.get("answer") in ("FIX_QTY", "ADD_STOP", "RAISE")]
    if need:
        parts.append(f"{len(need)} stop item(s) need a decision")
    worst = book.get("largest_unprotected_risk")
    if worst and worst.get("value"):
        parts.append(f"largest unprotected {worst['symbol']} {worst['shares']:g} sh")
    if market.get("market_wide") is False and "not" not in parts[0]:
        parts.append("not market-wide")
    if not reentry.get("stage2") and not reentry.get("stage3"):
        parts.append("no re-entry past stage 1")
    # Over the limit, drop "not market-wide" (the Market row says it) before clipping a sentence mid-word; the
    # futures clause goes last, because the operator asked for it in the bottom line (LQ-1317).
    for optional in ("not market-wide", "no re-entry past stage 1", futures_short):
        if len("; ".join(parts) + ".") > VERDICT_MAX_CHARS and optional in parts:
            parts.remove(optional)
    return _clip("; ".join(parts) + ".", VERDICT_MAX_CHARS)


def build_synopsis(
    *,
    as_of: datetime,
    holdings_doc: Mapping[str, Any],
    held: Mapping[str, Mapping[str, Any]],
    quotes: Mapping[str, Mapping[str, Any]],
    stops_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    stop_advice: Sequence[Mapping[str, Any]],
    risk_market: Optional[Mapping[str, Any]],
    reentry_desk: Optional[Mapping[str, Any]],
    positions: Optional[Mapping[str, Any]],
    week_ahead: Mapping[str, Any],
    service: Any = None,
    regime: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    market = market_summary(risk_market, as_of, service)
    book = book_summary(
        positions=positions,
        holdings_doc=holdings_doc,
        held=held,
        quotes=quotes,
        stops_by_symbol=stops_by_symbol,
        as_of=as_of,
        service=service,
    )
    reentry = reentry_summary(reentry_desk, as_of, service)
    posture, posture_label = POSTURE_BY_TIER.get(str(market.get("tier") or ""), POSTURE_UNKNOWN)
    posture_text = f"{posture} — {posture_label}"

    stop_advice = list(stop_advice)
    actionable = [e for e in stop_advice if e.get("answer") in ("FIX_QTY", "ADD_STOP", "RAISE")]
    first = actionable[0] if actionable else (stop_advice[0] if stop_advice else None)
    if first:
        verb = {
            "RAISE": f"raise to {first.get('suggested_stop')}",
            "ADD_STOP": f"add a stop near {first.get('suggested_stop')}",
            "FIX_QTY": f"cut the stop qty to {first.get('held_qty'):g}",
        }.get(str(first.get("answer")), "hold")
        do_now_line = (
            f"{len(stop_advice)} stop item(s), {len(actionable)} needing a decision; "
            f"first: {first.get('symbol')} in {_acct(first.get('account'))} — {first.get('answer')} ({verb})"
        )
    else:
        do_now_line = "no stop items tonight"
    do_now = {
        "line": do_now_line,
        "stop_advice_count": len(stop_advice),
        "actionable_count": len(actionable),
        "first": (
            {
                "symbol": first.get("symbol"),
                "account": first.get("account"),
                "answer": first.get("answer"),
                "suggested_stop": first.get("suggested_stop"),
                "source_ids": first.get("source_ids") or [],
            }
            if first
            else None
        ),
        "source_ids": list((first or {}).get("source_ids") or []),
    }

    changes_if = _clip(
        (risk_market or {}).get("deescalates_if")
        or f"the market-risk tier falls below {market.get('tier') or 'its current level'} with breadth improving",
        300,
    )
    this_week = {
        "line": week_line(week_ahead),
        "macro": list(week_ahead.get("macro") or []),
        "earnings": list(week_ahead.get("earnings") or []),
        "source_ids": ["macro_calendar", "earnings_dates"],
    }
    buys = buys_block(market.get("tier"), this_week["macro"], as_of.astimezone(ET))

    source_ids: list[str] = []
    for block in (market, book, reentry, this_week, do_now, regime or {}):
        for sid in block.get("source_ids") or []:
            if sid and sid not in source_ids:
                source_ids.append(sid)

    return {
        "posture": posture_text,
        "verdict": synopsis_verdict(
            posture_label=posture_label, market=market, book=book, stop_advice=stop_advice, reentry=reentry,
            buys=buys, regime=regime,
        ),
        "buys": buys,
        "book": book,
        "market": market,
        "regime": regime,
        "reentry": reentry,
        "this_week": this_week,
        "do_now": do_now,
        "changes_if": changes_if,
        "as_of": as_of.isoformat(),
        "advisory_only": True,
        "source_ids": source_ids,
    }



def research_question(sig: Mapping[str, Any], filings: Sequence[Mapping[str, Any]]) -> str:
    """The question posted to Hermes. Evidence goes in the question so a lane that only
    summarises what it was given still answers WHO / WHY / IMPACT with citations."""
    lines = [
        f"{sig['symbol']} is held ({sig.get('shares')} sh, about ${sig.get('market_value')}) "
        f"and was flagged overnight: move {sig.get('move_pct')}%, {len(sig.get('news') or [])} article(s) since the close.",
        f"Last price {sig.get('price')}. Explain, using only the evidence below and citing it:",
        "1. WHO acted or is named (insiders, filers, counterparties) and WHAT specifically happened.",
        "2. WHY it happened (mechanism, plan or cause), not just that it happened.",
        "3. IMPACT: likely direction and size on the price, weighed against average daily volume.",
        "Say plainly when the evidence does not support a WHO or a WHY; never invent a name or a number.",
        "Evidence:",
    ]
    for n in (sig.get("news") or [])[:8]:
        head = f"- [{n.get('source') or '?'} {str(n.get('published_at') or '')[:10]}] {n.get('title')}"
        if n.get("summary"):
            head += f" — {n['summary'][:280]}"
        if n.get("url"):
            head += f" ({n['url']})"
        lines.append(head)
    for f in filings[:8]:
        lines.append(
            f"- [SEC {f.get('form')} filed {f.get('filed')}] {f.get('filer') or ''} "
            f"{f.get('shares') or ''} sh worth {f.get('value') or ''} ({f.get('url') or 'no url'})"
        )
    if not sig.get("news") and not filings:
        lines.append("- (no news and no filing rows in the store for this window)")
    lines.append("Answer in at most 180 words, in three labelled parts: WHO/WHAT, WHY, IMPACT.")
    return "\n".join(lines)


def deterministic_research_fallback(sig: Mapping[str, Any], filings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What the brief can say with no model at all: the headline facts, still cited."""
    news = sig.get("news") or []
    lines = []
    if news:
        first = news[0]
        lines.append(
            f"WHO/WHAT: not established by the store; the newest item is "
            f"'{first['title']}' ({first.get('source') or 'unknown source'} {str(first.get('published_at') or '')[:10]})."
        )
        lines.append("WHY: the store carries no causal explanation.")
    else:
        lines.append("WHO/WHAT: no news item in the store for this window.")
        lines.append("WHY: not established.")
    if filings:
        f0 = filings[0]
        lines.append(
            f"FILING: SEC {f0.get('form')} by {f0.get('filer') or 'unknown'} filed {f0.get('filed')}."
        )
    move = sig.get("move_pct")
    lines.append(
        f"IMPACT: a {move}% move; no researched impact estimate available, so treat the move as unexplained."
        if move is not None
        else "IMPACT: no researched impact estimate available."
    )
    return {"text": " ".join(lines), "source": "deterministic", "sources": _research_sources(sig, filings)}


def _research_sources(sig: Mapping[str, Any], filings: Sequence[Mapping[str, Any]]) -> list[str]:
    out = []
    for n in (sig.get("news") or [])[:4]:
        out.append(f"{n.get('source') or '?'} {str(n.get('published_at') or '')[:10]}: {n.get('title')}")
    for f in filings[:3]:
        out.append(f"SEC {f.get('form')} {f.get('filer') or ''} {f.get('filed')}")
    return out


def render_deterministic_summary(
    risk: Mapping[str, Any],
    selected: Sequence[Mapping[str, Any]],
    week_ahead: Mapping[str, Any],
    totals: Mapping[str, Any],
    risk_market: Optional[Mapping[str, Any]] = None,
) -> str:
    ups = [s for s in selected if (s.get("move_pct") or 0) > 0]
    downs = [s for s in selected if (s.get("move_pct") or 0) < 0]
    parts = []
    if selected:
        parts.append(
            f"{len(selected)} held name(s) need attention: "
            + ", ".join(f"{s['symbol']} {s['move_pct']:+.2f}%" for s in selected[:5])
            + "."
        )
    else:
        parts.append("No held name moved more than 3% or carried news since the close.")
    if ups or downs:
        parts.append(
            f"{len(ups)} up and {len(downs)} down, on about ${totals.get('market_value_total', 0):,.0f} of measured holdings."
        )
    # The regime snapshot and the market-risk tier are two different measures on two different
    # scales; calling both "risk tier" made one document quote 5.0 and 59.6 for the same thing.
    regime = risk.get("regime_label") or "unavailable"
    line = f"Market regime: {regime} (score {risk.get('regime_score')}, volatility {risk.get('volatility_state')})"
    tier = str((risk_market or {}).get("tier") or "").upper()
    if tier:
        tier_score = _f((risk_market or {}).get("score"))
        line += f"; market risk tier {tier}" + (f" ({tier_score:.1f})" if tier_score is not None else "")
    parts.append(line + ".")
    macro = week_ahead.get("macro") or []
    if macro:
        parts.append("Macro this week: " + "; ".join(f"{m['date']} {m['event']}" for m in macro[:4]) + ".")
    earnings = week_ahead.get("earnings") or []
    if earnings:
        parts.append("Earnings in the window: " + ", ".join(f"{e['symbol']} {e['date']}" for e in earnings[:6]) + ".")
    parts.append("Every action below is advisory; the CIO remains the verdict owner per account.")
    return " ".join(parts)


# ── database loads (SELECT only) ────────────────────────────────────────────────────────────


def connect():
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("DB_HOST") or "/var/run/postgresql",
        port=os.getenv("DB_PORT") or None,
        dbname=os.getenv("DB_NAME") or "trade_ai",
        user=os.getenv("DB_USER") or None,
        password=os.getenv("DB_PASSWORD") or None,
    )


def load_quotes(conn, symbols: Sequence[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not symbols:
        return out
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (symbol) symbol, price, day_change_pct, source, fetched_at
                 FROM market_quotes
                WHERE symbol = ANY(%s) AND price IS NOT NULL
                  AND COALESCE(source, '') <> 'yfinance'
                ORDER BY symbol, fetched_at DESC""",
            (list(symbols),),
        )
        for symbol, price, change_pct, source, quote_time in cur.fetchall():
            out[symbol.upper()] = {
                "price": _f(price),
                "change_pct": _f(change_pct),
                "source": source,
                "quote_time": quote_time.isoformat() if isinstance(quote_time, datetime) else quote_time,
            }
    return out


def load_news(conn, symbols: Sequence[str], since: datetime, until: datetime) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    if not symbols:
        return out
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, symbol, title, summary, source, source_url, published_at
                 FROM news_articles
                WHERE symbol = ANY(%s) AND published_at > %s AND published_at <= %s
                  AND COALESCE(hygiene_status, 'active') = 'active'
                  AND COALESCE(is_duplicate, false) = false
                ORDER BY published_at DESC
                LIMIT 400""",
            (list(symbols), since, until),
        )
        for news_id, symbol, title, summary, source, url, published in cur.fetchall():
            out.setdefault(str(symbol).upper(), []).append(
                {
                    "id": news_id,
                    "title": title,
                    "summary": summary,
                    "source": source,
                    "source_url": url,
                    "published_at": published,
                }
            )
    return out


def load_filings(conn, symbols: Sequence[str], since: date) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    if not symbols:
        return out
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, symbol, filer_name, transaction_type, shares, total_value, filing_date, sec_url
                 FROM sec_form4
                WHERE symbol = ANY(%s) AND filing_date >= %s
                ORDER BY filing_date DESC LIMIT 200""",
            (list(symbols), since),
        )
        for row_id, symbol, filer, kind, shares, value, filed, url in cur.fetchall():
            # The store's boilerplate rows name the issuer with zero shares; they are not a
            # transaction and would drown a real insider row.
            if (_f(shares, 0.0) or 0.0) <= 0 and (_f(value, 0.0) or 0.0) <= 0:
                continue
            out.setdefault(str(symbol).upper(), []).append(
                {
                    "id": row_id,
                    "form": kind or "Form 4",
                    "filer": filer,
                    "shares": _f(shares),
                    "value": _f(value),
                    "filed": filed.isoformat() if isinstance(filed, date) else filed,
                    "url": url,
                }
            )
        cur.execute(
            """SELECT id, symbol, form, filing_date, doc_url, substring(COALESCE(text,''), 1, 240)
                 FROM sec_filing_documents
                WHERE symbol = ANY(%s) AND filing_date >= %s
                  AND (form LIKE '144%%' OR form LIKE '4%%' OR form LIKE 'SC 13%%')
                ORDER BY filing_date DESC LIMIT 200""",
            (list(symbols), since),
        )
        for row_id, symbol, form, filed, url, text in cur.fetchall():
            out.setdefault(str(symbol).upper(), []).append(
                {
                    "id": row_id,
                    "form": form,
                    "filer": (text or "").strip().splitlines()[0][:120] if text else "",
                    "shares": None,
                    "value": None,
                    "filed": filed.isoformat() if isinstance(filed, date) else filed,
                    "url": url,
                }
            )
    return out


def load_stops(conn, symbols: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    if not symbols:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT symbol, account, order_id, stop_price, qty, status, captured_at, origin
                 FROM stop_last_known
                WHERE symbol = ANY(%s)
                ORDER BY captured_at DESC""",
            (list(symbols),),
        )
        rows = [
            {
                "symbol": r[0],
                "account": r[1],
                "order_id": r[2],
                "stop_price": r[3],
                "qty": r[4],
                "status": r[5],
                "captured_at": r[6],
                "origin": r[7],
            }
            for r in cur.fetchall()
        ]
    return working_stops(rows)


def load_daily_bars(conn, symbols: Sequence[str], as_of: datetime) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    if not symbols:
        return out
    with conn.cursor() as cur:
        for symbol in symbols:
            cur.execute(
                """SELECT bar_time, open, high, low, close, volume
                     FROM market_ohlcv_bars
                    WHERE symbol=%s AND timeframe IN ('daily','1d') AND bar_time <= %s
                    ORDER BY bar_time DESC LIMIT 40""",
                (symbol, as_of),
            )
            rows = [
                {"bar_time": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
                for r in cur.fetchall()
            ]
            if rows:
                out[symbol.upper()] = list(reversed(rows))
    return out


def load_cio_decisions(conn, symbols: Sequence[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not symbols:
        return out
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (symbol) symbol, action, status, rationale, created_at, decision_id
                 FROM cio_decisions
                WHERE symbol = ANY(%s)
                ORDER BY symbol, created_at DESC""",
            (list(symbols),),
        )
        for symbol, action, status, rationale, created, decision_id in cur.fetchall():
            out[str(symbol).upper()] = {
                "action": action,
                "status": status,
                "rationale": (rationale or "")[:400],
                "decided_at": created.isoformat() if isinstance(created, datetime) else created,
                "decision_id": decision_id,
            }
    return out


def load_risk_tier(conn) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT generated_at, regime_label, regime_score, confidence, volatility_state,
                      trend_state, breadth_state, risk_appetite_state, stale_data
                 FROM market_regime_snapshots
                ORDER BY generated_at DESC LIMIT 1"""
        )
        row = cur.fetchone()
        out = {}
        if row:
            out = {
                "as_of": row[0].isoformat() if isinstance(row[0], datetime) else row[0],
                "regime_label": row[1],
                "regime_score": _f(row[2]),
                "confidence": _f(row[3]),
                "volatility_state": row[4],
                "trend_state": row[5],
                "breadth_state": row[6],
                "risk_appetite_state": row[7],
                "stale_data": row[8],
                "source": "market_regime_snapshots",
            }
        cur.execute(
            """SELECT run_id, status, finished_at FROM risk_regime_run_log
                ORDER BY finished_at DESC NULLS LAST LIMIT 1"""
        )
        run = cur.fetchone()
        if run:
            out["last_engine_run"] = {
                "run_id": run[0],
                "status": run[1],
                "finished_at": run[2].isoformat() if isinstance(run[2], datetime) else run[2],
            }
        return out


def load_positions_current(conn) -> dict[str, Any]:
    """The broker sync (positions_current), read-only — the book line's primary source."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT account_key, symbol, qty, broker_market_value, is_cash, as_of
                 FROM positions_current
                ORDER BY account_key, symbol"""
        )
        rows = [
            {
                "account": r[0],
                "symbol": r[1],
                "qty": _f(r[2], 0.0),
                "market_value": _f(r[3]),
                "is_cash": bool(r[4]),
                "as_of": r[5].isoformat() if isinstance(r[5], datetime) else r[5],
            }
            for r in cur.fetchall()
        ]
    return {"as_of": _latest([r.get("as_of") for r in rows]), "rows": rows, "source": "positions_current"}


def load_market_risk(root: Optional[Path] = None) -> dict[str, Any]:
    """runtime/market_risk/latest.json — the tier and shock class the synopsis quotes."""
    path = Path(root or state_root()) / "data" / "runtime" / "market_risk" / "latest.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        print(f"[{LANE_ID}] market risk unreadable: {type(exc).__name__}", file=sys.stderr)
        return {}
    shock = doc.get("shock_type") if isinstance(doc.get("shock_type"), Mapping) else {}
    # LQ-20261107-1317: the Regime block needs the parts of the same file the old loader dropped — the sector
    # breakdown, the breadth category and the count of confirming categories. They are passed through, never
    # recomputed, so the brief and the Home card cannot disagree about which sectors were stressed.
    obs = {str(o.get("category")): o for o in (doc.get("observations") or []) if isinstance(o, Mapping)}
    breadth = obs.get("breadth") or {}
    confirming = doc.get("confirming")
    confirming = {"n": confirming, "of": len(doc.get("observations") or [])} if isinstance(confirming, (int, float)) else confirming
    return {
        "as_of": doc.get("as_of"),
        "tier": doc.get("tier") or doc.get("market_tier"),
        "market_tier": doc.get("market_tier"),
        "score": _f(doc.get("score")),
        "mode": doc.get("mode"),
        "carried_only": bool((doc.get("hysteresis") or {}).get("carried_only")),
        "confirming": confirming,
        "breadth": {"state": breadth.get("state"), "detail": breadth.get("headline"),
                    "as_of": breadth.get("observed_at")},
        "sectors": doc.get("sectors") if isinstance(doc.get("sectors"), Mapping) else None,
        "shock": {
            "class": shock.get("class"),
            "label": shock.get("label"),
            "confidence": _f(shock.get("confidence")),
            "headline": shock.get("headline"),
        },
        "deescalates_if": doc.get("deescalates_if"),
        "source": "market_risk/latest.json",
    }


def load_regime(
    *,
    as_of: datetime,
    risk_market: Optional[Mapping[str, Any]],
    calendar: Mapping[str, Any],
    symbols: Sequence[str],
    service: Any = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """The LQ-20261107-1317 Regime block: market, sector, macro gate, event context, futures, pre-market.

    It reads the market-event episode and the off-hours store through its OWN short session, opened read-only under
    ``--dry-run``. A store that cannot be reached degrades the block — every section states its own ``missing`` — and
    never the brief: the tier, the sector read and the macro gate come from files and survive it.
    """
    conn = None
    reader = None
    try:
        conn = connect()
        if dry_run:
            # The guard is armed BEFORE a single row is read, and a guard that cannot be armed means the
            # block does not read at all: a read-only promise we could not prove is not worth a nicer brief.
            from scripts.lib.lane_last_receipt import enforce_readonly

            enforce_readonly(conn)
        reader = regime_reader(conn)
    except Exception as exc:  # noqa: BLE001 — an unreachable or unprovable store is a stated gap
        print(f"[{LANE_ID}] regime store unavailable read-only: {type(exc).__name__}", file=sys.stderr)
        _close_regime_conn(conn)
        conn = None
    try:
        return build_regime(
            as_of=as_of,
            market_risk=risk_market,
            macro=calendar.get("macro") or [],
            held_symbols=symbols,
            db_query=reader,
            service=service,
        )
    finally:
        _close_regime_conn(conn)


def _close_regime_conn(conn: Any) -> None:
    """Close the block's session; a close error is reported, never swallowed, and never fails the brief."""
    if conn is None:
        return
    try:
        conn.close()
    except Exception as exc:  # noqa: BLE001 — reported to stderr by name, so the failure is not silent
        print(f"[{LANE_ID}] regime conn close failed: {type(exc).__name__}", file=sys.stderr)


def load_reentry(root: Optional[Path] = None) -> dict[str, Any]:
    """runtime/reentry_decision_desk_latest.json — each row's canonical intel state."""
    path = Path(root or state_root()) / "data" / "runtime" / "reentry_decision_desk_latest.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        print(f"[{LANE_ID}] re-entry desk unreadable: {type(exc).__name__}", file=sys.stderr)
        return {}
    return {"computed_at": doc.get("computed_at"), "rows": doc.get("rows") or [], "source": "reentry_decision_desk"}


def load_calendar(sessions: Sequence[date], root: Optional[Path] = None) -> dict[str, Any]:
    base = Path(root or state_root())
    macro_rows: list[dict[str, Any]] = []
    notes: list[str] = []
    macro_path = base / "data" / "runtime" / "macro_calendar.json"
    try:
        doc = json.loads(macro_path.read_text(encoding="utf-8"))
        wanted = {d.isoformat() for d in sessions}
        dates = doc.get("dates") or {}
        entries = dates.items() if isinstance(dates, Mapping) else ((str(e.get("date") or ""), e) for e in dates)
        for day, entry in entries:
            if str(day) not in wanted:
                continue
            for ev in (entry or {}).get("events") or []:
                macro_rows.append(
                    {
                        "date": str(day),
                        "event": ev.get("name") or ev.get("event") or "event",
                        "time_et": ev.get("time_et") or ev.get("time"),
                        "importance": ev.get("importance"),
                    }
                )
    except FileNotFoundError:
        notes.append(f"macro calendar missing at {macro_path}")
    except Exception as exc:  # noqa: BLE001 -- a corrupt calendar is a named gap, not a crash
        notes.append(f"macro calendar unreadable ({type(exc).__name__})")
    earnings: list[dict[str, Any]] = []
    earn_path = base / "data" / "portfolios" / "state" / "earnings_dates.json"
    try:
        doc = json.loads(earn_path.read_text(encoding="utf-8"))
        wanted = {d.isoformat() for d in sessions}
        for symbol, ent in doc.items():
            day = str((ent or {}).get("earnings_date") or "")
            if day in wanted:
                earnings.append({"symbol": symbol, "date": day})
    except FileNotFoundError:
        notes.append(f"earnings calendar missing at {earn_path}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"earnings calendar unreadable ({type(exc).__name__})")
    earnings.sort(key=lambda e: (e["date"], e["symbol"]))
    return {"macro": macro_rows, "earnings": earnings, "notes": notes}


# ── research (the existing Hermes path) ─────────────────────────────────────────────────────


def _parse_no_store(stdout: str) -> Optional[dict[str, Any]]:
    """--no-store prints a JSON object after its packet dump; take the last complete one."""
    dec = json.JSONDecoder()
    idx = stdout.find('{"stored"')
    if idx < 0:
        idx = stdout.find('"stored"')
        if idx < 0:
            return None
        idx = stdout.rfind("{", 0, idx)
    while idx >= 0:
        try:
            obj, _end = dec.raw_decode(stdout[idx:])
            if isinstance(obj, dict) and "stored" in obj:
                return obj
        except json.JSONDecodeError:
            pass
        idx = stdout.find('{"stored"', idx + 1)
        if idx < 0:
            nxt = stdout.find('"stored"', (idx + 1) if idx >= 0 else 0)
            if nxt < 0:
                break
            idx = stdout.rfind("{", 0, nxt)
    return None


def research_one(
    symbol: str,
    question: str,
    lanes: Sequence[str],
    script: Path,
    timeout: int = RESEARCH_TIMEOUT_S,
) -> dict[str, Any]:
    """Ask Hermes. A gated lane (exit 75) hands over to the next; an answered one stops the chain."""
    attempts: list[dict[str, Any]] = []
    for lane in lanes:
        cmd = [
            sys.executable,
            str(script),
            "--lane",
            lane,
            "--question",
            question,
            "--symbol",
            symbol,
            "--trigger",
            RESEARCH_TRIGGER,
            "--apply",
            "--no-store",
        ]
        try:
            proc = subprocess.run(cmd, cwd=str(script.parents[1]), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            attempts.append({"lane": lane, "outcome": "timeout"})
            continue
        parsed = _parse_no_store(proc.stdout or "")
        status = (parsed or {}).get("status")
        attempts.append({"lane": lane, "rc": proc.returncode, "status": status})
        if proc.returncode == 75:
            continue
        if parsed and status in {"sent", "accepted"} and (parsed.get("recommendation") or "").strip():
            return {
                "status": "answered",
                "lane": lane,
                "answer": (parsed.get("recommendation") or "").strip()[:4000],
                "evidence": parsed.get("evidence"),
                "dissent": parsed.get("dissent"),
                "attempts": attempts,
            }
        if parsed and status == "refused":
            attempts[-1]["outcome"] = "refused"
            continue
        # Any other terminal answer (unavailable, auth_pending, budget) is a fact about that lane.
    return {"status": "unanswered", "lane": None, "answer": None, "attempts": attempts}


class ResearchBudget:
    """The reservation: a per-day counter file, so a full day of other T0 work cannot starve the
    brief and a re-run cannot double-spend."""

    def __init__(self, path: Path, per_day: int = RESEARCH_RESERVATION_PER_DAY, as_of: Optional[datetime] = None):
        self.path = path
        self.per_day = per_day
        self.day = (as_of or datetime.now(timezone.utc)).astimezone(ET).date().isoformat()
        self.used = 0
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if doc.get("date") == self.day:
                self.used = int(doc.get("used") or 0)
        except (FileNotFoundError, ValueError, TypeError):
            pass

    def remaining(self) -> int:
        return max(0, self.per_day - self.used)

    def spend(self, n: int = 1) -> None:
        self.used += n
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"date": self.day, "used": self.used, "reserved": self.per_day}), encoding="utf-8")
        except OSError:
            pass


# ── the LLM narrative (governed, optional) ──────────────────────────────────────────────────

PROCESS_ID = "cio_overnight_brief"


def llm_narrative(packet: Mapping[str, Any], max_tokens: int = 1400) -> Optional[dict[str, Any]]:
    """One governed DeepSeek call. Returns None on any failure — the caller falls back."""
    try:
        from scripts import llm_lane
    except Exception:  # noqa: BLE001
        try:
            import llm_lane  # type: ignore
        except Exception:
            return None
    prompt = (
        "You are writing the prose of a CIO overnight brief. Rules: never state a price target, never "
        "recommend a trade size, never say buy or sell; the actions are already written and you must not "
        "change them. Use only the facts in the packet. Cite each claim with the source name given. If a "
        "fact is absent, say it is not established.\n\nReturn STRICT JSON with this shape:\n"
        '{"summary": "4-6 sentences", "names": {"SYM": {"what_why": "<=80 words", "impact": "<=40 words"}}}\n\n'
        "PACKET:\n" + json.dumps(packet, default=str)[:12000]
    )
    try:
        text = llm_lane.generate(
            prompt,
            lane="deepseek-flash",
            process_id=PROCESS_ID,
            task_summary="cio_overnight_brief",
            timeout=120,
            max_tokens=max_tokens,
            response_json=True,
            metadata={"lane_id": LANE_ID},
        )
    except Exception as exc:  # noqa: BLE001 -- an LLM outage degrades wording, never the brief
        print(f"[{LANE_ID}] llm narrative unavailable: {type(exc).__name__}", file=sys.stderr)
        return None
    if isinstance(text, dict):
        return text
    try:
        doc = json.loads(text)
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


def _safe_prose(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


# ── assembly ────────────────────────────────────────────────────────────────────────────────


def build_brief(
    *,
    as_of: datetime,
    holdings_doc: Mapping[str, Any],
    quotes: Mapping[str, Mapping[str, Any]],
    news_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    filings_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    stops_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    bars_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    decisions: Mapping[str, Mapping[str, Any]],
    risk: Mapping[str, Any],
    calendar: Mapping[str, Any],
    session_service: Any = None,
    research_fn: Any = None,
    narrative_fn: Any = None,
    budget: Optional[ResearchBudget] = None,
    max_research: int = RESEARCH_PER_RUN_DEFAULT,
    holdings_meta: Optional[Mapping[str, Any]] = None,
    quote_as_of: Optional[str] = None,
    positions: Optional[Mapping[str, Any]] = None,
    risk_market: Optional[Mapping[str, Any]] = None,
    reentry_desk: Optional[Mapping[str, Any]] = None,
    regime: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    if session_service is None:
        from scripts.lib.cio_market_session import get_session_service

        session_service = get_session_service()
    close_date, close_dt = last_close_at(as_of, session_service)
    window_start = previous_close_at(close_date, session_service)
    sessions = next_sessions(as_of, WEEK_AHEAD_SESSIONS, session_service)
    held = aggregate_holdings(holdings_doc.get("holdings") or [])
    selected = select_names(held, quotes, news_by_symbol)
    excluded = selection_exclusions(held)
    note_gaps: list[str] = []
    if excluded.get("below_position_floor"):
        note_gaps.append(
            f"{excluded['below_position_floor']} held row(s) below ${MIN_POSITION_MARKET_VALUE:,.0f} "
            f"were not briefed (fractional remnants, not positions)"
        )

    if not calendar.get("macro"):
        note_gaps.append("no macro events in the next five sessions from the local calendar file")
    if not calendar.get("earnings"):
        note_gaps.append("no held/watchlist earnings in the window from the local earnings file")

    items: list[dict[str, Any]] = []
    stop_advice: list[dict[str, Any]] = []
    research_stats = {"attempted": 0, "answered": 0, "unanswered": 0, "skipped_budget": 0, "reserved_per_day":
                      budget.per_day if budget else 0, "budget_remaining": budget.remaining() if budget else 0}
    for idx, sig in enumerate(selected):
        symbol = sig["symbol"]
        filings = list(filings_by_symbol.get(symbol) or [])
        stops = list(stops_by_symbol.get(symbol) or [])
        bars = list(bars_by_symbol.get(symbol) or [])
        price = sig.get("price")
        if price is None:
            for b in reversed(bars):
                price = _f(b.get("close"))
                if price is not None:
                    break
        atr = atr14(bars)
        cov = stop_coverage(held[symbol], stops)
        cush = cushion(price, stops, atr)
        action = advisory_action(price, cov, cush, atr)

        research: dict[str, Any]
        wanted = idx < max_research
        can_spend = budget is None or budget.remaining() >= len(RESEARCH_LANES_DEFAULT.split(","))
        if research_fn is None or not wanted:
            research = deterministic_research_fallback(sig, filings)
            research["status"] = "disabled" if research_fn is None else "beyond_run_cap"
        elif not can_spend:
            research = deterministic_research_fallback(sig, filings)
            research["status"] = "budget_reserved_exhausted"
            research_stats["skipped_budget"] += 1
        else:
            research_stats["attempted"] += 1
            answer = research_fn(symbol, research_question(sig, filings), RESEARCH_LANES_DEFAULT.split(","))
            spent = max(1, len(answer.get("attempts") or []))
            if budget is not None:
                budget.spend(spent)
            if answer.get("status") == "answered":
                research_stats["answered"] += 1
                research = {
                    "status": "answered",
                    "lane": answer.get("lane"),
                    "text": answer["answer"],
                    "evidence": answer.get("evidence"),
                    "dissent": answer.get("dissent"),
                    "sources": _research_sources(sig, filings),
                    "attempts": answer.get("attempts"),
                }
            else:
                research_stats["unanswered"] += 1
                research = deterministic_research_fallback(sig, filings)
                research["status"] = "unanswered_deterministic_fallback"
                research["attempts"] = answer.get("attempts")

        items.append(
            {
                "symbol": symbol,
                "reasons": sig["reasons"],
                "price": _r(price),
                "move_pct": sig.get("move_pct"),
                "shares": sig.get("shares"),
                "market_value": sig.get("market_value"),
                "accounts": sig.get("accounts"),
                "quote_source": sig.get("quote_source"),
                "news": sig.get("news"),
                "news_total": sig.get("news_total"),
                "filings": filings,
                "stops": {
                    "working": stops,
                    "coverage": cov,
                    "cushion": cush,
                    "captured_at": stops[0].get("captured_at") if stops else None,
                },
                "cio_decision": decisions.get(symbol),
                "action_advisory": action,
                "research": research,
                "what_why": None,
                "impact": None,
            }
        )

        # ── stop advice: one entry per account per holding (AMENDMENT 1) ──
        event = classify_event(sig, filings, str(research.get("text") or ""))
        source_ids = [f"news:{n['id']}" for n in (sig.get("news") or []) if n.get("id") is not None]
        source_ids += [f"sec:{f['id']}" for f in filings if f.get("id") is not None]
        if research.get("status") == "answered":
            source_ids.append(f"research:{research.get('lane')}")
        for account, acct_qty in sorted((held[symbol].get("per_account") or {}).items()):
            if acct_qty <= 0:
                continue
            stop_advice.append(
                stop_advice_for_account(
                    symbol=symbol,
                    account=account,
                    held_qty=float(acct_qty),
                    price=price,
                    move_pct=sig.get("move_pct"),
                    atr=atr,
                    stops=stops,
                    event=event,
                    source_ids=source_ids + [f"stop_last_known:{symbol}:{account}"],
                    as_of=as_of.isoformat(),
                )
            )

    research_stats["budget_remaining"] = budget.remaining() if budget else 0
    stop_advice.sort(key=lambda e: (e["answer"] in ("HOLD", "NO_ACTION"), -(e.get("held_qty") or 0.0)))
    totals = {
        "market_value_total": (holdings_doc.get("portfolio_totals") or {}).get("broker_market_value_total")
        or _r(sum(v["market_value"] for v in held.values())),
        "held_names": len(held),
    }

    week_ahead = {
        "sessions": [d.isoformat() for d in sessions],
        "macro": list(calendar.get("macro") or []),
        "earnings": list(calendar.get("earnings") or []),
        "notes": list(calendar.get("notes") or []),
    }
    summary_text = render_deterministic_summary(risk, items, week_ahead, totals, risk_market)
    summary_source = "deterministic"

    packet = {
        "as_of": as_of.isoformat(),
        "last_close": {"session_date": close_date.isoformat(), "closed_at": close_dt.isoformat()},
        "risk_tier": risk,
        "week_ahead": week_ahead,
        "names": [
            {
                "symbol": it["symbol"],
                "move_pct": it["move_pct"],
                "price": it["price"],
                "shares": it["shares"],
                "market_value": it["market_value"],
                "news": [{"source": n["source"], "published_at": n["published_at"], "title": n["title"]}
                         for n in (it["news"] or [])[:6]],
                "filings": it["filings"][:4],
                "research": it["research"].get("text"),
                "stops": it["stops"]["cushion"],
                "uncovered_shares": it["stops"]["coverage"].get("uncovered_shares"),
                "action_advisory": it["action_advisory"],
            }
            for it in items
        ],
    }
    if narrative_fn is not None:
        doc = narrative_fn(packet)
        if isinstance(doc, Mapping):
            summary = _safe_prose(doc.get("summary"), 1600)
            if summary:
                summary_text = summary
                summary_source = "llm"
            names = doc.get("names") if isinstance(doc.get("names"), Mapping) else {}
            for it in items:
                ent = names.get(it["symbol"]) if isinstance(names, Mapping) else None
                if isinstance(ent, Mapping):
                    it["what_why"] = _safe_prose(ent.get("what_why"), 900) or None
                    it["impact"] = _safe_prose(ent.get("impact"), 400) or None

    doc = {
        "schema": SCHEMA,
        "lane_id": LANE_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat(),
        "run_id": os.environ.get("TRADEAI_RUN_ID") or f"cio-brief-{uuid.uuid4().hex[:12]}",
        "advisory_only": True,
        "verdict_owner": "CIO",
        "last_close": {"session_date": close_date.isoformat(), "closed_at": close_dt.isoformat()},
        "news_window": {"from": window_start.isoformat(), "to": as_of.isoformat()},
        "synopsis": build_synopsis(
            as_of=as_of,
            holdings_doc=holdings_doc,
            held=held,
            quotes=quotes,
            stops_by_symbol=stops_by_symbol,
            stop_advice=stop_advice,
            risk_market=risk_market,
            reentry_desk=reentry_desk,
            positions=positions,
            week_ahead=week_ahead,
            service=session_service,
            regime=regime,
        ),
        "summary": {"text": summary_text, "source": summary_source},
        "risk_tier": risk,
        "holdings": items,
        "stop_advice": stop_advice,
        "watchlist": [],
        "week_ahead": week_ahead,
        "research": research_stats,
        "gaps": note_gaps,
        "excluded_reasons": excluded,
        "source_timestamps": {
            "news": _latest([n.get("published_at") for it in items for n in (it.get("news") or [])]),
            "positions": (positions or {}).get("as_of") or (holdings_meta or {}).get("generated_at"),
            "risk": (risk_market or {}).get("as_of") or risk.get("as_of"),
            "quotes": quote_as_of,
            "stops": _latest([s.get("captured_at") for stops in stops_by_symbol.values() for s in stops]),
        },
        "counts": {
            "held_names": len(held),
            "selected": len(items),
            "with_news": sum(1 for it in items if "news" in (it["reasons"] or [])),
            "with_move": sum(1 for it in items if "move" in (it["reasons"] or [])),
            "uncovered_positions": sum(1 for it in items if not it["stops"]["coverage"].get("fully_covered")),
        },
    }
    return doc


def emit_lane_output(doc: Mapping[str, Any], mode: str) -> None:
    """One ``LANE_OUTPUT`` line on stderr for a real run and a dry run — the counts the executor
    captures. An emulated acceptance run emits none: it is not the scheduled lane's run."""
    try:
        from scripts.lib.lane_output import emit, output_block

        selected = int((doc.get("counts") or {}).get("selected") or 0)
        excluded = doc.get("excluded_reasons") or {}
        block = output_block(
            produced=selected,
            attempted=selected,
            skipped={k: int(v) for k, v in excluded.items()},
            empty_reason=None if selected else "no held name moved more than 3% or carried news since the close",
            unit="held_name",
        )
        emit(LANE_ID, mode, block)
    except Exception as exc:  # noqa: BLE001 -- evidence printing must never fail the run
        print(f"[{LANE_ID}] lane output not emitted: {type(exc).__name__}", file=sys.stderr)


def write_brief(doc: Mapping[str, Any], out_dir: Path) -> list[Path]:
    """Atomic latest + dated copy. Returns the paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    as_of = datetime.fromisoformat(str(doc["as_of"]).replace("Z", "+00:00"))
    dated = out_dir / f"{as_of.astimezone(ET).date().isoformat()}.json"
    latest = out_dir / "latest.json"
    written = []
    for path in (dated, latest):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1, default=str, sort_keys=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        written.append(path)
    return written


# ── entry point ─────────────────────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CIO overnight brief (advisory only)")
    ap.add_argument("--as-of", default=None, help="ISO instant the brief is 'as of' (default: now)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="assemble and print; no research call, no LLM, no write")
    mode.add_argument("--apply", action="store_true", help="run for real: research, LLM, write JSON + receipt")
    ap.add_argument("--no-research", action="store_true", help="skip Hermes (deterministic brief only)")
    ap.add_argument("--no-llm", action="store_true", help="skip the narrative model")
    ap.add_argument(
        "--emulated",
        action="store_true",
        help="write to --out-dir only and skip the lane receipt: an acceptance run, not a scheduled one",
    )
    ap.add_argument("--max-research", type=int, default=RESEARCH_PER_RUN_DEFAULT)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--holdings", default=None)
    ap.add_argument("--state-root", default=None)
    ap.add_argument(
        "--researcher-script",
        default=None,
        help="path to hermes_external_researcher.py (default: this tree's copy). A scratch tree "
        "has no .env; an acceptance run passes the deployed release's copy, which the lane itself uses.",
    )
    args = ap.parse_args(argv)

    started = datetime.now(timezone.utc)
    as_of = _parse_as_of(args.as_of)
    root = Path(args.state_root) if args.state_root else state_root()
    out_dir = Path(args.out_dir) if args.out_dir else runtime_dir(root)
    holdings_path = Path(args.holdings) if args.holdings else root / "data" / "portfolios" / "state" / "holdings.json"

    holdings_doc = json.loads(holdings_path.read_text(encoding="utf-8"))
    held = aggregate_holdings(holdings_doc.get("holdings") or [])
    symbols = sorted(held)

    from scripts.lib.cio_market_session import get_session_service

    service = get_session_service()
    close_date, close_dt = last_close_at(as_of, service)
    since = previous_close_at(close_date, service)

    conn = connect()
    try:
        if args.dry_run:
            try:
                from scripts.lib.lane_last_receipt import enforce_readonly

                enforce_readonly(conn)
            except Exception:  # noqa: BLE001
                pass
        quotes_db = load_quotes(conn, symbols)
        news = load_news(conn, symbols, since, as_of)
        filings = load_filings(conn, symbols, close_date - timedelta(days=FILING_LOOKBACK_DAYS))
        stops = load_stops(conn, symbols)
        bars = load_daily_bars(conn, symbols, as_of)
        decisions = load_cio_decisions(conn, symbols)
        risk = load_risk_tier(conn)
        positions = load_positions_current(conn)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    # The snapshot file is the house price read (Finviz cache first); the DB quote is the fallback
    # and is labelled as such on each name so a stale Finviz cache is visible.
    quotes = dict(quotes_db)
    quote_as_of = None
    snap_path = root / "data" / "portfolios" / "state" / "ticker_snapshot_latest.json"
    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        quote_as_of = (snap.get("_meta") or {}).get("generated_at")
        for symbol, ent in (snap.get("tickers") or {}).items():
            q = (ent or {}).get("quote") or {}
            if _f(q.get("price")) is not None:
                quotes[symbol.upper()] = {
                    "price": _f(q.get("price")),
                    "change_pct": _f(q.get("change_pct")),
                    "source": q.get("source") or "ticker_snapshot",
                    "quote_time": ent.get("fetched_at"),
                }
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"[{LANE_ID}] ticker snapshot unreadable: {type(exc).__name__}", file=sys.stderr)

    calendar = load_calendar(next_sessions(as_of, WEEK_AHEAD_SESSIONS, service), root)
    risk_market = load_market_risk(root)
    reentry_desk = load_reentry(root)
    # LQ-20261107-1317 (operator 2026-11-08 20:23 ET: "is the market right, is the sector right, we also have the
    # CPI, plus we're coming through the weekend of a crash"): one deterministic Regime block, every fire, so the
    # 06:00 read carries the futures and the 08:00 read carries pre-market.
    regime = load_regime(
        as_of=as_of, risk_market=risk_market, calendar=calendar, symbols=symbols, service=service,
        dry_run=args.dry_run,
    )
    budget = None if args.dry_run or args.no_research else ResearchBudget(out_dir / "research_budget.json", as_of=as_of)
    research_fn = None
    if not args.dry_run and not args.no_research:
        script = Path(args.researcher_script) if args.researcher_script else ROOT / "scripts" / "hermes_external_researcher.py"
        research_fn = lambda symbol, question, lanes: research_one(symbol, question, lanes, script)  # noqa: E731
    narrative_fn = None
    if not args.dry_run and not args.no_llm:
        narrative_fn = llm_narrative

    doc = build_brief(
        as_of=as_of,
        holdings_doc=holdings_doc,
        quotes=quotes,
        news_by_symbol=news,
        filings_by_symbol=filings,
        stops_by_symbol=stops,
        bars_by_symbol=bars,
        decisions=decisions,
        risk=risk,
        calendar=calendar,
        session_service=service,
        research_fn=research_fn,
        narrative_fn=narrative_fn,
        budget=budget,
        max_research=args.max_research,
        holdings_meta={
            "generated_at": holdings_doc.get("generated_at"),
            "as_of": holdings_doc.get("as_of"),
            "last_repriced": holdings_doc.get("last_repriced"),
        },
        quote_as_of=quote_as_of,
        positions=positions,
        risk_market=risk_market,
        reentry_desk=reentry_desk,
        regime=regime,
    )

    summary = {
        "as_of": doc["as_of"],
        "selected": doc["counts"]["selected"],
        "held_names": doc["counts"]["held_names"],
        "research": doc["research"],
        "summary_source": doc["summary"]["source"],
        "synopsis": {
            "posture": doc["synopsis"]["posture"],
            "verdict": doc["synopsis"]["verdict"],
            "sources": len(doc["synopsis"]["source_ids"]),
        },
        "advisory_only": True,
    }
    if args.dry_run:
        from scripts.lib.lane_last_receipt import dry_run_report

        emit_lane_output(doc, "dry_run")
        dry_run_report(
            LANE_ID,
            summary,
            would_write=[str(out_dir / "latest.json"), str(out_dir / f"{as_of.astimezone(ET).date().isoformat()}.json")],
        )
        return 0

    written = write_brief(doc, out_dir)
    # Verify by artifact: the file must exist, parse, and carry this run's id.
    check = json.loads((out_dir / "latest.json").read_text(encoding="utf-8"))
    ok = check.get("run_id") == doc["run_id"] and len(check.get("holdings") or []) == doc["counts"]["selected"]

    if args.emulated:
        # An acceptance run writes its own JSON and nothing else: no lane receipt, so the
        # scheduled lane's ok_at is not advanced by an emulation.
        print(json.dumps({"emulated": True, "written": [str(p) for p in written], **summary}, indent=1, default=str))
        return 0 if ok else 1

    from scripts.lib.lane_last_receipt import write_lane_receipt

    emit_lane_output(doc, "live")
    write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        started_at=started,
        script="scripts/cio_overnight_brief.py",
        summary=summary,
        produced_count=doc["counts"]["selected"],
        attempted_count=doc["counts"]["selected"],
        output_evidence=[{"kind": "json", "path": str(p)} for p in written],
        empty_reason=None if doc["counts"]["selected"] else "no held name moved more than 3% or carried news since the close",
        outcome="ok" if ok else "error",
    )
    print(json.dumps({"written": [str(p) for p in written], **summary}, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
