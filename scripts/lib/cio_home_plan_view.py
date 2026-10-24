"""Bounded, read-only plan input for CIO home; never rebuilds or writes a store.

The normal plan store remains the writer/detail API. Home needs 12 public plans
and a 5,000-row minimal coverage index, not every historical plan's payload.
"""

from __future__ import annotations

import heapq
import json
from pathlib import Path
from typing import Any

from scripts.lib.cio_plans import CIOPlanStore, OPENISH

CHUNK = 64 * 1024
MAX_VALUE_CHARS = 1 << 20
MAX_TAIL_BYTES = 4 << 20
MAX_PLANS = 100_000
MAX_RETAINED_BYTES = 24 << 20
COVERAGE_KEYS = (
    "plan_id",
    "situation_type",
    "symbols",
    "status",
    "revisit_at",
    "updated_ts",
    "created_ts",
    "material",
    "hermes_result_id",
)


class PlanReadLimit(ValueError):
    """A corrupt/oversized source is unavailable, never an incomplete success."""


class _Reader:
    def __init__(self, handle):
        self.handle, self.buffer, self.at, self.eof = handle, "", 0, False
        self.decoder = json.JSONDecoder()

    def more(self):
        self.buffer = self.buffer[self.at :]
        self.at = 0
        chunk = self.handle.read(CHUNK)
        self.eof = not chunk
        self.buffer += chunk

    def peek(self):
        while True:
            while self.at < len(self.buffer) and self.buffer[self.at].isspace():
                self.at += 1
            if self.at < len(self.buffer):
                return self.buffer[self.at]
            if self.eof:
                return ""
            self.more()

    def char(self, expected):
        if self.peek() != expected:
            raise ValueError(f"invalid projection: expected {expected}")
        self.at += 1

    def value(self):
        self.peek()
        while True:
            if len(self.buffer) - self.at > MAX_VALUE_CHARS + CHUNK:
                raise PlanReadLimit("projection value exceeds bounded record size")
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.at)
                # A numeric token at a chunk boundary may continue in the next chunk.
                if end == len(self.buffer) and not self.eof:
                    self.more()
                    continue
                if end - self.at > MAX_VALUE_CHARS:
                    raise PlanReadLimit("projection value exceeds bounded record size")
                self.at = end
                return value
            except json.JSONDecodeError:
                if self.eof:
                    raise
                self.more()


def _projection_rows(path):
    """Yield metadata and one plan at a time, with bounded decoder buffering."""
    with path.open(encoding="utf-8") as handle:
        reader = _Reader(handle)
        reader.char("{")
        root_keys, seen = set(), set()
        while reader.peek() != "}":
            key = reader.value()
            if not isinstance(key, str) or key in root_keys:
                raise ValueError("invalid/duplicate projection root key")
            root_keys.add(key)
            reader.char(":")
            if key == "plans":
                reader.char("{")
                while reader.peek() != "}":
                    plan_id = reader.value()
                    if not isinstance(plan_id, str) or plan_id in seen or len(plan_id) > 256:
                        raise ValueError("invalid/duplicate plan identity")
                    if len(seen) >= MAX_PLANS:
                        raise PlanReadLimit("projection plan count exceeds bounded scan")
                    seen.add(plan_id)
                    reader.char(":")
                    row = reader.value()
                    if not isinstance(row, dict):
                        raise ValueError("invalid plan row")
                    yield "plan", plan_id, row
                    if reader.peek() == "}":
                        break
                    reader.char(",")
                    if reader.peek() == "}":
                        raise ValueError("trailing comma in plans")
                reader.char("}")
            else:
                yield "meta", key, reader.value()
            if reader.peek() == "}":
                break
            reader.char(",")
            if reader.peek() == "}":
                raise ValueError("trailing comma in projection")
        reader.char("}")
        if "plans" not in root_keys or reader.peek():
            raise ValueError("missing plans or trailing projection data")


def _stamp(path):
    st = path.stat()
    return st.st_ino, st.st_size, st.st_mtime_ns


def _coverage(row):
    result = {key: row.get(key) for key in COVERAGE_KEYS}
    extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    result["extra"] = {key: extra.get(key) for key in ("material", "hermes_result_id")}
    return result


class HomePlanView:
    """The two home reads share this bounded snapshot. Errors stay explicit."""

    def __init__(self, root: Path, *, public_limit=12, coverage_limit=5000):
        self.public_limit, self.coverage_limit = public_limit, coverage_limit
        self._public, self._coverage = [], []
        self.read_state: dict[str, Any] = {"ok": False, "authority": "READ_ONLY_ADVISORY"}
        try:
            self._load(Path(root))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self._public, self._coverage = [], []
            self.read_state.update(error=type(exc).__name__, reason=str(exc)[:180])

    def _load(self, root):
        projection = root / "data/cio/cio_plans_projection.json"
        ledger = root / "data/cio/cio_plans.jsonl"
        initial = _stamp(projection)
        metadata = {}
        for kind, key, value in _projection_rows(projection):
            if kind == "meta":
                metadata[key] = value
        offset = metadata.get("event_offset")
        events: dict[str, list] = {}
        new_order = {}
        tail_bytes = 0
        try:
            event_stamp = _stamp(ledger)
            event_size = event_stamp[1]
        except FileNotFoundError:
            event_stamp = None
            event_size = 0
        # Legacy projections without a valid offset are served as-is by CIOPlanStore.
        # Its read path does not replay until an explicit refresh/write; preserve that.
        if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset <= event_size:
            tail_bytes = event_size - offset
            if tail_bytes > MAX_TAIL_BYTES:
                raise PlanReadLimit("event catch-up exceeds bounded tail")
            if tail_bytes:
                with ledger.open("rb") as handle:
                    handle.seek(offset)
                    raw = handle.read(tail_bytes)
                if len(raw) != tail_bytes:
                    raise ValueError("event ledger shrank during bounded read")
                raw = raw[: raw.rfind(b"\n") + 1]
                for index, line in enumerate(raw.splitlines()):
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if not isinstance(event, dict) or not event.get("plan_id"):
                        continue
                    plan_id = event["plan_id"]
                    events.setdefault(plan_id, []).append(event)
                    if event.get("event_type") == "PLAN_CREATED":
                        new_order.setdefault(plan_id, index)
                del raw
        public, coverage = [], []
        retained, count, total = 0, 0, 0
        applier = object.__new__(CIOPlanStore)  # _apply_event is pure; no constructor/writer path.

        def retain(row, index):
            nonlocal retained, count
            if row.get("status") not in OPENISH:
                return
            count += 1
            rank = (row.get("created_ts") or "", -index)
            for heap, limit, item in (
                (public, self.public_limit, row),
                (coverage, self.coverage_limit, _coverage(row)),
            ):
                if len(heap) < limit or rank > heap[0][0]:
                    cost = len(json.dumps(item, default=str).encode("utf-8"))
                    entry = (rank, item, cost)
                    old = heapq.heapreplace(heap, entry) if len(heap) >= limit else None
                    if old is None:
                        if len(heap) < limit:
                            heapq.heappush(heap, entry)
                    retained += cost - (old[2] if old else 0)
                    if retained > MAX_RETAINED_BYTES:
                        raise PlanReadLimit("retained home inputs exceed bounded view")

        for kind, plan_id, row in _projection_rows(projection):
            if kind != "plan":
                continue
            one = {plan_id: row}
            for event in events.pop(plan_id, []):
                CIOPlanStore._apply_event(applier, one, event)
            retain(one[plan_id], total)
            total += 1
        for plan_id in sorted(events, key=lambda p: new_order.get(p, float("inf"))):
            one = {}
            for event in events[plan_id]:
                CIOPlanStore._apply_event(applier, one, event)
            if plan_id in one:
                retain(one[plan_id], total)
                total += 1
        if _stamp(projection) != initial:
            raise ValueError("projection changed during bounded read")
        if event_stamp is not None:
            current = _stamp(ledger)
            if current[0] != event_stamp[0] or current[1] < event_size:
                raise ValueError("event ledger replaced/shrank during bounded read")
        self._public = [row for rank, row, cost in sorted(public, key=lambda e: e[0], reverse=True)]
        self._coverage = [row for rank, row, cost in sorted(coverage, key=lambda e: e[0], reverse=True)]
        self.read_state.update(
            ok=True,
            projection_bytes=initial[1],
            projection_plan_count=total,
            open_plan_count=count,
            coverage_truncated=count > self.coverage_limit,
            public_limit=self.public_limit,
            coverage_limit=self.coverage_limit,
            event_tail_bytes=tail_bytes,
            retained_bytes=retained,
        )

    def list_open_plans(self, *, limit=50, situation_type=None):
        rows = self._public if limit <= self.public_limit else self._coverage
        if situation_type:
            rows = [row for row in rows if row.get("situation_type") == situation_type]
        return [dict(row) for row in rows[:limit]]
