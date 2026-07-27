"""Stage 2 persistence tests — LAB database only (trade_ai_test).

Skipped with an explicit reason when ACTIVE_TRADER_TEST_DATABASE_DSN is absent.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

DSN = os.environ.get("ACTIVE_TRADER_TEST_DATABASE_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="ACTIVE_TRADER_TEST_DATABASE_DSN not set (lab DB required; never runs on production)")

psycopg2 = pytest.importorskip("psycopg2")

from active_trader.contracts import CapabilityState, Environment  # noqa: E402
from active_trader.discovery import (  # noqa: E402
    BrokerDiscoveryResult, DiscoveredAccount, make_capability, persist_capabilities,
)

NOW = datetime(2026, 7, 22, 18, 30, tzinfo=timezone.utc)


def _results(state=CapabilityState.SUPPORTED):
    cap = make_capability("alpaca", "alpaca_paper", Environment.SIMULATION, "READ_ACCOUNT",
                          state, "RUNTIME_READ_PROBE", NOW)
    acct = DiscoveredAccount("alpaca", "alpaca_paper", "***1234",
                             Environment.SIMULATION.value, "paper", "ACTIVE", "OK", "OK",
                             capabilities=[cap], observed_at=NOW.isoformat())
    return [BrokerDiscoveryResult("alpaca", "AVAILABLE", "OK", [acct], [], NOW.isoformat())]


@pytest.fixture(scope="module", autouse=True)
def migrated():
    import subprocess
    repo = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, str(repo / "scripts/active_trader/migrate.py"), "up"],
                       capture_output=True, text=True,
                       env={**os.environ, "ACTIVE_TRADER_TEST_DATABASE_DSN": DSN})
    assert r.returncode == 0, r.stderr


def test_persist_refuses_production_dsn():
    from active_trader.migrate import MigrationError
    with pytest.raises(MigrationError, match="REFUSED|production"):
        persist_capabilities("postgresql://u:p@localhost:5432/trade_ai", _results())


def test_persist_is_idempotent_upsert_with_evidence_hash():
    n1 = persist_capabilities(DSN, _results())
    n2 = persist_capabilities(DSN, _results())
    assert n1 == n2 == 1
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""SELECT count(*), max(evidence_ref) FROM broker_account_capabilities
                   WHERE broker='alpaca' AND account_label='alpaca_paper'
                     AND capability='READ_ACCOUNT'""")
    count, ev = cur.fetchone()
    assert count == 1 and ev and len(ev) == 64      # single row, sha256 evidence hash
    conn.close()


def test_stale_evidence_transition_recorded():
    persist_capabilities(DSN, _results())
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""SELECT state, expires_at FROM broker_account_capabilities
                   WHERE broker='alpaca' AND capability='READ_ACCOUNT'""")
    state, expires = cur.fetchone()
    assert state == "SUPPORTED" and expires is not None
    # contract layer resolves past-expiry to UNKNOWN (never silently SUPPORTED)
    cap = make_capability("alpaca", "alpaca_paper", Environment.SIMULATION, "READ_ACCOUNT",
                          CapabilityState.SUPPORTED, "RUNTIME_READ_PROBE", NOW)
    from datetime import timedelta
    assert cap.effective_state(NOW + timedelta(hours=25)) is CapabilityState.UNKNOWN
    conn.close()


def test_no_raw_account_ids_in_lab_rows():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT account_label, notes FROM broker_account_capabilities")
    for label, notes in cur.fetchall():
        assert not any(tok.isdigit() and len(tok) >= 6 for tok in str(label).split())
        assert "refresh_token" not in str(notes) and "secret" not in str(notes).lower()
    conn.close()
