"""
aegis_surveillance.py — Aegis Portfolio Surveillance Agent

Background service that runs after the daily pipeline and recovery watch.
Analyzes portfolio state and writes observations/recommendations to shared Postgres.

All outputs are marked with model='aegis', source='aegis:surveillance'.
Aegis does NOT trade, approve, or modify positions.

Entry point: main()
"""
from __future__ import annotations
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v

AGENT_NAME = "aegis"
AGENT_SOURCE = "aegis:surveillance"


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        return _execute(sql, params, fetch=fetch)
    except Exception:
        return None


def _db_write(sql, params=None):
    try:
        from db_adapter import _get_conn
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        conn.commit()
        return True
    except Exception as e:
        print(f"  [aegis] DB write error: {e}")
        return False


def _write_observation(symbol, category, observation, evidence, confidence=1.0):
    """Write an Aegis observation to advisor_observations with dedupe."""
    dedupe = f"aegis:{category}:{symbol or 'portfolio'}:{date.today()}"
    return _db_write(
        """INSERT INTO advisor_observations
           (observation_date, symbol, category, observation, evidence, source, confidence, model, freshness_hash)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (observation_date, symbol, category, source) DO UPDATE
           SET observation = EXCLUDED.observation, evidence = EXCLUDED.evidence,
               confidence = EXCLUDED.confidence""",
        (date.today(), symbol, category, observation,
         json.dumps(evidence, default=str), AGENT_SOURCE, confidence, AGENT_NAME,
         dedupe[:12])
    )


# ── Surveillance modules ─────────────────────────────────────────────────

def scan_concentration(holdings, total_value):
    """Check single-name and sector concentration."""
    observations = []
    for p in holdings:
        pct = (p.get("market_value", 0) / total_value * 100) if total_value > 0 else 0
        sym = p.get("symbol", "")
        if pct > 20:
            obs = f"{sym} at {pct:.1f}% of portfolio — exceeds 20% concentration limit. Immediate review recommended."
            _write_observation(sym, "concentration", obs, {"pct": round(pct, 1), "market_value": p.get("market_value", 0), "threshold": 20}, 0.95)
            observations.append({"symbol": sym, "type": "concentration", "severity": "high", "pct": round(pct, 1)})
        elif pct > 15:
            obs = f"{sym} at {pct:.1f}% — approaching concentration limit."
            _write_observation(sym, "concentration", obs, {"pct": round(pct, 1)}, 0.80)
            observations.append({"symbol": sym, "type": "concentration", "severity": "medium", "pct": round(pct, 1)})
    return observations


def scan_stop_integrity(rm_data):
    """Check stop protection status."""
    observations = []
    positions = rm_data.get("positions", [])
    triggered = [p for p in positions if p.get("status") == "TRIGGERED"]
    unprotected = [p for p in positions if p.get("status") == "NO STOP" and (p.get("market_value") or 0) > 5000 and p.get("account") != "fidelity_401k"]
    danger = [p for p in positions if p.get("status") == "DANGER"]

    if triggered:
        syms = ", ".join(p.get("symbol", "") for p in triggered)
        obs = f"{len(triggered)} stop(s) triggered: {syms}. Immediate stop review required."
        _write_observation(None, "stop_integrity", obs, {"triggered": [p.get("symbol") for p in triggered], "count": len(triggered)}, 0.95)
        observations.append({"type": "stop_triggered", "count": len(triggered), "symbols": syms})

    if unprotected:
        total_mv = sum(p.get("market_value", 0) for p in unprotected)
        obs = f"{len(unprotected)} position(s) without stops totaling ${total_mv:,.0f}."
        _write_observation(None, "stop_integrity", obs, {"unprotected_count": len(unprotected), "total_value": total_mv}, 0.85)
        observations.append({"type": "unprotected", "count": len(unprotected), "value": total_mv})

    if danger:
        obs = f"{len(danger)} position(s) in danger zone."
        _write_observation(None, "stop_danger", obs, {"danger": [p.get("symbol") for p in danger]}, 0.90)
        observations.append({"type": "danger", "count": len(danger)})

    return observations


def scan_income_architecture(div_data, total_value):
    """Check dividend/income coverage."""
    observations = []
    annual = div_data.get("total_annual", 0)
    portfolio_yield = (annual / total_value * 100) if total_value > 0 else 0

    if portfolio_yield < 1.0 and total_value > 100000:
        obs = f"Portfolio yield {portfolio_yield:.2f}% — below 1% target. Consider income-producing additions."
        _write_observation(None, "income", obs, {"yield_pct": round(portfolio_yield, 2), "annual_income": annual}, 0.70)
        observations.append({"type": "low_yield", "yield_pct": round(portfolio_yield, 2)})

    return observations


def scan_heat_posture(rm_data):
    """Check overall risk heat."""
    observations = []
    heat = rm_data.get("portfolio_heat_pct", 0)
    if heat > 7:
        obs = f"Portfolio heat at {heat:.1f}% — elevated risk. Consider reducing exposure."
        _write_observation(None, "risk_posture", obs, {"heat_pct": heat}, 0.85)
        observations.append({"type": "high_heat", "heat_pct": heat})
    return observations


# ── Main entry point ─────────────────────────────────────────────────────

def main():
    print(f"[aegis] Surveillance starting — {datetime.now().isoformat()}")

    h = _load_json(STATE_DIR / "holdings.json") or {}
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    dc = _load_json(STATE_DIR / "dividend_calendar.json") or {}

    holdings = [p for p in h.get("holdings", []) if not p.get("is_cash") and (p.get("market_value") or 0) > 50]
    total_value = sum(p.get("market_value", 0) for p in h.get("holdings", []))

    all_obs = []

    # 1. Concentration
    conc = scan_concentration(holdings, total_value)
    all_obs.extend(conc)
    print(f"  Concentration: {len(conc)} findings")

    # 2. Stop integrity
    stops = scan_stop_integrity(rm)
    all_obs.extend(stops)
    print(f"  Stop integrity: {len(stops)} findings")

    # 3. Income architecture
    income = scan_income_architecture(dc, total_value)
    all_obs.extend(income)
    print(f"  Income: {len(income)} findings")

    # 4. Risk heat
    heat = scan_heat_posture(rm)
    all_obs.extend(heat)
    print(f"  Risk posture: {len(heat)} findings")

    print(f"[aegis] Surveillance complete — {len(all_obs)} total findings — {datetime.now().isoformat()}")
    return {"findings": len(all_obs), "details": all_obs}


if __name__ == "__main__":
    main()
