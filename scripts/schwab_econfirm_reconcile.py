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


PARSER_VERSION = "econfirm-v2"   # per-fill parser (v1 emitted one row per section — superseded)


class GmailAccessError(RuntimeError):
    pass


def _gog(*args) -> str:
    """P0-2: nonzero exit / timeout / auth stderr / empty response = FAILURE,
    surfaced — never silently treated as 'zero emails'."""
    env = dict(os.environ)
    kp = Path.home() / ".openclaw" / "credentials" / "gog_keyring_password"
    if kp.exists():
        env["GOG_KEYRING_PASSWORD"] = kp.read_text().strip()
    try:
        r = subprocess.run(["gog", *args, "--account", ACCOUNT],
                           capture_output=True, text=True, timeout=120, env=env)
    except subprocess.TimeoutExpired as e:
        raise GmailAccessError(f"gog timeout: {e}")
    if r.returncode != 0:
        raise GmailAccessError(f"gog exit {r.returncode}: {r.stderr[:200]}")
    if re.search(r"auth|credential|token|denied", r.stderr or "", re.I):
        raise GmailAccessError(f"gog auth problem: {r.stderr[:200]}")
    if not r.stdout.strip():
        raise GmailAccessError("gog returned empty response")
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
    for ddl in (
        "ALTER TABLE econfirm_evidence ADD COLUMN IF NOT EXISTS parser_version text",
        "ALTER TABLE econfirm_evidence ADD COLUMN IF NOT EXISTS section_ordinal int",
        "ALTER TABLE econfirm_evidence ADD COLUMN IF NOT EXISTS fill_ordinal int",
        "ALTER TABLE econfirm_evidence ADD COLUMN IF NOT EXISTS content_hash text",
        "ALTER TABLE econfirm_evidence ADD COLUMN IF NOT EXISTS matched_txn_dedupe_key text",
    ):
        cur.execute(ddl)
    conn.commit()


def _f(x):
    try:
        return float(str(x).replace(",", "").replace("$", ""))
    except Exception:
        return None


def _bare_num(t: str) -> bool:
    return bool(re.match(r"^[\d,]+\.\d+$", t))


def parse_fills(body: str) -> list[dict]:
    """P0-2: ONE ROW PER FILL. Each Symbol section carries repeated value
    groups (qty, $price, $principal, charge-tokens, $total) followed by a
    'Totals' group (qty, principal, charge, total — NO price) which is a
    SECTION TOTAL, not a fill. Zero/absent charges ('N/A: $0.00 N/A' or no
    charge field) handled; mutual-fund fractional quantities allowed."""
    fills = []
    for s_ord, sec in enumerate(re.split(r"\bSymbol:\s*", body)[1:]):
        sym_m = re.match(r"\s*([A-Z][A-Z0-9.]{0,9})\b", sec)
        if not sym_m:
            continue
        meta = {"symbol": sym_m.group(1), "section_ordinal": s_ord}
        for label, key in (("Action", "action"), (r"Security No\./CUSIP", "cusip"),
                           ("Trade Date", "trade_date"), ("Settle Date", "settle_date")):
            m = re.search(label + r":\s*\n?\s*\n?\s*([A-Za-z0-9/ ]+)", sec)
            if m:
                meta[key] = m.group(1).strip()
        after = sec.split("Total Amount", 1)
        if len(after) < 2:
            continue
        toks = [t.strip() for t in after[1].splitlines() if t.strip() and t.strip() != "."]
        toks = toks[:400]
        i, f_ord = 0, 0
        while i < len(toks):
            t = toks[i]
            if t == "Totals":
                break  # section totals — never a fill
            if _bare_num(t) and i + 2 < len(toks) and toks[i + 1].startswith("$")                     and toks[i + 2].startswith("$"):
                qty, price, principal = _f(t), _f(toks[i + 1]), _f(toks[i + 2])
                j = i + 3
                seg = []
                while j < len(toks) and not _bare_num(toks[j]) and toks[j] != "Totals":
                    seg.append(toks[j])
                    j += 1
                dollars = [_f(x) for x in seg if x.startswith("$")]
                total = dollars[-1] if dollars else None
                charge = dollars[0] if len(dollars) >= 2 else (None if not dollars else 0.0)
                fills.append({**meta, "fill_ordinal": f_ord, "quantity": qty, "price": price,
                              "principal": principal, "charge_or_interest": charge,
                              "total_amount": total,
                              "raw_excerpt": " | ".join([t] + toks[i + 1:j][:8])})
                f_ord += 1
                i = j
            else:
                i += 1
    return fills


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
        matches = parse_fills(body)
        if not matches:
            if not dry:
                cur.execute("""INSERT INTO econfirm_evidence
                    (email_message_id, received_at, account_suffix, trade_date, parse_status,
                     raw_excerpt, dedupe_key)
                    VALUES (%s,%s,%s,%s,'unparsed',%s,%s) ON CONFLICT (dedupe_key) DO NOTHING""",
                    (mid, recvd, suffix, tdate_iso, body[-1500:], f"econf:{mid}:unparsed"))
            out["unparsed"] += 1
            continue
        import hashlib as _h
        chash = _h.sha256(re.sub(r"https?://\S+", "", body).encode()).hexdigest()[:16]
        if not dry:
            # a parser upgrade SUPERSEDES old rows for this email — no manual deletion
            cur.execute("""UPDATE econfirm_evidence SET parse_status='superseded_by_' || %s
                           WHERE email_message_id=%s AND COALESCE(parser_version,'v1') != %s
                             AND parse_status IN ('parsed','unparsed')""",
                        (PARSER_VERSION, mid, PARSER_VERSION))
        for m in matches:
            if not dry:
                cur.execute("""INSERT INTO econfirm_evidence
                    (email_message_id, received_at, account_suffix, trade_date, settle_date,
                     symbol, cusip, action, quantity, price, principal, charge_or_interest,
                     total_amount, parse_status, raw_excerpt, dedupe_key, parser_version,
                     section_ordinal, fill_ordinal, content_hash)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'parsed',%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (dedupe_key) DO NOTHING""",
                    (mid, recvd, suffix,
                     _date_iso(m.get("trade_date")) or tdate_iso, _date_iso(m.get("settle_date")),
                     m["symbol"], m.get("cusip"), (m.get("action") or "").strip(),
                     m.get("quantity"), m.get("price"), m.get("principal"),
                     m.get("charge_or_interest"), m.get("total_amount"),
                     m.get("raw_excerpt", "")[:400],
                     f"econf:{mid}:{PARSER_VERSION}:{m['section_ordinal']}:{m['fill_ordinal']}",
                     PARSER_VERSION, m["section_ordinal"], m["fill_ordinal"], chash))
            out["parsed_trades"] += 1
    if not dry:
        conn.commit()
    return out


SUFFIX_TO_ACCOUNT = {"258": "schwab_rollover_ira", "415": "schwab_roth", "469": "schwab_taxable"}


def reconcile_one_to_one(cur, conn) -> dict:
    """P0-3: deterministic one-to-one matching — each ledger transaction may
    satisfy at most ONE eConfirm fill. States are explicit; nothing arbitrary."""
    act_map = {"Sale": "Sell", "Purchase": "Buy"}
    cur.execute("""SELECT econfirm_id, account_suffix, trade_date, settle_date, symbol, cusip,
                          action, quantity, price, charge_or_interest
                   FROM econfirm_evidence
                   WHERE parse_status='parsed' AND parser_version=%s
                   ORDER BY trade_date, symbol, fill_ordinal""", (PARSER_VERSION,))
    fills = cur.fetchall()
    used_ledger = set()
    res = {"EXACT_MATCH": 0, "MATCH_WITH_DATE_FALLBACK": 0, "PRICE_MISMATCH": 0,
           "CHARGE_MISMATCH": 0, "AMBIGUOUS_MULTIPLE_CANDIDATES": 0, "ECONFIRM_ONLY": 0}
    for (eid, sfx, td, sd, sym, cusip, act, qty, px, chg) in fills:
        acct = SUFFIX_TO_ACCOUNT.get((sfx or "").strip())
        ledger_act = act_map.get((act or "").strip(), (act or "").strip())
        px, chg, qty = (float(px) if px is not None else None,
                        float(chg) if chg is not None else None, float(qty or 0))

        def _cands(date_col_val):
            cur.execute(f"""SELECT dedupe_key, price, fees FROM trade_transactions
                            WHERE trade_date=%s AND upper(symbol)=%s AND action ILIKE %s
                              AND abs(quantity-%s) < 0.01
                              AND (%s IS NULL OR account=%s)""",
                        (date_col_val, (sym or "").upper(), ledger_act + "%", qty, acct, acct))
            return [c for c in cur.fetchall() if c[0] not in used_ledger]

        cands, state_base = _cands(td), "EXACT_MATCH"
        if not cands and sd:
            cands, state_base = _cands(sd), "MATCH_WITH_DATE_FALLBACK"  # bounded: settle date only
        if not cands:
            status, detail = "ECONFIRM_ONLY", "no unconsumed ledger candidate (date+settle searched)"
            res["ECONFIRM_ONLY"] += 1
        else:
            exact = [c for c in cands if px is None or abs(float(c[1] or 0) - px) < 0.005]
            if len(exact) > 1:
                status, detail = "AMBIGUOUS_MULTIPLE_CANDIDATES", f"{len(exact)} equal candidates"
                res["AMBIGUOUS_MULTIPLE_CANDIDATES"] += 1
            elif len(exact) == 1:
                dk, lpx, lfees = exact[0]
                used_ledger.add(dk)
                if chg is not None and abs(float(lfees or 0) - chg) > 0.02:
                    status, detail = "CHARGE_MISMATCH", f"ledger fees {lfees} vs charge {chg}"
                    res["CHARGE_MISMATCH"] += 1
                else:
                    status, detail = state_base, f"1:1 vs ledger {dk[:40]}"
                    res[state_base] += 1
                cur.execute("UPDATE econfirm_evidence SET matched_txn_dedupe_key=%s WHERE econfirm_id=%s",
                            (dk, eid))
            else:
                dk, lpx, lfees = cands[0]
                used_ledger.add(dk)
                status, detail = "PRICE_MISMATCH", f"ledger px {lpx} vs eConfirm {px}"
                res["PRICE_MISMATCH"] += 1
                cur.execute("UPDATE econfirm_evidence SET matched_txn_dedupe_key=%s WHERE econfirm_id=%s",
                            (dk, eid))
        cur.execute("UPDATE econfirm_evidence SET recon_status=%s, recon_detail=%s WHERE econfirm_id=%s",
                    (status, detail, eid))
    conn.commit()
    return res


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
        print(json.dumps(reconcile_one_to_one(cur, conn), indent=1))
