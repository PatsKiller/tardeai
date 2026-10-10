"""sec_form4 re-runs must not duplicate filings (API_OVERLAP_CONSOLIDATION Q10, operator-approved 2026-10-10).

Measured (read-only SELECT, 2026-10-10): 7,960 sec_form4 rows for 530 distinct sec_url, all with
transaction_date NULL. The table's only unique key is (symbol, filer_name, transaction_date,
transaction_type); sec_data_ingest never sets transaction_date, and NULLs never conflict, so
"ON CONFLICT DO NOTHING" never fired and every run re-inserted the same filings.

The hermetic test drives ingest_form4 with a fake cursor that applies PostgreSQL's rules for this
table: the unique key ignores rows with a NULL member, and a guarded INSERT ... SELECT ... WHERE NOT
EXISTS inserts nothing when a row for (symbol, sec_url) exists. A second test runs the real SQL against
a scratch PostgreSQL when TRADEAI_SCRATCH_PG_DSN is set (never the live DB); otherwise it is skipped.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
    import psycopg2.extras  # noqa: F401
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

FILINGS = [
    {"symbol": "ACME", "filer_name": "Acme Corp", "filer_relation": "insider", "transaction_type": "Form 4",
     "filing_date": f"2026-10-0{i}", "sec_url": f"https://www.sec.gov/Archives/edgar/data/1/00{i}/f.xml"}
    for i in (1, 2, 3)
]


class _Table:
    def __init__(self):
        self.rows: list[dict] = []


class _Cur:
    """Applies PostgreSQL semantics for sec_form4 inserts (see module docstring)."""

    def __init__(self, table):
        self.t, self.rowcount = table, 0

    def execute(self, sql, params=None):
        if isinstance(params, dict):
            row = dict(params)
            row["transaction_date"] = None
            guarded = "NOT EXISTS" in sql
            exists = any(r["symbol"] == row["symbol"] and r["sec_url"] == row["sec_url"] for r in self.t.rows)
        else:  # the original positional VALUES insert
            sym, filer, rel, ttype, fdate, url, *_ = params
            row = {"symbol": sym, "filer_name": filer, "transaction_type": ttype, "filing_date": fdate,
                   "sec_url": url, "transaction_date": None}
            guarded, exists = False, False
        # unique (symbol, filer_name, transaction_date, transaction_type): a NULL member never conflicts
        unique_hit = row["transaction_date"] is not None and any(
            all(r[k] == row[k] for k in ("symbol", "filer_name", "transaction_date", "transaction_type"))
            for r in self.t.rows)
        if (guarded and exists) or unique_hit:
            self.rowcount = 0
            return
        self.t.rows.append(row)
        self.rowcount = 1


class _Conn:
    def __init__(self, table):
        self.table = table

    def cursor(self):
        return _Cur(self.table)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _wire(monkeypatch, table):
    monkeypatch.setattr(sdi, "fetch_form4", lambda sym, limit=5: [dict(f) for f in FILINGS])
    monkeypatch.setattr(sdi, "_get_conn", lambda: _Conn(table))
    monkeypatch.setitem(sys.modules, "content_scoring", types.SimpleNamespace(
        tag_content=lambda **_k: {"strategy_tags": [], "agent_tags": []}))


def test_rerun_inserts_no_duplicate_filings(monkeypatch):
    table = _Table()
    _wire(monkeypatch, table)
    first = sdi.ingest_form4(["ACME"])
    second = sdi.ingest_form4(["ACME"])
    third = sdi.ingest_form4(["ACME"])
    assert first["new_filings"] == 3
    assert second["new_filings"] == 0 and third["new_filings"] == 0, "a re-run must not re-insert the same filings"
    assert len(table.rows) == len({r["sec_url"] for r in table.rows}) == 3


def test_same_url_for_another_symbol_still_lands(monkeypatch):
    table = _Table()
    _wire(monkeypatch, table)
    sdi.ingest_form4(["ACME"])
    assert sdi.ingest_form4(["ACMEB"])["new_filings"] == 3  # dual-class share symbols share an accession


def test_url_less_filing_dedupes_on_filing_identity():
    params = sdi._form4_insert_params("ACME", {**FILINGS[0], "sec_url": ""}, {"strategy_tags": [], "agent_tags": []})
    assert params["sec_url"] == ""
    assert "x.filing_date IS NOT DISTINCT FROM" in sdi.FORM4_INSERT_SQL


@pytest.mark.skipif(not os.environ.get("TRADEAI_SCRATCH_PG_DSN"), reason="scratch PostgreSQL DSN not set")
def test_real_sql_against_scratch_postgres():  # pragma: no cover - opt-in, never the live DB
    import psycopg2 as pg
    dsn = os.environ["TRADEAI_SCRATCH_PG_DSN"]
    assert "trade_ai" not in dsn, "refusing to run against the production database"
    conn = pg.connect(dsn)
    cur = conn.cursor()
    cur.execute("CREATE TEMP TABLE sec_form4 (id bigserial primary key, symbol text not null,"
                " filer_name text default '', filer_relation text default '', transaction_type text default '',"
                " filing_date date, transaction_date date, sec_url text default '', strategy_tags jsonb default '[]',"
                " agent_tags jsonb default '[]', UNIQUE (symbol, filer_name, transaction_date, transaction_type))")
    tags = {"strategy_tags": [], "agent_tags": []}
    counts = []
    for _ in range(2):
        n = 0
        for f in FILINGS + [{**FILINGS[0], "sec_url": "", "filing_date": "2026-10-09"}]:
            cur.execute(sdi.FORM4_INSERT_SQL, sdi._form4_insert_params("ACME", f, tags))
            n += cur.rowcount
        counts.append(n)
    assert counts == [4, 0]
    conn.rollback()
    conn.close()
