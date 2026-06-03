#!/usr/bin/env python3
"""tastytrade_adapter.py — Tastytrade broker adapter.

Implements the same interface as alpaca_paper_adapter.py for broker-agnostic
trade execution. Uses Tastytrade's session-based REST API.

Requirements:
  - TASTYTRADE_USERNAME, TASTYTRADE_PASSWORD env vars
  - Session token obtained on init (auto-refreshed)

API Docs: https://developer.tastytrade.com

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

log = logging.getLogger("tastytrade-adapter")

# Tastytrade API endpoints
PROD_URL = "https://api.tastytrade.com"
SANDBOX_URL = "https://api.cert.tastytrade.com"


class TastytradeAdapter:
    """Tastytrade broker adapter — same interface as AlpacaPaperAdapter."""

    def __init__(self, dry_run=False, sandbox=True, account_label=None, account_number=None):
        self.dry_run = dry_run
        self.username = os.environ.get("TASTYTRADE_USERNAME", "")
        self.password = os.environ.get("TASTYTRADE_PASSWORD", "")
        self.base_url = SANDBOX_URL if sandbox else PROD_URL
        self.session_token = None
        # Multi-account: target a specific account rather than blindly items[0]. Resolved from
        # env TASTYTRADE_ACCT_<LABEL> or passed directly; if multiple accounts exist and none is
        # selected, _fetch_account refuses to guess.
        self.account_label = account_label
        self.account_number = account_number or (
            os.environ.get(f"TASTYTRADE_ACCT_{account_label.upper()}", "") if account_label else None
        )
        self.enabled = bool(self.username and self.password)

        if self.enabled:
            self._authenticate()

    def _authenticate(self):
        """Create session with username/password."""
        import requests
        try:
            resp = requests.post(f"{self.base_url}/sessions", json={
                "login": self.username,
                "password": self.password,
            }, timeout=15)
            if resp.ok:
                data = resp.json().get("data", {})
                self.session_token = data.get("session-token")
                log.info("[tastytrade] Authenticated successfully")
                # Get first account
                self._fetch_account()
            else:
                log.error(f"[tastytrade] Auth failed: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            log.error(f"[tastytrade] Auth error: {e}")

    def _fetch_account(self):
        """Resolve THIS account number — never blindly items[0] when multiple exist."""
        try:
            resp = self._api_get("/customers/me/accounts")
            items = resp.get("data", {}).get("items", [])
            numbers = [it.get("account", {}).get("account-number") for it in items]
            numbers = [n for n in numbers if n]
            if self.account_number:
                want = str(self.account_number)
                match = next((n for n in numbers if n == want or str(n).endswith(want)), None)
                if match:
                    self.account_number = match
                    log.info(f"[tastytrade] Account: {self.account_number}")
                else:
                    log.error(f"[tastytrade] Account '{want}' not among {len(numbers)} linked accounts")
                    self.account_number = None
            elif len(numbers) == 1:
                self.account_number = numbers[0]
                log.info(f"[tastytrade] Account: {self.account_number}")
            elif len(numbers) > 1:
                log.error(f"[tastytrade] {len(numbers)} accounts linked but none selected "
                          f"(label='{self.account_label}'). Set TASTYTRADE_ACCT_<LABEL>.")
                self.account_number = None
        except Exception as e:
            log.warning(f"[tastytrade] Failed to fetch account: {e}")

    def _headers(self):
        return {
            "Authorization": self.session_token or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _api_get(self, path):
        import requests
        if not self.session_token:
            return {}
        resp = requests.get(f"{self.base_url}{path}", headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _api_post(self, path, data):
        import requests
        if not self.session_token:
            return None
        resp = requests.post(f"{self.base_url}{path}", headers=self._headers(),
                            json=data, timeout=15)
        return resp

    def _api_delete(self, path):
        import requests
        if not self.session_token:
            return None
        resp = requests.delete(f"{self.base_url}{path}", headers=self._headers(), timeout=15)
        return resp

    # ── Account ──

    def get_account(self):
        """Get account info including balances."""
        if not self.enabled or not self.account_number:
            return {"status": "disabled"}
        try:
            data = self._api_get(f"/accounts/{self.account_number}/balances")
            balances = data.get("data", {})
            return {
                "status": "active",
                "equity": float(balances.get("net-liquidating-value", 0)),
                "cash": float(balances.get("cash-balance", 0)),
                "buying_power": float(balances.get("equity-buying-power", 0)),
                "account_type": balances.get("account-type", "unknown"),
                "broker": "tastytrade",
            }
        except Exception as e:
            log.warning(f"[tastytrade] get_account failed: {e}")
            return {"status": "error", "error": str(e)}

    # ── Positions ──

    def get_positions(self):
        """Get all open positions."""
        if not self.enabled or not self.account_number:
            return []
        try:
            data = self._api_get(f"/accounts/{self.account_number}/positions")
            items = data.get("data", {}).get("items", [])
            return [{
                "symbol": p.get("symbol", ""),
                "qty": str(p.get("quantity", 0)),
                "avg_entry_price": str(p.get("average-open-price", 0)),
                "current_price": str(p.get("close-price", 0)),
                "market_value": str(float(p.get("quantity", 0)) * float(p.get("close-price", 0))),
                "unrealized_pl": str(float(p.get("quantity", 0)) * (float(p.get("close-price", 0)) - float(p.get("average-open-price", 0)))),
                "side": "long" if p.get("quantity-direction") == "Long" else "short",
                "instrument_type": p.get("instrument-type", "Equity"),
            } for p in items if p.get("instrument-type") == "Equity"]
        except Exception as e:
            log.warning(f"[tastytrade] get_positions failed: {e}")
            return []

    # ── Orders ──

    def submit_entry(self, symbol, shares, entry_price, stop_price, target_price,
                     strategy_id, conn, proposal_id=None, **kwargs):
        """Submit a limit buy order."""
        if not self.enabled or not self.account_number:
            return {"status": "disabled", "error": "Tastytrade not configured"}
        if self.dry_run:
            log.info(f"[tastytrade] DRY RUN: {symbol} {shares}sh limit ${entry_price}")
            return {"status": "dry_run", "symbol": symbol}

        order = {
            "time-in-force": "Day",
            "order-type": "Limit",
            "price": str(entry_price),
            "legs": [{
                "instrument-type": "Equity",
                "symbol": symbol,
                "quantity": shares,
                "action": "Buy to Open",
            }],
        }

        try:
            resp = self._api_post(f"/accounts/{self.account_number}/orders", order)
            if resp and resp.ok:
                data = resp.json().get("data", {}).get("order", {})
                order_id = data.get("id", "")
                log.info(f"[tastytrade] Order submitted: {symbol} {shares}sh @ ${entry_price} → {order_id}")
                return {
                    "status": "submitted",
                    "order_id": str(order_id),
                    "symbol": symbol,
                    "shares": shares,
                    "broker": "tastytrade",
                }
            else:
                error = resp.text[:200] if resp else "No response"
                log.warning(f"[tastytrade] Order failed: {error}")
                return {"status": "error", "error": error}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def submit_stop_order(self, symbol, shares, stop_price):
        """Submit a stop sell order."""
        if not self.enabled or not self.account_number:
            return None
        order = {
            "time-in-force": "GTC",
            "order-type": "Stop",
            "stop-trigger": str(stop_price),
            "legs": [{
                "instrument-type": "Equity",
                "symbol": symbol,
                "quantity": shares,
                "action": "Sell to Close",
            }],
        }
        try:
            resp = self._api_post(f"/accounts/{self.account_number}/orders", order)
            if resp and resp.ok:
                data = resp.json().get("data", {}).get("order", {})
                return str(data.get("id", ""))
            return None
        except Exception:
            return None

    def get_open_orders(self):
        """Get all open/live orders."""
        if not self.enabled or not self.account_number:
            return []
        try:
            data = self._api_get(f"/accounts/{self.account_number}/orders/live")
            items = data.get("data", {}).get("items", [])
            return [{
                "id": str(o.get("id", "")),
                "symbol": o.get("legs", [{}])[0].get("symbol", ""),
                "side": "sell" if "Sell" in o.get("legs", [{}])[0].get("action", "") else "buy",
                "qty": str(o.get("legs", [{}])[0].get("quantity", 0)),
                "type": o.get("order-type", "").lower(),
                "stop_price": str(o.get("stop-trigger", "")),
                "limit_price": str(o.get("price", "")),
                "status": o.get("status", "").lower(),
            } for o in items]
        except Exception as e:
            log.warning(f"[tastytrade] get_open_orders failed: {e}")
            return []

    def cancel_order(self, order_id):
        """Cancel an order."""
        if not self.enabled or not self.account_number:
            return False
        try:
            resp = self._api_delete(f"/accounts/{self.account_number}/orders/{order_id}")
            return resp and resp.status_code in (200, 204)
        except Exception:
            return False

    def sync_positions(self, conn):
        """Sync broker positions with paper_trades table."""
        positions = self.get_positions()
        if not positions:
            return 0
        cur = conn.cursor()
        synced = 0
        for pos in positions:
            symbol = pos.get("symbol", "")
            if not symbol:
                continue
            cur.execute("""UPDATE paper_trades SET current_price=%s, unrealized_pnl=%s,
                          last_synced_at=NOW() WHERE symbol=%s AND status='open' AND broker='tastytrade'""",
                       [float(pos.get("current_price", 0)), float(pos.get("unrealized_pl", 0)), symbol])
            synced += cur.rowcount
        conn.commit()
        return synced

    def get_status(self):
        """Return adapter health status."""
        return {
            "broker": "tastytrade",
            "enabled": self.enabled,
            "authenticated": bool(self.session_token),
            "account_number": bool(self.account_number),
            "configured": bool(self.username and self.password),
            "dry_run": self.dry_run,
            "sandbox": self.base_url == SANDBOX_URL,
            "features": ["stocks", "options", "futures", "crypto", "options_analytics"],
            "ira_support": True,
            "account_types": ["taxable", "traditional_ira", "roth_ira", "sep_ira"],
        }
