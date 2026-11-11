"""Ask-the-CIO memory: durable, position-independent duplicate index (LQ-20261107-1947).

The research spine keeps only the last 100 contributions per tip, so comparing a retry against the tip (LQ-1929)
cannot recognise a memory that has since scrolled out of the window, and a read-then-write is not atomic across
processes. This index is a sidecar next to the spine: ``<spine>.askidx`` holds one sha256 fingerprint per line, one
per (subject, kind, ref, summary) ever written by Ask-the-CIO. The check-and-write runs under an exclusive
``flock`` on ``<spine>.askidx.lock`` so two processes retrying the same answer yield one memory.

The spine itself is never rewritten or read in full here. A memory written before this index existed is still caught
by the tip comparison while it is inside the window; ``rebuild`` (read-only on the spine) seeds the index from it.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

_CACHE: dict[str, tuple[int, set[str]]] = {}  # index path -> (bytes consumed, fingerprints)


def fingerprint(symbol: str, security_guid: Optional[str], kind: str, ref: str, summary: str) -> str:
    raw = "\x1f".join([str(symbol or "").upper(), str(security_guid or ""), kind, str(ref), summary])
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


class MemoryIndex:
    def __init__(self, spine_path: Path):
        self.path = Path(str(spine_path) + ".askidx")
        self.lock_path = Path(str(spine_path) + ".askidx.lock")

    @contextmanager
    def locked(self) -> Iterator["MemoryIndex"]:
        """Exclusive cross-process lock. Raises OSError if the lock cannot be taken (caller reports it)."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield self
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _known(self) -> set[str]:
        key = str(self.path)
        pos, seen = _CACHE.get(key, (0, set()))
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return seen if pos == 0 else set()
        if size < pos:  # truncated/replaced: start over
            pos, seen = 0, set()
        if size > pos:
            with self.path.open("rb") as fh:
                fh.seek(pos)
                chunk = fh.read()
            cut = chunk.rfind(b"\n") + 1  # only whole lines
            seen = set(seen) | {x for x in chunk[:cut].decode("ascii", "ignore").split() if len(x) == 64}
            pos += cut
        _CACHE[key] = (pos, seen)
        return seen

    def has(self, fp: str) -> bool:
        return fp in self._known()

    def add(self, fp: str) -> None:
        """Append one fingerprint durably. Call inside ``locked()``."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="ascii") as fh:
            fh.write(fp + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def rebuild(self, spine_path: Path, *, only_tag: str = "ask_the_cio") -> int:
        """Seed the index from an existing spine (READ-ONLY on the spine). Returns fingerprints added."""
        added = 0
        with self.locked():
            known = self._known()
            with Path(spine_path).open("rb") as fh:
                for raw in fh:
                    try:
                        tip = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(tip, dict):
                        continue
                    for c in tip.get("contributions") or []:
                        if not isinstance(c, dict) or only_tag not in (c.get("tags") or []):
                            continue
                        fp = fingerprint(tip.get("symbol"), tip.get("subject_guid"), c.get("kind"),
                                         c.get("artifact_id"), c.get("summary"))
                        if fp not in known:
                            self.add(fp)
                            known.add(fp)
                            added += 1
        return added
