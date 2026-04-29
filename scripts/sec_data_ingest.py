#!/usr/bin/env python3
"""sec_data_ingest.py — SEC data ingestion (Form 4, 13F, XBRL).

Uses free SEC EDGAR APIs (data.sec.gov). No API key needed.
Rate limit: 10 requests/second with User-Agent header.

Usage:
    python3 scripts/sec_data_ingest.py --test
    python3 scripts/sec_data_ingest.py --form4 [--symbol SYMBOL]
    python3 scripts/sec_data_ingest.py --all
"""
import json, os, sys, time
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SEC_BASE = "https://efts.sec.gov/LATEST/search-index?q="
SEC_EDGAR = "https://data.sec.gov"
SEC_HEADERS = {"User-Agent": "TradeAI john@jwwhiting.com", "Accept": "application/json"}


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
    except Exception:
        pass
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


def ingest_form4(symbols: list = None, limit: int = 5) -> dict:
    """Ingest Form 4 data for portfolio symbols."""
    if not symbols:
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT DISTINCT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
        symbols = [r["symbol"] for r in cur.fetchall()]
        conn.close()
        # Filter out mutual funds / non-SEC symbols
        symbols = [s for s in symbols if "-" not in s and len(s) <= 5]

    total_new = 0
    for sym in symbols[:15]:  # Rate limit protection
        filings = fetch_form4(sym, limit=limit)
        if not filings:
            continue

        conn = _get_conn()
        cur = conn.cursor()
        for f in filings:
            from content_scoring import tag_content
            tags = tag_content(text=f"insider trading {sym} {f.get('transaction_type','')}", title=f"Form 4: {sym}")
            try:
                cur.execute("""
                    INSERT INTO sec_form4 (symbol, filer_name, filer_relation, transaction_type,
                        filing_date, sec_url, strategy_tags, agent_tags)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (sym, f["filer_name"], f["filer_relation"], f["transaction_type"],
                      f["filing_date"] or None, f["sec_url"],
                      json.dumps(tags["strategy_tags"]), json.dumps(tags["agent_tags"])))
                total_new += cur.rowcount
            except Exception:
                conn.rollback()

        conn.commit()
        conn.close()
        print(f"  [sec] {sym}: {len(filings)} Form 4 filings")

    return {"symbols_scanned": len(symbols[:15]), "new_filings": total_new}


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


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    elif "--form4" in sys.argv:
        sym = None
        if "--symbol" in sys.argv:
            idx = sys.argv.index("--symbol")
            if idx + 1 < len(sys.argv):
                sym = [sys.argv[idx + 1].upper()]
        result = ingest_form4(sym)
        print(json.dumps(result, indent=2))
    elif "--all" in sys.argv:
        result = ingest_form4()
        print(json.dumps(result, indent=2))
    else:
        print("Usage: --test | --form4 [--symbol V] | --all")
