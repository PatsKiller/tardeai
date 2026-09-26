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


# ── M2 read-back (2026-09-26) ─────────────────────────────────────────────
# scripts/options_memory_projector.py writes the options thesis store into the
# CIO's bitemporal memory (memory_r10_m2, source_type options_thesis_store).
# The CIO options review reads prior decisions / theses / follow-ups back from
# there. Enabled by options_desk_settings.options_thesis_lifecycle.memory_reads;
# the MEMORY_BEHAVIOR_INFLUENCE_OPTIONS env flag, when set, overrides config.
# OUTCOME_LOADER_ENV="0" (tests/conftest.py) disables this DB read too.
PRIOR_FACT_PREDICATES = ("options_cio_decision", "options_thesis", "options_followup")
PRIOR_FACT_SOURCE_TYPE = "options_thesis_store"
PRIOR_TEXT_CLIP = 300
PRIOR_LIST_CLIP = 3


def options_memory_reads_enabled(config_value: Any = None, *, env: Optional[dict[str, Any]] = None) -> bool:
    """Config turns M2 reads on; a set MEMORY_BEHAVIOR_INFLUENCE_OPTIONS env wins either way."""
    e = os.environ if env is None else env
    raw = e.get("MEMORY_BEHAVIOR_INFLUENCE_OPTIONS")
    if raw is not None and str(raw).strip() != "":
        return _coerce_int_flag(raw) == 1
    return _coerce_int_flag(config_value) == 1


def _compact_prior(predicate: str, obj: dict[str, Any], valid_from: Any, same_strategy: bool) -> dict[str, Any]:
    """Advisory summary only. GUIDs are left out: the review's number-traceability
    rail reads every digit in the facts, and a GUID would loosen it."""
    def _clip(v: Any) -> Any:
        return (v[:PRIOR_TEXT_CLIP] + "…") if isinstance(v, str) and len(v) > PRIOR_TEXT_CLIP else v

    def _lst(v: Any) -> list[str]:
        return [str(_clip(x)) for x in (v or []) if x][:PRIOR_LIST_CLIP] if isinstance(v, list) else []

    row: dict[str, Any] = {
        "kind": predicate,
        "as_of": str(valid_from)[:10] if valid_from else None,
        "same_strategy": bool(same_strategy),
        "strategy": obj.get("strategy"),
    }
    if predicate == "options_cio_decision":
        row.update(outcome=obj.get("outcome"), confidence=obj.get("confidence"),
                   reasoning=_clip(obj.get("reasoning")), concerns=_lst(obj.get("concerns")),
                   unknowns=_lst(obj.get("unknowns")))
    elif predicate == "options_thesis":
        row.update(thesis_state=obj.get("thesis_state"), missing_required=_lst(obj.get("missing_required")),
                   summary=_clip((obj.get("investment_thesis") or {}).get("summary")))
    elif predicate == "options_followup":
        row.update(stage=obj.get("stage"), deliverables=_lst(obj.get("deliverables")))
    return {k: v for k, v in row.items() if v not in (None, [], "")}


def load_prior_options_facts(
    option_strategy_guid: Any,
    symbol: Any,
    *,
    limit: int,
    lookback_days: int,
    dsn: Optional[str] = None,
    connect: Optional[Any] = None,
    tenant_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Prior options facts from M2 for this strategy and symbol, newest first.

    Current rows (upper_inf(tx_period)) valid within ``lookback_days``. Returns
    [] on any failure, when no DSN is configured, or when disabled for tests —
    it never raises and never writes (read-only session).
    """
    guid = str(option_strategy_guid or "").strip()
    sym = str(symbol or "").strip().upper()
    if not (guid or sym) or int(limit) <= 0:
        return []
    if connect is None and os.environ.get(OUTCOME_LOADER_ENV, "1") == "0":
        return []
    target = dsn or os.environ.get("M2_DSN")
    if connect is None and not target:
        return []
    conn = None
    try:
        from scripts.lib.memory_namespace import DEFAULT_TENANT

        tenant = tenant_id or DEFAULT_TENANT
        if connect is None:
            import psycopg2

            from scripts.lib.m2_live_shadow_guard import refuse_live_shadow_under_pytest
            from scripts.lib.memory_m2_benchmark import _assert_isolated_dsn

            conn = psycopg2.connect(refuse_live_shadow_under_pytest(_assert_isolated_dsn(target)))
        else:
            conn = connect()
        try:
            conn.set_session(readonly=True, autocommit=True)
        except Exception:  # noqa: BLE001 — fakes and poolers may not support it
            pass
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant,))
            cur.execute(
                """
                SELECT predicate, object_value, lower(valid_period)
                  FROM memory_r10_m2.memory_fact_version
                 WHERE tenant_id = %s
                   AND source_type = %s
                   AND predicate = ANY(%s)
                   AND upper_inf(tx_period)
                   AND (object_value->>'option_strategy_guid' = %s
                        OR upper(object_value->>'symbol') = %s)
                   AND lower(valid_period) >= now() - make_interval(days => %s)
                 ORDER BY lower(valid_period) DESC, version_seq DESC
                 LIMIT %s
                """,
                (tenant, PRIOR_FACT_SOURCE_TYPE, list(PRIOR_FACT_PREDICATES), guid, sym,
                 int(lookback_days), int(limit)),
            )
            rows = cur.fetchall()
        out = []
        for pred, obj, vfrom in rows:
            if isinstance(obj, str):
                obj = json.loads(obj)
            if not isinstance(obj, dict):
                continue
            out.append(_compact_prior(str(pred), obj, vfrom,
                                      bool(guid) and str(obj.get("option_strategy_guid") or "") == guid))
        return out
    except Exception:  # noqa: BLE001 — memory is advisory; a read failure is "no priors"
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


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
    "options_memory_reads_enabled",
    "load_prior_options_facts",
]
