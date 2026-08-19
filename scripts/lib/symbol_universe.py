"""Canonical investable-universe reconciliation (READ_ONLY_ADVISORY).

Builds a deterministic projection of material symbols from existing stores.
Does NOT replace source stores. Does NOT write broker/risk state.

Memberships (multi-valued):
  HELD | FORMER_HOLDING | REENTRY | WATCHLIST | OPPORTUNITY | RESEARCH_ONLY | RETIRED
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]

MEMBERSHIPS = (
    "HELD",
    "FORMER_HOLDING",
    "REENTRY",
    "WATCHLIST",
    "OPPORTUNITY",
    "RESEARCH_ONLY",
    "RETIRED",
)

CASHISH = frozenset({
    "SPAXX", "CASH", "USD", "MMDA1", "SWVXX", "VMFXX", "FDRXX", "",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sym(x: Any) -> str:
    return str(x or "").strip().upper()


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _held_symbols(root: Path) -> dict[str, dict[str, Any]]:
    h = _load_json(root / "data/portfolios/state/holdings.json") or {}
    out: dict[str, dict[str, Any]] = {}
    rows: list = []
    if isinstance(h, dict):
        if isinstance(h.get("holdings"), list):
            rows = h["holdings"]
        elif isinstance(h.get("positions"), list):
            rows = h["positions"]
        elif isinstance(h.get("accounts"), dict):
            for acct, body in h["accounts"].items():
                if isinstance(body, dict) and isinstance(body.get("positions"), list):
                    for p in body["positions"]:
                        if isinstance(p, dict):
                            p = dict(p)
                            p.setdefault("account", acct)
                            rows.append(p)
                elif isinstance(body, list):
                    rows.extend(body)
        else:
            # flat symbol map?
            for k, v in h.items():
                if isinstance(v, dict) and (_sym(k) or _sym(v.get("symbol"))):
                    rows.append({**v, "symbol": v.get("symbol") or k})
    elif isinstance(h, list):
        rows = h
    for r in rows:
        if not isinstance(r, dict):
            continue
        s = _sym(r.get("symbol") or r.get("ticker"))
        if not s or s in CASHISH:
            continue
        qty = r.get("quantity") or r.get("qty") or r.get("shares")
        try:
            if qty is not None and float(qty) == 0:
                continue
        except Exception:
            pass
        out[s] = {
            "symbol": s,
            "account": r.get("account") or r.get("account_key"),
            "quantity": qty,
            "source": "holdings.json",
        }
    return out


def _reentry_rows(root: Path) -> dict[str, dict[str, Any]]:
    re = _load_json(root / "data/runtime/reentry_decision_desk_latest.json") or {}
    rows = re.get("rows") if isinstance(re, dict) else None
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        s = _sym(r.get("symbol"))
        if not s or s in CASHISH:
            continue
        intel = r.get("intel") or {}
        out[s] = {
            "symbol": s,
            "held": bool(r.get("held")),
            "intel_state": intel.get("state"),
            "intel_action": intel.get("action"),
            "advisory_action": (r.get("advisory") or {}).get("action"),
            "why": r.get("why"),
            "source": "reentry_decision_desk_latest.json",
        }
    return out


def _opportunity_rows(root: Path) -> dict[str, dict[str, Any]]:
    brief = _load_json(root / "data/cio/cio_investment_brief.json") or {}
    ob = (brief.get("opportunity_book") or {}) if isinstance(brief, dict) else {}
    top = ob.get("top") or []
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(top, list):
        return out
    for r in top:
        if not isinstance(r, dict):
            continue
        s = _sym(r.get("symbol"))
        if not s:
            continue
        out[s] = {
            "symbol": s,
            "rank": r.get("rank"),
            "source": r.get("source") or "opportunity_book",
            "label": r.get("label"),
            "vs_former_holdings": r.get("vs_former_holdings"),
        }
    return out


def _former_from_db(root: Path) -> dict[str, dict[str, Any]]:
    """Best-effort read of previously_traded_watchlist (fail-soft)."""
    out: dict[str, dict[str, Any]] = {}
    try:
        import psycopg2
        import psycopg2.extras
        env_path = root / ".env"
        pw = os.environ.get("DB_PASSWORD", "")
        if not pw and env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("DB_PASSWORD="):
                    pw = line.split("=", 1)[1].strip().strip("'\"")
        if not pw:
            return out
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=pw,
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT symbol, is_currently_held, reentry_signal, category,
                   best_pnl_pct, last_exit_price, current_price, pct_above_exit
            FROM previously_traded_watchlist
            """
        )
        for row in cur.fetchall() or []:
            s = _sym(row.get("symbol"))
            if not s:
                continue
            out[s] = dict(row)
            out[s]["symbol"] = s
            out[s]["source"] = "previously_traded_watchlist"
        conn.close()
    except Exception as exc:
        out["__error__"] = {"error": str(exc)[:200]}  # type: ignore
    return out


def _watchlist_from_db(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        import psycopg2
        import psycopg2.extras
        env_path = root / ".env"
        pw = os.environ.get("DB_PASSWORD", "")
        if not pw and env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("DB_PASSWORD="):
                    pw = line.split("=", 1)[1].strip().strip("'\"")
        if not pw:
            return out
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=pw,
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT symbol, source, status
            FROM watchlist_items
            WHERE COALESCE(status, 'active') NOT IN ('removed', 'deleted', 'archived')
            """
        )
        for row in cur.fetchall() or []:
            s = _sym(row.get("symbol"))
            if not s or s in CASHISH:
                continue
            rec = out.setdefault(s, {"symbol": s, "sources": [], "statuses": [], "source": "watchlist_items"})
            src = row.get("source")
            st = row.get("status")
            if src and src not in rec["sources"]:
                rec["sources"].append(src)
            if st and st not in rec["statuses"]:
                rec["statuses"].append(st)
        conn.close()
    except Exception as exc:
        out["__error__"] = {"error": str(exc)[:200]}  # type: ignore
    return out


def reconcile_universe(root: Path | None = None) -> dict[str, Any]:
    """Return projection: counts + per-symbol memberships (deterministic)."""
    root = Path(root or ROOT)
    held = _held_symbols(root)
    reentry = _reentry_rows(root)
    opportunity = _opportunity_rows(root)
    former = _former_from_db(root)
    watch = _watchlist_from_db(root)

    errors = []
    for name, blob in (("former", former), ("watchlist", watch)):
        if "__error__" in blob:
            errors.append({name: blob.pop("__error__")})

    symbols = sorted(
        set(held) | set(reentry) | set(opportunity) | set(former) | set(watch)
    )
    # drop error sentinel keys
    symbols = [s for s in symbols if not s.startswith("__")]

    records: dict[str, dict[str, Any]] = {}
    for s in symbols:
        memberships: list[str] = []
        reasons: list[str] = []
        sources: list[str] = []

        if s in held:
            memberships.append("HELD")
            reasons.append("in_holdings_json")
            sources.append("holdings.json")
        if s in former and not former[s].get("is_currently_held"):
            memberships.append("FORMER_HOLDING")
            reasons.append("previously_traded_watchlist")
            sources.append("previously_traded_watchlist")
        # Re-entry book: present in desk and not merely currently-held-only noise
        if s in reentry:
            intel = (reentry[s].get("intel_state") or "").upper()
            if reentry[s].get("held") and intel.startswith("CURRENTLY HELD"):
                # still list as REENTRY watch surface if in book names, but mark held
                memberships.append("REENTRY")
                reasons.append(f"reentry_desk:{intel or 'HELD'}")
            else:
                memberships.append("REENTRY")
                reasons.append(f"reentry_desk:{intel or 'PRESENT'}")
            sources.append("reentry_decision_desk_latest.json")
        if s in watch:
            memberships.append("WATCHLIST")
            reasons.append("watchlist_items_active")
            sources.append("watchlist_items")
        if s in opportunity:
            memberships.append("OPPORTUNITY")
            reasons.append(f"opportunity_rank:{opportunity[s].get('rank')}")
            sources.append("cio_investment_brief.opportunity_book")

        # unique preserve order
        seen = set()
        memberships = [m for m in memberships if not (m in seen or seen.add(m))]

        records[s] = {
            "symbol": s,
            "memberships": memberships,
            "membership_reasons": reasons,
            "source_refs": sources,
            "held": s in held,
            "reentry": reentry.get(s),
            "opportunity": opportunity.get(s),
            "former": {k: former[s].get(k) for k in (
                "is_currently_held", "reentry_signal", "category", "best_pnl_pct",
                "last_exit_price", "current_price", "pct_above_exit",
            )} if s in former else None,
            "watchlist": watch.get(s),
            "last_seen": _now(),
            "authority": "READ_ONLY_ADVISORY",
        }

    def _count(tag: str) -> int:
        return sum(1 for r in records.values() if tag in r["memberships"])

    return {
        "as_of": _now(),
        "authority": "READ_ONLY_ADVISORY",
        "root": str(root),
        "counts": {
            "HELD": _count("HELD"),
            "FORMER_HOLDING": _count("FORMER_HOLDING"),
            "REENTRY": _count("REENTRY"),
            "WATCHLIST": _count("WATCHLIST"),
            "OPPORTUNITY": _count("OPPORTUNITY"),
            "RESEARCH_ONLY": _count("RESEARCH_ONLY"),
            "RETIRED": _count("RETIRED"),
            "universe_union": len(records),
        },
        "errors": errors,
        "symbols": records,
    }


def get_symbol(universe: dict[str, Any], symbol: str) -> Optional[dict[str, Any]]:
    return (universe.get("symbols") or {}).get(_sym(symbol))
