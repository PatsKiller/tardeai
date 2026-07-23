"""Stage 3 persistence tests — LAB database only (trade_ai_test)."""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

DSN = os.environ.get("ACTIVE_TRADER_TEST_DATABASE_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="ACTIVE_TRADER_TEST_DATABASE_DSN not set (lab DB required; never runs on production)")

psycopg2 = pytest.importorskip("psycopg2")

from active_trader.rejections import classify, persist_rejection, project_capability  # noqa: E402
from active_trader.notifications import (  # noqa: E402
    InMemorySink, LabDbSink, NotificationCenter,
)

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 22, 21, 0, tzinfo=timezone.utc)


def run_migrate(*args):
    return subprocess.run([sys.executable, str(REPO / "scripts/active_trader/migrate.py"), *args],
                          capture_output=True, text=True,
                          env={**os.environ, "ACTIVE_TRADER_TEST_DATABASE_DSN": DSN})


@pytest.fixture(scope="module", autouse=True)
def migrated():
    r = run_migrate("reapply")
    assert r.returncode == 0, r.stderr + r.stdout
    yield


def _event(msg="broker assistance", symbol="GME", account="schwab_taxable"):
    sys.path.insert(0, str(REPO / "tests"))
    from test_active_trader_stage3_rejections import make_event  # reuse factory
    return make_event(raw_message=msg, symbol=symbol, account=account)


def test_migration_0006_forward_rollback_reapply():
    st = run_migrate("status")
    assert "rejection_enrichment" in st.stdout and "pending" not in st.stdout
    down = run_migrate("down", "--to", "5")
    assert down.returncode == 0 and "0006" in down.stdout
    up = run_migrate("up")
    assert up.returncode == 0 and "0006" in up.stdout


def test_rejection_upsert_occurrence_and_links():
    e = _event()
    cls = classify(e)
    prop = project_capability(e, cls)
    rid1 = persist_rejection(DSN, e, cls, prop)
    rid2 = persist_rejection(DSN, e, cls, prop)          # replay same raw event
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""SELECT count(*), max(occurrence_count), max(classifier_version),
                          max(matched_rule_id), max(confidence), max(capability_evidence_ref)
                   FROM broker_rejection_events WHERE idempotency_key = %s""",
                (e.idempotency_key,))
    count, occ, ver, rule, conf, capref = cur.fetchone()
    assert count == 1 and occ == 2                       # one row, incremented
    assert rid1 == rid2                                  # same event id returned
    assert ver and rule == "SW-PT-001" and conf == "MESSAGE_PATTERN"
    assert capref and len(capref) == 64                  # capability-evidence link
    cur.execute("""SELECT retryable, requires_operator, requires_broker_call, evidence_hash
                   FROM broker_rejection_events WHERE idempotency_key = %s""", (e.idempotency_key,))
    retry, op, call, ev = cur.fetchone()
    assert (retry, op, call) == (False, True, True) and len(ev) == 64
    conn.close()


def test_notification_lab_rows_dedupe_and_link():
    sink = LabDbSink(DSN)
    center = NotificationCenter(sinks=[InMemorySink(), sink], now=lambda: NOW)
    e = _event(msg="not permitted for electronic entry", symbol="AMC")
    note = center.publish(e, classify(e), requested_qty=50)
    center.publish(e, classify(e), requested_qty=50)     # identical — deduped in memory, no re-emit
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""SELECT count(*), max(severity), max(status), bool_and(requires_operator_action)
                   FROM active_trader_notification_events WHERE dedupe_key = %s""",
                (note.dedupe_key,))
    count, sev, status, op = cur.fetchone()
    assert count == 1 and sev == "BLOCKING" and op is True   # ACTION_REQUIRED -> BLOCKING mapping
    cur.execute("SELECT rejection_event_id IS NOT NULL FROM active_trader_notification_events WHERE dedupe_key=%s",
                (note.dedupe_key,))
    conn.close()


def test_no_unmasked_ids_or_secrets_in_lab_rows():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT raw_message, raw_code FROM broker_rejection_events")
    for msg, code in cur.fetchall():
        import re
        assert not re.search(r"\b\d{8,}\b", str(msg)), "unmasked digit run in raw_message"
        low = str(msg).lower()
        assert "bearer " not in low and "api_key=" not in low
    cur.execute("SELECT body FROM active_trader_notification_events WHERE body IS NOT NULL")
    for (body,) in cur.fetchall():
        assert "SECRETVALUE" not in str(body)
    conn.close()


def test_production_db_untouched():
    """The rejection tables exist ONLY in the lab DB; production has no new rows/schema."""
    from active_trader.migrate import _resolve_dsn, MigrationError
    with pytest.raises(MigrationError):
        _resolve_dsn("postgresql://u:p@localhost:5432/trade_ai")
