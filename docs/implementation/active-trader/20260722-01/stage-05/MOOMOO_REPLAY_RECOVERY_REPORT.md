# Moomoo Replay & Recovery Report — Stage 5

`scripts/active_trader/moomoo/replay.py` — implemented and integration-tested (with the
isolated venv's pyarrow). No raw market data enters Git or PostgreSQL.

## WAL
Append-only, per-record `<crc32>\t<json>\n`, fsync'd. Partitioned by
UTC-date/session/symbol/stream. Crash recovery (tested): a torn/unterminated tail line is
dropped and all prior records survive; a corrupted CRC truncates cleanly at that record.
SHA-256 checksum per segment.

## Parquet compaction
Closed WAL → zstd Parquet via PyArrow, carrying schema/source version, row count, and the
WAL sha256 in Parquet metadata. Verified by **read-back**: row count must match before the
result is marked verified; min/max timestamps recorded. The WAL is retained until the
Parquet round-trip verifies (tested — WAL still present after a verified compaction).

## Disk budget
max replay 20 GiB · min free before start 10 GiB · high-water 80% (shed P3 + compact) ·
critical 90% (stop new subscriptions, degrade). `disk_gate` returns OK/HIGH_WATER/
CRITICAL/INSUFFICIENT_FREE; unverified evidence is never deleted. Current host: 265 GiB
free, replay usage ~0 → state OK.

## Endurance (market-closed)
Per §22, with the US market CLOSED and login blocked, the WAL→Parquet round-trip +
crash-recovery integration tests stand in for live endurance. Live continuous capture is
pending both a working login and an open market session.
