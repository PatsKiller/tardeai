"""Source clocks must distinguish registry intent, run receipts and source age."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.desk_sources import get_sources
from scripts.lib.lane_registry import N8N_LEDGER_REL

NOW = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)


def registry(tmp_path, rows=None):
    path = tmp_path / 'registry.json'
    path.write_text(json.dumps({'lanes': rows if rows is not None else [
        {'lane_id': 'posture', 'state': 'ACTIVE'}, {'lane_id': 'options', 'state': 'PAUSED'},
        {'lane_id': 'cash', 'state': 'RETIRED'}, {'lane_id': 'unscheduled', 'state': 'NEVER_SCHEDULED'}]}))
    return path


def result(tmp_path, lanes='posture', **kwargs):
    return get_sources({'lanes': lanes}, registry_path=registry(tmp_path), root=tmp_path, now=NOW, **kwargs)


def ledger(tmp_path, runs):
    path = tmp_path / N8N_LEDGER_REL
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE runs(run_id,lane_id,mode,state,finished_at,exit_code,receipt_json)')
        for changes in runs:
            row = {'run_id': 'r1', 'lane_id': 'posture', 'mode': 'live', 'state': 'RUN_DONE',
                   'finished_at': (NOW - timedelta(minutes=30)).isoformat(), 'exit_code': 0}
            row.update({k: v for k, v in changes.items() if k != 'receipt'})
            receipt = {'schema': 'RunReceipt@v1', **row}
            receipt.update(changes.get('receipt', {}))
            conn.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)', (*row.values(), json.dumps(receipt)))
    return path


def monitor(tmp_path, **changes):
    path = tmp_path / 'data/runtime/cron_outage_watchdog_latest.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {'schema': 'CronOutageWatchdog@v1', 'mode': 'monitor', 'observed_at': NOW.isoformat(),
           'rows': [{'lane_id': 'posture', 'last_success_at': (NOW - timedelta(hours=1)).isoformat()}]}
    doc.update(changes)
    path.write_text(json.dumps(doc))
    return path


def test_states_are_registry_intent_and_missing_evidence_stays_unknown(tmp_path):
    rows = result(tmp_path, 'posture,options,cash,unscheduled,missing')['writers']
    assert [r['state'] for r in rows] == ['ACTIVE', 'PAUSED', 'RETIRED', 'NONE', 'NONE']
    assert all(row['last_success_at'] is None and row['reason'] for row in rows)
    assert not (tmp_path / N8N_LEDGER_REL).exists()  # A GET cannot create a DB.


def test_registry_unavailable_cannot_mean_no_writer(tmp_path):
    rows = get_sources({'lanes': 'posture'}, root=tmp_path, registry_path=tmp_path / 'absent', now=NOW)['writers']
    assert rows[0]['state'] is None
    assert 'registry' in rows[0]['reason']


def test_receipt_required_and_failure_does_not_erase_last_success(tmp_path):
    ledger(tmp_path, [{}, {'run_id': 'failed', 'state': 'RUN_FAILED', 'exit_code': 1, 'finished_at': NOW.isoformat()},
                      {'run_id': 'bad-proof', 'finished_at': NOW.isoformat(), 'receipt': {'run_id': 'other'}}])
    row = result(tmp_path)['writers'][0]
    assert row['last_success_at'] == '2026-10-24T23:30:00Z'
    assert row['evidence_source'] == 'n8n run receipt'


@pytest.mark.parametrize('changes', [
    {'mode': 'dry_run'}, {'mode': 'shadow'}, {'exit_code': 1}, {'state': 'RUN_FAILED'},
    {'receipt': {'schema': 'invented'}}, {'receipt': {'lock_skipped': True}},
    {'receipt': {'timed_out': True}}, {'receipt': {'exit_code': 1}},
    {'finished_at': (NOW + timedelta(seconds=1)).isoformat()},
    {'finished_at': '2026-10-24T23:30:00'},
])
def test_invalid_execution_is_never_success(tmp_path, changes):
    ledger(tmp_path, [changes])
    assert result(tmp_path)['writers'][0]['last_success_at'] is None


def test_monitor_is_existing_success_evidence_not_file_mtime(tmp_path):
    monitor(tmp_path)
    row = result(tmp_path)['writers'][0]
    assert row['last_success_at'] == '2026-10-24T23:00:00Z'
    assert row['evidence_source'] == 'missed-run monitor'


@pytest.mark.parametrize('changes', [{'mode': 'dry_run'}, {'observed_at': '2026-10-26T00:00:00Z'},
                                    {'schema': 'other'}, {'rows': None}, {'rows': [{'lane_id': 'posture', 'last_success_at': '2026-10-26T00:00:00Z'}]}])
def test_bad_monitor_snapshot_cannot_prove_success(tmp_path, changes):
    monitor(tmp_path, **changes)
    assert result(tmp_path)['writers'][0]['last_success_at'] is None


def test_newer_monitor_success_wins_without_claiming_scheduler_is_healthy(tmp_path):
    ledger(tmp_path, [{'finished_at': '2026-10-24T22:00:00Z'}])
    monitor(tmp_path)
    row = result(tmp_path)['writers'][0]
    assert row['last_success_at'] == '2026-10-24T23:00:00Z'
    assert 'healthy' not in json.dumps(row)


def test_no_execution_evidence_attaches_to_unregistered_lane(tmp_path):
    ledger(tmp_path, [{'lane_id': 'missing'}])
    monitor(tmp_path, rows=[{'lane_id': 'missing', 'last_success_at': NOW.isoformat()}])
    assert result(tmp_path, 'missing')['writers'][0]['last_success_at'] is None


@pytest.mark.parametrize('lanes', ['../.env', 'x/y', ',posture', 'posture,' * 1000, ','.join(f'lane-{n}' for n in range(25))])
def test_bounded_ids_cannot_be_paths(tmp_path, lanes):
    with pytest.raises(ValueError):
        result(tmp_path, lanes)


def test_large_source_and_corrupt_ledger_degrade_without_writing(tmp_path):
    path = tmp_path / N8N_LEDGER_REL
    path.parent.mkdir(parents=True)
    path.write_bytes(b'not sqlite')
    row = result(tmp_path)['writers'][0]
    assert row['last_success_at'] is None
    assert path.read_bytes() == b'not sqlite'


def test_duplicate_ids_deduplicate_and_payload_stays_small(tmp_path):
    response = result(tmp_path, 'posture,posture')
    assert len(response['writers']) == 1
    assert len(json.dumps(response)) < 1024


def test_oversized_receipt_is_not_materialized_or_treated_as_success(tmp_path):
    path = ledger(tmp_path, [{}])
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE runs SET receipt_json=?', ('x' * 65537,))
    assert result(tmp_path)['writers'][0]['last_success_at'] is None
