"""Score Phase 1 alert decisions after the fact: MFE / MAE at 1, 5 and 15 minutes.

Deterministic. Reads the append-only alert journal, and for every decision (ALERT and VETO —
vetoes are scored too, so we learn what the vetoes cost) whose 15-minute window has closed and
is not yet scored, measures the best (MFE) and worst (MAE) move from the reference price in the
minute bars that START after the decision, in dollars, percent and R. Appends to
momentum_alerts_scored.jsonl. No order path; no LLM.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

try:
    from active_trader import momentum_alerts as ma
except ModuleNotFoundError:
    from scripts.active_trader import momentum_alerts as ma

CONTRACT = "active-trader-momentum-alert-score-v2"
WINDOWS_MIN = (1, 5, 15)

# v2 (audit 2026-10-05). v1 measured MFE from the trigger's fire price (`entry_ref`), which can be
# minutes old: XNDU's 09:55 time-to-buy was scored from $4.375 while you could only pay $4.43, and a
# move that hit the stop before +1R still counted as a hit. v2 adds `outcome`, measured from the
# price you could have paid when the alert went out (best ask, else last): which came first (stop
# or +1R), the best exit with hindsight, and a simple rule exit. The legacy windows are kept.
STOPPED, WORKED, SAME_BAR, NO_TOUCH, AT_OR_BELOW_STOP = "STOPPED", "WORKED", "SAME_BAR", "NO_TOUCH", "AT_OR_BELOW_STOP"


def _cfg():
    try:
        from active_trader import momentum_alerts_api as api
    except ModuleNotFoundError:
        from scripts.active_trader import momentum_alerts_api as api
    try:
        return api._alert_config()
    except Exception:  # noqa: BLE001
        return ma.AlertConfig()


def _f(b: Mapping[str, Any], *keys) -> Optional[float]:
    for k in keys:
        if b.get(k) is not None:
            try:
                return float(b[k])
            except (TypeError, ValueError):
                return None
    return None


def outcome(row: Mapping[str, Any], bars: Iterable[Mapping[str, Any]], *, touch_min: int,
            horizon_min: int) -> dict:
    """What would have happened had you acted on this decision at the alert. Bars must START at or
    after the alert, so nothing before the alert leaks in. A bar that touches both the stop and
    +1R counts as stopped (we cannot know the order inside a minute)."""
    c = row.get("candidate") or {}
    l2 = row.get("l2") or {}
    fill, src = (l2.get("best_ask"), "ask") if l2.get("best_ask") is not None else (c.get("last"), "last")
    stop = c.get("stop_ref")
    if fill is None or stop is None:
        return {"status": "NO_FILL_REF"}
    fill, stop, t0 = float(fill), float(stop), float(row["ts_epoch"])
    risk = fill - stop
    seq = sorted(((_bar_epoch(b), b) for b in bars), key=lambda x: x[0] or 0)
    seq = [(e, b) for e, b in seq if e is not None and t0 <= e < t0 + horizon_min * 60]
    out: dict[str, Any] = {"fill": fill, "fill_source": src, "stop": round(stop, 4),
                           "risk": round(risk, 4), "risk_pct": round(risk / fill * 100, 3) if fill else None,
                           "horizon_bars": len(seq)}
    if not seq:
        out["status"] = "NO_BARS"
        return out
    pct = lambda px: round((px - fill) / fill * 100, 3)          # noqa: E731
    rr = lambda px: round((px - fill) / risk, 2) if risk > 0 else None  # noqa: E731
    he, hb = max(seq, key=lambda x: (_f(x[1], "h", "high") or -1e18, -x[0]))
    hi = _f(hb, "h", "high")
    out["best_exit"] = {"price": hi, "ts_epoch": he, "pct": pct(hi), "r": rr(hi),
                        "min_after": round((he - t0) / 60, 1)}
    if risk <= 0:
        out["status"] = AT_OR_BELOW_STOP
        out["result"] = AT_OR_BELOW_STOP
        return out
    result, touch_at = NO_TOUCH, None
    for e, b in seq:
        if e >= t0 + touch_min * 60:
            break
        lo, h = _f(b, "l", "low"), _f(b, "h", "high")
        hit_s = lo is not None and lo <= stop
        hit_t = h is not None and h >= fill + risk
        if hit_s or hit_t:
            result = SAME_BAR if (hit_s and hit_t) else (STOPPED if hit_s else WORKED)
            touch_at = e
            break
    out["result"], out["first_touch_epoch"] = result, touch_at
    rule = None
    for i, (e, b) in enumerate(seq):
        lo, cl = _f(b, "l", "low"), _f(b, "c", "close")
        if lo is not None and lo <= stop:
            rule = (stop, e, "stop hit"); break
        if i > 0 and cl is not None and (_f(seq[i - 1][1], "l", "low") or -1e18) > cl:
            rule = (cl, e, "closed below prior bar low"); break
        if e >= t0 + (touch_min - 1) * 60 and cl is not None:
            rule = (cl, e, f"{touch_min}-min time stop"); break
    if rule:
        out["rule_exit"] = {"price": rule[0], "ts_epoch": rule[1], "reason": rule[2], "pct": pct(rule[0]),
                            "r": rr(rule[0]), "min_after": round((rule[1] - t0) / 60, 1)}
    out["status"] = "SCORED"
    return out


def decision_id(row: Mapping[str, Any]) -> str:
    c = row.get("candidate") or {}
    return f"{row.get('run_id')}:{c.get('symbol')}:{row.get('kind')}:{row.get('ts_epoch')}"


def _bar_epoch(b: Mapping[str, Any]) -> Optional[float]:
    t = b.get("t")
    if t is None:
        return None
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None


def _hl(b: Mapping[str, Any]) -> tuple[Optional[float], Optional[float]]:
    def g(*keys):
        for k in keys:
            if b.get(k) is not None:
                try:
                    return float(b[k])
                except (TypeError, ValueError):
                    return None
        return None
    return g("h", "high", "H"), g("l", "low", "L")


def score_row(row: Mapping[str, Any], bars: Iterable[Mapping[str, Any]]) -> dict:
    c = row.get("candidate") or {}
    ref = c.get("entry_ref") if c.get("entry_ref") is not None else c.get("last")
    r = row.get("r_dollars")
    t0 = float(row["ts_epoch"])
    out: dict[str, Any] = {"contract": CONTRACT, "decision_id": decision_id(row),
                           "symbol": c.get("symbol"), "kind": row.get("kind"),
                           "verdict": row.get("verdict"), "veto_reasons": row.get("veto_reasons"),
                           "ref_price": ref, "r_dollars": r, "windows": {}}
    if ref is None:
        out["status"] = "NO_REFERENCE_PRICE"
        return out
    ref = float(ref)
    after = sorted(((_bar_epoch(b), b) for b in bars), key=lambda x: x[0] or 0)
    after = [(e, b) for e, b in after if e is not None and e >= t0]
    for w in WINDOWS_MIN:
        win = [b for e, b in after if e < t0 + w * 60]
        highs = [h for h, _ in map(_hl, win) if h is not None]
        lows = [lo for _, lo in map(_hl, win) if lo is not None]
        if not highs or not lows:
            out["windows"][f"{w}m"] = {"status": "NO_BARS"}
            continue
        mfe, mae = max(highs) - ref, ref - min(lows)
        out["windows"][f"{w}m"] = {
            "mfe": round(mfe, 4), "mae": round(mae, 4),
            "mfe_pct": round(mfe / ref * 100, 3), "mae_pct": round(mae / ref * 100, 3),
            "mfe_r": round(mfe / r, 2) if r else None, "mae_r": round(mae / r, 2) if r else None,
            "bars": len(win)}
    cfg = _cfg()
    out["outcome"] = outcome(row, bars, touch_min=int(cfg.score_touch_min), horizon_min=int(cfg.score_horizon_min))
    out["status"] = "SCORED"
    return out


def score_pending(bars_fn: Callable[[str, str], list], *, now: float,
                  journal: Optional[Path] = None, scored: Optional[Path] = None) -> list[dict]:
    """Score every journal decision whose 15-minute window closed (plus 2 min of bar lag)."""
    d = ma.journal_dir()
    journal = journal or d / "momentum_alerts.jsonl"
    scored = scored or d / "momentum_alerts_scored.jsonl"
    if not journal.exists():
        return []
    done = set()
    if scored.exists():
        for line in scored.read_text(encoding="utf-8").splitlines():
            try:
                prev = json.loads(line)
                if prev.get("contract") == CONTRACT:   # v1 rows are re-scored once under v2
                    done.add(prev["decision_id"])
            except Exception:  # noqa: BLE001
                continue
    new: list[dict] = []
    cache: dict[tuple, list] = {}
    wait_min = int(_cfg().score_horizon_min)
    for line in journal.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if row.get("contract") != ma.CONTRACT or decision_id(row) in done:
            continue
        if now - float(row.get("ts_epoch") or now) < (max(max(WINDOWS_MIN), wait_min) + 2) * 60:
            continue
        c = row.get("candidate") or {}
        key = (c.get("symbol"), c.get("session_date"))
        if key not in cache:
            try:
                cache[key] = bars_fn(*key) or []
            except Exception:  # noqa: BLE001
                cache[key] = []
        res = score_row(row, cache[key])
        new.append(res)
        done.add(res["decision_id"])
    if new:
        scored.parent.mkdir(parents=True, exist_ok=True)
        with scored.open("a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r, default=str, sort_keys=True) + "\n")
    return new


def outcome_summary(scored_rows: Iterable[Mapping[str, Any]]) -> dict:
    """v2 track record by kind:verdict: WORKED (+1R from the price you could pay, before the stop),
    STOPPED (stop first, or both in the same minute), NO_TOUCH, AT_OR_BELOW_STOP, plus the average
    best and rule exits in percent."""
    agg: dict[str, dict[str, Any]] = {}
    for r in scored_rows:
        o = r.get("outcome") or {}
        res = o.get("result")
        if r.get("status") != "SCORED" or not res:
            continue
        k = f"{r.get('kind')}:{r.get('verdict')}"
        a = agg.setdefault(k, {"n": 0, WORKED: 0, STOPPED: 0, NO_TOUCH: 0, AT_OR_BELOW_STOP: 0,
                               "_best": [], "_rule": []})
        a["n"] += 1
        a[STOPPED if res == SAME_BAR else res] += 1
        if (o.get("best_exit") or {}).get("pct") is not None:
            a["_best"].append(o["best_exit"]["pct"])
        if (o.get("rule_exit") or {}).get("pct") is not None:
            a["_rule"].append(o["rule_exit"]["pct"])
    for a in agg.values():
        b, ru = a.pop("_best"), a.pop("_rule")
        a["worked_rate"] = round(a[WORKED] / a["n"], 3) if a["n"] else None
        a["avg_best_exit_pct"] = round(sum(b) / len(b), 3) if b else None
        a["avg_rule_exit_pct"] = round(sum(ru) / len(ru), 3) if ru else None
    return agg


def precision_summary(scored_rows: Iterable[Mapping[str, Any]], *, window: str = "5m",
                      hit_r: float = 1.0) -> dict:
    """LEGACY (v1): share of decisions whose MFE from the fire price reached `hit_r` R within the
    window, regardless of whether the stop was hit first. Overstates results; kept for comparison.
    Use outcome_summary."""
    agg: dict[str, dict[str, int]] = {}
    for r in scored_rows:
        if r.get("status") != "SCORED":
            continue
        w = (r.get("windows") or {}).get(window) or {}
        if w.get("mfe_r") is None:
            continue
        k = f"{r.get('kind')}:{r.get('verdict')}"
        a = agg.setdefault(k, {"n": 0, "hit": 0})
        a["n"] += 1
        a["hit"] += 1 if w["mfe_r"] >= hit_r else 0
    return {k: {**v, "precision": round(v["hit"] / v["n"], 3) if v["n"] else None} for k, v in agg.items()}
