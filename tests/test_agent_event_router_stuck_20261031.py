"""agent_event_queue rows must never stay 'processing' forever (7 RSI_EXTREME rows, 2026-10-01..10-23).

Root cause: the content-gap loop ran minutes of subprocesses while the batch DB connection sat idle; the server
closed it and the final "mark done" UPDATE raised on the closed connection, so the row stayed 'processing'.
Hermetic: fake connections only.
"""

import scripts.agent_event_router as R


class Cur:
    def __init__(self, log, rows=None, fail=False):
        self.log, self.rows, self.fail = log, rows or [], fail

    def execute(self, sql, params=None):
        if self.fail:
            raise RuntimeError("connection already closed")
        self.log.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Conn:
    def __init__(self, log, rows=None, fail=False):
        self.log, self.rows, self.fail, self.closed, self.commits = log, rows, fail, 0, 0

    def cursor(self, **kw):
        return Cur(self.log, self.rows, self.fail)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = 1


def test_status_write_uses_a_fresh_connection(monkeypatch):
    log = []
    monkeypatch.setattr(R, "_get_conn", lambda: Conn(log))
    assert R._set_event_status(5669, "done") is True
    assert any("SET status=%s, processed_at=NOW()" in s and p == ("done", 5669) for s, p in log)


def test_status_write_failure_is_logged_not_raised(monkeypatch, capsys):
    monkeypatch.setattr(R, "_get_conn", lambda: Conn([], fail=True))
    assert R._set_event_status(1, "done") is False
    assert "could not set event #1 -> done" in capsys.readouterr().out


def test_stale_processing_rows_are_marked_failed_not_rerun():
    log = []
    conn = Conn(log, rows=[(4825,), (5669,)])
    assert R.reclaim_stale_processing(conn, dry_run=False) == 2
    upd = [(s, p) for s, p in log if s.startswith("UPDATE")]
    assert upd and "status='failed'" in upd[0][0] and upd[0][1] == ([4825, 5669],)
    assert "pending" not in upd[0][0]
    assert conn.commits == 1


def test_stale_reclaim_dry_run_writes_nothing():
    log = []
    conn = Conn(log, rows=[(4825,)])
    assert R.reclaim_stale_processing(conn, dry_run=True) == 1
    assert not [s for s, _ in log if s.startswith("UPDATE")] and conn.commits == 0


def test_topic_events_create_no_per_symbol_jobs():
    log = []
    conn = Conn(log)
    ev = {
        "id": 9,
        "symbol": "TOPIC:ai_datacenter_buildout",
        "agents_to_notify": ["Maria", "Steph"],
        "event_type": "TOPIC_INTELLIGENCE",
    }
    assert R.create_agent_jobs(conn, ev, dry_run=False) == []
    assert log == []
    assert R._is_topic_subject("topic:x") and not R._is_topic_subject("TOPS") and not R._is_topic_subject(None)
