"""Data Broker projection — live Active Trader microstructure (registry domain
``active_trader_microstructure``).

Operator rule (2026-10-05): "the source of truth should be the Command Center for all data. If
data needs to be refreshed, it's refreshed with the data broker in the Command Center and then
spawned out. Each individual process should not be going out looking for its own data sources."

The single producer is scripts/active_trader/microstructure_recorder.py (moomoo quote context,
every ~5 s for the live scalp names). It writes, under the Active Trader journal directory:
  micro/<day>/<SYMBOL>.jsonl       one line per poll: book (b/a), new prints (k), last (l/qt)
  micro/<day>/<SYMBOL>.bars.json   today's 1-min bars, start-normalized, last one may be forming
  micro/live_symbols.json          the symbols currently recorded

This module only READS those files. Zero provider calls; no provider SDK is imported here. Every
read carries its age and fails closed: older than the freshness contract → status "stale" and no
data, never a stale value presented as current.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

DOMAIN = "active_trader_microstructure"
DEFAULT_MAX_AGE_S = 15.0
TAIL_BYTES = 256_000
_SIDE = {"B": "BUY", "S": "SELL"}


def store_dir() -> Path:
    """Same root as the alert journal (persistent state; ACTIVE_TRADER_ALERTS_DIR in tests)."""
    env = os.environ.get("ACTIVE_TRADER_ALERTS_DIR", "").strip()
    if env:
        return Path(env) / "micro"
    try:
        from active_trader import momentum_alerts as ma  # pure module (no provider imports)
    except ModuleNotFoundError:  # pragma: no cover
        from scripts.active_trader import momentum_alerts as ma
    return ma.journal_dir() / "micro"


def _status(as_of: Optional[float], now: float, max_age_s: float) -> dict:
    if as_of is None:
        return {"domain": DOMAIN, "status": "missing", "as_of": None, "age_s": None}
    age = round(now - float(as_of), 1)
    return {"domain": DOMAIN, "status": "ok" if age <= max_age_s else "stale", "as_of": as_of, "age_s": age}


def _tail_lines(path: Path, max_bytes: int = TAIL_BYTES) -> list[str]:
    try:
        size = path.stat().st_size
    except OSError:
        return []
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()   # drop the partial first line
        return fh.read().decode("utf-8", "replace").splitlines()


def snapshots(day: str, symbol: str, *, start: Optional[float] = None, end: Optional[float] = None,
              base: Optional[Path] = None) -> list[dict]:
    out = []
    for raw in _tail_lines((base or store_dir()) / day / f"{symbol.upper()}.jsonl"):
        try:
            s = json.loads(raw)
        except ValueError:
            continue
        t = s.get("t") or 0
        if (start is None or t >= start) and (end is None or t <= end):
            out.append(s)
    return out


def latest(day: str, symbol: str, *, now: float, max_age_s: float = DEFAULT_MAX_AGE_S,
           base: Optional[Path] = None) -> dict:
    snaps = snapshots(day, symbol, start=now - 600, base=base)
    snap = snaps[-1] if snaps else None
    env = _status(snap.get("t") if snap else None, now, max_age_s)
    env["snapshot"] = snap if env["status"] == "ok" else None
    return env


def book(day: str, symbol: str, *, now: float, max_age_s: float = DEFAULT_MAX_AGE_S,
         base: Optional[Path] = None) -> Optional[dict]:
    """The latest recorded book in the shape l2_evidence expects; None when stale/missing (the
    decision then vetoes BOOK_MISSING — fail closed)."""
    env = latest(day, symbol, now=now, max_age_s=max_age_s, base=base)
    s = env.get("snapshot")
    if not s or "b" not in s or "a" not in s:
        return None
    return {"bids": s.get("b") or [], "asks": s.get("a") or [],
            "ts_epoch": s.get("bt") or s.get("t"), "ts_source": f"store:{s.get('bs') or 'recorder'}"}


def tape(day: str, symbol: str, *, now: float, lookback_s: float = 600.0, max_prints: int = 200,
         base: Optional[Path] = None) -> list[dict]:
    """Prints recorded in the last lookback_s, oldest→newest, in tape_evidence's shape."""
    rows: list[dict] = []
    for s in snapshots(day, symbol, start=now - lookback_s, base=base):
        for t, p, v, side in (s.get("k") or []):
            rows.append({"ts_epoch": t, "price": p, "volume": v, "direction": _SIDE.get(side, "NEUTRAL")})
    rows.sort(key=lambda r: r["ts_epoch"] or 0)
    return rows[-max_prints:]


def quote(day: str, symbol: str, *, now: float, max_age_s: float = DEFAULT_MAX_AGE_S,
          base: Optional[Path] = None) -> tuple[Optional[float], Optional[float]]:
    env = latest(day, symbol, now=now, max_age_s=max_age_s, base=base)
    s = env.get("snapshot")
    if not s or s.get("l") is None:
        return None, None
    return float(s["l"]), (s.get("qt") or s.get("t"))


def bars(day: str, symbol: str, *, now: float, max_age_s: float = DEFAULT_MAX_AGE_S,
         base: Optional[Path] = None) -> dict:
    """{status, age_s, closed:[bars], forming: bar|None}. Bars carry t (start epoch) and o/h/l/c/v.
    A bar is closed when its end (start+60) is at or before `now`."""
    p = (base or store_dir()) / day / f"{symbol.upper()}.bars.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    env = _status(doc.get("t") if doc else None, now, max_age_s)
    env.update(closed=[], forming=None, provider=(doc or {}).get("provider"))
    if env["status"] != "ok":
        return env
    for r in doc.get("rows") or []:
        b = {"t": float(r["s"]), "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"], "v": r.get("v") or 0.0}
        if b["t"] + 60.0 <= now:
            env["closed"].append(b)
        elif b["t"] <= now:
            env["forming"] = b
    return env


def live_symbols(*, now: float, max_age_s: float = 900.0, base: Optional[Path] = None) -> list[str]:
    try:
        doc = json.loads(((base or store_dir()) / "live_symbols.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if now - float(doc.get("ts_epoch") or 0) > max_age_s:
        return []
    return [str(s).upper() for s in doc.get("symbols") or []]
