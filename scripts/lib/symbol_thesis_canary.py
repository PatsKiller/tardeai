"""Gated canary publish for SCHG / CSCO / ANET only.

Default is DRY. ``--apply`` is a no-op unless CANARY_THESIS_APPLY=1 (env)
or a flag file exists at ``<root>/data/cio/CANARY_THESIS_APPLY``.

Never auto-publishes on wake. Never crawls the full universe.
READ_ONLY_ADVISORY. notify=False on any real publish.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol
from scripts.lib.symbol_thesis_coverage import symbol_thesis_id
from scripts.lib.symbol_thesis_publish import publish_symbol_thesis

AUTHORITY = "READ_ONLY_ADVISORY"
CANARY_SYMBOLS = ("SCHG", "CSCO", "ANET")
CANARY_SET = frozenset(CANARY_SYMBOLS)
APPLY_ENV = "CANARY_THESIS_APPLY"
FLAG_REL = Path("data/cio/CANARY_THESIS_APPLY")


def _root(root: Path | str | None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


def canary_apply_enabled(*, root: Path | str | None = None, env: Optional[dict[str, str]] = None) -> bool:
    e = env if env is not None else os.environ
    if str(e.get(APPLY_ENV) or "").strip() == "1":
        return True
    return (_root(root) / FLAG_REL).is_file()


def normalize_canary_symbols(symbols: Optional[list[str]]) -> list[str]:
    raw = [str(s).strip().upper() for s in (symbols or list(CANARY_SYMBOLS)) if str(s).strip()]
    out = []
    for s in raw:
        if s in CANARY_SET and s not in out:
            out.append(s)
    return out


def plan_canary_publish(
    symbols: Optional[list[str]] = None,
    *,
    root: Path | str | None = None,
    apply: bool = False,
    env: Optional[dict[str, str]] = None,
    store=None,
) -> dict[str, Any]:
    """Dry-run (default) or gated apply for canary symbol theses.

    Apply still refuses unless canary_apply_enabled. Does not invent thesis text:
    publishes only when an existing summary is already on the card.
    """
    root = _root(root)
    wanted = normalize_canary_symbols(symbols)
    apply_ok = canary_apply_enabled(root=root, env=env)
    will_apply = bool(apply) and apply_ok
    blocked = bool(apply) and not apply_ok

    rows: list[dict[str, Any]] = []
    for sym in wanted:
        fields = thesis_fields_for_symbol(sym, root=root)
        summary = str(fields.get("thesis_summary") or "").strip()
        draft = {
            "symbol": sym,
            "thesis_id": fields.get("symbol_thesis_id") or symbol_thesis_id(sym),
            "current_version": fields.get("symbol_thesis_version"),
            "thesis_state": fields.get("thesis_state"),
            "portfolio_role": fields.get("portfolio_role"),
            "has_summary": bool(summary),
            "would_publish": bool(summary),
            "notify": False,
            "applied": False,
        }
        if not summary:
            draft["skip_reason"] = "no_existing_summary_will_not_invent"
        if will_apply and summary:
            published = publish_symbol_thesis(
                sym,
                summary=summary,
                stance=str(fields.get("thesis_stance") or ""),
                portfolio_role=str(fields.get("portfolio_role") or "UNKNOWN"),
                universe_memberships=list(fields.get("memberships") or []),
                why_owned_or_watched=str(fields.get("why_owned_or_watched") or ""),
                why_exited=str(fields.get("why_exited") or ""),
                what_changed_since_exit=str(fields.get("what_changed_since_exit") or ""),
                evidence_for=list(fields.get("evidence_for") or []),
                counter_evidence=list(fields.get("counter_evidence") or []),
                invalidation_conditions=list(fields.get("invalidation_conditions") or []),
                research_gaps=list(fields.get("research_gaps") or []),
                what_changes_my_mind=list(fields.get("what_would_change") or []),
                change_note="canary gated republish (explicit --apply)",
                store=store,
                notify=False,
                actor_id="symbol_thesis_canary",
            )
            draft["applied"] = True
            draft["publish"] = {
                "thesis_id": published.get("thesis_id"),
                "version": published.get("version") or published.get("thesis_version"),
            }
        rows.append(draft)

    return {
        "schema": "SymbolThesisCanaryPlan@v1",
        "mode": "apply" if will_apply else "dry",
        "apply_requested": bool(apply),
        "apply_blocked": blocked,
        "apply_block_reason": (
            f"{APPLY_ENV}!=1 and no flag file {FLAG_REL}" if blocked else None
        ),
        "symbols": wanted,
        "rejected_not_canary": [
            str(s).upper() for s in (symbols or [])
            if str(s).strip().upper() not in CANARY_SET
        ],
        "rows": rows,
        "auto_thesis_on_wake": False,
        "authority": AUTHORITY,
        "financial_action": False,
        "note": (
            "Default dry. --apply requires CANARY_THESIS_APPLY=1. "
            "Wake must not auto-publish @vN."
        ),
    }
