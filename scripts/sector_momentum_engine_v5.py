#!/usr/bin/env python3
"""Sector momentum v5 launcher: v4 breadth plus shared diligence envelopes.

Additive and inactive until explicitly selected by the host invocation.
"""
from __future__ import annotations

import sector_momentum_engine as base
import sector_momentum_engine_v4 as breadth_v4
from specialized_research_due_diligence import sector_packet

_ORIGINAL_COMPUTE_STATES = base.compute_states


def compute_states_v5(cur, as_of_idx_offset=0):
    rows = _ORIGINAL_COMPUTE_STATES(cur, as_of_idx_offset=as_of_idx_offset)
    # Base main adds breadth/truth after compute_states. The initial packet is
    # intentionally INSUFFICIENT until finalize_rows_v5 runs after enrichment.
    for row in rows:
        row["due_diligence_pending"] = True
    return rows


def finalize_rows_v5(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["due_diligence"] = sector_packet(row)
        row["proposal_research_eligible"] = row["due_diligence"]["release_allowed"]
        row.pop("due_diligence_pending", None)
    return rows


def install() -> None:
    breadth_v4.install()
    base.compute_states = compute_states_v5


def main() -> int:
    # The established base main owns persistence. A downstream snapshot consumer
    # must call finalize_rows_v5 after breadth/truth enrichment; this launcher
    # exposes the contract without changing existing persisted schema.
    install()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
