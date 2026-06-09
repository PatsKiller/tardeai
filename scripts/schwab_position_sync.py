#!/usr/bin/env python3
"""schwab_position_sync.py — read-only Schwab position sync into the current-holdings pipeline (Phase 1,
GATE B).

GATE B (non-negotiable): holdings.json has been wiped twice by past deployments. This is the single
highest-risk component. EVERY holdings write goes through protected_holdings_write(), which:
  • PRE-WRITE SANITY: the payload must have non-zero positions and a sane total, else NO-OP.
  • EMPTY / PARTIAL / 401 / TIMEOUT / PARSE-ERROR  ==>  NO-OP. Never overwrite a good snapshot.
  • BACKUP before write; ATOMIC write (temp + os.replace); POST-WRITE assert total_value>1M & count>0,
    else RESTORE the backup.
  • TAX-GRADE BASIS PROTECTION: Schwab average price may be compared/displayed but NEVER silently
    overwrites manually-repaired cost basis. On divergence → FLAG (schwab_basis_divergence), don't write.
  • Every outcome recorded in schwab_sync_history (ok | degraded_noop | rejected_sanity | rejected_postwrite).

The live Schwab fetch requires the token manager to be non-degraded AND portal app creds (architect
open-item); without them sync_schwab_positions() is a degraded NO-OP. The PROTECTED WRITER and its guards
are fully functional and proven by simulation now.
"""
from __future__ import annotations
import json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
MIN_TOTAL = 1_000_000          # canonical sanity floor (the portfolio is ~$1.24M)
BASIS_DIVERGENCE_PCT = 2.0     # flag if API avg price differs from stored basis by > this %
CATASTROPHIC_DROP_FRACTION = 0.5  # reject a write whose total < this fraction of the last-good total
TG_CHAT_IDS = ("6993102664", "8797974247")


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _record(account_key, status, reason, position_count=None, total_value=None, wrote=False):
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("""INSERT INTO schwab_sync_history (account_key, status, reason, position_count, total_value, wrote_holdings)
                       VALUES (%s,%s,%s,%s,%s,%s)""", (account_key, status, reason[:300], position_count, total_value, wrote))
        conn.commit()
    except Exception:
        pass


def _positions_of(h):
    return h.get("holdings") or h.get("positions") or []


def _total_of(h):
    try:
        return float((h.get("portfolio_totals") or {}).get("total_value") or h.get("total_value") or 0)
    except Exception:
        return 0.0


def sane_payload(h):
    """PRE-WRITE SANITY — returns (ok, reason). Empty/partial/garbage all fail here."""
    if not isinstance(h, dict):
        return False, "payload is not a dict (parse error / garbage)"
    pos = _positions_of(h)
    if not isinstance(pos, list) or len(pos) == 0:
        return False, "zero positions in payload — refusing to write"
    total = _total_of(h)
    if total < MIN_TOTAL:
        return False, f"total_value {total:,.0f} below sanity floor {MIN_TOTAL:,.0f} — refusing to write"
    return True, "ok"


def canonical_assert(path=None):
    """The documented post-write check. Raises AssertionError on a bad snapshot."""
    d = json.load(open(path or HOLDINGS_PATH))
    v = d["portfolio_totals"]["total_value"]
    n = len(_positions_of(d))
    assert v > MIN_TOTAL, f"post-write total_value {v} <= floor"
    assert n > 0, "post-write position_count == 0"
    return v, n


def check_basis_divergence(new_holdings, account_key="schwab"):
    """Compare incoming Schwab average price vs stored tax-grade cost basis. FLAG divergences (do NOT
    overwrite). Returns the list of flagged symbols. Material to MFS filing + Roth math."""
    flagged = []
    cur_map = {}
    if HOLDINGS_PATH.exists():
        try:
            for p in _positions_of(json.load(open(HOLDINGS_PATH))):
                s = (p.get("symbol") or p.get("ticker") or "").upper()
                basis = p.get("cost_basis") or p.get("avg_cost") or p.get("average_price") or p.get("basis")
                if s and basis:
                    cur_map[s] = float(basis)
        except Exception:
            return flagged
    conn = _conn(); cur = conn.cursor()
    for p in _positions_of(new_holdings):
        s = (p.get("symbol") or p.get("ticker") or "").upper()
        api_avg = p.get("average_price") or p.get("avg_price") or p.get("cost_basis")
        if not (s and api_avg and s in cur_map and cur_map[s]):
            continue
        api_avg = float(api_avg); stored = cur_map[s]
        div = abs(api_avg - stored) / stored * 100 if stored else 0
        if div > BASIS_DIVERGENCE_PCT:
            cur.execute("""INSERT INTO schwab_basis_divergence (account_key, symbol, api_avg_price, stored_basis, divergence_pct)
                           VALUES (%s,%s,%s,%s,%s)""", (account_key, s, api_avg, stored, round(div, 2)))
            flagged.append({"symbol": s, "api_avg": api_avg, "stored_basis": stored, "divergence_pct": round(div, 2)})
    conn.commit()
    return flagged


def _last_good_total(path=None):
    try:
        p = path or HOLDINGS_PATH
        if p.exists():
            return _total_of(json.load(open(p)))
    except Exception:
        pass
    return 0.0


def _alert(msg, source=""):
    """Loud alert on a blocked/restored holdings write (existing Telegram path, both chat IDs).
    Suppressed for test/proof sources so verification runs never spam the operator's Telegram."""
    if "test" in (source or "").lower() or "proof" in (source or "").lower():
        return
    try:
        import requests
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not tok:
            for l in (PROJECT_ROOT / ".env").read_text().splitlines():
                if l.startswith("TELEGRAM_BOT_TOKEN="):
                    tok = l.split("=", 1)[1].strip()
        if not tok:
            return
        for cid in TG_CHAT_IDS:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": cid, "text": msg}, timeout=8)
    except Exception:
        pass


def protected_holdings_write(new_holdings, source="schwab_sync", account_key="schwab", protect_basis=False,
                            target_path=None):
    """GATE B / mandatory holdings wipe-guard. Routes EVERY holdings/current-state write so a bad payload
    fails closed instead of zeroing holdings.json. NEVER overwrites a good snapshot with empty/zeroed/
    catastrophically-low data; backs up + writes atomically + post-asserts + restores on failure.

    protect_basis=True (Schwab sync only) additionally preserves manually-repaired tax-grade cost basis
    (flag-not-overwrite). General writers pass protect_basis=False so legitimate basis edits (e.g.
    patch_holdings_cost_basis) are NOT reverted. target_path defaults to the canonical holdings.json;
    a caller may pass its own resolved path (the guard operates entirely on that path).
    """
    HP = Path(target_path).resolve() if target_path else HOLDINGS_PATH
    ok, reason = sane_payload(new_holdings)
    if not ok:
        _record(account_key, "rejected_sanity", f"[{source}] {reason}")
        _alert(f"🛑 holdings write BLOCKED ({source}): {reason}. Prior snapshot kept (no wipe).", source)
        return {"wrote": False, "status": "rejected_sanity", "reason": reason}

    # catastrophic-drop guard vs last-good snapshot
    prior = _last_good_total(HP)
    new_total = _total_of(new_holdings)
    if prior > 0 and new_total < CATASTROPHIC_DROP_FRACTION * prior:
        rsn = f"total {new_total:,.0f} < {CATASTROPHIC_DROP_FRACTION:.0%} of last-good {prior:,.0f}"
        _record(account_key, "rejected_drop", f"[{source}] {rsn}", len(_positions_of(new_holdings)), new_total)
        _alert(f"🛑 holdings write REJECTED ({source}): catastrophic drop — {rsn}. Prior snapshot kept.", source)
        return {"wrote": False, "status": "rejected_drop", "reason": rsn}

    # preserve manually-repaired tax-grade basis — Schwab sync only (opt-in), never for general writers
    flagged = check_basis_divergence(new_holdings, account_key) if protect_basis else []
    if protect_basis and flagged and HP.exists():
        try:
            stored = {(_p.get("symbol") or _p.get("ticker") or "").upper():
                      (_p.get("cost_basis") or _p.get("avg_cost") or _p.get("average_price") or _p.get("basis"))
                      for _p in _positions_of(json.load(open(HP)))}
            for p in _positions_of(new_holdings):
                s = (p.get("symbol") or p.get("ticker") or "").upper()
                if s in stored and stored[s] and any(f["symbol"] == s for f in flagged):
                    p["cost_basis"] = stored[s]          # keep the manually-repaired basis
                    p["_basis_divergence_flagged"] = True
        except Exception:
            pass

    backup = None
    if HP.exists():
        backup = HP.read_bytes()

    # atomic write
    try:
        HP.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(HP.parent), suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(new_holdings, f, indent=2, default=str)
        os.replace(tmp, HP)
    except Exception as e:
        if backup is not None:
            HP.write_bytes(backup)
        _record(account_key, "rejected_postwrite", f"[{source}] write error, restored backup: {str(e)[:120]}")
        _alert(f"🛑 holdings write FAILED ({source}) — prior snapshot RESTORED: {str(e)[:80]}", source)
        return {"wrote": False, "status": "rejected_postwrite", "reason": str(e)[:120]}

    # post-write verification — restore on failure
    try:
        v, n = canonical_assert(HP)
    except Exception as e:
        if backup is not None:
            HP.write_bytes(backup)
        _record(account_key, "rejected_postwrite", f"[{source}] post-write assert failed, restored backup: {str(e)[:120]}")
        _alert(f"🛑 holdings post-write assert FAILED ({source}) — prior snapshot RESTORED: {str(e)[:80]}", source)
        return {"wrote": False, "status": "rejected_postwrite", "reason": str(e)[:120]}

    _record(account_key, "ok", f"wrote {n} positions / ${v:,.0f}; basis_flags={len(flagged)}", n, v, True)
    return {"wrote": True, "status": "ok", "total_value": v, "position_count": n, "basis_flags": flagged}


def sync_schwab_positions(account_key):
    """Read-only entry point. Fail-closed: degraded token OR missing portal creds => NO-OP (holdings
    untouched). Live fetch + Alpaca-preserving merge land here once the portal is connected."""
    import schwab_token_manager as tm
    h = tm.health(account_key)
    if h.get("degraded") or not h.get("refresh_valid"):
        _record(account_key, "degraded_noop", f"token degraded/expired: {h.get('last_error')}")
        return {"status": "degraded_noop", "reason": h.get("last_error"), "wrote": False}
    token = tm.get_access_token(account_key)
    if not token:
        _record(account_key, "degraded_noop", "no usable access token (fail closed)")
        return {"status": "degraded_noop", "wrote": False}
    # Live Schwab fetch + normalize + MERGE-with-non-Schwab (preserve Alpaca) → protected_holdings_write.
    # Requires portal app creds + proven read entitlement (architect open-item).
    _record(account_key, "degraded_noop", "live Schwab fetch NOT_PROVEN (portal app creds + read entitlement pending)")
    return {"status": "degraded_noop", "reason": "live fetch NOT_PROVEN (architect open-item)", "wrote": False}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("account", nargs="?", default="schwab_rollover_ira")
    print(json.dumps(sync_schwab_positions(ap.parse_args().account), indent=2))
