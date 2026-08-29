"""Identity coverage measurement for the CIO product surfaces.

Wave 2 slice 13 — *measure* how much of NEW_POSITION_IF / re-entry / watch
carries a `subject_guid`. Wave 2 slice 14 — *dry* the register list for held
(non-dust) and active-watch names that the registry does not know.

READ_ONLY_ADVISORY. MEMORY_BEHAVIOR_INFLUENCE = 0.

**This module never mints.** It reads `identity_registry` and reports. Two
different numbers are reported per surface and they are not interchangeable:

* ``resolvable`` — the registry can answer for this symbol today.
* ``stamped``    — the payload row actually carries the ``subject_guid``.

Reporting only the first would hide that three of the four surfaces resolve but
ship no identity; reporting only the second would read as a registry gap that
does not exist. Slice 13 asks for the measurement, not for new stamping, so
nothing here writes a guid onto a row.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CIOIdentityCoverage@v1"
UNRESOLVED_CAP = 20

# Surfaces slice 13 names, mapped to where each lives. NEW_POSITION_IF sits at
# action_book.NEW_POSITION_IF on the built product and at new_position_if on the
# operator projection; both are tried so the measure is never silently empty.
SURFACE_PATHS: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    ("new_position_if", (("action_book", "NEW_POSITION_IF"), ("new_position_if",))),
    ("reentry_book", (("reentry_book", "names"),)),
    ("opportunity_book", (("opportunity_book", "top"),)),
    ("watch_block", (("watch_block_summary", "top"),)),
)


def _dig(doc: Any, path: Iterable[str]) -> list[dict[str, Any]]:
    cur = doc
    for key in path:
        if not isinstance(cur, dict):
            return []
        cur = cur.get(key)
    return [r for r in (cur or []) if isinstance(r, dict)]


def _symbols(rows: list[dict[str, Any]]) -> list[str]:
    return [str(r.get("symbol") or "").strip().upper() for r in rows if r.get("symbol")]


def _pct(hit: int, total: int) -> Optional[float]:
    return round(100.0 * hit / total, 1) if total else None


def measure_identity_coverage(
    *,
    product: Optional[dict[str, Any]] = None,
    operator_product: Optional[dict[str, Any]] = None,
    registry: Optional[dict[str, Any]] = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Per-surface resolvable / stamped subject_guid coverage. Lookup only."""
    from scripts.lib.identity_registry import load_cached, lookup_symbol

    doc = registry if registry is not None else load_cached(root)
    product = product or {}
    surfaces: list[dict[str, Any]] = []
    tot_n = tot_res = tot_stamp = 0

    for name, paths in SURFACE_PATHS:
        rows: list[dict[str, Any]] = []
        for path in paths:
            rows = _dig(product, path) or _dig(operator_product or {}, path)
            if rows:
                break
        syms = _symbols(rows)
        resolvable = [s for s in syms if lookup_symbol(doc, s)]
        unresolved = sorted({s for s in syms if not lookup_symbol(doc, s)})
        stamped = sum(1 for r in rows if r.get("subject_guid"))
        tot_n += len(syms)
        tot_res += len(resolvable)
        tot_stamp += stamped
        surfaces.append({
            "surface": name,
            "n": len(syms),
            "resolvable_n": len(resolvable),
            "resolvable_pct": _pct(len(resolvable), len(syms)),
            "stamped_n": stamped,
            "stamped_pct": _pct(stamped, len(syms)),
            "unresolved_symbols": unresolved[:UNRESOLVED_CAP],
            "unresolved_truncated": len(unresolved) > UNRESOLVED_CAP,
            "class": "D",
        })

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "minted": 0,
        "mint": False,
        "surfaces": surfaces,
        "total_rows": tot_n,
        "total_resolvable": tot_res,
        "total_resolvable_pct": _pct(tot_res, tot_n),
        "total_stamped": tot_stamp,
        "total_stamped_pct": _pct(tot_stamp, tot_n),
        "registry_entities": len((doc or {}).get("entities") or {}),
        "registry_symbols": len((doc or {}).get("by_symbol") or {}),
        "class": "D",
        "note": (
            "resolvable = registry can answer; stamped = the payload row carries "
            "subject_guid. Lookup only — this measure never mints an identity."
        ),
    }


# ── slice 14: dry register list ──────────────────────────────────────────────

REGISTER_CAP = 30


def collect_registerable(
    *,
    product: Optional[dict[str, Any]] = None,
    registry: Optional[dict[str, Any]] = None,
    root: Path | str | None = None,
    holdings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Held (non-dust) + active-watch symbols the registry does not know.

    Deliberately narrow. The registry already carries ~10k researched entities;
    slice 14 registers the operator's *own book* and the names actively on
    watch, not a research dump. CASH, CUSIP-only rows and DUST_RESIDUAL are
    excluded — a residual share is not a position worth an identity.
    """
    from scripts.lib.identity_registry import load_cached, lookup_symbol
    from scripts.lib.cio_investment_product import collect_holdings, held_equity_symbols_nondust

    doc = registry if registry is not None else load_cached(root)
    holdings = holdings if holdings is not None else collect_holdings(root)
    held = list(held_equity_symbols_nondust(holdings))
    watch = _symbols(_dig(product or {}, ("watch_block_summary", "top")))
    watch += _symbols(_dig(product or {}, ("opportunity_book", "top")))

    candidates: list[tuple[str, str]] = [(s, "held_non_dust") for s in held]
    candidates += [(s, "active_watch") for s in dict.fromkeys(watch) if s not in set(held)]

    would: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sym, reason in candidates:
        if not sym or sym in seen:
            continue
        seen.add(sym)
        if lookup_symbol(doc, sym):
            continue
        would.append({"symbol": sym, "reason": reason, "class": "D"})

    over_cap = len(would) > REGISTER_CAP
    return {
        "schema": "CIOIdentityRegisterDry@v1",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "held_non_dust_n": len(held),
        "watch_n": len(set(watch)),
        "considered_n": len(seen),
        "would_register_n": len(would),
        "would_register": would,
        "cap": REGISTER_CAP,
        "over_cap": over_cap,
        "apply_allowed": not over_cap,
        "apply_blocked_reason": (
            f"would_register_n {len(would)} exceeds cap {REGISTER_CAP}" if over_cap else None
        ),
        "note": (
            "Held non-dust + active watch only. Never the researched dump. "
            "--apply is refused above the cap."
        ),
    }


def apply_registerable(
    dry: dict[str, Any],
    *,
    root: Path | str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Register the dry list. Refuses above the cap; writes only when `apply`."""
    from scripts.lib.identity_registry import register_all

    rows = [{"symbol": r["symbol"]} for r in (dry.get("would_register") or [])]
    if dry.get("over_cap"):
        return {
            "schema": "CIOIdentityRegisterApply@v1",
            "authority": AUTHORITY,
            "applied": False,
            "refused": True,
            "reason": dry.get("apply_blocked_reason"),
            "would_register_n": dry.get("would_register_n"),
        }
    summary = register_all(rows, root, apply=bool(apply))
    return {
        "schema": "CIOIdentityRegisterApply@v1",
        "authority": AUTHORITY,
        "financial_action": False,
        "applied": bool(apply),
        "refused": False,
        "reason": None,
        "would_register_n": dry.get("would_register_n"),
        "registry": summary,
    }
