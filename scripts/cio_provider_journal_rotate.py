#!/usr/bin/env python3
"""cio_provider_journal_rotate.py -- archive aged rows out of the provider request journal.

The provider request journal (``ProviderRequestJournal``, scripts/lib/cio_provider_retry_v1.py) is
append-only and was never rotated: 71 MB / 147k rows by 2026-10-15, when whole-file parses in
``latest()`` OOM-killed the governed bridge. ``latest()`` is now memory-bounded; this maintenance
entry point keeps the file itself from growing without bound. It is NOT on the request hot path
and is NOT scheduled -- the operator runs it.

What moves (config/cio_provider_journal_retention.json):
  * a semantic key is archived only when its NEWEST row is older than ``window_days`` AND its latest
    state is not in ``retain_states`` (AMBIGUOUS / DISPATCHED need explicit resolution, so they stay
    live at any age);
  * all rows of a key move together, so for every key left in the live journal ``latest()`` and the
    attempt count are byte-for-byte what they were -- the retry / idempotency window is honoured;
  * lines that do not parse as a JSON object (torn writes) are archived too; ``latest()`` already
    skips them. Rows without a semantic key or a parseable ``recorded_at`` stay live.

How (``--apply``), all under the journal's exclusive flock (the lock reserve()/record() take, so no
append can interleave; the bridge blocks for the few seconds this takes):
  1. stream the journal once, per key: newest ``recorded_at`` and latest state;
  2. stream it again: archived lines, byte-for-byte, to
     ``retention_archive.file_archive_root() / <label> / <label>.<UTC stamp>.jsonl.gz`` (fsync); kept lines to a temp
     file beside the journal (fsync);
  3. re-read the archive: line count and sha256 must match what was written; kept + archived must
     equal the lines read; any mismatch raises and the live journal is untouched;
  4. write the sha256 manifest and the RetentionArchiveTripwire@v1 record
     (scripts/lib/retention_archive.write_manifest; reader scripts/lib/retention_tripwire.py);
  5. ``os.replace`` the temp file over the journal and fsync the directory.
A crash before step 5 leaves every row in the live journal (possibly also in an archive): nothing is
ever lost and nothing is deleted (AGENTS.md rule 6).

  python3 scripts/cio_provider_journal_rotate.py                 # dry run (default)
  python3 scripts/cio_provider_journal_rotate.py --apply

AUTHORITY: READ_ONLY_ADVISORY. Touches only the journal file and its archive directory.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.lib.cio_provider_retry_v1 import ProviderRequestJournal  # noqa: E402

CONFIG_PATH = PROJECT_ROOT / "config" / "cio_provider_journal_retention.json"
REPORT_SCHEMA = "ProviderJournalRotation@v1"
WRITER = "cio_provider_journal_rotate"


class RotationVerifyError(RuntimeError):
    """The archive re-read or the line accounting did not match; the live journal was not replaced."""


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != "ProviderJournalRetention@v1":
        raise SystemExit(f"ERROR: {path}: schema must be ProviderJournalRetention@v1")
    for k in ("window_days", "min_window_days"):
        v = doc.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise SystemExit(f"ERROR: {path}: {k} must be an int >= 1")
    if not isinstance(doc.get("retain_states"), list) or not doc.get("archive_label"):
        raise SystemExit(f"ERROR: {path}: retain_states (list) and archive_label are required")
    return doc


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _classify(raw: bytes) -> tuple[str, dict[str, Any] | None]:
    """('row', obj) | ('bad', None). Blank lines are 'blank'."""
    if not raw.strip():
        return "blank", None
    try:
        obj = json.loads(raw)
    except (TypeError, ValueError):
        return "bad", None
    return ("row", obj) if isinstance(obj, dict) else ("bad", None)


def analyse(path: Path) -> dict[str, Any]:
    """One streaming pass: per key (newest ts, latest state). Memory ~ number of distinct keys."""
    keys: dict[str, list[Any]] = {}  # key -> [newest_ts, latest_state, rows]
    lines = rows = bad = blank = 0
    oldest: datetime | None = None
    newest: datetime | None = None
    size = 0
    if path.exists():
        with path.open("rb") as fh:
            size = os.fstat(fh.fileno()).st_size
            for raw in fh:
                lines += 1
                kind, obj = _classify(raw)
                if kind == "blank":
                    blank += 1
                    continue
                if kind == "bad":
                    bad += 1
                    continue
                rows += 1
                ts = _parse_ts(obj.get("recorded_at"))
                if ts is not None:
                    oldest = ts if oldest is None or ts < oldest else oldest
                    newest = ts if newest is None or ts > newest else newest
                key = obj.get("semantic_key")
                if not isinstance(key, str) or not key:
                    continue
                entry = keys.setdefault(key, [None, None, 0])
                if ts is not None and (entry[0] is None or ts > entry[0]):
                    entry[0] = ts
                entry[1] = obj.get("state")
                entry[2] += 1
    return {
        "keys": keys,
        "lines": lines,
        "rows": rows,
        "unparseable": bad,
        "blank": blank,
        "oldest": oldest,
        "newest": newest,
        "bytes": size,
    }


def select_keys(keys: dict[str, list[Any]], *, cutoff: datetime, retain_states: set[str]) -> tuple[set[str], int]:
    """(keys to archive, keys held back only because their latest state is unresolved)."""
    out: set[str] = set()
    held = 0
    for key, (newest_ts, state, _n) in keys.items():
        if newest_ts is None or newest_ts >= cutoff:
            continue
        if state in retain_states:
            held += 1
            continue
        out.add(key)
    return out, held


def _line_moves(raw: bytes, archive_keys: set[str]) -> bool:
    kind, obj = _classify(raw)
    if kind == "blank":
        return False
    if kind == "bad":
        return True
    return obj.get("semantic_key") in archive_keys


def _verify_archive(path: Path, *, expected_lines: int, expected_sha256: str) -> None:
    from scripts.lib.retention_archive import _sha256_file

    sha = _sha256_file(path)
    if sha != expected_sha256:
        raise RotationVerifyError(f"archive sha256 {sha} != {expected_sha256}")
    n = 0
    with gzip.open(path, "rb") as fh:
        for _ in fh:
            n += 1
    if n != expected_lines:
        raise RotationVerifyError(f"archive has {n} lines, expected {expected_lines}")


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def rotate(
    journal_path: Path,
    *,
    window_days: int,
    retain_states: set[str],
    archive_dir: Path,
    label: str,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    journal = ProviderRequestJournal(journal_path)
    live = Path(os.path.realpath(journal.path))
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    archive_file = Path(archive_dir) / f"{label}.{stamp}.jsonl.gz"
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "mode": "APPLY" if apply else "DRY_RUN",
        "journal": str(live),
        "window_days": window_days,
        "cutoff": cutoff.isoformat(),
        "retain_states": sorted(retain_states),
        "archive": str(archive_file),
    }

    def _plan() -> tuple[dict[str, Any], set[str]]:
        a = analyse(live)
        keys, held = select_keys(a["keys"], cutoff=cutoff, retain_states=retain_states)
        report.update(
            {
                "bytes_before": a["bytes"],
                "lines": a["lines"],
                "rows": a["rows"],
                "keys": len(a["keys"]),
                "unparseable_lines": a["unparseable"],
                "blank_lines": a["blank"],
                "oldest_recorded_at": a["oldest"].isoformat() if a["oldest"] else None,
                "newest_recorded_at": a["newest"].isoformat() if a["newest"] else None,
                "keys_to_archive": len(keys),
                "keys_held_unresolved": held,
                "rows_to_archive": sum(a["keys"][k][2] for k in keys) + a["unparseable"],
            }
        )
        return a, keys

    if not apply:
        _plan()  # no lock: a read-only snapshot of an append-only file
        report["result"] = "DRY_RUN"
        return report

    with journal.locked():
        a, keys = _plan()
        if report["rows_to_archive"] == 0:
            report["result"] = "NOTHING_TO_ARCHIVE"
            report["archive"] = None
            return report
        from scripts.lib.retention_archive import _sha256_file, write_manifest

        archive_file.parent.mkdir(parents=True, exist_ok=True)
        if archive_file.exists():
            raise RotationVerifyError(f"archive {archive_file} already exists; refusing to overwrite")
        tmp = live.with_name(live.name + f".rotate-{stamp}.tmp")
        kept = moved = read = 0
        try:
            with live.open("rb") as src, tmp.open("wb") as keep_fh, open(archive_file, "wb") as raw_out:
                with gzip.GzipFile(fileobj=raw_out, mode="wb", compresslevel=6) as gz:
                    for raw in src:
                        read += 1
                        line = raw if raw.endswith(b"\n") else raw + b"\n"
                        if _line_moves(raw, keys):
                            gz.write(line)
                            moved += 1
                        else:
                            keep_fh.write(line)
                            kept += 1
                raw_out.flush()
                os.fsync(raw_out.fileno())
                keep_fh.flush()
                os.fsync(keep_fh.fileno())
            if read != a["lines"] or kept + moved != read or moved != report["rows_to_archive"]:
                raise RotationVerifyError(
                    f"line accounting: read={read} analysed={a['lines']} kept={kept} moved={moved} "
                    f"planned={report['rows_to_archive']}"
                )
            sha = _sha256_file(archive_file)
            _verify_archive(archive_file, expected_lines=moved, expected_sha256=sha)
            write_manifest(
                archive_file,
                writer=WRITER,
                kind="rows",
                table=label,
                label=label,
                rows=moved,
                sha256=sha,
                bytes=archive_file.stat().st_size,
                source=str(live),
                cutoff=cutoff.isoformat(),
                window_days=window_days,
                keys=len(keys),
            )
            os.replace(tmp, live)
            _fsync_dir(live.parent)
        finally:
            if tmp.exists():
                # Never reached after os.replace; on failure the temp copy is redundant (the live
                # journal is untouched) -- keep it beside the journal for inspection, do not unlink.
                report["left_temp_file"] = str(tmp)
        report.update(
            {
                "result": "APPLIED",
                "rows_archived": moved,
                "rows_kept": kept,
                "archive_sha256": sha,
                "bytes_after": live.stat().st_size,
            }
        )
        return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report only (default)")
    mode.add_argument("--apply", action="store_true", help="archive and rewrite the live journal")
    ap.add_argument("--journal", help="journal path (default: the bridge's default_journal_path())")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--window-days", type=int, help="override config window_days (>= min_window_days)")
    ap.add_argument("--archive-dir", help="override retention_archive.file_archive_root() / <label>")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config(Path(a.config))
    window = a.window_days if a.window_days is not None else cfg["window_days"]
    if window < cfg["min_window_days"]:
        print(f"ERROR: window_days {window} < min_window_days {cfg['min_window_days']}", file=sys.stderr)
        return 2
    label = str(cfg["archive_label"])
    if a.archive_dir:
        archive_dir = Path(a.archive_dir)
    else:
        from scripts.lib.retention_archive import file_archive_root

        archive_dir = file_archive_root() / label
    journal_path = Path(a.journal) if a.journal else ProviderRequestJournal().path
    report = rotate(
        journal_path,
        window_days=window,
        retain_states=set(cfg["retain_states"]),
        archive_dir=archive_dir,
        label=label,
        apply=a.apply,
    )
    if a.json:
        print(json.dumps(report, sort_keys=True, indent=1))
    else:
        for k in sorted(report):
            print(f"{k:>24}: {report[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
