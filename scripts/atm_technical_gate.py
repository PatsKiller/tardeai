#!/usr/bin/env python3
"""Finviz technical gate for ATM paper entries — aligns ATM with Path B technical quality."""
from __future__ import annotations

import os
from typing import Any

# Configurable via atm_config.yaml → defaults.technical_gate
_DEFAULT_MIN_SCORE = 60
_BLOCK_GRADES = frozenset({"TECH_WEAK", "TECH_INCOMPLETE"})


def _gate_config() -> dict:
    try:
        from atm_config_manager import load_config
        cfg, _ = load_config()
        return (cfg.get("defaults") or {}).get("technical_gate") or {}
    except Exception:
        return {}


def letter_grade(score: int | float | None) -> str:
    s = int(score or 0)
    if s >= 80:
        return "A"
    if s >= 60:
        return "B"
    if s >= 40:
        return "C"
    if s >= 20:
        return "D"
    return "F"


def resolve_proposal_technical(
    proposal_id: int,
    symbol: str,
    *,
    conn=None,
    live_price: float | None = None,
) -> dict[str, Any]:
    """Snapshot first, then cached Finviz enrichment (same feed as Proposals card)."""
    sym = str(symbol or "").upper()
    grade = None
    score = None
    source = None

    if conn is None:
        from db_adapter import get_connection
        conn = get_connection()

    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT technical_grade, technical_score
                 FROM proposal_technical_snapshots
                WHERE proposal_id=%s
                ORDER BY computed_at DESC LIMIT 1""",
            (int(proposal_id),),
        )
        row = cur.fetchone()
        if row and row[0]:
            grade, score = str(row[0]), int(row[1] or 0)
            source = "proposal_technical_snapshot"
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

    if not grade or grade == "TECH_INCOMPLETE":
        try:
            import proposal_enrichment_bridge as peb
            snap = peb.snapshot_from_enrichment(sym, live_price=live_price)
            grade = str(snap.get("technical_grade") or "TECH_INCOMPLETE")
            score = int(snap.get("technical_score") or 0)
            source = snap.get("enrichment_source") or "finviz_enrichment"
        except Exception:
            grade = grade or "TECH_INCOMPLETE"
            score = score or 0
            source = source or "unavailable"

    return {
        "technical_grade": grade,
        "technical_score": score,
        "finviz_letter": letter_grade(score),
        "source": source,
    }


def atm_technical_allowed(
    proposal_id: int,
    symbol: str,
    *,
    conn=None,
    live_price: float | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Returns (allowed, reason_code, meta)."""
    cfg = _gate_config()
    min_score = int(cfg.get("min_score") or _DEFAULT_MIN_SCORE)
    block_grades = set(cfg.get("block_grades") or _BLOCK_GRADES)

    meta = resolve_proposal_technical(
        proposal_id, symbol, conn=conn, live_price=live_price,
    )
    grade = str(meta.get("technical_grade") or "TECH_INCOMPLETE")
    score = int(meta.get("technical_score") or 0)

    if grade in block_grades:
        return False, f"technical_grade_{grade.lower()}", meta
    if score < min_score:
        return False, f"technical_score_{score}_below_{min_score}", meta
    return True, "ok", meta