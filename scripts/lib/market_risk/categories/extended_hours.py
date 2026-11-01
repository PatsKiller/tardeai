"""extended_hours category — premarket / after-hours index proxies and index heavyweights (plan §5.1, §5.14).

Worst index-proxy move versus the previous close over the last ``lookback_hours`` of extended-session quotes:
at or below ``warn_pct`` WARN, at or below ``stress_pct`` STRESS. Heavyweights down at least
``heavyweight_stress_pct`` are named as evidence (the 10-29 case: INTC -22%, AMZN -6% after the close while NQ
fell 1.6%). An opening-shock verdict in ``ctx.extras["opening_shock"]`` of ``panic_open`` forces STRESS with
``shock=True`` evidence, which scoring treats as a single-evaluation RED. No extended-session quotes → UNKNOWN.
"""

from __future__ import annotations

import sys

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from scripts.lib.market_risk import sessions
from scripts.lib.market_risk.categories._marketdata import ts as _ts
from scripts.lib.market_risk.contract import CategoryObservation, EvalContext, Evidence, unknown

CATEGORY = "extended_hours"
ET = ZoneInfo("America/New_York")


def _gap_moves(ctx: EvalContext, cfg: dict[str, Any], proxies: list[str]) -> dict[str, dict[str, Any]]:
    """Overnight gap of each index proxy: today's 09:30 open vs the previous session's close, in % and in ATR units.
    Known from the open only (``session_opens`` never returns an open before 09:30 ET of its session)."""
    gc = cfg.get("gap_proxy") or {}
    if not gc.get("enabled", True) or not hasattr(ctx.reader, "session_opens"):
        return {}
    today = ctx.now.astimezone(ET).date()
    n_atr = int(gc.get("atr_sessions", 14))
    opens = {r["symbol"]: r for r in ctx.reader.session_opens(proxies, sessions=1, end=ctx.now)}
    bars: dict[str, list[dict[str, Any]]] = {}
    for r in ctx.reader.daily_bars(proxies, sessions=n_atr + 2, end=ctx.now):
        bars.setdefault(str(r["symbol"]), []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for s in proxies:
        o = opens.get(s)
        if not o or date.fromisoformat(str(o["date"])) != today:
            continue
        prior = [b for b in bars.get(s, []) if date.fromisoformat(str(b["date"])) < today]
        if len(prior) < n_atr + 1:
            continue
        try:
            prev = float(prior[-1]["close"])
            gap = 100.0 * (float(o["open"]) - prev) / prev if prev else None
        except (TypeError, ValueError, KeyError):
            continue
        trs = []
        for a, b in zip(prior[-n_atr - 1 : -1], prior[-n_atr:]):
            # quote-derived bars carry a close but no high/low: skip them for the ATR rather than blank the whole
            # category (review of #2383, N4)
            try:
                hi, lo, pc = float(b["high"]), float(b["low"]), float(a["close"])
            except (TypeError, ValueError, KeyError):
                continue
            trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
        if len(trs) < max(3, n_atr // 2):
            continue  # too few full OHLC bars for an honest ATR
        atr_pct = 100.0 * (sum(trs) / len(trs)) / prev if prev else None
        if gap is None or not atr_pct:
            continue
        out[s] = {"gap_pct": gap, "gap_atr": gap / atr_pct, "as_of": o["as_of"], "prev_close": prev}
    return out


def _move(row: dict[str, Any]) -> float | None:
    try:
        price, prev = float(row["price"]), float(row["prev_close"])
    except (KeyError, TypeError, ValueError):
        return None
    return 100.0 * (price - prev) / prev if prev else None


EXTENDED_SESSIONS = ("premarket", "afterhours", "overnight", "extended", "pre", "post")


def _proof(r: dict[str, Any], now, cfg: dict[str, Any]) -> str | None:
    """Why this row is NOT a usable extended-session print, or None when it is.

    ``market_quotes.fetched_at`` is the fetch time, not a trade time, and Alpaca IEX ``latestTrade`` returns the
    closing print when nothing has traded since: 20 of 106 after-close QQQ/SPY rows in the 30 days to 2026-10-31
    were priced exactly at that day's close (Wed 10-28 16:50 QQQ 725.59 = close). Such a row proves nothing about
    the after-hours market, so it can never read CALM. Likewise a feed with no overnight book (IEX: 04:00-20:00)
    fetched 20:00-04:00 is a stale last trade."""
    try:
        at = _ts(r)
    except Exception:  # noqa: BLE001
        at = None
    if at is None:
        return "no timestamp"
    if at > now + timedelta(seconds=float(cfg.get("future_tolerance_seconds", 60))):
        return "stamped in the future"
    if r.get("prev_close") in (None, "") or r.get("price") in (None, ""):
        return f"no reference close ({r.get('reference') or 'missing'})"
    # The reference must be the close of the session this print follows (after-hours on D -> D's close; Sunday
    # overnight / Monday pre-market -> Friday's). market_quotes_extended (#2384) stamps reference_date; a row
    # referencing any other session (a 10:00 quote, Thursday's close for a Friday after-hours print) measures the
    # regular-session move, not an extended one (review of #2415, F4).
    if r.get("reference_date"):
        want = sessions.last_closed_session(at).isoformat()
        if str(r["reference_date"])[:10] != want:
            return f"reference close {str(r['reference_date'])[:10]} is not the {want} session close"
    src = str(r.get("source") or "").lower().split(":", 1)[-1]  # feed name (market_quotes_extended:sip -> sip)
    sess = str(r.get("session") or "").lower()
    overnight_ok = {str(x).lower() for x in cfg.get("overnight_sources") or []}
    if sess == "overnight" and src and src not in overnight_ok:
        return f"{src} has no overnight trades (20:00-04:00 ET); its price is an earlier last trade"
    try:
        if float(r["price"]) == float(r["prev_close"]):
            return "price equals the reference close: no extended-session trade proven"
    except (TypeError, ValueError):
        return "unreadable price"
    return None


def _source_ok(source: str, allowed: set[str]) -> bool:
    """``market_quotes_extended:sip`` matches ``market_quotes_extended``; ``alpaca`` matches ``alpaca``."""
    src = source.lower()
    return src in allowed or src.split(":", 1)[0] in allowed


def _latest(
    rows: list[dict[str, Any]], sources: list[str] | None = None, now=None, cfg: dict[str, Any] | None = None
) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[dict[str, Any], str]]]:
    """(newest PROVEN extended-session print per symbol, {symbol: (newest unproven row, why)} for symbols whose
    newest extended row proves nothing). A row naming a ``source`` outside ``sources`` is skipped: a feed whose price
    is the regular-session close (yfinance ``regularMarketPrice``) fetched at 18:00 is not an after-hours print."""
    allowed = {str(x).lower() for x in sources} if sources else None
    newest: dict[str, tuple[dict[str, Any], str | None]] = {}
    future: dict[str, tuple[dict[str, Any], str]] = {}
    for r in rows:
        if str(r.get("session") or "").lower() not in EXTENDED_SESSIONS:
            continue
        if allowed is not None and r.get("source") and not _source_ok(str(r["source"]), allowed):
            continue
        s = str(r.get("symbol") or "").upper()
        if not s:
            continue
        why = _proof(r, now, cfg or {}) if now is not None else None
        if why == "stamped in the future":
            future.setdefault(s, (r, f"{why} (invalid; the reader should never return it)"))
            continue  # never newer than a valid row; it is not a row at all
        if s not in newest or str(r.get("as_of")) > str(newest[s][0].get("as_of")):
            newest[s] = (r, why)
    good = {s: r for s, (r, why) in newest.items() if why is None}
    bad = {s: (r, why) for s, (r, why) in newest.items() if why is not None}
    for s, rw in future.items():
        if s not in good:
            bad.setdefault(s, rw)
    return good, bad


def _last_close(now):
    """The instant of the most recent regular-session close at or before ``now`` (so a Saturday or Sunday evaluation
    still sees Friday's after-hours quotes and can report their age instead of "no quotes")."""
    from datetime import datetime as _dt

    d = now.astimezone(ET).date()
    for _ in range(10):
        if sessions.is_trading_day(d):
            t = _dt.combine(d, sessions.close_time(d), ET)
            if t <= now:
                return t
        d -= timedelta(days=1)
    return now


def _age(row: dict[str, Any], ctx: EvalContext) -> float | None:
    """Age of a quote in the same clock the scorer decays with (``decay.clock``; market hours by default)."""
    from scripts.lib.market_risk.categories._marketdata import ts as _ts
    from scripts.lib.market_risk.scoring import _age_hours

    at = _ts(row)
    return None if at is None else _age_hours(at, ctx.now, ctx.policy.get("decay") or {})


def _et_label(iso: Any) -> str:
    from scripts.lib.market_risk.categories._marketdata import ts as _ts

    t = _ts({"as_of": iso}) if iso else None
    return t.astimezone(ET).strftime("%a %m-%d %H:%M ET") if t else "time unknown"


def evaluate(ctx: EvalContext) -> CategoryObservation:
    cfg = ctx.policy.get("extended_hours") or {}
    proxies = [str(s).upper() for s in cfg.get("index_proxies") or ["QQQ", "SPY"]]
    heavy = [str(s).upper() for s in cfg.get("heavyweights") or []]
    start = min(ctx.now - timedelta(hours=float(cfg.get("lookback_hours", 18))), _last_close(ctx.now))
    pcfg = dict(cfg, future_tolerance_seconds=(ctx.policy.get("decay") or {}).get("future_tolerance_seconds", 60))
    latest, unproven = _latest(
        ctx.reader.quotes(proxies + heavy, start=start, end=ctx.now), cfg.get("extended_sources"), ctx.now, pcfg
    )
    stale_h = float(cfg.get("stale_after_hours", 2))
    aged = {s: _age(latest[s], ctx) for s in latest}
    fresh = {s: r for s, r in latest.items() if aged[s] is not None and aged[s] <= stale_h}
    old_quotes = {s: r for s, r in latest.items() if s not in fresh}
    latest = fresh
    # Index proxies that are not measured now, by name: a stale QQQ at -3% beside a fresh flat SPY must not read as
    # a silent CALM (review of #2415, F5).
    dropped: list[str] = []
    for s in proxies:
        if s in latest:
            continue
        if s in old_quotes:
            m0 = _move(old_quotes[s])
            dropped.append(
                f"{s}{f' {m0:+.1f}%' if m0 is not None else ''} at {_et_label(old_quotes[s].get('as_of'))} is "
                f"{aged[s]:.1f} market hours old (limit {stale_h:g}h)"
            )
        elif s in unproven:
            r0, why = unproven[s]
            dropped.append(f"{s} {r0.get('session')} {_et_label(r0.get('as_of'))} ({r0.get('source')}): {why}")
        else:
            dropped.append(f"{s}: no extended-session quote")
    shock = (ctx.extras or {}).get("opening_shock") or {}
    moves = {s: _move(latest[s]) for s in proxies if s in latest and _move(latest[s]) is not None}
    try:
        gaps = _gap_moves(ctx, cfg, proxies)
    except Exception as exc:  # noqa: BLE001 — the gap proxy failing must not blank the live-quote evidence
        print(f"market_risk: extended_hours gap proxy failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        gaps = {}
    if not moves and not shock.get("shock") and not gaps:
        return unknown(
            CATEGORY,
            ctx.now,
            ("no proven extended-session print for the index proxies: " + "; ".join(dropped))[:400]
            + "; no opening print"
            + (
                f"; market_quotes_extended: {err}"
                if (err := getattr(ctx.reader, "extended_quotes_error", None))
                else ""
            ),
        )
    warn, stress = float(cfg.get("warn_pct", -0.75)), float(cfg.get("stress_pct", -1.5))
    worst_sym = min(moves, key=moves.get) if moves else None
    worst = moves[worst_sym] if worst_sym else 0.0
    evidence = [
        Evidence(
            label=f"{s} {latest[s].get('session') or 'extended'} move vs {latest[s].get('reference') or 'previous close'}",
            value=round(m, 2),
            as_of=latest[s].get("as_of"),
            source=str(latest[s].get("source") or "market_quotes"),
            detail=f"{m:+.1f}%"
            + (f" vs {latest[s]['reference_date']} close" if latest[s].get("reference_date") else "")
            + f" ({_et_label(latest[s].get('as_of'))}, {aged[s]:.1f}h old)",
        )
        for s, m in sorted(moves.items(), key=lambda kv: kv[1])
    ]
    hw_cut = float(cfg.get("heavyweight_stress_pct", -8))
    big = []
    for s in heavy:
        m = _move(latest[s]) if s in latest else None
        if m is not None and m <= hw_cut:
            big.append(f"{s} {m:+.0f}%")
            evidence.append(
                Evidence(
                    label=f"{s} extended-session move",
                    value=round(m, 2),
                    as_of=latest[s].get("as_of"),
                    source="market_quotes",
                    detail=f"{m:+.1f}%",
                )
            )
    if shock.get("shock"):
        evidence.append(
            Evidence(
                label="opening_shock",
                value={"class": shock.get("class"), "shock": True},
                as_of=ctx.now.isoformat(),
                source="opening_shock",
                detail="panic open",
            )
        )
        state, score = "STRESS", 100.0
    elif worst <= stress:
        state, score = "STRESS", min(100.0, 75.0 + 25.0 * (worst - stress) / stress)
    elif worst <= warn:
        state, score = "WARN", 40.0 + 35.0 * (worst - warn) / (stress - warn)
    else:
        state, score = "CALM", max(0.0, 40.0 * worst / warn) if worst < 0 else 0.0
    gap_state = None
    if gaps:
        gc = cfg.get("gap_proxy") or {}
        gsym = min(gaps, key=lambda k: gaps[k]["gap_pct"])
        g = gaps[gsym]
        for s2, gv in sorted(gaps.items(), key=lambda kv: kv[1]["gap_pct"]):
            evidence.append(
                Evidence(
                    label=f"{s2} opening gap vs previous close",
                    value={"gap_pct": round(gv["gap_pct"], 2), "gap_atr": round(gv["gap_atr"], 2)},
                    as_of=gv["as_of"],
                    source="session_opens",
                    detail=f"{gv['gap_pct']:+.1f}% ({gv['gap_atr']:+.1f} ATR)",
                )
            )
        if g["gap_pct"] <= stress or g["gap_atr"] <= -float(gc.get("stress_atr", 1.5)):
            depth = max(g["gap_pct"] / stress, g["gap_atr"] / -float(gc.get("stress_atr", 1.5)))
            gap_state, gap_score = "STRESS", min(100.0, 75.0 + 25.0 * (depth - 1.0))
        elif g["gap_pct"] <= warn or g["gap_atr"] <= -float(gc.get("warn_atr", 0.75)):
            gap_state, gap_score = "WARN", 50.0
        else:
            gap_state, gap_score = "CALM", 0.0
        if not moves and not shock.get("shock") or (gap_score > score):
            state, score = gap_state, gap_score
            worst_sym, worst = gsym, g["gap_pct"]
    head = f"{worst_sym} {worst:+.1f}% extended" if worst_sym else "opening shock"
    if gap_state is not None and worst_sym in gaps and worst == gaps[worst_sym]["gap_pct"]:
        head = f"{worst_sym} opened {worst:+.1f}% ({gaps[worst_sym]['gap_atr']:+.1f} ATR) vs previous close"
    if big:
        head += " · " + ", ".join(big[:3])
    if shock.get("shock"):
        head = "PANIC OPEN · " + head
    if dropped and (moves or gaps):
        head += " · not measured: " + "; ".join(dropped)
        evidence.extend(
            Evidence(label="index proxy not measured", value=None, as_of=None, source="market_quotes", detail=d)
            for d in dropped
        )
    observed = max(
        [str(latest[s].get("as_of")) for s in latest] + [str(g["as_of"]) for g in gaps.values()],
        default=ctx.now.isoformat(),
    )
    if gaps and not latest:
        stale_h = float((cfg.get("gap_proxy") or {}).get("stale_after_hours", 7))
    return CategoryObservation(
        category=CATEGORY,
        state=state,
        score=round(score, 1),
        observed_at=observed,
        headline=head,
        evidence=tuple(evidence),
        stale_after_hours=stale_h,
    )
