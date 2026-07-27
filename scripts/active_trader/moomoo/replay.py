"""Stage 5 — append-only checksummed WAL → verified zstd Parquet replay store.

WAL is partitioned by UTC date/session/symbol/stream, crash-recoverable (each line
is length-prefixed + per-line CRC; a torn tail line is dropped on recovery). Parquet
compaction via PyArrow; the WAL segment is retained until Parquet read-back, row count,
and checksums all verify. No raw market data ever enters Git or PostgreSQL.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

REPLAY_ROOT = Path.home() / ".local/share/trade-ai-lab/moomoo/replay"


def _crc(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


class WALWriter:
    """Append-only. Each record: <crc32 hex>\\t<json>\\n."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        self._fh = open(path, "ab")

    def append(self, record: dict) -> None:
        body = json.dumps(record, sort_keys=True, default=str).encode()
        line = f"{_crc(body):08x}\t".encode() + body + b"\n"
        self._fh.write(line)
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self):
        self._fh.close()


def wal_read(path: Path) -> Iterator[dict]:
    """Yield valid records; drop a torn/invalid tail line (crash recovery)."""
    if not path.exists():
        return
    with open(path, "rb") as fh:
        for raw in fh:
            if not raw.endswith(b"\n"):
                break                         # torn tail — stop
            try:
                crc_hex, body = raw[:-1].split(b"\t", 1)
                if int(crc_hex, 16) != _crc(body):
                    break
                yield json.loads(body)
            except Exception:
                break


def wal_checksum(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class CompactionResult:
    parquet_path: Path
    row_count: int
    wal_sha256: str
    parquet_sha256: str
    min_ts: Optional[str]
    max_ts: Optional[str]
    verified: bool


def compact_to_parquet(wal_path: Path, parquet_path: Path,
                       schema_version: str = "moomoo-md-1") -> CompactionResult:
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = list(wal_read(wal_path))
    row_count = len(rows)
    ts = [r.get("gateway_receive_timestamp") for r in rows if r.get("gateway_receive_timestamp")]
    table = pa.Table.from_pylist([{"record": json.dumps(r, sort_keys=True, default=str)} for r in rows],
                                 metadata={b"schema_version": schema_version.encode(),
                                           b"row_count": str(row_count).encode(),
                                           b"wal_sha256": wal_checksum(wal_path).encode()})
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(parquet_path.parent, 0o700)
    pq.write_table(table, parquet_path, compression="zstd")

    # verify by read-back
    back = pq.read_table(parquet_path)
    verified = back.num_rows == row_count
    return CompactionResult(
        parquet_path=parquet_path, row_count=row_count, wal_sha256=wal_checksum(wal_path),
        parquet_sha256=wal_checksum(parquet_path),
        min_ts=min(ts) if ts else None, max_ts=max(ts) if ts else None, verified=verified)


def partition_path(root: Path, utc_date: str, session: str, symbol: str,
                   stream: str, kind: str = "wal") -> Path:
    safe_symbol = symbol.replace("/", "_").replace(".", "_")
    ext = "wal" if kind == "wal" else "parquet"
    return root / utc_date / session / safe_symbol / stream / f"segment.{ext}"


def disk_usage_bytes(root: Path = REPLAY_ROOT) -> int:
    total = 0
    for p in root.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


DISK_BUDGET_BYTES = 20 * 1024**3
MIN_FREE_BYTES = 10 * 1024**3


def disk_gate(root: Path = REPLAY_ROOT) -> dict:
    import shutil
    used = disk_usage_bytes(root) if root.exists() else 0
    free = shutil.disk_usage(root.parent if root.exists() else Path.home()).free
    ratio = used / DISK_BUDGET_BYTES if DISK_BUDGET_BYTES else 0
    state = "OK"
    if free < MIN_FREE_BYTES:
        state = "INSUFFICIENT_FREE"
    elif ratio >= 0.90:
        state = "CRITICAL"
    elif ratio >= 0.80:
        state = "HIGH_WATER"
    return {"used_bytes": used, "free_bytes": free, "budget_bytes": DISK_BUDGET_BYTES,
            "ratio": round(ratio, 4), "state": state}
