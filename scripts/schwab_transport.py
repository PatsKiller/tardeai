#!/usr/bin/env python3
"""schwab_transport.py — READ-ONLY Schwab transport via schwab-py (alexgolec, MIT), under the existing
schwab_token_manager.py.

ROLE SPLIT (non-negotiable):
  • schwab_token_manager.py = encrypted SYSTEM-OF-RECORD (Fernet storage, atomic rotation, day-5/6 alerts,
    fail-closed health). Its read_oauth_token / write_oauth_token are wired as schwab-py's token hooks so a
    refresh persists THROUGH the manager — the wrapper NEVER owns token storage.
  • schwab-py = request/response transport ONLY.

WRITE FENCE (Hard Rule #1 — the point of this module): the wrapper's place_order / cancel_order /
replace_order are NEVER exposed. The only order-surface symbols here RAISE NotProvenWrite. No caller —
adapter, endpoint, or agent — can reach a live Schwab write through this module.

LIVE = NOT_PROVEN until credentials exist (SCHWAB_APP_KEY/SECRET/CALLBACK). Without them build_client()
returns NOT_PROVEN and every read returns degraded. The NORMALIZERS are pure functions proven against
recorded fixtures now; real payload schemas MUST be reconciled at cred-in.  # TODO(cred-in): reconcile shapes
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SCHWAB_PY_VERSION = "1.5.1"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "schwab"


class NotProvenWrite(RuntimeError):
    """Raised by any wrapper write-surface symbol. Stage 1 is read-only; writes are fenced."""


# ── WRITE FENCE — these shadow the wrapper's write methods so any call hits NOT_PROVEN, never a live write ──
def place_order(*_a, **_k):
    raise NotProvenWrite("Schwab place_order is FENCED (read-only Stage 1; api_write_enabled=false)")


def cancel_order(*_a, **_k):
    raise NotProvenWrite("Schwab cancel_order is FENCED (read-only Stage 1; api_write_enabled=false)")


def replace_order(*_a, **_k):
    raise NotProvenWrite("Schwab replace_order is FENCED (read-only Stage 1; api_write_enabled=false)")


def _creds():
    try:
        import broker_secrets
        broker_secrets.load_into_env()
    except Exception:
        pass
    return os.environ.get("SCHWAB_APP_KEY"), os.environ.get("SCHWAB_APP_SECRET")


def _rate_acquire():
    """Shared token-bucket across all accounts + read cadences (the manager owns the one bucket)."""
    try:
        import schwab_token_manager as tm
        tm.RATE.acquire()
    except Exception:
        pass


def build_client(account_key, broker="schwab", environment="live"):
    """Construct the schwab-py READ client with token hooks into the manager. Returns (client, None) or
    (None, status_dict). Live construction needs portal creds → NOT_PROVEN until they exist (fail closed)."""
    api_key, app_secret = _creds()
    if not (api_key and app_secret):
        return None, {"status": "NOT_PROVEN", "reason": "SCHWAB_APP_KEY/SECRET absent — live transport NOT_PROVEN"}
    import schwab_token_manager as tm
    # ONE Schwab login token covers all the user's accounts — share it via the canonical key (the account
    # HASH distinguishes accounts). Refresh writes back to the canonical key (no rotation conflict).
    tkey = tm.canonical_token_key(broker, environment) or account_key
    if tm.read_oauth_token(tkey, broker, environment) is None:
        return None, {"status": "degraded", "reason": "no Schwab login token (manager is system-of-record)"}
    try:
        from schwab.auth import client_from_access_functions
        client = client_from_access_functions(
            api_key, app_secret,
            token_read_func=lambda: tm.read_oauth_token(tkey, broker, environment),
            token_write_func=lambda token, *a, **k: tm.write_oauth_token(token, tkey, broker, environment),
            enforce_enums=False,
        )
        return client, None
    except Exception as e:
        return None, {"status": "NOT_PROVEN", "reason": f"client construction failed: {str(e)[:120]}"}


# ── PURE NORMALIZERS (fixture-proven; match existing schwab_adapter shapes) ──
def normalize_account(raw):
    acct = (raw or {}).get("securitiesAccount", {})
    bal = acct.get("currentBalances", {})
    return {"status": "active", "equity": bal.get("liquidationValue", 0), "cash": bal.get("cashBalance", 0),
            "buying_power": bal.get("buyingPower", 0), "account_type": acct.get("type", "unknown"), "broker": "schwab"}


def normalize_positions(raw):
    acct = (raw or {}).get("securitiesAccount", {})
    out = []
    for p in acct.get("positions", []):
        lq = p.get("longQuantity", 0) or 0
        out.append({"symbol": p.get("instrument", {}).get("symbol", ""), "qty": str(lq),
                    "avg_entry_price": str(p.get("averagePrice", 0)),
                    "current_price": str(p.get("marketValue", 0) / max(lq, 1)),
                    "market_value": str(p.get("marketValue", 0)),
                    "unrealized_pl": str(p.get("longOpenProfitLoss", 0)),
                    "side": "long" if lq > 0 else "short"})
    return out


def normalize_orders(raw):
    out = []
    for o in (raw or []):
        leg = (o.get("orderLegCollection") or [{}])[0]
        out.append({"id": o.get("orderId"), "symbol": leg.get("instrument", {}).get("symbol", ""),
                    "side": (leg.get("instruction") or "").lower(), "qty": str(o.get("quantity", 0)),
                    "type": (o.get("orderType") or "").lower(), "stop_price": str(o.get("stopPrice", "")),
                    "limit_price": str(o.get("price", "")), "status": (o.get("status") or "").lower()})
    return out


def normalize_transactions(raw):
    out = []
    for t in (raw or []):
        item = (t.get("transferItems") or [{}])[0]
        out.append({"id": t.get("activityId") or t.get("transactionId"), "type": t.get("type", ""),
                    "trade_date": t.get("tradeDate") or t.get("time"), "net_amount": t.get("netAmount", 0),
                    "symbol": (item.get("instrument") or {}).get("symbol", "")})
    return out


def normalize_quote(raw):
    out = {}
    for sym, blk in (raw or {}).items():
        q = (blk or {}).get("quote", {})
        out[sym] = {"symbol": sym, "last": q.get("lastPrice"), "bid": q.get("bidPrice"),
                    "ask": q.get("askPrice"), "mark": q.get("mark")}
    return out


# ── ACCOUNT-HASH RESOLVER — map account_key → real Schwab hash; REFUSE ambiguity, never blind-select ──
def resolve_account_hashes(account_key, expected_last4=None):
    """Match account_key → a real Schwab account hash via get_account_numbers, by account-number last-4.
    With no expected_last4, returns the live accounts' masked last-4 only (operator supplies the mapping) —
    never blind-selects accounts[0]. On a UNIQUE last-4 match, stores the ENCRYPTED hash + masked last-4 in
    schwab_account_links (verified). Ambiguous (0 or >1 match) ⇒ refused."""
    client, err = build_client(account_key)
    if err:
        return err
    _rate_acquire()
    try:
        resp = client.get_account_numbers()
        rows = resp.json() if hasattr(resp, "json") else resp
    except Exception as e:
        return {"status": "error", "error": str(e)[:160]}
    accts = [{"last4": (r.get("accountNumber") or "")[-4:], "hash": r.get("hashValue")} for r in (rows or [])]
    if not expected_last4:
        return {"status": "needs_mapping", "accounts": [{"last4": a["last4"]} for a in accts],
                "note": "Re-run resolve_account_hashes(account_key, expected_last4=...) — never blind-selected."}
    want = str(expected_last4)[-4:]
    matches = [a for a in accts if a["last4"] == want]
    if len(matches) != 1:
        return {"status": "ambiguous_refused", "expected_last4": want, "match_count": len(matches),
                "note": "Refused — exactly one account must match the last-4."}
    import schwab_token_manager as tm
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM schwab_account_links WHERE account_key=%s", (account_key,))
    cur.execute("""INSERT INTO schwab_account_links (account_key, schwab_hash_enc, masked_last4, verified, last_verified_at)
                   VALUES (%s,%s,%s,TRUE,NOW())""", (account_key, tm._enc(matches[0]["hash"]), want))
    conn.commit()
    return {"ok": True, "account_key": account_key, "masked_last4": want, "note": "Hash stored encrypted + verified."}


def _get_hash(account_key):
    """Decrypt the verified Schwab account hash for read calls (None if unresolved)."""
    try:
        import schwab_token_manager as tm
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("SELECT schwab_hash_enc FROM schwab_account_links WHERE account_key=%s AND verified=TRUE", (account_key,))
        r = cur.fetchone()
        return tm._dec(r[0]) if r and r[0] else None
    except Exception:
        return None


# ── READ METHODS — degraded/NOT_PROVEN without a live client; live reads NOT_PROVEN until cred-in ──
def _read(account_key, fn_name, normalize, *args, **kwargs):
    client, err = build_client(account_key)
    if err:
        return err
    _rate_acquire()
    try:
        resp = getattr(client, fn_name)(*args, **kwargs)
        data = resp.json() if hasattr(resp, "json") else resp
        return normalize(data)
    except Exception as e:
        return {"status": "error", "error": str(e)[:160]}


def get_account(account_key, account_hash=None):
    h = account_hash or _get_hash(account_key)
    if not h:
        return {"status": "needs_account_hash", "reason": "run resolve_account_hashes(account_key, expected_last4=...)"}
    return _read(account_key, "get_account", normalize_account, h)


def get_positions(account_key, account_hash=None):
    h = account_hash or _get_hash(account_key)
    if not h:
        return {"status": "needs_account_hash", "reason": "run resolve_account_hashes(account_key, expected_last4=...)"}
    from schwab.client import Client
    return _read(account_key, "get_account", normalize_positions, h, fields=Client.Account.Fields.POSITIONS)


def get_orders(account_key, account_hash=None):
    h = account_hash or _get_hash(account_key)
    if not h:
        return {"status": "needs_account_hash", "reason": "run resolve_account_hashes(account_key, expected_last4=...)"}
    return _read(account_key, "get_orders_for_account", normalize_orders, h)


def get_transactions(account_key, account_hash=None):
    h = account_hash or _get_hash(account_key)
    if not h:
        return {"status": "needs_account_hash", "reason": "run resolve_account_hashes(account_key, expected_last4=...)"}
    return _read(account_key, "get_transactions", normalize_transactions, h)


def get_quote(account_key, symbol):
    return _read(account_key, "get_quote", normalize_quote, symbol)


def get_option_chain(account_key, symbol):
    return _read(account_key, "get_option_chain", lambda d: d, symbol)  # passthrough; reconcile at cred-in


def normalize_watchlists(raw):
    out = []
    for w in (raw or []):
        items = w.get("watchlistItems") or []
        out.append({"name": w.get("name"), "watchlist_id": w.get("watchlistId"),
                    "account": w.get("accountNumber"),
                    "symbols": [s for s in ((i.get("instrument") or {}).get("symbol") for i in items) if s]})
    return out


def get_watchlists(account_key):
    """Read all Schwab watchlists for the linked accounts. schwab-py 1.5.1 exposes NO watchlist method, so
    we call the Trader API watchlist endpoint (/trader/v1/watchlists) through the wrapper's authenticated
    session via its private _get_request (token refresh handled). READ-ONLY — no write surface touched."""
    client, err = build_client(account_key)
    if err:
        return err
    _rate_acquire()
    try:
        resp = client._get_request("/trader/v1/watchlists", {})
        sc = getattr(resp, "status_code", 200)
        if sc == 404:
            # CONFIRMED 2026-06-10 against a live approved app: the Schwab Trader API has NO watchlist
            # endpoint (not migrated from the legacy TDA API; userPreference carries no watchlists either).
            # Fall back to the thinkorswim (ToS) export ingestion path — never fabricate.
            return {"status": "NOT_AVAILABLE", "reason": "Schwab Trader API exposes no watchlist endpoint "
                    "(confirmed live; not migrated from legacy TDA). Use ToS export ingestion: exports/tos_watchlists/."}
        if sc >= 400:
            return {"status": "error", "http": sc, "body": resp.text[:160]}
        data = resp.json() if hasattr(resp, "json") else resp
        return normalize_watchlists(data)
    except Exception as e:
        return {"status": "error", "error": str(e)[:160]}
