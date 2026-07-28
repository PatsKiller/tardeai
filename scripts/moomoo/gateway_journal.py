"""Append-only durable observation journal for Moomoo L2 and fire replay.

The service writes normalized market-data observations; API processes only read them. The
journal contains no credentials or orders and is bounded by daily files / configured retention.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional

try:
    from .gateway_ipc import expand_path, parse_iso, utc_now_iso
except ImportError:  # pragma: no cover
    from gateway_ipc import expand_path, parse_iso, utc_now_iso  # type: ignore

EVENT_CONTRACT = "moomoo-l2-gateway-event-v1"


@dataclass(frozen=True)
class ReplayExtrema:
    high: Optional[float]
    low: Optional[float]
    coverage_complete: bool
    coverage_reason: str
    observation_count: int
    first_observed_at: Optional[str]
    last_observed_at: Optional[str]


class GatewayJournal:
    def __init__(self, directory: str | Path, *, retention_days: int = 14):
        self.directory = expand_path(directory)
        self.retention_days = max(1, int(retention_days))

    def _path_for(self, event_at: str | datetime | None = None) -> Path:
        if isinstance(event_at, datetime):
            dt = event_at
        else:
            dt = parse_iso(event_at) or datetime.now(timezone.utc)
        return self.directory / f"moomoo-l2-{dt.astimezone(timezone.utc).date().isoformat()}.jsonl"

    def make_event(
        self,
        event_type: str,
        *,
        symbol: Optional[str] = None,
        event_at: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        return {
            "contract": EVENT_CONTRACT,
            "event_id": str(uuid.uuid4()),
            "event_type": str(event_type),
            "event_at": event_at or utc_now_iso(),
            "symbol": str(symbol).upper() if symbol else None,
            "payload": dict(payload or {}),
        }

    def append_events(self, events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Append a batch and fsync once per daily file."""
        prepared = [dict(event) for event in events]
        if not prepared:
            return []
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        grouped: dict[Path, list[dict[str, Any]]] = {}
        for event in prepared:
            if event.get("contract") != EVENT_CONTRACT:
                raise ValueError("journal event contract mismatch")
            grouped.setdefault(self._path_for(event.get("event_at")), []).append(event)
        for path, batch in grouped.items():
            descriptor = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                encoded = "".join(
                    json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
                    for event in batch
                ).encode()
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
        return prepared

    def append(
        self,
        event_type: str,
        *,
        symbol: Optional[str] = None,
        event_at: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        body = self.make_event(
            event_type, symbol=symbol, event_at=event_at, payload=payload
        )
        self.append_events([body])
        return body

    def prune(self, *, today: Optional[date] = None) -> list[str]:
        cutoff = (today or datetime.now(timezone.utc).date()) - timedelta(days=self.retention_days)
        removed: list[str] = []
        if not self.directory.is_dir():
            return removed
        for path in self.directory.glob("moomoo-l2-*.jsonl"):
            try:
                day = date.fromisoformat(path.stem.replace("moomoo-l2-", ""))
            except ValueError:
                continue
            if day < cutoff:
                path.unlink(missing_ok=True)
                removed.append(path.name)
        return removed

    def _paths_between(self, start: datetime, end: datetime) -> list[Path]:
        day = start.astimezone(timezone.utc).date()
        last = end.astimezone(timezone.utc).date()
        paths: list[Path] = []
        while day <= last:
            path = self.directory / f"moomoo-l2-{day.isoformat()}.jsonl"
            if path.is_file():
                paths.append(path)
            day += timedelta(days=1)
        return paths

    def iter_events(
        self,
        *,
        start_at: str | datetime,
        end_at: str | datetime,
        symbols: Optional[Iterable[str]] = None,
        event_types: Optional[Iterable[str]] = None,
    ) -> Iterator[dict[str, Any]]:
        start = start_at if isinstance(start_at, datetime) else parse_iso(start_at)
        end = end_at if isinstance(end_at, datetime) else parse_iso(end_at)
        if start is None or end is None:
            return
        wanted_symbols = {str(value).upper() for value in symbols or ()}
        wanted_types = {str(value) for value in event_types or ()}
        for path in self._paths_between(start, end):
            try:
                handle = path.open("r", encoding="utf-8")
            except OSError:
                continue
            with handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("contract") != EVENT_CONTRACT:
                        continue
                    when = parse_iso(event.get("event_at"))
                    if when is None or when < start or when > end:
                        continue
                    if wanted_symbols and str(event.get("symbol") or "").upper() not in wanted_symbols:
                        continue
                    if wanted_types and event.get("event_type") not in wanted_types:
                        continue
                    yield event

    def replay_extrema(self, symbol: str, fired_at: str, now_iso: str) -> ReplayExtrema:
        start = parse_iso(fired_at)
        end = parse_iso(now_iso)
        if start is None or end is None:
            return ReplayExtrema(None, None, False, "INVALID_TIME_RANGE", 0, None, None)
        # Read a small pre-fire window to establish whether continuous coverage already existed.
        search_start = start - timedelta(hours=12)
        events = list(
            self.iter_events(
                start_at=search_start,
                end_at=end,
                symbols=[symbol],
                event_types=["COVERAGE_START", "COVERAGE_GAP", "MARK"],
            )
        )
        coverage_start: Optional[datetime] = None
        gap_after_start = False
        high: Optional[float] = None
        low: Optional[float] = None
        count = 0
        first_at: Optional[str] = None
        last_at: Optional[str] = None
        for event in events:
            when = parse_iso(event.get("event_at"))
            if when is None:
                continue
            event_type = event.get("event_type")
            if event_type == "COVERAGE_START":
                coverage_start = when
                gap_after_start = False
                continue
            if event_type == "COVERAGE_GAP":
                if coverage_start is not None and when >= coverage_start:
                    gap_after_start = True
                continue
            if event_type != "MARK" or when < start:
                continue
            payload = event.get("payload") or {}
            def number(raw):
                try:
                    value = float(raw)
                    return value if value == value and value > 0 else None
                except (TypeError, ValueError):
                    return None

            last = number(payload.get("last"))
            bid = number(payload.get("bid"))
            ask = number(payload.get("ask"))
            mark = last
            if mark is None and bid is not None and ask is not None:
                mark = (bid + ask) / 2.0
            if mark is None:
                mark = bid if bid is not None else ask
            if mark is None:
                continue
            mark_high = mark_low = mark
            high = mark_high if high is None else max(high, mark_high)
            low = mark_low if low is None else min(low, mark_low)
            count += 1
            first_at = first_at or event.get("event_at")
            last_at = event.get("event_at")
        complete = bool(coverage_start is not None and coverage_start <= start and not gap_after_start)
        reason = "COMPLETE" if complete else (
            "GAP_AFTER_COVERAGE_START" if gap_after_start else "NO_COVERAGE_START_BEFORE_FIRE"
        )
        return ReplayExtrema(high, low, complete, reason, count, first_at, last_at)


class JournalBackedFirePerfTracker:
    """Drop-in tracker using durable observations instead of process-local extrema."""

    def __init__(self, journal: GatewayJournal, cfg, *, cache_seconds: float = 1.0):
        self.journal = journal
        self.cfg = cfg
        self.cache_seconds = max(0.0, float(cache_seconds))
        self._cache: dict[tuple[str, str, str], tuple[float, ReplayExtrema]] = {}

    def _replay(self, symbol: str, fired_at: str, now_iso: str) -> ReplayExtrema:
        key = (symbol.upper(), fired_at, now_iso[:16])
        cached = self._cache.get(key)
        now_mono = time.monotonic()
        if cached and now_mono - cached[0] <= self.cache_seconds:
            return cached[1]
        value = self.journal.replay_extrema(symbol, fired_at, now_iso)
        self._cache[key] = (now_mono, value)
        if len(self._cache) > 1024:
            for old_key in list(self._cache)[:256]:
                self._cache.pop(old_key, None)
        return value

    def update(self, fire: dict[str, Any], **kwargs) -> dict[str, Any]:
        try:
            from active_trader.fire_performance import compute_fire_performance
        except ImportError:  # pragma: no cover
            from ..active_trader.fire_performance import compute_fire_performance  # type: ignore
        symbol = str(fire.get("symbol") or "").upper()
        fired_at = str(fire.get("fired_at") or "")
        now_iso = str(kwargs["now_iso"])
        replay = self._replay(symbol, fired_at, now_iso)
        result = compute_fire_performance(
            fire,
            current_bid=kwargs.get("current_bid"),
            current_ask=kwargs.get("current_ask"),
            current_last=kwargs.get("current_last"),
            mark_source=kwargs.get("mark_source"),
            mark_at_iso=kwargs.get("mark_at_iso"),
            now_iso=now_iso,
            cfg=self.cfg,
            prior_high=replay.high,
            prior_low=replay.low,
            l2_state_now=kwargs.get("l2_state_now"),
            finalized_outcome=kwargs.get("finalized_outcome"),
        )
        result["mfe_mae_scope"] = "DURABLE_JOURNAL_REPLAY"
        result["coverage_complete_since_fire"] = replay.coverage_complete
        result["coverage_reason"] = replay.coverage_reason
        result["replay_observation_count"] = replay.observation_count
        result["replay_first_observed_at"] = replay.first_observed_at
        result["replay_last_observed_at"] = replay.last_observed_at
        return result
