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

    def __init__(self, dry_run=False, account_label=None, account_number=None):
        self.dry_run = dry_run
        try:
            from broker_secrets import load_into_env
            load_into_env()
        except Exception:
            pass
        self.app_key = os.environ.get("SCHWAB_APP_KEY", "")
        self.app_secret = os.environ.get("SCHWAB_APP_SECRET", "")
        self.refresh_token = os.environ.get("SCHWAB_REFRESH_TOKEN", "")
        self.access_token = None
        self.account_hash = None
        # Multi-account: John holds 3 Schwab accounts (rollover IRA, Roth IRA, taxable).
        # The adapter MUST target a specific one — never blindly use accounts[0]. The Schwab
        # account number is resolved per account_label from env SCHWAB_ACCT_<LABEL> (or passed
        # directly). Without it, get_account() refuses to guess when >1 account is present.
        self.account_label = account_label
        self.account_number = account_number or (
            os.environ.get(f"SCHWAB_ACCT_{account_label.upper()}", "") if account_label else ""
        )
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
        # Phase 1 read-only foundation: ALL Schwab write paths are fail-closed (Gate / Hard Rule #1).
        raise RuntimeError("NOT_PROVEN: Schwab write path disabled in Phase 1 (read-only foundation)")
        import requests
        if not self.access_token:
            return None
        resp = requests.post(f"{BASE_URL}{path}", headers={
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }, json=data, timeout=15)
        return resp

    # ── Account ──

    def _ensure_account_hash(self):
        """Resolve THIS account's hash, never blindly accounts[0] when multiple exist.
        Returns (ok: bool, err: dict|None). Safe to call from any entry point."""
        if self.account_hash:
            return True, None
        if not self.enabled:
            return False, {"status": "disabled"}
        accts = self._api_get("/trader/v1/accounts/accountNumbers") or []
        if self.account_number:
            # Match by full number or trailing digits (last-4 is what users usually have)
            want = str(self.account_number)
            match = next((a for a in accts
                          if str(a.get("accountNumber", "")) == want
                          or str(a.get("accountNumber", "")).endswith(want)), None)
            if not match:
                return False, {"status": "account_not_found",
                               "error": f"Schwab account '{want}' not among {len(accts)} linked accounts"}
            self.account_hash = match.get("hashValue")
        elif len(accts) == 1:
            self.account_hash = accts[0].get("hashValue")
        elif len(accts) > 1:
            # Ambiguous — refuse to guess. Configure SCHWAB_ACCT_<LABEL> or pass account_number.
            return False, {"status": "ambiguous_account",
                           "error": f"{len(accts)} Schwab accounts linked but none selected for "
                                    f"label='{self.account_label}'. Set SCHWAB_ACCT_<LABEL>."}
        else:
            return False, {"status": "no_account_hash"}
        return True, None

    def get_account(self):
        """Get account info including balances."""
        if not self.enabled:
            return {"status": "disabled"}
        try:
            ok, err = self._ensure_account_hash()
            if not ok:
                return err
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
        if not self.enabled:
            return []
        ok, _ = self._ensure_account_hash()
        if not ok:
            return []
        try:
            data = self._api_get(f"/trader/v1/accounts/{self.account_hash}?fields=positions")
            acct = data.get("securitiesAccount", {})
            positions = acct.get("positions", [])
            return [{
                "symbol": p.get("instrument", {}).get("symbol", ""),
                # Schwab returns instrument = {assetType, cusip, symbol, description}.
                # Only `symbol` was read, so the CUSIP — a durable instrument
                # identifier the broker hands us for free — was discarded on every
                # sync. It is what upgrades an entity from a name-derived CANDIDATE
                # identity to a CONFIRMED one in the identity registry, and it is
                # never invented: absent from the payload, it stays absent here.
                "cusip": (p.get("instrument", {}).get("cusip") or "").strip() or None,
                "asset_type": (p.get("instrument", {}).get("assetType") or "").strip() or None,
                "description": (p.get("instrument", {}).get("description") or "").strip() or None,
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
        """Submit a limit buy order. DISABLED in Phase 1 — read-only foundation only."""
        return {"status": "NOT_PROVEN", "error": "Schwab order submission disabled in Phase 1 (read-only foundation)"}
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
        if not self.enabled:
            return []
        ok, _ = self._ensure_account_hash()
        if not ok:
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
        """Cancel an order. DISABLED in Phase 1 — read-only foundation only (Hard Rule #1)."""
        return {"status": "NOT_PROVEN", "error": "Schwab cancel/replace disabled in Phase 1 (read-only foundation)"}
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
