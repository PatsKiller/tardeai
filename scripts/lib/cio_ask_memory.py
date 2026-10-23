"""Ask the CIO — persistent memory across the CIO system. READ_ONLY_ADVISORY.

Operator 2026-10-23: "the key is the persistent memory. Across the CIO system." and (NO SILOS) "Anything ... for the
security. The CIO agent needs to have it in memory."

Every ask, entity resolution, answer version, source, follow-up and tracking change about a security is appended to
the CIO-owned **SecurityResearchSpine** (``scripts/lib/cross_asset/security_research_spine.py``, the shared research
memory every silo reads through ``view_for_silo``), keyed by the registry ``security_guid``, as a ``silo="cio"``
contribution tagged ``ask_the_cio``. The CIO recalls prior questions and answers on the same security from there —
across channels (CC and Telegram) and across threads.

A private entity (no listed security, e.g. a pre-IPO company) has no spine (the spine needs a ticker and a registry
GUID, and we never invent a ticker). Its memory is the ask ledger keyed by ``entity_guid``; ``recall`` reads it there.

The M2 bitemporal memory is not written from here: the memory chokepoint (scripts/check_memory_chokepoint.py) allows
M2 only through scripts/lib/intelligence_client.py, and the Phase 9 research path already appends its sourced facts
to M2 through CIOEnvelopeIntegrator. The spine is the memory of record for asks.

Nothing written here carries a BEHAVIOR_FIELDS key (§2): memory items are text summaries and ids only — never an
operator-named quantity, exposure dollars or a reference stop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Protocol

from scripts.lib.cio_ask_contract import EntityRef, MEMORY_KINDS

ASK_TAG = "ask_the_cio"


class AskMemory(Protocol):
    def append(self, *, entity: EntityRef, kind: str, summary: str, ref: str, extra: Optional[dict] = None) -> dict: ...

    def recall(self, *, entity: EntityRef, limit: int = 6, exclude_refs: tuple[str, ...] = ()) -> list[dict]: ...


def _excerpt(text: Any, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


class SpineAskMemory:
    """Default memory: research spine for securities, ask ledger for private entities."""

    def __init__(self, *, spine_path: Optional[Path] = None, ledger=None):
        self.spine_path = spine_path
        self.ledger = ledger

    # ── write ──────────────────────────────────────────────────────────────────────────────────────────────────────
    def append(self, *, entity: EntityRef, kind: str, summary: str, ref: str, extra: Optional[dict] = None) -> dict:
        if kind not in MEMORY_KINDS:
            raise ValueError(f"unknown memory kind {kind!r}")
        receipt: dict[str, Any] = {"kind": kind, "ref": ref, "key": entity.memory_key, "spine": None}
        if entity.kind == "security" and entity.symbol and entity.security_guid:
            from scripts.lib.cross_asset.security_research_spine import upsert_research_memory  # noqa: PLC0415

            text = f"[{kind}] {_excerpt(summary, 700)}"
            res = upsert_research_memory(
                entity.symbol,
                silo="cio",
                kind=kind,
                summary=text,
                artifact_id=ref,
                refs=[ref],
                tags=[ASK_TAG, kind.replace(".", "_")],
                operator={"pending_id": ref, "kind": kind, "text": text}
                if kind in ("ask.asked", "ask.follow_up")
                else None,
                subject_guid=entity.security_guid,
                issuer_guid=entity.issuer_guid,
                path=self.spine_path,
            )
            receipt["spine"] = {k: res.get(k) for k in ("ok", "error", "path") if k in res}
        else:
            receipt["spine"] = {"ok": False, "skipped": "no listed security — ledger is the memory (entity_guid)"}
        return receipt

    # ── read ───────────────────────────────────────────────────────────────────────────────────────────────────────
    def recall(self, *, entity: EntityRef, limit: int = 6, exclude_refs: tuple[str, ...] = ()) -> list[dict]:
        """Prior ask memory on this entity, newest first: [{at, kind, summary, ref, source}]."""
        items: list[dict] = []
        if entity.kind == "security" and entity.symbol:
            try:
                from scripts.lib.cross_asset.security_research_spine import load_latest  # noqa: PLC0415

                sp = load_latest(entity.symbol, path=self.spine_path) or {}
                if entity.security_guid and sp.get("subject_guid") and sp["subject_guid"] != entity.security_guid:
                    sp = {}  # a different security under the same ticker: never recall across identities
                for c in sp.get("contributions") or []:
                    if ASK_TAG not in (c.get("tags") or []):
                        continue
                    items.append(
                        {
                            "at": c.get("ts"),
                            "kind": c.get("kind"),
                            "summary": c.get("summary"),
                            "ref": c.get("artifact_id"),
                            "source": "security_research_spine",
                        }
                    )
            except Exception:  # noqa: BLE001
                items = []
        if self.ledger is not None:
            # The spine keeps the last 100 contributions per security; the ledger keeps every ask. Merge by ref.
            seen = {str(i.get("ref")) for i in items}
            items += [i for i in self._recall_ledger(entity) if str(i.get("ref")) not in seen]
        items = [i for i in items if not any(str(i.get("ref") or "").startswith(x) for x in exclude_refs if x)]
        items.sort(key=lambda i: str(i.get("at") or ""), reverse=True)
        return items[:limit]

    def _recall_ledger(self, entity: EntityRef) -> list[dict]:
        key = entity.memory_key
        if not key:
            return []
        threads = self.ledger.threads()
        out: list[dict] = []
        for t in threads.values():
            if not any(e.get("key") == key for e in t["entities"]):
                continue
            for turn in t["turns"]:
                out.append(
                    {
                        "at": turn.get("asked_at"),
                        "kind": "ask.asked",
                        "summary": f"[ask.asked] {turn.get('question')}",
                        "ref": turn.get("ask_id"),
                        "source": "cio_ask_events",
                    }
                )
                for a in turn.get("answers") or []:
                    out.append(
                        {
                            "at": a.get("produced_at"),
                            "kind": "ask.answer_version",
                            "summary": f"[ask.answer_version] {_excerpt(a.get('summary'), 400)}",
                            "ref": f"{turn.get('ask_id')}:v{a.get('version')}",
                            "source": "cio_ask_events",
                        }
                    )
        return out


def format_recall(entity: EntityRef, items: list[dict], *, max_items: int = 4) -> str:
    """The 'Earlier on X' block the operator sees. Empty string when there is nothing to recall."""
    if not items:
        return ""
    label = entity.symbol or entity.name
    lines = [f"Earlier on {label} (CIO memory):"]
    for it in items[:max_items]:
        when = str(it.get("at") or "")[:10]
        body = str(it.get("summary") or "")
        body = body.split("] ", 1)[1] if body.startswith("[") and "] " in body else body
        verb = "you asked" if it.get("kind") in ("ask.asked", "ask.follow_up") else "I answered"
        if it.get("kind") == "ask.tracking_changed":
            verb = "tracking"
        elif it.get("kind") == "ask.reanswer_triggered":
            verb = "re-answered after"
        lines.append(f'- {when} {verb}: "{_excerpt(body, 160)}"')
    return "\n".join(lines)


__all__ = ["AskMemory", "SpineAskMemory", "format_recall", "ASK_TAG"]
