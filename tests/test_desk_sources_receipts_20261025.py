"""Source clocks read a lane's own run receipt where the registry declares one (2026-10-25 operator screenshots).

Release train, CIO and holdings clocks said "Last successful run: not measured" while the lanes had
LaneRunReceipt files with ok_at. desk_sources read only n8n ledger rows and the (uninstalled) missed-run
monitor snapshot. A receipt counts only when the registry declares ``json_key`` / ``ok_at`` for that lane and the
receipt is a live, ok, exit-0 run of the same lane with an aware ok_at that is not in the future.
"""

import json
from datetime import datetime, timedelta, timezone

from scripts.lib.desk_sources import get_sources

NOW = datetime(2026, 10, 25, 18, tzinfo=timezone.utc)
OK_AT = (NOW - timedelta(hours=6)).isoformat()


def _setup(tmp_path, receipt=None, signal=None, name='train-0800_last.json'):
    lane = {'lane_id': 'train-0800', 'state': 'ACTIVE',
            'output_signal': signal or {'kind': 'json_key', 'path': f'data/runtime/{name}', 'key': 'ok_at'}}
    reg = tmp_path / 'registry.json'
    reg.write_text(json.dumps({'lanes': [lane, {'lane_id': 'mtime-only', 'state': 'ACTIVE',
                                                 'output_signal': {'kind': 'file_mtime', 'path': 'logs/x.log'}}]}))
    runtime = tmp_path / 'data/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    if receipt is not False:
        doc = {'schema': 'LaneRunReceipt@v1', 'lane_id': 'train-0800', 'mode': 'live', 'status': 'ok', 'exit': 0,
               'ok_at': OK_AT}
        doc.update(receipt or {})
        (runtime / name).write_text(json.dumps(doc))
    return get_sources({'lanes': 'train-0800,mtime-only'}, registry_path=reg, root=tmp_path, now=NOW)['writers']


def test_declared_receipt_is_success_evidence(tmp_path):
    train, mtime = _setup(tmp_path)
    assert train['last_success_at'] == OK_AT.replace('+00:00', 'Z')
    assert train['evidence_source'] == 'lane run receipt'
    assert train['reason'] is None
    # The read clock is not the freshness clock: last_success_at is six hours old while the
    # projection read the evidence now (2026-11-01).
    assert train['evidence_read_at'] == NOW.isoformat().replace('+00:00', 'Z')
    assert train['evidence_as_of'] == train['evidence_read_at']
    # A file mtime is never evidence.
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'logs/x.log').write_text('ran')
    assert mtime['last_success_at'] is None and mtime['reason']


def test_failed_foreign_dry_or_future_receipts_are_not_success(tmp_path):
    for bad in ({'status': 'failed'}, {'exit': 1}, {'lane_id': 'other'}, {'mode': 'dry_run'},
                {'schema': 'Other@v1'}, {'ok_at': (NOW + timedelta(minutes=5)).isoformat()},
                {'ok_at': '2026-10-25T12:00:00'}, {'ok_at': None}):
        train = _setup(tmp_path, bad)[0]
        assert train['last_success_at'] is None, bad
        assert train['reason'] == 'No successful run is recorded in the available execution evidence.'


def test_only_declared_runtime_paths_are_read(tmp_path):
    outside = {'kind': 'json_key', 'path': '../secrets.json', 'key': 'ok_at'}
    assert _setup(tmp_path, signal=outside)[0]['last_success_at'] is None
    other_key = {'kind': 'json_key', 'path': 'data/runtime/train-0800_last.json', 'key': 'as_of'}
    assert _setup(tmp_path, signal=other_key)[0]['last_success_at'] is None
    absent = {'kind': 'json_key', 'path': 'data/runtime/never-written_last.json', 'key': 'ok_at'}
    assert _setup(tmp_path, receipt=False, signal=absent)[0]['last_success_at'] is None


def test_symlinked_receipt_is_refused(tmp_path):
    real = tmp_path / 'elsewhere.json'
    real.write_text(json.dumps({'schema': 'LaneRunReceipt@v1', 'lane_id': 'train-0800', 'status': 'ok', 'exit': 0,
                                'ok_at': OK_AT}))
    _setup(tmp_path, receipt=False)
    link = tmp_path / 'data/runtime/train-0800_last.json'
    link.symlink_to(real)
    reg = tmp_path / 'registry.json'
    train = get_sources({'lanes': 'train-0800'}, registry_path=reg, root=tmp_path, now=NOW)['writers'][0]
    assert train['last_success_at'] is None
