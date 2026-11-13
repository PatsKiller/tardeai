"""LQ-20261107-2595 phase 2 (b): the Hermes research projection as an indexed Postgres table.

``data/cio/hermes_research_projection.json`` is one 143 MB JSON object (``_save_projection`` writes it with
``json.dumps(indent=2)``). Server code parses it whole per plan and per symbol, up to 24 times per CIO desk
request (DSN-20261112-PRECOMPUTE-CACHE §4.3). This module ingests it into Postgres once per change and gives
server code indexed point reads instead.

Storage choice. DSN §4.3 sketches two tables, ``hermes_projection_plan`` (key plan id) and
``hermes_projection_symbol`` (key symbol). This module uses ONE table, ``hermes_projection_entry``, keyed by
(``map``, ``entry_key``), where ``map`` is one of the projection's four maps. Reasons:

* The file has four maps, not two, and every reader in ``cio_hermes_research`` reads one of the four by its own
  key (research id, plan id, fingerprint). One row per map entry mirrors the source exactly, so the ingest is a
  plain keyed upsert and keyed-product eviction (DSN §4.5) is one ``DELETE ... WHERE ingest_seq <> current``.
* A per-symbol table would need a derived aggregation (symbol → its research rows) that must be recomputed and
  kept consistent with the entries; the plan and symbol access paths are instead served by the indexes on
  ``plan_id`` and ``upper(symbol)`` over the same rows, so there is one copy of each entry and nothing to drift.

``hermes_projection_meta`` is a single row that records which source file was ingested (path, mtime, size,
sha256), the projection's own ``updated_ts``, the ingest sequence and per-map counts. Entries and meta change in
one transaction, so a reader never sees half an ingest.

The streaming reader is stdlib only. It never holds the whole document: it reads fixed-size chunks, decodes UTF-8
incrementally, and calls ``json.JSONDecoder.raw_decode`` on a sliding buffer one map entry at a time, carrying the
unconsumed tail of the buffer across chunk boundaries.

CLI: ``python -m scripts.lib.cc_products.hermes_projection --dry-run [--path P]`` prints the receipt JSON.
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import math
import os
import re
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

MAPS = ("by_research_id", "by_plan_id", "by_fingerprint_open", "by_fingerprint_completed")
DEFAULT_PATH = Path(os.environ.get("HERMES_PROJECTION_PATH", "data/cio/hermes_research_projection.json"))
DEFAULT_DSN = os.environ.get("CC_PRODUCTS_PG_DSN", "host=/var/run/postgresql dbname=trade_ai")
LOCK_KEY = "hermes.projection|global"  # same key shape as store_pg.try_lock(product_id, scope_key)
BATCH_SIZE = 500
INGEST_RLIMIT_AS_BYTES = 1536 * 1024 * 1024  # DSN §4.4: 1.5 GB for the §4.3 ingest jobs
MAX_VALUE_CHARS = 64 * 1024 * 1024  # a single entry larger than this is treated as a corrupt file

_WS = re.compile(r"[ \t\n\r]*")
# raw_decode accepts "1" out of a truncated "1.5" or "1e9", so a value followed only by number characters up to the
# buffer end is not known to be complete until more input arrives.
_NUM_TAIL = re.compile(r"[0-9.eE+\-]*")
_DECODER = json.JSONDecoder()


class ProjectionFormatError(ValueError):
    """The file is not a JSON object of the expected shape."""


# ── streaming reader ─────────────────────────────────────────────────────────


class ProjectionReader:
    """Yield ``(map_name, key, value)`` for the four maps of a projection file without loading it whole.

    After ``entries()`` is exhausted: ``top`` holds the top-level non-map members (``updated_ts``),
    ``maps_seen`` lists the maps present (empty ones included) and ``bytes_read`` the file size read.
    """

    def __init__(self, fh, chunk_size: int = 1 << 20, hasher=None, max_value_chars: int = MAX_VALUE_CHARS):
        if chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        self._fh = fh
        self._chunk = int(chunk_size)
        self._dec = codecs.getincrementaldecoder("utf-8")()
        self._hasher = hasher
        self._max = int(max_value_chars)
        self._buf = ""
        self._pos = 0
        self._eof = False
        self.bytes_read = 0
        self.top: dict[str, Any] = {}
        self.maps_seen: list[str] = []

    # buffer management
    def _fill(self, n: Optional[int] = None) -> None:
        data = self._fh.read(n or self._chunk)
        if data:
            self.bytes_read += len(data)
            if self._hasher is not None:
                self._hasher.update(data)
            text = self._dec.decode(data)
        else:
            self._eof = True
            text = self._dec.decode(b"", final=True)
        # Carry the unconsumed tail across the chunk boundary; drop only what was consumed.
        self._buf = self._buf[self._pos :] + text
        self._pos = 0

    def _skip_ws(self) -> str:
        """Skip JSON whitespace; return the next char without consuming it, or '' at EOF."""
        while True:
            self._pos = _WS.match(self._buf, self._pos).end()
            if self._pos < len(self._buf):
                return self._buf[self._pos]
            if self._eof:
                return ""
            self._fill()

    def _expect(self, ch: str) -> None:
        got = self._skip_ws()
        if got != ch:
            raise ProjectionFormatError(f"expected {ch!r}, got {got!r} near byte {self.bytes_read}")
        self._pos += 1

    def _decode(self) -> Any:
        """Decode one JSON value at the cursor, reading more input until it is complete."""
        self._skip_ws()
        while True:
            try:
                val, end = _DECODER.raw_decode(self._buf, self._pos)
                # A value that ends at the buffer end (or before only number characters) may be truncated.
                if self._eof or _NUM_TAIL.match(self._buf, end).end() < len(self._buf):
                    self._pos = end
                    return val
            except json.JSONDecodeError:
                if self._eof:
                    raise
            pending = len(self._buf) - self._pos
            if pending > self._max:
                raise ProjectionFormatError(f"value larger than {self._max} chars near byte {self.bytes_read}")
            # Grow geometrically so a value much larger than the chunk is re-scanned O(log n) times, not O(n/chunk).
            self._fill(max(self._chunk, pending))

    def _decode_key(self) -> str:
        if self._skip_ws() != '"':
            raise ProjectionFormatError(f"expected a string key near byte {self.bytes_read}")
        return self._decode()

    def entries(self) -> Iterator[tuple[str, str, Any]]:
        self._expect("{")
        if self._skip_ws() == "}":
            self._pos += 1
        else:
            while True:
                name = self._decode_key()
                self._expect(":")
                if name in MAPS and self._skip_ws() == "{":
                    self._pos += 1
                    self.maps_seen.append(name)
                    if self._skip_ws() == "}":
                        self._pos += 1
                    else:
                        while True:
                            key = self._decode_key()
                            self._expect(":")
                            yield name, key, self._decode()
                            c = self._skip_ws()
                            self._pos += 1
                            if c == "}":
                                break
                            if c != ",":
                                raise ProjectionFormatError(f"expected ',' or '}}' in {name}, got {c!r}")
                else:
                    self.top[name] = self._decode()
                c = self._skip_ws()
                self._pos += 1
                if c == "}":
                    break
                if c != ",":
                    raise ProjectionFormatError(f"expected ',' or '}}' at top level, got {c!r}")
        if self._skip_ws() != "":
            raise ProjectionFormatError("trailing data after the top-level object")


def iter_entries(path: Path | str, chunk_size: int = 1 << 20) -> Iterator[tuple[str, str, Any]]:
    with open(path, "rb") as fh:
        yield from ProjectionReader(fh, chunk_size).entries()


# ── helpers ──────────────────────────────────────────────────────────────────


def _peak_rss_kb() -> Optional[int]:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1])
    except Exception:  # noqa: BLE001
        return None
    return None


def _sha256_stream(fh, chunk_size: int) -> str:
    h = hashlib.sha256()
    while True:
        b = fh.read(chunk_size)
        if not b:
            return h.hexdigest()
        h.update(b)


def _sanitize(v: Any) -> Any:
    """jsonb rejects NUL in strings and non-finite numbers; map them to U+FFFD and null."""
    if isinstance(v, str):
        return v.replace("\x00", "�")
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {_sanitize(k): _sanitize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_sanitize(x) for x in v]
    return v


def _jsonb_text(v: Any) -> tuple[str, bool]:
    try:
        s = json.dumps(v, allow_nan=False, separators=(",", ":"))
        if "\\u0000" not in s:
            return s, False
    except ValueError:
        pass
    return json.dumps(_sanitize(v), allow_nan=False, separators=(",", ":")), True


def _str_or_none(v: Any) -> Optional[str]:
    if v is None or isinstance(v, (dict, list)):
        return None
    s = str(v)
    return s if s else None


def _row_for(map_name: str, key: str, value: Any) -> tuple[Optional[str], Optional[str]]:
    """(plan_id, symbol) for the indexed columns."""
    if map_name == "by_plan_id":
        return key, None
    if isinstance(value, dict):
        return _str_or_none(value.get("plan_id")), _str_or_none(value.get("symbol"))
    return None, None


def _first(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _as_dict(cur, row: Any) -> Optional[dict]:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return {d[0]: row[i] for i, d in enumerate(cur.description)}


def _json_value(v: Any) -> Any:
    return json.loads(v) if isinstance(v, (str, bytes, bytearray, memoryview)) else v


# ── ingest ───────────────────────────────────────────────────────────────────

_UPSERT_SQL = (
    "INSERT INTO hermes_projection_entry (map, entry_key, body, plan_id, symbol, ingest_seq, updated_at) "
    "VALUES %s ON CONFLICT (map, entry_key) DO UPDATE SET body = EXCLUDED.body, plan_id = EXCLUDED.plan_id, "
    "symbol = EXCLUDED.symbol, ingest_seq = EXCLUDED.ingest_seq, updated_at = EXCLUDED.updated_at"
)
_UPSERT_TEMPLATE = "(%s, %s, %s::jsonb, %s, %s, %s, %s)"

_META_SQL = (
    "INSERT INTO hermes_projection_meta (id, source_path, source_mtime, source_size, source_sha256, "
    "projection_updated_ts, ingest_seq, entries, ingested_at, build_ms) "
    "VALUES (1, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s) ON CONFLICT (id) DO UPDATE SET "
    "source_path = EXCLUDED.source_path, source_mtime = EXCLUDED.source_mtime, source_size = EXCLUDED.source_size, "
    "source_sha256 = EXCLUDED.source_sha256, projection_updated_ts = EXCLUDED.projection_updated_ts, "
    "ingest_seq = EXCLUDED.ingest_seq, entries = EXCLUDED.entries, ingested_at = EXCLUDED.ingested_at, "
    "build_ms = EXCLUDED.build_ms"
)


def _upsert_batch(cur, rows: list[tuple]) -> None:
    from psycopg2.extras import execute_values

    execute_values(cur, _UPSERT_SQL, rows, template=_UPSERT_TEMPLATE, page_size=BATCH_SIZE)


def _try_lock(cur) -> bool:
    cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", (LOCK_KEY,))
    return bool(_first(cur.fetchone()))


def ingest(connect: Optional[Callable[[], Any]], path: Path | str, *, dry_run: bool,
           chunk_size: int = 1 << 20) -> dict:
    """Ingest the projection file into ``hermes_projection_entry`` / ``hermes_projection_meta``.

    ``connect()`` returns a new psycopg2 connection; this function closes it. Outcomes: OK, UNCHANGED,
    SKIPPED_BUSY, DRY_RUN (nothing written, ``connect`` not called) and FAILED (rolled back; previous state kept).
    """
    t0 = time.monotonic()
    path = Path(path)
    receipt: dict[str, Any] = {
        "product": "hermes.projection", "path": str(path), "dry_run": bool(dry_run), "outcome": None,
        "entries": {m: 0 for m in MAPS}, "entries_total": 0, "deleted": 0, "sanitized": 0, "bytes": None,
        "sha256": None, "ingest_seq": None, "projection_updated_ts": None, "build_ms": None,
        "peak_rss_kb": None, "error": None,
    }

    def done(outcome: str, error: Optional[str] = None) -> dict:
        receipt["outcome"] = outcome
        receipt["error"] = error
        receipt["build_ms"] = int((time.monotonic() - t0) * 1000)
        receipt["peak_rss_kb"] = _peak_rss_kb()
        return receipt

    with open(path, "rb") as fh:
        st = os.fstat(fh.fileno())
        receipt["bytes"] = st.st_size

        if dry_run:
            hasher = hashlib.sha256()
            reader = ProjectionReader(fh, chunk_size, hasher=hasher)
            for name, _key, _value in reader.entries():
                receipt["entries"][name] += 1
            receipt["entries_total"] = sum(receipt["entries"].values())
            receipt["sha256"] = hasher.hexdigest()
            receipt["projection_updated_ts"] = _str_or_none(reader.top.get("updated_ts"))
            return done("DRY_RUN")

        conn = connect()
        try:
            cur = conn.cursor()
            if not _try_lock(cur):
                conn.rollback()
                return done("SKIPPED_BUSY")
            cur.execute("SELECT source_mtime, source_size, source_sha256, ingest_seq FROM hermes_projection_meta "
                        "WHERE id = 1")
            m = _as_dict(cur, cur.fetchone())
            if m and int(m["source_size"]) == st.st_size and float(m["source_mtime"]) == st.st_mtime:
                sha = _sha256_stream(fh, chunk_size)
                fh.seek(0)
                if sha == m["source_sha256"]:
                    conn.rollback()
                    receipt["sha256"] = sha
                    receipt["ingest_seq"] = int(m["ingest_seq"])
                    return done("UNCHANGED")
            seq = (int(m["ingest_seq"]) if m else 0) + 1
            now = datetime.now(timezone.utc)
            hasher = hashlib.sha256()
            reader = ProjectionReader(fh, chunk_size, hasher=hasher)
            batch: dict[tuple[str, str], tuple] = {}
            for name, key, value in reader.entries():
                receipt["entries"][name] += 1
                text, fixed = _jsonb_text(value)
                receipt["sanitized"] += int(fixed)
                plan_id, symbol = _row_for(name, key, value)
                batch[(name, key)] = (name, key, text, plan_id, symbol, seq, now)  # a duplicate key: last wins
                if len(batch) >= BATCH_SIZE:
                    _upsert_batch(cur, list(batch.values()))
                    batch = {}
            if batch:
                _upsert_batch(cur, list(batch.values()))
            # Keyed-product eviction (DSN §4.5): an entry absent from this ingest was not touched, so its seq is old.
            cur.execute("DELETE FROM hermes_projection_entry WHERE ingest_seq <> %s", (seq,))
            receipt["deleted"] = cur.rowcount
            receipt["entries_total"] = sum(receipt["entries"].values())
            receipt["sha256"] = hasher.hexdigest()
            receipt["ingest_seq"] = seq
            receipt["projection_updated_ts"] = _str_or_none(reader.top.get("updated_ts"))
            cur.execute(_META_SQL, (
                str(path), st.st_mtime, st.st_size, receipt["sha256"], receipt["projection_updated_ts"], seq,
                json.dumps(receipt["entries"]), now, int((time.monotonic() - t0) * 1000),
            ))
            conn.commit()
            return done("OK")
        except Exception as exc:  # noqa: BLE001 - the receipt carries it; the stored state is untouched
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            return done("FAILED", f"{type(exc).__name__}: {exc}"[:2000])
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ── readers (server code calls these instead of parsing the file) ────────────


def _entry(cur, map_name: str, key: str) -> Optional[dict]:
    cur.execute("SELECT body FROM hermes_projection_entry WHERE map = %s AND entry_key = %s", (map_name, str(key)))
    return _json_value(_first(cur.fetchone()))


def plan_entry(cur, plan_id: str) -> Optional[dict]:
    return _entry(cur, "by_plan_id", plan_id)


def research_entry(cur, rid: str) -> Optional[dict]:
    return _entry(cur, "by_research_id", rid)


def fingerprint_entry(cur, fp: str, completed: bool) -> Optional[dict]:
    return _entry(cur, "by_fingerprint_completed" if completed else "by_fingerprint_open", fp)


def research_for_symbol(cur, symbol: str, limit: int = 50) -> list[dict]:
    """Research records for a symbol, newest ``created_ts`` first (uses the upper(symbol) index)."""
    cur.execute(
        "SELECT body FROM hermes_projection_entry WHERE upper(symbol) = upper(%s) AND map = 'by_research_id' "
        "ORDER BY body->>'created_ts' DESC NULLS LAST, entry_key LIMIT %s",
        (str(symbol or ""), int(limit)),
    )
    return [_json_value(_first(r)) for r in cur.fetchall()]


def latest_research_for_plan_from_store(cur, plan_id: str,
                                        result_lookup: Optional[Callable[[str], Optional[dict]]] = None) -> dict:
    """Same shape as ``cio_hermes_research.latest_research_for_plan``, from one indexed row.

    ``result_lookup(result_id)`` supplies ``latest_result``; with none, ``latest_result`` is None (the results
    JSONL is a separate §4.3 item and is not read here).
    """
    bp = plan_entry(cur, plan_id) or {}
    rid = bp.get("latest_result_id")
    result = None
    if rid and result_lookup is not None:
        try:
            result = result_lookup(rid)
        except Exception:  # noqa: BLE001 - same tolerance as the file-backed original
            result = None
    return {
        "plan_id": plan_id,
        "open": list(bp.get("open") or []),
        "latest_result_id": rid,
        "latest_as_of": bp.get("latest_as_of"),
        "latest_result": result,
    }


def meta(cur) -> Optional[dict]:
    cur.execute(
        "SELECT source_path, source_mtime, source_size, source_sha256, projection_updated_ts, ingest_seq, entries, "
        "ingested_at, build_ms FROM hermes_projection_meta WHERE id = 1"
    )
    row = _as_dict(cur, cur.fetchone())
    if row is not None:
        row["entries"] = _json_value(row["entries"])
    return row


# ── CLI ──────────────────────────────────────────────────────────────────────


def _set_rlimit_as(limit: int) -> Optional[str]:
    try:
        _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if hard != resource.RLIM_INFINITY and hard < limit:
            limit = hard
        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
        return None
    except (ValueError, OSError) as exc:
        return str(exc)


def main(argv: Optional[list[str]] = None) -> int:
    rl_err = _set_rlimit_as(INGEST_RLIMIT_AS_BYTES)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", default=str(DEFAULT_PATH))
    ap.add_argument("--dry-run", action="store_true", help="parse and count; write nothing, connect to nothing")
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    ap.add_argument("--chunk-size", type=int, default=1 << 20)
    args = ap.parse_args(argv)

    def connect():
        import psycopg2

        return psycopg2.connect(args.dsn)

    receipt = ingest(connect, args.path, dry_run=args.dry_run, chunk_size=args.chunk_size)
    receipt["rlimit_as_bytes"] = None if rl_err else resource.getrlimit(resource.RLIMIT_AS)[0]
    if rl_err:
        receipt["rlimit_error"] = rl_err
    print(json.dumps(receipt, indent=2, default=str))
    return 0 if receipt["outcome"] in ("OK", "UNCHANGED", "DRY_RUN", "SKIPPED_BUSY") else 1


if __name__ == "__main__":
    sys.exit(main())
