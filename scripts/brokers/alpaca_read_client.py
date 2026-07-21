"""alpaca_read_client.py — GET-only Alpaca HTTP for paper/live read paths.

HARD RULES (read-only integration 2026-07-21):
  • Transport allowlist is GET only — POST/PUT/PATCH/DELETE raise.
  • Host comes from credential *slot* (brokers.alpaca_credentials), never ALPACA_BASE_URL.
  • Live account data fetch requires broker_accounts.api_read_enabled=true
    (NOT is_enabled — arm CHECK stays out of the data path).
  • Never places orders.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_ALLOWED_METHODS = frozenset({"GET"})


class MethodNotAllowedError(RuntimeError):
    """Raised when a non-GET method is attempted on the live/paper read transport."""


def _api_read_enabled(account_key: str) -> Tuple[bool, Optional[dict]]:
    """Return (enabled, row-or-None)."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT account_key, environment, credential_slot, api_read_enabled,
                      is_enabled, api_write_enabled, connection_status
                 FROM broker_accounts WHERE account_key=%s""",
            (account_key,),
        )
        r = cur.fetchone()
        if not r:
            return False, None
        cols = ["account_key", "environment", "credential_slot", "api_read_enabled",
                "is_enabled", "api_write_enabled", "connection_status"]
        row = dict(zip(cols, r))
        return bool(row.get("api_read_enabled")), row
    except Exception as e:
        log.warning("api_read_enabled lookup failed: %s", e)
        return False, None


def _slot_and_creds(account_key: str, row: Optional[dict] = None):
    from brokers.alpaca_credentials import resolve_credentials, slot_for_account_key
    slot = (row or {}).get("credential_slot") or slot_for_account_key(account_key)
    key, secret, base = resolve_credentials(slot)
    return slot, key, secret, base.rstrip("/")


def http_get(url: str, headers: Dict[str, str], *, method: str = "GET",
             timeout: int = 20) -> Any:
    """GET-only transport. Non-GET raises MethodNotAllowedError before any socket."""
    m = (method or "GET").upper()
    if m not in _ALLOWED_METHODS:
        raise MethodNotAllowedError(
            f"alpaca_read_client allows GET only — refused method={m!r} url={url!r}"
        )
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def test_connection(account_key: str) -> dict:
    """Single GET /v2/account — does not require api_read_enabled (admin probe).

    Still GET-only; never writes. Used by admin Test connection button.
    """
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT account_key, environment, credential_slot FROM broker_accounts
               WHERE account_key=%s""",
            (account_key,),
        )
        r = cur.fetchone()
        if not r:
            return {"ok": False, "error": f"unknown account {account_key}", "status": "unknown"}
        row = {"account_key": r[0], "environment": r[1], "credential_slot": r[2]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160], "status": "error"}

    slot, key, secret, base = _slot_and_creds(account_key, row)
    if not key or not secret:
        return {
            "ok": False,
            "status": "no_credentials",
            "error": "no credentials for slot — enter keys in API Keys & Secrets",
            "slot": slot,
            "host": (urlparse(base).hostname or ""),
        }
    try:
        data = http_get(
            f"{base}/v2/account",
            {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
        )
        # Do not persist or return secret-bearing fields beyond status
        status = "ok"
        equity = data.get("equity") or data.get("portfolio_value")
        # update connection_status only (no enable flags)
        try:
            cur = _get_conn().cursor()
            cur.execute(
                """UPDATE broker_accounts SET connection_status=%s, last_sync_at=now(),
                   updated_at=now() WHERE account_key=%s""",
                (status, account_key),
            )
            _get_conn().commit()
        except Exception:
            pass
        return {
            "ok": True,
            "status": status,
            "slot": slot,
            "host": (urlparse(base).hostname or ""),
            "account_status": data.get("status"),
            "equity_present": equity is not None,
            # never return raw account numbers/secrets
        }
    except MethodNotAllowedError:
        raise
    except Exception as e:
        err = str(e)[:160]
        try:
            cur = _get_conn().cursor()
            cur.execute(
                """UPDATE broker_accounts SET connection_status=%s, updated_at=now()
                   WHERE account_key=%s""",
                ("error", account_key),
            )
            _get_conn().commit()
        except Exception:
            pass
        return {"ok": False, "status": "error", "error": err, "slot": slot}


def fetch_json(account_key: str, path: str) -> Any:
    """GET path for account when api_read_enabled. Empty list/dict if disabled or no keys."""
    enabled, row = _api_read_enabled(account_key)
    if not enabled:
        log.info("alpaca_read_client: api_read disabled for %s — skip %s", account_key, path)
        return None
    slot, key, secret, base = _slot_and_creds(account_key, row)
    if not key or not secret:
        log.info("alpaca_read_client: no credentials for %s", account_key)
        return None
    url = f"{base}{path if path.startswith('/') else '/' + path}"
    return http_get(url, {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})


def fetch_positions(account_key: str) -> List[dict]:
    data = fetch_json(account_key, "/v2/positions")
    if data is None:
        return []
    return data if isinstance(data, list) else []


def fetch_account(account_key: str) -> Optional[dict]:
    data = fetch_json(account_key, "/v2/account")
    return data if isinstance(data, dict) else None


def fetch_orders(account_key: str, status: str = "closed", limit: int = 50) -> List[dict]:
    data = fetch_json(account_key, f"/v2/orders?status={status}&limit={int(limit)}&direction=desc")
    if data is None:
        return []
    return data if isinstance(data, list) else []


def fetch_activities(account_key: str, activity_type: str = "FILL", page_size: int = 50) -> List[dict]:
    # Alpaca account activities
    data = fetch_json(
        account_key,
        f"/v2/account/activities/{activity_type}?page_size={int(page_size)}",
    )
    if data is None:
        return []
    return data if isinstance(data, list) else []
