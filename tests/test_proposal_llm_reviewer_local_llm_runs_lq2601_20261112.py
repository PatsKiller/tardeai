"""LQ-20261107-2601: the proposal-review audit write targets only real local_llm_runs columns,
and a failed write is a WARNING with a counter (it was a silent debug line, failing since 2026-05-06)."""
import logging
import sys
from pathlib import Path

import psycopg2
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from tests.support.isolated_pg import isolated_cluster  # noqa: E402

# The REAL production shape (\d local_llm_runs, migration 20260506_1200 section 2.4).
REAL_DDL = """
CREATE TABLE local_llm_runs (
    id SERIAL PRIMARY KEY, model_name TEXT, status TEXT NOT NULL, run_type TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(), finished_at TIMESTAMPTZ, duration_sec NUMERIC,
    items_processed INTEGER DEFAULT 0, items_failed INTEGER DEFAULT 0, last_error TEXT, payload JSONB)
"""


@pytest.fixture(scope="module")
def conn():
    with isolated_cluster() as pg:
        c = psycopg2.connect(host=pg.host, port=pg.port, user=pg.user, password=pg.password, dbname=pg.dbname)
        cur = c.cursor()
        cur.execute(REAL_DDL)
        c.commit()
        yield c
        c.close()


@pytest.fixture()
def reviewer(monkeypatch):
    # session13_db may need env at import; the module only needs _record_review_run here.
    import proposal_llm_reviewer as r
    monkeypatch.setattr(r, "LOCAL_LLM_RUNS_WRITE_FAILURES", 0)
    return r


from datetime import datetime, timezone  # noqa: E402

PROPOSAL = {"id": 12650, "strategy_id": "s-1"}
REVIEW = {"decision": "CAUTIOUS_TEST", "confidence_score": 61}


def test_write_lands_a_real_row_with_context_in_payload(conn, reviewer):
    cur = conn.cursor()
    ok = reviewer._record_review_run(conn, cur, "governed-bridge", "ZZTEST", PROPOSAL, REVIEW, "local_llm",
                                     datetime.now(timezone.utc))
    conn.commit()
    assert ok is True
    cur.execute("select model_name,status,run_type,items_processed,payload from local_llm_runs "
                "where run_type='proposal_review' order by id desc limit 1")
    model, status, rtype, n, payload = cur.fetchone()
    assert (model, status, rtype, n) == ("governed-bridge", "completed", "proposal_review", 1)
    assert payload["symbol"] == "ZZTEST" and payload["strategy_id"] == "s-1"
    assert payload["proposal_id"] == 12650 and payload["decision"] == "CAUTIOUS_TEST"
    assert reviewer.LOCAL_LLM_RUNS_WRITE_FAILURES == 0


def test_failed_write_is_a_warning_with_a_counter_and_does_not_raise(conn, reviewer, caplog):
    cur = conn.cursor()
    cur.execute("ALTER TABLE local_llm_runs RENAME TO local_llm_runs_gone")
    conn.commit()
    try:
        with caplog.at_level(logging.WARNING, logger="llm_reviewer"):
            ok = reviewer._record_review_run(conn, cur, "m", "ZZTEST", PROPOSAL, REVIEW, "local_llm",
                                             datetime.now(timezone.utc))
            ok2 = reviewer._record_review_run(conn, conn.cursor(), "m", "ZZTEST", PROPOSAL, REVIEW, "local_llm",
                                              datetime.now(timezone.utc))
    finally:
        cur = conn.cursor()
        cur.execute("ALTER TABLE local_llm_runs_gone RENAME TO local_llm_runs")
        conn.commit()
    assert ok is False and ok2 is False
    assert reviewer.LOCAL_LLM_RUNS_WRITE_FAILURES == 2
    warns = [r for r in caplog.records if r.levelno == logging.WARNING and "local_llm_runs audit write failed" in r.getMessage()]
    assert len(warns) == 2 and "2 this process" in warns[-1].getMessage()
    # the connection is usable afterwards (rolled back), so the next status write is not poisoned
    c2 = conn.cursor(); c2.execute("select 1"); assert c2.fetchone() == (1,)


def test_review_proposal_uses_the_helper_not_the_old_column_list():
    src = (ROOT / "scripts" / "proposal_llm_reviewer.py").read_text()
    code = [ln.strip() for ln in src.splitlines() if not ln.strip().startswith("#")]
    assert "_record_review_run(conn, cur, model, symbol, proposal, review, narrative_source, now)" in code
    for dead in ("model_used, prompt_tokens", "response_tokens", "(table may differ)"):
        assert dead not in src
