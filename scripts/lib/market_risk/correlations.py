"""Correlation anomaly engine (DSN-20261031-market-risk-engine §5.6, P2-T5).

Rolling ``window``-session correlations of daily returns for configured pairs, compared with their own trailing
``lookback_sessions`` distribution. An anomaly is a current correlation more than ``z_anomaly`` standard deviations
from its mean, or a sign opposite to a clearly-signed mean (|mean| >= ``min_abs_mean_for_flip``) held for
``sign_flip_sessions`` consecutive sessions — e.g. SPY and VIX moving together, as on 10-29. Pure function of the
close series; no I/O.
"""

from __future__ import annotations

import math
from datetime import datetime
from statistics import mean, pstdev
from typing import Any


def _returns(series: list[tuple[datetime, float]]) -> dict[str, float]:
    out = {}
    for (_, a), (t, b) in zip(series, series[1:]):
        if a > 0 and b > 0:
            out[t.date().isoformat()] = math.log(b / a)
    return out


def _corr(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    mx, my = mean(x), mean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def rolling(a: list[tuple[datetime, float]], b: list[tuple[datetime, float]], window: int) -> list[tuple[str, float]]:
    ra, rb = _returns(a), _returns(b)
    days = sorted(set(ra) & set(rb))
    out = []
    for i in range(window, len(days) + 1):
        d = days[i - window : i]
        c = _corr([ra[k] for k in d], [rb[k] for k in d])
        if c is not None:
            out.append((d[-1], c))
    return out


def pair_state(a: list, b: list, cfg: dict[str, Any]) -> dict[str, Any]:
    roll = rolling(a, b, int(cfg["window"]))
    if len(roll) < int(cfg["min_sessions"]):
        return {"status": "UNKNOWN", "reason": f"{len(roll)} rolling values < {cfg['min_sessions']}"}
    hist = [c for _, c in roll[-int(cfg["lookback_sessions"]) :]]
    mu, sd = mean(hist), pstdev(hist)
    cur_day, cur = roll[-1]
    z = (cur - mu) / sd if sd else 0.0
    n = int(cfg["sign_flip_sessions"])
    flip = (
        abs(mu) >= float(cfg["min_abs_mean_for_flip"])
        and len(roll) >= n
        and all((c > 0) != (mu > 0) and c != 0 for _, c in roll[-n:])
    )
    anomaly = abs(z) >= float(cfg["z_anomaly"]) or flip
    return {
        "status": "ANOMALY" if anomaly else "NORMAL",
        "current": round(cur, 3),
        "mean": round(mu, 3),
        "z": round(z, 2),
        "sign_flip": flip,
        "as_of": cur_day,
        "sessions": len(roll),
    }


def anomalies(closes: dict[str, list[tuple[datetime, float]]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per configured pair: {pair, status ANOMALY|NORMAL|UNKNOWN, current, mean, z, sign_flip, as_of}."""
    out = []
    for p, q in cfg["pairs"]:
        if p not in closes or q not in closes:
            out.append({"pair": f"{p}~{q}", "status": "UNKNOWN", "reason": "series missing"})
            continue
        out.append({"pair": f"{p}~{q}", **pair_state(closes[p], closes[q], cfg)})
    return out
