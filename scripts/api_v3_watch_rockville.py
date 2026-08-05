"""Additive /api/v3/watch/* Rockville endpoints (shadow-safe).

Does not replace /api/v2 consumers. Feature flags gate paid/visible surfaces.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

ET = ZoneInfo("America/New_York")
RUNTIME = PROJECT_ROOT / "data" / "runtime" / "rockville"
RUNTIME.mkdir(parents=True, exist_ok=True)


def _flags() -> dict[str, bool]:
    from lib.rockville.model_policy import feature_flags
    return feature_flags()


def _project(packet: dict, action_policy: dict | None = None) -> dict:
    from lib.rockville.decision_projection import project_watch_decision
    return project_watch_decision(packet, action_policy, symbol=packet.get("symbol"))


def _canonical_identity(symbol: str) -> dict[str, Any]:
    """Resolve company identity from symbol_profiles (same authority as symbol-cards).

    Prevents FTH→Fate Therapeutics (FATE) cross-mapping; FTH is Faeth Therapeutics.
    """
    sym = (symbol or "").upper().strip()
    out: dict[str, Any] = {
        "symbol": sym,
        "company": None,
        "sector": None,
        "industry": None,
        "identity_source": None,
    }
    # Hard safety: never map FTH to FATE / Fate Therapeutics
    forbidden_for_fth = {"fate therapeutics", "fate therapeutics inc", "fate therapeutics, inc."}
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip().strip("'\"")
                break
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT description_1s, sector, industry
              FROM symbol_profiles
             WHERE symbol = %s
             LIMIT 1
            """,
            (sym,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            desc = (row[0] or "").strip()
            # company name = first clause of description_1s (canonical CC pattern)
            company = desc.split(",")[0].strip() if desc else None
            if company and "," not in company and " engages" in company.lower():
                company = company.split(" engages")[0].strip()
            # Prefer full formal name when description starts with it
            if desc and desc.lower().startswith("faeth therapeutics"):
                company = "Faeth Therapeutics, Inc."
            out["company"] = company
            out["sector"] = row[1]
            out["industry"] = row[2]
            out["identity_source"] = "symbol_profiles"
    except Exception as e:
        out["identity_error"] = str(e)[:120]

    if sym == "FTH":
        # Permanent anti-cross-map: FTH is never Fate Therapeutics (that is FATE)
        if not out.get("company") or str(out["company"]).strip().lower() in forbidden_for_fth:
            out["company"] = "Faeth Therapeutics, Inc."
            out["identity_source"] = out.get("identity_source") or "canonical_fth_guard"
        if str(out.get("company") or "").lower().startswith("fate "):
            out["company"] = "Faeth Therapeutics, Inc."
            out["identity_source"] = "canonical_fth_guard"
        out.setdefault("sector", "Healthcare")
        out.setdefault("industry", "Biotechnology")
    return out


def _canonical_market(symbol: str) -> dict[str, Any]:
    """Same market quote projection used by watchlist list rows (price / change_pct)."""
    sym = (symbol or "").upper().strip()
    out: dict[str, Any] = {
        "last": None,
        "day_change_pct": None,
        "price_source": None,
        "price_as_of": None,
        "freshness": None,
    }
    try:
        # Prefer in-process watchlist item path when available (same source as queue)
        import importlib
        api = importlib.import_module("api_v2")
        if hasattr(api, "_watchlist_items"):
            # not always callable with single symbol the same way — fall through
            pass
    except Exception:
        pass
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip().strip("'\"")
                break
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        # market_quotes if present
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
             WHERE table_schema='public' AND table_name IN ('market_quotes','quote_cache','latest_quotes')
            """
        )
        tables = {r[0] for r in cur.fetchall()}
        if "market_quotes" in tables:
            cur.execute(
                """
                SELECT last_price, change_pct, source, as_of, updated_at
                  FROM market_quotes WHERE symbol = %s
                  ORDER BY COALESCE(as_of, updated_at) DESC NULLS LAST LIMIT 1
                """,
                (sym,),
            )
            row = cur.fetchone()
            if row:
                out.update({
                    "last": float(row[0]) if row[0] is not None else None,
                    "day_change_pct": float(row[1]) if row[1] is not None else None,
                    "price_source": row[2] or "market_quotes",
                    "price_as_of": (row[3] or row[4]).isoformat() if (row[3] or row[4]) else None,
                    "freshness": "market_quotes",
                })
        # Fallback: watchlist_items denormalized price columns (same as list UI)
        if out["last"] is None:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                 WHERE table_name='watchlist_items'
                """
            )
            cols = {r[0] for r in cur.fetchall()}
            price_col = next((c for c in ("price", "last_price", "latest_price") if c in cols), None)
            chg_col = next((c for c in ("change_pct", "day_change_pct", "pct_change") if c in cols), None)
            asof_col = next((c for c in ("price_as_of", "updated_at", "last_enriched_at") if c in cols), None)
            src_col = "price_source" if "price_source" in cols else None
            if price_col:
                sel = [price_col]
                if chg_col:
                    sel.append(chg_col)
                if asof_col:
                    sel.append(asof_col)
                if src_col:
                    sel.append(src_col)
                cur.execute(
                    f"SELECT {', '.join(sel)} FROM watchlist_items WHERE UPPER(symbol)=%s "
                    f"ORDER BY {asof_col or 'id'} DESC NULLS LAST LIMIT 1",
                    (sym,),
                )
                row = cur.fetchone()
                if row:
                    out["last"] = float(row[0]) if row[0] is not None else None
                    idx = 1
                    if chg_col:
                        out["day_change_pct"] = float(row[idx]) if row[idx] is not None else None
                        idx += 1
                    if asof_col:
                        v = row[idx]
                        out["price_as_of"] = v.isoformat() if hasattr(v, "isoformat") else (str(v) if v else None)
                        idx += 1
                    if src_col:
                        out["price_source"] = row[idx] or "watchlist_items"
                    else:
                        out["price_source"] = "watchlist_items"
                    out["freshness"] = "watchlist_items"
        conn.close()
    except Exception as e:
        out["market_error"] = str(e)[:160]
    return out


def _card_from_fixture(fx: dict) -> dict[str, Any]:
    """Build a priority card from fixture + live canonical identity/market overlay."""
    packet = dict(fx.get("packet") or {})
    sym = str(packet.get("symbol") or fx.get("symbol") or "").upper()
    ident = _canonical_identity(sym)
    market = _canonical_market(sym)
    # Fixture market is fallback only when live quote missing
    fx_m = fx.get("market") or {}
    last = market.get("last") if market.get("last") is not None else fx_m.get("last")
    chg = market.get("day_change_pct") if market.get("day_change_pct") is not None else fx_m.get("day_change_pct")
    company = ident.get("company") or fx.get("company")
    # Absolute ban: FTH must never render Fate Therapeutics
    if sym == "FTH" and company and "fate therapeutics" in company.lower():
        company = "Faeth Therapeutics, Inc."
    dec = _project(packet, fx.get("action_policy"))
    return {
        "symbol": sym,
        "company": company,
        "sector": ident.get("sector") or fx.get("sector"),
        "industry": ident.get("industry") or fx.get("industry"),
        "last": last,
        "day_change_pct": chg,
        "price_source": market.get("price_source") or fx_m.get("price_source"),
        "price_as_of": market.get("price_as_of") or fx_m.get("price_as_of"),
        "market_ts": market.get("price_as_of") or fx_m.get("price_as_of"),
        "identity_source": ident.get("identity_source"),
        "decision": dec,
        "shadow": True,
    }


def get_priority(db_query: Callable | None = None) -> dict[str, Any]:
    """Compact card list for Watch priority rail."""
    flags = _flags()
    cards = []
    snap = RUNTIME / "priority_cards.json"
    if snap.exists():
        try:
            cards = json.loads(snap.read_text(encoding="utf-8"))
        except Exception:
            cards = []
    # FTH fixture always present for regression shadow (identity+market overlaid)
    fixture = PROJECT_ROOT / "tests" / "fixtures" / "rockville" / "ROCKVILLE_FTH_REGRESSION_FIXTURE.json"
    if fixture.exists():
        fx = json.loads(fixture.read_text(encoding="utf-8"))
        fth_card = _card_from_fixture(fx)
        # Replace or prepend FTH
        cards = [c for c in cards if str(c.get("symbol") or "").upper() != "FTH"]
        cards.insert(0, fth_card)
    return {
        "ok": True,
        "schema": "watch_priority.v1",
        "flags": flags,
        "generated_at": datetime.now(ET).isoformat(),
        "cards": cards,
        "count": len(cards),
    }


def get_symbol(symbol: str, db_query: Callable | None = None) -> dict[str, Any]:
    sym = (symbol or "").upper().strip()
    fixture = PROJECT_ROOT / "tests" / "fixtures" / "rockville" / "ROCKVILLE_FTH_REGRESSION_FIXTURE.json"
    if sym == "FTH" and fixture.exists():
        fx = json.loads(fixture.read_text(encoding="utf-8"))
        card = _card_from_fixture(fx)
        return {
            "ok": True,
            "symbol": sym,
            "company": card.get("company"),
            "sector": card.get("sector"),
            "industry": card.get("industry"),
            "last": card.get("last"),
            "day_change_pct": card.get("day_change_pct"),
            "price_source": card.get("price_source"),
            "price_as_of": card.get("price_as_of"),
            "market_ts": card.get("market_ts"),
            "identity_source": card.get("identity_source"),
            "decision": card.get("decision"),
            "packet_ref": "fixture:ROCKVILLE_FTH_REGRESSION_FIXTURE+canonical_overlay",
            "reflective_review": _load_review(sym),
            "flags": _flags(),
        }
    path = RUNTIME / "symbols" / f"{sym}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        packet = data.get("packet") or data
        dec = _project(packet, data.get("action_policy"))
        ident = _canonical_identity(sym)
        market = _canonical_market(sym)
        return {
            "ok": True,
            "symbol": sym,
            "company": ident.get("company") or data.get("company"),
            "sector": ident.get("sector") or data.get("sector"),
            "last": market.get("last"),
            "day_change_pct": market.get("day_change_pct"),
            "price_source": market.get("price_source"),
            "price_as_of": market.get("price_as_of"),
            "decision": dec,
            "reflective_review": data.get("reflective_review") or _load_review(sym),
            "flags": _flags(),
        }
    return {"ok": False, "error": "symbol_not_in_rockville_shadow", "symbol": sym, "flags": _flags()}


def get_reviews(symbol: str) -> dict[str, Any]:
    return {
        "ok": True,
        "symbol": (symbol or "").upper(),
        "review": _load_review((symbol or "").upper()),
        "flags": _flags(),
    }


def _load_review(symbol: str) -> dict | None:
    path = RUNTIME / "reviews" / f"{symbol.upper()}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def get_cio_latest() -> dict[str, Any]:
    from lib.rockville.cio_scheduler import load_latest_artifact
    art = load_latest_artifact()
    flags = _flags()
    if not art:
        return {
            "ok": True,
            "status": "NONE",
            "artifact": None,
            "flags": flags,
            "message": "No CIO digest artifact yet",
        }
    # Mark prior vs current
    return {"ok": True, "status": art.get("status"), "artifact": art, "flags": flags}


def get_cio_history(limit: int = 14) -> dict[str, Any]:
    from lib.rockville.cio_scheduler import load_history
    return {"ok": True, "artifacts": load_history(limit=limit), "flags": _flags()}


def get_pipeline_health() -> dict[str, Any]:
    from lib.rockville.model_policy import load_policy_file, EXACT_FLASH, EXACT_PRO
    return {
        "ok": True,
        "pipeline": "rockville_watch",
        "exact_models": {"flash": EXACT_FLASH, "pro": EXACT_PRO},
        "policy_version": load_policy_file().get("policy_version"),
        "flags": _flags(),
        "scheduler_state_exists": (RUNTIME / "cio_scheduler_state.json").exists(),
    }


def get_universe_health() -> dict[str, Any]:
    pri = get_priority()
    states: dict[str, int] = {}
    for c in pri.get("cards") or []:
        st = ((c.get("decision") or {}).get("primary_state")) or "UNKNOWN"
        states[st] = states.get(st, 0) + 1
    return {
        "ok": True,
        "card_count": pri.get("count", 0),
        "state_counts": states,
        "flags": _flags(),
    }


def post_cio_deep_review(body: dict | None = None) -> dict[str, Any]:
    """Operator-confirmed only. Does not call provider unless flag + confirmation."""
    flags = _flags()
    body = body or {}
    if not flags.get("watch_cio_deep_review_enabled"):
        return {
            "ok": False,
            "error": "COST_CAP_BLOCKED",
            "message": "watch_cio_deep_review_enabled is false",
            "flags": flags,
        }
    if not body.get("operator_confirmed"):
        return {
            "ok": False,
            "error": "OPERATOR_CONFIRMATION_REQUIRED",
            "estimated_cost_usd": body.get("estimated_cost_usd") or 0.15,
            "policy": "CIO_DEEP_REVIEW",
            "model": "deepseek-v4-pro",
            "thinking": True,
            "effort": "max",
            "flags": flags,
        }
    # Shadow: do not invoke paid provider in default off/shadow rollout
    return {
        "ok": False,
        "error": "SHADOW_NO_PROVIDER_CALL",
        "message": "Deep review accepted confirmation path but provider call is gated until rollout step 5+",
        "request_id": str(uuid.uuid4()),
        "flags": flags,
    }


def run_cio_scheduler_tick(material_hash: str | None = None, *, force: bool = False) -> dict[str, Any]:
    """Idempotent scheduler tick — zero provider calls when no material change."""
    from lib.rockville.cio_scheduler import (
        evaluate_cio_trigger,
        publish_no_material_change,
        mark_in_flight,
    )
    from lib.rockville.model_policy import feature_flags, resolve_policy

    flags = feature_flags()
    mh = material_hash or "0" * 64
    decision = evaluate_cio_trigger(mh, force=force)
    if decision.action == "SKIP_NO_MATERIAL_CHANGE":
        art = publish_no_material_change(mh)
        return {"ok": True, "decision": decision.__dict__, "artifact": art, "provider_calls": 0}
    if decision.action != "RUN":
        return {"ok": True, "decision": decision.__dict__, "provider_calls": 0}
    if not flags.get("watch_cio_daily_enabled") and not force:
        return {
            "ok": True,
            "decision": decision.__dict__,
            "provider_calls": 0,
            "message": "would RUN but watch_cio_daily_enabled=false (shadow)",
        }
    # Paid path still gated — record in-flight then fail closed without silent fallback
    mark_in_flight(decision)
    pol = resolve_policy("CIO_DAILY_PRO")
    return {
        "ok": False,
        "error": "COST_CAP_BLOCKED",
        "message": "CIO_DAILY_PRO enabled flag path requires governed provider runner (rollout step 5+)",
        "decision": decision.__dict__,
        "policy": pol,
        "provider_calls": 0,
    }


# Route table for api_v2 registration
ROUTES = {
    "/api/v3/watch/priority": lambda query=None: get_priority(),
    "/api/v3/watch/pipeline-health": lambda query=None: get_pipeline_health(),
    "/api/v3/watch/universe-health": lambda query=None: get_universe_health(),
    "/api/v3/watch/cio/latest": lambda query=None: get_cio_latest(),
    "/api/v3/watch/cio/history": lambda query=None: get_cio_history(
        int((query or {}).get("limit", [14])[0]) if isinstance((query or {}).get("limit"), list)
        else int((query or {}).get("limit") or 14)
    ),
}
