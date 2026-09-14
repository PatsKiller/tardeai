"""Trade-AI scalp GO criteria -- one test for screener and social setups alike.

Operator, 2026-09-14: "look at my goal signals for my momentum scalps. For months
have been broke and not showing." Asked whether a GO must also carry the
momentum_scalp route tag: "it should match Trade AI criteria for scalps, vol,
catalyst etc" -- and "needs to include social scalps also".

Measured: trade_ai_scans held 9-35 GO decisions a week through 09-10, but the
social scanner fired 0 GO alerts after 2026-07-13, because its gate required
``route_actionability == "GO"`` and 0 GO rows since 06-29 carried it; the
screener's own GO list rode inside the "Trade AI v12.1d" digest the router
filed to the archive.

The criteria are the ``tradeable`` block of config/finviz_momentum_scalp_screen.yaml,
the same numbers the screen and its drift test enforce (price 1-25, float <= 20M,
RVOL >= 5, |gap| >= 5 %, volume >= 1M, score >= 40 with A+ at 48, verified
catalyst). The route tag is deliberately NOT required (operator decision).

AUTHORITY: READ_ONLY_ADVISORY. An alert is a notification; nothing here sizes,
orders or stops anything. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT_ROOT / "config" / "finviz_momentum_scalp_screen.yaml"

#: Used only when the config cannot be read; kept equal to the config on 2026-09-14.
FALLBACK = {
    "price": {"min": 1.0, "max": 25.0},
    "float_m": {"max": 20},
    "rvol": {"min": 5.0, "premium": 8.0},
    "gap_pct": {"min_abs": 5.0},
    "volume": {"min_shares": 1_000_000},
    "score": {"min": 40, "aplus": 48},
    "catalyst": {"required_for_go": True, "verified_required_for_momentum_scalp": True},
}


def load_criteria(path: Path = CONFIG) -> dict[str, Any]:
    try:
        import yaml  # noqa: PLC0415

        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return dict(FALLBACK)
    node = doc
    for key in ("tradeable",):
        node = _find(doc, key)
    return node if isinstance(node, dict) and node.get("rvol") else dict(FALLBACK)


def _find(doc: Any, key: str) -> Any:
    if isinstance(doc, dict):
        if key in doc:
            return doc[key]
        for v in doc.values():
            found = _find(v, key)
            if found is not None:
                return found
    return None


def _num(v: Any) -> Optional[float]:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class GoVerdict:
    qualifies: bool
    tier: Optional[str]                 # "A+" | "GO" | None
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def evaluate(row: Mapping[str, Any], criteria: Optional[Mapping[str, Any]] = None) -> GoVerdict:
    """Does this setup meet Trade-AI's scalp GO criteria? Missing data is a failure, never a pass."""
    c = criteria or load_criteria()
    passed: list[str] = []
    failed: list[str] = []
    missing: list[str] = []

    def check(name: str, value: Optional[float], ok) -> None:
        if value is None:
            missing.append(name)
        elif ok(value):
            passed.append(name)
        else:
            failed.append(name)

    price = _num(row.get("price"))
    pr = c.get("price") or {}
    check("price", price, lambda v: float(pr.get("min", 0)) <= v <= float(pr.get("max", 1e9)))
    flt = _num(row.get("float_m"))
    check("float", flt, lambda v: v <= float((c.get("float_m") or {}).get("max", 1e9)))
    rvol = _num(row.get("rvol"))
    check("rvol", rvol, lambda v: v >= float((c.get("rvol") or {}).get("min", 0)))
    gap = _num(row.get("gap_pct") if row.get("gap_pct") is not None else row.get("change_pct"))
    check("gap", gap, lambda v: abs(v) >= float((c.get("gap_pct") or {}).get("min_abs", 0)))
    vol = _num(row.get("volume"))
    check("volume", vol, lambda v: v >= float((c.get("volume") or {}).get("min_shares", 0)))
    score = _num(row.get("score"))
    sc = c.get("score") or {}
    check("score", score, lambda v: v >= float(sc.get("min", 0)))
    cat = c.get("catalyst") or {}
    if cat.get("required_for_go", True):
        verified = row.get("catalyst_verified")
        if verified is None:
            missing.append("catalyst")
        elif bool(verified):
            passed.append("catalyst")
        else:
            failed.append("catalyst")
    for flag in ("disqualified",):
        if row.get(flag):
            failed.append(flag)
    qualifies = not failed and not missing
    tier = None
    if qualifies:
        tier = "A+" if (score is not None and score >= float(sc.get("aplus", 1e9))) else "GO"
    return GoVerdict(qualifies=qualifies, tier=tier, passed=passed, failed=failed, missing=missing)


__all__ = ["CONFIG", "FALLBACK", "GoVerdict", "evaluate", "load_criteria"]
