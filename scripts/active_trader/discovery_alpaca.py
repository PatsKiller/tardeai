"""Active Trader Stage 2 — Alpaca read-only discovery.

Uses the existing credential-slot convention (scripts/brokers/alpaca_credentials.py):
host derives from the slot name, never from an env URL. GET-only; no order method
exists in this module. Secrets are used in headers internally and never logged,
returned, or persisted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from active_trader.contracts import CapabilityState, Environment
from active_trader.discovery import (
    BrokerDiscoveryResult, DiscoveredAccount, CapabilityState as _CS,
    make_capability, mask_identifier,
)

SLOTS = (
    ("ALPACA_PAPER", "alpaca_paper", Environment.SIMULATION, "paper"),
    ("ALPACA_TAXABLE", "alpaca_taxable_live", Environment.LIVE, "taxable"),
    ("ALPACA_IRA", "alpaca_ira_live", Environment.LIVE, "ira"),
)

READ_ENDPOINTS = {
    "READ_ACCOUNT": "/v2/account",
    "READ_POSITIONS": "/v2/positions",
    "READ_OPEN_ORDERS": "/v2/orders?status=open&limit=50",
    # market clock + safe asset lookup (read-only capability evidence)
    "_CLOCK": "/v2/clock",
    "_ASSET": "/v2/assets/AAPL",
}

ADAPTER_VERSION = "alpaca_paper_adapter+read_client (stage2 read probe)"


def _default_http_get(base: str, path: str, key: str, secret: str, timeout: float):
    import requests
    resp = requests.get(f"{base}{path}", headers={
        "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json"}, timeout=timeout, allow_redirects=False)
    return resp.status_code, (resp.json() if resp.content and
                              resp.headers.get("content-type", "").startswith("application/json") else None)


def discover(http_get: Optional[Callable] = None, now: Optional[datetime] = None,
             timeout: float = 10.0) -> BrokerDiscoveryResult:
    """Read-only discovery across the three configured credential slots."""
    import sys
    from pathlib import Path
    brokers_dir = str(Path(__file__).resolve().parents[1] / "brokers")
    if brokers_dir not in sys.path:
        sys.path.insert(0, brokers_dir)
    from alpaca_credentials import resolve_credentials  # existing convention

    http_get = http_get or _default_http_get
    now = now or datetime.now(timezone.utc)
    result = BrokerDiscoveryResult(broker="alpaca", connector_state="AVAILABLE",
                                   account_discovery="OK", observed_at=now.isoformat())
    for slot, label, env, acct_type in SLOTS:
        key, secret, base = resolve_credentials(slot)
        if not key or not secret:
            result.accounts.append(DiscoveredAccount(
                broker="alpaca", account_label=label, masked_account_id="***",
                environment=env.value, account_type=acct_type, status="NOT_CONFIGURED",
                read_state="UNAVAILABLE", authentication_state="NOT_CONFIGURED",
                credential_slot=slot, observed_at=now.isoformat(),
                evidence={"credential_slot_status": "EMPTY"},
                notes="credential slot unset (expected for unarmed live scaffolds)"))
            continue
        caps, evidence, read_ok, auth_state = [], {"credential_slot_status": "PRESENT"}, 0, "OK"
        masked = "***"
        for cap_name, path in READ_ENDPOINTS.items():
            try:
                status, body = http_get(base, path, key, secret, timeout)
            except Exception as exc:
                status, body = -1, None
                evidence[cap_name] = f"error:{type(exc).__name__}"
            if status == 200:
                read_ok += 1
                evidence[cap_name] = "200"
                if cap_name == "READ_ACCOUNT" and isinstance(body, dict):
                    masked = mask_identifier(body.get("account_number"))
                    evidence["account_status"] = body.get("status", "")
                    evidence["buying_power_present"] = "buying_power" in body
                    caps.append(make_capability("alpaca", label, env, "READ_BALANCES",
                                                _CS.SUPPORTED, "RUNTIME_READ_PROBE", now))
                if cap_name == "_ASSET":
                    caps.append(make_capability("alpaca", label, env, "SYMBOL_TRADABILITY",
                                                _CS.SUPPORTED, "RUNTIME_READ_PROBE", now))
                if not cap_name.startswith("_"):
                    caps.append(make_capability("alpaca", label, env, cap_name,
                                                _CS.SUPPORTED, "RUNTIME_READ_PROBE", now))
            elif status in (401, 403):
                auth_state = "EXPIRED"
                evidence[cap_name] = str(status)
            elif status != -1:
                evidence[cap_name] = str(status)
        # Write capabilities: NEVER probed. Paper placement is graded from the
        # existing production adapter evidence; live slots are execution-not-built.
        if env is Environment.SIMULATION:
            for wcap in ("PLACE_MARKET_RTH", "PLACE_LIMIT_RTH", "CANCEL_ORDER"):
                caps.append(make_capability("alpaca", label, env, wcap, _CS.SUPPORTED,
                                            "EXISTING_ADAPTER", now, adapter_version=ADAPTER_VERSION,
                                            note="alpaca_paper_adapter.submit_entry proven in production paper lane"))
            for wcap in ("BRACKET_ORDER", "OTO_PROTECTION", "TRAILING_STOP",
                         "NATIVE_CLOSE_POSITION", "NATIVE_CLOSE_ALL", "CANCEL_ALL_ACCOUNT",
                         "REPLACE_ORDER", "PLACE_LIMIT_EXTENDED", "SHORT_SELL",
                         "FRACTIONAL_SHARES"):
                caps.append(make_capability("alpaca", label, env, wcap, _CS.UNKNOWN,
                                            "EXISTING_ADAPTER", now, adapter_version=ADAPTER_VERSION,
                                            note="documented by Alpaca; not exercised by existing adapter — requires later non-Stage-2 proof"))
        else:
            for wcap in sorted(w for w in
                               ("PLACE_MARKET_RTH", "PLACE_LIMIT_RTH", "PLACE_LIMIT_EXTENDED",
                                "REPLACE_ORDER", "CANCEL_ORDER", "CANCEL_ALL_ACCOUNT",
                                "NATIVE_CLOSE_POSITION", "NATIVE_CLOSE_ALL", "BRACKET_ORDER",
                                "OTO_PROTECTION", "TRAILING_STOP")):
                caps.append(make_capability("alpaca", label, env, wcap, _CS.UNSUPPORTED,
                                            "EXISTING_ADAPTER", now, adapter_version=ADAPTER_VERSION,
                                            note="live execution not built (read-only scaffold by policy)"))
        result.accounts.append(DiscoveredAccount(
            broker="alpaca", account_label=label, masked_account_id=masked,
            environment=env.value, account_type=acct_type,
            status="ACTIVE" if read_ok else "ERROR",
            read_state="OK" if read_ok >= 3 else ("PARTIAL" if read_ok else "UNAVAILABLE"),
            authentication_state=auth_state, capabilities=caps, evidence=evidence,
            credential_slot=slot, observed_at=now.isoformat(), notes=""))
    if all(a.read_state == "UNAVAILABLE" for a in result.accounts):
        result.account_discovery = "UNAVAILABLE"
    elif any(a.read_state != "OK" for a in result.accounts):
        result.account_discovery = "PARTIAL"
    return result
