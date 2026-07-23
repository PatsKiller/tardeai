"""Active Trader Stage 2 — Schwab read-only discovery.

Rides the EXISTING approved read transport (scripts/schwab_transport.py): managed
tokens via schwab_token_manager (no refresh race), account-hash mapping via
schwab_account_links with masked last-4, rate limiting via _rate_acquire, and
the standing write fence (place/replace fail closed) untouched.

GET/read methods only. Write capabilities are graded exclusively from the
existing fences: RESTRICTED where a fence deliberately blocks a built path,
UNKNOWN where no evidence exists. Nothing here can invoke a write.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from active_trader.contracts import CapabilityState as _CS, Environment
from active_trader.discovery import (
    BrokerDiscoveryResult, DiscoveredAccount, make_capability, mask_identifier,
)

ACCOUNT_KEYS = ("schwab_rollover_ira", "schwab_roth", "schwab_taxable")
ADAPTER_VERSION = "schwab_transport (read) + execution_guard fences (stage2)"

# Fence-derived write grading: the protective-stop lane exists and is live-proven
# (Stage 2c, per-order 2FA), so CANCEL_ORDER/TRAILING_STOP-class actions through
# that lane are RESTRICTED (built, deliberately gated) rather than UNKNOWN.
FENCE_RESTRICTED = ("CANCEL_ORDER", "TRAILING_STOP", "PLACE_LIMIT_RTH", "PLACE_MARKET_RTH")
FENCE_UNKNOWN = ("PLACE_LIMIT_EXTENDED", "REPLACE_ORDER", "CANCEL_ALL_ACCOUNT",
                 "CANCEL_ALL_SYMBOL", "NATIVE_CLOSE_POSITION", "NATIVE_CLOSE_ALL",
                 "BRACKET_ORDER", "OTO_PROTECTION", "SHORT_SELL", "FRACTIONAL_SHARES",
                 "PRETRADE_ESTIMATE", "ELECTRONIC_ENTRY_ELIGIBILITY")


def _default_transport():
    import sys
    from pathlib import Path
    scripts_dir = str(Path(__file__).resolve().parents[1])
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import schwab_transport as st
    return st


def discover(transport=None, now: Optional[datetime] = None) -> BrokerDiscoveryResult:
    now = now or datetime.now(timezone.utc)
    result = BrokerDiscoveryResult(broker="schwab", connector_state="AVAILABLE",
                                   account_discovery="OK", observed_at=now.isoformat())
    try:
        st = transport or _default_transport()
    except Exception as exc:
        result.connector_state = "ERROR"
        result.account_discovery = "UNAVAILABLE"
        result.errors.append(f"transport import failed: {type(exc).__name__}")
        return result

    for account_key in ACCOUNT_KEYS:
        caps, evidence, read_ok, auth_state = [], {}, 0, "OK"
        masked = "***"
        for cap_name, fn in (("READ_ACCOUNT", st.get_account),
                             ("READ_POSITIONS", st.get_positions),
                             ("READ_OPEN_ORDERS", st.get_orders)):
            try:
                out = fn(account_key)
            except Exception as exc:
                out = {"status": "error", "error": type(exc).__name__}
            if isinstance(out, dict) and out.get("status") in ("error", "disabled",
                                                               "not_proven", "needs_mapping",
                                                               "ambiguous_refused"):
                evidence[cap_name] = str(out.get("status"))
                if "auth" in str(out.get("error", "")).lower() or out.get("status") == "disabled":
                    auth_state = "EXPIRED" if out.get("status") != "disabled" else "NOT_CONFIGURED"
                continue
            read_ok += 1
            evidence[cap_name] = "OK"
            caps.append(make_capability("schwab", account_key, Environment.LIVE, cap_name,
                                        _CS.SUPPORTED, "RUNTIME_READ_PROBE", now))
            if cap_name == "READ_ACCOUNT" and isinstance(out, dict):
                acct_no = (out.get("account_number") or out.get("accountNumber")
                           or out.get("masked_last4") or "")
                masked = mask_identifier(acct_no)
                if "balances" in out or "currentBalances" in out or "cash" in out:
                    caps.append(make_capability("schwab", account_key, Environment.LIVE,
                                                "READ_BALANCES", _CS.SUPPORTED,
                                                "RUNTIME_READ_PROBE", now))
                    evidence["READ_BALANCES"] = "OK"
        # market-clock / quote capability via safe read (evidence only, optional)
        try:
            hours = st.get_market_hours(account_key=account_key)
            if isinstance(hours, dict) and hours.get("status") not in ("error", "disabled"):
                evidence["MARKET_HOURS"] = "OK"
                caps.append(make_capability("schwab", account_key, Environment.LIVE,
                                            "SYMBOL_TRADABILITY", _CS.SUPPORTED,
                                            "RUNTIME_READ_PROBE", now,
                                            note="market-hours/quote read lane healthy"))
        except Exception as exc:
            evidence["MARKET_HOURS"] = f"error:{type(exc).__name__}"
        # Fence-derived write capabilities (no probe can or does occur):
        for wcap in FENCE_RESTRICTED:
            caps.append(make_capability("schwab", account_key, Environment.LIVE, wcap,
                                        _CS.RESTRICTED, "EXISTING_ADAPTER", now,
                                        adapter_version=ADAPTER_VERSION,
                                        note="built path exists but is fail-closed behind execution_guard + per-order 2FA (Stage 2c lane)"))
        for wcap in FENCE_UNKNOWN:
            caps.append(make_capability("schwab", account_key, Environment.LIVE, wcap,
                                        _CS.UNKNOWN, "EXISTING_ADAPTER", now,
                                        adapter_version=ADAPTER_VERSION,
                                        note="would require a write or a broker rejection to prove — not permitted in Stage 2"))
        result.accounts.append(DiscoveredAccount(
            broker="schwab", account_label=account_key, masked_account_id=masked,
            environment=Environment.LIVE.value, account_type=account_key.replace("schwab_", ""),
            status="ACTIVE" if read_ok else ("NEEDS_MAPPING" if evidence.get("READ_ACCOUNT") == "needs_mapping" else "ERROR"),
            read_state="OK" if read_ok >= 3 else ("PARTIAL" if read_ok else "UNAVAILABLE"),
            authentication_state=auth_state, capabilities=caps, evidence=evidence,
            credential_slot="SCHWAB_* (managed by schwab_token_manager)",
            observed_at=now.isoformat()))
    if all(a.read_state == "UNAVAILABLE" for a in result.accounts):
        result.account_discovery = "UNAVAILABLE"
    elif any(a.read_state != "OK" for a in result.accounts):
        result.account_discovery = "PARTIAL"
    return result
