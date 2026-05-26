# Source Export: scripts/stop_alert_assembler.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/stop_alert_assembler.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `e0bf770326c733224c46e77af1a50ac56a88e2c89c4bb6b76d6348ffd119f44b` |
| **File Size** | 5047 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""stop_alert_assembler.py — Assemble data for rich stop-triggered decision alerts.

Pure data assembly. No side effects. Caller decides what to send.
No trades, no orders, no live execution.
"""
import json, logging, os, sys
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger(__name__)
BASE_URL = "http://localhost:7777"


def _api_get(path):
    try:
        req = Request(f"{BASE_URL}{path}", method="GET")
        resp = urlopen(req, timeout=10)
        return json.loads(resp.read())
    except Exception as e:
        log.warning(f"API {path} failed: {e}")
        return {}


def assemble_stop_alert_data(symbol, account=""):
    """Fetch and assemble everything needed for a stop decision alert."""

    # 1. Risk positions
    risk_data = _api_get("/api/v2/risk").get("data", {})
    positions = risk_data.get("positions", [])
    pos = next((p for p in positions if p["symbol"] == symbol), None)
    if not pos:
        return None

    current_price = pos.get("current_price", 0)
    stop_price = pos.get("stop_price", 0)
    market_value = pos.get("market_value", 0)

    # 2. Tax lots for cost basis + P&L
    lots_resp = _api_get("/api/v2/tax-lots")
    lots_data = lots_resp.get("data", lots_resp)
    lots = lots_data.get("lots", lots_data.get("positions", [])) if isinstance(lots_data, dict) else lots_data if isinstance(lots_data, list) else []
    lot = next((l for l in lots if l.get("symbol") == symbol), None)

    cost_basis = lot.get("cost_basis") if lot else None
    unrealized_gain = lot.get("unrealized_gain") if lot else None
    gain_pct = lot.get("gain_pct") if lot else None
    holding_period = lot.get("holding_period", "unknown") if lot else "unknown"
    acquired_date = lot.get("acquired") if lot else None
    shares = lot.get("shares") if lot else None
    account = lot.get("account", account) if lot else account

    # 3. Market regime
    regime = _api_get("/api/v2/risk-regime/status").get("data", {})
    regime_label = regime.get("regime_label", "unknown")
    regime_confidence = regime.get("confidence", 0)
    trend_state = regime.get("trend_state", "unknown")

    # 4. Portfolio context
    portfolio_heat = risk_data.get("portfolio_heat_pct", 0)
    triggered_positions = [p for p in positions if p.get("status") == "TRIGGERED"]
    triggered_count = len(triggered_positions)

    # 5. Compute P&L scenarios
    current_pnl_dollars = None
    current_pnl_pct = None
    if cost_basis and current_price and shares:
        current_pnl_dollars = (current_price * shares) - cost_basis
        current_pnl_pct = (current_pnl_dollars / cost_basis * 100) if cost_basis else 0
    elif unrealized_gain is not None:
        current_pnl_dollars = unrealized_gain
        current_pnl_pct = gain_pct

    stop_pnl_dollars = None
    if cost_basis and stop_price and shares:
        stop_pnl_dollars = (stop_price * shares) - cost_basis

    pct_below_stop = pos.get("distance_pct", pos.get("distance_to_stop_pct", 0))

    # 6. Tax note
    tax_note = ""
    if holding_period == "short" and current_pnl_dollars is not None:
        if current_pnl_dollars < 0:
            tax_note = "SHORT-TERM LOSS — deductible up to $3K/yr against ordinary income"
        else:
            tax_note = "SHORT-TERM GAIN — taxed as ordinary income if exited"
    elif holding_period == "long" and current_pnl_dollars is not None:
        if current_pnl_dollars < 0:
            tax_note = "LONG-TERM LOSS — deductible, favorable rate"
        else:
            tax_note = "LONG-TERM GAIN — favorable 15-20% rate"

    # 7. Sector context
    defense = {"RTX", "LHX", "LMT", "NOC", "LDOS", "AVAV", "KBR",
               "CACI", "BAH", "SAIC", "GD", "HII", "TXT", "HEI"}
    sector_note = ""
    if symbol in defense:
        n_def = sum(1 for p in triggered_positions if p["symbol"] in defense)
        sector_note = f"Defense sector rotation — {n_def} defense stops triggered."

    return {
        "symbol": symbol,
        "account": account,
        "current_price": current_price,
        "stop_price": stop_price,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "shares": shares,
        "rsi": pos.get("rsi"),
        "day_change_pct": pos.get("day_change_pct", 0),
        "pct_below_stop": pct_below_stop,
        "current_pnl_dollars": current_pnl_dollars,
        "current_pnl_pct": current_pnl_pct,
        "stop_pnl_dollars": stop_pnl_dollars,
        "holding_period": holding_period,
        "acquired_date": acquired_date,
        "tax_note": tax_note,
        "sector_note": sector_note,
        "regime_label": regime_label,
        "regime_confidence": regime_confidence,
        "trend_state": trend_state,
        "portfolio_heat_pct": portfolio_heat,
        "portfolio_triggered_count": triggered_count,
        "triggered_symbols": [p["symbol"] for p in triggered_positions],
    }
```
