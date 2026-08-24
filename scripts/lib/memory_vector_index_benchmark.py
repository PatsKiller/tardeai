"""Deterministic vector-index harness. Does not fabricate production scores.

HNSW / IVFFlat / Neo4j are UNMEASURED until a real Postgres shadow workload runs.
Exact cosine on a tiny synthetic set is the only score this module may emit.
"""
from __future__ import annotations

import math
from typing import Any

SCHEMA = "MemoryVectorIndexBenchmark@v1"
AUTHORITY = "READ_ONLY_ADVISORY"


def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=True))
    da = math.sqrt(sum(x * x for x in a)) or 1.0
    db = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (da * db)


def run_synthetic_exact(*, n: int = 64, dim: int = 8) -> dict[str, Any]:
    """Tiny CPU exact-scan sanity check. NOT a production ANN study."""
    vecs = [[((i + 1) * (j + 1) % 17) / 17.0 for j in range(dim)] for i in range(n)]
    q = vecs[0]
    scored = sorted(((cosine(q, v), i) for i, v in enumerate(vecs)), key=lambda t: (-t[0], t[1]))
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "recommendation": "INSUFFICIENT_DATA",
        "measured": {
            "EXACT": {
                "n": n,
                "dim": dim,
                "top1_self": scored[0][1] == 0,
                "note": "synthetic self-retrieval only",
            },
            "HNSW": "UNMEASURED",
            "IVFFLAT": "UNMEASURED",
            "HYBRID": "UNMEASURED",
            "NEO4J": "UNMEASURED",
        },
        "longmemeval_style_numbers": "REFERENCE_TARGET_NOT_MEASURED",
        "neo4j_shadow_poc_decision": "INSUFFICIENT_DATA",
        "financial_action": False,
    }
