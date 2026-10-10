#!/usr/bin/env python3
"""sec_data_ingest.py — SEC data ingestion (Form 4, 13F, XBRL).

Uses free SEC EDGAR APIs (data.sec.gov). No API key needed.
Rate limit: 10 requests/second with User-Agent header.

Usage:
    python3 scripts/sec_data_ingest.py --test
    python3 scripts/sec_data_ingest.py --form4 [--symbol SYMBOL]
    python3 scripts/sec_data_ingest.py --all
    python3 scripts/sec_data_ingest.py --all --dry-run

Lane ``sec-data-ingest`` (cron L150, ``--all``). ``--dry-run`` wins over every mode: it never enters
PipelineRun (no pipeline_runs row) and makes no SEC request (data.sec.gov is free but rate-limited, so
the dry run reports the work list instead); it opens a READ ONLY session, reads the tracked-symbol
universe with the same query as a real run, and prints the symbols a real run would scan and the
sec_form4 rows already stored for them. No receipt.

A real ``--all`` run writes ``<state_root>/data/runtime/sec-data-ingest_last.json`` (LaneRunReceipt@v1;
``ok_at`` only on success; ``--form4`` / ``--test`` are manual modes and write no lane receipt).
Exit codes: 0 = ran (symbols with no recent Form 4, or zero new filings, are findings); 1 = the run
failed: crash / DB unavailable (failed receipt, exception re-raised), every scanned symbol's SEC fetch
errored, or every attempted sec_form4 insert errored; 2 = usage error (no mode given).
"""
import json, os, sys, time
from datetime import datetime, date
from pathlib import Path

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SEC_BASE = "https://efts.sec.gov/LATEST/search-index?q="
SEC_EDGAR = "https://data.sec.gov"
SEC_HEADERS = {"User-Agent": "TradeAI john@jwwhiting.com", "Accept": "application/json"}
LANE_ID = "sec-data-ingest"
SYMBOL_CAP = 15  # rate limit protection
#: SEC request errors seen in this process (each failed request appends; ingest_form4 diffs the length)
_FETCH_ERRORS: list = []


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.sec_data_ingest
        from scripts.lib import lane_last_receipt as lr
    return lr


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _sec_get(url: str) -> dict:
    """Make a rate-limited request to SEC EDGAR."""
    import urllib.request
    time.sleep(0.15)  # SEC rate limit: 10/sec
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [sec] Error: {e}")
        _FETCH_ERRORS.append(f"{url}: {type(e).__name__}")
        return {}


def _get_cik(symbol: str) -> str:
    """Look up CIK number for a ticker symbol."""
    url = f"{SEC_EDGAR}/submissions/CIK{symbol.upper()}.json"
    # Try the ticker mapping first
    try:
        import urllib.request
        map_url = "https://www.sec.gov/files/company_tickers.json"
        req = urllib.request.Request(map_url, headers=SEC_HEADERS)
        time.sleep(0.15)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            for entry in data.values():
                if entry.get("ticker", "").upper() == symbol.upper():
                    return str(entry["cik_str"]).zfill(10)
    except Exception as e:
        _FETCH_ERRORS.append(f"company_tickers.json: {type(e).__name__}")
    return ""


def fetch_form4(symbol: str, limit: int = 10) -> list:
    """Fetch recent Form 4 (insider transactions) for a symbol."""
    cik = _get_cik(symbol)
    if not cik:
        return []

    url = f"{SEC_EDGAR}/submissions/CIK{cik}.json"
    data = _sec_get(url)
    if not data:
        return []

    company = data.get("name", symbol)
    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accessions = filings.get("accessionNumber", [])
    primary_docs = filings.get("primaryDocument", [])

    results = []
    for i, form in enumerate(forms):
        if form == "4" and i < limit * 3:  # Form 4 = insider trading
            filing_date = dates[i] if i < len(dates) else ""
            accession = accessions[i].replace("-", "") if i < len(accessions) else ""
            doc = primary_docs[i] if i < len(primary_docs) else ""
            sec_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession}/{doc}" if accession else ""

            results.append({
                "symbol": symbol.upper(),
                "filer_name": company,
                "filer_relation": "insider",
                "transaction_type": "Form 4",
                "filing_date": filing_date,
                "sec_url": sec_url,
            })
            if len(results) >= limit:
                break

    return results


def _tracked_symbols(conn) -> list:
    """Active strategy-classified symbols that can have SEC filings (read-only SELECT)."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT DISTINCT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
    symbols = [r["symbol"] for r in cur.fetchall()]
    # Filter out mutual funds / non-SEC symbols
    return [s for s in symbols if "-" not in s and len(s) <= 5]


def preview_form4(symbols: list = None) -> dict:
    """Dry run (AGENTS.md §6): READ ONLY session, SELECTs only; no SEC request, no INSERT."""
    conn = _get_conn()
    try:
        _receipt_lib().enforce_readonly(conn)
        if not symbols:
            symbols = _tracked_symbols(conn)
        batch = symbols[:SYMBOL_CAP]
        cur = conn.cursor()
        cur.execute("SELECT symbol, count(*), max(filing_date) FROM sec_form4 WHERE symbol = ANY(%s) GROUP BY symbol",
                    (batch,))
        stored = {r[0]: {"rows": int(r[1]), "latest_filing": str(r[2])} for r in cur.fetchall()}
    finally:
        conn.close()
    return {"symbols_total": len(symbols), "would_scan": batch, "stored": stored}


# Dedupe on the filing itself (2026-10-10). The table's only unique key is (symbol, filer_name,
# transaction_date, transaction_type), and this writer never sets transaction_date, so NULL never conflicted:
# every run re-inserted the same filings (measured 7,960 rows for 530 distinct sec_url). A Form 4 is identified
# by its accession URL, so a row is inserted only when no row for (symbol, sec_url) exists; a row without a URL
# falls back to (symbol, filing_date, filer_name, transaction_type). No schema change: existing duplicates are
# left in place for the operator (docs/audits/SEC_FORM4_DUPLICATES_2026-10-10.md).
FORM4_INSERT_SQL = """
    INSERT INTO sec_form4 (symbol, filer_name, filer_relation, transaction_type,
        filing_date, sec_url, strategy_tags, agent_tags)
    SELECT %(symbol)s, %(filer_name)s, %(filer_relation)s, %(transaction_type)s,
        %(filing_date)s::date, %(sec_url)s, %(strategy_tags)s::jsonb, %(agent_tags)s::jsonb
    WHERE NOT EXISTS (
        SELECT 1 FROM sec_form4 x
         WHERE x.symbol = %(symbol)s
           AND coalesce(x.sec_url, '') = %(sec_url)s
           AND (%(sec_url)s <> ''
                OR (x.filing_date IS NOT DISTINCT FROM %(filing_date)s::date
                    AND x.filer_name IS NOT DISTINCT FROM %(filer_name)s
                    AND x.transaction_type IS NOT DISTINCT FROM %(transaction_type)s)))
    ON CONFLICT DO NOTHING
"""


def _form4_insert_params(sym: str, f: dict, tags: dict) -> dict:
    return {
        "symbol": sym, "filer_name": f["filer_name"], "filer_relation": f["filer_relation"],
        "transaction_type": f["transaction_type"], "filing_date": f["filing_date"] or None,
        "sec_url": f["sec_url"] or "",
        "strategy_tags": json.dumps(tags["strategy_tags"]), "agent_tags": json.dumps(tags["agent_tags"]),
    }


def ingest_form4(symbols: list = None, limit: int = 5) -> dict:
    """Ingest Form 4 data for portfolio symbols."""
    if not symbols:
        conn = _get_conn()
        symbols = _tracked_symbols(conn)
        conn.close()

    total_new = 0
    fetch_failed = insert_attempts = insert_errors = 0
    for sym in symbols[:SYMBOL_CAP]:  # Rate limit protection
        errs_before = len(_FETCH_ERRORS)
        filings = fetch_form4(sym, limit=limit)
        if len(_FETCH_ERRORS) > errs_before:
            fetch_failed += 1
        if not filings:
            continue

        conn = _get_conn()
        cur = conn.cursor()
        for f in filings:
            from content_scoring import tag_content
            tags = tag_content(text=f"insider trading {sym} {f.get('transaction_type','')}", title=f"Form 4: {sym}")
            insert_attempts += 1
            try:
                cur.execute(FORM4_INSERT_SQL, _form4_insert_params(sym, f, tags))
                total_new += cur.rowcount
            except Exception:
                insert_errors += 1
                conn.rollback()

        conn.commit()
        conn.close()
        print(f"  [sec] {sym}: {len(filings)} Form 4 filings")

    return {"symbols_scanned": len(symbols[:SYMBOL_CAP]), "new_filings": total_new,
            "fetch_failed": fetch_failed, "insert_errors": insert_errors, "insert_attempts": insert_attempts}


def get_sec_intel(symbol: str) -> str:
    """Get SEC intelligence summary for agent prompt injection."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    lines = []

    # Form 4 — recent insider transactions
    cur.execute("""SELECT filer_name, transaction_type, filing_date, sec_url
                   FROM sec_form4 WHERE symbol=%s ORDER BY filing_date DESC LIMIT 3""", (symbol,))
    form4s = cur.fetchall()
    if form4s:
        lines.append(f"SEC FORM 4 (insider transactions for {symbol}):")
        for f in form4s:
            lines.append(f"  {f['filing_date']}: {f['filer_name']} — {f['transaction_type']}")

    # 13F — institutional holdings
    cur.execute("""SELECT institution, shares, value_thousands, change_pct, report_date
                   FROM sec_13f WHERE symbol=%s ORDER BY report_date DESC LIMIT 3""", (symbol,))
    inst = cur.fetchall()
    if inst:
        lines.append(f"SEC 13F (institutional holdings for {symbol}):")
        for i in inst:
            chg = f" ({float(i['change_pct']):+.1f}%)" if i.get("change_pct") else ""
            lines.append(f"  {i['institution']}: {float(i['shares']):,.0f} shares (${float(i['value_thousands']):,.0f}K){chg}")

    conn.close()
    return "\n".join(lines) if lines else ""


def test():
    """Test SEC data ingestion."""
    print("=== SEC Data Ingestion Test ===\n")

    # Test CIK lookup
    print("CIK lookups:")
    for sym in ["V", "SCHD", "LMT"]:
        cik = _get_cik(sym)
        print(f"  {sym}: CIK={cik if cik else 'NOT FOUND'}")

    # Test Form 4 fetch
    print("\nForm 4 fetch (V):")
    filings = fetch_form4("V", limit=3)
    for f in filings:
        print(f"  {f['filing_date']}: {f['filer_name']} — {f['transaction_type']}")

    # Test ingestion
    print("\nIngesting Form 4 for 3 symbols:")
    result = ingest_form4(["V", "LMT", "SCHD"], limit=3)
    print(f"  Result: {result}")

    # Test SEC intel context
    print("\nSEC intel for V:")
    intel = get_sec_intel("V")
    print(f"  {intel if intel else 'No SEC data yet'}")

    # Count stored
    conn = _get_conn()
    cur = conn.cursor()
    for t in ["sec_form4", "sec_13f", "sec_xbrl"]:
        cur.execute(f"SELECT count(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]} rows")
    conn.close()

    print("\n=== Test Complete ===")


def dry_run(argv) -> int:
    sym = None
    if "--form4" in argv and "--symbol" in argv:
        idx = argv.index("--symbol")
        if idx + 1 < len(argv):
            sym = [argv[idx + 1].upper()]
    plan = preview_form4(sym)
    for s_ in plan["would_scan"]:
        have = plan["stored"].get(s_)
        print(f"  [sec] would scan {s_}: stored sec_form4 rows={have['rows'] if have else 0}"
              + (f" latest={have['latest_filing']}" if have else ""))
    n = len(plan["would_scan"])
    _receipt_lib().dry_run_report(
        LANE_ID, {"symbols_total": plan["symbols_total"], "would_scan": n,
                  "symbols_with_stored_filings": len(plan["stored"]),
                  "sec_requests_planned": 2 * n},
        would_write=[f"sec_form4 INSERT ... WHERE NOT EXISTS (symbol, sec_url) (<= {5 * n} new rows)",
                     "pipeline_runs row (PipelineRun)"])
    return 0


def run_all() -> int:
    """The lane (--all): ingest_form4() + LaneRunReceipt@v1 + honest exit code."""
    lr = _receipt_lib()
    started = lr.now_iso()
    try:
        result = ingest_form4()
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="sec_data_ingest.py", error=f"{type(exc).__name__}: {exc}")
        raise
    print(json.dumps(result, indent=2))
    scanned = result["symbols_scanned"]
    failed = (scanned > 0 and result["fetch_failed"] >= scanned) or (
        result["insert_attempts"] > 0 and result["insert_errors"] >= result["insert_attempts"])
    rc = 1 if failed else 0
    lr.write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started,
                          script="sec_data_ingest.py", summary=result)
    return rc


def main(argv) -> int:
    if "--test" in argv:
        test()
    elif "--form4" in argv:
        sym = None
        if "--symbol" in argv:
            idx = argv.index("--symbol")
            if idx + 1 < len(argv):
                sym = [argv[idx + 1].upper()]
        result = ingest_form4(sym)
        print(json.dumps(result, indent=2))
    elif "--all" in argv:
        return run_all()
    else:
        print("Usage: --test | --form4 [--symbol V] | --all  [--dry-run]")
        return 2
    return 0


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        # Before PipelineRun: a dry run records no pipeline_runs row and cannot reach ingest_form4().
        sys.exit(dry_run(sys.argv[1:]))
    with PipelineRun("sec_data_ingest") as _run:
        sys.exit(main(sys.argv[1:]))
