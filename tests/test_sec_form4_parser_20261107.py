"""sec-data-ingest must store the Form 4's own facts, not the filing index's (LQ-20261107-58).

Measured read-only on the live table 2026-11-07: 7,039 sec_form4 rows for 519 distinct sec_url,
7,039 with shares = price = total_value = 0, 7,039 with transaction_date NULL, and filer_name set to
the ISSUER ("Armata Pharmaceuticals, Inc.") rather than the reporting owner. The parser read only the
issuer's submissions index — form, filingDate, accessionNumber, primaryDocument — so it never opened
the ownership XML that carries the owner, the transaction code, the shares, the price and the
transaction date. Every consumer already expects `transaction_type` to be the transaction CODE
(sec_form4_source_maturity._BUY_CODES = {"P", ...}; prospectus/domains.py startswith("P")/"S"), so a
row saying "Form 4" was unreadable to all of them.

These tests are hermetic: the XML is a synthetic document (this repository is public) and the cursor
fake applies PostgreSQL's rules for the insert guard and the table's unique key.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:  # pragma: no cover - environment dependent
    import psycopg2  # noqa: F401 -- imported only to prove the real driver is present; the tests use fakes
    import psycopg2.extras  # noqa: F401 -- same: presence check, every cursor in this file is a fake
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg_extras = types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import sec_data_ingest as sdi  # noqa: E402

# A synthetic ownership document: fictional issuer and owner, the real EDGAR element names.
XML = """<?xml version="1.0"?>
<ownershipDocument>
  <schemaVersion>X0609</schemaVersion>
  <documentType>4</documentType>
  <periodOfReport>2026-06-02</periodOfReport>
  <issuer>
    <issuerCik>0009999999</issuerCik>
    <issuerName>ZQXT HOLDINGS INC</issuerName>
    <issuerTradingSymbol>ZQXT</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001111111</rptOwnerCik>
      <rptOwnerName>Example Dana Q</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>1</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner>
      <isOther>0</isOther>
      <officerTitle>Chief Financial Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-06-01</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>P</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>12.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>6000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-06-02</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>S</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>400</value></transactionShares>
        <transactionPricePerShare><value>13.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>5600</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
    <!-- two grants of the same code on the same day: under the table's unique key they are ONE row -->
    <nonDerivativeTransaction>
      <securityTitle><value>Restricted Stock</value></securityTitle>
      <transactionDate><value>2026-06-01</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>200</value></transactionShares>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>5800</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Restricted Stock</value></securityTitle>
      <transactionDate><value>2026-06-01</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>300</value></transactionShares>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>6100</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <derivativeTable>
    <derivativeTransaction>
      <securityTitle><value>Employee Stock Option</value></securityTitle>
      <transactionDate><value>2026-06-01</value></transactionDate>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>5</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>500</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </derivativeTransaction>
  </derivativeTable>
</ownershipDocument>
"""

HOLDINGS_ONLY = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <issuer><issuerName>ZQXT HOLDINGS INC</issuerName><issuerTradingSymbol>ZQXT</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Example Dana Q</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOther>1</isOther><otherText>Former officer</otherText></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeHolding>
      <securityTitle><value>Common Stock</value></securityTitle>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>900</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeHolding>
  </nonDerivativeTable>
</ownershipDocument>
"""

CLEAN = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <issuer><issuerName>ZQXT HOLDINGS INC</issuerName><issuerTradingSymbol>ZQXT</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Example Dana Q</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-06-01</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10</value></transactionShares>
        <transactionPricePerShare><value>2.5</value></transactionPricePerShare>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>10</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


# --------------------------------------------------------------------------- the parsed row


def test_owner_is_the_filer_never_the_issuer():
    rows, _stats = sdi.parse_form4_xml(XML)
    assert {r["filer_name"] for r in rows} == {"Example Dana Q"}
    assert all("ZQXT" not in r["filer_name"].upper() for r in rows)


def test_every_transaction_carries_its_code_shares_price_and_date():
    rows, _stats = sdi.parse_form4_xml(XML)
    by_code = {r["transaction_type"]: r for r in rows}
    assert set(by_code) == {"P", "S", "A", "M"}
    p = by_code["P"]
    assert (p["shares"], p["price"], p["total_value"]) == (1000.0, 12.5, 12500.0)
    assert p["transaction_date"] == "2026-06-01"
    assert p["ownership_after"] == 6000.0
    s = by_code["S"]
    assert (s["shares"], s["price"], s["total_value"], s["transaction_date"]) == (400.0, 13.0, 5200.0, "2026-06-02")
    m = by_code["M"]  # a derivative transaction is still a transaction
    assert (m["shares"], m["price"], m["transaction_date"]) == (500.0, 5.0, "2026-06-01")


def test_same_day_same_code_lines_are_one_row_summed():
    # The table's unique key is (symbol, filer_name, transaction_date, transaction_type). Two grants of
    # the same code on the same day are ONE row under that key, so they are summed rather than silently
    # dropped by ON CONFLICT DO NOTHING (200 + 300 shares at no price).
    rows, _stats = sdi.parse_form4_xml(XML)
    a = [r for r in rows if r["transaction_type"] == "A"]
    assert len(a) == 1
    assert a[0]["shares"] == 500.0
    assert a[0]["transaction_date"] == "2026-06-01"


def test_an_unstated_number_is_unknown_not_zero():
    # The A lines above state shares but no price: "not stated" must stay unknown (stored as NULL), or
    # the row reproduces the zero row this fix removes, one row down. A filing that STATES 0 still
    # stores 0 — a gift, or a grant of no value.
    rows, stats = sdi.parse_form4_xml(XML)
    a = [r for r in rows if r["transaction_type"] == "A"][0]
    assert a["shares"] == 500.0
    assert a["price"] is None and a["total_value"] is None
    assert stats["no_price"] == 2, "both A lines stated no price"

    explicit = XML.replace("<transactionShares><value>1000</value></transactionShares>",
                           "<transactionShares><value>1000</value></transactionShares>"
                           "<transactionPricePerShare><value>0</value></transactionPricePerShare>")
    p = [r for r in sdi.parse_form4_xml(explicit)[0] if r["transaction_type"] == "P"][0]
    assert (p["shares"], p["price"], p["total_value"]) == (1000.0, 0.0, 0.0)


def test_filer_relation_names_the_office():
    rows, _stats = sdi.parse_form4_xml(XML)
    assert all(r["filer_relation"] == "Director, Officer (Chief Financial Officer)" for r in rows)


def test_a_holdings_only_filing_yields_no_transaction_rows():
    rows, stats = sdi.parse_form4_xml(HOLDINGS_ONLY)
    assert rows == []
    assert stats["no_transaction"] >= 1


def test_an_unparseable_document_is_reported_not_swallowed():
    rows, stats = sdi.parse_form4_xml("<ownershipDocument><broken>")
    assert rows == []
    assert stats["xml_invalid"] == 1


# --------------------------------------------------------------------------- the dedupe key


class _Table:
    def __init__(self):
        self.rows: list[dict] = []


class _Cur:
    """Applies PostgreSQL's rules for sec_form4: the guarded INSERT ... WHERE NOT EXISTS, and the
    unique key (symbol, filer_name, transaction_date, transaction_type), where a NULL member never
    conflicts."""

    def __init__(self, table):
        self.t, self.rowcount, self._hit = table, 0, False

    def execute(self, sql, params=None):
        row = dict(params)
        exists = any(
            r["symbol"] == row["symbol"]
            and (r.get("sec_url") or "") == (row.get("sec_url") or "")
            and r.get("filer_name") == row.get("filer_name")
            and r.get("transaction_date") == row.get("transaction_date")
            and r.get("transaction_type") == row.get("transaction_type")
            for r in self.t.rows
        )
        self._hit = exists
        if sql.strip().startswith("SELECT 1 FROM sec_form4"):  # the "which kind of miss" probe
            self.rowcount = 1 if exists else 0
            return
        unique_hit = row.get("transaction_date") is not None and any(
            all(r.get(k) == row.get(k) for k in ("symbol", "filer_name", "transaction_date", "transaction_type"))
            for r in self.t.rows
        )
        if ("NOT EXISTS" in sql and exists) or unique_hit:
            self.rowcount = 0
            return
        self.t.rows.append(row)
        self.rowcount = 1

    def fetchone(self):
        return (1,) if self._hit else None

    def close(self):
        pass


class _Conn:
    def __init__(self, table):
        self.t = table

    def cursor(self, *a, **k):
        return _Cur(self.t)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _wire(monkeypatch, table):
    monkeypatch.setattr(sdi, "_get_conn", lambda: _Conn(table))
    monkeypatch.setattr(sdi, "_tracked_symbols", lambda conn: ["ZQXT"])
    monkeypatch.setattr(sdi, "fetch_form4", lambda symbol, limit=5: [{
        "symbol": symbol,
        "filer_name": "Example Dana Q", "filer_relation": "Director",
        "transaction_type": "P", "filing_date": "2026-06-01", "transaction_date": "2026-06-01",
        "shares": 10.0, "price": 2.5, "total_value": 25.0, "ownership_after": 10.0,
        "sec_url": "https://www.sec.gov/Archives/edgar/data/9999999/0001/zqxt.xml",
    }])


def test_a_re_run_of_the_same_filing_inserts_nothing(monkeypatch):
    table = _Table()
    _wire(monkeypatch, table)
    first = sdi.ingest_form4(["ZQXT"])
    second = sdi.ingest_form4(["ZQXT"])
    assert first["new_filings"] == 1
    assert second["new_filings"] == 0
    assert len(table.rows) == 1
    assert sdi.lane_output(second)["skipped_reasons"]["already_present"] == 1


def test_the_stored_row_is_the_transaction_not_the_index_entry(monkeypatch):
    table = _Table()
    _wire(monkeypatch, table)
    sdi.ingest_form4(["ZQXT"])
    row = table.rows[0]
    assert row["transaction_type"] == "P"
    assert float(row["shares"]) == 10.0 and float(row["price"]) == 2.5
    assert float(row["total_value"]) == 25.0
    assert row["transaction_date"] == "2026-06-01"


# --------------------------------------------------------------------------- the raw document url


@pytest.mark.parametrize("primary,expected", [
    ("xslF345X06/ownership.xml", "ownership.xml"),
    ("xslF345X05/form4-07022026_080711.xml", "form4-07022026_080711.xml"),
    ("form4.xml", "form4.xml"),
])
def test_raw_document_url_strips_the_rendered_variant_folder(primary, expected):
    url = sdi.raw_document_url("0000921114", "000110465926083516", primary)
    assert url.endswith("/" + expected)
    assert "xslF345" not in url


@pytest.mark.parametrize("stored,expected", [
    ("https://www.sec.gov/Archives/edgar/data/921114/000110465926083516/xslF345X06/tm2620483-1_4seq1.xml",
     "https://www.sec.gov/Archives/edgar/data/921114/000110465926083516/tm2620483-1_4seq1.xml"),
    ("https://www.sec.gov/Archives/edgar/data/1095435/000117184326006026/xslF345X06/ownership.xml",
     "https://www.sec.gov/Archives/edgar/data/1095435/000117184326006026/ownership.xml"),
])
def test_a_stored_url_reads_back_to_its_raw_xml(stored, expected):
    # The backfill plan recovers the filing identity from the URL already stored. The stored URL names
    # the RENDERED document, and the document lives one folder below the accession, so a regex that
    # stops at the next "/" yields "xslF345X06" and fetches a folder (HTTP 404) instead of the filing.
    m = sdi._SEC_URL.search(stored)
    assert m, "the stored URL must be readable as a filing identity"
    assert sdi.raw_document_url(*m.groups()) == expected
