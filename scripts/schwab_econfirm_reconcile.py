#!/usr/bin/env python3
"""schwab_econfirm_reconcile.py — v1.2.1 P1-2: Gmail Schwab eConfirm adapter.

READ-ONLY, SECONDARY evidence (the execution source of truth remains the broker
API/ledger). Uses the gog CLI (same authorized account as the Drive sync) to
pull Schwab eConfirm emails, parses per-trade sections, stores them in
econfirm_evidence, and reconciles amounts/fees against trade_transactions.

Rules:
  - The generic "Charge and/or Interest" field is stored EXACTLY as labeled and
    normalized only to broker_charge_unclassified (P1-1) — never inferred into
    a specific fee subtype.
  - Unparseable emails land in the operator queue (parse_status='unparsed'),
    never silently dropped.
  - No email may create, approve, or execute anything.
Usage: schwab_econfirm_reconcile.py [--days 14] [--dry-run]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

ACCOUNT = "john@jwwhiting.com"


def _gog(*args) -> str:
    env = dict(os.environ)
    kp = Path.home() / ".openclaw" / "credentials" / "gog_keyring_password"
    if kp.exists():
        env["GOG_KEYRING_PASSWORD"] = kp.read_text().strip()
    r = subprocess.run(["gog", *args, "--account", ACCOUNT],
                       capture_output=True, text=True, timeout=90, env=env)
    return r.stdout


def ensure_econfirm_tables(cur, conn):
    cur.execute("""CREATE TABLE IF NOT EXISTS econfirm_evidence (
        econfirm_id serial PRIMARY KEY,
        email_message_id text NOT NULL,
        received_at text,
        account_suffix text,
        trade_date date,
        settle_date date,
        symbol text,
        cusip text,
        action text,
        quantity numeric,
        price numeric,
        principal numeric,
        charge_or_interest numeric,      -- stored under the source's OWN label
        total_amount numeric,
        parse_status text NOT NULL,      -- parsed | unparsed
        raw_excerpt text,
        dedupe_key text UNIQUE NOT NULL,
        recon_status text DEFAULT 'pending',   -- pending | matched | mismatch | no_ledger_row
        recon_detail text,
        created_at timestamptz DEFAULT now())""")
    conn.commit()


def _f(x):
    try:
        return float(str(x).replace(",", "").replace("$", ""))
    except Exception:
        return None


def parse_trade_sections(body: str) -> list[dict]:
    """Schwab eConfirm layout (observed 2026-07): label blocks then a value
    block — Quantity/Price/Principal/'Charge and/or Interest'/Total Amount
    headers followed by the numeric run (charge may render as 'N/A: $0.00 N/A').
    Section-wise, fail-honest: a section that doesn't parse is skipped and the
    email lands in the unparsed queue if NOTHING parses."""
    out = []
    for sec in re.split(r"\bSymbol:\s*", body)[1:]:
        sym_m = re.match(r"\s*([A-Z][A-Z0-9.]{0,9})\b", sec)
        if not sym_m:
            continue
        d = {"symbol": sym_m.group(1)}
        for label, key in (("Action", "action"), (r"Security No\./CUSIP", "cusip"),
                           ("Trade Date", "trade_date"), ("Settle Date", "settle_date")):
            m = re.search(label + r":\s*\n?\s*\n?\s*([A-Za-z0-9/ ]+)", sec)
            if m:
                d[key] = m.group(1).strip()
        # numeric run after the "Total Amount" header
        after = sec.split("Total Amount", 1)
        if len(after) < 2:
            continue
        tokens = re.findall(r"\$?[\d][\d,]*\.?\d*", after[1][:600])
        nums = [_f(t) for t in tokens if _f(t) is not None]
        if len(nums) < 4:
            continue
        d["quantity"], d["price"], d["principal"] = nums[0], nums[1], nums[2]
        # charge sits between principal and the final total; 'N/A' renders a 0.00
        d["charge_or_interest"] = nums[3] if len(nums) >= 5 else 0.0
        d["total_amount"] = nums[-1]
        out.append(d)
    return out


def _date_iso(us: str | None) -> str | None:
    if not us:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{2})$", us.strip())
    return f"20{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None


def ingest(cur, conn, days: int = 14, dry: bool = False) -> dict:
    out = {"emails": 0, "parsed_trades": 0, "unparsed": 0}
    listing = _gog("gmail", "search", f"from:schwab.com subject:eConfirms newer_than:{days}d",
                   "--max", "25")
    ids = re.findall(r"^([0-9a-f]{16})\s", listing, re.M)
    out["emails"] = len(ids)
    for mid in ids:
        body = _gog("gmail", "get", mid)
        suffix = (re.search(r"account ending in (\d+)", body) or [None, None])[1]
        recvd = (re.search(r"^date\t(.+)$", body, re.M) or [None, None])[1]
        tdate = (re.search(r"confirmation\(s\) for (\d{8})", body) or [None, None])[1]
        tdate_iso = f"{tdate[:4]}-{tdate[4:6]}-{tdate[6:]}" if tdate else None
        matches = parse_trade_sections(body)
        if not matches:
            if not dry:
                cur.execute("""INSERT INTO econfirm_evidence
                    (email_message_id, received_at, account_suffix, trade_date, parse_status,
                     raw_excerpt, dedupe_key)
                    VALUES (%s,%s,%s,%s,'unparsed',%s,%s) ON CONFLICT (dedupe_key) DO NOTHING""",
                    (mid, recvd, suffix, tdate_iso, body[-1500:], f"econf:{mid}:unparsed"))
            out["unparsed"] += 1
            continue
        for i, m in enumerate(matches):
            if not dry:
                cur.execute("""INSERT INTO econfirm_evidence
                    (email_message_id, received_at, account_suffix, trade_date, settle_date,
                     symbol, cusip, action, quantity, price, principal, charge_or_interest,
                     total_amount, parse_status, dedupe_key)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'parsed',%s)
                    ON CONFLICT (dedupe_key) DO NOTHING""",
                    (mid, recvd, suffix,
                     _date_iso(m.get("trade_date")) or tdate_iso, _date_iso(m.get("settle_date")),
                     m["symbol"], m.get("cusip"), (m.get("action") or "").strip(),
                     m.get("quantity"), m.get("price"), m.get("principal"),
                     m.get("charge_or_interest"), m.get("total_amount"), f"econf:{mid}:{i}"))
            out["parsed_trades"] += 1
    if not dry:
        conn.commit()
    return out


def reconcile(cur, conn) -> dict:
    """Match parsed eConfirm trades to the ledger by (date, symbol, qty≈, action).
    Charges reconcile against ledger fees; the generic charge stays generic."""
    cur.execute("""SELECT econfirm_id, trade_date, symbol, action, quantity, price,
                          charge_or_interest FROM econfirm_evidence
                   WHERE parse_status='parsed' AND recon_status='pending'""")
    res = {"matched": 0, "mismatch": 0, "no_ledger_row": 0}
    act_map = {"Sale": "Sell", "Purchase": "Buy"}
    for eid, td, sym, act, qty, px, chg in cur.fetchall():
        ledger_act = act_map.get((act or "").strip(), (act or "").strip())
        cur.execute("""SELECT price, fees FROM trade_transactions
                       WHERE trade_date=%s AND upper(symbol)=%s
                         AND action ILIKE %s AND abs(quantity-%s) < 0.01 LIMIT 1""",
                    (td, (sym or "").upper(), ledger_act + "%", qty))
        row = cur.fetchone()
        if not row:
            status, detail = "no_ledger_row", "no matching ledger transaction (ingest lag or gap)"
            res["no_ledger_row"] += 1
        else:
            lpx, lfees = float(row[0] or 0), float(row[1] or 0)
            px, chg = (float(px) if px is not None else None), (float(chg) if chg is not None else None)
            px_ok = px is None or abs(lpx - px) < 0.01
            fee_ok = chg is None or abs(lfees - chg) < 0.02
            if px_ok and fee_ok:
                status, detail = "matched", "price+charge agree with ledger"
                res["matched"] += 1
            else:
                status = "mismatch"
                detail = f"ledger px {lpx}/fees {lfees} vs eConfirm px {px}/charge {chg}"
                res["mismatch"] += 1
        cur.execute("UPDATE econfirm_evidence SET recon_status=%s, recon_detail=%s WHERE econfirm_id=%s",
                    (status, detail, eid))
    conn.commit()
    return res


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    ensure_econfirm_tables(cur, conn)
    print(json.dumps(ingest(cur, conn, days=a.days, dry=a.dry_run), indent=1))
    if not a.dry_run:
        print(json.dumps(reconcile(cur, conn), indent=1))
