"""Claim / evidence graph.

A recommendation should expose actual causal evidence, not another generated
narrative. Nodes are FACT, CLAIM, SOURCE, MEMORY_REF, CASE_REF,
SPECIALIST_OPINION, DECISION; edges are SUPPORTS, CONTRADICTS, DEPENDS_ON,
QUALIFIES, INVALIDATES, DERIVED_FROM, USED_BY.

Provenance invariants (fail closed):
  * every FACT requires source + observed_at/as_of + quality
  * every derived CLAIM requires incoming evidence (else UNSUPPORTED)
  * contradictions are preserved, never deleted
  * MEMORY_REF edges are NON_AUTHORITATIVE_CONTEXT and cannot replace FACTs
Pure module: no network, no database.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from .provider import BaseProvider, Capability
from .result import FinancialSenseResult, STATUS_OK
from .source_governance import (
    FRESHNESS_STALE,
    SOURCE_MEMORY_CONTEXT,
    SOURCE_MODEL_INFERENCE,
    can_back_fact,
)

NODE_FACT = "FACT"
NODE_CLAIM = "CLAIM"
NODE_SOURCE = "SOURCE"
NODE_MEMORY_REF = "MEMORY_REF"
NODE_CASE_REF = "CASE_REF"
NODE_SPECIALIST_OPINION = "SPECIALIST_OPINION"
NODE_DECISION = "DECISION"
VALID_NODE_TYPES = frozenset(
    {
        NODE_FACT,
        NODE_CLAIM,
        NODE_SOURCE,
        NODE_MEMORY_REF,
        NODE_CASE_REF,
        NODE_SPECIALIST_OPINION,
        NODE_DECISION,
    }
)

EDGE_SUPPORTS = "SUPPORTS"
EDGE_CONTRADICTS = "CONTRADICTS"
EDGE_DEPENDS_ON = "DEPENDS_ON"
EDGE_QUALIFIES = "QUALIFIES"
EDGE_INVALIDATES = "INVALIDATES"
EDGE_DERIVED_FROM = "DERIVED_FROM"
EDGE_USED_BY = "USED_BY"
VALID_EDGE_RELATIONS = frozenset(
    {
        EDGE_SUPPORTS,
        EDGE_CONTRADICTS,
        EDGE_DEPENDS_ON,
        EDGE_QUALIFIES,
        EDGE_INVALIDATES,
        EDGE_DERIVED_FROM,
        EDGE_USED_BY,
    }
)

UNSUPPORTED = "UNSUPPORTED"
CONTEXTUAL_ONLY = "CONTEXTUAL_ONLY"
SUPPORTED = "SUPPORTED"
CONTESTED = "CONTESTED"

# Edges that count as positive evidence for a claim.
_EVIDENCE_IN = frozenset({EDGE_SUPPORTS, EDGE_DERIVED_FROM, EDGE_QUALIFIES})


@dataclass
class GraphNode:
    id: str
    type: str
    text: Optional[str] = None
    claim_type: Optional[str] = None
    subject: Optional[str] = None
    created_at: Optional[str] = None
    as_of: Optional[str] = None
    status: Optional[str] = None
    confidence: Optional[float] = None
    quality: Optional[str] = None
    source: Optional[str] = None
    observed_at: Optional[str] = None
    freshness: Optional[str] = None
    fields: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GraphEdge:
    id: str
    from_id: str
    to_id: str
    relation: str
    strength: Optional[str] = None
    source_age: Optional[str] = None
    quality: Optional[str] = None
    created_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClaimEvidenceGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []
        self.edge_ids: set[str] = set()

    def add_node(self, node: dict) -> None:
        n = GraphNode(**node)
        n.created_at = n.created_at or _now()
        self.nodes[n.id] = n

    def add_edge(self, edge: dict) -> None:
        e = GraphEdge(**edge)
        e.created_at = e.created_at or _now()
        self.edge_ids.add(e.id)
        self.edges.append(e)

    def validate(self) -> list[str]:
        errors: list[str] = []
        for nid, node in self.nodes.items():
            if node.type not in VALID_NODE_TYPES:
                errors.append(f"node {nid}: invalid type {node.type!r}")
            if node.type == NODE_FACT:
                if not node.source or not can_back_fact(node.source):
                    errors.append(
                        f"FACT {nid}: source required and must be fact-capable (got {node.source!r})"
                    )
                if not (node.observed_at or node.as_of):
                    errors.append(f"FACT {nid}: observed_at or as_of required")
                if not node.quality:
                    errors.append(f"FACT {nid}: quality required")
            if node.type == NODE_CLAIM:
                if not node.text:
                    errors.append(f"CLAIM {nid}: text required")
                if not node.claim_type:
                    errors.append(f"CLAIM {nid}: claim_type required")
        seen_edges: set[str] = set()
        for e in self.edges:
            if e.relation not in VALID_EDGE_RELATIONS:
                errors.append(f"edge {e.id}: invalid relation {e.relation!r}")
            if e.from_id not in self.nodes:
                errors.append(f"edge {e.id}: from_id {e.from_id!r} not a node")
            if e.to_id not in self.nodes:
                errors.append(f"edge {e.id}: to_id {e.to_id!r} not a node")
            if e.id in seen_edges:
                errors.append(f"edge {e.id}: duplicate edge id")
            seen_edges.add(e.id)
        # Claims: classify evidence and assign a support status.
        for nid, node in self.nodes.items():
            if node.type == NODE_CLAIM:
                authoritative, contextual, contradiction, _stale = self._evidence_classification(nid)
                if not authoritative and not contextual and not contradiction:
                    node.status = UNSUPPORTED
                elif not authoritative and contextual:
                    # MEMORY_REF is context, not a substitute for a FACT.
                    node.status = CONTEXTUAL_ONLY
                elif contradiction:
                    node.status = CONTESTED
                else:
                    node.status = SUPPORTED
        return errors

    def _evidence_classification(self, claim_id: str):
        """Split a claim's incoming evidence into authority classes.

        Returns (authoritative_fact_support, contextual_support, contradiction,
        stale_fact_support). A MEMORY_REF source is contextual, never
        authoritative.
        """
        authoritative = []
        contextual = []
        contradiction = []
        stale_support = []
        for e in self.edges:
            if e.to_id != claim_id:
                continue
            src = self.nodes.get(e.from_id)
            src_type = src.type if src else None
            src_fresh = (src.freshness or "").upper() if src else ""
            if e.relation == EDGE_CONTRADICTS:
                contradiction.append(e.to_dict())
            elif e.relation in _EVIDENCE_IN:
                if src_type == NODE_MEMORY_REF:
                    contextual.append(e.to_dict())
                else:
                    authoritative.append(e.to_dict())
                if src_fresh == FRESHNESS_STALE:
                    stale_support.append(e.to_dict())
        return authoritative, contextual, contradiction, stale_support

    def claim_evidence(self, claim_id: str) -> dict:
        authoritative, contextual, contradiction, stale_support = self._evidence_classification(claim_id)
        node = self.nodes.get(claim_id)
        # A claim is actionable only with authoritative (fact-backed) support
        # that is not stale. Stale facts remain historical evidence.
        actionable = bool(authoritative) and not stale_support
        return {
            "claim": node.to_dict() if node else None,
            "authoritative_fact_support": authoritative,
            "contextual_support": contextual,
            "contradiction": contradiction,
            "supporting": authoritative + contextual,
            "contradicting": contradiction,
            "stale_fact_support": stale_support,
            "actionable": actionable,
            "status": node.status if node else UNSUPPORTED,
        }

    def detect_cycles(self) -> list[list[str]]:
        """Return cycles in the directed from_id -> to_id graph."""
        adj: dict[str, list[str]] = {}
        for e in self.edges:
            adj.setdefault(e.from_id, []).append(e.to_id)
        color: dict[str, int] = {}
        stack: list[str] = []
        cycles: list[list[str]] = []

        def dfs(u: str) -> None:
            color[u] = 1
            stack.append(u)
            for v in adj.get(u, []):
                if color.get(v) == 0:
                    dfs(v)
                elif color.get(v) == 1:
                    # found a back edge -> cycle
                    try:
                        start = stack.index(v)
                        cycles.append(stack[start:] + [v])
                    except ValueError:
                        pass
            stack.pop()
            color[u] = 2

        for n in self.nodes:
            color.setdefault(n, 0)
        for n in list(self.nodes):
            if color.get(n) == 0:
                dfs(n)
        return cycles

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "errors": self.validate(),
            "cycles": self.detect_cycles(),
            "unsupported_claims": [
                nid for nid, n in self.nodes.items() if n.type == NODE_CLAIM and n.status == UNSUPPORTED
            ],
            "contextual_only_claims": [
                nid for nid, n in self.nodes.items() if n.type == NODE_CLAIM and n.status == CONTEXTUAL_ONLY
            ],
            # Stale facts are preserved but never silently treated as current.
            "stale_facts": [
                nid
                for nid, n in self.nodes.items()
                if n.type == NODE_FACT and (n.freshness or "").upper() == FRESHNESS_STALE
            ],
        }


def build_graph(nodes: list[dict], edges: list[dict]) -> ClaimEvidenceGraph:
    g = ClaimEvidenceGraph()
    for n in nodes or []:
        g.add_node(n)
    for e in edges or []:
        g.add_edge(e)
    return g


class ClaimEvidenceProvider(BaseProvider):
    name = "evidence"
    version = "1.0.0"

    def _capabilities(self) -> list[Capability]:
        return [
            Capability(
                "evidence.build_graph",
                "READ_ONLY",
                input_schema={"nodes": "list<object>", "edges": "list<object>"},
            )
        ]

    def _query(self, capability: str, request: dict) -> FinancialSenseResult:
        if capability != "evidence.build_graph":
            return self._unavailable(capability, "unknown capability")
        nodes = request.get("nodes")
        edges = request.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return self._invalid("evidence.build_graph", "nodes and edges lists required")
        graph = build_graph(nodes, edges)
        result = graph.to_dict()
        r = self._ok("evidence.build_graph")
        r.data = result
        if result["errors"]:
            r.set_status("PARTIAL")
            for err in result["errors"]:
                r.add_warning(err)
        return r
