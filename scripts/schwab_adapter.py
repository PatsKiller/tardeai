#!/usr/bin/env python3
"""schwab_adapter.py — Charles Schwab broker adapter.

Implements the same interface as alpaca_paper_adapter.py for broker-agnostic
trade execution. Uses Schwab's OAuth2 REST API.

Requirements:
  - SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_REFRESH_TOKEN env vars
  - Account hash from Schwab API (fetched on first connect)

API Docs: https://developer.schwab.com

Status: SCAFFOLDING — not yet tested with live credentials.
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger("schwab-adapter")

BASE_URL = "https://api.schwabapi.com"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"


class SchwabAdapter:
    """Schwab broker adapter — same interface as AlpacaPaperAdapter."""

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.app_key = os.environ.get("SCHWAB_APP_KEY", "")
        self.app_secret = os.environ.get("SCHWAB_APP_SECRET", "")
        self.refresh_token = os.environ.get("SCHWAB_REFRESH_TOKEN", "")
        self.access_token = None
        self.account_hash = None
        self.enabled = bool(self.app_key and self.app_secret and self.refresh_token)

        if self.enabled:
            self._authenticate()

    def _authenticate(self):
        """Exchange refresh token for access token."""
        import requests
        try:
            import base64
            credentials = base64.b64encode(f"{self.app_key}:{self.app_secret}".encode()).decode()
            resp = requests.post(TOKEN_URL, headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            }, data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            }, timeout=15)
            if resp.ok:
                data = resp.json()
                self.access_token = data.get("access_token")
                # Store new refresh token if rotated
                new_refresh = data.get("refresh_token")
                if new_refresh and new_refresh != self.refresh_token:
                    self.refresh_token = new_refresh
                    log.info("[schwab] Refresh token rotated — update SCHWAB_REFRESH_TOKEN env var")
                log.info("[schwab] Authenticated successfully")
            else:
                log.error(f"[schwab] Auth failed: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            log.error(f"[schwab] Auth error: {e}")

    def _api_get(self, path):
        import requests
        if not self.access_token:
            return None
        resp = requests.get(f"{BASE_URL}{path}", headers={
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _api_post(self, path, data):
        import requests
        if not self.access_token:
            return None
        resp = requests.post(f"{BASE_URL}{path}", headers={
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }, json=data, timeout=15)
        return resp

    # ── Account ──

    def get_account(self):
        """Get account info including balances."""
        if not self.enabled:
            return {"status": "disabled"}
        try:
            # First get account numbers/hashes
            if not self.account_hash:
                accts = self._api_get("/trader/v1/accounts/accountNumbers")
                if accts and len(accts) > 0:
                    self.account_hash = accts[0].get("hashValue")
            if not self.account_hash:
                return {"status": "no_account_hash"}
            data = self._api_get(f"/trader/v1/accounts/{self.account_hash}")
            acct = data.get("securitiesAccount", {})
            balances = acct.get("currentBalances", {})
            return {
                "status": "active",
                "equity": balances.get("liquidationValue", 0),
                "cash": balances.get("cashBalance", 0),
                "buying_power": balances.get("buyingPower", 0),
                "account_type": acct.get("type", "unknown"),
                "broker": "schwab",
            }
        except Exception as e:
            log.warning(f"[schwab] get_account failed: {e}")
            return {"status": "error", "error": str(e)}

    # ── Positions ──

    def get_positions(self):
        """Get all open positions."""
        if not self.enabled or not self.account_hash:
            return []
        try:
            data = self._api_get(f"/trader/v1/accounts/{self.account_hash}?fields=positions")
            acct = data.get("securitiesAccount", {})
            positions = acct.get("positions", [])
            return [{
                "symbol": p.get("instrument", {}).get("symbol", ""),
                "qty": str(p.get("longQuantity", 0)),
                "avg_entry_price": str(p.get("averagePrice", 0)),
                "current_price": str(p.get("marketValue", 0) / max(p.get("longQuantity", 1), 1)),
                "market_value": str(p.get("marketValue", 0)),
                "unrealized_pl": str(p.get("longOpenProfitLoss", 0)),
                "side": "long" if p.get("longQuantity", 0) > 0 else "short",
            } for p in positions]
        except Exception as e:
            log.warning(f"[schwab] get_positions failed: {e}")
            return []

    # ── Orders ──

    def submit_entry(self, symbol, shares, entry_price, stop_price, target_price,
                     strategy_id, conn, proposal_id=None, **kwargs):
        """Submit a limit buy order."""
        if not self.enabled or not self.account_hash:
            return {"status": "disabled", "error": "Schwab not configured"}
        if self.dry_run:
            log.info(f"[schwab] DRY RUN: {symbol} {shares}sh limit ${entry_price}")
            return {"status": "dry_run", "symbol": symbol}

        order = {
            "orderType": "LIMIT",
            "session": "NORMAL",
            "duration": "DAY",
            "orderStrategyType": "SINGLE",
            "price": str(entry_price),
            "orderLegCollection": [{
                "instruction": "BUY",
                "quantity": shares,
                "instrument": {
                    "symbol": symbol,
                    "assetType": "EQUITY",
                },
            }],
        }

        try:
            resp = self._api_post(f"/trader/v1/accounts/{self.account_hash}/orders", order)
            if resp and resp.status_code in (200, 201):
                # Schwab returns order ID in Location header
                order_id = resp.headers.get("Location", "").split("/")[-1]
                log.info(f"[schwab] Order submitted: {symbol} {shares}sh @ ${entry_price} → {order_id}")
                return {
                    "status": "submitted",
                    "order_id": order_id,
                    "symbol": symbol,
                    "shares": shares,
                    "broker": "schwab",
                }
            else:
                error = resp.text[:200] if resp else "No response"
                log.warning(f"[schwab] Order failed: {error}")
                return {"status": "error", "error": error}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_open_orders(self):
        """Get all open orders."""
        if not self.enabled or not self.account_hash:
            return []
        try:
            orders = self._api_get(f"/trader/v1/accounts/{self.account_hash}/orders?status=WORKING")
            return [{
                "id": o.get("orderId"),
                "symbol": o.get("orderLegCollection", [{}])[0].get("instrument", {}).get("symbol", ""),
                "side": o.get("orderLegCollection", [{}])[0].get("instruction", "").lower(),
                "qty": str(o.get("quantity", 0)),
                "type": o.get("orderType", "").lower(),
                "stop_price": str(o.get("stopPrice", "")),
                "limit_price": str(o.get("price", "")),
                "status": o.get("status", "").lower(),
            } for o in (orders or [])]
        except Exception as e:
            log.warning(f"[schwab] get_open_orders failed: {e}")
            return []

    def cancel_order(self, order_id):
        """Cancel an order."""
        import requests
        if not self.enabled or not self.account_hash:
            return False
        try:
            resp = requests.delete(
                f"{BASE_URL}/trader/v1/accounts/{self.account_hash}/orders/{order_id}",
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=15)
            return resp.status_code in (200, 204)
        except Exception:
            return False

    def sync_positions(self, conn):
        """Sync broker positions with paper_trades table."""
        positions = self.get_positions()
        if not positions:
            return 0
        # Same sync logic as Alpaca adapter
        cur = conn.cursor()
        synced = 0
        for pos in positions:
            symbol = pos.get("symbol", "")
            if not symbol:
                continue
            cur.execute("""UPDATE paper_trades SET current_price=%s, unrealized_pnl=%s,
                          last_synced_at=NOW() WHERE symbol=%s AND status='open' AND broker='schwab'""",
                       [float(pos.get("current_price", 0)), float(pos.get("unrealized_pl", 0)), symbol])
            synced += cur.rowcount
        conn.commit()
        return synced

    def get_status(self):
        """Return adapter health status."""
        return {
            "broker": "schwab",
            "enabled": self.enabled,
            "authenticated": bool(self.access_token),
            "account_hash": bool(self.account_hash),
            "configured": bool(self.app_key and self.app_secret),
            "dry_run": self.dry_run,
            "features": ["stocks", "options", "etfs", "mutual_funds"],
            "ira_support": True,
            "account_types": ["taxable", "traditional_ira", "roth_ira", "rollover_ira", "sep_ira"],
        }
