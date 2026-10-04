"""CounterfactualLedger@v1 — what blocked ideas did afterwards, by gate.

Operator-approved 2026-10-03 (Policy Review P3). Gates block ideas, but nothing
recorded what the blocked ideas then did, so no gate could be tuned on evidence.
This ledger records each blocked idea once per gate, symbol and day, then
measures the price 1, 5 and 20 trading sessions later against the decision-time
price and against SPY.

Prices are ticker_prices snapshots (written about 07:20 ET, i.e. roughly the
prior close). The base is the latest snapshot known at block time; forward
points are snapshots 1/5/20 SPY sessions later. A missing price is PENDING, a
forward snapshot identical to the base is flagged STALE_IDENTICAL (likely
copy-forward) and excluded from statistics. Nothing is fabricated.

Observation only: no order, size or threshold is changed by this ledger.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

SCHEMA = "CounterfactualLedger@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
STORE_RELATIVE = Path("data") / "cio" / "counterfactual_ledger.jsonl"
HORIZONS = (1, 5, 20)
BIG_MOVE_PCT = 5.0
_ET = ZoneInfo("America/New_York")
_OPTIONS_BLOCKED = ("MONITOR_ONLY", "REJECT", "MORE_RESEARCH")
_BASE_MAX_AGE = timedelta(days=4)


def store_path(path: Path | str | None = None) -> Path:
    if path:
        return Path(path)
    configured = (os.environ.get("CIO_COUNTERFACTUAL_LEDGER_JSONL") or "").strip()
    if configured:
        return Path(configured)
    from scripts.lib.canonical_store_registry import production_state_root
    return Path(production_state_root()) / STORE_RELATIVE


def _ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def block_id(gate: str, symbol: str, day: str) -> str:
    return "cf_" + hashlib.sha256(f"{gate}|{symbol}|{day}".encode()).hexdigest()[:20]


# ── blocks ───────────────────────────────────────────────────────────────────


def collect_blocks(db_query: Callable[..., Any], *, since: datetime) -> list[dict[str, Any]]:
    """Blocked ideas since ``since``, one per (gate, symbol, ET day): first block wins."""
    rows: list[dict[str, Any]] = []
    for r in db_query(
        "SELECT symbol, strategy_id, decision, reason_codes, created_at FROM auto_proposal_decisions"
        " WHERE decision LIKE 'SKIPPED%%' AND created_at >= %s ORDER BY created_at",
        (since,), fetch="all",
    ) or []:
        rows.append({
            "source": "auto_proposal_decisions",
            "gate": f"{r.get('strategy_id') or 'unknown'}:{r.get('decision')}",
            "family": "proposal_generator",
            "symbol": r.get("symbol"),
            "blocked_at": r.get("created_at"),
            "detail": r.get("reason_codes"),
        })
    for r in db_query(
        "SELECT decision_id, symbol, action, action_class, created_at FROM cio_decisions"
        " WHERE action_class IN ('options_thesis_review', 'entry_review') AND created_at >= %s"
        " ORDER BY created_at",
        (since,), fetch="all",
    ) or []:
        action = str(r.get("action") or "").upper()
        cls = r.get("action_class")
        if cls == "options_thesis_review" and action not in _OPTIONS_BLOCKED:
            continue
        if cls == "entry_review" and action in ("APPROVE", "APPROVED", "BUY", "GO"):
            continue
        rows.append({
            "source": "cio_decisions",
            "gate": f"{'options_review' if cls == 'options_thesis_review' else 'buy_ready_review'}:{action}",
            "family": cls,
            "symbol": r.get("symbol"),
            "blocked_at": r.get("created_at"),
            "decision_id": r.get("decision_id"),
        })
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").strip().upper()
        when = _ts(row.get("blocked_at"))
        if not sym or when is None:
            continue
        day = when.astimezone(_ET).date().isoformat()
        bid = block_id(row["gate"], sym, day)
        if bid in out:
            out[bid]["rechecks"] += 1
            continue
        out[bid] = {**row, "symbol": sym, "blocked_at": when.isoformat(), "day": day,
                    "block_id": bid, "rechecks": 1}
    return list(out.values())


# ── prices ───────────────────────────────────────────────────────────────────


def load_prices(db_query: Callable[..., Any], symbols: Iterable[str], *, since: datetime) -> dict[str, list[dict]]:
    """symbol -> snapshots sorted by price_date: {date, close, created_at}."""
    syms = sorted({str(s).upper() for s in symbols if s} | {"SPY"})
    out: dict[str, list[dict]] = {s: [] for s in syms}
    for r in db_query(
        "SELECT symbol, price_date, close_price, created_at FROM ticker_prices"
        " WHERE symbol = ANY(%s) AND price_date >= %s ORDER BY symbol, price_date",
        (syms, (since - _BASE_MAX_AGE).date()), fetch="all",
    ) or []:
        try:
            close = float(r.get("close_price"))
        except (TypeError, ValueError):
            continue
        out.setdefault(str(r["symbol"]).upper(), []).append({
            "date": str(r.get("price_date")), "close": close, "created_at": _ts(r.get("created_at")),
        })
    return out


def _pct(a: float, b: float) -> Optional[float]:
    return round(100.0 * (b - a) / a, 3) if a else None


def measure(block: dict[str, Any], prices: dict[str, list[dict]]) -> dict[str, Any]:
    """Forward returns for one block. Missing data is PENDING, never guessed."""
    sym_rows = prices.get(block["symbol"]) or []
    spy = prices.get("SPY") or []
    calendar = [r["date"] for r in spy]
    when = _ts(block["blocked_at"])
    known = [r for r in sym_rows if r["created_at"] and when and r["created_at"] <= when
             and when - r["created_at"] <= _BASE_MAX_AGE]
    horizons: dict[str, dict[str, Any]] = {}
    if not known:
        for k in HORIZONS:
            horizons[str(k)] = {"status": "PENDING", "reason": "no price snapshot at block time"}
        return {**block, "base": None, "horizons": horizons}
    base = known[-1]
    by_date = {r["date"]: r["close"] for r in sym_rows}
    spy_by_date = {r["date"]: r["close"] for r in spy}
    idx = calendar.index(base["date"]) if base["date"] in calendar else None
    for k in HORIZONS:
        key = str(k)
        if idx is None:
            horizons[key] = {"status": "PENDING", "reason": "base date not on the SPY session calendar"}
            continue
        if idx + k >= len(calendar):
            horizons[key] = {"status": "PENDING", "reason": f"{k} sessions have not elapsed"}
            continue
        target = calendar[idx + k]
        later = by_date.get(target)
        if later is None:
            horizons[key] = {"status": "PENDING", "reason": f"no {block['symbol']} snapshot on {target}"}
            continue
        if later == base["close"]:
            horizons[key] = {"status": "STALE_IDENTICAL", "date": target,
                             "reason": "forward snapshot equals the base (likely copy-forward)"}
            continue
        ret = _pct(base["close"], later)
        spy_ret = _pct(spy_by_date.get(base["date"]) or 0.0, spy_by_date.get(target) or 0.0) \
            if spy_by_date.get(base["date"]) and spy_by_date.get(target) else None
        horizons[key] = {"status": "MEASURED", "date": target, "close": later, "return_pct": ret,
                         "spy_return_pct": spy_ret,
                         "relative_pct": round(ret - spy_ret, 3) if ret is not None and spy_ret is not None else None}
    return {**block, "base": {"date": base["date"], "close": base["close"]}, "horizons": horizons}


# ── summary ──────────────────────────────────────────────────────────────────


def summarize(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per gate and horizon: n, mean/median return, % up/down > 5%, cost and benefit."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        for k, h in (row.get("horizons") or {}).items():
            g = groups.setdefault((row["gate"], k), {"returns": [], "pending": 0, "stale": 0, "blocks": 0})
            g["blocks"] += 1
            if h.get("status") == "MEASURED" and h.get("return_pct") is not None:
                g["returns"].append(float(h["return_pct"]))
            elif h.get("status") == "STALE_IDENTICAL":
                g["stale"] += 1
            else:
                g["pending"] += 1
    out = []
    for (gate, k), g in sorted(groups.items(), key=lambda kv: (kv[0][0], int(kv[0][1]))):
        r = g["returns"]
        up = sum(1 for x in r if x > BIG_MOVE_PCT)
        down = sum(1 for x in r if x < -BIG_MOVE_PCT)
        out.append({
            "gate": gate, "horizon_sessions": int(k), "blocks": g["blocks"], "measured": len(r),
            "pending": g["pending"], "stale_identical": g["stale"],
            "mean_return_pct": round(statistics.fmean(r), 2) if r else None,
            "median_return_pct": round(statistics.median(r), 2) if r else None,
            "pct_up_over_5": round(100.0 * up / len(r), 1) if r else None,
            "pct_down_over_5": round(100.0 * down / len(r), 1) if r else None,
            "cost_good_moves_blocked": up,
            "benefit_losers_avoided": down,
        })
    return out



def summarize_ideas(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per strategy and horizon, each idea (strategy, symbol, ET day) counted ONCE.

    ``summarize`` is per gate, and one idea is usually blocked by several gates of
    the same strategy (GLND 09-21: four meme-squeeze gates), so adding gate rows
    counted it up to four times. This is the per-idea view to judge a strategy by.
    """
    ideas: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        strategy = str(row.get("gate") or "").split(":", 1)[0]
        key = (strategy, str(row.get("symbol")), str(row.get("day")))
        idea = ideas.setdefault(key, {"strategy": strategy, "gates": set(), "horizons": row.get("horizons") or {}})
        idea["gates"].add(str(row.get("gate") or "").split(":", 1)[-1])
    out: list[dict[str, Any]] = []
    for strategy in sorted({k[0] for k in ideas}):
        members = [v for k, v in ideas.items() if k[0] == strategy]
        for k in HORIZONS:
            r = [float(m["horizons"][str(k)]["return_pct"]) for m in members
                 if (m["horizons"].get(str(k)) or {}).get("status") == "MEASURED"
                 and m["horizons"][str(k)].get("return_pct") is not None]
            up = sum(1 for x in r if x > BIG_MOVE_PCT)
            down = sum(1 for x in r if x < -BIG_MOVE_PCT)
            out.append({
                "strategy": strategy, "horizon_sessions": int(k), "ideas": len(members), "measured": len(r),
                "mean_return_pct": round(statistics.fmean(r), 2) if r else None,
                "median_return_pct": round(statistics.median(r), 2) if r else None,
                "good_moves_blocked": up, "losers_avoided": down,
                "multi_gate_ideas": sum(1 for m in members if len(m["gates"]) > 1),
            })
    return out

# ── store ────────────────────────────────────────────────────────────────────

_INDEX: dict[str, tuple[tuple[int, int], dict[str, dict[str, Any]]]] = {}
_LOCK = threading.Lock()


def _stat_key(path: Path) -> Optional[tuple[int, int]]:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def latest_rows(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """block_id -> latest row (append-only; a later measurement supersedes)."""
    target = store_path(path)
    key = _stat_key(target)
    if key is None:
        return {}
    hit = _INDEX.get(str(target))
    if hit and hit[0] == key:
        return hit[1]
    rows: dict[str, dict[str, Any]] = {}
    with target.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("block_id"):
                rows[str(row["block_id"])] = row
    _INDEX[str(target)] = (key, rows)
    return rows


def _content(row: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"h": row.get("horizons"), "b": row.get("base")},
                                     sort_keys=True, default=str).encode()).hexdigest()[:16]


def append_rows(rows: Iterable[dict[str, Any]], *, path: Path | str | None = None) -> int:
    """Append rows whose measurement changed since their last version. Returns count written."""
    import fcntl

    target = store_path(path)
    with _LOCK:
        current = latest_rows(target)
        fresh = []
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            c = _content(row)
            prior = current.get(row["block_id"])
            if prior and prior.get("content_hash") == c:
                continue
            fresh.append({**row, "schema": SCHEMA, "authority": AUTHORITY, "memory_behavior_influence": 0,
                          "financial_action": False, "content_hash": c, "recorded_at": now,
                          "source_ref": f"counterfactual_ledger:{row['block_id']}"})
        if not fresh:
            return 0
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                for row in fresh:
                    fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        _INDEX.pop(str(target), None)
        return len(fresh)


def build(db_query: Callable[..., Any], *, days: int = 30, now: Optional[datetime] = None) -> dict[str, Any]:
    """Collect, measure and summarize the last ``days`` of blocks. Pure apart from reads."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    blocks = collect_blocks(db_query, since=since)
    prices = load_prices(db_query, (b["symbol"] for b in blocks), since=since)
    rows = [measure(b, prices) for b in blocks]
    return {"schema": SCHEMA, "as_of": now.isoformat(), "days": days, "blocks": len(rows),
            "rechecks_collapsed": sum(b.get("rechecks", 1) - 1 for b in blocks),
            "summary": summarize(rows), "idea_summary": summarize_ideas(rows), "rows": rows}


__all__ = ["SCHEMA", "HORIZONS", "append_rows", "block_id", "build", "collect_blocks", "latest_rows",
           "load_prices", "measure", "store_path", "summarize", "summarize_ideas"]
