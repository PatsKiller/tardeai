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
# G2: scripts-only + lib — never also put scripts/lib or root on path
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
# MIN_TOTAL retained as a deprecated alias for import compatibility. It is NOT
# applied. Validation is coverage + relative-drop (see holdings_sanity).
MIN_TOTAL = None
BASIS_DIVERGENCE_PCT = 2.0     # flag if API avg price differs from stored basis by > this %
from lib.holdings_sanity import (  # noqa: E402
    CATASTROPHIC_DROP_FRACTION,
    REASON_VALID_COMPLETE,
    validate_payload,
)
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


def _last_good_doc(path=None):
    try:
        p = Path(path) if path else HOLDINGS_PATH
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return None


def sane_payload(h, last_good=None):
    """PRE-WRITE SANITY — same contract as canonical_assert()."""
    last = last_good if last_good is not None else _last_good_doc()
    v = validate_payload(h, last)
    return v.ok, f"{v.reason_code}: {v.reason}"


def canonical_assert(path=None, last_good=None):
    """Post-write check — identical contract to sane_payload()."""
    p = path or HOLDINGS_PATH
    d = json.load(open(p))
    last = last_good
    if last is None:
        # After a write the file IS the candidate; compare against in-memory prior if given.
        last = getattr(canonical_assert, "_prior", None)
    v = validate_payload(d, last)
    if not v.ok:
        raise AssertionError(f"post-write {v.reason_code}: {v.reason}")
    return v.total, v.position_count


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
    """Loud alert on a blocked/restored holdings write via telegram_alert chokepoint.
    Suppressed for test/proof sources so verification runs never spam the operator's Telegram."""
    if "test" in (source or "").lower() or "proof" in (source or "").lower():
        return
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="schwab_position_sync", subject_key="ops:holdings_guard",
                retention_class="operational", severity="critical",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def reconcile_totals(doc, *, source="unknown"):
    """Make portfolio_totals.total_value agree with the positions being written.

    Root fix 2026-08-27. A bulk position writer updated per-row `price` and
    `market_value` and left `portfolio_totals.total_value` at its previous
    figure, so the freshly-written copy was internally inconsistent by
    $3,748.04 on $1.288M while the older copy still reconciled exactly. The
    divergence between the two stores was the symptom; this was the defect.

    Applied HERE, before validation, at the one gate every holdings writer
    funnels through (holdings_guard re-exports it) -- the same reasoning as the
    SSOT basis shield above. Patching the individual writer would leave the next
    one free to reintroduce it; making the totals part of the write makes an
    internally inconsistent holdings.json structurally impossible.

    Deliberately BEFORE validate_payload, not after. holdings_sanity computes
    `total = declared if declared > 0 else summed`, so the wipe-guard trusts the
    declared figure -- a payload whose positions collapsed while its stated
    total stayed healthy would pass the catastrophic-drop check on the stale
    number. Recomputing first means the guard is evaluated on what is actually
    being written. That is strictly stronger: the only writes whose verdict can
    change are those where declared and summed disagree by more than
    CATASTROPHIC_DROP_FRACTION, which is exactly the masked catastrophe.

    Fail-soft: a correction is never worth blocking a write over. Returns the
    correction applied, or None.
    """
    try:
        pos = _positions_of(doc)
        if not pos:
            return None
        totals = doc.get("portfolio_totals")
        if not isinstance(totals, dict):
            return None
        summed = round(sum(float(p.get("market_value") or p.get("value") or 0)
                           for p in pos), 2)
        declared = float(totals.get("total_value") or 0)
        if abs(summed - declared) <= 0.01:
            return None
        totals["total_value"] = summed
        totals["total_value_recomputed_at_write"] = True
        correction = {"declared": declared, "summed": summed,
                      "delta": round(summed - declared, 2), "source": source}
        try:
            # Visible, not silent: a writer that keeps needing this is a bug.
            _record(source, "totals_recomputed",
                    f"[{source}] portfolio_totals.total_value {declared:,.2f} -> "
                    f"{summed:,.2f} (delta {correction['delta']:,.2f}) to match "
                    f"{len(pos)} positions being written",
                    len(pos), summed)
        except Exception:
            pass
        return correction
    except Exception:
        return None


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
    prior_doc = _last_good_doc(HP)
    # Totals must describe the positions in THIS payload -- see reconcile_totals.
    reconcile_totals(new_holdings, source=source)
    verdict = validate_payload(new_holdings, prior_doc)
    if not verdict.ok:
        status = "rejected_drop" if verdict.reason_code == "CATASTROPHIC_DROP" else "rejected_sanity"
        reason = f"{verdict.reason_code}: {verdict.reason}"
        _record(account_key, status, f"[{source}] {reason}", verdict.position_count, verdict.total)
        _alert(f"🛑 holdings write BLOCKED ({source}): {reason}. Prior snapshot kept (no wipe).", source)
        return {"wrote": False, "status": status, "reason": reason, "reason_code": verdict.reason_code,
                "missing_accounts": verdict.missing_accounts}

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
    if HP.exists():
        backup = HP.read_bytes()
        if prior_doc is None:
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
        v, n = canonical_assert(HP, last_good=prior_doc)
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

    # ROOT: sold names must not keep source='portfolio' rows (watchlist HELD badge /
    # watchlist_symbol_master.in_portfolio = bool_or(source='portfolio')).
    try:
        from sync_portfolio_watchlist_membership import sync_portfolio_watchlist_membership
        _ms = sync_portfolio_watchlist_membership(new_holdings)
        if _ms.get("exited") or _ms.get("ensured"):
            print(f"  [portfolio-membership] exited={_ms.get('exited')} ensured={_ms.get('ensured')}")
    except Exception as _e:
        print(f"  [portfolio-membership] sync failed (non-fatal): {str(_e)[:120]}")

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

    # G1 — resolution-layer dual-write. When the primary path is one of the
    # durable write targets (served/persistent + checkout), mirror the validated
    # bytes to the other targets so cron→dev and release readers cannot diverge
    # on the next write. Never runs for an arbitrary target_path (tests / one-offs),
    # and never merges two historically divergent copies — it writes ONE new
    # payload. report_authoritative_divergence reports existing forks.
    try:
        # scripts-only spelling (G2): this file runs with scripts/ on sys.path.
        from lib.persistent_state_root import portfolio_state_write_targets

        durable = [
            (d / "holdings.json").resolve()
            for d in portfolio_state_write_targets(PROJECT_ROOT)
        ]
        hp_res = HP.resolve()
        if hp_res in durable:
            primary_bytes = HP.read_bytes()
            for other in durable:
                if other == hp_res:
                    continue
                try:
                    other.parent.mkdir(parents=True, exist_ok=True)
                    fd2, tmp2 = tempfile.mkstemp(dir=str(other.parent), suffix=".tmp")
                    with os.fdopen(fd2, "wb") as f:
                        f.write(primary_bytes)
                    os.replace(tmp2, other)
                except OSError as e:
                    print(
                        f"  [holdings-guard] secondary write failed for {other}: "
                        f"{type(e).__name__}: {e}"
                    )
    except Exception as _e:
        print(f"  [holdings-guard] secondary mirror skipped (non-fatal): {str(_e)[:120]}")

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
                    "as_of": as_of, "updated_at": now, "is_cash": (sym == "CASH"),
                    # The broker confirmed this position NOW. portfolio_repricer's
                    # _preserve_broker_snapshot is deliberately write-once ("never
                    # overwrite with a later mark"), so it can only ever backfill this
                    # field when absent — it cannot refresh it. Nothing else set it, so
                    # it froze at the first backfill (observed 2026-08-14) while the
                    # rows beneath it kept updating daily, and every freshness consumer
                    # read a 18-day-old stamp on same-day data. The broker sync is the
                    # only writer that knows the real confirmation time; it stamps it.
                    "broker_position_as_of": as_of})
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
        "broker_position_as_of": as_of,   # see the equity-row note above
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
    # G2: after imports settle — refuse dual lib.X / scripts.lib.X identity
    from lib import assert_single_import_identity
    assert_single_import_identity()
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("account", nargs="?", default=None, help="one account, or omit for all 3 Schwab accounts")
    ap.add_argument("--apply", action="store_true", help="write (default is dry-run diff)")
    a = ap.parse_args()
    accts = [a.account] if a.account else ["schwab_taxable", "schwab_roth_ira", "schwab_rollover_ira"]
    for acct in accts:
        print(json.dumps({acct: sync_schwab_positions(acct, dry_run=not a.apply)}, indent=2, default=str))
