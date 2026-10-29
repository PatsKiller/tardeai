"""Bounded, read-only source clocks for restored desks.

Registry intent and successful execution are separate facts. Never collect host
state, run a producer, infer success from mtime, or create a missing ledger.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from scripts.lib import lane_registry
from scripts.lib.cron_outage_watchdog import instant, iso
from scripts.lib.scheduler_operations import receipt_proves_run

MAX_LANES = 24
MAX_HISTORY = 50


def _read_object(path: Path, limit: int) -> dict:
    try:
        with path.open('rb') as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            return {}
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def _successful_runs(path: Path, ids: list[str], now: datetime) -> dict:
    """At most 50 completed live runs per requested lane, in a read-only DB."""
    if not path.is_file():
        return {}
    found = {}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.25)) as conn:
            conn.row_factory = sqlite3.Row
            for lane_id in ids:
                rows = conn.execute(
                    'SELECT run_id,lane_id,mode,state,finished_at,exit_code, '
                    'CASE WHEN length(receipt_json)<=65536 THEN receipt_json ELSE NULL END AS receipt_json FROM runs '
                    'WHERE lane_id=? AND mode=? AND state=? AND exit_code=0 '
                    'ORDER BY finished_at DESC LIMIT ?', (lane_id, 'live', 'RUN_DONE', MAX_HISTORY),
                )
                for row in rows:
                    run = dict(row)
                    raw = run.pop('receipt_json') or ''
                    if len(raw) > 65536:
                        continue
                    try:
                        run['receipt'] = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    if instant(run.get('finished_at')) and receipt_proves_run(run, now):
                        found[lane_id] = iso(instant(run['finished_at']))
                        break
    except (sqlite3.Error, OSError):
        # Missing/unreadable evidence remains unknown, never healthy.
        return {}
    return found


RECEIPT_SCHEMAS = ('LaneRunReceipt@v1', 'LaneRunReceipt@v2')
RECEIPT_MAX_BYTES = 256 * 1024


def _receipt_success(root: Path, lane: dict, now: datetime) -> str | None:
    """A lane's own run receipt (scripts/lib/lane_last_receipt.py), only where the registry declares it.

    The registry ``output_signal`` must be ``json_key`` on ``ok_at`` under ``data/runtime/``. The receipt must name
    this lane, be a live run that exited 0 with status ok, and carry an aware ``ok_at`` that is not in the future.
    ``ok_at`` only advances on a successful real run (a dry run never writes it); a file mtime is never used.
    """
    signal = lane.get('output_signal') if isinstance(lane.get('output_signal'), dict) else {}
    rel = signal.get('path')
    if signal.get('kind') != 'json_key' or signal.get('key') != 'ok_at' or not isinstance(rel, str):
        return None
    if not re.fullmatch(r'data/runtime/[A-Za-z0-9][A-Za-z0-9._-]{0,160}\.json', rel):
        return None
    path = root / rel
    try:
        if path.is_symlink() or not path.is_file():
            return None
    except OSError:
        return None
    receipt = _read_object(path, RECEIPT_MAX_BYTES)
    if (receipt.get('schema') not in RECEIPT_SCHEMAS or receipt.get('lane_id') != lane.get('lane_id')
            or receipt.get('status') != 'ok' or receipt.get('exit') != 0 or receipt.get('mode', 'live') != 'live'):
        return None
    at = instant(receipt.get('ok_at'))
    return iso(at) if at is not None and at <= now else None


def get_sources(query=None, *, registry_path=None, root=None, now=None) -> dict:
    """GET projection; only a caller's lane IDs are returned (max 24, no paths)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('An aware clock is required')
    raw = (query or {}).get('lanes') or ''
    if isinstance(raw, list):
        raw = raw[0] if raw else ''
    if not isinstance(raw, str) or len(raw) > MAX_LANES * 129:
        raise ValueError('lanes must be a comma-separated list')
    ids = list(dict.fromkeys(raw.split(','))) if raw else []
    if len(ids) > MAX_LANES or any(not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}', item) for item in ids):
        raise ValueError('Request at most 24 registered lane IDs')
    root = Path(root) if root is not None else lane_registry.state_root()
    registry = _read_object(Path(registry_path or lane_registry.REGISTRY_PATH), 8 * 1024 * 1024)
    rows = registry.get('lanes')
    registry_ok = isinstance(rows, list)
    lanes = {row.get('lane_id'): row for row in rows or [] if isinstance(row, dict)} if registry_ok else {}
    snapshot = _read_object(root / 'data/runtime/cron_outage_watchdog_latest.json', 2 * 1024 * 1024)
    observed = instant(snapshot.get('observed_at'))
    monitor_ok = (snapshot.get('schema') == 'CronOutageWatchdog@v1' and snapshot.get('mode') == 'monitor'
                  and observed is not None and observed <= now)
    monitor_rows = snapshot.get('rows')
    monitor = {row.get('lane_id'): row for row in monitor_rows if isinstance(row, dict)} if monitor_ok and isinstance(monitor_rows, list) else {}
    successes = _successful_runs(root / lane_registry.N8N_LEDGER_REL, [item for item in ids if item in lanes], now)
    result = []
    for lane_id in ids:
        row = lanes.get(lane_id)
        state = row.get('state') if row else ('NONE' if registry_ok else None)
        reason = None
        if state == 'NEVER_SCHEDULED':
            state = 'NONE'
        if state not in {'ACTIVE', 'PAUSED', 'RETIRED', 'NONE'}:
            state = None
            reason = 'Writer state could not be read from the lane registry.'
        elif state == 'NONE':
            reason = 'No scheduled writer is registered for this source.'
        last = successes.get(lane_id)
        evidence_source = 'n8n run receipt' if last else None
        evidence_as_of = iso(now) if last else None
        receipt = _receipt_success(root, row, now) if row else None
        if receipt and (last is None or instant(receipt) > instant(last)):
            last = receipt
            evidence_source = 'lane run receipt'
            evidence_as_of = iso(now)
        measured = instant(monitor.get(lane_id, {}).get('last_success_at')) if row else None
        if measured and measured <= observed and (last is None or measured > instant(last)):
            last = iso(measured)
            evidence_source = 'missed-run monitor'
            evidence_as_of = iso(observed)
        result.append({'lane_id': lane_id, 'state': state, 'last_success_at': last,
                       'evidence_source': evidence_source, 'evidence_as_of': evidence_as_of,
                       'reason': reason or (None if last else 'No successful run is recorded in the available execution evidence.')})
    return {'observed_at': iso(now), 'writers': result,
            'scope': 'Registry state and execution evidence; source freshness is a separate clock.'}
