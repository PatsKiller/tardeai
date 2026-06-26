#!/usr/bin/env python3
"""proposal_live_submit_tag.py — Stamp live-submit path + correlation on proposal rows.

Unifies the two Schwab submit surfaces (queue-route 2FA vs canary pilot) so every
broker order is auditable from paper_trade_proposals.
"""
from __future__ import annotations

from typing import Optional


VALID_PATHS = frozenset({
    "queue_route_2fa",
    "canary_pilot",
    "paper_auto",
    "record_only",
})


def tag_proposal_live_submit(
    proposal_id: int,
    *,
    live_submit_path: str,
    correlation_id: Optional[str] = None,
    intent_id: Optional[str] = None,
) -> bool:
    """Persist path tag on paper_trade_proposals. No-op if columns missing."""
    if not proposal_id or live_submit_path not in VALID_PATHS:
        return False
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        meta_patch = {}
        if intent_id:
            meta_patch["last_intent_id"] = intent_id
        cur.execute(
            """UPDATE paper_trade_proposals
               SET live_submit_path = COALESCE(live_submit_path, %s),
                   last_correlation_id = COALESCE(%s::uuid, last_correlation_id),
                   sizing_basis = CASE
                     WHEN %s::jsonb = '{}'::jsonb THEN sizing_basis
                     ELSE COALESCE(sizing_basis, '{}'::jsonb) || %s::jsonb
                   END,
                   updated_at = NOW()
               WHERE id = %s""",
            (
                live_submit_path,
                correlation_id,
                __import__("json").dumps(meta_patch),
                __import__("json").dumps(meta_patch),
                int(proposal_id),
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        try:
            from db_adapter import _get_conn
            _get_conn().rollback()
        except Exception:
            pass
        return False