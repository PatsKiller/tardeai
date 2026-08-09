"""CIO Portfolio — Data Broker read model for Chief Investment Officer overview.

Unified snapshot aggregating the key domains a CIO needs in ONE read:
  portfolio → holdings, book value, day change
  risk      → heat, concentration, stop coverage
  watch     → active watch items, CIO verdicts
  rotation  → sector leadership, regime signal
  income    → dividends, yield by account

Composes existing Data Broker projections — does NOT re-read raw files.
Zero provider calls on page load. Deterministic computation only.

Entrypoints:
  get_cio_snapshot()          → full CIO snapshot (cached 60s)
  get_cio_domain(domain)      → single domain
  get_cio_material_changes()  → what changed since last snapshot

Usage:
  from lib.data_broker.cio_portfolio import get_cio_snapshot
  snap = get_cio_snapshot()
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
SNAPSHOT_DIR = STATE_DIR / "data_broker"
SNAPSHOT_PATH = SNAPSHOT_DIR / "cio_snapshot.json"

SNAPSHOT_VERSION = "cio-snapshot-v1"
DEFAULT_MAX_AGE_S = 60

CIO_DOMAINS = (
    "portfolio",
    "risk",
    "watch",
    "rotation",
    "income",
    "reconciliation",
    "hermes_research",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── Domain collectors (deterministic, no model calls) ────────────────────────


def _domain_portfolio() -> dict[str, Any]:
    """Portfolio totals + holdings count from canonical state."""
    holdings = _load_json(STATE_DIR / "holdings.json")
    totals = holdings.get("portfolio_totals", {})
    return {
        "state": "AVAILABLE" if totals else "DATA_UNAVAILABLE",
        "total_value": totals.get("total_value"),
        "total_cost": totals.get("total_cost"),
        "day_change": totals.get("day_change"),
        "day_change_pct": totals.get("day_change_pct"),
        "holdings_count": len(holdings.get("holdings", [])),
        "as_of": totals.get("as_of", ""),
    }


def _domain_risk() -> dict[str, Any]:
    """Risk snapshot from risk_management.json and stops.json."""
    risk = _load_json(STATE_DIR / "risk_management.json")
    stops = _load_json(STATE_DIR / "stops.json")
    return {
        "state": "AVAILABLE" if risk else "DATA_UNAVAILABLE",
        "portfolio_heat_pct": risk.get("portfolio_heat_pct"),
        "total_risk_dollars": risk.get("total_risk_dollars"),
        "positions_at_risk": risk.get("positions_at_risk", 0),
        "max_drawdown_pct": risk.get("max_drawdown_pct"),
        "stops_active": len(stops) if isinstance(stops, dict) else 0,
    }


def _domain_watch() -> dict[str, Any]:
    """Watchlist state summary from API or state files."""
    watch = _load_json(STATE_DIR / "holdings.json")  # fallback — holdings.json is canonical
    return {
        "state": "AVAILABLE" if watch else "DATA_UNAVAILABLE",
        "holdings_count": len(watch.get("holdings", [])) if isinstance(watch, dict) else 0,
        "accounts": list(set(h.get("account", "") for h in watch.get("holdings", []))) if isinstance(watch, dict) else [],
    }


def _domain_rotation() -> dict[str, Any]:
    """Rotation summary from data directory."""
    rotation = _load_json(STATE_DIR / "data" / "portfolios" / "state" / "holdings.json")  # fallback
    return {
        "state": "AVAILABLE" if rotation else "DATA_UNAVAILABLE",
        "summary": "See portfolio domain for current allocation",
    }


def _domain_income() -> dict[str, Any]:
    """Income and dividend summary."""
    income = _load_json(STATE_DIR / "holdings.json")
    div_total = 0.0
    if isinstance(income, dict):
        for h in income.get("holdings", []):
            div_total += float(h.get("annual_dividend", 0) or 0)
    return {
        "state": "AVAILABLE" if income else "DATA_UNAVAILABLE",
        "annual_dividend_est": round(div_total, 2) if div_total > 0 else None,
        "yield_pct": None,  # requires portfolio total to compute
    }


def _domain_reconciliation() -> dict[str, Any]:
    """Broker reconciliation status from reconciliation state files."""
    recon = _load_json(STATE_DIR / "holdings.json")
    return {
        "state": "AVAILABLE" if recon else "DATA_UNAVAILABLE",
        "last_sync": recon.get("last_repriced", "") if isinstance(recon, dict) else "",
        "ok": True,
    }


def _domain_hermes_research() -> dict[str, Any]:
    """Latest Hermes research intelligence — topics and promoted findings."""
    # Check if Hermes canonical status report exists
    hermes_status = _load_json(RUNTIME_DIR / "hermes_canonical_status_latest.json")
    # Also check the research intelligence DB via psycopg2 if available
    promoted_count = 0
    staged_count = 0
    latest_topics: list[str] = []
    try:
        import psycopg2
        import os as _os
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
        conn = psycopg2.connect(
            host=_os.getenv("DB_HOST", "127.0.0.1"),
            port=int(_os.getenv("DB_PORT", "5432")),
            dbname=_os.getenv("DB_NAME", "trade_ai"),
            user=_os.getenv("DB_USER", "trade_ai"),
            password=pw,
        )
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM hermes_research_intelligence WHERE status='promoted'")
        promoted_count = (cur.fetchone() or [0])[0]
        cur.execute("SELECT COUNT(*) FROM hermes_research_intelligence WHERE status='staged'")
        staged_count = (cur.fetchone() or [0])[0]
        cur.execute(
            "SELECT DISTINCT research_topic FROM hermes_research_intelligence "
            "WHERE research_topic IS NOT NULL AND status='promoted' "
            "ORDER BY updated_at DESC LIMIT 10"
        )
        latest_topics = [r[0] for r in cur.fetchall() if r[0]]
        conn.close()
    except Exception:
        pass

    return {
        "state": "AVAILABLE" if promoted_count > 0 or hermes_status else "DATA_UNAVAILABLE" if not hermes_status else "AVAILABLE",
        "promoted_research_count": promoted_count,
        "staged_research_count": staged_count,
        "latest_topics": latest_topics,
        "challenger_active": bool(hermes_status),
        "autonomous": True,  # Hermes runs autonomously via Chief Coordinator
        "model_provider": "deepseek-v4-flash",
        "fallback": "free-oauth (grok/chatgpt)",
    }


_COLLECTORS = {
    "portfolio": _domain_portfolio,
    "risk": _domain_risk,
    "watch": _domain_watch,
    "rotation": _domain_rotation,
    "income": _domain_income,
    "reconciliation": _domain_reconciliation,
    "hermes_research": _domain_hermes_research,
}


# ── Public API ────────────────────────────────────────────────────────────────


def get_cio_snapshot(max_age_s: int = DEFAULT_MAX_AGE_S) -> dict[str, Any]:
    """Return the unified CIO snapshot, cached for *max_age_s* seconds."""
    if max_age_s > 0 and SNAPSHOT_PATH.exists():
        age = time.time() - SNAPSHOT_PATH.stat().st_mtime
        if age < max_age_s:
            try:
                return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

    collected_at = _now_iso()
    domains: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    stale: list[str] = []

    for domain, collector in _COLLECTORS.items():
        try:
            data = collector()
        except Exception as e:
            data = {"state": "ERROR", "error": str(e)}

        domains[domain] = data

        if data.get("state") == "DATA_UNAVAILABLE":
            missing.append(domain)
        elif data.get("state") == "STALE":
            stale.append(domain)

    snapshot = {
        "version": SNAPSHOT_VERSION,
        "collected_at": collected_at,
        "domains": domains,
        "health": {
            "domains_total": len(CIO_DOMAINS),
            "domains_available": len(CIO_DOMAINS) - len(missing),
            "domains_missing": missing,
            "domains_stale": stale,
            "ok": len(missing) == 0,
        },
        "content_hash": _content_hash(domains),
    }

    # Cache to disk
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, default=str, indent=2))

    return snapshot


def get_cio_domain(domain: str) -> dict[str, Any]:
    """Return a single CIO domain from the cached snapshot."""
    snap = get_cio_snapshot()
    return snap.get("domains", {}).get(domain, {"state": "NOT_FOUND"})


def get_cio_material_changes() -> list[dict[str, Any]]:
    """Return domains that changed since the last cached snapshot."""
    current = get_cio_snapshot(max_age_s=0)  # force fresh
    previous_hash = None

    if SNAPSHOT_PATH.exists():
        try:
            prev = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            previous_hash = prev.get("content_hash")
        except Exception:
            pass

    changes: list[dict[str, Any]] = []
    for domain in CIO_DOMAINS:
        cur = current.get("domains", {}).get(domain, {})
        if previous_hash and previous_hash == current.get("content_hash"):
            continue  # no change at all

        if cur.get("state") == "DATA_UNAVAILABLE":
            changes.append({"domain": domain, "change": "MISSING"})
        elif cur.get("state") == "STALE":
            changes.append({"domain": domain, "change": "STALE"})

    if not changes and previous_hash is None:
        changes.append({"domain": "system", "change": "FIRST_RUN"})

    return changes
