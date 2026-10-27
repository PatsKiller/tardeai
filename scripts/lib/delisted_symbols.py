"""Delisted / inactive symbol detection — one reader for the prospectus universe and the Watch archive script.

Operator 2026-10-26 (verbatim): "remove SRNE and any delisted". A symbol is treated as delisted when ANY of:

  explicit        it is on config/delisted_symbols.json ``explicit`` (SRNE), with the operator's reason;
  identity        the house says so: the position store flags the row ``delisted`` (schwab_position_sync marks a
                  CUSIP-only line), or the identity registry entity carries ``delisted: true`` or a
                  ``listing_status`` in ``inactive_identity_statuses``;
  no_prices       the last house daily close is more than ``no_price_sessions`` weekday sessions behind the freshest
                  house close (a symbol with no bars at all is NOT excluded: that is a data gap, not a delisting);
  near_zero       the last close is at or below ``near_zero_close_usd``;
  terminal        the last close is at or below ``terminal_collapse.max_ratio_to_prior_median`` x the median of the
                  prior ``terminal_collapse.prior_sessions`` closes.

``never_exclude`` overrides every detector. Every threshold comes from the config file (no hardcoded values).
Pure functions: the caller injects the bars and flags, so tests never reach a database. AUTHORITY:
READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0 — this decides what is researched and shown, never an order, size or stop.
It never deletes a price row (the bad rows are the quarantine script's input).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
CONFIG_REL = Path("config") / "delisted_symbols.json"
SCHEMA = "DelistedSymbolsPolicy@v1"
LABEL = "delisted — excluded"
STATUS = "delisted_excluded"


def norm(symbol: Any) -> str:
    return str(symbol or "").strip().upper()


def load_config(path: Path | str | None = None) -> dict:
    p = Path(path) if path else ROOT / CONFIG_REL
    doc = json.loads(p.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"{p}: schema must be {SCHEMA}")
    for key in ("explicit", "never_exclude", "inactive_identity_statuses", "no_price_sessions",
                "near_zero_close_usd", "terminal_collapse"):
        if key not in doc:
            raise ValueError(f"{p}: missing {key}")
    return doc


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def sessions_between(last: date, today: date) -> int:
    """Weekday sessions strictly after ``last`` up to and including ``today`` (holidays count; the threshold
    allows for them)."""
    if today <= last:
        return 0
    n, d = 0, last
    while d < today:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _close(bar: Mapping) -> float | None:
    try:
        v = float(bar.get("close"))
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _bar_day(bar: Mapping) -> date | None:
    return _day(bar.get("price_date") or bar.get("date") or bar.get("d"))


def classify(symbol: str, *, bars: list[Mapping] | None, flags: Mapping | None, cfg: Mapping,
             today: date) -> dict | None:
    """The first reason ``symbol`` is delisted, or None. ``flags``: {delisted: bool, listing_status: str, ...}."""
    sym = norm(symbol)
    if not sym or sym in {norm(s) for s in cfg.get("never_exclude") or []}:
        return None
    for row in cfg.get("explicit") or []:
        if norm(row.get("symbol")) == sym:
            return {"symbol": sym, "code": "explicit", "reason": str(row.get("reason") or "operator list"),
                    "since": row.get("since")}
    flags = flags or {}
    inactive = {str(s).upper() for s in cfg.get("inactive_identity_statuses") or []}
    if flags.get("delisted") is True:
        return {"symbol": sym, "code": "identity", "reason": f"house record flags the symbol delisted ({flags.get('source') or 'store'})"}
    status = str(flags.get("listing_status") or "").upper()
    if status and status in inactive:
        return {"symbol": sym, "code": "identity", "reason": f"identity listing status {status}"}
    rows = sorted(((d, c) for d, c in ((_bar_day(b), _close(b)) for b in bars or []) if d is not None and c is not None),
                  key=lambda x: x[0])
    if not rows:
        return None  # no bars at all: a data gap, never a delisting
    last_day, last_close = rows[-1]
    gap = sessions_between(last_day, today)
    if gap > int(cfg["no_price_sessions"]):
        return {"symbol": sym, "code": "no_prices", "reason": f"no house close for {gap} sessions (last {last_day.isoformat()})",
                "last_price_date": last_day.isoformat()}
    if last_close <= float(cfg["near_zero_close_usd"]):
        return {"symbol": sym, "code": "near_zero", "reason": f"last close {last_close:g} on {last_day.isoformat()} is near zero",
                "last_close": last_close}
    tc = cfg.get("terminal_collapse") or {}
    prior = [c for _, c in rows[-1 - int(tc.get("prior_sessions", 0)):-1] if c > 0]
    if prior and tc.get("max_ratio_to_prior_median") is not None:
        med = median(prior)
        if med > 0 and last_close / med <= float(tc["max_ratio_to_prior_median"]):
            return {"symbol": sym, "code": "terminal",
                    "reason": f"last close {last_close:g} is {last_close / med:.4f}x the prior {len(prior)}-session median {med:g}",
                    "last_close": last_close}
    return None


def detect(symbols: Iterable[str], *, bars_fn: Callable[[str], list] | None, flags: Mapping[str, Mapping] | None = None,
           cfg: Mapping | None = None, today: date | None = None) -> dict:
    """{excluded: {SYM: verdict}, checked: n, errors: {SYM: reason}, reference_date}. A bars read failure never
    excludes.

    ``today`` defaults to the FRESHEST house close among the checked symbols (not the wall clock), so a house-wide
    ingest outage never makes every name look delisted — "no prices for N sessions" means N sessions behind the
    rest of the house."""
    cfg = cfg if cfg is not None else load_config()
    out: dict[str, Any] = {"excluded": {}, "checked": 0, "errors": {}, "reference_date": None}
    explicit = {norm(r.get("symbol")) for r in cfg.get("explicit") or []}
    flags = flags or {}
    gathered: dict[str, list] = {}
    for sym in sorted({norm(s) for s in symbols if norm(s)}):
        out["checked"] += 1
        bars: list = []
        if sym not in explicit and not (flags.get(sym) or {}).get("delisted") and bars_fn is not None:
            try:
                bars = bars_fn(sym) or []
            except Exception as exc:  # noqa: BLE001 - a read failure is recorded, never an exclusion
                out["errors"][sym] = f"{type(exc).__name__}: {str(exc)[:120]}"
                bars = []
        gathered[sym] = bars
    if today is None:
        lasts = [d for d in (max((_bar_day(b) for b in bars if _bar_day(b)), default=None) for bars in gathered.values()) if d]
        today = max(lasts) if lasts else datetime.now(timezone.utc).date()
    out["reference_date"] = today.isoformat()
    for sym, bars in gathered.items():
        verdict = classify(sym, bars=bars, flags=flags.get(sym), cfg=cfg, today=today)
        if verdict:
            out["excluded"][sym] = verdict
    return out


def house_flags(*, holdings_doc: Mapping | None = None, identity_doc: Mapping | None = None) -> dict[str, dict]:
    """{SYM: flags} from the position store (row ``delisted``) and the identity registry (entity ``delisted`` /
    ``listing_status``). Both documents are optional; a missing store contributes nothing."""
    out: dict[str, dict] = {}
    for row in (holdings_doc or {}).get("holdings") or []:
        if isinstance(row, Mapping) and row.get("delisted") and norm(row.get("symbol")):
            out.setdefault(norm(row.get("symbol")), {}).update(delisted=True, source="position store")
    ents = (identity_doc or {}).get("entities") or {}
    for sym, guid in ((identity_doc or {}).get("by_symbol") or {}).items():
        ent = ents.get(guid) if isinstance(ents, Mapping) else None
        if not isinstance(ent, Mapping):
            continue
        f: dict = {}
        if ent.get("delisted") is True:
            f.update(delisted=True, source="identity registry")
        if ent.get("listing_status"):
            f["listing_status"] = str(ent.get("listing_status"))
        if f:
            out.setdefault(norm(sym), {}).update(f)
    return out


def load_house_flags(state_root: Path | str | None = None) -> dict[str, dict]:
    """house_flags over the production stores (read-only). Each store failing contributes nothing."""
    holdings_doc = identity_doc = None
    try:
        from scripts.lib import portfolio_positions as pp
        holdings_doc = pp.load_store(pp.store_path(state_root) if state_root else None)
    except Exception:  # noqa: BLE001
        holdings_doc = None
    try:
        from scripts.lib import identity_registry as ir
        identity_doc = ir.load(state_root)
    except Exception:  # noqa: BLE001
        identity_doc = None
    return house_flags(holdings_doc=holdings_doc, identity_doc=identity_doc)
