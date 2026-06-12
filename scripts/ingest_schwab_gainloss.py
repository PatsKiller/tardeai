#!/usr/bin/env python3
"""ingest_schwab_gainloss.py — ingest AUTHORITATIVE Schwab cost basis (Realized/Unrealized Gain-Loss export).

The Schwab Trader API exposes only average price (no tax lots), so per-lot cost basis must come from the
operator's CSV export: schwab.com → Accounts → History → Cost Basis → Realized Gain/Loss (and Unrealized) →
Export. Drop the CSV(s) into imports/schwab_gainloss/. This is the authoritative source ABOVE both the API
average price and the hand-entered journal_basis_overrides.yaml.

  python3 scripts/ingest_schwab_gainloss.py --apply        # ingest exports -> schwab_cost_basis_lots
  python3 scripts/ingest_schwab_gainloss.py --reconcile     # compare schwab_round_trips vs authoritative basis

Read-only of the broker. No trading writes. Basis hierarchy: this export > operator-documented > basis_unknown.
"""
import argparse, csv, json, re, sys, hashlib
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
INBOUND = PROJECT_ROOT / "imports" / "schwab_gainloss"

# Flexible header detection — Schwab's export headers vary slightly across realized/unrealized + over time.
H = {
    "symbol": ["symbol"],
    "quantity": ["quantity", "qty", "shares"],
    "opened": ["opened date", "date acquired", "acquired", "open date", "date opened"],
    "closed": ["closed date", "date sold", "sold", "close date", "date closed"],
    "cost_per_share": ["cost per share", "cost/share", "cost basis per share", "unit cost"],
    "cost_basis": ["cost basis", "total cost", "cost"],
    "proceeds": ["proceeds", "total proceeds"],
    "gain": ["gain/loss ($)", "gain/loss", "realized gain/loss", "gain $", "gain"],
    "term": ["term", "long term gain/loss", "holding period"],
    "wash": ["wash sale", "wash sale?", "disallowed loss"],
}


def _num(v):
    if v is None:
        return None
    s = re.sub(r"[,$()%\s]", "", str(v)).replace("—", "")
    if s in ("", "-", "N/A", "NA"):
        return None
    neg = str(v).strip().startswith("(") or str(v).strip().startswith("-")
    try:
        n = float(s)
        return -abs(n) if (neg and n > 0) else n
    except Exception:
        return None


def _date(v):
    if not v:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%b %d, %Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date().isoformat()
        except Exception:
            continue
    return None


def _colmap(header):
    low = [(h or "").strip().lower() for h in header]
    out = {}
    for key, names in H.items():
        for i, h in enumerate(low):
            if any(h == n or h.startswith(n) for n in names):
                out[key] = i
                break
    return out


def _account_from_name(fn):
    f = fn.lower()
    if "roth" in f:
        return "schwab_roth_ira"
    if "rollover" in f or "rol3" in f:
        return "schwab_rollover_ira"
    if "taxable" in f or "individual" in f or "brokerage" in f:
        return "schwab_taxable"
    return None


def _parse(p):
    try:
        rows = list(csv.reader(p.read_text(errors="ignore").splitlines()))
    except Exception:
        return []
    # find the header row (the one containing 'Symbol')
    hdr_i = next((i for i, r in enumerate(rows[:15]) if any((c or "").strip().lower() == "symbol" for c in r)), None)
    if hdr_i is None:
        return []
    cm = _colmap(rows[hdr_i])
    if "symbol" not in cm:
        return []
    acct = _account_from_name(p.name)
    out = []
    for r in rows[hdr_i + 1:]:
        if len(r) <= cm["symbol"]:
            continue
        sym = (r[cm["symbol"]] or "").strip().upper()
        if not re.match(r"^[A-Z][A-Z0-9.]{0,5}$", sym):
            continue
        g = lambda k: r[cm[k]] if (k in cm and len(r) > cm[k]) else None
        closed = _date(g("closed"))
        rec = {"account": acct, "symbol": sym, "kind": "realized" if closed else "unrealized",
               "quantity": _num(g("quantity")), "opened_date": _date(g("opened")), "closed_date": closed,
               "cost_per_share": _num(g("cost_per_share")), "cost_basis": _num(g("cost_basis")),
               "proceeds": _num(g("proceeds")), "realized_gain": _num(g("gain")),
               "term": ("long" if "long" in (g("term") or "").lower() else "short" if "short" in (g("term") or "").lower() else None),
               "wash": bool((g("wash") or "").strip() and (g("wash") or "").strip().lower() not in ("no", "0", "")),
               "source_file": p.name}
        rec["dedupe_key"] = hashlib.md5(f"{sym}|{acct}|{closed}|{rec['opened_date']}|{rec['quantity']}|{rec['cost_basis']}".encode()).hexdigest()
        out.append(rec)
    return out


def ingest(apply=False):
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    files = sorted(list(INBOUND.glob("*.csv")))
    report = {"mode": "APPLIED" if apply else "DRY-RUN", "files": [], "lots": 0}
    for p in files:
        lots = _parse(p)
        report["files"].append({"file": p.name, "lots": len(lots), "account": lots[0]["account"] if lots else None})
        report["lots"] += len(lots)
        if apply:
            for L in lots:
                cur.execute("""INSERT INTO schwab_cost_basis_lots
                    (account,symbol,kind,quantity,opened_date,closed_date,cost_per_share,cost_basis,proceeds,
                     realized_gain,term,wash_sale,source_file,dedupe_key)
                    VALUES (%(account)s,%(symbol)s,%(kind)s,%(quantity)s,%(opened_date)s,%(closed_date)s,
                     %(cost_per_share)s,%(cost_basis)s,%(proceeds)s,%(realized_gain)s,%(term)s,%(wash)s,
                     %(source_file)s,%(dedupe_key)s)
                    ON CONFLICT (dedupe_key) DO UPDATE SET cost_basis=EXCLUDED.cost_basis,
                     realized_gain=EXCLUDED.realized_gain, imported_at=NOW()""", L)
            conn.commit()
    print(json.dumps(report, indent=2))
    return report


def reconcile():
    """Compare schwab_round_trips (current basis) against authoritative realized lots; flag divergences."""
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("SELECT count(*) FROM schwab_cost_basis_lots WHERE kind='realized'")
    if cur.fetchone()[0] == 0:
        print(json.dumps({"status": "NO_AUTHORITATIVE_DATA",
                          "reason": "No Schwab realized gain-loss export ingested yet. Drop the CSV into "
                                    "imports/schwab_gainloss/ and run --apply first."}, indent=2))
        return
    # authoritative realized gain per symbol+account
    cur.execute("""SELECT symbol, account, SUM(realized_gain) auth_gain, SUM(cost_basis) auth_basis, SUM(quantity) qty
                   FROM schwab_cost_basis_lots WHERE kind='realized' GROUP BY symbol, account""")
    auth = {(r[0], r[1]): {"gain": r[2], "basis": r[3], "qty": r[4]} for r in cur.fetchall()}
    cur.execute("""SELECT symbol, account, SUM(net_pnl) jrnl_pnl, SUM(qty) qty FROM schwab_round_trips
                   WHERE basis_status IS DISTINCT FROM 'basis_unknown' AND canary IS NOT TRUE
                   GROUP BY symbol, account""")
    out = []
    for sym, acct, jrnl, qty in cur.fetchall():
        a = auth.get((sym, acct))
        if not a:
            out.append({"symbol": sym, "account": acct, "status": "NO_AUTH_RECORD", "journal_pnl": float(jrnl or 0)})
            continue
        diff = float(jrnl or 0) - float(a["gain"] or 0)
        out.append({"symbol": sym, "account": acct, "journal_pnl": round(float(jrnl or 0), 2),
                    "schwab_authoritative_gain": round(float(a["gain"] or 0), 2), "divergence": round(diff, 2),
                    "status": "MATCH" if abs(diff) < 1.0 else "DIVERGENCE — Schwab wins"})
    print(json.dumps({"reconciliation": out}, indent=2, default=str))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--reconcile", action="store_true")
    a = ap.parse_args()
    if a.reconcile:
        reconcile()
    else:
        ingest(apply=a.apply)


if __name__ == "__main__":
    main()
