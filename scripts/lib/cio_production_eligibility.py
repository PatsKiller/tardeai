"""Single production-advisory eligibility contract.

Provenance / environment / source identity is the primary control.
String markers (_e2e, _test, _fixture) are defense-in-depth only.

A record may be "material" in text and still be forbidden from live CIO NOW,
current product, what_changed, and production notification.

Authority: READ_ONLY_ADVISORY. No broker / order / stop / 2FA.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

AUTHORITY = "READ_ONLY_ADVISORY"

ENV_PROD = "PROD"
ENV_SHADOW = "SHADOW"
ENV_TEST = "TEST"
ENV_E2E = "E2E"
ENV_UNPROVEN = "UNPROVEN"

CLASS_PROD_VALID = "PROD_VALID"
CLASS_PROD_EXPIRED = "PROD_EXPIRED_REVALIDATION_REQUIRED"
CLASS_SYNTHETIC_TEST = "SYNTHETIC_TEST"
CLASS_SYNTHETIC_E2E = "SYNTHETIC_E2E"
CLASS_SHADOW = "SHADOW"
CLASS_LEGACY_PROVEN = "LEGACY_PROVEN"
CLASS_LEGACY_UNPROVEN = "LEGACY_UNPROVEN"
CLASS_ORPHANED = "ORPHANED"
CLASS_QUARANTINED = "QUARANTINED"

ELIGIBLE_CLASSES = frozenset({CLASS_PROD_VALID, CLASS_LEGACY_PROVEN})
FORBIDDEN_CLASSES = frozenset({
    CLASS_SYNTHETIC_TEST,
    CLASS_SYNTHETIC_E2E,
    CLASS_SHADOW,
    CLASS_QUARANTINED,
    CLASS_ORPHANED,
    CLASS_LEGACY_UNPROVEN,
    CLASS_PROD_EXPIRED,
})
TERMINAL_STATUSES = frozenset({
    "quarantined",
    "terminal",
    "closed",
    "tombstone",
    "revalidation_required",
    "orphaned",
    "ORPHANED_DEFER",
    "REVALIDATION_REQUIRED",
})

# Defense-in-depth only — never the primary gate.
_E2E_MARKERS = ("_e2e", "e2e_", "activation_defer_e2e")
_TEST_MARKERS = ("_test", "test_", "_fixture", "fixture_")
_INTERNAL_REASON_PREFIXES = ("activation_defer", "e2e_", "test_", "fixture_")

KNOWN_PRODUCTION_CIO_ROOTS = (
    Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/cio"),
)

OPERATOR_REASON_PROSE = {
    "review_due": "Scheduled CIO review is due; current evidence is being revalidated.",
    "operator_defer": "Operator deferred this decision; scheduled review is due.",
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_env(raw: Any) -> str:
    v = str(raw or "").strip().upper()
    if v in {"PROD", "PRODUCTION", "LIVE"}:
        return ENV_PROD
    if v in {"SHADOW"}:
        return ENV_SHADOW
    if v in {"TEST", "PYTEST", "UNIT"}:
        return ENV_TEST
    if v in {"E2E", "END_TO_END"}:
        return ENV_E2E
    if v in {"", "UNPROVEN", "UNKNOWN", "LEGACY"}:
        return ENV_UNPROVEN
    return v


def _truthy(v: Any) -> Optional[bool]:
    if v is True or v is False:
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return None


def _blob(record: dict[str, Any]) -> str:
    parts = [
        record.get("environment"),
        record.get("source_kind"),
        record.get("producer"),
        record.get("reason"),
        record.get("reason_code"),
        record.get("decision_id"),
        record.get("product_id"),
        record.get("trigger"),
        record.get("run_id"),
        record.get("lineage_id"),
        record.get("classification"),
    ]
    return " ".join(str(p or "") for p in parts).lower()


def detect_test_markers(record: dict[str, Any]) -> dict[str, bool]:
    """Defense-in-depth markers. Not the primary eligibility control."""
    blob = _blob(record)
    e2e = any(m in blob for m in _E2E_MARKERS)
    test = any(m in blob for m in _TEST_MARKERS)
    return {"e2e": e2e, "test": test, "any": e2e or test}


def is_internal_reason_code(text: Any) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    low = t.lower()
    if low.startswith("deferred review due ("):
        return True
    if any(p in low for p in _E2E_MARKERS):
        return True
    if any(low.startswith(p) for p in _INTERNAL_REASON_PREFIXES):
        return True
    return False


def operator_reason_prose(reason_code: Any) -> Optional[str]:
    code = str(reason_code or "").strip()
    if not code or is_internal_reason_code(code):
        return None
    return OPERATOR_REASON_PROSE.get(code)


def under_test_isolation() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CIO_TEST_ISOLATION"))


def cio_state_root() -> Path:
    for key in ("CIO_STATE_ROOT", "TRADEAI_ROOT", "MATURITY_CONTROL_ROOT"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return Path(val)
    return PROJECT_ROOT


def production_cio_roots() -> list[Path]:
    roots: list[Path] = []
    extra = (os.environ.get("CIO_PRODUCTION_STATE_ROOTS") or "").strip()
    if extra:
        for part in extra.split(os.pathsep):
            if part.strip():
                roots.append(Path(part.strip()))
    roots.extend(KNOWN_PRODUCTION_CIO_ROOTS)
    current = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/data/cio")
    if current.exists():
        roots.append(current)
    out: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        try:
            key = str(r.resolve())
        except OSError:
            key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def is_production_shared_cio_path(path: Path | str) -> bool:
    try:
        resolved = Path(path).resolve()
    except OSError:
        resolved = Path(path)
    for root in production_cio_roots():
        try:
            prod = root.resolve()
        except OSError:
            prod = root
        if resolved == prod or prod in resolved.parents or resolved.parent == prod:
            return True
    return False


class CioStateIsolationError(RuntimeError):
    """Tests/E2E resolved a production shared CIO path."""


def guard_test_cio_write(path: Path | str) -> Path:
    p = Path(path)
    if under_test_isolation() and is_production_shared_cio_path(p):
        raise CioStateIsolationError(
            f"TEST_ISOLATION_VIOLATION: {p} resolves to production shared CIO state"
        )
    return p


def infer_origin(record: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    rec = record if isinstance(record, dict) else {}
    env = _norm_env(rec.get("environment") or os.environ.get("CIO_ADVISORY_ENVIRONMENT"))
    markers = detect_test_markers(rec)
    if env == ENV_UNPROVEN:
        if markers["e2e"]:
            env = ENV_E2E
        elif markers["test"] or under_test_isolation():
            env = ENV_TEST
        else:
            live = (os.environ.get("TRADE_AI_ENV") or os.environ.get("TRADEAI_ENV")
                    or os.environ.get("APP_ENV") or "").strip().lower()
            if live in {"prod", "production", "live"}:
                env = ENV_PROD

    synthetic = _truthy(rec.get("synthetic"))
    if synthetic is None:
        synthetic = env in {ENV_TEST, ENV_E2E} or markers["any"]

    source_kind = str(rec.get("source_kind") or "").strip()
    if not source_kind:
        source_kind = {
            ENV_PROD: "PRODUCTION",
            ENV_SHADOW: "SHADOW",
            ENV_TEST: "TEST",
            ENV_E2E: "E2E",
        }.get(env, "UNPROVEN")

    return {
        "environment": env,
        "synthetic": bool(synthetic),
        "source_kind": source_kind,
        "run_id": rec.get("run_id") or os.environ.get("CIO_RUN_ID") or None,
        "source_commit": (
            rec.get("source_commit")
            or os.environ.get("SOURCE_COMMIT")
            or os.environ.get("GIT_SHA")
            or None
        ),
        "producer": rec.get("producer") or os.environ.get("CIO_ADVISORY_PRODUCER") or None,
        "created_at": rec.get("created_at") or rec.get("as_of") or rec.get("deferred_at") or _now_iso(),
    }


def stamp_advisory_origin(
    record: dict[str, Any],
    *,
    producer: str,
    force: bool = False,
) -> dict[str, Any]:
    """Additive origin metadata. Never strip historical fields."""
    if not isinstance(record, dict):
        return record
    inferred = infer_origin(record)
    inferred["producer"] = record.get("producer") or producer
    for key, val in inferred.items():
        if force or record.get(key) in (None, "", []):
            record[key] = val
    return record


def _looks_like_cio_product(record: dict[str, Any]) -> bool:
    schema = str(record.get("schema") or "")
    pid = str(record.get("product_id") or "")
    return schema.startswith("CIOInvestmentProduct@") and pid.startswith("prod_")


def _looks_like_office_decision(record: dict[str, Any]) -> bool:
    did = str(record.get("decision_id") or "")
    if not did.startswith("dec_"):
        return False
    if "activation" in did.lower() or "_e2e" in did.lower():
        return False
    return bool(record.get("symbol") or record.get("stance_code") or record.get("action"))


def classify_advisory_record(record: Optional[dict[str, Any]]) -> dict[str, Any]:
    rec = record if isinstance(record, dict) else {}
    markers = detect_test_markers(rec)
    env = _norm_env(rec.get("environment"))
    synthetic = _truthy(rec.get("synthetic"))
    source_kind = str(rec.get("source_kind") or "").strip().upper()
    status = str(rec.get("status") or rec.get("classification") or "").strip()
    quarantined = bool(rec.get("quarantined") or rec.get("terminal"))
    if status.lower() in {s.lower() for s in TERMINAL_STATUSES} or quarantined:
        if status.upper() in {"ORPHANED", "ORPHANED_DEFER"} or rec.get("classification") == CLASS_ORPHANED:
            classification = CLASS_ORPHANED
        elif status.upper() in {"REVALIDATION_REQUIRED"} or rec.get("classification") == CLASS_PROD_EXPIRED:
            classification = CLASS_PROD_EXPIRED
        else:
            classification = CLASS_QUARANTINED
        return _verdict(rec, classification, env, synthetic, source_kind, markers,
                        reason="terminal_or_quarantined")

    if env == ENV_E2E or source_kind == "E2E" or markers["e2e"]:
        return _verdict(rec, CLASS_SYNTHETIC_E2E, env or ENV_E2E, True, source_kind or "E2E",
                        markers, reason="e2e_origin")
    if env == ENV_TEST or source_kind in {"TEST", "FIXTURE"} or (synthetic is True and env != ENV_PROD):
        return _verdict(rec, CLASS_SYNTHETIC_TEST, env or ENV_TEST, True, source_kind or "TEST",
                        markers, reason="test_origin")
    if markers["test"] and env not in {ENV_PROD}:
        return _verdict(rec, CLASS_SYNTHETIC_TEST, env or ENV_TEST, True, source_kind or "TEST",
                        markers, reason="test_marker")
    if env == ENV_SHADOW or source_kind == "SHADOW":
        return _verdict(rec, CLASS_SHADOW, ENV_SHADOW, bool(synthetic), source_kind or "SHADOW",
                        markers, reason="shadow_origin")
    if env == ENV_PROD and synthetic is True:
        return _verdict(rec, CLASS_SYNTHETIC_TEST, ENV_PROD, True, source_kind, markers,
                        reason="prod_env_but_synthetic")
    if env == ENV_PROD and synthetic is False:
        return _verdict(rec, CLASS_PROD_VALID, ENV_PROD, False, source_kind or "PRODUCTION",
                        markers, reason="explicit_prod")

    # Legacy / missing origin — never infer PROD from file location.
    if env == ENV_UNPROVEN:
        if markers["e2e"]:
            return _verdict(rec, CLASS_SYNTHETIC_E2E, ENV_E2E, True, "E2E", markers,
                            reason="legacy_e2e_marker")
        if markers["test"]:
            return _verdict(rec, CLASS_SYNTHETIC_TEST, ENV_TEST, True, "TEST", markers,
                            reason="legacy_test_marker")
        if _looks_like_cio_product(rec) or _looks_like_office_decision(rec):
            return _verdict(rec, CLASS_LEGACY_PROVEN, ENV_UNPROVEN, False,
                            source_kind or "LEGACY_COMPAT", markers,
                            reason="legacy_compatible_schema")
        return _verdict(rec, CLASS_LEGACY_UNPROVEN, ENV_UNPROVEN, None,
                        source_kind or "UNPROVEN", markers,
                        reason="legacy_unproven")

    return _verdict(rec, CLASS_LEGACY_UNPROVEN, env, synthetic, source_kind, markers,
                    reason="unclassified")


def _verdict(
    rec: dict[str, Any],
    classification: str,
    env: Any,
    synthetic: Any,
    source_kind: Any,
    markers: dict[str, bool],
    *,
    reason: str,
) -> dict[str, Any]:
    eligible = classification in ELIGIBLE_CLASSES
    return {
        "classification": classification,
        "eligible": eligible,
        "environment": env,
        "synthetic": synthetic,
        "source_kind": source_kind,
        "reason": reason,
        "markers": markers,
        "decision_id": rec.get("decision_id"),
        "product_id": rec.get("product_id"),
        "lineage_id": rec.get("lineage_id"),
        "authority": AUTHORITY,
    }


def eligibility_verdict(
    record: Optional[dict[str, Any]],
    *,
    purpose: str = "current",
) -> dict[str, Any]:
    v = classify_advisory_record(record)
    v["purpose"] = purpose
    v["eligible"] = bool(v["eligible"])
    if purpose in {"production_notification", "production_publication", "current"} and not v["eligible"]:
        v["block"] = f"not_production_advisory_eligible:{v['classification']}"
    return v


def is_production_advisory_eligible(
    record: Optional[dict[str, Any]],
    *,
    purpose: str = "current",
) -> bool:
    return bool(eligibility_verdict(record, purpose=purpose)["eligible"])


def is_forbidden_from_production(record: Optional[dict[str, Any]]) -> bool:
    c = classify_advisory_record(record)["classification"]
    return c in {
        CLASS_SYNTHETIC_E2E,
        CLASS_SYNTHETIC_TEST,
        CLASS_SHADOW,
        CLASS_QUARANTINED,
        CLASS_ORPHANED,
        CLASS_LEGACY_UNPROVEN,
    }


def prior_visible_for_what_changed(
    prior: Optional[dict[str, Any]],
    new: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """what_changed compares eligible PROD→PROD (or same-class TEST→TEST in fixtures).

    E2E / SHADOW / quarantined artifacts are invisible to the comparison chain.
    A TEST/E2E product between two production products does not manufacture change.
    """
    if not isinstance(prior, dict) or not prior:
        return {}
    pc = classify_advisory_record(prior)["classification"]
    nc = classify_advisory_record(new if isinstance(new, dict) else {})["classification"]
    if pc in {CLASS_SYNTHETIC_E2E, CLASS_SHADOW, CLASS_QUARANTINED, CLASS_ORPHANED}:
        return {}
    if nc in ELIGIBLE_CLASSES and pc == CLASS_SYNTHETIC_TEST:
        return {}
    return prior


def select_current_production_product(
    candidates: Iterable[Optional[dict[str, Any]]],
) -> Optional[dict[str, Any]]:
    """Newest eligible production product wins. Timestamp cannot defeat provenance."""
    eligible: list[dict[str, Any]] = []
    for rec in candidates:
        if isinstance(rec, dict) and is_production_advisory_eligible(rec, purpose="current"):
            eligible.append(rec)
    if not eligible:
        return None

    def _key(rec: dict[str, Any]) -> tuple[str, str]:
        return (
            str(rec.get("as_of") or rec.get("generated_at") or rec.get("created_at") or ""),
            str(rec.get("product_id") or rec.get("decision_id") or ""),
        )

    eligible.sort(key=_key)
    return eligible[-1]


def unavailable_current_product(
    *,
    reason: str,
    last: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    last = last if isinstance(last, dict) else {}
    return {
        "schema": "CIOCurrentProductUnavailable@v1",
        "status": "CIO_CURRENT_PRODUCT_UNAVAILABLE",
        "reason": reason,
        "last_valid_product": {
            "product_id": last.get("product_id"),
            "decision_id": last.get("decision_id"),
            "as_of": last.get("as_of"),
            "classification": classify_advisory_record(last)["classification"] if last else None,
        } if last else None,
        "freshness": last.get("freshness") if last else None,
        "revalidation_status": "REVALIDATION_REQUIRED",
        "authority": AUTHORITY,
        "financial_action": False,
        "synthetic": False,
        "environment": ENV_PROD,
    }


def attach_capital_truth(decision: dict[str, Any], plan: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(decision, dict):
        return decision
    cap = dict(decision.get("capital") or {}) if isinstance(decision.get("capital"), dict) else {}
    src = plan if isinstance(plan, dict) else {}
    mapping = {
        "free_investable": ("cash_investable_usd", "cash_free_unearmarked_usd"),
        "deploy_now": ("recommended_deploy_usd", "deployable_usd"),
        "remain_cash": ("post_plan_cash_usd", "cash_reserved_usd"),
    }
    for dest, keys in mapping.items():
        if cap.get(dest) is not None:
            continue
        for k in keys:
            if src.get(k) is not None:
                cap[dest] = src[k]
                break
    if cap:
        decision["capital"] = cap
        decision.setdefault("capital_source", "capital_plan")
    return decision


def quarantine_record(
    record: dict[str, Any],
    *,
    classification: str,
    reason: str,
) -> dict[str, Any]:
    out = dict(record)
    out.update({
        "status": "quarantined",
        "quarantined": True,
        "terminal": True,
        "classification": classification,
        "classification_reason": reason,
        "quarantined_at": _now_iso(),
        "authority": AUTHORITY,
    })
    return out
