"""trade_fill_verifier.py — two-source fill verification (TradeAI + Hermes), vendor-neutral.

A trade is COUNTED toward the win-rate/live-gate only if it is broker-proven:
  1. has a broker_order_id, AND
  2. the broker confirms it filled (via the contract), AND
  3. TradeAI re-verifies the order exists with matching qty/price, AND
  4. Hermes independently re-verifies (read-only) and agrees.

This module names NO broker — it resolves the adapter from the account. Hermes writes its
verdict to hermes_fill_verifications ONLY; it never mutates paper_trades (challenger wall).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from broker_adapter import adapter_for

HERMES_DDL = """
CREATE TABLE IF NOT EXISTS hermes_fill_verifications (
    id              bigserial PRIMARY KEY,
    paper_trade_id  bigint NOT NULL,
    broker          text,
    broker_order_id text,
    hermes_confirmed boolean,
    qty_match       boolean,
    price_match     boolean,
    verdict         text,            -- VERIFIED | UNCONFIRMED | MISMATCH | NO_ORDER_ID
    detail          text,
    checked_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_hfv_trade ON hermes_fill_verifications(paper_trade_id);
"""

_QTY_TOL = 0.01
_PRICE_TOL_PCT = 0.01    # 1%


def _qty_match(fc_qty, trade_qty):
    if fc_qty is None or trade_qty in (None, 0):
        return False
    return abs(float(fc_qty) - float(trade_qty)) <= max(_QTY_TOL, abs(float(trade_qty)) * 0.001)


def _price_match(fc_price, trade_price):
    if fc_price is None or trade_price in (None, 0):
        return False
    return abs(float(fc_price) - float(trade_price)) / max(abs(float(trade_price)), 0.01) <= _PRICE_TOL_PCT


def trade_ai_verify(trade: dict) -> dict:
    """TradeAI's independent re-query: does the order exist, filled, qty/price match?"""
    oid = trade.get("broker_order_id")
    if not oid:
        return {"verified": False, "verdict": "NO_ORDER_ID", "qty_match": False, "price_match": False}
    try:
        adapter = adapter_for(trade.get("account"))
    except Exception as e:
        return {"verified": False, "verdict": "NO_ADAPTER", "detail": str(e), "qty_match": False, "price_match": False}
    s = adapter.get_order_status(oid)
    qm = _qty_match(s.filled_qty, trade.get("shares"))
    pm = _price_match(s.filled_price, trade.get("entry_price"))
    verified = bool(s.confirmed and qm and pm)
    verdict = "VERIFIED" if verified else ("UNCONFIRMED" if not s.confirmed else "MISMATCH")
    return {"verified": verified, "verdict": verdict, "qty_match": qm, "price_match": pm,
            "broker_status": s.status, "filled_qty": s.filled_qty, "filled_price": s.filled_price}


def hermes_verify(conn, trade: dict) -> dict:
    """Hermes's INDEPENDENT read-only re-check. Writes only to hermes_fill_verifications."""
    cur = conn.cursor()
    cur.execute(HERMES_DDL)
    oid = trade.get("broker_order_id")
    broker = None
    if not oid:
        verdict, confirmed, qm, pm = "NO_ORDER_ID", False, False, False
        detail = "no broker_order_id to verify against"
    else:
        try:
            adapter = adapter_for(trade.get("account"))
            broker = adapter.broker_name
            s = adapter.get_order_status(oid)
            qm = _qty_match(s.filled_qty, trade.get("shares"))
            pm = _price_match(s.filled_price, trade.get("entry_price"))
            confirmed = bool(s.confirmed)
            if confirmed and qm and pm:
                verdict = "VERIFIED"
            elif not confirmed:
                verdict = "UNCONFIRMED"
            else:
                verdict = "MISMATCH"
            detail = f"broker_status={s.status} filled_qty={s.filled_qty} filled_price={s.filled_price}"
        except Exception as e:
            verdict, confirmed, qm, pm = "UNCONFIRMED", False, False, False
            detail = f"verify error: {e}"
    cur.execute(
        """INSERT INTO hermes_fill_verifications
               (paper_trade_id, broker, broker_order_id, hermes_confirmed, qty_match, price_match, verdict, detail)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        [trade["id"], broker, oid, confirmed, qm, pm, verdict, detail],
    )
    conn.commit()
    return {"confirmed": confirmed, "verdict": verdict, "qty_match": qm, "price_match": pm, "detail": detail}


def is_counted(trade: dict, tradeai: dict, hermes: dict) -> bool:
    """The COUNTED rule — broker-proven and two-source agreement. (Computed only in STEP 2.)"""
    return bool(trade.get("broker_order_id")) and tradeai.get("verified") and hermes.get("confirmed")


import logging as _logging
_log = _logging.getLogger("trade-fill-verifier")

# Additive, nullable — no rewrite of existing rows.
_VERIFY_COLUMNS_DDL = """
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS confirmation_state text;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS fill_verified_by   text;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS fill_verified_at   timestamptz;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS fill_verified_ok   boolean;
"""
_columns_ensured = False


def _ensure_verify_columns(conn):
    global _columns_ensured
    if _columns_ensured:
        return
    try:
        cur = conn.cursor()
        cur.execute(_VERIFY_COLUMNS_DDL)
        conn.commit()
        _columns_ensured = True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log.warning(f"_ensure_verify_columns failed: {e}")


def verify_and_stamp_fill(conn, trade_id):
    """LIVE post-fill hook — confirm a freshly-opened trade at ITS broker and run two-source
    (TradeAI + Hermes) verification, stamping the result on the trade and into the
    hermes_fill_verifications staging table.

    NON-FATAL by contract: it never raises into the execution path and never closes/blocks/
    quarantines a position — it only records what the broker says. Downstream policy (the gate's
    COUNTED rule, the integrity audit) decides what to do with an unverified trade. Broker is the
    source of truth; this resolves the adapter from the account and names no vendor.
    """
    try:
        _ensure_verify_columns(conn)
        cur = conn.cursor()
        cur.execute("""SELECT id, symbol, account, shares, entry_price, broker_order_id
                       FROM paper_trades WHERE id=%s""", [trade_id])
        row = cur.fetchone()
        if not row:
            return None
        trade = dict(zip([d[0] for d in cur.description], row))

        from broker_confirmation_gate import confirm_and_finalize
        _fc, state = confirm_and_finalize(trade, apply=False)   # confirm at broker; we stamp here
        ai = trade_ai_verify(trade)                              # TradeAI re-query
        hz = hermes_verify(conn, trade)                          # Hermes independent (writes staging)

        # THREE-STATE, not two. A real trade whose verification merely COULDN'T RUN must never be
        # recorded the same as one the broker actively refutes — otherwise an API outage or an
        # adapter-less account would silently drop real trades from the gate.
        #   TRUE  = broker confirms filled AND both agree            -> safe to count
        #   FALSE = broker TERMINALLY says no fill (canceled/rejected/expired) -> the only true exclude
        #   NULL  = couldn't verify (unknown / no adapter / no order id / error / qty-price mismatch
        #           on an otherwise-real fill) -> downstream MUST fall back to the phantom-flag rule
        bstatus = (ai.get("broker_status") or "").lower()
        if ai.get("verified") and hz.get("confirmed"):
            verified_ok = True
        elif bstatus in ("canceled", "cancelled", "rejected", "expired"):
            verified_ok = False
        else:
            verified_ok = None

        cur.execute("""UPDATE paper_trades
                          SET confirmation_state=%s, fill_verified_by='tradeai',
                              fill_verified_at=NOW(), fill_verified_ok=%s
                        WHERE id=%s""", [state, verified_ok, trade_id])
        conn.commit()
        _log.info(f"[verify] #{trade_id} {trade.get('symbol')} state={state} "
                  f"tradeai={ai['verdict']} hermes={hz['verdict']} verified_ok={verified_ok}")
        return {"trade_id": trade_id, "state": state, "tradeai": ai["verdict"],
                "hermes": hz["verdict"], "verified_ok": verified_ok}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log.warning(f"verify_and_stamp_fill({trade_id}) non-fatal error: {e}")
        return None
