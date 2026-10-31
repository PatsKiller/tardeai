"""Technical category: index and semiconductor trend damage from daily closes (DSN-20261031-market-risk-engine §5.1).

Sub-signals (points and thresholds in config/market_risk_policy.yaml ``technical``): drawdown from the 52-week and
20-day highs, losing streaks, a failed retest of a recent high, closes below the 50/200-day averages, and the
semiconductor month-to-date move. RCA: SOX lost 8 straight sessions into 10-16 and was -15% month to date; QQQ
retested its 10-21 high (725.59) on 10-28 and closed 2.7% lower on 10-29.
"""

from __future__ import annotations

from datetime import datetime

from scripts.lib.market_risk.categories import _marketdata as md
from scripts.lib.market_risk.contract import CategoryObservation, EvalContext, Evidence, unknown

CATEGORY = "technical"
SOURCE = "market_ohlcv_bars"


def _streak(closes: list[float]) -> int:
    n = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] < closes[i - 1]:
            n += 1
        else:
            break
    return n


def _failed_retest(series: list[tuple[datetime, float]], cfg: dict) -> tuple[float, float] | None:
    """(reference_high, close_drop_pct) when a close inside the retest window came within tolerance of the
    prior reference high and the latest close sits at least retest_fail_pct below it."""
    w, ref_n = int(cfg["retest_window_sessions"]), int(cfg["retest_reference_sessions"])
    if len(series) < w + ref_n:
        return None
    closes = [c for _, c in series]
    ref = max(closes[-(w + ref_n) : -w])
    window = closes[-w:]
    tol = ref * float(cfg["retest_tolerance_pct"]) / 100.0
    if not any(c >= ref - tol for c in window[:-1]):
        return None
    drop = md.pct(closes[-1], ref)
    return (ref, drop) if drop <= -float(cfg["retest_fail_pct"]) else None


def evaluate(ctx: EvalContext) -> CategoryObservation:
    cfg = ctx.policy[CATEGORY]
    rows = ctx.reader.daily_bars(cfg["symbols"], sessions=int(cfg["history_sessions"]), end=ctx.now)
    by = md.closes_by_symbol(rows)
    usable = {s: v for s, v in by.items() if len(v) >= int(cfg["min_sessions"])}
    if not usable:
        return unknown(CATEGORY, ctx.now, "no daily bars for the index symbols")
    newest = max(v[-1][0] for v in usable.values())
    if md.stale(newest, ctx.now, cfg["stale_after_hours"]):
        return unknown(CATEGORY, ctx.now, f"daily bars stale (newest {md.iso(newest)})")

    fired: dict[str, tuple[str, Evidence]] = {}  # one firing per sub-signal: the worst symbol

    def fire(key: str, sym: str, severity: float, ev: Evidence) -> None:
        cur = fired.get(key)
        if cur is None or severity > cur[1].value[1]:  # type: ignore[index]
            fired[key] = (key, Evidence(ev.label, (sym, severity), ev.as_of, ev.source, ev.detail))

    context: list[Evidence] = []
    for sym, series in sorted(usable.items()):
        closes = [c for _, c in series]
        last_t, last = series[-1]
        asof = md.iso(last_t)
        hi52 = max(closes[-252:])
        dd52 = md.pct(last, hi52)
        if dd52 <= -float(cfg["drawdown_52w_pct"]):
            fire(
                "drawdown_52w",
                sym,
                -dd52,
                Evidence("drawdown from 52-week high", None, asof, SOURCE, f"{sym} {dd52:.1f}% off 52w high"),
            )
        dd20 = md.pct(last, max(closes[-20:]))
        if dd20 <= -float(cfg["drawdown_20d_pct"]):
            fire(
                "drawdown_20d",
                sym,
                -dd20,
                Evidence("drawdown from 20-day high", None, asof, SOURCE, f"{sym} {dd20:.1f}% off 20d high"),
            )
        streak = _streak(closes)
        if streak >= int(cfg["losing_streak_sessions"]):
            fire(
                "losing_streak",
                sym,
                float(streak),
                Evidence("losing streak", None, asof, SOURCE, f"{sym} {streak} straight down sessions"),
            )
        rt = _failed_retest(series, cfg)
        if rt:
            fire(
                "failed_retest",
                sym,
                -rt[1],
                Evidence(
                    "failed retest of recent high",
                    None,
                    asof,
                    SOURCE,
                    f"{sym} failed retest of {rt[0]:.2f}, now {rt[1]:.1f}%",
                ),
            )
        d50, d200 = md.sma(closes, 50), md.sma(closes, 200)
        if d50 is not None and last < d50:
            fire(
                "below_dma50",
                sym,
                md.pct(d50, last),
                Evidence("close below 50-day average", None, asof, SOURCE, f"{sym} below 50-DMA {d50:.2f}"),
            )
        if d200 is not None and last < d200:
            fire(
                "below_dma200",
                sym,
                md.pct(d200, last),
                Evidence("close below 200-day average", None, asof, SOURCE, f"{sym} below 200-DMA {d200:.2f}"),
            )
        if sym in cfg["semis_symbols"]:
            month_start = [c for t, c in series if (t.year, t.month) < (last_t.year, last_t.month)]
            if month_start:
                mtd = md.pct(last, month_start[-1])
                context.append(Evidence("month-to-date change", round(mtd, 2), asof, SOURCE, f"{sym} MTD {mtd:.1f}%"))
                if mtd <= float(cfg["semis_mtd_pct"]):
                    fire(
                        "semis_mtd",
                        sym,
                        -mtd,
                        Evidence("semiconductor month-to-date", None, asof, SOURCE, f"{sym} {mtd:.1f}% month to date"),
                    )
        context.append(Evidence("last close", round(last, 2), asof, SOURCE, f"{sym} {last:.2f}"))

    fixed = [(k, Evidence(e.label, round(e.value[1], 2), e.as_of, e.source, e.detail)) for k, e in fired.values()]
    return md.observation(CATEGORY, cfg, fixed, context, newest, headline_prefix="Technical")
