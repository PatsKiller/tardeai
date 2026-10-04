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

CONTRACT = "active-trader-momentum-alert-score-v1"
WINDOWS_MIN = (1, 5, 15)


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
                done.add(json.loads(line)["decision_id"])
            except Exception:  # noqa: BLE001
                continue
    new: list[dict] = []
    cache: dict[tuple, list] = {}
    for line in journal.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if row.get("contract") != ma.CONTRACT or decision_id(row) in done:
            continue
        if now - float(row.get("ts_epoch") or now) < (max(WINDOWS_MIN) + 2) * 60:
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


def precision_summary(scored_rows: Iterable[Mapping[str, Any]], *, window: str = "5m",
                      hit_r: float = 1.0) -> dict:
    """Share of decisions whose MFE reached `hit_r` R within the window, split by kind and
    verdict, so the precision of alerts and the cost of vetoes are both visible."""
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
