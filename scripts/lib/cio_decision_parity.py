"""cio_decision_parity.py — G8 multi-surface material decision parity.

Compares material decisions across capital plan, CIO home, report, and
Telegram payload on identity + digest + action + dollars.

Returns missing_from_surface, extra_on_surface, field_mismatch,
digest_mismatch. Any material mismatch => ok=False.

Authority: READ_ONLY_ADVISORY. Pure. No broker / Telegram send.
"""
from __future__ import annotations

from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
DECISION_PARITY_VERSION = "decision_surface_parity_1.0.0"

SURFACES = ("plan", "cio_home", "report", "telegram_payload")

MATERIAL_FIELDS = (
    "decision_id",
    "decision_input_digest",
    "decision_evidence_digest",
    "symbol",
    "action",
    "recommended_delta_usd",
)

DIGEST_FIELDS = ("decision_input_digest", "decision_evidence_digest")

ACTIONABLE_STANCES = frozenset({"TRIM", "EXIT", "ADD", "RE_ENTER", "BUY", "SELL"})
DELTA_TOL_USD = 0.02


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_action(row: dict[str, Any]) -> str:
    raw = (
        row.get("action")
        or row.get("stance_code")
        or row.get("cio_stance")
        or row.get("stance")
        or ""
    )
    return str(raw).upper().strip()


def _norm_symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").upper().strip()


def _delta(row: dict[str, Any]) -> Optional[float]:
    if row.get("recommended_delta_usd") is not None:
        return _num(row.get("recommended_delta_usd"))
    return _num(row.get("delta_usd"))


def is_material_decision(row: Optional[dict[str, Any]]) -> bool:
    if not isinstance(row, dict):
        return False
    action = _norm_action(row)
    delta = _delta(row)
    if delta is not None and abs(delta) >= 0.01:
        return True
    if action in ACTIONABLE_STANCES:
        return True
    if row.get("act_now") or str(row.get("action_label") or "") == "ACT_NOW":
        return True
    return False


def decision_key(row: dict[str, Any]) -> str:
    did = str(row.get("decision_id") or "").strip()
    if did:
        return did
    sym = _norm_symbol(row)
    action = _norm_action(row)
    delta = _delta(row)
    return f"sym:{sym}|{action}|{round(delta or 0.0, 2)}"


def _as_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    return []


def extract_surface_decisions(surface: str, payload: Any) -> list[dict[str, Any]]:
    """Best-effort decision rows from a named surface payload."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return _as_rows(payload)
    if not isinstance(payload, dict):
        return []

    name = str(surface or "").strip().lower()

    if name == "plan":
        rows = payload.get("position_decisions")
        if rows is None and payload.get("decision_id"):
            return [payload]
        return _as_rows(rows)

    if name == "cio_home":
        now = payload.get("cio_now") if isinstance(payload.get("cio_now"), dict) else {}
        for candidate in (
            now.get("decisions"),
            now.get("cards"),
            payload.get("decisions"),
            payload.get("position_decisions"),
        ):
            rows = _as_rows(candidate)
            if rows:
                return rows
        return []

    if name == "report":
        pa = payload.get("part_a") if isinstance(payload.get("part_a"), dict) else {}
        view = payload.get("view") if isinstance(payload.get("view"), dict) else {}
        facts = view.get("facts") if isinstance(view.get("facts"), dict) else {}
        for candidate in (
            pa.get("decisions_now"),
            pa.get("decisions"),
            facts.get("decisions"),
            payload.get("decisions_now"),
            payload.get("decisions"),
            payload.get("position_decisions"),
        ):
            rows = _as_rows(candidate)
            if rows:
                return rows
        return []

    if name == "telegram_payload":
        for candidate in (
            payload.get("decisions"),
            payload.get("items"),
            payload.get("position_decisions"),
        ):
            rows = _as_rows(candidate)
            if rows:
                return rows
        inner = payload.get("decision") or payload.get("payload")
        if isinstance(inner, dict) and (inner.get("decision_id") or inner.get("symbol")):
            return [inner]
        if isinstance(inner, list):
            return _as_rows(inner)
        if payload.get("decision_id") or payload.get("symbol"):
            return [payload]
        return []

    for key in ("position_decisions", "decisions", "decisions_now", "items"):
        rows = _as_rows(payload.get(key))
        if rows:
            return rows
    if payload.get("decision_id") or payload.get("symbol"):
        return [payload]
    return []


def _material_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": str(row.get("decision_id") or "").strip() or None,
        "decision_input_digest": row.get("decision_input_digest"),
        "decision_evidence_digest": row.get("decision_evidence_digest"),
        "symbol": _norm_symbol(row) or None,
        "action": _norm_action(row) or None,
        "recommended_delta_usd": _delta(row),
    }


def _index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not is_material_decision(row):
            continue
        out[decision_key(row)] = row
    return out


def compare_decision_surfaces(
    *,
    plan: Any = None,
    cio_home: Any = None,
    report: Any = None,
    telegram_payload: Any = None,
    extra_surfaces: Optional[dict[str, Any]] = None,
    require_digests: bool = True,
    subset_surfaces: tuple[str, ...] = ("telegram_payload",),
) -> dict[str, Any]:
    """Compare material decisions across provided surfaces.

    A surface whose payload is None is omitted (not treated as empty).
    Empty dict/list is a provided surface with zero decisions.
    """
    provided: dict[str, Any] = {}
    if plan is not None:
        provided["plan"] = plan
    if cio_home is not None:
        provided["cio_home"] = cio_home
    if report is not None:
        provided["report"] = report
    if telegram_payload is not None:
        provided["telegram_payload"] = telegram_payload
    if extra_surfaces:
        for name, payload in extra_surfaces.items():
            if payload is not None:
                provided[str(name)] = payload

    extracted: dict[str, list[dict[str, Any]]] = {
        name: extract_surface_decisions(name, payload) for name, payload in provided.items()
    }
    indexed = {name: _index(rows) for name, rows in extracted.items()}

    missing_from_surface: list[dict[str, Any]] = []
    extra_on_surface: list[dict[str, Any]] = []
    field_mismatch: list[dict[str, Any]] = []
    digest_mismatch: list[dict[str, Any]] = []

    canonical = "plan" if "plan" in indexed else (next(iter(indexed), None))
    if not canonical:
        return {
            "version": DECISION_PARITY_VERSION,
            "ok": True,
            "surfaces": [],
            "decision_count": 0,
            "missing_from_surface": [],
            "extra_on_surface": [],
            "field_mismatch": [],
            "digest_mismatch": [],
            "authority": AUTHORITY,
        }

    canon_ids = set(indexed[canonical].keys())
    all_ids = set(canon_ids)
    for name, idx in indexed.items():
        all_ids |= set(idx.keys())
        if name == canonical:
            continue
        # A canary/telegram payload is a subset: it need not repeat every plan card.
        if name in subset_surfaces:
            continue
        for did in canon_ids - set(idx.keys()):
            missing_from_surface.append({
                "decision_id": did,
                "surface": name,
                "symbol": _norm_symbol(indexed[canonical][did]),
            })
        if name not in subset_surfaces:
            for did in set(idx.keys()) - canon_ids:
                extra_on_surface.append({
                    "decision_id": did,
                    "surface": name,
                    "symbol": _norm_symbol(idx[did]),
                })

    surface_names = list(indexed.keys())
    for did in sorted(all_ids):
        present = {n: indexed[n][did] for n in surface_names if did in indexed[n]}
        if len(present) < 2:
            continue
        base_name = canonical if canonical in present else next(iter(present))
        base = _material_view(present[base_name])
        for name, row in present.items():
            if name == base_name:
                continue
            view = _material_view(row)
            for fld in MATERIAL_FIELDS:
                bv = base.get(fld)
                rv = view.get(fld)
                if fld in DIGEST_FIELDS:
                    if bv and rv and str(bv) != str(rv):
                        digest_mismatch.append({
                            "decision_id": did,
                            "field": fld,
                            "surface": name,
                            "values": [bv, rv],
                        })
                    elif require_digests and bool(bv) != bool(rv):
                        digest_mismatch.append({
                            "decision_id": did,
                            "field": fld,
                            "surface": name,
                            "values": [bv, rv],
                            "detail": "digest_missing_on_one_surface",
                        })
                    continue
                if fld == "recommended_delta_usd":
                    if bv is None or rv is None:
                        if bv != rv:
                            field_mismatch.append({
                                "decision_id": did,
                                "field": fld,
                                "surface": name,
                                "values": [bv, rv],
                            })
                        continue
                    if abs(float(bv) - float(rv)) > DELTA_TOL_USD:
                        field_mismatch.append({
                            "decision_id": did,
                            "field": fld,
                            "surface": name,
                            "values": [bv, rv],
                        })
                    continue
                if bv is None and rv is None:
                    continue
                if str(bv or "").upper() != str(rv or "").upper():
                    field_mismatch.append({
                        "decision_id": did,
                        "field": fld,
                        "surface": name,
                        "values": [bv, rv],
                    })

    material_mismatch = bool(
        missing_from_surface or extra_on_surface or field_mismatch or digest_mismatch
    )
    return {
        "version": DECISION_PARITY_VERSION,
        "ok": not material_mismatch,
        "surfaces": surface_names,
        "decision_count": len(all_ids),
        "missing_from_surface": missing_from_surface[:40],
        "extra_on_surface": extra_on_surface[:40],
        "field_mismatch": field_mismatch[:40],
        "digest_mismatch": digest_mismatch[:40],
        "required_fields": list(MATERIAL_FIELDS),
        "authority": AUTHORITY,
    }


def compare_plan_home_report_telegram(
    plan: Any,
    cio_home: Any,
    report: Any,
    telegram_payload: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience wrapper for the four acceptance surfaces."""
    return compare_decision_surfaces(
        plan=plan,
        cio_home=cio_home,
        report=report,
        telegram_payload=telegram_payload,
        **kwargs,
    )
