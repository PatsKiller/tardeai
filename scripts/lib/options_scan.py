"""Options producer scan coordination. Advisory only; GET readers never create state.

A single worker owns chain snapshots and proposal projection. SQLite transactions
make POST requests idempotent and retain each run, including failures and resumes.
No research/thesis state is stored here; the CIO spine remains authoritative.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
import zlib
from collections.abc import Mapping
from functools import lru_cache
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA = "OptionsScan@v1"
PROFILES = {"full", "priority"}
PRIORITY_LANES = {"holdings", "watchlist", "watchlist_buy_strong_buy", "reentry", "entry_state"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(root: Path) -> dict:
    path = root / "config" / "options_scan.json"
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"enabled": False, "status": "CONFIG_REQUIRED"}
    try:
        rate = float(cfg.get("provider_requests_per_minute") or 0)
        valid = math.isfinite(rate) and rate > 0 and int(cfg.get("max_requests_per_slice", 0)) > 0
    except (ValueError, TypeError):
        valid = False
    if not cfg.get("capacity_approval") or not valid:
        cfg["enabled"] = False
    return cfg


def due_profiles(now: datetime, *, open_at: datetime | None, close_at: datetime | None) -> list[tuple[str, str]]:
    """Official exchange bounds only: unknown/closed calendar cannot schedule work."""
    if open_at is None or close_at is None or not open_at + timedelta(minutes=5) <= now < close_at:
        return []
    date = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    bucket = int((now - open_at - timedelta(minutes=5)).total_seconds() // 900)
    return [("full", f"daily:{date}"), ("priority", f"priority:{date}:{bucket}")]


def chain_receipt(chain: dict) -> dict:
    coverage = chain.get("request_coverage") or {}
    exps = [e for e in chain.get("expirations", []) if 7 <= int(e.get("dte") or 0) <= 365]
    status = "COMPLETE" if (chain.get("status") == "ok" and coverage.get("all_strikes") is True
        and coverage.get("both_sides") is True and coverage.get("status") == "COMPLETE"
        and coverage.get("min_dte") == 7 and coverage.get("max_dte") == 365 and exps) else "PARTIAL"
    if chain.get("status") not in {"ok", "empty"}:
        status = "ERROR"
    return {"status": status, "fetched_at": chain.get("fetched_at"),
            "snapshot_id": hashlib.sha256(json.dumps(chain, sort_keys=True, default=str).encode()).hexdigest()[:24],
            "expiration_count": len(exps), "contract_count": sum(len(e.get("strikes", [])) for e in exps),
            "request_coverage": coverage,
            "reason": None if status == "COMPLETE" else str(chain.get("status") or "missing coverage proof")}


class ScanStore:
    def __init__(self, state_dir: Path):
        self.path = Path(state_dir) / "options_scan.sqlite3"

    @contextmanager
    def connection(self, *, write: bool = False):
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=10)
            conn.executescript('''
              CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, profile TEXT NOT NULL, request_key TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}');
              CREATE TABLE IF NOT EXISTS requests (request_key TEXT PRIMARY KEY, run_id TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS snapshots (
                symbol TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, chain TEXT NOT NULL, receipt TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS inputs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS results (run_id TEXT NOT NULL, symbol TEXT NOT NULL, receipt TEXT NOT NULL,
                                                 PRIMARY KEY(run_id,symbol));
              CREATE TABLE IF NOT EXISTS snapshot_versions (id TEXT PRIMARY KEY, chain BLOB NOT NULL, receipt TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, at TEXT NOT NULL, event TEXT NOT NULL, detail TEXT);
            ''')
            conn.execute("BEGIN IMMEDIATE")
        else:
            conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            if write:
                conn.commit()
        except BaseException:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def row(raw):
        if raw is None:
            return None
        value = dict(raw)
        value["payload"] = json.loads(value["payload"])
        return value

    def request(self, profile: str, request_key: str, *, now: str | None = None) -> dict:
        if profile not in PROFILES or not request_key or len(request_key) > 160:
            raise ValueError("profile must be full or priority; request key required (max 160)")
        at = now or utcnow()
        key = f"{profile}:{request_key}"
        run_id = hashlib.sha256(key.encode()).hexdigest()[:24]
        with self.connection(write=True) as db:
            old = db.execute("SELECT r.* FROM runs r LEFT JOIN requests q ON q.run_id=r.id WHERE r.request_key=? OR q.request_key=? LIMIT 1", (key, key)).fetchone()
            if old is None:
                # Coalesce concurrent clicks and timer ticks for the same unfinished work.
                old = db.execute("SELECT * FROM runs WHERE profile=? AND (status IN ('QUEUED','RUNNING') OR json_extract(payload,'$.projection_state')='PENDING') ORDER BY created_at LIMIT 1",
                                 (profile,)).fetchone()
            if old is not None:
                db.execute("INSERT OR IGNORE INTO requests VALUES (?,?)", (key, old["id"]))
                return {**self.row(old), "deduplicated": True}
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (run_id, profile, key, "QUEUED", at, at, '{}'))
            db.execute("INSERT INTO requests VALUES (?,?)", (key, run_id))
            db.execute("INSERT INTO events(run_id,at,event) VALUES (?,?,?)", (run_id, at, "REQUESTED"))
            return self.row(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def update(self, run_id: str, status: str, payload: dict, *, event: str = "CHECKPOINT") -> None:
        at = utcnow()
        with self.connection(write=True) as db:
            input_keys = {'inventory', 'holdings', 'holdings_meta', 'convictions', 'source_receipts', 'discovery'}
            if 'inventory' in payload:
                db.execute("INSERT OR IGNORE INTO inputs VALUES (?,?)", (run_id, json.dumps(
                    {k: v for k, v in payload.items() if k in input_keys}, default=str)))
            progress = {k: v for k, v in payload.items() if k not in input_keys and k != 'results'}
            progress['completed_count'] = len(payload.get('results', {}))
            db.execute("UPDATE runs SET status=?, updated_at=?, payload=? WHERE id=?",
                       (status, at, json.dumps(progress, default=str), run_id))
            db.execute("INSERT INTO events(run_id,at,event,detail) VALUES (?,?,?,?)",
                       (run_id, at, event, json.dumps({"status": status, "completed": len(payload.get('results', {}))})))

    def save_result(self, run_id: str, symbol: str, receipt: dict):
        with self.connection(write=True) as db:
            db.execute("INSERT OR IGNORE INTO results VALUES (?,?,?)", (run_id, symbol, json.dumps(receipt)))

    def runs(self, *, active: bool = False, summaries: bool = False) -> list[dict]:
        if not self.path.exists():
            return []
        with self.connection() as db:
            where = "WHERE status IN ('QUEUED','RUNNING') OR json_extract(payload,'$.projection_state')='PENDING'" if active else ""
            runs = [self.row(r) for r in db.execute(
                f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT 50")]
            if not summaries:
                for run in runs:
                    inputs = db.execute("SELECT payload FROM inputs WHERE run_id=?", (run['id'],)).fetchone()
                    if inputs:
                        run['payload'].update(json.loads(inputs['payload']))
                    run['payload']['results'] = {r['symbol']: json.loads(r['receipt']) for r in db.execute(
                        "SELECT symbol,receipt FROM results WHERE run_id=?", (run['id'],))}
            return runs

    def latest_full_discovery(self) -> dict | None:
        if not self.path.exists():
            return None
        with self.connection() as db:
            row = db.execute("SELECT i.payload FROM inputs i JOIN runs r ON r.id=i.run_id WHERE r.profile='full' ORDER BY r.created_at DESC LIMIT 1").fetchone()
            return json.loads(row['payload']).get('discovery') if row else None

    def latest_receipts(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        with self.connection() as db:
            return {r['symbol']: {"receipt": json.loads(r['receipt'])}
                    for r in db.execute("SELECT symbol,receipt FROM snapshots")}

    def snapshots(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        with self.connection() as db:
            return {r['symbol']: {"chain": json.loads(r['chain']), "receipt": json.loads(r['receipt'])}
                    for r in db.execute("SELECT * FROM snapshots")}

    def snapshot(self, snapshot_id: str) -> dict:
        if not self.path.exists():
            return {}
        with self.connection() as db:
            row = db.execute("SELECT chain,receipt FROM snapshot_versions WHERE id=?", (snapshot_id,)).fetchone()
            return {'chain': json.loads(zlib.decompress(row['chain'])), 'receipt': json.loads(row['receipt'])} if row else {}

    def save_snapshot(self, symbol: str, chain: dict, receipt: dict):
        data = json.dumps(chain, sort_keys=True, default=str)
        receipt.setdefault('snapshot_id', hashlib.sha256(data.encode()).hexdigest()[:24])
        with self.connection(write=True) as db:
            db.execute("INSERT OR IGNORE INTO snapshot_versions VALUES (?,?,?)",
                       (receipt['snapshot_id'], zlib.compress(data.encode()), json.dumps(receipt)))
            db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",
                       (symbol, utcnow(), data, json.dumps(receipt)))


class CapturedChains(Mapping):
    """Read immutable chain versions lazily, bounding resident full-chain memory."""
    def __init__(self, store: ScanStore, receipts: dict):
        self.store, self.receipts = store, receipts
        self._load = lru_cache(maxsize=4)(self._read)

    def _read(self, symbol):
        receipt = self.receipts[symbol]
        chain = self.store.snapshot(receipt.get('snapshot_id')).get('chain', {}) if receipt.get('snapshot_id') else {}
        return {**chain, 'status': chain.get('status', 'pending'), 'snapshot_id': receipt.get('snapshot_id')}

    def __getitem__(self, symbol):
        if symbol not in self.receipts:
            raise KeyError(symbol)
        return self._load(symbol)

    def __iter__(self):
        return iter(self.receipts)

    def __len__(self):
        return len(self.receipts)


def fair_order(rows: list[dict], snapshots: dict) -> list[dict]:
    """Mandatory membership first, oldest successful refresh next, stable identity last."""
    return sorted(rows, key=lambda row: (
        not bool(set(row.get("source_lanes", [])).intersection(PRIORITY_LANES)),
        (snapshots.get(row['symbol'], {}).get('receipt') or {}).get('fetched_at') or '', row['symbol']))


def run_slice(store: ScanStore, run: dict, *, collect, fetch_chain, max_requests: int,
              min_interval: float = 0, clock=time.monotonic, sleep=time.sleep,
              now: datetime | None = None, max_snapshot_age_seconds: float = 900) -> dict:
    """Bounded resumable chain pass. Worker must hold the process lock.

    Injected providers make replay/test completely offline. Every result is checkpointed
    before the next request. Failed names remain visible and retry on the next scan.
    """
    payload = dict(run['payload'])
    if not payload.get('inventory'):
        inputs = collect(run['profile'])
        rows = inputs['inventory']
        if run['profile'] == 'priority':
            rows = [r for r in rows if set(r.get('source_lanes', [])).intersection(PRIORITY_LANES)
                    or r.get('shortlisted')]
        payload.update(inputs)
        payload['inventory'] = fair_order(rows, store.latest_receipts())
        payload['results'] = {}
        payload['request_count'] = 0
        payload['response_bytes'] = 0
        payload['inventory_count'] = len(payload['inventory'])
        store.update(run['id'], 'RUNNING', payload, event='STARTED')
    results = payload.setdefault('results', {})
    snapshots = store.latest_receipts()
    current_time = now or datetime.now(timezone.utc)
    requests = 0
    last_request = None
    for row in payload['inventory']:
        symbol = row['symbol']
        if symbol in results:
            continue
        snapshot = snapshots.get(symbol) or {}
        prior = snapshot.get('receipt') or {}
        try:
            fetched = datetime.fromisoformat(str(prior.get('fetched_at')).replace('Z', '+00:00'))
            age = (current_time - fetched).total_seconds()
        except (ValueError, TypeError):
            age = float('inf')
        if prior.get('status') == 'COMPLETE' and 0 <= age < max_snapshot_age_seconds:
            results[symbol] = {**prior, 'reused': True}
            store.save_result(run['id'], symbol, results[symbol])
            payload['reused_count'] = payload.get('reused_count', 0) + 1
            continue
        if requests >= max_requests:
            break
        if row.get('status') in {'POLICY_EXCLUDED', 'UNSUPPORTED'}:
            results[symbol] = {'status': row['status'], 'reason': 'inventory exclusion'}
            store.save_result(run['id'], symbol, results[symbol])
            continue
        if last_request is not None:
            sleep(max(0, min_interval - (clock() - last_request)))
        last_request = clock()
        started = clock()
        try:
            chain = fetch_chain(symbol)
            receipt = chain_receipt(chain)
        except Exception as exc:
            # Never persist exception text: HTTP libraries can include credential URLs.
            chain = {'status': 'error', 'error_type': type(exc).__name__}
            receipt = {'status': 'ERROR', 'reason': type(exc).__name__}
        receipt['elapsed_seconds'] = round(clock() - started, 3)
        size = len(json.dumps(chain, default=str).encode())
        receipt['response_bytes'] = size
        results[symbol] = receipt
        store.save_snapshot(symbol, chain, receipt)
        store.save_result(run['id'], symbol, receipt)
        requests += 1
        payload['request_count'] += 1
        payload['response_bytes'] += size
        store.update(run['id'], 'RUNNING', payload)
        if receipt.get('reason') in {'FinvizRateLimited', 'TooManyRequests', 'rate_limited'}:
            break
    done = len(results) == len(payload['inventory'])
    sources_ok = all(r.get('status') == 'COMPLETE' for r in payload.get('source_receipts', {}).values())
    status = ('COMPLETE' if sources_ok and all(r.get('status') in {'COMPLETE', 'POLICY_EXCLUDED', 'UNSUPPORTED'}
                                             for r in results.values()) else 'PARTIAL') if done else 'RUNNING'
    # Derive counters from durable per-symbol checkpoints, including crash recovery.
    payload['request_count'] = sum('response_bytes' in r and not r.get('reused') for r in results.values())
    payload['response_bytes'] = sum(r.get('response_bytes', 0) for r in results.values() if not r.get('reused'))
    payload['reused_count'] = sum(bool(r.get('reused')) for r in results.values())
    if done:
        payload['projection_state'] = 'PENDING'
    payload['chain_complete_count'] = sum(r.get('status') == 'COMPLETE' for r in results.values())
    store.update(run['id'], status, payload, event='FINISHED' if done else 'CHECKPOINT')
    return {**run, 'status': status, 'payload': payload}


def scan_coverage(snapshot: dict, store: ScanStore) -> dict:
    """Expose in-progress membership without provider work or mutating the cache."""
    from .options_universe_census import build_coverage
    runs = store.runs(active=True)
    active = next((r for r in runs if r['payload'].get('inventory')), None)
    if not active:
        return snapshot
    payload = active['payload']
    receipts = {s: v['receipt'] for s, v in store.latest_receipts().items()}
    receipts.update(payload.get('results', {}))
    coverage = build_coverage(holdings=payload['holdings_meta'].get('_inventory_holdings', payload['holdings']),
        convictions=payload['convictions'], proposals=snapshot.get('proposals', []), drops=[],
        chains=receipts, source_receipts=payload['source_receipts'])
    current_symbols = {r['symbol'] for r in payload['inventory']}
    for row in coverage['rows']:
        row['in_current_run'] = row['symbol'] in current_symbols
        row['current_run_status'] = payload.get('results', {}).get(row['symbol'], {}).get('status', 'PENDING')
    coverage['status'] = active['status']
    return {**snapshot, 'coverage': coverage, 'scan_run_id': active['id'], 'generated_at': active['updated_at']}


def coverage_page(snapshot: dict, *, offset: int = 0, limit: int = 100, symbol: str = '') -> dict:
    coverage = snapshot.get('coverage') or {}
    rows = coverage.get('rows') or []
    if symbol:
        rows = [r for r in rows if symbol.upper() in r.get('symbol', '')]
    offset, limit = max(0, int(offset)), min(250, max(1, int(limit)))
    return {**coverage, 'rows': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'limit': limit,
            'run_id': snapshot.get('scan_run_id'), 'as_of': snapshot.get('generated_at'),
            'status': coverage.get('status', 'UNAVAILABLE')}


def request_missing_research(rows: list[dict], *, pending: set[str], limit: int, request, run_id: str) -> list[dict]:
    """Use the existing symbol-thesis acquisition queue, once per security, within its budget."""
    candidates = [r for r in rows if r.get('research_status') == 'research_required'
                  and r.get('symbol') not in pending and r.get('chain', {}).get('status') == 'COMPLETE']
    candidates.sort(key=lambda r: (not bool(set(r.get('source_lanes', [])).intersection(PRIORITY_LANES)),
                                   str(r.get('research_as_of') or r.get('evaluated_at') or ''), r['symbol']))
    receipts = []
    for row in candidates[:max(0, int(limit))]:
        result = request(row['symbol'], reason=f"Options scan {run_id}: shared thesis required before expression ranking",
                         source='options_scan')
        receipts.append({'symbol': row['symbol'], 'request': result, 'run_id': run_id,
                         'chain_snapshot_id': row['chain'].get('snapshot_id')})
        pending.add(row['symbol'])
    return receipts
