"""LQ-20261107-1239 emulation: the lane WRITES, the card READS, on a throwaway socket-only Postgres cluster.

The unit tests beside this file drive both sides with dicts. This one stands up the real thing — initdb + pg_ctl on a
unix socket, a test-only role, destroyed afterwards — seeds the weekend's shape as of Sunday 2026-11-08 16:45 ET, runs
``news_risk_raise.run(..., apply=True)``, and then reads the card's two blocks back through
``market_risk_book_join`` against the rows the lane just wrote.

Never the live database: its own data directory, its own socket, its own role, torn down in a finally block.
Synthetic data only (public repo).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts import news_risk_raise as nrr  # noqa: E402
from scripts.lib import market_risk_book_dollars as bd  # noqa: E402
from scripts.lib import market_risk_book_join as bj  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402

ET = ZoneInfo("America/New_York")
SUNDAY = datetime(2026, 11, 8, 16, 45, tzinfo=ET)
POLICY = load_policy()


def _bin() -> Path | None:
    p = shutil.which("pg_ctl")
    if p:
        return Path(p).parent
    for major in ("17", "18", "16", "15"):
        cand = Path(f"/usr/lib/postgresql/{major}/bin")
        if (cand / "pg_ctl").exists():
            return cand
    return None


BIN = _bin()

SCHEMA = """
CREATE TABLE news_articles (
  id serial PRIMARY KEY, symbol text, title text, summary text,
  published_at timestamptz, created_at timestamptz DEFAULT now(),
  is_duplicate boolean DEFAULT false, hygiene_status text DEFAULT 'active',
  agent_tags jsonb
);
CREATE TABLE catalyst_events (
  id serial PRIMARY KEY, symbol text NOT NULL, catalyst_type text NOT NULL, headline text NOT NULL,
  severity text, confidence double precision, impact_score double precision, source text,
  published_at timestamptz, created_at timestamptz DEFAULT now(), raw_payload jsonb,
  UNIQUE (symbol, headline)
);
CREATE TABLE market_event_episodes (
  episode_id text PRIMARY KEY, scope text, state text, opened_at timestamptz
);
CREATE TABLE market_event_candidates (
  episode_id text NOT NULL, symbol text NOT NULL, source text[], reason_evidence jsonb, state text,
  updated_at timestamptz, PRIMARY KEY (episode_id, symbol)
);
CREATE TABLE trade_closed (symbol text, account text, close_date date, pnl numeric);
CREATE TABLE watchlist_items (symbol text, status text);
CREATE TABLE market_quotes_extended (
  symbol text NOT NULL, session text NOT NULL, session_date date, bar_start timestamptz, bar_end timestamptz NOT NULL,
  price double precision, change_pct double precision, reference_basis text, reference_date date, feed text
);
"""

# The weekend, synthetic: Friday 16:00 ET is the floor. Articles before it, duplicates and out-of-scope names must all
# stay untouched; every in-scope article is tagged and the two material ones are raised.
ARTICLES = [
    # id 1: held, canonical catalyst row exists (high) -> material through catalyst_events
    ("NVDA", "NVDA completes merger with a peer", "2026-11-07 12:00-05"),
    # id 2: watchlist, canonical row exists (critical)
    ("V", "V raises guidance for the year", "2026-11-06 18:38-05"),
    # id 3: watchlist, no catalyst row -> classified from the keyword map (dividend_increase, medium) -> tagged only
    ("SCHD", "SCHD announces dividend increase", "2026-11-07 10:35-05"),
    # id 4: not in scope anywhere
    ("ANET", "ANET unveils a new switch", "2026-11-07 12:00-05"),
    # id 5: before Friday's close -> outside the window even though it is scoped
    ("NVDA", "NVDA old news before the close", "2026-11-06 15:00-05"),
]

STORE = {"holdings": [{"symbol": "NVDA", "account": "Demo Taxable"},
                      {"symbol": "CASH", "account": "Demo Taxable", "is_cash": True}]}


@pytest.fixture(scope="module")
def cluster():
    base = Path(tempfile.mkdtemp(prefix="nrr-pg-", dir=os.environ.get("TMPDIR") or None))
    data, sock = base / "data", base / "sock"
    sock.mkdir()
    env = {**os.environ, "LC_ALL": "C"}
    for k in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSWORD", "PGSERVICE", "PGPASSFILE", "DATABASE_URL"):
        env.pop(k, None)
    subprocess.run([str(BIN / "initdb"), "-D", str(data), "-U", "nrr", "--auth=trust", "-E", "UTF8"], check=True,
                   capture_output=True, env=env)
    port = "55453"
    opts = f"-c listen_addresses='' -c unix_socket_directories={sock} -p {port} -c fsync=off"
    subprocess.run([str(BIN / "pg_ctl"), "-D", str(data), "-o", opts, "-l", str(base / "log"), "-w", "start"],
                   check=True, capture_output=True, env=env)

    def psql(sql=None, file=None):
        argv = [str(BIN / "psql"), "-X", "-h", str(sock), "-p", port, "-U", "nrr", "-d", "postgres", "-v",
                "ON_ERROR_STOP=1", "-tA"] + (["-f", str(file)] if file else ["-c", sql])
        p = subprocess.run(argv, capture_output=True, text=True, env=env)
        return p.returncode, (p.stdout + p.stderr).strip()

    def connect():
        import psycopg2

        return psycopg2.connect(host=str(sock), port=int(port), user="nrr", dbname="postgres")

    try:
        assert psql(SCHEMA)[0] == 0
        yield psql, connect
    finally:
        subprocess.run([str(BIN / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], capture_output=True, env=env)
        shutil.rmtree(base, ignore_errors=True)  # scratch this test created


def _seed(psql):
    for sym, title, when in ARTICLES:
        assert psql(f"INSERT INTO news_articles (symbol, title, published_at) VALUES ('{sym}', '{title}', "
                    f"'{when}'::timestamptz)")[0] == 0
    # a duplicate and a hygiene-hidden article: never tagged, never raised
    assert psql("INSERT INTO news_articles (symbol, title, published_at, is_duplicate) "
                "VALUES ('NVDA', 'NVDA duplicate wire copy', '2026-11-07 12:01-05', TRUE)")[0] == 0
    assert psql("INSERT INTO news_articles (symbol, title, published_at, hygiene_status) "
                "VALUES ('NVDA', 'NVDA low quality scrape', '2026-11-07 12:02-05', 'hidden')")[0] == 0
    # the canonical classifier already spoke for two of them
    assert psql("INSERT INTO catalyst_events (symbol, catalyst_type, headline, severity, source, published_at, raw_payload) "
                "VALUES ('NVDA','merger_acquisition','NVDA completes merger with a peer','high','news-to-catalyst',"
                "'2026-11-07 12:00-05','{\"news_article_id\": 1}'), "
                "('V','guidance_raise','V raises guidance for the year','critical','news-to-catalyst',"
                "'2026-11-06 18:38-05','{\"news_article_id\": 2}')")[0] == 0
    assert psql("INSERT INTO market_event_episodes (episode_id, scope, state, opened_at) "
                "VALUES ('broad_selloff:market:2026-11-04','market','OPEN','2026-11-04 10:00-05')")[0] == 0
    # scope inputs: a stopped-out loss sale and an active watchlist name
    assert psql("INSERT INTO trade_closed (symbol, account, close_date, pnl) VALUES ('PFE','Demo IRA','2026-10-30',-412.0)")[0] == 0
    assert psql("INSERT INTO watchlist_items (symbol, status) VALUES ('V','active'),('SCHD','active')")[0] == 0
    # the overnight/futures store, as the Schwab lane writes it: one level-only print, one dated overseas print
    assert psql("INSERT INTO market_quotes_extended (symbol, session, session_date, bar_start, bar_end, price, change_pct, "
                "reference_basis, reference_date, feed) VALUES "
                "('/ES','futures_open','2026-11-08','2026-11-08 13:30-05','2026-11-08 13:30:00.001-05',6810.25,NULL,"
                "'none_level_only_no_dated_reference_in_payload',NULL,'schwab'), "
                "('$NIKKEI','futures_open','2026-11-06','2026-11-06 01:00-05','2026-11-06 01:00:00.001-05',50100,0.8,"
                "'schwab_quote_close_price_settle_dated','2026-11-05','schwab')")[0] == 0


@pytest.mark.skipif(BIN is None, reason="no PostgreSQL server binaries on this host")
def test_the_lane_writes_and_the_home_card_reads_the_same_rows(cluster):
    psql, connect = cluster
    _seed(psql)

    # ── the lane, applied, as of Sunday 16:45 ET ────────────────────────────────────────────────────────────────
    out = nrr.run(SUNDAY, apply=True, policy=nrr.load_policy(), connect=connect, store_loader=lambda: STORE)
    assert out["mode"] == "APPLY"
    assert out["scopes"] == {"held": 1, "stopped_out": 1, "watchlist": 2}
    assert out["articles_seen"] == 4  # 7 rows, minus the duplicate, the hidden one and the pre-close article
    assert out["tagged"] == 3 and out["tagged_by_scope"] == {"held": 1, "stopped_out": 0, "watchlist": 2}
    assert out["raised"] == 2 and out["raised_symbols"] == ["NVDA", "V"]
    assert out["episode_id"] == "broad_selloff:market:2026-11-04"
    assert out["applied"] == {"tagged": 3, "catalyst_events": 0, "candidates": 2}

    # ── what is on disk ─────────────────────────────────────────────────────────────────────────────────────────
    _, tagged = psql("SELECT count(*) FROM news_articles WHERE jsonb_array_length(COALESCE(agent_tags,'[]')) > 0")
    assert tagged == "3"
    _, kinds = psql("SELECT DISTINCT e->>'kind' FROM news_articles, jsonb_array_elements(agent_tags) e")
    assert kinds == "risk_scope"
    _, held_tag = psql("SELECT e->>'scopes' FROM news_articles, jsonb_array_elements(agent_tags) e WHERE symbol='NVDA'")
    assert held_tag == '["held"]'
    _, untouched = psql("SELECT count(*) FROM news_articles WHERE symbol IN ('ANET') OR published_at < '2026-11-06 16:00-05'")
    assert untouched == "2"  # ANET and the pre-close NVDA article carry no tag
    _, cands = psql("SELECT string_agg(symbol || ':' || state || ':' || (source)[1], ',' ORDER BY symbol) "
                    "FROM market_event_candidates")
    assert cands == "NVDA:WATCH:news-risk-raise,V:WATCH:news-risk-raise"
    _, evidence = psql("SELECT reason_evidence->>'as_of' IS NOT NULL AND (reason_evidence->'news_ids')::text = '[1]' "
                       "FROM market_event_candidates WHERE symbol='NVDA'")
    assert evidence == "t"
    # the lane added no catalyst row: both articles were already classified by the canonical lane
    _, cat = psql("SELECT count(*) FROM catalyst_events")
    assert cat == "2"

    # ── the card reads the same rows back ───────────────────────────────────────────────────────────────────────
    conn = connect()
    try:
        news = bj.material_news(conn, POLICY, SUNDAY, ["NVDA", "V", "SCHD", "PFE"])
        block = bj.material_news_block(news, SUNDAY, POLICY)
        markets = bj.overnight_markets(conn, SUNDAY, POLICY)
    finally:
        conn.close()
    assert news["NVDA"]["severity"] == "high" and news["NVDA"]["catalyst_type"] == "merger_acquisition"
    assert news["V"]["severity"] == "critical"
    assert "SCHD" not in news  # tagged (watchlist) but medium: never a material card item
    assert [i["symbol"] for i in block["items"]] == ["V", "NVDA"]  # critical first
    assert block["since"] == "2026-11-06T16:00:00-05:00"
    assert markets["items"][0]["symbol"] == "/ES" and markets["items"][0]["level_only"] is True
    assert markets["items"][1]["label"] == "Nikkei 225" and markets["items"][1]["level_only"] is False

    # the review item the Home card would show, built from the same map
    store = {"data_as_of": "2026-11-06", "portfolio_totals": {"total_value": 100_000.0},
             "holdings": [{"symbol": "NVDA", "account": "Demo Taxable", "market_value": 40_000.0, "shares": 100, "price": 400.0}]}
    proj = {"heatmap": [{"key": "tech", "kind": "sector", "state": "STRESS"}],
            "positions": {"NVDA": {"label": "hold", "look_through": {"groups": {"tech": 1.0}, "basis": "stock"}}},
            "book": {"budgets": []}}
    built = bd.build(proj, store, stops=[{"account": "Demo Taxable", "symbol": "NVDA", "stop_price": 300.0}],
                     policy=POLICY, label_fn=lambda k: "Demo Taxable", canon_fn=str, material_news=news)
    item = next(i for i in built["review"] if i["symbol"] == "NVDA")
    assert "material_news" in item["kinds"] and item["usd"] == 40_000.0
    assert item["facts"]["news_type"] == "merger acquisition" and item["facts"]["news_severity"] == "high"

    # ── a re-run is idempotent: one tag per article, no new candidates ─────────────────────────────────────────
    again = nrr.run(SUNDAY, apply=True, policy=nrr.load_policy(), connect=connect, store_loader=lambda: STORE)
    assert again["applied"]["candidates"] == 0
    _, per_article = psql("SELECT max(n) FROM (SELECT count(*) AS n FROM news_articles, "
                          "jsonb_array_elements(agent_tags) e GROUP BY news_articles.id) s")
    assert per_article == "1"
    _, total = psql("SELECT count(*) FROM market_event_candidates")
    assert total == "2"


@pytest.mark.skipif(BIN is None, reason="no PostgreSQL server binaries on this host")
def test_the_dry_run_on_the_same_cluster_writes_nothing(cluster):
    psql, connect = cluster
    out = nrr.run(SUNDAY, apply=False, policy=nrr.load_policy(), connect=connect, store_loader=lambda: STORE)
    assert out["mode"] == "DRY" and out["tagged"] >= 3
    _, n = psql("SELECT count(*) FROM news_articles WHERE jsonb_array_length(COALESCE(agent_tags,'[]')) > 0")
    assert n == "3"  # exactly what the applied run above left behind
