"""WP6 of SPEC_MARKET_EVENT_REENTRY_20261107 (LQ-20261107-339): what happened to a candidate after each signal.

Pure functions. No database, no network, no clock: the caller hands in the episode, the candidate rows, the daily closes
and "today". That keeps the arithmetic provable on synthetic fixtures. Advisory telemetry only -- nothing here sizes,
orders or touches a broker, and nothing here uses an LLM.

Conventions (all stated once, here):

* A *session* is an exchange session from the injected calendar. The *anchor session* of a signal is the most recent
  session whose close is at or before ``signal_at`` (baseline: the baseline date itself). ``ret_N`` is the percent
  return of the Nth session close after the anchor versus the signal's ``price``.
* ``None`` means NOT OBSERVABLE (horizon not reached, or no close recorded for that session). It is never turned into
  0, and a scorecard counts it separately (``n_observed``) instead of averaging it in.
* Closes are Finviz-sourced (``ticker_prices`` source='finviz'); the caller filters. This module does not fetch.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HORIZONS = (5, 20, 60)
SIGNALS = ("baseline", "READY_t1", "READY_t2", "READY_t3")
CLOSE = time(16, 0)
# Below these the Friday check reports "insufficient" rather than a verdict: a weekend effect read off two
# Fridays is an anecdote, not a test.
MIN_FRIDAYS = 3
MIN_PAIRS = 10

Closes = Mapping[str, Mapping[date, float]]  # symbol -> {session date: close}


def weekday_calendar(start: date, end: date, holidays: Iterable[date] = ()) -> list[date]:
    """Mon-Fri sessions in [start, end] minus ``holidays``. Test/fallback calendar."""
    hol = set(holidays)
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in hol:
            out.append(d)
        d += timedelta(days=1)
    return out


def xnys_sessions(start: date, end: date) -> list[date]:
    """NYSE sessions from exchange_calendars (project venv). Raises ImportError if unavailable -- the caller decides."""
    import exchange_calendars as xc  # noqa: PLC0415

    cal = xc.get_calendar("XNYS")
    return [s.date() for s in cal.sessions_in_range(start.isoformat(), end.isoformat())]


def anchor_session(signal_at: datetime, sessions: Sequence[date]) -> date | None:
    """Most recent session whose close is at or before ``signal_at``; None if the calendar starts later."""
    at = signal_at.astimezone(ET) if signal_at.tzinfo else signal_at.replace(tzinfo=ET)
    best = None
    for s in sessions:
        if datetime.combine(s, CLOSE, tzinfo=ET) <= at:
            best = s
        else:
            break
    return best


def nth_session_after(anchor: date, n: int, sessions: Sequence[date]) -> date | None:
    try:
        i = list(sessions).index(anchor)
    except ValueError:
        return None
    j = i + n
    return sessions[j] if j < len(sessions) else None


def pct(new: float, old: float) -> float | None:
    if old is None or new is None or old <= 0:
        return None
    return round((new / old - 1.0) * 100.0, 4)


def returns_for(price: float, anchor: date, symbol_closes: Mapping[date, float], sessions: Sequence[date],
                today: date, horizons: Sequence[int] = HORIZONS) -> dict[str, float | None]:
    """ret_<N> for each horizon. A target session after ``today`` or without a close stays None."""
    out: dict[str, float | None] = {}
    for n in horizons:
        tgt = nth_session_after(anchor, n, sessions)
        close = symbol_closes.get(tgt) if tgt and tgt <= today else None
        out[f"ret_{n}"] = pct(close, price) if close is not None else None
    return out


def ready_stamps(plan: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Tranche stamps WP3 writes into market_event_candidates.plan.

    Contract (WP3 must write it; reported to the lead): ``plan["tranches"] = [{"tranche": 1|2|3,
    "ready_at": ISO-8601 with offset, "price": number|null}, ...]``. Returns {"READY_t1": {...}, ...} for well-formed
    entries only; a malformed entry is skipped, never repaired.
    """
    out: dict[str, dict[str, Any]] = {}
    for t in (plan or {}).get("tranches") or []:
        if not isinstance(t, Mapping):
            continue
        try:
            n = int(t.get("tranche"))
            at = datetime.fromisoformat(str(t.get("ready_at")))
        except (TypeError, ValueError):
            continue
        if n in (1, 2, 3) and at.tzinfo is not None:
            px = t.get("price")
            out[f"READY_t{n}"] = {"signal_at": at, "price": float(px) if isinstance(px, (int, float)) and px > 0 else None}
    return out


def build_signals(episode: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]], closes: Closes,
                  sessions: Sequence[date], now: datetime) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Signal rows for one episode (entry fields only; returns are filled by :func:`score_rows`).

    Returns (rows, skipped) where skipped counts every candidate/signal that could not be recorded, by reason --
    a candidate dropped silently would read as "no signal".
    """
    rows: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    eid = episode["episode_id"]
    base_date = episode.get("baseline_date")
    for c in candidates:
        sym = c["symbol"]
        sc = closes.get(sym, {})
        if base_date:
            px, src = sc.get(base_date), "finviz_close"
            if px is None and c.get("baseline_price"):
                px, src = float(c["baseline_price"]), "candidate_baseline_price"
            if px:
                rows.append({"episode_id": eid, "symbol": sym, "signal": "baseline",
                             "signal_at": datetime.combine(base_date, CLOSE, tzinfo=ET), "anchor_session": base_date,
                             "price": float(px), "price_source": src, "signal_basis": "baseline_close"})
            else:
                skip("baseline_no_price")
        else:
            skip("episode_without_baseline_date")
        stamps = ready_stamps(c.get("plan"))
        if not stamps and c.get("state") in ("READY", "ENTERED"):
            # WP3 has not stamped a tranche: record our own observation time, labelled as such.
            stamps = {"READY_t1": {"signal_at": now, "price": None}}
            basis = "first_seen"
        else:
            basis = "plan_stamp"
        for sig, st in stamps.items():
            anchor = anchor_session(st["signal_at"], sessions)
            if anchor is None:
                skip("ready_before_calendar")
                continue
            px, src = st["price"], "plan_price"
            if px is None:
                px, src = sc.get(anchor), "finviz_close_anchor"
            if px is None and basis == "first_seen" and c.get("last_price"):
                px, src = float(c["last_price"]), "candidate_last_price"
            if not px:
                skip("ready_no_price")
                continue
            rows.append({"episode_id": eid, "symbol": sym, "signal": sig, "signal_at": st["signal_at"],
                         "anchor_session": anchor, "price": float(px), "price_source": src, "signal_basis": basis})
    return rows, skipped


def score_rows(rows: Sequence[Mapping[str, Any]], closes: Closes, sessions: Sequence[date], today: date) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        rets = returns_for(r["price"], r["anchor_session"], closes.get(r["symbol"], {}), sessions, today)
        out.append({**r, **rets})
    return out


def _agg(vals: Sequence[float | None]) -> dict[str, Any]:
    obs = [v for v in vals if v is not None]
    n = len(vals)
    if not obs:
        return {"n": n, "n_observed": 0, "median": None, "mean": None, "hit_rate": None, "best": None, "worst": None}
    return {"n": n, "n_observed": len(obs), "median": round(statistics.median(obs), 4),
            "mean": round(statistics.fmean(obs), 4), "hit_rate": round(sum(v > 0 for v in obs) / len(obs), 4),
            "best": max(obs), "worst": min(obs)}


def scorecard(scored: Sequence[Mapping[str, Any]], episode_id: str | None = None) -> dict[str, Any]:
    """Per-episode scorecard: for each signal x horizon, n / n_observed / median / mean / hit_rate / best / worst.

    ``edge_vs_baseline`` is the median READY return minus the median baseline return over the SAME symbols that have
    both observed (a paired comparison), or None when no symbol has both. It is a descriptive number, not a test.
    """
    rs = [r for r in scored if episode_id is None or r["episode_id"] == episode_id]
    card: dict[str, Any] = {"episode_id": episode_id, "signals": {}, "edge_vs_baseline": {}}
    for sig in SIGNALS:
        sr = [r for r in rs if r["signal"] == sig]
        card["signals"][sig] = {f"ret_{n}": _agg([r.get(f"ret_{n}") for r in sr]) for n in HORIZONS}
        card["signals"][sig]["symbols"] = len({r["symbol"] for r in sr})
    base = {r["symbol"]: r for r in rs if r["signal"] == "baseline"}
    for sig in SIGNALS[1:]:
        for n in HORIZONS:
            k = f"ret_{n}"
            diffs = [r[k] - base[r["symbol"]][k] for r in rs
                     if r["signal"] == sig and r["symbol"] in base and r.get(k) is not None and base[r["symbol"]].get(k) is not None]
            card["edge_vs_baseline"][f"{sig}.{k}"] = (
                {"n_paired": len(diffs), "median_diff": round(statistics.median(diffs), 4)} if diffs
                else {"n_paired": 0, "median_diff": None})
    return card


def friday_check(closes: Closes, symbols: Sequence[str], sessions: Sequence[date], window_start: date,
                 window_end: date) -> dict[str, Any]:
    """Spec 4.7: does a Friday dump before the weekend recover on Mon/Tue?

    For every Friday session F in the window that has a following Monday session M and Tuesday session T:
      thu_to_fri (the dump itself), fri_to_mon, fri_to_tue -- per symbol, percent.
    Control: the same 1- and 2-session forward returns started on every NON-Friday session in the window, so the
    Friday numbers are read against what these names do on an ordinary day. Reports medians, positive share and the
    pair counts; ``verdict`` is "insufficient" below MIN_FRIDAYS Fridays or MIN_PAIRS pairs. It never says "confirmed".
    """
    win = [s for s in sessions if window_start <= s <= window_end]
    idx = {s: i for i, s in enumerate(sessions)}

    def ret(sym: str, a: date, b: date) -> float | None:
        c = closes.get(sym, {})
        return pct(c[b], c[a]) if a in c and b in c else None

    fri_rows: list[dict[str, Any]] = []
    fridays_used = 0
    for f in (s for s in win if s.weekday() == 4):
        i = idx[f]
        if i + 2 >= len(sessions) or i < 1:
            continue
        thu, mon, tue = sessions[i - 1], sessions[i + 1], sessions[i + 2]
        got = False
        for sym in symbols:
            r = {"friday": f.isoformat(), "symbol": sym, "thu_to_fri": ret(sym, thu, f),
                 "fri_to_mon": ret(sym, f, mon), "fri_to_tue": ret(sym, f, tue)}
            if r["fri_to_mon"] is not None or r["fri_to_tue"] is not None:
                fri_rows.append(r)
                got = True
        fridays_used += got
    ctrl_1, ctrl_2 = [], []
    for s in win:
        if s.weekday() == 4:
            continue
        i = idx[s]
        for sym in symbols:
            if i + 1 < len(sessions):
                v = ret(sym, s, sessions[i + 1])
                if v is not None:
                    ctrl_1.append(v)
            if i + 2 < len(sessions):
                v = ret(sym, s, sessions[i + 2])
                if v is not None:
                    ctrl_2.append(v)

    def col(k: str) -> list[float]:
        return [r[k] for r in fri_rows if r[k] is not None]

    def summ(v: Sequence[float]) -> dict[str, Any]:
        return {"n": len(v), "median": round(statistics.median(v), 4) if v else None,
                "share_positive": round(sum(x > 0 for x in v) / len(v), 4) if v else None}

    fm, ft = col("fri_to_mon"), col("fri_to_tue")
    enough = fridays_used >= MIN_FRIDAYS and len(fm) >= MIN_PAIRS
    return {"window": [window_start.isoformat(), window_end.isoformat()], "fridays_used": fridays_used,
            "thu_to_fri": summ(col("thu_to_fri")), "fri_to_mon": summ(fm), "fri_to_tue": summ(ft),
            "control_1_session": summ(ctrl_1), "control_2_session": summ(ctrl_2),
            "verdict": "insufficient" if not enough else "measured",
            "note": ("fewer than %d Fridays or %d pairs: descriptive only" % (MIN_FRIDAYS, MIN_PAIRS)) if not enough
            else "descriptive comparison against non-Friday control, not a significance test",
            "rows": fri_rows}
