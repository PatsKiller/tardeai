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
from tg_chat_ids import chat_ids  # no hardcoded chat IDs


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
        for cid in chat_ids():
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": cid, "text": msg}, timeout=8)
    except Exception:
        pass


def protected_holdings_write(new_holdings, source="schwab_sync", account_key="schwab", protect_basis=False,
                            target_path=None, skip_transfer_detect=False):
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

    # ── SSOT BASIS SHIELD (root fix 2026-06-12) ──────────────────────────────────────────────
    # Rows whose basis came from the single-source-of-truth hierarchy (csv tax lot > broker API
    # averagePrice; see sync_basis_from_broker.py) are STICKY against every writer EXCEPT the SSOT
    # syncer itself. Found live: a pipeline writer was reverting corrected basis VALUES while the
    # source label survived (SCHD $127,954 -> $16,562 etc.). Enforced here — the one gate all
    # writers funnel through (holdings_guard re-exports this) — so no individual pipeline can ever
    # resurrect stale basis again. Each shielded restore is logged WITH the writer's source, which
    # also unmasks the reverting pipeline on its next attempt. Fail-soft: shield errors never block.
    if source != "broker_basis_sync" and HP.exists():
        try:
            _cur_rows = _positions_of(json.loads(HP.read_text()))
            _protected = {((p.get("symbol") or "").upper(), p.get("account") or ""):
                          (p.get("cost_basis"), p.get("cost_basis_source"))
                          for p in _cur_rows
                          if p.get("cost_basis_source") in ("csv_lot", "broker_api", "txn_history") and p.get("cost_basis")}
            _shielded = []
            for p in _positions_of(new_holdings):
                k = ((p.get("symbol") or "").upper(), p.get("account") or "")
                if k in _protected:
                    keep_cb, keep_src = _protected[k]
                    new_cb = p.get("cost_basis")
                    if new_cb is None or abs(float(new_cb) - float(keep_cb)) > max(1.0, 0.001 * float(keep_cb)):
                        p["cost_basis"] = keep_cb
                        p["cost_basis_source"] = keep_src
                        mv = p.get("market_value")
                        if mv is not None and keep_cb:
                            p["gain_loss"] = round(float(mv) - float(keep_cb), 2)
                            p["gain_loss_pct"] = round((float(mv) - float(keep_cb)) / float(keep_cb) * 100, 4)
                        _shielded.append(f"{k[0]}@{k[1].replace('schwab_','')}:{new_cb}->{keep_cb}")
            if _shielded:
                _record(account_key, "basis_shielded",
                        f"[{source}] SSOT basis shield restored {len(_shielded)}: " + "; ".join(_shielded[:6]))
                print(f"  [holdings-guard] SSOT basis shield: writer '{source}' tried to change "
                      f"{len(_shielded)} protected basis value(s) — restored: {'; '.join(_shielded[:6])}")
        except Exception:
            pass  # shield is best-effort; never blocks a write

    # preserve manually-repaired tax-grade basis — Schwab sync only (opt-in), never for general writers
    flagged = check_basis_divergence(new_holdings, account_key) if protect_basis else []
    if protect_basis and flagged and HP.exists():
        try:
            # KEY BY (symbol, account) — NOT symbol alone. A symbol held in >1 account (SCHD/SCHG in both
            # taxable and the IRAs) has a DIFFERENT basis per account; a symbol-only key cross-contaminated
            # them (taxable SCHD got the rollover IRA's $127,953 → phantom -90% P&L). 2026-06-16 root fix.
            def _bk(_p):
                return ((_p.get("symbol") or _p.get("ticker") or "").upper(),
                        _p.get("account") or _p.get("account_id") or _p.get("account_key") or "")
            stored = {_bk(_p): (_p.get("cost_basis") or _p.get("avg_cost") or _p.get("average_price") or _p.get("basis"))
                      for _p in _positions_of(json.load(open(HP)))}
            for p in _positions_of(new_holdings):
                k = _bk(p)
                if k in stored and stored[k] and any(f["symbol"] == k[0] for f in flagged):
                    p["cost_basis"] = stored[k]          # keep the manually-repaired basis (per account)
                    p["_basis_divergence_flagged"] = True
        except Exception:
            pass

    backup = None
    prior_doc = None
    if HP.exists():
        backup = HP.read_bytes()
        try:
            prior_doc = json.loads(backup.decode())
        except Exception:
            prior_doc = None

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

    # Held-state change → re-queue CIO synthesis for affected watchlist symbols (advisory, non-fatal).
    # This is the single write gate for both the Schwab sync and the SnapTrade merge, so hooking here
    # covers every position-changing path — see scripts/holdings_change_trigger.py.
    try:
        from holdings_change_trigger import check_and_enqueue
        trig = check_and_enqueue(apply=True)
        if trig.get("changed"):
            print(f"  [holdings-change] {trig['summary']}")
    except Exception as _e:
        print(f"  [holdings-change] trigger failed (non-fatal): {str(_e)[:120]}")

    # Cross-account transfer detection + normalization (Fidelity→Schwab rollover, Trad→Roth ladder).
    # Carry cost basis, stamp transfer_history / original_source_account, persist DB audit, and
    # re-write holdings when any provenance/basis change was applied (never silent fabrication).
    if not skip_transfer_detect and prior_doc is not None:
        try:
            from lib.cost_basis_transfer import process_holdings_change
            xfer = process_holdings_change(prior_doc, new_holdings, sync_source=source, apply=True)
            if xfer.get("events"):
                print(f"  [transfer-normalize] {xfer.get('summary')}")
                if xfer.get("stop_flags"):
                    print(f"  [transfer-normalize] {len(xfer['stop_flags'])} stop(s) may need replace-mode resize")
                tagged = xfer.get("holdings_doc")
                # Rewrite when overrides applied OR positions were provenance-normalized
                if tagged and (xfer.get("applied_overrides") or xfer.get("normalized") or xfer.get("holdings_tagged")):
                    fd2, tmp2 = tempfile.mkstemp(dir=str(HP.parent), suffix=".tmp")
                    with os.fdopen(fd2, "w") as f:
                        json.dump(tagged, f, indent=2, default=str)
                    os.replace(tmp2, HP)
        except Exception as _e:
            print(f"  [transfer-normalize] detect failed (non-fatal): {str(_e)[:120]}")

    return {"wrote": True, "status": "ok", "total_value": v, "position_count": n, "basis_flags": flagged}


def _looks_like_cusip(sym):
    """A 9-char alphanumeric symbol containing digits = a CUSIP, which Schwab returns as the 'symbol' ONLY
    when there is no active ticker (delisted/closed). Normal tickers are ≤6 letters with no digit run."""
    return bool(sym) and len(sym) == 9 and sym.isalnum() and not sym.isalpha() and any(c.isdigit() for c in sym)


def _mark_delisted(row, sym):
    """Auto-flag a delisted position (symbol came back as a CUSIP). Self-clearing: if it ever re-prices to
    a real ticker, the flag/bucket are removed on the next sync."""
    if _looks_like_cusip(sym):
        row["delisted"] = True
        row["market_value"] = 0.0
        row["price"] = 0.0
        row["bucket"] = "Delisted/Worthless"
        if not row.get("name") or row.get("name") == sym:
            row["name"] = f"DELISTED — CUSIP {sym}"
    elif row.get("delisted"):                       # was flagged, now a real ticker → un-flag
        row.pop("delisted", None)
        if row.get("bucket") == "Delisted/Worthless":
            row["bucket"] = "US Equity"
    return row


def _build_account_rows(account_key, live, existing_by_key):
    """Build holdings rows for ONE account from live Schwab positions, PRESERVING enrichment (name/bucket/
    cost_basis/sector) on positions we already track; minimal row for genuinely-new buys. Drops sold
    positions (absent from `live`). The repricer/basis-sync refine prices/basis afterward.

    Share reconciliation (2026-07-15): always stamp broker_actual_shares from live qty. For small
    positive DRIP-like drift, keep prior system shares sticky and open an approval task — do not
    silently inflate stop/risk sizing until the operator reconciles.
    """
    as_of = datetime.now(timezone.utc).date().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    drift_events = []
    for p in live:
        sym = (p.get("symbol") or "").upper()
        if not sym:
            continue
        try:
            qty = float(p.get("qty") or 0)
        except Exception:
            qty = 0.0
        if abs(qty) < 1e-9:
            continue
        def _f(x):
            try:
                return float(x)
            except Exception:
                return None
        price = _f(p.get("current_price")) or None
        mv = _f(p.get("market_value")) or 0.0
        avg = _f(p.get("avg_entry_price")) or None
        prior = existing_by_key.get((sym, account_key))
        row = dict(prior or {})   # preserve enrichment if tracked
        is_new = prior is None
        row.update({"account": account_key, "account_id": account_key, "symbol": sym,
                    "price": price, "market_value": round(mv, 2),
                    "as_of": as_of, "updated_at": now, "is_cash": (sym == "CASH")})
        # Share drift policy (approval-based for DRIP-like increases)
        try:
            from share_reconciliation import stamp_broker_qty
            share_fields, drift_ev = stamp_broker_qty(
                prior, qty, account_key=account_key, symbol=sym, name=row.get("name"))
            row.update(share_fields)
            if drift_ev:
                drift_events.append(drift_ev)
            # market_value: if shares sticky below broker, scale MV by system shares / broker when price known
            sys_sh = float(row.get("shares") or qty)
            if price and abs(sys_sh - qty) > 1e-6 and qty > 0:
                row["market_value"] = round(sys_sh * price, 2)
            elif not price and qty > 0 and abs(sys_sh - qty) > 1e-6:
                row["market_value"] = round(mv * (sys_sh / qty), 2)
        except Exception as _se:
            row["shares"] = qty
            row["system_shares"] = qty
            row["broker_actual_shares"] = qty
            print(f"  [share-recon] stamp failed {sym}: {str(_se)[:80]}")
        if is_new:
            row.setdefault("name", sym)
            row.setdefault("bucket", "US Equity")
            if avg and qty:
                row.setdefault("cost_basis", round(avg * float(row.get("shares") or qty), 2))
                row.setdefault("cost_basis_source", "broker_api")
            if row.get("cost_basis"):
                row["gain_loss"] = round(float(row.get("market_value") or mv) - float(row["cost_basis"]), 2)
                row["gain_loss_pct"] = round((float(row.get("market_value") or mv) - float(row["cost_basis"])) / float(row["cost_basis"]) * 100, 4) if float(row["cost_basis"]) else None
        rows.append(_mark_delisted(row, sym))   # auto-flag delisted (CUSIP-only) positions; self-clearing
    return rows, drift_events


# the broker account_key vs the holdings.json account label (the roth IRA is stored as 'schwab_roth')
_HOLDINGS_ACCT = {"schwab_roth_ira": "schwab_roth"}


def _cash_rows_for_account(label: str, hold: list, account_key: str, st) -> list:
    """Live Schwab cash balance → holdings CASH row (positions API omits cash)."""
    existing = [
        r for r in hold
        if r.get("account") == label
        and ((r.get("symbol") or "").upper() == "CASH" or r.get("is_cash"))
    ]
    acct = st.get_account(account_key)
    if not isinstance(acct, dict) or acct.get("status") != "active":
        return existing
    try:
        cash = float(acct.get("cash") or 0)
    except (TypeError, ValueError):
        return existing
    if cash <= 0:
        return existing
    now = datetime.now(timezone.utc).isoformat()
    as_of = datetime.now(timezone.utc).date().isoformat()
    row = dict(existing[0]) if existing else {}
    row.update({
        "symbol": "CASH",
        "account": label,
        "account_id": label,
        "asset_type": "cash",
        "is_cash": True,
        "shares": cash,
        "price": 1.0,
        "current_price": 1.0,
        "market_value": round(cash, 2),
        "name": row.get("name") or "Cash & Cash Investments",
        "source": "schwab_api",
        "updated_at": now,
        "as_of": as_of,
        "day_change": 0,
        "day_change_pct": 0,
    })
    return [row]


def sync_schwab_positions(account_key, dry_run=True):
    """LIVE Schwab position sync → holdings.json (auto-surface trades). Fetches live positions, replaces
    ONLY this account's equity rows (preserving every other account, the account's CASH row, and per-
    position enrichment), and writes through protected_holdings_write (GATE B: sane + catastrophic-drop
    guard + basis shield + backup/atomic/post-assert). dry_run=True returns the add/remove diff without
    writing. Cash row refreshed from Schwab account API cashBalance (positions endpoint excludes cash)."""
    import schwab_transport as st
    label = _HOLDINGS_ACCT.get(account_key, account_key)   # write/read under the holdings.json label
    live = st.get_positions(account_key)
    if not isinstance(live, list):
        reason = str(live)[:120]
        try:
            import schwab_token_manager as tm
            detail = reason
            if isinstance(live, dict):
                detail = " ".join(str(live.get(k, "")) for k in ("error", "reason", "status", "detail"))
            if tm.is_auth_failure(detail):
                tm.record_auth_failure(detail, account_key=account_key, source="schwab_position_sync")
        except Exception:
            pass
        _record(account_key, "degraded_noop", f"live fetch unavailable: {reason}")
        return {"status": "degraded_noop", "reason": reason, "wrote": False}
    if not HOLDINGS_PATH.exists():
        return {"status": "no_holdings_file", "wrote": False}
    cur = json.loads(HOLDINGS_PATH.read_text())
    hold = cur.get("holdings", [])
    existing_by_key = {((r.get("symbol") or "").upper(), label): r
                       for r in hold if r.get("account") == label}
    equity_rows, drift_events = _build_account_rows(label, live, existing_by_key)
    # Cash from Schwab account API (positions endpoint omits cash); fall back to existing row on API miss.
    cash_rows = _cash_rows_for_account(label, hold, account_key, st)
    new_rows = equity_rows + cash_rows
    old_syms = {(r.get("symbol") or "").upper() for r in hold if r.get("account") == label}
    new_syms = {(r.get("symbol") or "").upper() for r in new_rows}
    added, removed = sorted(new_syms - old_syms), sorted(old_syms - new_syms)
    if dry_run:
        return {"status": "dry_run", "broker_account": account_key, "holdings_label": label,
                "live_positions": len(equity_rows), "added": added, "removed": removed,
                "share_drift_events": drift_events, "wrote": False}
    cur["holdings"] = [r for r in hold if r.get("account") != label] + new_rows
    res = protected_holdings_write(cur, source="schwab_position_sync", account_key=account_key, protect_basis=True)
    res.update({"added": added, "removed": removed})
    # Open approval tasks for DRIP-like share drift (non-fatal)
    if drift_events:
        try:
            from share_reconciliation import process_sync_events
            res["share_drift_tasks"] = process_sync_events(drift_events)
            res["share_drift_events"] = drift_events
        except Exception as _de:
            res["share_drift_error"] = str(_de)[:120]
            print(f"  [share-recon] process_sync_events failed: {str(_de)[:120]}")
    return res


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("account", nargs="?", default=None, help="one account, or omit for all 3 Schwab accounts")
    ap.add_argument("--apply", action="store_true", help="write (default is dry-run diff)")
    a = ap.parse_args()
    accts = [a.account] if a.account else ["schwab_taxable", "schwab_roth_ira", "schwab_rollover_ira"]
    for acct in accts:
        print(json.dumps({acct: sync_schwab_positions(acct, dry_run=not a.apply)}, indent=2, default=str))
