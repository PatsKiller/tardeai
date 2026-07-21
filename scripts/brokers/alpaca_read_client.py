"""alpaca_read_client.py — account-scoped GET-only scaffold (R4).

Activates only when broker_accounts.api_read_enabled is true for the account.
Live scaffolds ship with api_read_enabled=false — this module stays inert.
Never places orders.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)


def _api_read_enabled(account_key: str) -> bool:
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT api_read_enabled, environment, credential_slot FROM broker_accounts WHERE account_key=%s",
            (account_key,),
        )
        r = cur.fetchone()
        return bool(r and r[0])
    except Exception:
        return False


def fetch_positions(account_key: str) -> list:
    """GET /v2/positions when api_read_enabled; else empty list."""
    if not _api_read_enabled(account_key):
        log.info("alpaca_read_client: api_read disabled for %s — no fetch", account_key)
        return []
    from brokers.alpaca_credentials import resolve_credentials, slot_for_account_key
    from brokers.alpaca_credentials import base_url_for_slot
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("SELECT credential_slot FROM broker_accounts WHERE account_key=%s", (account_key,))
        row = cur.fetchone()
        slot = (row[0] if row else None) or slot_for_account_key(account_key)
    except Exception:
        slot = slot_for_account_key(account_key)
    key, secret, base = resolve_credentials(slot)
    # refuse accidental live host if paper slot misconfigured
    host = (urlparse(base).hostname or "")
    if not key or not secret:
        return []
    req = urllib.request.Request(
        f"{base.rstrip('/')}/v2/positions",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())
