"""GET /api/v3/active-trader/alerts — Phase 1 L2-confirmed scalp alert feed (read-only).

Reads the append-only decision journal, the scored ledger and the engine heartbeat that
scripts/active_trader/momentum_alert_pass writes into persistent state, plus the alert mode
from config/scalp_signal_engine.yaml. Pure read: never writes, never sends, no broker, no LLM.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

try:
    from active_trader import momentum_alerts as ma
    from active_trader import momentum_alert_scoring as ms
except ModuleNotFoundError:
    from scripts.active_trader import momentum_alerts as ma
    from scripts.active_trader import momentum_alert_scoring as ms

CONTRACT = "active-trader-alerts-feed-v1"
ET = ZoneInfo("America/New_York")
REPO = Path(__file__).resolve().parents[2]
TAIL_BYTES = 4_000_000          # journal tail read; a full session is far smaller
ENGINE_WINDOW_ET = ("09:30", "11:55")
L2_PROOF = {"source": "moomoo OpenD (quote context)", "levels_proven": 60,
            "proven_at": "2026-10-04", "compare": "Schwab NASDAQ_BOOK (5 levels, comparison only)"}


def _tail_lines(path: Path, max_bytes: int = TAIL_BYTES) -> list[str]:
    if not path.exists():
        return []
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()                      # drop the partial first line
        return fh.read().decode("utf-8", "replace").splitlines()


def _rows(path: Path) -> list[dict]:
    out = []
    for line in _tail_lines(path):
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out


def _alert_config() -> ma.AlertConfig:
    try:
        import yaml
        raw = yaml.safe_load((REPO / "config" / "scalp_signal_engine.yaml").read_text(encoding="utf-8")) or {}
        return ma.AlertConfig.from_mapping(raw.get("active_trader_alerts"))
    except Exception:  # noqa: BLE001 — unreadable config falls back to the code defaults (shadow)
        return ma.AlertConfig()


def _et(ts: Optional[float]) -> Optional[str]:
    return None if ts is None else datetime.fromtimestamp(ts, ET).isoformat(timespec="seconds")


def _compact(row: dict, score: Optional[dict]) -> dict:
    c = row.get("candidate") or {}
    l2, tape, cmp_ = row.get("l2") or {}, row.get("tape") or {}, row.get("l2_compare") or {}
    windows = (score or {}).get("windows") or {}
    return {
        "id": ms.decision_id(row), "at": _et(row.get("ts_epoch")), "ts_epoch": row.get("ts_epoch"),
        "symbol": c.get("symbol"), "kind": row.get("kind"), "verdict": row.get("verdict"),
        "veto_reasons": row.get("veto_reasons") or [], "sent": bool(row.get("sent")),
        "mode": row.get("mode"), "last": c.get("last"), "entry": c.get("entry_ref"), "stop": c.get("stop_ref"),
        "r": row.get("r_dollars"), "float_mm": c.get("float_mm"), "rvol": c.get("rvol"),
        "ign": c.get("ign"), "lane": c.get("lane"), "setup": c.get("setup_label") or c.get("setup_id"),
        "quote_age_s": row.get("quote_age_s"),
        "l2": {k: l2.get(k) for k in ("source", "levels", "depth_ratio", "spread_bps", "age_s", "ts_source")},
        "tape": {k: tape.get(k) for k in ("source", "prints", "buy_ratio", "age_s")} if tape else None,
        "l2_compare": {k: cmp_.get(k) for k in ("source", "levels", "depth_ratio", "spread_bps", "age_s")} if cmp_ else None,
        "score": {w: {k: v.get(k) for k in ("mfe_r", "mae_r", "mfe_pct", "mae_pct")} for w, v in windows.items()
                  if isinstance(v, dict) and v.get("mfe") is not None} or None,
    }


def alerts_snapshot(*, limit: int = 100, session_date: Optional[str] = None,
                    now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    d = ma.journal_dir()
    cfg = _alert_config()
    journal = [r for r in _rows(d / "momentum_alerts.jsonl") if r.get("contract") == ma.CONTRACT]
    day = session_date or datetime.fromtimestamp(now, ET).date().isoformat()
    today = [r for r in journal if (r.get("candidate") or {}).get("session_date") == day]
    latest_day = max(((r.get("candidate") or {}).get("session_date") or "" for r in journal), default=None)
    scored = {s.get("decision_id"): s for s in _rows(d / "momentum_alerts_scored.jsonl")}
    try:
        hb = json.loads((d / "momentum_alerts_heartbeat.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        hb = None
    alerts = [r for r in today if r.get("verdict") == ma.ALERT]
    vetoes = [r for r in today if r.get("verdict") == ma.VETO]
    reasons = Counter(x for r in vetoes for x in (r.get("veto_reasons") or []))
    all_scored = list(scored.values())
    hb_age = (now - float(hb["ts_epoch"])) if hb and hb.get("ts_epoch") else None
    return {
        "contract": CONTRACT, "authority": ma.AUTHORITY, "read_only": True,
        "generated_at": _et(now), "session_date": day, "latest_session_with_decisions": latest_day,
        "mode": cfg.mode, "delivery": "telegram" if cfg.mode == "send" else "journal only (shadow)",
        "engine": {"window_et": ENGINE_WINDOW_ET, "last_pass_at": _et(hb.get("ts_epoch")) if hb else None,
                   "last_pass_age_s": None if hb_age is None else round(hb_age),
                   "last_pass": (hb or {}).get("last_pass"), "symbols_scored": (hb or {}).get("symbols_scored")},
        "l2": L2_PROOF,
        "rules": {
            "armed": f"trigger state ARMED (or IGN lane {'/'.join(cfg.armed_lanes)}) + book bid/ask ≥ "
                     f"{cfg.min_depth_ratio_armed:g}x, spread ≤ {cfg.max_spread_bps:g} bps",
            "triggered": f"trigger fired ≤ {cfg.max_fire_age_s / 60:g} min ago + book bid/ask ≥ "
                         f"{cfg.min_depth_ratio_triggered:g}x, spread ≤ {cfg.max_spread_bps:g} bps + "
                         f"tape buys ≥ {cfg.min_buy_ratio * 100:.0f}% of last {cfg.tape_prints} prints + stop set",
            "freshness": f"quote ≤ {cfg.max_quote_age_s:g}s · book ≤ {cfg.max_book_age_s:g}s · tape ≤ {cfg.max_tape_age_s:g}s",
            "throttle": f"{cfg.cooldown_s / 60:g} min cooldown per symbol+kind · {cfg.max_alerts_per_hour}/hour",
        },
        "counts": {"triggered_alerts": sum(1 for r in alerts if r.get("kind") == ma.TRIGGERED),
                   "armed_alerts": sum(1 for r in alerts if r.get("kind") == ma.ARMED),
                   "vetoes": len(vetoes), "sent": sum(1 for r in today if r.get("sent")),
                   "decisions": len(today)},
        "veto_reasons": dict(reasons.most_common()),
        "precision": {w: ms.precision_summary(all_scored, window=w, hit_r=1.0) for w in ("1m", "5m", "15m")},
        "scored_total": len(all_scored),
        "decisions": [_compact(r, scored.get(ms.decision_id(r)))
                      for r in sorted(today, key=lambda x: x.get("ts_epoch") or 0, reverse=True)[:max(1, int(limit))]],
    }
