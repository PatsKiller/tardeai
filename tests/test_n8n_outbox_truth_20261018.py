"""Outbox full-window aggregates versus bounded details, fake query effects only."""
from datetime import datetime,timezone,timedelta
from scripts.lib import notification_outbox_projection as P
NOW=datetime(2026,10,18,16,tzinfo=timezone.utc)

def query(sql,params):
    if 'GROUP BY' in sql:
        return [('communication_outbox','suppressed',600),('communication_outbox','sent',1)]
    if sql.startswith('SELECT outbox_id'):
        return [(i,f'event-{i}','telegram','suppressed',0,'dedupe',NOW-timedelta(minutes=1),NOW) for i in range(500)]
    return []

def test_full_outbox_total_is_not_limited_detail_count():
    out=P.project_outbox(query,now=NOW)
    assert out['total']==601
    assert out['counts']['communication_outbox']['sent']==1
    assert out.get('coverage',{}).get('items_truncated') is True


def test_hidden_older_send_prevents_false_silent_senders_alarm():
    out=P.project_outbox(query,now=NOW)
    assert 'silent_senders' not in [r['item'] for r in P.anomalies(out)]


def test_unavailable_outbox_has_unknown_totals(monkeypatch):
    monkeypatch.delenv('DB_PASSWORD',raising=False)
    out=P.load_outbox(now=NOW)
    assert out['count'] is None and out['total'] is None and out['counts'] is None


def test_actual_sql_aggregates_all_rows_while_details_stay_bounded():
    import sqlite3
    from contextlib import contextmanager
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE communication_outbox(outbox_id INT,event_id TEXT,channel TEXT,status TEXT,attempt_count INT,last_error TEXT,created_at TEXT,updated_at TEXT)')
    db.execute('CREATE TABLE telegram_outbox(id INT,sent_at TEXT,report_type TEXT,title TEXT,char_len INT,ok INT,channel TEXT)')
    for i in range(600):db.execute('INSERT INTO communication_outbox VALUES(?,?,?,?,?,?,?,?)',(i,'evt','telegram','suppressed',0,'dedupe',(NOW-timedelta(minutes=1)).isoformat(),NOW.isoformat()))
    db.execute('INSERT INTO communication_outbox VALUES(?,?,?,?,?,?,?,?)',(999,'older','telegram','sent',1,None,(NOW-timedelta(hours=2)).isoformat(),NOW.isoformat()))
    db.commit();before=db.total_changes
    class Reader:
        @contextmanager
        def snapshot(self):
            db.execute('PRAGMA query_only=1');db.execute('BEGIN')
            try:yield
            finally:db.rollback()
        def __call__(self,sql,params):
            return db.execute(sql.replace('%s','?'),tuple(v.isoformat() if isinstance(v,datetime) else v for v in params)).fetchall()
    out=P.project_outbox(Reader(),now=NOW)
    assert out['total']==601 and out['count']==500 and out['counts']['communication_outbox']['sent']==1
    assert out['coverage']['snapshot_consistent'] is True and out['coverage']['items_truncated'] is True
    assert not P.anomalies(out) and db.total_changes==before
    db.close()


def test_unknown_delivery_is_not_failed_or_proof_of_no_sends():
    def q(sql,params):
        if 'GROUP BY' in sql:return [('telegram_outbox','unknown',21)]
        if sql.startswith('SELECT id,'):return [(1,NOW,'fixture','fixture',1,None,'fixture')]
        return []
    out=P.project_outbox(q,now=NOW)
    assert out['items'][0]['state']=='unknown'
    assert not P.anomalies(out)


def test_live_query_adapter_has_read_only_repeatable_snapshot_and_rolls_back(monkeypatch):
    import sys,types
    sql=[]
    class Cursor:
        def execute(self,text,params=None):sql.append(text)
        def fetchall(self):return []
        def close(self):pass
    class Connection:
        rollbacks=0
        def cursor(self):return Cursor()
        def rollback(self):self.rollbacks+=1
    connection=Connection()
    monkeypatch.setitem(sys.modules,'db_adapter',types.SimpleNamespace(_get_conn=lambda:connection))
    out=P.project_outbox(P.db_query_with_timeout(3),now=NOW)
    assert out['total']==0 and out['coverage']['snapshot_consistent']
    assert 'BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY' in sql
    assert connection.rollbacks==2 and not any(s.startswith(('INSERT','UPDATE','DELETE')) for s in sql)
