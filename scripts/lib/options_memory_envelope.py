"""Scoped options/CIO memory envelope (Slice B — agentic memory acceleration).

Keeps global MEMORY_BEHAVIOR_INFLUENCE at its conservative default (0).
When MEMORY_BEHAVIOR_INFLUENCE_OPTIONS=1, loads a bounded "what we learned"
envelope (prior options outcomes + CIO learning notes for an issuer) into
CIO/options advisory with Sources chrome.

Fail-closed:
  * flag off → no influence
  * flag on but empty priors → no influence (applied=False, reason EMPTY)

Never invents PnL. Never sizes, orders, or writes to a broker.
Does not flip global MEMORY_BEHAVIOR_INFLUENCE.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from scripts.lib.agent_feature_flags import (
    _coerce_int_flag,
    load_feature_flags,
)

SCHEMA = "OptionsMemoryEnvelope@v1"
DEFAULT_MAX_OUTCOMES = 5
DEFAULT_MAX_NOTES = 3

# Conservative default — must stay 0 unless an operator pin sets the env.
DEFAULT_MEMORY_BEHAVIOR_INFLUENCE_OPTIONS = 0

# Resolved against the persistent-state root and the repo root, not the cwd
# (a cwd-relative path read nothing from a worktree or a probe; 2026-09-25).
_REPO_ROOT = Path(__file__).resolve().parents[2]


def learning_candidate_paths() -> tuple[Path, ...]:
    rel = Path("data/cio/cio_operator_learning.jsonl")
    out: list[Path] = []
    try:
        from scripts.lib.canonical_store_registry import production_state_root

        out.append(Path(production_state_root()) / rel)
    except Exception:  # noqa: BLE001
        pass
    out.append(_REPO_ROOT / rel)
    out.append(rel)
    seen: set[str] = set()
    uniq = [p for p in out if not (str(p) in seen or seen.add(str(p)))]
    return tuple(uniq)


LEARNING_CANDIDATES = learning_candidate_paths()

# Tranche 2 Slice 6 (2026-09-25): the live path never passed outcomes, so the
# envelope only ever saw two August learning notes. With no rows injected the
# loader reads settled paper options outcomes (options_paper_outcomes joined to
# the approval queue) through validation.fetch_symbol_outcomes. "0" disables the
# DB read — tests/conftest.py sets it so hermetic tests never touch the database;
# a test that wants rows injects ``rows=``/``outcomes=`` or ``loader=``.
OUTCOME_LOADER_ENV = "TRADEAI_OPTIONS_OUTCOME_LOADER"
SOURCE_PAPER_OUTCOMES = "options_paper_outcomes"


def default_outcome_loader(symbol: str, limit: int) -> list[dict[str, Any]]:
    """Settled paper options outcomes for the symbol from the DB; [] on any failure."""
    if os.environ.get(OUTCOME_LOADER_ENV, "1") == "0":
        return []
    try:
        from scripts.lib.options_pipeline.validation import fetch_symbol_outcomes
    except ImportError:
        try:
            from lib.options_pipeline.validation import fetch_symbol_outcomes  # type: ignore
        except ImportError:
            return []
    try:
        return list(fetch_symbol_outcomes(symbol, limit=max(int(limit), 1) * 4) or [])
    except Exception:  # noqa: BLE001
        return []


def options_behavior_influence_active(
    flags: Optional[dict[str, Any]] = None,
    *,
    env: Optional[dict[str, Any]] = None,
) -> bool:
    """True only when the SCOPED options memory flag is on.

    Independent of global MEMORY_BEHAVIOR_INFLUENCE and MEMORY_PROVIDER so a
    lab pin can enable options learning without flipping house-wide influence.
    """
    if isinstance(flags, dict):
        return _coerce_int_flag(flags.get("MEMORY_BEHAVIOR_INFLUENCE_OPTIONS")) == 1
    resolved = load_feature_flags(env)
    return _coerce_int_flag(resolved.get("MEMORY_BEHAVIOR_INFLUENCE_OPTIONS")) == 1


def _symbol_match(row: dict[str, Any], symbol: str) -> bool:
    sym = symbol.upper().strip()
    if not sym:
        return False
    for key in ("symbol", "underlying", "ticker"):
        v = row.get(key)
        if v is not None and str(v).strip().upper() == sym:
            return True
    symbols = row.get("symbols")
    if isinstance(symbols, (list, tuple)):
        return any(str(s).strip().upper() == sym for s in symbols)
    return False


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def load_cio_learning_notes_for_symbol(
    symbol: str,
    *,
    paths: Optional[list[Path]] = None,
    rows: Optional[list[dict[str, Any]]] = None,
    limit: int = DEFAULT_MAX_NOTES,
) -> list[dict[str, Any]]:
    """Bounded CIO learning notes mentioning the issuer. Newest-last preferred."""
    if rows is not None:
        matched = [r for r in rows if isinstance(r, dict) and _symbol_match(r, symbol)]
    else:
        matched = []
        for p in paths or list(LEARNING_CANDIDATES):
            for r in _load_jsonl(Path(p)):
                if _symbol_match(r, symbol):
                    matched.append(r)
    # Prefer trailing (newest) entries when the file is append-only
    if limit > 0:
        matched = matched[-limit:]
    return matched


def load_options_outcomes_for_symbol(
    symbol: str,
    *,
    rows: Optional[list[dict[str, Any]]] = None,
    limit: int = DEFAULT_MAX_OUTCOMES,
    loader: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """Bounded prior options outcomes for an issuer.

    ``rows`` given (even ``[]``): hermetic, filtered as-is. ``rows is None``:
    the ``loader`` (default ``default_outcome_loader`` → options_paper_outcomes)
    supplies settled outcomes; it returns [] when the DB is unavailable or the
    loader is disabled. Settled rows only — this never reads open positions.
    """
    if rows is None:
        fn = loader or default_outcome_loader
        try:
            rows = list(fn(symbol, limit) or [])
        except Exception:  # noqa: BLE001
            rows = []
    if not rows:
        return []
    matched = [r for r in rows if isinstance(r, dict) and _symbol_match(r, symbol)]
    if limit > 0:
        matched = matched[-limit:]
    return matched


def _format_outcome_line(row: dict[str, Any]) -> str:
    strat = row.get("strategy") or row.get("strategy_id") or "options"
    outcome = row.get("outcome") or row.get("chain_status") or row.get("verdict") or "recorded"
    bits = [f"{strat}: {outcome}"]
    # Cite existing numbers only — never invent PnL
    if row.get("pnl") is not None:
        try:
            bits.append(f"pnl={float(row['pnl']):+.2f}")
        except (TypeError, ValueError):
            pass
    if row.get("option_strategy_guid"):
        bits.append(f"strategy_guid={str(row['option_strategy_guid'])[:8]}…")
    if row.get("contract_guid"):
        bits.append(f"contract_guid={str(row['contract_guid'])[:8]}…")
    return " · ".join(bits)


def _format_note_line(row: dict[str, Any]) -> str:
    note = (
        row.get("note")
        or row.get("narrative")
        or row.get("disposition")
        or row.get("summary")
        or row.get("kind")
        or "learning note"
    )
    return str(note).strip()[:160]


def build_options_memory_envelope(
    symbol: str,
    *,
    flags: Optional[dict[str, Any]] = None,
    outcomes: Optional[list[dict[str, Any]]] = None,
    learning_notes: Optional[list[dict[str, Any]]] = None,
    learning_paths: Optional[list[Path]] = None,
    max_outcomes: int = DEFAULT_MAX_OUTCOMES,
    max_notes: int = DEFAULT_MAX_NOTES,
) -> dict[str, Any]:
    """Build a bounded memory envelope for one issuer.

    Returns a dict with:
      applied: bool — True only when flag on AND at least one prior exists
      reason: str — FLAG_OFF | EMPTY | APPLIED
      sources: list[str] — chrome labels for finalize_operator_reply
      prose: str — operator-facing block (empty when not applied)
      outcomes / learning_notes — the bounded rows cited
    """
    sym = str(symbol or "").strip().upper()
    base = {
        "schema": SCHEMA,
        "symbol": sym or None,
        "applied": False,
        "reason": "FLAG_OFF",
        "sources": [],
        "prose": "",
        "outcomes": [],
        "learning_notes": [],
        "memory_behavior_influence_global": 0,  # this module never flips global
    }
    if not options_behavior_influence_active(flags):
        return base

    prior_outcomes = load_options_outcomes_for_symbol(
        sym, rows=outcomes, limit=max_outcomes,
    )
    prior_notes = learning_notes
    if prior_notes is None:
        prior_notes = load_cio_learning_notes_for_symbol(
            sym, paths=learning_paths, limit=max_notes,
        )
    else:
        prior_notes = [
            r for r in prior_notes
            if isinstance(r, dict) and _symbol_match(r, sym)
        ][-max_notes:]

    if not prior_outcomes and not prior_notes:
        base["reason"] = "EMPTY"
        return base

    sources: list[str] = []
    lines = [f"What we learned (options memory — {sym}):"]
    if prior_outcomes:
        sources.append("options_prior_outcomes")
        if any(str(r.get("source") or "") == SOURCE_PAPER_OUTCOMES for r in prior_outcomes):
            sources.append(SOURCE_PAPER_OUTCOMES)
        lines.append("Prior options outcomes:")
        for row in prior_outcomes:
            lines.append(f"  · {_format_outcome_line(row)}")
    if prior_notes:
        sources.append("cio_operator_learning")
        lines.append("CIO learning notes:")
        for row in prior_notes:
            lines.append(f"  · {_format_note_line(row)}")
    lines.append(
        "Sources: " + ", ".join(sources) + " — advisory context only; Path B unchanged."
    )

    return {
        "schema": SCHEMA,
        "symbol": sym,
        "applied": True,
        "reason": "APPLIED",
        "sources": sources,
        "prose": "\n".join(lines),
        "outcomes": prior_outcomes,
        "learning_notes": prior_notes,
        "memory_behavior_influence_global": 0,
    }


__all__ = [
    "SCHEMA",
    "DEFAULT_MEMORY_BEHAVIOR_INFLUENCE_OPTIONS",
    "options_behavior_influence_active",
    "load_cio_learning_notes_for_symbol",
    "load_options_outcomes_for_symbol",
    "build_options_memory_envelope",
]
