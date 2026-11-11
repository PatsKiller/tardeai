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
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

_CACHE: dict[str, tuple[int, set[str]]] = {}  # index path -> (bytes consumed, fingerprints)


def fingerprint(symbol: str, security_guid: Optional[str], kind: str, ref: str, summary: str) -> str:
    raw = "\x1f".join([str(symbol or "").upper(), str(security_guid or ""), kind, str(ref), summary])
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


class MemoryIndex:
    def __init__(self, spine_path: Path):
        self.spine_path = Path(spine_path)
        self.path = Path(str(spine_path) + ".askidx")
        self.meta_path = Path(str(spine_path) + ".askidx.meta")
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
        lead = ""
        try:  # a torn last line (crash mid-write) must not swallow this fingerprint (LQ-1962 R-2)
            with self.path.open("rb") as rf:
                rf.seek(-1, os.SEEK_END)
                lead = "" if rf.read(1) == b"\n" else "\n"
        except (FileNotFoundError, OSError):
            lead = ""
        with self.path.open("a", encoding="ascii") as fh:
            fh.write(lead + fp + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._stamp()

    # ── index <-> spine binding (LQ-1962 R-1) ─────────────────────────────────────────────────────────────────────
    def _spine_id(self) -> Optional[dict]:
        try:
            st = self.spine_path.stat()
        except OSError:
            return None
        return {"ino": st.st_ino, "size": st.st_size}

    def _stamp(self) -> None:
        """Record which spine (inode) and how large it was when the index last claimed to describe it."""
        ident = self._spine_id()
        if ident is None:
            return
        tmp = self.meta_path.with_name(self.meta_path.name + ".tmp")
        tmp.write_text(json.dumps(ident), encoding="ascii")
        os.replace(tmp, self.meta_path)

    def verify(self) -> Optional[str]:
        """None when the index may be trusted; else the reason it is stale. A fingerprint is a claim that the spine
        holds the memory, so a replaced, shrunk or missing spine (restore, compaction, truncation), or an index with no
        record of the spine it describes, voids every claim."""
        try:
            has_claims = self.path.exists() and self.path.stat().st_size > 0
        except OSError:
            return "index_unreadable"
        if not has_claims:
            return None
        try:
            rec = json.loads(self.meta_path.read_text(encoding="ascii"))
        except (OSError, ValueError):
            return "no_stamp"
        now = self._spine_id()
        if now is None:
            return "spine_missing"
        if rec.get("ino") != now["ino"]:
            return "spine_replaced"
        if now["size"] < int(rec.get("size") or 0):
            return "spine_shrunk"
        return None

    def reseed(self) -> int:
        """Archive the stale index (never delete), then rebuild it from what the spine really holds. Inside ``locked()``."""
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        for src in (self.path, self.meta_path):
            if src.exists():
                src.rename(src.with_name(f"{src.name}.stale-{stamp}-{os.getpid()}"))
        _CACHE.pop(str(self.path), None)
        if self.spine_path.exists():
            return self._rebuild_locked(self.spine_path)
        return 0

    def rebuild(self, spine_path: Path, *, only_tag: str = "ask_the_cio") -> int:
        """Seed the index from an existing spine (READ-ONLY on the spine). Returns fingerprints added."""
        with self.locked():
            return self._rebuild_locked(spine_path, only_tag=only_tag)

    def _rebuild_locked(self, spine_path: Path, *, only_tag: str = "ask_the_cio") -> int:
        added = 0
        if True:
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
        self._stamp()
        return added
