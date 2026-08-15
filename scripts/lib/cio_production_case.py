"""Production CIO case store — decision → disposition → outcome → Darwin.

Does not mutate production config. No broker calls.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()

AUTHORITY = "READ_ONLY_ADVISORY"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = PROJECT_ROOT / "data" / "cio" / "cio_production_cases.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def case_id_for(decision_id: str, input_digest: str, evidence_digest: str) -> str:
    return "case_" + _stable_hash({
        "decision_id": decision_id,
        "in": input_digest,
        "ev": evidence_digest,
    })[:20]


def append_case(case: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    p = path or DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = dict(case)
    rec.setdefault("authority", AUTHORITY)
    rec.setdefault("recorded_at", _now())
    rec.setdefault("auto_promoted", False)
    rec.setdefault("creates_trade_authority", False)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    return rec


def open_case_from_decision(decision: dict[str, Any], *, research: Optional[dict] = None) -> dict[str, Any]:
    did = str(decision.get("decision_id") or "").strip()
    inp = str(decision.get("decision_input_digest") or "")
    evd = str(decision.get("decision_evidence_digest") or "")
    return append_case({
        "case_id": case_id_for(did, inp, evd),
        "status": "OPEN",
        "decision_id": did,
        "symbol": decision.get("symbol"),
        "action": decision.get("action") or decision.get("stance"),
        "decision_input_digest": inp,
        "decision_evidence_digest": evd,
        "decision_time_facts": {
            "weight_pct": decision.get("current_weight_pct") or decision.get("weight_pct"),
            "delta_usd": decision.get("recommended_delta_usd") or decision.get("delta_usd"),
            "why_now": decision.get("why_now"),
        },
        "research": research or {},
        "operator_disposition": None,
        "outcome": None,
        "darwin": None,
    })


def record_disposition(decision_id: str, disposition: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    return append_case({
        "case_id": f"disp_{decision_id}",
        "status": "DISPOSITION",
        "decision_id": decision_id,
        "operator_disposition": disposition,
    }, path=path)


def score_case_darwin(case: dict[str, Any]) -> dict[str, Any]:
    """Deterministic job score — not generic win rate."""
    disp = str((case.get("operator_disposition") or {}).get("disposition") or "").lower()
    outcome = str((case.get("outcome") or {}).get("outcome_status") or "").upper()
    points = 50
    if disp in {"ack", "done"}:
        points += 10
    if disp == "reject":
        points -= 5
    if outcome == "POSITIVE":
        points += 20
    elif outcome == "NEGATIVE":
        points -= 20
    if case.get("research", {}).get("decision_use_audit", {}).get("signature_ok"):
        points += 10
    if case.get("auto_promoted"):
        points = 0
    score = max(0, min(100, points))
    return {
        "scorer": "cio_production_case_darwin_v1",
        "score": score,
        "formula": "base50+disp+outcome+audit; auto_promote=0",
        "authority": AUTHORITY,
    }


def load_cases(path: Optional[Path] = None) -> list[dict[str, Any]]:
    p = path or DEFAULT_PATH
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
