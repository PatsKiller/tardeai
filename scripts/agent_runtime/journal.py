from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import Environment, canonical_hash


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    created_at: str
    previous_hash: str
    event_hash: str


class ShadowRunJournal:
    """Append-only LAB/SHADOW run journal used before Postgres activation.

    The canonical production target is the additive Postgres MVL schema. This
    file journal exists for deterministic unit/replay testing and shadow runs.
    It refuses production-looking locations and never stores secrets.
    """

    def __init__(self, root: str | Path, environment: Environment) -> None:
        if environment not in {Environment.LAB, Environment.SHADOW}:
            raise ValueError("journal environment must be LAB or SHADOW")
        self.environment = environment
        self.root = Path(root).expanduser().resolve()
        lowered = str(self.root).lower()
        if any(fragment in lowered for fragment in ("trade-ai-prod", "/prod/", "production")):
            raise ValueError("shadow journal refuses production-looking paths")
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def _path(self, run_id: str) -> Path:
        safe = "".join(character for character in run_id if character.isalnum() or character in "-_")
        if not safe or safe != run_id:
            raise ValueError("run_id contains unsupported characters")
        return self.root / f"{safe}.jsonl"

    def events(self, run_id: str) -> list[RunEvent]:
        path = self._path(run_id)
        if not path.exists():
            return []
        output: list[RunEvent] = []
        previous = "0" * 64
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            data = json.loads(raw)
            event = RunEvent(**data)
            expected = canonical_hash({
                "run_id": event.run_id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at,
                "previous_hash": event.previous_hash,
            })
            if event.previous_hash != previous or event.event_hash != expected:
                raise ValueError(f"run journal hash-chain failure at line {line_number}")
            output.append(event)
            previous = event.event_hash
        return output

    def append(self, run_id: str, event_type: str, payload: Mapping[str, Any]) -> RunEvent:
        prior = self.events(run_id)
        sequence = len(prior) + 1
        previous_hash = prior[-1].event_hash if prior else "0" * 64
        created_at = datetime.now(timezone.utc).isoformat()
        body = {
            "run_id": run_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": dict(payload),
            "created_at": created_at,
            "previous_hash": previous_hash,
        }
        event = RunEvent(**body, event_hash=canonical_hash(body))
        path = self._path(run_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return event

    def latest(self, run_id: str, event_type: str | None = None) -> RunEvent | None:
        events = self.events(run_id)
        if event_type is None:
            return events[-1] if events else None
        for event in reversed(events):
            if event.event_type == event_type:
                return event
        return None

    def replay(self, run_id: str) -> dict[str, Any]:
        state: dict[str, Any] = {"run_id": run_id, "sequence": 0, "status": "UNKNOWN"}
        for event in self.events(run_id):
            state["sequence"] = event.sequence
            state["last_event_hash"] = event.event_hash
            state["last_event_type"] = event.event_type
            state["updated_at"] = event.created_at
            state.update(event.payload)
        return state

    def list_run_ids(self) -> Iterable[str]:
        for path in sorted(self.root.glob("*.jsonl")):
            yield path.stem
