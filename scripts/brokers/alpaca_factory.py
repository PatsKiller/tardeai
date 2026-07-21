"""alpaca_factory.py — sole sanctioned Alpaca adapter constructor (R2).

adapter_for(account_key):
  • paper env  → existing AlpacaPaperAdapter (unchanged class)
  • live env   → NotImplementedError (no live submit path in this build)
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _row(account_key: str) -> dict | None:
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return None
        cur = conn.cursor()
        cur.execute(
            """SELECT account_key, broker, environment, credential_slot,
                      is_enabled, api_read_enabled, api_write_enabled
                 FROM broker_accounts WHERE account_key=%s""",
            (account_key,),
        )
        r = cur.fetchone()
        if not r:
            # alias
            from live_trading_interlock import _normalize
            nk = _normalize(account_key)
            if nk != account_key:
                cur.execute(
                    """SELECT account_key, broker, environment, credential_slot,
                              is_enabled, api_read_enabled, api_write_enabled
                         FROM broker_accounts WHERE account_key=%s""",
                    (nk,),
                )
                r = cur.fetchone()
        if not r:
            return None
        cols = ["account_key", "broker", "environment", "credential_slot",
                "is_enabled", "api_read_enabled", "api_write_enabled"]
        return dict(zip(cols, r))
    except Exception as e:
        log.warning("alpaca_factory row lookup failed: %s", e)
        return None


def adapter_for(account_key: str, *, dry_run: bool = False) -> Any:
    """Return a paper Alpaca adapter or raise for live/unknown."""
    key = (account_key or "").strip()
    row = _row(key)
    if not row:
        # hardcode-ok: paper-only fallback keys when DB unavailable (R2)
        if key in ("tradeai_automated", "alpaca_paper", "ALPACA_PAPER"):  # hardcode-ok
            env = "paper"
            slot = "ALPACA_PAPER"
        else:
            raise ValueError(f"unknown account_key {account_key!r} for alpaca factory")
    else:
        if (row.get("broker") or "").lower() != "alpaca":
            raise ValueError(f"account {account_key!r} is broker={row.get('broker')!r}, not alpaca")
        env = (row.get("environment") or "").lower()
        slot = row.get("credential_slot") or "ALPACA_PAPER"  # hardcode-ok: default paper slot

    if env == "live":
        # hardcode-ok: intentional refusal — live submit path not built this phase
        raise NotImplementedError(
            "live adapter not built; see docs/brokers/alpaca-live-accounts.md roadmap "
            f"(account={account_key})"
        )
    if env not in ("paper", ""):
        raise ValueError(f"unsupported alpaca environment {env!r} for {account_key}")

    # Ensure paper credentials resolve via slot (legacy fallback inside)
    from brokers.alpaca_credentials import resolve_credentials, base_url_for_slot
    api_key, secret, base = resolve_credentials(slot)
    assert base_url_for_slot(slot).endswith("paper-api.alpaca.markets") or env != "paper"

    # Inject legacy env for AlpacaPaperAdapter which still reads ALPACA_API_KEY
    if api_key and not os.environ.get("ALPACA_API_KEY"):
        os.environ["ALPACA_API_KEY"] = api_key
    if secret and not os.environ.get("ALPACA_SECRET_KEY"):
        os.environ["ALPACA_SECRET_KEY"] = secret

    from alpaca_paper_adapter import AlpacaPaperAdapter
    return AlpacaPaperAdapter(dry_run=dry_run)
