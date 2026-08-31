"""Bind catalysts to durable entities — Phase C of the identity/memory advisory.

`catalyst_events` holds 133,659 rows and `catalyst_symbol_impact`,
`portfolio_catalyst_summary` and `catalyst_historical_reactions` are all empty.
The catalysts exist; the edges binding them to entities do not. A catalyst keyed
only on a ticker string cannot be traversed, because a ticker is an alias that is
reassigned after delisting — so "every earnings event for this company" is not a
question the current data can answer.

This module supplies the edges, reusing what already exists rather than defining
new contracts:

  * `event_identity.build_event` → `SecurityEvent@v1`, the catalyst lifecycle
    node. It was written months ago with **zero consumers**, because
    `event_guid()` requires an `issuer_guid` and no issuer GUIDs existed until
    Phase A minted them. Phase A is what makes this module possible.
  * `identity_registry` → resolves a ticker to its durable entity.
  * `CatalystTrace@v1` → the edge shape already defined in `r17_producer_links`.

## Why period matters

`event_guid(issuer, event_type, period)` is deliberately period-scoped: earnings
is not a timeless catalyst. Two earnings events for one issuer must be different
nodes or the lifecycle collapses to a single point and chronological traversal
becomes impossible. Period is derived from the publication timestamp at the
granularity the event type warrants — quarterly for earnings, daily for news and
ratings, because two downgrades in one quarter are distinct events while two
earnings reports in one quarter are a data error.

## What this does not do

It does not score, rank or interpret a catalyst, and it never decides materiality.
It answers only "which durable entity is this catalyst about, and which lifecycle
node does it belong to". Materiality already has an owner elsewhere.

Catalysts whose symbol is not a registered entity are counted and skipped, never
bound to a guessed identity — an edge to the wrong company is worse than a
missing edge.

AUTHORITY: READ_ONLY_ADVISORY. MBI=0. No financial action.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from scripts.lib.event_identity import build_event, event_guid
from scripts.lib.identity_registry import load as load_registry, lookup_symbol
from scripts.lib.security_identity import normalize_symbol

try:
    from scripts.lib.hermes_discovery.symbol_validation import is_research_directive_slug
except Exception:  # pragma: no cover — fail-soft; slug filter is belt-and-braces
    def is_research_directive_slug(sym: str) -> bool:  # type: ignore
        return "_" in str(sym or "")

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CatalystEntityBinding@v1"
TRACE_SCHEMA = "CatalystTrace@v1"

# Event types whose natural lifecycle unit is a fiscal quarter. Everything else
# is dated to the day: two analyst downgrades in one quarter are two events,
# while two Q3 earnings reports for one issuer are a data error, not two events.
QUARTERLY_TYPES = frozenset({
    "earnings_beat", "earnings_miss", "earnings", "earnings_preview", "guidance",
})


def period_for(catalyst_type: str, when: Any) -> str | None:
    """Lifecycle bucket for an event. None when the timestamp is unusable.

    A missing period yields no event_guid at all rather than a shared placeholder,
    which would merge unrelated events onto one node.
    """
    dt = _as_dt(when)
    if dt is None:
        return None
    if str(catalyst_type or "").strip().lower() in QUARTERLY_TYPES:
        return f"{dt.year}Q{(dt.month - 1) // 3 + 1}"
    return f"{dt:%Y%m%d}"


def _as_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def bind_catalyst(row: Mapping[str, Any], registry: Mapping[str, Any]) -> dict[str, Any] | None:
    """One catalyst → one `SecurityEvent@v1` node plus its entity edge.

    Returns None when the catalyst cannot be bound honestly: an unregistered
    symbol, an entity with no issuer identity, or an unusable timestamp.
    """
    symbol = normalize_symbol(row.get("symbol"))
    if not symbol:
        return None

    # E1 defense: research-directive / topic slugs are not securities. Refuse
    # before identity lookup so they never mint a wrong-company edge.
    if is_research_directive_slug(symbol):
        return None

    entity = lookup_symbol(registry, symbol)
    if not entity:
        return None

    issuer = entity.get("issuer_guid")
    if not issuer:
        # A ticker-alias-only entity has no issuer to scope the event to. Binding
        # anyway would key the event on the alias, which is what this exists to stop.
        return None

    ctype = str(row.get("catalyst_type") or "other")
    period = period_for(ctype, row.get("published_at") or row.get("created_at"))
    if not period:
        return None

    event = build_event(
        issuer_guid=issuer,
        security_guid=entity.get("security_guid"),
        event_type=ctype,
        period=period,
        status="OCCURRED",  # catalyst_events records what already happened
        as_of=str(row.get("published_at") or row.get("created_at") or ""),
    )
    if not event.get("event_guid"):
        return None

    return {
        "schema": SCHEMA,
        "event": event,
        "trace": {
            "schema": TRACE_SCHEMA,
            "source": str(row.get("source") or "catalyst_events"),
            "catalyst_guid": event["event_guid"],
            "target_security": {
                "symbol": symbol,
                "subject_guid": entity.get("subject_guid"),
                "ticker_guid_is_not_security": True,
            },
            "headline": str(row.get("headline") or "")[:300],
            "catalyst_row_id": row.get("id"),
        },
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def build_graph(rows: Iterable[Mapping[str, Any]],
                registry: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Bind many catalysts. Nodes are deduped by event_guid; edges are not.

    Several catalyst rows legitimately describe one event — two outlets reporting
    one downgrade. They collapse to a single lifecycle node with several traces,
    which is the point: the node is the event, the traces are the observations.
    """
    reg = registry if registry is not None else load_registry()
    nodes: dict[str, dict[str, Any]] = {}
    traces: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    by_type: Counter[str] = Counter()

    for row in rows:
        bound = bind_catalyst(row, reg)
        if not bound:
            sym = normalize_symbol(row.get("symbol"))
            if not sym:
                skipped["no_symbol"] += 1
            elif is_research_directive_slug(sym):
                skipped["research_directive_slug"] += 1
            elif not lookup_symbol(reg, sym):
                skipped["symbol_not_registered"] += 1
            elif not (lookup_symbol(reg, sym) or {}).get("issuer_guid"):
                skipped["entity_has_no_issuer"] += 1
            else:
                skipped["unusable_timestamp"] += 1
            continue
        guid = bound["event"]["event_guid"]
        nodes.setdefault(guid, bound["event"])
        traces.append(bound["trace"])
        by_type[bound["event"]["event_type"]] += 1

    return {
        "schema": "CatalystGraph@v1",
        "nodes": list(nodes.values()),
        "traces": traces,
        "node_count": len(nodes),
        "trace_count": len(traces),
        "bound_by_type": dict(by_type.most_common(12)),
        "skipped": dict(skipped),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def events_for_entity(graph: Mapping[str, Any], subject_guid: str) -> list[dict[str, Any]]:
    """Every lifecycle node touching one entity, oldest first.

    This is the chronological traversal the graph exists to enable: given a
    durable entity id, every catalyst in its life, in order, regardless of what
    ticker it traded under at the time.
    """
    wanted = {
        t["catalyst_guid"] for t in (graph.get("traces") or [])
        if (t.get("target_security") or {}).get("subject_guid") == subject_guid
    }
    hits = [n for n in (graph.get("nodes") or []) if n.get("event_guid") in wanted]
    return sorted(hits, key=lambda n: str(n.get("as_of") or ""))
