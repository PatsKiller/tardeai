from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

AGENT_NAMESPACE = "tradeai.agent"
ENTITY_NAMESPACE = "tradeai.agent_runtime"
_SHORT_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_KIND = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def qualified_agent_id(short_id: str) -> str:
    value = str(short_id or "").strip().lower()
    if not _SHORT_ID.fullmatch(value):
        raise ValueError(f"invalid agent short id: {short_id}")
    return f"{AGENT_NAMESPACE}.{value}"


def stable_entity_id(kind: str, *parts: object) -> str:
    entity_kind = str(kind or "").strip().lower()
    if not _KIND.fullmatch(entity_kind):
        raise ValueError(f"invalid entity kind: {kind}")
    normalized = [str(part).strip() for part in parts]
    if not normalized or any(not part for part in normalized):
        raise ValueError("stable entity ids require non-empty identity parts")
    material = "\x1f".join([ENTITY_NAMESPACE, entity_kind, *normalized])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"ta:{entity_kind}:{digest}"


@dataclass(frozen=True)
class AgentIdentity:
    short_id: str

    @property
    def qualified_id(self) -> str:
        return qualified_agent_id(self.short_id)

    def entity_id(self, kind: str, parts: Iterable[object]) -> str:
        return stable_entity_id(kind, self.qualified_id, *tuple(parts))
