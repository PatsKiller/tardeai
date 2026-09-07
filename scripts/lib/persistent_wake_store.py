"""Disposable JSONL store for WakeRecord@v2 / receipts / commitments.

Production Postgres DDL is proposed for integration owner (migrations/**).
Lane A writes only under an explicit state_root (tests use tmp paths).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterator


class JsonlStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._global = threading.Lock()

    def _lock(self, name: str) -> threading.Lock:
        with self._global:
            if name not in self._locks:
                self._locks[name] = threading.Lock()
            return self._locks[name]

    def path(self, name: str) -> Path:
        return self.root / f"{name}.jsonl"

    def append_unique(self, name: str, key_field: str, record: dict) -> tuple[bool, dict]:
        """Append if key absent. Returns (inserted, existing_or_new)."""
        with self._lock(name):
            p = self.path(name)
            existing = None
            if p.exists():
                for line in p.read_text().splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if row.get(key_field) == record.get(key_field):
                        return False, row
            with p.open("a") as fh:
                fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            return True, record

    def upsert_by_key(self, name: str, key_field: str, record: dict, *,
                      preserve_terminal: bool = False,
                      terminal_states: frozenset[str] | None = None) -> dict:
        terminal_states = terminal_states or frozenset()
        with self._lock(name):
            p = self.path(name)
            rows: list[dict] = []
            found = False
            if p.exists():
                for line in p.read_text().splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if row.get(key_field) == record.get(key_field):
                        found = True
                        if preserve_terminal and row.get("lifecycle_state") in terminal_states:
                            # keep terminal; merge non-regressive fields
                            merged = dict(row)
                            for k, v in record.items():
                                if k == "lifecycle_state":
                                    continue
                                if k.endswith("_ids") or k.endswith("_created") or k.endswith("_emitted"):
                                    # lists only grow
                                    old = list(merged.get(k) or [])
                                    for item in (v or []):
                                        if item not in old:
                                            old.append(item)
                                    merged[k] = old
                                elif k == "provenance":
                                    merged[k] = v  # latest provenance ok
                                else:
                                    merged[k] = merged.get(k, v) if merged.get(k) not in (None, "", []) else v
                            rows.append(merged)
                        else:
                            rows.append(record)
                    else:
                        rows.append(row)
            if not found:
                rows.append(record)
            tmp = p.with_suffix(".tmp")
            with tmp.open("w") as fh:
                for r in rows:
                    fh.write(json.dumps(r, sort_keys=True, default=str) + "\n")
            os.replace(tmp, p)
            for r in rows:
                if r.get(key_field) == record.get(key_field):
                    return r
            return record

    def get(self, name: str, key_field: str, key: str) -> dict | None:
        p = self.path(name)
        if not p.exists():
            return None
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get(key_field) == key:
                return row
        return None

    def iter(self, name: str) -> Iterator[dict]:
        p = self.path(name)
        if not p.exists():
            return
        for line in p.read_text().splitlines():
            if line.strip():
                yield json.loads(line)

    def count(self, name: str) -> int:
        return sum(1 for _ in self.iter(name))
