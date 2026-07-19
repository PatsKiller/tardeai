"""v1.2.3 P1-2/3/4 — friction, statement reconciliation, OER ingestion (real PG)."""
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

psycopg2 = pytest.importorskip("psycopg2")


@pytest.fixture()
def pg():
    try:
        conn = psycopg2.connect(dbname=os.environ.get("DB_NAME", os.environ.get("PGDATABASE", "trade_ai")),
                                user=os.environ.get("DB_USER", "postgres"),
                                password=os.environ.get("DB_PASSWORD", ""),
                                host=os.environ.get("DB_HOST", "localhost"),
                                port=os.environ.get("DB_PORT", "5432"))
    except Exception as e:
        pytest.skip(f"no postgres: {e}")
    schema = f"p123_{uuid.uuid4().hex[:8]}"
    cur = conn.cursor()
    cur.execute(f'CREATE SCHEMA "{schema}"')
    cur.execute(f'SET search_path TO "{schema}"')
    conn.commit()
    yield conn, cur
    conn.rollback()
    conn.cursor().execute(f'DROP SCHEMA "{schema}" CASCADE')
    conn.commit()
    conn.close()


def test_friction_buy_sell_direction_and_quality(pg):
    conn, cur = pg
    from options_execution_friction import ensure_friction_tables, record_friction, _dir_slip
    ensure_friction_tables(cur, conn)
    assert _dir_slip("BTC", 1.05, 1.00) == 0.05      # buy filled above mid = worse
    assert _dir_slip("STC", 0.95, 1.00) == 0.05      # sell filled below mid = worse
    assert _dir_slip("STO", 1.05, 1.00) == -0.05     # sell filled above mid = better
    ticket = {"strategy_position_id": 1, "quote_ts": "2026-07-18T14:00:00+00:00",
              "legs": [{"occ_symbol": "T", "instruction": "BTC", "contracts": 2,
                        "proposed_limit": 1.00, "bid": 0.95, "ask": 1.05}]}
    n = record_friction(cur, conn, ticket, 7, {("T", "BTC"): {"vwap": 1.02, "fills_count": 2}}, "schwab")
    assert n == 1
    cur.execute("SELECT slippage_vs_mid, slippage_vs_limit, data_quality_state, partial_fill_count FROM options_execution_friction")
    slip_mid, slip_lim, quality, pf = cur.fetchone()
    assert abs(float(slip_mid) - 0.02) < 1e-9 and abs(float(slip_lim) - 0.02) < 1e-9
    assert quality == "ACTUAL" and pf == 2
    # replay upserts (no dup), operator source can never be ACTUAL, missing quotes = UNAVAILABLE
    record_friction(cur, conn, ticket, 7, {("T", "BTC"): {"vwap": 1.02, "fills_count": 2}}, "schwab")
    cur.execute("SELECT count(*) FROM options_execution_friction")
    assert cur.fetchone()[0] == 1
    t2 = {**ticket, "legs": [{**ticket["legs"][0], "bid": None, "ask": None}]}
    record_friction(cur, conn, t2, 8, {("T", "BTC"): {"vwap": 1.02}}, "operator_manual")
    cur.execute("SELECT data_quality_state, slippage_vs_mid FROM options_execution_friction WHERE ticket_id=8")
    q2, s2 = cur.fetchone()
    assert q2 == "UNAVAILABLE" and s2 is None        # NULLs preserved, never fabricated


def test_statement_reconciliation_states(pg):
    conn, cur = pg
    from schwab_econfirm_reconcile import ensure_econfirm_tables
    from statement_reconciliation import reconcile_period
    ensure_econfirm_tables(cur, conn)
    cur.execute("""CREATE TABLE trade_transactions (trade_date date, action text, symbol text,
                   quantity numeric, price numeric, amount numeric, fees numeric,
                   account text, import_source text, dedupe_key text)""")
    # multi-fill day + fractional MF sale; ledger matches principal+charges
    rows = [("2026-07-07", "BJDX", "Sale", 1000, 1.41, 0.23, "e1"),
            ("2026-07-07", "BJDX", "Sale", 1000, 1.46, 0.23, "e2"),
            ("2026-07-13", "FCNTX", "Sale", 4034.942, 26.53, 0.0, "e3")]
    for d, sym, act, q, px, chg, dk in rows:
        cur.execute("""INSERT INTO econfirm_evidence
            (email_message_id, trade_date, symbol, action, quantity, price, principal,
             charge_or_interest, total_amount, parse_status, dedupe_key, parser_version,
             recon_status, matched_txn_dedupe_key)
            VALUES ('m', %s,%s,%s,%s,%s,%s,%s,%s,'parsed',%s,'econfirm-v2','EXACT_MATCH',%s)""",
            (d, sym, act, q, px, q * px, chg, q * px - chg, dk, "L" + dk))
        cur.execute("""INSERT INTO trade_transactions VALUES (%s,'Sell',%s,%s,%s,%s,%s,'a','s',%s)""",
                    (d, sym, q, px, -q * px, chg, "L" + dk))
    conn.commit()
    r = reconcile_period(cur, "2026-07-01", "2026-07-14")
    assert r["state"] == "EXACT_RECONCILIATION", r
    assert r["matched"] == 3 and r["unmatched_source_rows"] == 0
    # charge mismatch detected
    cur.execute("UPDATE trade_transactions SET fees=9.99 WHERE dedupe_key='Le1'")
    conn.commit()
    assert reconcile_period(cur, "2026-07-01", "2026-07-14")["state"] == "CHARGE_MISMATCH"
    # empty period = SOURCE_UNAVAILABLE, never fake-pass
    assert reconcile_period(cur, "2025-01-01", "2025-01-31")["state"] == "SOURCE_UNAVAILABLE"


def test_oer_rates_lineage_and_effective_dates(pg):
    conn, cur = pg
    from investment_costs import ensure_cost_tables
    from oer_rate_ingest import ensure_oer_tables, record_rate, rate_for
    ensure_cost_tables(cur, conn)
    ensure_oer_tables(cur, conn)
    # missing source → refused; nothing inferred
    r = record_rate(cur, conn, symbol="SCHG", net_expense_ratio=0.04, effective_from="2025-01-01",
                    source_url="", source_publisher="", source_excerpt="")
    assert r["ok"] is False and "REQUIRED" in r["error"]
    a = record_rate(cur, conn, symbol="SCHG", net_expense_ratio=0.04, effective_from="2025-01-01",
                    source_url="https://schwabassetmanagement.com/schg", source_publisher="Schwab AM",
                    source_excerpt="Net expense ratio 0.04%")
    assert a["ok"]
    # duplicate ingest = no-op
    assert record_rate(cur, conn, symbol="SCHG", net_expense_ratio=0.04, effective_from="2025-01-01",
                       source_url="https://schwabassetmanagement.com/schg", source_publisher="Schwab AM",
                       source_excerpt="Net expense ratio 0.04%").get("duplicate")
    # same-source correction supersedes with lineage
    b = record_rate(cur, conn, symbol="SCHG", net_expense_ratio=0.03, effective_from="2026-01-01",
                    source_url="https://schwabassetmanagement.com/schg2026", source_publisher="Schwab AM",
                    source_excerpt="Net expense ratio 0.03% effective 2026")
    assert b["ok"]
    # rate change over time: historical period uses the HISTORICAL rate
    assert rate_for(cur, "SCHG", "2025-06-30")["net_expense_ratio"] == 0.04
    assert rate_for(cur, "SCHG", "2026-06-30")["net_expense_ratio"] == 0.03
    # conflicting DIFFERENT source enters review and never silently wins
    c = record_rate(cur, conn, symbol="SCHG", net_expense_ratio=0.09, effective_from="2026-01-01",
                    source_url="https://thirdparty.example/schg", source_publisher="ThirdParty",
                    source_excerpt="expense 0.09%")
    assert c["review_state"] == "conflict_review"
    assert rate_for(cur, "SCHG", "2026-06-30")["net_expense_ratio"] == 0.03
    # no rate available = None (gap), never zero
    assert rate_for(cur, "NOPE", "2026-06-30") is None
