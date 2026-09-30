"""Enqueue Hermes refresh when SecurityResearchSpine tip breaches CLASS_SLA.

Fail-soft, rate-limited. Does not place orders. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_ENQUEUED: set[str] = set()


def _day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _max_per_day() -> int:
    try:
        return max(0, int(os.environ.get("SPINE_SLA_ENQUEUE_MAX_PER_DAY", "8")))
    except ValueError:
        return 8


def candidates_for_symbols(
    symbols: list[str] | None,
    *,
    root: Path | str | None = None,
    silo: str = "cio",
) -> list[dict[str, Any]]:
    """Return {symbol, age_days, sla_days, reason} for tips past CLASS_SLA."""
    try:
        from scripts.lib.cross_asset.security_research_spine import view_for_silo
    except Exception:
        return []
    root_p = Path(root) if root is not None else None
    out: list[dict[str, Any]] = []
    for raw in symbols or []:
        sym = str(raw or "").upper().strip()
        if not sym:
            continue
        try:
            v = view_for_silo(sym, silo, root=root_p, persist_read_receipt=False) or {}
        except Exception:
            continue
        if not v.get("found"):
            continue
        cur = v.get("currency") or {}
        refuse = cur.get("refuse_fresh_claim")
        fresh = cur.get("fresh")
        if refuse is True or fresh is False or v.get("spine_fresh") is False:
            out.append({
                "symbol": sym,
                "age_days": cur.get("age_days") if cur.get("age_days") is not None else v.get("spine_age_days"),
                "sla_days": cur.get("sla_days") if cur.get("sla_days") is not None else v.get("spine_sla_days"),
                "as_of": v.get("as_of"),
                "reason": "spine_sla_breach",
            })
    return out


def scan_ledger_candidates(
    *,
    root: Path | str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Scan latest spine tips and return SLA breach candidates."""
    try:
        from scripts.lib.cross_asset.security_research_spine import default_path, load_latest
    except Exception:
        return []
    root_p = Path(root) if root is not None else None
    path = default_path(root_p)
    if not path.exists():
        return []
    # Collect unique symbols from ledger (last-write wins via load loop).
    syms: list[str] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                import json
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            s = str(row.get("symbol") or "").upper()
            if s and s not in seen:
                seen.add(s)
                syms.append(s)
    # Prefer re-checking latest tips for listed symbols (newest-first scan via set order).
    # Re-walk for actual latest set:
    latest_syms: list[str] = []
    latest_seen: set[str] = set()
    with path.open(encoding="utf-8", errors="ignore") as fh:
        rows = []
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                import json
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict) and row.get("symbol"):
                rows.append(str(row["symbol"]).upper())
        for s in reversed(rows):
            if s not in latest_seen:
                latest_seen.add(s)
                latest_syms.append(s)
            if len(latest_syms) >= limit:
                break
    return candidates_for_symbols(latest_syms, root=root_p)


def enqueue_spine_sla_breaches(
    symbols: list[str] | None = None,
    *,
    root: Path | str | None = None,
    apply: bool = False,
    chat_id: str = "",
    pending_id: str = "",
    operator_text: str | None = None,
    enqueue_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Find SLA-breached tips and optionally enqueue Hermes via enqueue_research_gap.

    Dry-run when apply=False. Rate-limited by SPINE_SLA_ENQUEUE_MAX_PER_DAY and
    per-process day+symbol dedupe.
    """
    cands = candidates_for_symbols(symbols, root=root) if symbols else scan_ledger_candidates(root=root)
    max_n = _max_per_day()
    day = _day_key()
    selected: list[dict[str, Any]] = []
    skipped_cap = 0
    for c in cands:
        key = f"{day}:{c['symbol']}"
        if key in _ENQUEUED:
            continue
        if len(selected) >= max_n:
            skipped_cap += 1
            continue
        selected.append(c)
    result: dict[str, Any] = {
        "ok": True,
        "apply": apply,
        "candidates": len(cands),
        "selected": len(selected),
        "skipped_cap": skipped_cap,
        "max_per_day": max_n,
        "symbols": [c["symbol"] for c in selected],
        "enqueued": [],
        "authority": "READ_ONLY_ADVISORY",
        "reason": "spine_sla_breach",
    }
    if not apply or not selected:
        result["dry_run"] = True
        return result
    if enqueue_fn is None:
        try:
            from scripts.lib.cio_operator_desk_loop import enqueue_research_gap
            enqueue_fn = enqueue_research_gap
        except Exception as exc:  # noqa: BLE001
            return {**result, "ok": False, "error": f"enqueue_import:{type(exc).__name__}"}
    text = operator_text or (
        "Refresh house research — SecurityResearchSpine tip past class SLA (READ_ONLY)."
    )
    for c in selected:
        key = f"{day}:{c['symbol']}"
        try:
            out = enqueue_fn(
                symbols=[c["symbol"]],
                chat_id=chat_id or "",
                pending_id=pending_id or f"spine_sla_{c['symbol']}_{day}",
                operator_text=text,
            )
        except Exception as exc:  # noqa: BLE001
            out = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
        _ENQUEUED.add(key)
        result["enqueued"].append({"symbol": c["symbol"], "result": out})
    result["ok"] = True
    return result


def reset_dedupe_for_tests() -> None:
    _ENQUEUED.clear()
