"""Bounded reads of append-only JSONL stores (2026-10-23).

Several never-rotated logs under data/cio are hundreds of MB (aif_memory_retrievals.jsonl:
574 MB / 1,066,782 lines; cio_workflow_lineage.jsonl: 157 MB on 2026-10-23). Request handlers
read them with ``read_text().splitlines()`` to take the last 20 rows or a line count, which held
the whole file -- and a list of every line -- in memory: +1.19 GB peak RSS per
GET /api/v3/maturity/memory and per CIO brain build, against portfolio-server's 1.5 GB
MemoryHigh (docs/ops/SERVER_MEMORY_SPIKES_2026-10-23.md).

* ``tail_jsonl_lines(path, n)`` -- the same lines as the full read's last ``n`` non-blank
  lines, read backwards from the end in doubling windows, capped at ``max_bytes``.
* ``count_jsonl_lines(path)`` -- the full read's non-blank line count, streamed in fixed
  chunks and cached per (device, inode, size): a grown file is counted over the appended
  bytes only; a shrunk or replaced file is recounted. One lock: concurrent callers share a scan.

Stdlib only. READ_ONLY_ADVISORY: reads files, writes nothing.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

TAIL_WINDOW_BYTES = int(os.environ.get("TRADEAI_MEMORY_TAIL_WINDOW_BYTES") or 256 * 1024)
TAIL_MAX_BYTES = int(os.environ.get("TRADEAI_MEMORY_TAIL_MAX_BYTES") or 16 * 1024 * 1024)
COUNT_CHUNK_BYTES = 4 * 1024 * 1024

_LINE_COUNT_LOCK = threading.Lock()
# str(path) -> (st_dev, st_ino, bytes_counted, complete_nonblank_lines, open_line_has_content)
_LINE_COUNT_CACHE: dict[str, tuple[int, int, int, int, bool]] = {}


def tail_jsonl_lines(
    path: Path | str,
    n: int,
    *,
    window: int | None = None,
    max_bytes: int | None = None,
) -> list[str]:
    """Last ``n`` non-blank lines of ``path``, read backwards from the end.

    Same lines as ``[ln for ln in read_text().splitlines() if ln.strip()][-n:]``, but reads
    at most ``max_bytes`` from the end of the file (windows double from ``window``). The
    result is short only when the byte budget runs out before ``n`` lines were seen.
    """
    p = Path(path)
    if n <= 0:
        return []
    window = max(1024, int(window or TAIL_WINDOW_BYTES))
    max_bytes = max(window, int(max_bytes or TAIL_MAX_BYTES))
    try:
        fh = p.open("rb")
    except OSError:
        return []
    with fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        buf = b""
        read = 0
        while True:
            at_start = pos == 0
            # Complete lines: everything after the first b"\n" (the whole buffer at file start).
            if at_start:
                body = buf
            else:
                cut = buf.find(b"\n")
                body = buf[cut + 1:] if cut >= 0 else b""
            lines = [ln for ln in body.decode("utf-8", errors="replace").splitlines() if ln.strip()]
            if len(lines) >= n or at_start or read >= max_bytes:
                return lines[-n:]
            step = min(max(window, read), pos, max_bytes - read)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
            read += step


def count_jsonl_lines(path: Path | str) -> int:
    """Count the non-blank lines of an append-only JSONL file with constant memory.

    Cached per file identity (device, inode) and size: a file that grew is counted only over
    the appended bytes; a file that shrank or was replaced is recounted from the start.
    Streams fixed-size chunks and never holds the file in memory. One lock serialises the
    count, so concurrent callers share one scan instead of each starting their own.
    """
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return 0
    key = str(p)
    with _LINE_COUNT_LOCK:
        hit = _LINE_COUNT_CACHE.get(key)
        if hit and hit[0] == st.st_dev and hit[1] == st.st_ino and hit[2] <= st.st_size:
            pos, complete, open_content = hit[2], hit[3], hit[4]
        else:
            pos, complete, open_content = 0, 0, False
        if pos < st.st_size:
            try:
                with p.open("rb") as fh:
                    fh.seek(pos)
                    remaining = st.st_size - pos
                    while remaining > 0:
                        chunk = fh.read(min(COUNT_CHUNK_BYTES, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        pos += len(chunk)
                        segs = chunk.split(b"\n")
                        # Every segment but the last closes a line; the last stays open.
                        for seg in segs[:-1]:
                            if open_content or seg.strip():
                                complete += 1
                            open_content = False
                        if segs[-1].strip():
                            open_content = True
            except OSError:
                return complete + (1 if open_content else 0)
            _LINE_COUNT_CACHE[key] = (st.st_dev, st.st_ino, pos, complete, open_content)
        return complete + (1 if open_content else 0)
