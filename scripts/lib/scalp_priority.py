"""scalp_priority.py — which scalps are "about to fire" and get first claim on paid search (ScalpPriority@v1).

Operator, 2026-10-10: "we need to prioritize the search for scalps that are about to fire and make
sense." This is the deterministic definition, built only from data that already exists and read-only:

  * the scalp list — ``data/trade_ai/scalp_universe_latest.json`` (TradeAIScalpUniverse@v1, written by
    ``scripts/run_trade_ai_scalp_live.py``, the L1050 lane: symbol, decision, score, float, price,
    setup_class), or the candidate rows a calling lane hands in (the premarket band of
    ``catalyst_momentum_engine.py`` L379, Agent Q's hot tier) with optional ``rvol`` / ``gap_pct`` /
    ``change_pct``;
  * the GO line — ``assets/weights.yaml decision_rules.GO.min_score`` (40);
  * the routing receipts — when each symbol was last researched.

A candidate is PRIORITY when every rule holds (policy ``priority.scalp``):

  1. **session**: an NYSE trading day, inside premarket (04:00-09:30 ET) or RTH (09:30-16:00 ET);
  2. **on the current list**: the projection is no older than ``max_list_age_min`` (15), or the row was
     handed in by the calling lane this cycle;
  3. **makes sense**: decision is GO, MANUAL_REVIEW or WAIT — never AVOID;
  4. **about to fire**: score >= GO line - ``trigger_proximity_points`` (35), or momentum: RVOL >= 3 with a
     gap >= 5% or a move >= 10% (only when the row carries those fields);
  5. **needs research**: never researched today, or last researched >= ``research_stale_after_min`` (30) ago.

The top ``max_per_cycle`` (5) by score are priority; the rest are reported with the reason they were not.
Pure (``classify``) plus two read-only loaders. Nothing here sizes, orders or touches a broker.
AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

SCHEMA = "ScalpPriority@v1"
ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[2]


@dataclass
class PriorityDecision:
    symbol: str
    priority: bool
    score: Optional[float] = None
    decision: Optional[str] = None
    reasons: list[str] = field(default_factory=list)
    rank: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hhmm(s: str) -> time:
    h, m = str(s).split(":", 1)
    return time(int(h), int(m))


def _is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    try:
        from scripts.lib.cio_market_session import nyse_holidays
    except ImportError:  # pragma: no cover
        from lib.cio_market_session import nyse_holidays  # type: ignore
    try:
        return d not in set(nyse_holidays(d.year))
    except Exception:  # noqa: BLE001
        return True


def session_phase(now: datetime, cfg: Mapping[str, Any]) -> Optional[str]:
    """``premarket`` / ``rth`` / None (closed), in America/New_York."""
    local = now.astimezone(ET)
    if not _is_trading_day(local.date()):
        return None
    t = local.time()
    for name, (start, end) in (cfg.get("sessions_et") or {}).items():
        if _hhmm(start) <= t < _hhmm(end):
            return str(name)
    return None


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def classify(candidates: Iterable[Mapping[str, Any]], *, now: datetime, cfg: Mapping[str, Any],
             go_min: float, last_researched: Optional[Mapping[str, datetime]] = None,
             list_as_of: Optional[datetime] = None, handed_in: bool = False) -> list[PriorityDecision]:
    """Deterministic: same inputs, same answer. Returns one decision per distinct symbol."""
    last = {str(k).upper(): v for k, v in (last_researched or {}).items()}
    phase = session_phase(now, cfg)
    max_age = float(cfg.get("max_list_age_min", 15))
    list_fresh = handed_in or (list_as_of is not None and (now - list_as_of).total_seconds() <= max_age * 60)
    eligible = {str(d).upper() for d in cfg.get("eligible_decisions") or []}
    near = go_min - float(cfg.get("trigger_proximity_points", 5))
    mo = cfg.get("momentum_override") or {}
    stale_s = float(cfg.get("research_stale_after_min", 30)) * 60
    out: list[PriorityDecision] = []
    seen: set[str] = set()
    for row in candidates:
        sym = str((row or {}).get("symbol") or "").upper().strip()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        score = _f(row.get("score"))
        decision = str(row.get("decision") or "").upper() or None
        d = PriorityDecision(symbol=sym, priority=False, score=score, decision=decision)
        if phase is None:
            d.reasons.append("SESSION_CLOSED")
        if not list_fresh:
            d.reasons.append("LIST_STALE")
        if decision not in eligible:
            d.reasons.append(f"DECISION_{decision or 'NONE'}")
        rvol, gap, chg = _f(row.get("rvol") or row.get("relative_volume")), _f(row.get("gap_pct") or row.get("gap_percent")), \
            _f(row.get("change_pct") or row.get("change_percent"))
        near_go = score is not None and score >= near
        momentum = (rvol is not None and rvol >= float(mo.get("min_rvol", 3.0))
                    and ((gap is not None and gap >= float(mo.get("min_gap_pct", 5.0)))
                         or (chg is not None and chg >= float(mo.get("min_change_pct", 10.0)))))
        if not (near_go or momentum):
            d.reasons.append("NOT_NEAR_TRIGGER")
        prev = last.get(sym)
        if prev is not None and (now - prev).total_seconds() < stale_s:
            d.reasons.append("RESEARCHED_RECENTLY")
        if not d.reasons:
            d.reasons.append("NEAR_GO" if near_go else "MOMENTUM")
            d.priority = True
        out.append(d)
    ranked = sorted([d for d in out if d.priority], key=lambda x: (-(x.score or 0.0), x.symbol))
    cap = int(cfg.get("max_per_cycle", 5))
    for i, d in enumerate(ranked, start=1):
        if i <= cap:
            d.rank = i
        else:
            d.priority = False
            d.reasons = ["OVER_CYCLE_CAP"]
    return out


# ── read-only loaders ──────────────────────────────────────────────────────


def go_min_score(default: float = 40.0) -> float:
    try:
        import yaml

        w = yaml.safe_load((ROOT / "assets" / "weights.yaml").read_text(encoding="utf-8")) or {}
        return float(((w.get("decision_rules") or {}).get("GO") or {}).get("min_score", default))
    except Exception:  # noqa: BLE001
        return float(default)


def load_scalp_list(state_root: Path, rel: str) -> tuple[list[dict[str, Any]], Optional[datetime]]:
    """The L1050 projection rows and its ``as_of``. Empty + None when missing/unreadable."""
    try:
        doc = json.loads((Path(state_root) / rel).read_text(encoding="utf-8"))
        as_of = datetime.fromisoformat(str(doc.get("as_of")))
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=ET)
        return [r for r in doc.get("rows") or [] if isinstance(r, dict)], as_of
    except Exception:  # noqa: BLE001
        return [], None


def last_researched_from_receipts(path: Path, *, now: datetime, classes: Iterable[str] = ("scalp_priority",),
                                  max_bytes: int = 2_000_000) -> dict[str, datetime]:
    """Latest answered routing receipt per symbol for ``classes``, today only (UTC day)."""
    want = set(classes)
    out: dict[str, datetime] = {}
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            raw = fh.read().decode("utf-8", errors="ignore")
    except OSError:
        return out
    day = now.astimezone(timezone.utc).date()
    for line in raw.splitlines():
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if r.get("class") not in want or not r.get("symbol") or not r.get("answered"):
            continue
        try:
            ts = datetime.fromisoformat(str(r.get("ts")))
        except Exception:  # noqa: BLE001
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts.astimezone(timezone.utc).date() != day or ts > now:
            continue
        sym = str(r["symbol"]).upper()
        if sym not in out or ts > out[sym]:
            out[sym] = ts
    return out


__all__ = ["SCHEMA", "PriorityDecision", "session_phase", "classify", "go_min_score", "load_scalp_list",
           "last_researched_from_receipts"]
