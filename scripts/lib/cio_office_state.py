"""Live CIO office state for the production material scanner.

Automatically loads verified holdings, last snapshot, capital-plan, and
re-entry desk state. No manual --prev/--curr arguments required.

Authority: READ_ONLY_ADVISORY. No broker / order / stop.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIVE_CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
DEFAULT_API = "http://127.0.0.1:7777"
SNAPSHOT_PATH = PROJECT_ROOT / "data" / "cio" / "holdings_snapshot_latest.json"
OFFICE_STATE_PATH = PROJECT_ROOT / "data" / "cio" / "office_state_latest.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(k: str, default: str = "") -> str:
    return (os.environ.get(k) or default).strip()


def api_base() -> str:
    return _env("CIO_OFFICE_API_BASE", DEFAULT_API).rstrip("/")


def holdings_json_path() -> Path:
    env = _env("TRADEAI_HOLDINGS_JSON")
    if env:
        return Path(env)
    for root in (PROJECT_ROOT, LIVE_CURRENT):
        p = root / "data" / "portfolios" / "state" / "holdings.json"
        if p.is_file():
            return p
    return PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"


def snapshot_path() -> Path:
    env = _env("CIO_HOLDINGS_SNAPSHOT_JSON")
    return Path(env) if env else SNAPSHOT_PATH


def office_state_path() -> Path:
    env = _env("CIO_OFFICE_STATE_JSON")
    return Path(env) if env else OFFICE_STATE_PATH


def _http_json(url: str, timeout: float = 20.0) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
        inner = data["data"]
        if inner.get("ok") is False and data.get("ok") is False:
            return data
        if "ok" in data and "ok" in inner:
            return inner
        return inner
    return data if isinstance(data, dict) else {"ok": False, "error": "non_object", "raw_type": str(type(data))}


def fetch_capital_plan() -> dict[str, Any]:
    try:
        plan = _http_json(f"{api_base()}/api/v2/cio/capital-plan")
        plan.setdefault("ok", True)
        plan["source"] = "api_v2_cio_capital_plan"
        return plan
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": f"capital_plan_unavailable:{exc}", "authority": AUTHORITY}


def fetch_reentry_desk() -> dict[str, Any]:
    try:
        desk = _http_json(f"{api_base()}/api/v2/reentry/decision-desk")
        desk.setdefault("ok", True)
        desk["source"] = "api_v2_reentry_decision_desk"
        return desk
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": f"reentry_unavailable:{exc}", "rows": [], "authority": AUTHORITY}


def fetch_office_home() -> dict[str, Any]:
    try:
        home = _http_json(f"{api_base()}/api/v3/cio/home")
        home.setdefault("ok", True)
        home["source"] = "api_v3_cio_home"
        return home
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": f"office_home_unavailable:{exc}", "authority": AUTHORITY}


def load_holdings_document(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or holdings_json_path()
    if not p.is_file():
        return {"ok": False, "error": f"holdings_missing:{p}", "holdings": []}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"holdings_unreadable:{exc}", "holdings": []}
    if not isinstance(doc, dict):
        return {"ok": False, "error": "holdings_not_object", "holdings": []}
    doc.setdefault("ok", True)
    doc["source_path"] = str(p)
    return doc


def compact_holdings_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in doc.get("holdings") or []:
        if not isinstance(row, dict):
            continue
        if row.get("is_cash"):
            continue
        sym = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if not sym or sym in {"CASH", "USD"}:
            continue
        try:
            value = float(row.get("market_value") or row.get("current_value_usd") or 0)
        except (TypeError, ValueError):
            value = 0.0
        try:
            shares = float(row.get("shares") or row.get("quantity") or 0)
        except (TypeError, ValueError):
            shares = 0.0
        rows.append({
            "symbol": sym,
            "account": str(row.get("account") or row.get("account_id") or "").strip(),
            "market_value": value,
            "shares": shares,
            "updated_at": row.get("updated_at") or doc.get("as_of") or doc.get("generated_at"),
        })
    return rows


def load_previous_snapshot() -> Optional[dict[str, Any]]:
    p = snapshot_path()
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def save_holdings_snapshot(doc: dict[str, Any], *, events: Optional[list] = None) -> Path:
    p = snapshot_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at": _now(),
        "authority": AUTHORITY,
        "as_of": doc.get("as_of") or doc.get("generated_at"),
        "source_path": doc.get("source_path"),
        "holdings": compact_holdings_rows(doc),
        "event_count": len(events or []),
    }
    p.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return p


def save_office_state(state: dict[str, Any]) -> Path:
    p = office_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, default=str) + "\n", encoding="utf-8")
    return p


def load_previous_office_state() -> Optional[dict[str, Any]]:
    p = office_state_path()
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def classify_reentry_rows(desk: dict[str, Any]) -> dict[str, Any]:
    rows = desk.get("rows") if isinstance(desk.get("rows"), list) else []
    ready: list[str] = []
    near: list[str] = []
    wait: list[str] = []
    wash: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        intel = row.get("intel") if isinstance(row.get("intel"), dict) else {}
        state = str(intel.get("state") or row.get("state") or "").upper()
        if row.get("wash_blocked"):
            wash.append(sym)
            continue
        if "READY" in state:
            ready.append(sym)
        elif "NEAR" in state:
            near.append(sym)
        else:
            wait.append(sym)
    return {
        "n": len(rows),
        "ready": sorted(set(ready)),
        "near": sorted(set(near)),
        "wait": sorted(set(wait)),
        "wash_blocked": sorted(set(wash)),
        "actionable_count": int((desk.get("freshness") or {}).get("actionable_count") or len(ready)),
        "call": "RE_ENTER" if ready else ("NEAR" if near else "WAIT"),
    }


def cash_posture(plan: dict[str, Any]) -> dict[str, Any]:
    band = plan.get("cash_policy_band") if isinstance(plan.get("cash_policy_band"), dict) else {}
    uses = plan.get("capital_uses") if isinstance(plan.get("capital_uses"), dict) else {}
    return {
        "portfolio_value_usd": plan.get("portfolio_value_usd"),
        "cash_total_usd": plan.get("cash_total_usd"),
        "cash_reserved_usd": plan.get("cash_reserved_usd"),
        "cash_investable_usd": plan.get("cash_investable_usd"),
        "cash_earmarked_redeploy_usd": plan.get("cash_earmarked_redeploy_usd"),
        "cash_free_unearmarked_usd": plan.get("cash_free_unearmarked_usd"),
        "cash_policy_band": band,
        "cash_posture_status": plan.get("cash_posture_status"),
        "net_recommended_deploy_usd": plan.get("net_recommended_deploy_usd"),
        "net_recommended_raise_usd": plan.get("net_recommended_raise_usd"),
        "deployable_usd": plan.get("deployable_usd"),
        "adds_usd": uses.get("adds_usd"),
        "reentry_usd": uses.get("reentry_usd"),
        "new_positions_usd": uses.get("new_positions_usd"),
        "new_positions": uses.get("new_positions") or [],
        "digest": plan.get("digest"),
        "act_now_count": ((plan.get("freshness_materiality_gate") or {}).get("act_now_count")
                          if isinstance(plan.get("freshness_materiality_gate"), dict) else None),
    }


def load_live_office() -> dict[str, Any]:
    """Single chokepoint for current office truth. Fail-soft per source."""
    holdings = load_holdings_document()
    plan = fetch_capital_plan()
    reentry = fetch_reentry_desk()
    home = fetch_office_home()
    prev_snap = load_previous_snapshot()
    prev_state = load_previous_office_state()
    return {
        "authority": AUTHORITY,
        "as_of": _now(),
        "holdings": holdings,
        "previous_snapshot": prev_snap,
        "previous_office_state": prev_state,
        "capital_plan": plan,
        "reentry": reentry,
        "office_home": home,
        "baseline_needed": prev_snap is None,
    }
