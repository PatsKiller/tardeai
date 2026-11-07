#!/usr/bin/env python3
"""sec_data_ingest.py — SEC data ingestion (Form 4, 13F, XBRL).

Uses free SEC EDGAR APIs (data.sec.gov). No API key needed.
Rate limit: 10 requests/second with User-Agent header.

Usage:
    python3 scripts/sec_data_ingest.py --test
    python3 scripts/sec_data_ingest.py --form4 [--symbol SYMBOL]
    python3 scripts/sec_data_ingest.py --all
    python3 scripts/sec_data_ingest.py --all --dry-run
    python3 scripts/sec_data_ingest.py --backfill-plan [--limit N]

A Form 4 row is one TRANSACTION, read from the filing's own ownership XML (LQ-20261107-58): the
reporting owner as ``filer_name``, the transaction code ("P" purchase, "S" sale, "A" award, "M" option
exercise, "F" tax withholding, …) as ``transaction_type``, and the shares, price, total value, ownership
after, transaction date and filing date. Before 2026-11-07 the writer read only the issuer's submissions
index, so every row named the ISSUER, said "Form 4", and carried 0 / 0 / 0 with a NULL transaction date
(measured: 7,039 rows for 519 filings, 7,039 zero-valued) — unreadable to every consumer, which already
match ``transaction_type`` against buy/sell codes.

Lane ``sec-data-ingest`` (cron L150, ``--all``). ``--dry-run`` wins over every mode: it never enters
PipelineRun (no pipeline_runs row) and makes no SEC request (data.sec.gov is free but rate-limited, so
the dry run reports the work list instead); it opens a READ ONLY session, reads the tracked-symbol
universe with the same query as a real run, and prints the symbols a real run would scan and the
sec_form4 rows already stored for them. No receipt.

``--backfill-plan`` is also write-free and outside PipelineRun: it re-reads the filings already stored
and reports what the corrected parser would write for them, so the 7,039 legacy rows can be archived
under an operator decision rather than deleted (AGENTS.md rule 6).

A real ``--all`` run writes ``<state_root>/data/runtime/sec-data-ingest_last.json`` (LaneRunReceipt@v1;
``ok_at`` only on success; ``--form4`` / ``--test`` are manual modes and write no lane receipt).
Exit codes: 0 = ran (symbols with no recent Form 4, or zero new transactions, are findings); 1 = the run
failed: crash / DB unavailable (failed receipt, exception re-raised), every scanned symbol's SEC fetch
errored, or every attempted sec_form4 insert errored; 2 = usage error (no mode given).
"""
import json, os, re, sys, time
import xml.etree.ElementTree as ET
from datetime import datetime, date, timezone
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
try:
    from lib import sec_edgar_client as _sec_client
except ImportError:  # imported as scripts.sec_data_ingest
    from scripts.lib import sec_edgar_client as _sec_client
#: SEC fair-access contact comes from config/sec_edgar_client.json + the local override, never from code
#: (DSN-20261101 P0-T2). An empty/placeholder/invalid contact raises SecContactError: no request is sent.
SecContactError = _sec_client.SecContactError


def _sec_headers() -> dict:
    return _sec_client.headers("application/json")
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
    """Make a rate-limited request to SEC EDGAR and parse JSON."""
    body = _sec_get_text(url, accept="application/json")
    if not body:
        return {}
    try:
        return json.loads(body)
    except ValueError:
        _FETCH_ERRORS.append(f"{url}: invalid JSON")
        return {}


def _sec_get_text(url: str, accept: str = "application/xml") -> str:
    """Rate-limited GET returning the body as text ("" on any failure, recorded in _FETCH_ERRORS)."""
    import urllib.request
    req = urllib.request.Request(url, headers=_sec_headers_for(accept))  # fails closed before any request
    _sec_client.throttle()  # SEC fair access (config spacing_s / max_rps)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  [sec] Error: {e}")
        _FETCH_ERRORS.append(f"{url}: {type(e).__name__}")
        return ""


def _sec_headers_for(accept: str) -> dict:
    """The one User-Agent (sec_edgar_client, fails closed) plus the Accept this request needs."""
    return {**_sec_headers(), "Accept": accept}


def _get_cik(symbol: str) -> str:
    """Look up CIK number for a ticker symbol."""
    # Try the ticker mapping first
    import urllib.request
    map_url = "https://www.sec.gov/files/company_tickers.json"
    req = urllib.request.Request(map_url, headers=_sec_headers())  # fails closed before any request
    try:
        _sec_client.throttle()
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            for entry in data.values():
                if entry.get("ticker", "").upper() == symbol.upper():
                    return str(entry["cik_str"]).zfill(10)
    except Exception as e:
        _FETCH_ERRORS.append(f"company_tickers.json: {type(e).__name__}")
    return ""


def raw_document_url(cik: str, accession: str, primary_document: str) -> str:
    """The filing's own XML. EDGAR's submissions index names the RENDERED document
    (``xslF345X06/ownership.xml``); the machine document is the same file directly in the accession
    folder. Reading the rendered variant returns HTML, which no parser can read (LQ-20261107-58)."""
    doc = str(primary_document or "").rsplit("/", 1)[-1]
    return f"https://www.sec.gov/Archives/edgar/data/{str(cik).lstrip('0')}/{accession}/{doc}"


def _flag(node, tag: str) -> bool:
    return node is not None and (node.findtext(tag) or "").strip().lower() in {"1", "true", "yes"}


def _relation(owner) -> str:
    """Human label for the reporting owner's relationship, e.g. "Director, Officer (Chief Executive
    Officer)". `filer_relation` was the constant "insider" while every row named the ISSUER."""
    rel = owner.find("reportingOwnerRelationship") if owner is not None else None
    if rel is None:
        return "insider"
    parts = []
    if _flag(rel, "isDirector"):
        parts.append("Director")
    if _flag(rel, "isOfficer"):
        title = (rel.findtext("officerTitle") or "").strip()
        parts.append(f"Officer ({title})" if title else "Officer")
    if _flag(rel, "isTenPercentOwner"):
        parts.append("10% Owner")
    if _flag(rel, "isOther"):
        other = (rel.findtext("otherText") or "").strip()
        parts.append(f"Other ({other})" if other else "Other")
    return ", ".join(parts) or "insider"


def _scalar(node, path: str):
    """Text of a Form 4 element, which is either a bare value or a ``<value>`` child. None when absent
    (a missing price is expressed as a footnote id, not as 0)."""
    if node is None:
        return None
    el = node.find(path)
    if el is None:
        return None
    inner = el.find("value")
    text = (inner.text if inner is not None else el.text) or ""
    return text.strip() or None


def _num(node, path: str):
    raw = _scalar(node, path)
    if raw is None:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _iso_date(raw) -> str:
    if not raw:
        return ""
    try:
        return date.fromisoformat(str(raw).strip()[:10]).isoformat()
    except ValueError:
        return ""


def _sum_known(a, b):
    """a + b, where an unknown addend (None) contributes nothing but never turns the sum into a zero:
    None + None is None (still unknown), 5 + None is 5."""
    if a is None:
        return b
    if b is None:
        return a
    return a + b


def parse_form4_xml(xml_text: str):
    """One row per transaction in a Form 4 ownership document, aggregated under the table's identity.

    Returns ``(rows, stats)``. Pure: no network, no DB, fixture-testable.

    * ``filer_name`` is the REPORTING OWNER (``reportingOwner/rptOwnerName``), joined with " & " when a
      filing names joint filers — never the issuer, which is what every stored row said.
    * ``transaction_type`` is the transaction CODE ("P", "S", "A", "M", "F", …). Every consumer already
      reads it that way (sec_form4_source_maturity._BUY_CODES, prospectus/domains startswith("P")/"S"),
      and the constant "Form 4" was unreadable to all of them.
    * Derivative transactions count: they are transactions of the same filing.

    sec_form4's unique key is (symbol, filer_name, transaction_date, transaction_type), so two lines of
    the same code on the same day are ONE row under that key. They are summed here (shares and
    total_value, price as the resulting average, the last line's post-transaction holding) rather than
    left for ``ON CONFLICT DO NOTHING`` to drop silently — measured on a live filing 2026-11-07, a
    12,359-share and an 11,735-share grant of the same code on the same day. ``stats["aggregated"]``
    counts the merges so the receipt can say so.

    A number the filing does NOT state is None (stored as SQL NULL), never 0: "not stated" and "zero"
    are different facts, and the zero row is the defect this parser replaces. An element that states
    "0" (a gift, a valueless grant) still stores 0.
    """
    stats = {"transactions": 0, "aggregated": 0, "no_code": 0, "no_price": 0, "no_shares": 0,
             "no_owner": 0, "no_transaction": 0, "xml_invalid": 0}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        stats["xml_invalid"] = 1
        return [], stats

    owners = [n.strip() for n in (o.findtext("reportingOwnerId/rptOwnerName") or ""
                                  for o in root.findall("reportingOwner")) if n and n.strip()]
    if not owners:
        stats["no_owner"] = 1
        return [], stats
    filer_name = " & ".join(owners)
    filer_relation = _relation(root.find("reportingOwner"))

    merged: dict = {}
    for tag in ("nonDerivativeTransaction", "derivativeTransaction"):
        for txn in root.iter(tag):
            stats["transactions"] += 1
            code = (_scalar(txn, "transactionCoding/transactionCode") or "").upper()
            if not code:
                stats["no_code"] += 1
                continue
            tdate = _iso_date(_scalar(txn, "transactionDate"))
            shares = _num(txn, "transactionAmounts/transactionShares")
            price = _num(txn, "transactionAmounts/transactionPricePerShare")
            after = _num(txn, "postTransactionAmounts/sharesOwnedFollowingTransaction")
            if shares is None:
                stats["no_shares"] += 1
            if price is None:
                stats["no_price"] += 1
            # An element the filing omits stays UNKNOWN (None), never 0: writing 0 for "not stated" is
            # precisely the defect this fix removes, one row down. A filing that states 0 (a gift, a
            # grant of 0 value) still stores 0 — _num returns 0.0 for an explicit "0".
            value = shares * price if shares is not None and price is not None else None
            row = merged.get((tdate, code))
            if row is None:
                merged[(tdate, code)] = {
                    "filer_name": filer_name, "filer_relation": filer_relation,
                    "transaction_type": code, "transaction_date": tdate or None,
                    "shares": shares, "price": price, "total_value": value,
                    "ownership_after": after,
                }
                continue
            stats["aggregated"] += 1
            row["shares"] = _sum_known(row["shares"], shares)
            row["total_value"] = _sum_known(row["total_value"], value)
            row["ownership_after"] = after if after is not None else row["ownership_after"]
            # The merged price is the resulting average; unknown when no line stated both numbers.
            row["price"] = (round(row["total_value"] / row["shares"], 6)
                            if row["shares"] and row["total_value"] is not None else None)

    if not merged and not stats["no_code"]:
        stats["no_transaction"] = 1  # holdings-only filing: nothing was transacted
    return [merged[k] for k in sorted(merged, key=lambda k: (k[0] or "", k[1]))], stats


def fetch_form4(symbol: str, limit: int = 10) -> list:
    """Fetch recent Form 4 filings for a symbol and return one dict per TRANSACTION.

    ``limit`` bounds the filings read (each filing is one extra EDGAR request, paced by
    sec_edgar_client). A filing whose XML cannot be fetched or parsed contributes nothing and is
    counted in ``_FETCH_ERRORS`` / the lane receipt — it is never turned into a zero row.
    """
    cik = _get_cik(symbol)
    if not cik:
        return []

    url = f"{SEC_EDGAR}/submissions/CIK{cik}.json"
    data = _sec_get(url)
    if not data:
        return []

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accessions = filings.get("accessionNumber", [])
    primary_docs = filings.get("primaryDocument", [])

    results = []
    seen = 0
    for i, form in enumerate(forms):
        if form != "4" and not form.startswith("4/"):
            continue
        if seen >= limit:  # rate limit: one EDGAR request per filing
            break
        seen += 1
        filing_date = dates[i] if i < len(dates) else ""
        accession = accessions[i].replace("-", "") if i < len(accessions) else ""
        doc = primary_docs[i] if i < len(primary_docs) else ""
        if not accession:
            continue
        sec_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession}/{doc}"
        xml = _sec_get_text(raw_document_url(cik, accession, doc))
        if not xml:
            continue
        rows, _stats = parse_form4_xml(xml)
        for row in rows:
            row.update(symbol=symbol.upper(), filing_date=filing_date,
                       transaction_date=row.get("transaction_date") or filing_date or None,
                       sec_url=sec_url)
            results.append(row)

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
        cur.execute("""SELECT symbol, count(*), max(filing_date),
                              count(*) FILTER (WHERE shares = 0 AND price = 0 AND total_value = 0),
                              count(*) FILTER (WHERE transaction_date IS NULL)
                         FROM sec_form4 WHERE symbol = ANY(%s) GROUP BY symbol""",
                    (batch,))
        stored = {r[0]: {"rows": int(r[1]), "latest_filing": str(r[2]),
                         "zero_valued": int(r[3]), "no_transaction_date": int(r[4])} for r in cur.fetchall()}
    finally:
        conn.close()
    return {"symbols_total": len(symbols), "would_scan": batch, "stored": stored}


# Dedupe on the TRANSACTION (2026-11-07, LQ-20261107-58). The 2026-10-10 guard keyed on (symbol, sec_url)
# alone, which was right while a filing produced one row; a filing produces one row per transaction, so the
# guard now names the transaction too: a re-read of the same filing re-produces the same (symbol, sec_url,
# filer, transaction_date, transaction_type) tuples and inserts nothing. `transaction_date` is finally set
# from the XML, so the table's own unique key also starts working (it never conflicted while it was NULL).
FORM4_INSERT_SQL = """
    INSERT INTO sec_form4 (symbol, filer_name, filer_relation, transaction_type,
        filing_date, transaction_date, shares, price, total_value, ownership_after,
        sec_url, strategy_tags, agent_tags)
    SELECT %(symbol)s, %(filer_name)s, %(filer_relation)s, %(transaction_type)s,
        %(filing_date)s::date, %(transaction_date)s::date, %(shares)s, %(price)s, %(total_value)s,
        %(ownership_after)s, %(sec_url)s, %(strategy_tags)s::jsonb, %(agent_tags)s::jsonb
    WHERE NOT EXISTS (
        SELECT 1 FROM sec_form4 x
         WHERE x.symbol = %(symbol)s
           AND coalesce(x.sec_url, '') = %(sec_url)s
           AND x.filer_name IS NOT DISTINCT FROM %(filer_name)s
           AND x.transaction_date IS NOT DISTINCT FROM %(transaction_date)s::date
           AND x.transaction_type IS NOT DISTINCT FROM %(transaction_type)s)
    ON CONFLICT DO NOTHING
"""

#: Does a row for this exact transaction already exist? Asked only when the INSERT changed nothing, so the
#: receipt can say whether the miss was "already present" or a collision on the table's unique key (a second
#: filing, same owner/code/day) — the two are not the same fact and must not be flattened into one number.
FORM4_PRESENT_SQL = """
    SELECT 1 FROM sec_form4 x
     WHERE x.symbol = %(symbol)s
       AND coalesce(x.sec_url, '') = %(sec_url)s
       AND x.filer_name IS NOT DISTINCT FROM %(filer_name)s
       AND x.transaction_date IS NOT DISTINCT FROM %(transaction_date)s::date
       AND x.transaction_type IS NOT DISTINCT FROM %(transaction_type)s
     LIMIT 1
"""


def _form4_insert_params(sym: str, f: dict, tags: dict) -> dict:
    """Bind one transaction. A number the filing did not state stays NULL — `x or 0` here would put the
    zero row back that this fix removes, and a NULL is a fact the operator can query for."""
    def num(key):
        v = f.get(key)
        return None if v is None else float(v)

    return {
        "symbol": sym, "filer_name": f["filer_name"], "filer_relation": f["filer_relation"],
        "transaction_type": f["transaction_type"],
        "filing_date": f["filing_date"] or None,
        "transaction_date": f.get("transaction_date") or None,
        "shares": num("shares"), "price": num("price"),
        "total_value": num("total_value"),
        "ownership_after": num("ownership_after"),
        "sec_url": f["sec_url"] or "",
        "strategy_tags": json.dumps(tags["strategy_tags"]), "agent_tags": json.dumps(tags["agent_tags"]),
    }


def ingest_form4(symbols: list = None, limit: int = 5) -> dict:
    """Ingest Form 4 transactions for portfolio symbols."""
    if not symbols:
        conn = _get_conn()
        symbols = _tracked_symbols(conn)
        conn.close()

    counts = {"new_filings": 0, "insert_attempts": 0, "insert_errors": 0,
              "already_present": 0, "duplicate_key": 0, "transactions_parsed": 0}
    fetch_failed = 0
    for sym in symbols[:SYMBOL_CAP]:  # Rate limit protection
        errs_before = len(_FETCH_ERRORS)
        transactions = fetch_form4(sym, limit=limit)
        if len(_FETCH_ERRORS) > errs_before:
            fetch_failed += 1
        if not transactions:
            continue
        counts["transactions_parsed"] += len(transactions)

        conn = _get_conn()
        cur = conn.cursor()
        for f in transactions:
            from content_scoring import tag_content
            tags = tag_content(text=f"insider {f.get('transaction_type','')} {sym}",
                               title=f"Form 4: {sym} {f.get('transaction_type','')}")
            params = _form4_insert_params(sym, f, tags)
            counts["insert_attempts"] += 1
            try:
                cur.execute(FORM4_INSERT_SQL, params)
                if cur.rowcount:
                    counts["new_filings"] += cur.rowcount
                else:  # guarded miss: say which kind
                    cur.execute(FORM4_PRESENT_SQL, params)
                    if cur.fetchone():
                        counts["already_present"] += 1
                    else:
                        counts["duplicate_key"] += 1
                conn.commit()  # per row: one failing insert must not discard the rows already written
            except Exception:
                counts["insert_errors"] += 1
                conn.rollback()

        conn.close()
        print(f"  [sec] {sym}: {len(transactions)} transactions from Form 4 filings")

    return {"symbols_scanned": len(symbols[:SYMBOL_CAP]), "fetch_failed": fetch_failed, **counts}


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
        cur.execute(f"SELECT count(*) FROM {t}")  # nosemgrep: tq-py-sql-fstring -- t from the literal table list above
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
              + (f" latest={have['latest_filing']}" if have else "")
              + (f" — {have['zero_valued']} zero-valued, {have['no_transaction_date']} with no transaction date"
                 if have else ""))
    n = len(plan["would_scan"])
    _receipt_lib().dry_run_report(
        LANE_ID, {"symbols_total": plan["symbols_total"], "would_scan": n,
                  "symbols_with_stored_filings": len(plan["stored"]),
                  # per symbol: the ticker map + the submissions index, then up to 5 filing XMLs
                  "sec_requests_planned": 7 * n},
        would_write=[f"sec_form4 INSERT ... WHERE NOT EXISTS (symbol, sec_url, filer, transaction_date, code) "
                     f"(<= {5 * n} transaction rows)",
                     "pipeline_runs row (PipelineRun)"])
    return 0


#: One filing's identity can be read back out of the URL it was stored with:
#: https://www.sec.gov/Archives/edgar/data/<cik>/<accession>/<document>
#: The stored URL names the RENDERED document, so the third group is the whole path below the accession
#: folder ("xslF345X06/tm2620483-1_4seq1.xml"); raw_document_url() keeps only its basename, which is
#: the raw ownership XML sitting beside the rendered copy.
_SEC_URL = re.compile(r"/Archives/edgar/data/(\d+)/(\d+)/(.+?)(?:\?|#|$)")


def plan_backfill(limit: int = 25) -> dict:
    """READ-ONLY: what the corrected parser would write for filings already stored (LQ-20261107-58).

    The 7,039 rows written before 2026-11-07 carry the issuer as the filer, a NULL transaction date and
    zero shares/price/value. This plan re-reads a bounded set of those filings and reports, per filing,
    how many transaction rows the corrected parser produces and how many legacy rows they supersede.
    It writes nothing and deletes nothing: the legacy rows are left for an operator-approved archive
    (AGENTS.md rule 6), which is why this is a plan and not a run.
    """
    conn = _get_conn()
    try:
        _receipt_lib().enforce_readonly(conn)
        cur = conn.cursor()
        cur.execute("""SELECT symbol, sec_url, count(*) AS rows,
                              count(*) FILTER (WHERE transaction_date IS NULL) AS legacy_rows
                         FROM sec_form4
                        WHERE coalesce(sec_url, '') <> ''
                     GROUP BY 1, 2 ORDER BY rows DESC LIMIT %s""", (limit,))
        filings = cur.fetchall()
    finally:
        conn.close()

    out, totals = [], {"filings": 0, "xml_unavailable": 0, "transactions": 0, "legacy_rows_superseded": 0}
    for symbol, sec_url, rows, legacy in filings:
        m = _SEC_URL.search(sec_url or "")
        if not m:
            totals["xml_unavailable"] += 1
            continue
        cik, accession, doc = m.groups()
        xml = _sec_get_text(raw_document_url(cik, accession, doc))
        parsed, stats = parse_form4_xml(xml) if xml else ([], {})
        if not xml:
            totals["xml_unavailable"] += 1
        totals["filings"] += 1
        totals["transactions"] += len(parsed)
        totals["legacy_rows_superseded"] += int(legacy)
        out.append({"symbol": symbol, "sec_url": sec_url, "stored_rows": int(rows),
                    "legacy_rows": int(legacy), "transactions_now": len(parsed),
                    "stats": stats,
                    "would_insert": [{"code": r["transaction_type"], "date": r["transaction_date"],
                                      "shares": r["shares"], "price": r["price"],
                                      "total_value": r["total_value"], "filer": r["filer_name"]}
                                     for r in parsed]})
    return {"mode": "backfill-plan (read-only, writes nothing)",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "totals": totals, "filings": out}


def run_all() -> int:
    """The lane (--all): ingest_form4() + LaneRunReceipt@v1 + honest exit code."""
    lr = _receipt_lib()
    started = lr.now_iso()
    try:
        result = ingest_form4()
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="sec_data_ingest.py", error=f"{type(exc).__name__}: {exc}",
                              output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    print(json.dumps(result, indent=2))
    scanned = result["symbols_scanned"]
    failed = (scanned > 0 and result["fetch_failed"] >= scanned) or (
        result["insert_attempts"] > 0 and result["insert_errors"] >= result["insert_attempts"])
    rc = 1 if failed else 0
    lr.write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started,
                          script="sec_data_ingest.py", summary=result, output=lane_output(result))
    return rc


def lane_output(result: dict) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: new sec_form4 rows; one filing yields one
    row per transaction, and a transaction already stored for (symbol, sec_url, filer, date, code) is
    skipped). attempted = INSERT attempts; no tracked symbol is fatal (``universe_empty_unexpected``); no
    new transaction = ``no_new_input``. ``duplicate_key`` is a real loss — a second filing, same owner/code/
    day, that the table's unique key cannot hold — and is named rather than counted as "already present"."""
    new = int(result.get("new_filings") or 0)  # nosemgrep: tq-py-missing-as-zero -- event counter: absent = zero rows inserted this run
    attempts = int(result.get("insert_attempts") or 0)  # nosemgrep: tq-py-missing-as-zero -- event counter: absent = zero INSERT attempts this run
    # These are counters of events observed THIS run: an absent key means the run made zero attempts
    # (or the caller is an older shape), so 0 is the true count, not a stand-in for an unknown.
    skipped = {"already_present": int(result.get("already_present") or 0),  # nosemgrep: tq-py-missing-as-zero -- event counter, absent = zero events this run
               "insert_error": int(result.get("insert_errors") or 0),  # nosemgrep: tq-py-missing-as-zero -- event counter, absent = zero events this run
               "duplicate_key": int(result.get("duplicate_key") or 0),  # nosemgrep: tq-py-missing-as-zero -- event counter, absent = zero events this run
               "fetch_failed": int(result.get("fetch_failed") or 0)}  # nosemgrep: tq-py-missing-as-zero -- event counter, absent = zero events this run
    if not int(result.get("symbols_scanned") or 0):
        skipped["universe_empty_unexpected"] = 1
    return {"produced_count": new, "attempted_count": max(attempts, new), "skipped_reasons": skipped,
            "empty_reason": "no_new_input" if new == 0 else None}


def main(argv) -> int:
    if "--test" in argv:
        test()
    elif "--backfill-plan" in argv:
        limit = 25
        if "--limit" in argv:
            idx = argv.index("--limit")
            if idx + 1 < len(argv):
                limit = max(1, int(argv[idx + 1]))
        print(json.dumps(plan_backfill(limit), indent=2, default=str))
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
        print("Usage: --test | --form4 [--symbol V] | --all | --backfill-plan [--limit N]  [--dry-run]")
        return 2
    return 0


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        # Before PipelineRun: a dry run records no pipeline_runs row and cannot reach ingest_form4().
        sys.exit(dry_run(sys.argv[1:]))
    if "--backfill-plan" in sys.argv:
        # A plan is a read: no pipeline_runs row, no INSERT, no DELETE.
        sys.exit(main(sys.argv[1:]))
    with PipelineRun("sec_data_ingest") as _run:
        sys.exit(main(sys.argv[1:]))
