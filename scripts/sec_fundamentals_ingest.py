#!/usr/bin/env python3
"""Ingest reported fundamentals from SEC company facts into sec_xbrl (fundamentals plan F1, 2026-09-27).

The only writer of sec_xbrl and (under --apply) of sec_filing_documents, the 8-K exhibit
99.1 text + dollar-figure facts read by the thesis catalog and the options CIO packet
(2026-09-27). Official source only (data.sec.gov / sec.gov Archives, declared User-Agent,
rate-limited by financial_senses.sec_companyfacts_reader). Universe, in order: open
symbol-thesis priority requests, options-desk symbols, the acquisition worker's
debt-ordered queue (held names first); ETFs/funds are skipped. Idempotent: a row is
keyed by (symbol, metric, form, period); a restated value updates it; nothing is
deleted. Dry run by default.

    python3 scripts/sec_fundamentals_ingest.py --symbols DELL          # dry run
    python3 scripts/sec_fundamentals_ingest.py --apply                 # priority universe
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    f = ROOT / ".env"
    if f.is_file():
        for raw in f.read_text(errors="ignore").splitlines():
            s = raw.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def universe(limit: int) -> list[str]:
    out: list[str] = []
    try:
        from lib.symbol_thesis_priority import open_requests
        out += open_requests(ROOT)
    except Exception:  # noqa: BLE001
        pass
    try:
        props = json.loads((ROOT / "data/portfolios/state/options_proposals.json").read_text()).get("proposals") or []
        out += [str(p.get("symbol") or "").upper() for p in props]
    except Exception:  # noqa: BLE001
        pass
    try:
        from run_symbol_thesis_acquisition import build_debt_ordered_queue
        out += [str(r.get("symbol") or "").upper() for r in build_debt_ordered_queue(root=ROOT, limit=limit)]
    except Exception:  # noqa: BLE001
        pass
    seen, uniq = set(), []
    for s in out:
        if s and s.isalpha() and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq[:limit]


EXISTING_SQL = """SELECT id, metric_name, form_type, period_start, period_end, metric_value
                  FROM sec_xbrl WHERE symbol=%s"""
INSERT_SQL = """INSERT INTO sec_xbrl (symbol, form_type, metric_name, metric_value, unit, period_start,
                                      period_end, filing_date, sec_url, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())"""
UPDATE_SQL = """UPDATE sec_xbrl SET metric_value=%s, filing_date=%s, sec_url=%s WHERE id=%s"""


def upsert(cur, rows: list[dict]) -> dict:
    if not rows:
        return {"inserted": 0, "updated": 0, "unchanged": 0}
    cur.execute(EXISTING_SQL, (rows[0]["symbol"],))
    have = {}
    for r in cur.fetchall() or []:
        r = dict(r) if isinstance(r, dict) else dict(zip(("id", "metric_name", "form_type", "period_start",
                                                            "period_end", "metric_value"), r))
        have[(r["metric_name"], r["form_type"], str(r["period_start"] or ""), str(r["period_end"]))] = r
    ins = upd = same = 0
    for r in rows:
        key = (r["metric_name"], r["form_type"], str(r["period_start"] or ""), str(r["period_end"]))
        old = have.get(key)
        if old is None:
            cur.execute(INSERT_SQL, (r["symbol"], r["form_type"], r["metric_name"], r["metric_value"], r["unit"],
                                     r["period_start"], r["period_end"], r["filing_date"], r["sec_url"]))
            ins += 1
        elif abs(float(old["metric_value"] or 0) - float(r["metric_value"])) > 1e-9:
            cur.execute(UPDATE_SQL, (r["metric_value"], r["filing_date"], r["sec_url"], old["id"]))
            upd += 1
        else:
            same += 1
    return {"inserted": ins, "updated": upd, "unchanged": same}


def is_fund(cur, symbol: str) -> bool:
    cur.execute("SELECT instrument_type, quote_type FROM symbol_profiles WHERE symbol=%s LIMIT 1", (symbol,))
    r = cur.fetchone()
    if not r:
        return False
    r = dict(r) if isinstance(r, dict) else {"instrument_type": r[0], "quote_type": r[1]}
    return str(r.get("instrument_type") or "").lower() in ("etf", "fund", "mutual_fund") or \
        str(r.get("quote_type") or "").upper() in ("ETF", "MUTUALFUND")


def ingest_documents(conn, sym: str, cik: str, filings: list, *, fetch_json=None, fetch_text=None,
                     since_days: int = 45, max_docs: int = 3) -> dict:
    """Fetch + store EX-99.1 for in-window 8-K 2.02/7.01 filings. Own transaction; never raises."""
    from lib import sec_filing_documents as sfd
    try:
        with conn.cursor() as cur:
            docs = sfd.fetch_documents_for_filings(sym, cik, filings, skip=lambda acc, ex: sfd.stored(cur, acc, ex),
                                                   fetch_json=fetch_json, fetch_text=fetch_text,
                                                   since_days=since_days, max_docs=max_docs)
            for d in docs:
                sfd.upsert(cur, d)
        conn.commit()
        return {"filing_documents_new": len(docs), "filing_facts_new": sum(len(d["facts"]) for d in docs)}
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        return {"filing_documents_error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SEC company facts -> sec_xbrl")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--since-days", type=int, default=45,
                    help="8-K window for catalyst events and EX-99.1 documents (default 45; a one-off "
                         "wider window backfills an earlier quarter's release, e.g. DELL Q1 FY27 on 2026-05-28)")
    a = ap.parse_args(argv)
    _load_env()
    import psycopg2
    import psycopg2.extras
    from lib import fundamentals_feed as ff
    from lib.financial_senses import sec_companyfacts_reader as sec
    s = ff.settings()
    syms = [x.strip().upper() for x in a.symbols.split(",") if x.strip()] or universe(int(s["max_symbols_per_run"]))
    conn = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))
    report = []
    try:
        for sym in syms:
            step = {"symbol": sym}
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if is_fund(cur, sym):
                        step["status"] = "NOT_APPLICABLE_FUND"
                        report.append(step)
                        continue
                cik = sec.resolve_cik(sym)
                if not cik:
                    step["status"] = "NO_CIK"
                    report.append(step)
                    continue
                rows = ff.extract_rows(sym, cik, sec.get_company_facts(cik), s)
                summ = ff.summarize(sym, rows)
                step.update(status="OK" if rows else "NO_FACTS", rows=len(rows),
                            latest_quarter_end=summ["latest_quarter_end"], freshness=ff.freshness(summ, s))
                if a.apply and rows:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        step.update(upsert(cur, rows))
                    conn.commit()
                # F3: recent 8-K items and 10-Q/10-K filings become dated catalyst events;
                # a new high-severity 8-K files a thesis re-synthesis request.
                from lib import sec_filing_events as sfe
                filings = sfe.filings_from_submissions(cik, sec.get_submissions(cik))
                events = sfe.events_from_filings(sym, filings, since_days=int(a.since_days))
                step["filing_events"] = len(events)
                if a.apply and events:
                    with conn.cursor() as cur:
                        new = sfe.insert(cur, events)
                    conn.commit()
                    step["filing_events_new"] = len(new)
                    material = [e for e in new if sfe.is_material(e)]
                    if material:
                        from lib.symbol_thesis_priority import request
                        request(sym, reason=f"new SEC filing: {material[0]['headline']}", source="sec_fundamentals_ingest",
                                root=ROOT)
                        step["thesis_refresh_requested"] = True
                # 8-K exhibit 99.1 (earnings release / Reg FD) text and its dollar-figure
                # sentences become primary evidence (2026-09-27: Dell's $95B backlog and
                # $60.9B orders were in the filing the house held only as a headline).
                # Idempotent on (accession, exhibit); a missing table is reported, not fatal.
                if a.apply:
                    step.update(ingest_documents(conn, sym, cik, filings, since_days=int(a.since_days),
                                                 max_docs=(3 if int(a.since_days) <= 45 else 6)))
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                step.update(status="ERROR", error=f"{type(exc).__name__}: {str(exc)[:160]}")
            report.append(step)
    finally:
        conn.close()
    counts: dict = {}
    for r in report:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(json.dumps({"mode": "apply" if a.apply else "dry_run", "symbols": len(syms), "statuses": counts,
                      "results": report}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
