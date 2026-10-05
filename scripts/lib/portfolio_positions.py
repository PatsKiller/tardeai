"""ONE accessor for a position's price, value and P&L (operator 2026-10-05).

Why: the Command Center showed SPCX at $136.46 (value $40,938, P&L -$8,272) while Schwab had $171.09
(+$2,122). holdings.json rows carry several price fields; `schwab_position_sync` rebuilds each row from
`dict(prior)` and refreshes `price`, so `current_price` survives every sync frozen at whatever wrote it
first — and the holdings API preferred it for Schwab accounts (22 of 27 rows were off, -20% to +16%).

Rules this module enforces (docs/architecture/POSITIONS_SOURCE_OF_TRUTH_2026-10-05.md):
  * A stored position record is quantity, cost, account and lot facts. A price stored on it is only a
    fallback mark with its own as_of — never the truth.
  * The price comes from the Command Center data broker quote (market_quotes via
    lib.data_broker.market_quote.get_price_batch) with its as_of; then the Finviz live cache the repricer
    reads; then the stored repricer/broker mark, flagged with its age. `current_price` is never read.
  * value = shares × price; P&L = value − cost. Every surface goes through `resolve_mark` /
    `value_and_pl` so two pages can never show two prices for the same position.
Pure functions: no I/O except `load_config`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "portfolio_positions.yaml"
# The position store, phase 1 (docs/architecture/POSITIONS_SOURCE_OF_TRUTH_2026-10-05.md). New code reads
# it ONLY through load_store(); tests/test_portfolio_price_truth_20261005.py ratchets direct readers.
STORE_REL = ("data", "portfolios", "state", "holdings" + ".json")


def store_path() -> Path:
    """The position store under the persistent-state root (TRADEAI_PERSISTENT_STATE_ROOT, see
    lib/persistent_overlay.overlay_data_source) — never a hardcoded host path."""
    try:
        from lib.persistent_overlay import overlay_data_source  # type: ignore
    except ImportError:
        from persistent_overlay import overlay_data_source  # type: ignore
    return Path(overlay_data_source(canonical_source=ROOT)).joinpath(*STORE_REL)
NEVER_TRUSTED_PRICE_FIELDS = ("current_price",)   # frozen by dict(prior) merges; see module docstring
_DEFAULTS = {"price_stale_after_s": 6 * 3600, "price_tolerance_pct": 1.0, "value_tolerance_usd": 1.0,
             "basis_tolerance_usd": 1.0, "qty_tolerance": 0.001}


def load_config(path: Optional[Path] = None) -> dict:
    """config/portfolio_positions.yaml merged over the documented defaults."""
    cfg = dict(_DEFAULTS)
    try:
        import yaml
        raw = yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
        cfg.update({k: v for k, v in (raw.get("positions") or {}).items() if k in _DEFAULTS})
    except Exception:  # noqa: BLE001 — missing/unreadable config falls back to the documented defaults
        pass
    return cfg


_CLOSED_DEFAULTS = {"test_accounts": ["health", "journal_check"]}


def load_closed_config(path: Optional[Path] = None) -> dict:
    """`closed:` section — accounts whose trade_closed rows are probes, not trades."""
    cfg = dict(_CLOSED_DEFAULTS)
    try:
        import yaml
        raw = yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
        cfg.update({k: v for k, v in (raw.get("closed") or {}).items() if k in _CLOSED_DEFAULTS})
    except Exception:  # noqa: BLE001
        pass
    return cfg


def load_store(path: Optional[Path] = None) -> dict:
    """The raw position store document (positions are facts; any price on them is a fallback mark)."""
    import json
    p = path or store_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None   # NaN → None


def _age_s(as_of: Any, now: datetime) -> Optional[float]:
    if not as_of:
        return None
    s = str(as_of).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S ET",):
        try:
            from zoneinfo import ZoneInfo
            dt = datetime.strptime(s, fmt).replace(tzinfo=ZoneInfo("America/New_York"))
            return (now - dt).total_seconds()
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds()


def is_cash(position: dict) -> bool:
    return bool(position.get("is_cash")) or str(position.get("symbol") or "").upper() in ("CASH", "SPAXX", "FDRXX")


def resolve_mark(position: dict, *, quote: Optional[dict] = None, finviz: Optional[dict] = None,
                 now: Optional[datetime] = None, cfg: Optional[dict] = None) -> dict:
    """The one price for a position. quote = data-broker {price, as_of|fetched_at, source};
    finviz = {price, as_of}. Returns {price, source, as_of, age_s, live, stale}."""
    cfg = cfg or _DEFAULTS
    now = now or datetime.now(timezone.utc)
    if is_cash(position):
        return {"price": 1.0, "source": "cash_unit", "as_of": None, "age_s": None, "live": False, "stale": False}
    cands = []
    if quote and (_f(quote.get("price")) or 0) > 0:
        src = str(quote.get("source") or "market_quotes")
        cands.append((_f(quote["price"]), f"data_broker:{src}" if not src.startswith("data_broker") else src,
                      quote.get("as_of") or quote.get("fetched_at"), True))
    if finviz and (_f(finviz.get("price")) or 0) > 0:
        cands.append((_f(finviz["price"]), "finviz", finviz.get("as_of"), True))
    stored = _f(position.get("price")) or _f(position.get("canonical_mark"))
    if stored and stored > 0:
        cands.append((stored, "stored_mark", position.get("last_repriced") or position.get("canonical_mark_ingested_at")
                      or position.get("updated_at") or position.get("as_of"), False))
    if not cands:
        return {"price": None, "source": "none", "as_of": None, "age_s": None, "live": False, "stale": True}
    price, source, as_of, live = cands[0]
    age = _age_s(as_of, now)
    stale = age is None or age > float(cfg["price_stale_after_s"])
    return {"price": round(price, 6), "source": source, "as_of": str(as_of) if as_of else None,
            "age_s": None if age is None else round(age), "live": live and not stale, "stale": stale}


def value_and_pl(position: dict, mark: dict, cost_basis: Optional[float] = None) -> dict:
    """value = shares × mark price; P&L = value − cost (cost_basis override = the caller's reconciled basis)."""
    sh = _f(position.get("shares")) or 0.0
    px = mark.get("price")
    if is_cash(position):
        mv = _f(position.get("market_value")) if position.get("market_value") is not None else sh
    else:
        mv = round(sh * px, 2) if (px and sh) else None
    cb = cost_basis if cost_basis is not None else _f(position.get("cost_basis"))
    gl = round(mv - cb, 2) if (mv is not None and cb is not None and not is_cash(position)) else None
    glp = round(gl / cb * 100, 2) if (gl is not None and cb) else None
    return {"market_value": mv, "cost_basis": cb, "gain_loss": gl, "gain_loss_pct": glp}


def per_share_cost(position: dict) -> Optional[float]:
    """Average cost per share from the stored TOTAL cost basis (holdings rows store totals)."""
    sh, cb = _f(position.get("shares")), _f(position.get("cost_basis"))
    if sh and cb is not None and sh > 0:
        return round(cb / sh, 6)
    return _f(position.get("avg_cost"))
