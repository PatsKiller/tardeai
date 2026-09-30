"""Append-only SymbolDecisionObject ledger."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .symbol_decision_object import SCHEMA, validate_symbol_decision

DEFAULT_REL = Path("data") / "cio" / "symbol_decisions.jsonl"


def default_ledger_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[3]
    return base / DEFAULT_REL


def append_symbol_decision(
    obj: dict[str, Any],
    *,
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Validate then append. Fail-soft: returns {ok, error?} without raising on IO."""
    check = validate_symbol_decision(obj)
    if not check["ok"]:
        return {"ok": False, "error": "invalid_object", "errors": check["errors"]}
    dest = path or default_ledger_path(root)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, separators=(",", ":"), default=str) + "\n")
        return {"ok": True, "path": str(dest), "schema": SCHEMA}
    except Exception as exc:  # noqa: BLE001 — fail-soft
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"[:160]}


def load_latest_by_symbol(
    symbol: str,
    *,
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    sym = str(symbol or "").upper().strip()
    dest = path or default_ledger_path(root)
    if not dest.exists():
        return None
    latest: dict[str, Any] | None = None
    with dest.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            ident = row.get("identity") if isinstance(row.get("identity"), dict) else {}
            if str(ident.get("symbol") or "").upper() == sym:
                latest = row
    return latest
