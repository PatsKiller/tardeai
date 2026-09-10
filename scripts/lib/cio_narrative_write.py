#!/usr/bin/env python3
"""The one place a narrative becomes durable, with its identity attached.

Fifteen surfaces on this system hold a narrative, thesis, rationale or summary,
and on 2026-09-10 fourteen of them wrote it with no identity at all. Each had its
own writer, its own shape, and no shared notion of what the text was ABOUT. This
module is the chokepoint that makes the CIO the owner of all of it.

WHAT "CIO OWNS IT" MEANS HERE, PRECISELY. Two separable things, and conflating
them is what makes this kind of refactor stall:

  * OWNERSHIP OF PERSISTENCE AND IDENTITY -- the text already exists, and the CIO
    routes it through here so it acquires subjects, citations, an author and a
    schema. Text in equals text out. Every lane gets this immediately.
  * OWNERSHIP OF COMPOSITION -- the CIO writes the prose itself, replacing
    template output. This is a model call, so it is governed by the existing lane
    policy and its budget, and it is enabled per lane rather than everywhere at
    once. High-volume lanes compose on material change, not on every tick.

There is deliberately NO dual-write mode. For a lane in the first category a
comparison proves nothing a unit test does not; for a lane in the second the
text is SUPPOSED to differ, so a comparison gate would fail by design. Running
two writers to feel safe would have bought ambiguity about which one is
authoritative -- and this repo already carries enough of that.

FAIL-SAFE, NOT FAIL-CLOSED. If identity resolution throws, the narrative still
persists, untagged, and the miss is reported. An untagged watchlist row is a
degraded row; a lost one is a blank surface the operator depends on. This is the
one place that trade-off runs the opposite way to the rest of the campaign, and
it is deliberate: the gate protecting a paid provider call should fail closed,
the gate protecting a display row should not.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0 -- modelled on
cio_instrument_record.apply_cognition(), which raises BehaviorWriteRefused rather
than let cognition carry a behaviour field. A narrative may say what the desk
thinks; it can never size, order, stop or weight anything.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Iterable, Mapping

from scripts.lib.cio_narrative_subjects import build_links

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "NarrativeSubjectLink@v1"

#: Never allowed on a narrative write. Mirrors cio_instrument_record.BEHAVIOR_FIELDS.
#: A narrative that carries a size or a stop is not a narrative.
BEHAVIOR_FIELDS = frozenset({
    "quantity", "shares", "size", "weight", "stop", "stop_price", "limit_price",
    "order_type", "side", "notional", "target_weight", "allocation",
})


class NarrativeBehaviorRefused(ValueError):
    """MBI_BEHAVIOR=0. A narrative may never carry a behaviour field."""


def row_guid_for(source_table: str, source_id: Any, *, discriminator: str = "") -> str:
    """Deterministic row identity for a lane that has no guid of its own.

    Most of the fifteen surfaces have an integer PK and nothing stable to hang a
    link on. uuid5 over (table, pk) gives them one without a migration, and makes
    re-ingestion idempotent.
    """
    basis = f"tradeai:narrative_row:{source_table}|{source_id}"
    if discriminator:
        basis = f"{basis}|{discriminator}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, basis))


def ground(sentences: Iterable[Mapping[str, Any]], allowed: Iterable[str]) -> list[dict]:
    """Drop any sentence citing evidence that is not in the dossier.

    Lifted from due_diligence_questions.ground(), which is the only narrative
    lane that already did this. A sentence whose citation does not resolve is
    indistinguishable from an invention, and the desk's whole claim to be
    evidence-led rests on the difference.
    """
    ok = set(allowed or ())
    out: list[dict] = []
    for s in sentences or []:
        cites = [c for c in (s.get("cites") or []) if c in ok]
        if not cites:
            continue
        out.append({"sentence": s.get("sentence"), "cites": sorted(cites)})
    return out


def write_narrative(
    cur=None,
    *,
    executor: Any = None,
    source_table: str,
    source_id: Any,
    subjects: Iterable[Mapping[str, Any]],
    sentences: Iterable[Mapping[str, Any]] | None = None,
    dossier_ids: Iterable[str] | None = None,
    author_agent_id: str = "cio",
    lane: str | None = None,
    model: str | None = None,
    row_guid: str | None = None,
    composed: bool = False,
    **forbidden: Any,
) -> dict[str, Any]:
    """Attach identity to one narrative and persist its links. Returns a report.

    Pass either `cur` (an open cursor, caller owns the transaction so the
    narrative row and its links commit together) or `executor` (the injected
    `(sql, params) -> result` callable used by two_way_curation and db_adapter).
    Fifteen lanes do not share one DB idiom, and forcing them to would mean
    touching fifteen transaction boundaries to add identity -- which is how a
    tagging change turns into an outage.

    `composed` records whether the CIO wrote the prose or merely took ownership
    of persistence, so a later audit can tell which lanes have actually been
    upgraded and which are only tagged.
    """
    if forbidden:
        bad = sorted(k for k in forbidden if k in BEHAVIOR_FIELDS) or sorted(forbidden)
        raise NarrativeBehaviorRefused(
            f"MBI_BEHAVIOR=0: a narrative may not carry {bad}")

    rg = row_guid or row_guid_for(source_table, source_id)
    grounded = ground(sentences or [], dossier_ids or []) if sentences is not None else []
    cited = sorted({c for s in grounded for c in s["cites"]})

    links: list[dict] = []
    misses: list[dict] = []
    try:
        links, misses = build_links(
            row_guid=rg, source_table=source_table, source_id=source_id,
            subjects=subjects, author_agent_id=author_agent_id)
    except Exception as exc:  # fail-safe -- see module docstring
        misses = [{"error": type(exc).__name__, "detail": str(exc)[:200]}]

    def _run(sql, params):
        if executor is not None:
            return executor(sql, params)
        cur.execute(sql, params)
        return getattr(cur, "rowcount", 1)

    written = 0
    for link in links:
        try:
            res = _run(
                """INSERT INTO narrative_subjects
                     (link_guid, row_guid, source_table, source_id, entity_type,
                      subject_guid, semantic_subject, relationship, confidence,
                      author_agent_id, schema_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (link_guid) DO NOTHING""",
                (link["link_guid"], link["row_guid"], link["source_table"],
                 link["source_id"], link["entity_type"], link["subject_guid"],
                 link["semantic_subject"], link["relationship"], link["confidence"],
                 link["author_agent_id"], link["schema_version"]))
            written += 1 if (res is None or res) else 0
        except Exception as exc:
            misses.append({"link_guid": link["link_guid"],
                           "error": type(exc).__name__, "detail": str(exc)[:200]})

    return {
        "schema": SCHEMA,
        "row_guid": rg,
        "source_table": source_table,
        "source_id": str(source_id),
        "author_agent_id": author_agent_id,
        "composed": bool(composed),
        "lane": lane,
        "model": model,
        "authority": AUTHORITY,
        "links_built": len(links),
        "links_written": written,
        "misses": misses,
        "sentences": grounded,
        "cited_ids": cited,
    }


def remember(report: Mapping[str, Any], *, symbols: Iterable[str] | None = None) -> str | None:
    """Hand the narrative to durable memory so the next wake can read it back.

    agent_durable_memory is the only memory path already on the identity spine.
    Its own docstring records the defect this avoids repeating: "441 live records
    carried `symbols`, none carried a `subject_guid`". Failure here is reported,
    never raised -- memory is an enrichment, and losing it must not lose the
    narrative.
    """
    try:
        from scripts.lib.agent_durable_memory import get_durable_provider

        guids = [l for l in (report.get("subject_guids") or [])]
        record = {
            "memory_type": "SEMANTIC_OPERATOR",
            "text": " ".join(s.get("sentence") or "" for s in report.get("sentences") or []),
            "symbols": list(symbols or []),
            "subject_guids": guids,
            "source_type": report.get("source_table"),
            "source_id": report.get("source_id"),
            "asserted_by": report.get("author_agent_id") or "cio",
            "authority": AUTHORITY,
        }
        return get_durable_provider().add_candidate(record)
    except Exception:
        return None


__all__ = [
    "SCHEMA", "AUTHORITY", "MBI", "BEHAVIOR_FIELDS",
    "NarrativeBehaviorRefused", "row_guid_for", "ground",
    "write_narrative", "remember",
]
