"""Split / corporate-action guard for daily close series (LIVEFIX-S, 2026-11-06).

Why: the quote-derived closes in ``reader.PgReader.daily_bars`` are NOT split-adjusted (``market_quotes`` carries the
broker's ``prev_close`` as printed that day). SOXX split about 3:1 on 2026-11-05: its closes went 451.20 -> 130.935
-> 136.71 while SMH, the other semis ETF, fell a real ~11.5%. The semis group then showed r5 -42%, dd20 -49%, STRESS/RED.

Rule (stated, thresholds in ``config/market_risk_policy.yaml`` ``corporate_actions.split_guard``):

* A session is a **candidate** only when its one-session close ratio ``q = close(D) / close(D-1)`` moves at least
  ``candidate_min_move_pct``. A real -12% crash day is never a candidate.
* For each configured split ratio ``k`` (and its reverse ``1/k`` when ``include_reverse``) the **residual** move is
  ``q * k / peer_ratio - 1``, where ``peer_ratio`` is the benchmark's own close ratio over the same two dates (the
  market move that day; 1.0 when the benchmark has no closes for them). A ratio **fits** when
  ``|residual| <= max_residual_move_pct``.
* No ratio fits: a genuine move, left alone. Exactly one fits AND each of the next ``confirm_sessions`` closes stays
  within ``max_residual_move_pct`` of the new level: a split, and every earlier row is back-adjusted (prices divided
  by ``k``) and marked ``adjusted_for_split``. Anything else -- several ratios fit, the jump reverts (a bad print), or
  no later session exists yet to confirm it -- is **ambiguous**: the symbol's series is a data gap with a stated
  reason, never a guessed number.

Known limit (documented, not detectable from closes alone): a genuine one-session move that equals a split ratio
(a stock that halves on the day, and stays there) is indistinguishable from a 2:1 split and would be adjusted.

Pure functions; no I/O. Advisory data plumbing only (``MBI_BEHAVIOR = 0``).
"""

from __future__ import annotations

from typing import Any, Callable

PRICE_FIELDS = ("open", "high", "low", "close")
REQUIRED_KEYS = (
    "candidate_min_move_pct",
    "split_ratios",
    "max_residual_move_pct",
    "confirm_sessions",
)


def config(block: dict[str, Any] | None) -> dict[str, Any] | None:
    """The validated guard config, or ``None`` when the block is absent or ``enabled`` is false. A present but
    incomplete block raises: a half-configured guard must not silently pass unadjusted splits through."""
    if not block or not block.get("enabled", False):
        return None
    missing = [k for k in REQUIRED_KEYS if block.get(k) is None]
    if missing:
        raise ValueError(f"corporate_actions.split_guard: missing {missing}")
    ratios = [float(x) for x in block["split_ratios"]]
    if not ratios or any(x <= 1.0 for x in ratios):
        raise ValueError("corporate_actions.split_guard.split_ratios: each ratio must be > 1 (forward split k:1)")
    factors = [(k, f"{_fmt(k)}:1") for k in ratios]
    if block.get("include_reverse", True):
        factors += [(1.0 / k, f"1:{_fmt(k)}") for k in ratios]
    cand = float(block["candidate_min_move_pct"]) / 100.0
    tol = float(block["max_residual_move_pct"]) / 100.0
    if tol >= cand:
        # a residual allowance as wide as the candidate floor would let an adjusted series still carry a "candidate"
        # sized move, and makes the fit test meaningless
        raise ValueError("corporate_actions.split_guard: max_residual_move_pct must be below candidate_min_move_pct")
    return {
        "benchmark": str(block.get("benchmark") or "SPY").upper(),
        "candidate": cand,
        "tolerance": tol,
        "confirm": int(block["confirm_sessions"]),
        "exempt_prefixes": tuple(str(x) for x in (block.get("exempt_prefixes") or [])),
        "exempt_symbols": frozenset(str(x).upper() for x in (block.get("exempt_symbols") or [])),
        "factors": factors,
    }


def exempt(symbol: str, cfg: dict[str, Any]) -> bool:
    """Series that never split: indexes (``^VIX`` rose 62.7% on 2026-11-05, a real move that fits 1:1.5 and 1:2)."""
    sym = str(symbol).upper()
    return sym in cfg["exempt_symbols"] or any(sym.startswith(p) for p in cfg["exempt_prefixes"])


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def guard_series(
    rows: list[dict[str, Any]],
    cfg: dict[str, Any],
    peer: Callable[[], dict[str, float] | None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Check one symbol's rows (oldest first) for one-session split jumps.

    Returns ``(rows, report)``. ``report`` is ``{"adjustments": [...]}`` (possibly empty; ``rows`` then carry the
    back-adjusted prices) or ``{"gap": reason, "adjustments": [...]}`` (``rows`` returned unchanged; the caller must
    not use them). ``peer`` is called at most once, lazily, only when a candidate jump exists, and returns the
    benchmark's closes by ISO date (or ``None``)."""
    pts = [(i, _num(r.get("close"))) for i, r in enumerate(rows)]
    pts = [(i, c) for i, c in pts if c is not None]
    report: dict[str, Any] = {"adjustments": []}
    if len(pts) < 2:
        return rows, report
    peer_closes: dict[str, float] | None = None
    peer_loaded = False
    splits: list[tuple[int, float]] = []  # (row index of the first post-split row, factor)
    for n in range(1, len(pts)):
        (ia, a), (ib, b) = pts[n - 1], pts[n]
        q = b / a
        if abs(q - 1.0) < cfg["candidate"]:
            continue
        if not peer_loaded:
            peer_closes = peer() if peer else None
            peer_loaded = True
        da, db = str(rows[ia].get("date"))[:10], str(rows[ib].get("date"))[:10]
        pa, pb = (peer_closes or {}).get(da), (peer_closes or {}).get(db)
        peer_ratio = (pb / pa) if (pa and pb) else None
        base = peer_ratio or 1.0
        fits = [(k, label, q * k / base - 1.0) for k, label in cfg["factors"] if abs(q * k / base - 1.0) <= cfg["tolerance"]]
        if not fits:
            continue  # a genuine large move: no split ratio explains it
        where = f"{da} -> {db} close ratio {q:.4f}"
        if len(fits) > 1:
            labels = " and ".join(lbl for _, lbl, _ in fits)
            report["gap"] = f"ambiguous corporate action: {where} fits {labels} splits; series excluded"
            return rows, report
        k, label, resid = fits[0]
        after = pts[n + 1 : n + 1 + cfg["confirm"]]
        if len(after) < cfg["confirm"]:
            report["gap"] = (
                f"unconfirmed corporate action: {where} fits a {label} split but no later session confirms the new "
                f"level yet; series excluded"
            )
            return rows, report
        drift = [c / b - 1.0 for _, c in after]
        if any(abs(x) > cfg["tolerance"] for x in drift):
            report["gap"] = (
                f"reverted jump: {where} fits a {label} split but the next close(s) left the new level "
                f"({', '.join(f'{x * 100:+.1f}%' for x in drift)}); likely a bad print; series excluded"
            )
            return rows, report
        splits.append((ib, k))
        report["adjustments"].append(
            {
                "date": db,
                "ratio": label,
                "factor": round(k, 6),
                "raw_close_ratio": round(q, 6),
                "peer_move_pct": None if peer_ratio is None else round((peer_ratio - 1.0) * 100.0, 2),
                "residual_move_pct": round(resid * 100.0, 2),
                "confirmed_by": [str(rows[i].get("date"))[:10] for i, _ in after],
            }
        )
    if not splits:
        return rows, report
    out = []
    for i, r in enumerate(rows):
        cum = 1.0
        for start, k in splits:
            if i < start:
                cum *= k
        if cum == 1.0:
            out.append(r)
            continue
        nr = dict(r)
        for f in PRICE_FIELDS:
            v = _num(nr.get(f))
            if v is not None:
                nr[f] = v / cum
        nr["adjusted_for_split"] = round(cum, 6)
        nr["source"] = f"{nr.get('source') or 'unknown'}+split_adj:{_fmt(round(cum, 6))}"
        out.append(nr)
    return out, report
