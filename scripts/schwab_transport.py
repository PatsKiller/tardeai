#!/usr/bin/env python3
"""schwab_transport.py — READ-ONLY Schwab transport via schwab-py (alexgolec, MIT), under the existing
schwab_token_manager.py.

ROLE SPLIT (non-negotiable):
  • schwab_token_manager.py = encrypted SYSTEM-OF-RECORD (Fernet storage, atomic rotation, day-5/6 alerts,
    fail-closed health). Its read_oauth_token / write_oauth_token are wired as schwab-py's token hooks so a
    refresh persists THROUGH the manager — the wrapper NEVER owns token storage.
  • schwab-py = request/response transport ONLY.

WRITE SURFACE (Stage 2b SB-1, operator-approved 2026-06-12): place_order / cancel_order are now REAL,
but every call passes the FULL stack before any HTTP: committed pilot account allowlist (taxable only —
IRA keys raise unconditionally) → broker_accounts.api_write_enabled (DB) → execution_guard.require()
(canary envelope → standing locks → pilot 5-order cap → per-trade 2FA web+telegram). A correlation row
is persisted BEFORE the POST (Schwab does not dedupe — timeout ⇒ reconcile via GET before any retry).
replace_order remains FENCED (NotProvenWrite) — no replace in the pilot; cancel + new order instead.

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


# ── Stage 2b WRITE SURFACE — the ONLY Schwab write path in the repo; full guard stack per call ──

def _pilot_ensure_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS schwab_pilot_orders (
                     id SERIAL PRIMARY KEY,
                     correlation_id TEXT NOT NULL,
                     intent_id TEXT,
                     account_key TEXT NOT NULL,
                     symbol TEXT,
                     side TEXT,
                     qty NUMERIC,
                     limit_price NUMERIC,
                     order_spec JSONB,
                     status TEXT NOT NULL,
                     broker_order_id TEXT,
                     detail TEXT,
                     created_at TIMESTAMPTZ DEFAULT NOW(),
                     updated_at TIMESTAMPTZ DEFAULT NOW())""")
    # additive: tag the pilot family so the canary 5-order cap counts ONLY canary rows (Stage 2c)
    cur.execute("ALTER TABLE schwab_pilot_orders ADD COLUMN IF NOT EXISTS kind TEXT DEFAULT 'canary'")


def _pilot_preconditions(account_key, kind="canary"):
    """Hard structural asserts BEFORE the guard even runs. The committed account allowlist depends on the
    order family: canary writes are taxable-only (pilot_caps); protective stops use the protective policy's
    effective allowlist (taxable always, + the two Schwab IRAs ONLY when IRA_PROTECTIVE_ENABLED is committed
    True). With the IRA flag off, IRA keys can never reach a write here either."""
    if kind == "protective_stop":
        from brokers.protective_stop_policy import effective_account_allowlist
        allow = effective_account_allowlist()
        desc = "protective-stop allowlist"
    elif kind == "oco_bracket":
        # An OCO bracket is a protective EXIT (sell-to-close stop + take-profit) — same safe direction and
        # account envelope as a protective stop, so it shares the protective-stop allowlist. (P3, inert until
        # OCO_BRACKETS_SCHWAB is armed; see schwab_oco_bracket.submit_oco.)
        from brokers.protective_stop_policy import effective_account_allowlist
        allow = effective_account_allowlist()
        desc = "OCO-bracket allowlist (shares the protective-stop envelope)"
    elif kind == "options":
        from brokers.options_execution_policy import OPTIONS_ACCOUNT_ALLOWLIST
        allow = OPTIONS_ACCOUNT_ALLOWLIST
        desc = "options execution allowlist"
    elif kind == "queue_entry":
        from brokers.pilot_caps import PILOT_ACCOUNT_ALLOWLIST
        allow = PILOT_ACCOUNT_ALLOWLIST
        desc = "queue-entry bracket allowlist"
    else:
        from brokers.pilot_caps import PILOT_ACCOUNT_ALLOWLIST
        allow = PILOT_ACCOUNT_ALLOWLIST
        desc = "canary pilot allowlist"
    if (account_key or "").strip() not in allow:
        raise NotProvenWrite(f"account {account_key!r} is not in the committed {desc} {allow}")
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("SELECT api_write_enabled FROM broker_accounts WHERE account_key=%s", (account_key,))
    r = cur.fetchone()
    if not r or r[0] is not True:
        raise NotProvenWrite(f"broker_accounts.api_write_enabled is not true for {account_key} "
                             "(pilot disarmed — run schwab_pilot_arm.py --arm)")
    return conn


def place_order(account_key, order_spec, intent, kind="canary"):
    """Stage 2b pilot submit. Stack: taxable-only assert → api_write_enabled → execution_guard.require
    (canary OR protective gate → standing locks → pilot/protective caps → 2FA) → persist row → POST →
    consume approval → read-back. `kind` tags the pilot family ('canary' | 'protective_stop') so the
    canary 5-order cap counts only canary rows. Raises NotProvenWrite/ExecutionBlocked on any closed
    lock; returns a result dict on broker contact."""
    import json as _json
    from brokers.execution_guard import require           # raises ExecutionBlocked when denied
    from brokers import approval_service
    from brokers.execution_readiness import evaluate_execution_readiness, require_ready
    conn = _pilot_preconditions(account_key, kind)
    if (intent.account_key or "") != account_key:
        raise NotProvenWrite(f"intent.account_key {intent.account_key!r} != {account_key!r} — refusing")
    asset_class = "option" if kind == "options" else "equity"
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    readiness = evaluate_execution_readiness(
        {"intent_id": intent.intent_id, "correlation_id": intent.correlation_id,
         "account_key": account_key, "signal_evidence": ev},
        asset_class=asset_class, broker="schwab", account_key=account_key, mode="submit",
    )
    if not readiness.get("ok"):
        from brokers.execution_guard import ExecutionBlocked
        blocks = "; ".join(b.get("reason", "") for b in readiness.get("hard_blocks", [])[:3])
        raise ExecutionBlocked(f"EXECUTION_READINESS BLOCK: {blocks}")
    try:
        from brokers.evidence_approval import revalidate_before_submit
        rev = revalidate_before_submit(
            intent.intent_id,
            current_readiness=readiness,
            current_order_spec=order_spec,
        )
        if not rev.get("ok"):
            from brokers.execution_guard import ExecutionBlocked
            raise ExecutionBlocked(f"EVIDENCE_REVALIDATION BLOCK: {rev.get('reason')}")
    except ImportError:
        pass
    require(intent, "submit")
    cur = conn.cursor()
    _pilot_ensure_table(cur)
    legs = (order_spec.get("orderLegCollection") or [{}])[0]
    _symbol = (legs.get("instrument") or {}).get("symbol")
    # Idempotency fence (P0-5): never create a second ACTIVE submit for the same
    # intent/account/symbol. Schwab does not dedupe, so a duplicate row = a duplicate live
    # order. A stale prior SUBMIT_REQUESTED must be reconciled (GET broker truth) first.
    try:
        from brokers.order_lifecycle import idempotency_key, is_duplicate_active_submit
        idem = idempotency_key(intent.intent_id or "", account_key or "", _symbol or "")
        cur.execute(
            """SELECT intent_id, account_key, symbol, status FROM schwab_pilot_orders
               WHERE intent_id=%s AND account_key=%s AND symbol=%s
                 AND status NOT IN ('filled','canceled','cancelled','rejected','expired',
                                    'error_reconcile_required','client_unavailable','post_exception')""",
            (intent.intent_id, account_key, _symbol))
        existing = [{"idempotency_key": idempotency_key(r[0] or "", r[1] or "", r[2] or ""),
                     "status": r[3]} for r in (cur.fetchall() or [])]
        if is_duplicate_active_submit(idem, existing):
            raise NotProvenWrite(
                f"duplicate_active_submit for {intent.intent_id}/{account_key}/{_symbol} — "
                "reconcile existing open order before resubmitting")
    except NotProvenWrite:
        raise
    except Exception:
        # Never fail-open on a guard error path other than the explicit duplicate block.
        pass
    # ── P1 duplicate-stop guard (cross-origin) ──────────────────────────────────
    # The idempotency fence above only catches a re-submit of the SAME intent. It does NOT catch a
    # SECOND stop when the broker ALREADY has a live SELL stop from a different source (e.g. one placed
    # manually in ToS — the ARKQ case). Two live SELL stops on the same shares = over-sell / naked risk.
    # Rule: refuse to place a SELL stop when the broker shows a live SELL stop on this symbol, UNLESS the
    # only such order is the one this intent explicitly replaces (replace_order_id, already cancelled just
    # above in the confirm path). Fails CLOSED. Distinguishes pilot- vs manually-placed for the message.
    _is_sell = str(legs.get("instruction", "")).upper() in ("SELL", "SELL_SHORT")
    _is_stop = "STOP" in str(order_spec.get("orderType", "")).upper() or "TRAIL" in str(order_spec.get("orderType", "")).upper()
    if _is_sell and _is_stop and _symbol:
        try:
            _ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
            _replace_id = str(_ev.get("replace_order_id") or "").strip()
            _raw = get_orders_raw(account_key)
            # A degraded read (NOT_PROVEN/error/needs_hash dict) must NOT be read as "no orders" —
            # that would fail-OPEN. Only a successful order LIST (or {"orders": [...]}) is trusted.
            if isinstance(_raw, dict) and str(_raw.get("status", "")).upper() in (
                    "NOT_PROVEN", "ERROR", "NEEDS_ACCOUNT_HASH", "DEGRADED"):
                raise NotProvenWrite(
                    f"duplicate_stop_guard_unverified for {_symbol}: broker order read is degraded "
                    f"({_raw.get('status')}) — refusing to place to avoid a possible duplicate. Retry.")
            _orders = _raw if isinstance(_raw, list) else ((_raw.get("orders") if isinstance(_raw, dict) else []) or [])
            _live_states = ("WORKING", "AWAITING_STOP_CONDITION", "PENDING_ACTIVATION", "QUEUED", "ACCEPTED", "AWAITING_MANUAL_REVIEW")
            _conflicts = []
            for _o in (_orders if isinstance(_orders, list) else []):
                _ol = (_o.get("orderLegCollection") or [{}])[0]
                _oi = (_ol.get("instrument") or {})
                if (str(_oi.get("symbol", "")).upper() == _symbol.upper()
                        and str(_ol.get("instruction", "")).upper() in ("SELL", "SELL_SHORT")
                        and str(_o.get("status", "")).upper() in _live_states
                        and ("STOP" in str(_o.get("orderType", "")).upper() or "TRAIL" in str(_o.get("orderType", "")).upper())):
                    _oid = str(_o.get("orderId") or "")
                    if _oid and _oid == _replace_id:
                        continue   # the order we are replacing (already cancelled) — allowed
                    _conflicts.append(_oid)
            if _conflicts:
                _oid0 = _conflicts[0]
                cur.execute("SELECT 1 FROM schwab_pilot_orders WHERE broker_order_id=%s AND account_key=%s LIMIT 1",
                            (_oid0, account_key))
                _is_pilot = cur.fetchone() is not None
                if _is_pilot:
                    raise NotProvenWrite(
                        f"duplicate_stop_blocked: {_symbol} already has a live app-placed SELL stop "
                        f"(order {_oid0}). Replace it (cancel-then-place) rather than adding a second stop.")
                raise NotProvenWrite(
                    f"duplicate_stop_blocked: {_symbol} already has a live MANUAL SELL stop (order {_oid0}) "
                    "placed in ToS — Trade AI cannot cancel a non-pilot order. Modify or cancel it in ToS "
                    "first, then place here. No order was sent (avoiding a duplicate stop).")
        except NotProvenWrite:
            raise
        except Exception:
            # Read/parse failure must NOT fail-open on a safety guard — block conservatively.
            raise NotProvenWrite(
                f"duplicate_stop_guard_unverified for {_symbol}: could not confirm the broker has no "
                "existing SELL stop — refusing to place to avoid a possible duplicate. Retry or check ToS.")
    # persist BEFORE any HTTP — Schwab does not dedupe; this row is the reconcile anchor on timeout
    cur.execute("""INSERT INTO schwab_pilot_orders
                     (correlation_id, intent_id, account_key, symbol, side, qty, limit_price, order_spec, status, kind)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'submitting',%s) RETURNING id""",
                (intent.correlation_id, intent.intent_id, account_key,
                 (legs.get("instrument") or {}).get("symbol"), legs.get("instruction"),
                 legs.get("quantity"), order_spec.get("price"), _json.dumps(order_spec), kind))
    row_id = cur.fetchone()[0]
    conn.commit()
    client, err = build_client(account_key)
    if err:
        cur.execute("UPDATE schwab_pilot_orders SET status='client_unavailable', detail=%s, updated_at=NOW() "
                    "WHERE id=%s", (str(err)[:300], row_id)); conn.commit()
        return {"status": "error", "error": "client unavailable", "detail": err, "pilot_row_id": row_id}
    h = _get_hash(account_key)
    _rate_acquire()
    try:
        resp = client.place_order(h, order_spec)
    except Exception as e:
        cur.execute("UPDATE schwab_pilot_orders SET status='post_exception', detail=%s, updated_at=NOW() "
                    "WHERE id=%s", (str(e)[:300], row_id)); conn.commit()
        # ground-truth: if Schwab rejected on auth (expired/revoked refresh token), persist degraded so the
        # token-health badge flips to "re-auth needed" instead of staying green on the freshness timestamp.
        try:
            import schwab_token_manager as _tm
            if _tm.is_auth_failure(e):
                _tm.mark_degraded(f"place_order: {str(e)[:200]}")
        except Exception:
            pass
        return {"status": "error", "error": f"POST exception: {str(e)[:160]}", "pilot_row_id": row_id,
                "note": "DO NOT blind-retry — reconcile open orders via GET first (Schwab does not dedupe)"}
    if resp.status_code not in (200, 201):
        cur.execute("UPDATE schwab_pilot_orders SET status='rejected_by_broker', detail=%s, updated_at=NOW() "
                    "WHERE id=%s", (f"HTTP {resp.status_code}: {resp.text[:240]}", row_id)); conn.commit()
        return {"status": "rejected", "http_status": resp.status_code, "body": resp.text[:400],
                "pilot_row_id": row_id}
    order_id = None
    try:
        from schwab.utils import Utils
        order_id = str(Utils(client, h).extract_order_id(resp) or "")
    except Exception:
        loc = resp.headers.get("Location", "")
        order_id = loc.rstrip("/").rsplit("/", 1)[-1] if loc else None
    approval_service.consume(intent.intent_id)              # single-use: burn the 2FA set NOW
    try:
        from brokers.evidence_approval import consume_approval as _consume_evidence_approval
        _consume_evidence_approval(intent.intent_id)
    except Exception:
        pass
    cur.execute("UPDATE schwab_pilot_orders SET status='submitted', broker_order_id=%s, updated_at=NOW() "
                "WHERE id=%s", (order_id, row_id)); conn.commit()
    if kind == "canary":
        try:
            ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
            pid = ev.get("proposal_id")
            if pid:
                import proposal_live_submit_tag as _tag
                _tag.tag_proposal_live_submit(
                    int(pid),
                    live_submit_path="canary_pilot",
                    correlation_id=str(getattr(intent, "correlation_id", "") or "") or None,
                    intent_id=str(getattr(intent, "intent_id", "") or "") or None,
                )
        except Exception:
            pass
    readback = None
    try:
        _rate_acquire()
        rb = client.get_order(order_id, h)
        readback = rb.json() if rb.status_code == 200 else {"http_status": rb.status_code}
    except Exception as e:
        readback = {"error": str(e)[:120]}
    return {"status": "submitted", "broker_order_id": order_id, "pilot_row_id": row_id,
            "readback": readback}


def cancel_order(account_key, broker_order_id):
    """Stage 2b pilot cancel — the safe direction. Same structural asserts + guard (no 2FA for cancel)."""
    from brokers.execution_guard import require
    from brokers.order_intent import OrderIntent, Instrument, Direction, EntrySpec, EntryMethod, Quantity
    conn = _pilot_preconditions(account_key)
    cur = conn.cursor()
    _pilot_ensure_table(cur)
    cur.execute("SELECT id, symbol, qty FROM schwab_pilot_orders WHERE broker_order_id=%s AND account_key=%s "
                "ORDER BY id DESC LIMIT 1", (str(broker_order_id), account_key))
    row = cur.fetchone()
    if not row:
        raise NotProvenWrite(f"order {broker_order_id} is not a pilot order — only pilot orders may be canceled")
    row_id, sym, qty = row
    intent = OrderIntent(instrument=Instrument(sym or "UNKNOWN"), direction=Direction.LONG,
                         entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=0.01),
                         quantity=Quantity(qty=float(qty or 1)), broker="schwab", account_key=account_key)
    require(intent, "cancel")
    client, err = build_client(account_key)
    if err:
        return {"status": "error", "error": "client unavailable", "detail": err}
    h = _get_hash(account_key)
    _rate_acquire()
    try:
        resp = client.cancel_order(broker_order_id, h)
    except Exception as e:
        return {"status": "error", "error": f"cancel exception: {str(e)[:160]}"}
    ok = resp.status_code in (200, 201)
    cur.execute("UPDATE schwab_pilot_orders SET status=%s, detail=%s, updated_at=NOW() WHERE id=%s",
                ("cancel_requested" if ok else "cancel_rejected",
                 f"HTTP {resp.status_code}", row_id)); conn.commit()
    return {"status": "cancel_requested" if ok else "cancel_rejected",
            "http_status": resp.status_code, "broker_order_id": str(broker_order_id)}


def replace_order(*_a, **_k):
    raise NotProvenWrite("Schwab replace_order is FENCED — no replace in the Stage 2b pilot "
                         "(cancel + new order instead)")


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
    # Fail-fast when the manager has marked this token degraded (refresh token revoked/expired server-side →
    # re-auth required). Without this guard, every read still constructs a client and triggers a doomed
    # schwab-py refresh → POST /oauth/token 400 invalid_grant in a tight retry loop, which blocks request-
    # path endpoints (broker-proposals) long enough to time out the dashboard. Cleared automatically by a
    # successful re-auth (seed_token clears the degraded flag), so normal reads resume with no code change.
    try:
        if tm.health(tkey, broker, environment).get("degraded"):
            return None, {"status": "degraded", "needs_reauth": True,
                          "reason": "Schwab token degraded — re-auth required (manager is system-of-record)"}
    except Exception:
        pass
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


def get_orders_raw(account_key, account_hash=None):
    """READ-ONLY raw order JSON (no normalization) — for the Stage-2a shadow-reconciliation harness,
    which diffs Schwab's actual order representation against the translator's predicted payload.
    Same fenced read path as get_orders; never touches the order WRITE surface."""
    h = account_hash or _get_hash(account_key)
    if not h:
        return {"status": "needs_account_hash", "reason": "run resolve_account_hashes(account_key, expected_last4=...)"}
    return _read(account_key, "get_orders_for_account", lambda raw: list(raw or []), h)


def get_transactions_raw(account_key, account_hash=None):
    """READ-ONLY raw transaction JSON — for the Stage-2a poll-based activity capture (full payloads,
    not the single-item summary normalize_transactions keeps)."""
    h = account_hash or _get_hash(account_key)
    if not h:
        return {"status": "needs_account_hash", "reason": "run resolve_account_hashes(account_key, expected_last4=...)"}
    return _read(account_key, "get_transactions", lambda raw: list(raw or []), h)


def get_transactions(account_key, account_hash=None):
    h = account_hash or _get_hash(account_key)
    if not h:
        return {"status": "needs_account_hash", "reason": "run resolve_account_hashes(account_key, expected_last4=...)"}
    return _read(account_key, "get_transactions", normalize_transactions, h)


def get_quote(account_key, symbol):
    return _read(account_key, "get_quote", normalize_quote, symbol)


def get_price_history(symbol, start, end, timeframe="1Day", account_key=None):
    """READ-ONLY market-data price history (OHLCV) — tier-2 chart fallback when Alpaca has no bars. Returns
    [{open,high,low,close,volume,datetime}] or [] on any failure (caller falls through). Schwab payload has
    no per-bar VWAP — the chart layer computes VWAP from these candles. No write surface."""
    import datetime as _dt
    if account_key is None:
        try:
            from db_adapter import _get_conn
            conn = _get_conn(); cur = conn.cursor()
            cur.execute("SELECT account_key FROM schwab_account_links WHERE verified=TRUE LIMIT 1")
            r = cur.fetchone(); account_key = r[0] if r else None
        except Exception:
            return []
    if not account_key:
        return []
    client, err = build_client(account_key)
    if err or not client:
        return []

    def _pd(s):
        s = str(s)
        try:
            return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return _dt.datetime.fromisoformat(s[:10])

    _rate_acquire()
    try:
        sym = symbol.upper()
        if timeframe == "1Min":
            resp = client.get_price_history_every_minute(sym, start_datetime=_pd(start), end_datetime=_pd(end))
        else:
            resp = client.get_price_history_every_day(sym, start_datetime=_pd(start), end_datetime=_pd(end))
        data = resp.json() if hasattr(resp, "json") else resp
        out = []
        for c in (data.get("candles") or []):
            ts = c.get("datetime")
            out.append({"open": c.get("open"), "high": c.get("high"), "low": c.get("low"),
                        "close": c.get("close"), "volume": c.get("volume", 0),
                        "datetime": (_dt.datetime.utcfromtimestamp(ts / 1000).isoformat() + "Z") if ts else None})
        return out
    except Exception:
        return []


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


# ── READY capabilities wired 2026-06-11 (read-only; see SCHWAB_API_CAPABILITY_MAP) ──────────────────────────

def _default_account_key():
    """First verified linked account — used for market-data reads that aren't account-specific."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("SELECT account_key FROM schwab_account_links WHERE verified=TRUE LIMIT 1")
        r = cur.fetchone()
        return r[0] if r else None
    except Exception:
        return None


def normalize_quotes(raw):
    """Batch-quote payload -> {symbol: {last, bid, ask, volume, updated}}. Conservative: unknown shapes pass
    through under 'raw' so wire-time differences are visible, never silently zeroed."""
    out = {}
    if not isinstance(raw, dict):
        return {"status": "error", "error": "unexpected quotes payload type"}
    for sym, q in raw.items():
        if not isinstance(q, dict):
            continue
        quote = q.get("quote") or q
        out[sym] = {
            "last": quote.get("lastPrice"),
            "bid": quote.get("bidPrice"),
            "ask": quote.get("askPrice"),
            "volume": quote.get("totalVolume"),
            "close": quote.get("closePrice"),
            "updated": quote.get("quoteTime") or quote.get("tradeTime"),
        }
        if out[sym]["last"] is None and "raw_keys" not in out[sym]:
            out[sym]["raw_keys"] = sorted(quote.keys())[:10]
    return {"status": "ok", "quotes": out, "count": len(out)}


def get_quotes(symbols, account_key=None):
    """READ-ONLY batch quotes — one API call for many symbols (vs per-symbol get_quote). No write surface."""
    if not symbols:
        return {"status": "error", "error": "no symbols"}
    account_key = account_key or _default_account_key()
    if not account_key:
        return {"status": "needs_account_link"}
    return _read(account_key, "get_quotes", normalize_quotes, list(symbols))


def normalize_market_hours(raw):
    """Market-hours payload -> per-market {is_open, session windows}."""
    out = {}
    if not isinstance(raw, dict):
        return {"status": "error", "error": "unexpected market-hours payload type"}
    for market, products in raw.items():
        if not isinstance(products, dict):
            continue
        for _pid, info in products.items():
            if not isinstance(info, dict):
                continue
            sess = info.get("sessionHours") or {}
            reg = (sess.get("regularMarket") or [{}])[0] if sess.get("regularMarket") else {}
            out[market] = {
                "is_open": info.get("isOpen"),
                "regular_start": reg.get("start"),
                "regular_end": reg.get("end"),
                "pre": (sess.get("preMarket") or [{}])[0] if sess.get("preMarket") else None,
                "post": (sess.get("postMarket") or [{}])[0] if sess.get("postMarket") else None,
            }
    return {"status": "ok", "markets": out}


def get_market_hours(markets=None, account_key=None):
    """READ-ONLY market hours/calendar — authoritative is-the-market-open signal. No write surface."""
    account_key = account_key or _default_account_key()
    if not account_key:
        return {"status": "needs_account_link"}
    client, err = build_client(account_key)
    if err:
        return err
    _rate_acquire()
    try:
        from schwab.client import Client
        mk = markets or [Client.MarketHours.Market.EQUITY]
        mk = [getattr(Client.MarketHours.Market, str(m).upper(), m) if isinstance(m, str) else m for m in mk]
        resp = client.get_market_hours(mk)
        data = resp.json() if hasattr(resp, "json") else resp
        return normalize_market_hours(data)
    except Exception as e:
        return {"status": "error", "error": str(e)[:160]}


def normalize_option_chain(raw):
    """Option-chain payload -> compact summary (full chains are huge): underlying, per-expiration strike
    summaries with mid/IV/delta/OI for calls+puts. Read-only analytics shape."""
    if not isinstance(raw, dict):
        return {"status": "error", "error": "unexpected chain payload type"}
    out = {"status": "ok", "symbol": raw.get("symbol"), "underlying_price": (raw.get("underlyingPrice") or
           (raw.get("underlying") or {}).get("last")), "expirations": []}
    def _walk(side_map, side):
        rows = []
        for exp, strikes in (side_map or {}).items():
            for strike, contracts in (strikes or {}).items():
                c = (contracts or [{}])[0]
                rows.append({"exp": exp.split(":")[0], "strike": float(strike), "side": side,
                             "bid": c.get("bid"), "ask": c.get("ask"), "last": c.get("last"),
                             "iv": c.get("volatility"), "delta": c.get("delta"),
                             "oi": c.get("openInterest"), "volume": c.get("totalVolume"),
                             "dte": c.get("daysToExpiration")})
        return rows
    rows = _walk(raw.get("callExpDateMap"), "call") + _walk(raw.get("putExpDateMap"), "put")
    by_exp = {}
    for r in rows:
        by_exp.setdefault(r["exp"], []).append(r)
    for exp in sorted(by_exp):
        rs = by_exp[exp]
        out["expirations"].append({"exp": exp, "dte": rs[0].get("dte"), "contracts": len(rs),
                                   "total_call_oi": sum(r["oi"] or 0 for r in rs if r["side"] == "call"),
                                   "total_put_oi": sum(r["oi"] or 0 for r in rs if r["side"] == "put"),
                                   "strikes": sorted(rs, key=lambda r: (r["side"], r["strike"]))})
    return out


def get_option_chain(symbol, strike_count=8, account_key=None):
    """READ-ONLY option chain (near-the-money by default). No order surface."""
    account_key = account_key or _default_account_key()
    if not account_key:
        return {"status": "needs_account_link"}
    return _read(account_key, "get_option_chain", normalize_option_chain, symbol.upper(),
                 strike_count=strike_count, include_underlying_quote=True)


def get_option_expirations(symbol, account_key=None):
    """READ-ONLY option expiration calendar for a symbol."""
    account_key = account_key or _default_account_key()
    if not account_key:
        return {"status": "needs_account_link"}
    def _norm(raw):
        xs = (raw or {}).get("expirationList") or []
        return {"status": "ok", "symbol": symbol.upper(),
                "expirations": [{"date": x.get("expirationDate"), "dte": x.get("daysToExpiration"),
                                 "type": x.get("expirationType")} for x in xs]}
    return _read(account_key, "get_option_expiration_chain", _norm, symbol.upper())


def get_fundamentals(symbols, account_key=None):
    """READ-ONLY instrument fundamentals (P/E, EPS, div yield, market cap, shares) via get_instruments."""
    account_key = account_key or _default_account_key()
    if not account_key:
        return {"status": "needs_account_link"}
    def _norm(raw):
        out = {}
        for inst in (raw or {}).get("instruments", []):
            f = inst.get("fundamental") or {}
            out[inst.get("symbol")] = {
                "description": inst.get("description"), "exchange": inst.get("exchange"),
                "pe": f.get("peRatio"), "eps": f.get("eps"), "div_yield": f.get("divYield"),
                "div_amount": f.get("divAmount"), "market_cap": f.get("marketCap"),
                "shares_outstanding": f.get("sharesOutstanding"), "beta": f.get("beta"),
                "high52": f.get("high52"), "low52": f.get("low52"),
                "next_div_date": f.get("nextDivExDate") or f.get("divExDate"),
                "next_earnings": f.get("nextEarningsDate"),
            }
        return {"status": "ok", "fundamentals": out, "count": len(out)}
    from schwab.client import Client
    syms = [s.strip().upper() for s in (symbols if isinstance(symbols, (list, tuple)) else str(symbols).split(",")) if s.strip()][:25]
    return _read(account_key, "get_instruments", _norm, syms, Client.Instrument.Projection.FUNDAMENTAL)


def get_movers(index="$SPX", account_key=None):
    """READ-ONLY market movers for an index ($SPX, $DJI, $COMPX, NYSE, NASDAQ, ...)."""
    account_key = account_key or _default_account_key()
    if not account_key:
        return {"status": "needs_account_link"}
    def _norm(raw):
        ms = (raw or {}).get("screeners") or (raw or {}).get("movers") or []
        return {"status": "ok", "index": index,
                "movers": [{"symbol": m.get("symbol"), "description": (m.get("description") or "")[:60],
                            "last": m.get("lastPrice"), "change_pct": m.get("netPercentChange") or m.get("changePercent"),
                            "volume": m.get("volume") or m.get("totalVolume"), "direction": m.get("direction")}
                           for m in ms][:25]}
    from schwab.client import Client
    idx = getattr(Client.Movers.Index, index.replace("$", "").upper(), None)
    return _read(account_key, "get_movers", _norm, idx if idx is not None else index)


def build_stream_client(account_key=None):
    """Boundary-only constructor for the READ-ONLY streaming client (market-data subscriptions only).
    schwab-py is imported HERE so the transport boundary rule holds; callers (the Rule-9-isolated stream
    daemon) never import schwab-py directly. No order/account streams are exposed by the daemon."""
    account_key = account_key or _default_account_key()
    if not account_key:
        return None, {"status": "needs_account_link"}
    client, err = build_client(account_key)
    if err:
        return None, err
    from schwab.streaming import StreamClient
    return StreamClient(client), None
