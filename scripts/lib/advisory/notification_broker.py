"""Phase 6 notification broker — Tier D chokepoint (SHADOW-first).

Ingests producer messages, dedupes, ranks, and reports compression.
Default mode does **not** cut over egress: legacy telegram_alert continues.
Egress cutover only after prove_zero_material_drops() is green.

Tier model (design):
  A/B producers → C classify/route → **D broker** (this module) → E transport
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME = PROJECT_ROOT / "data" / "runtime"
BROKER_DIR = RUNTIME / "advisory_notif_broker"
INGEST_PATH = BROKER_DIR / "ingest.jsonl"
DECISIONS_PATH = BROKER_DIR / "decisions.jsonl"
METRICS_PATH = BROKER_DIR / "metrics.json"
PROOF_PATH = BROKER_DIR / "egress_cutover_proof.json"

# Material alert types that must never be dropped (egress cutover gate)
MATERIAL_TYPES = frozenset({
    "orphaned_stop",
    "position_unprotected",
    "protection_failure",
    "broker_auth_blocking",
    "live_order_2fa_required",
    "live_session_2fa_required",
    "protective_order_approval_required",
    "partial_fill_protection_uncertain",
    "CRITICAL",
    "P1",
})

SEVERITY_RANK = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def fingerprint(message: str, producer: str = "") -> str:
    norm = re.sub(r"\s+", " ", (message or "").strip().lower())
    # strip volatile timestamps
    norm = re.sub(r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}", "", norm)
    base = f"{producer}|{norm[:500]}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def classify_severity(message: str, alert_type: str = "") -> str:
    m = (message or "").lower()
    t = (alert_type or "").lower()
    if any(k in m or k in t for k in ("orphaned", "unprotected", "2fa", "auth block", "protection fail")):
        return "critical"
    if "⚠️" in message or "critical" in m or t.startswith("p1"):
        return "high"
    if "advisory" in m or "digest" in m:
        return "info"
    if "warning" in m or "stale" in m:
        return "medium"
    return "low"


def is_material(alert_type: str, severity: str, message: str = "") -> bool:
    if severity == "critical":
        return True
    t = (alert_type or "").lower()
    if t in {x.lower() for x in MATERIAL_TYPES}:
        return True
    m = (message or "").lower()
    return any(k in m for k in ("orphaned stop", "unprotected", "2fa required", "broker auth"))


def ingest(
    message: str,
    *,
    producer: str = "unknown",
    alert_type: str = "",
    bypass_router: bool = False,
) -> dict[str, Any]:
    """Record a producer message at the broker chokepoint (non-blocking for senders)."""
    sev = classify_severity(message, alert_type)
    fp = fingerprint(message, producer)
    entry = {
        "ts": _now_iso(),
        "producer": producer,
        "alert_type": alert_type or "untyped",
        "severity": sev,
        "material": is_material(alert_type, sev, message),
        "fingerprint": fp,
        "bypass_router": bypass_router,
        "message_preview": (message or "")[:240],
        "message_len": len(message or ""),
    }
    _append_jsonl(INGEST_PATH, entry)
    return entry


def process_window(*, hours: float = 24.0) -> dict[str, Any]:
    """Dedupe + rank ingest over a time window; write decisions + metrics."""
    cutoff = _now() - timedelta(hours=hours)
    rows = []
    for e in _read_jsonl(INGEST_PATH):
        try:
            ts = datetime.fromisoformat(str(e.get("ts")).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if ts >= cutoff:
            rows.append(e)

    ingested = len(rows)
    # Dedupe by fingerprint — keep highest severity (lowest rank number)
    best: dict[str, dict[str, Any]] = {}
    for e in rows:
        fp = e.get("fingerprint") or ""
        prev = best.get(fp)
        if not prev:
            best[fp] = e
            continue
        if SEVERITY_RANK.get(e.get("severity"), 9) < SEVERITY_RANK.get(prev.get("severity"), 9):
            best[fp] = e

    unique = list(best.values())
    unique.sort(key=lambda e: (
        SEVERITY_RANK.get(e.get("severity"), 9),
        0 if e.get("material") else 1,
        e.get("ts") or "",
    ))

    suppressed = ingested - len(unique)
    material_in = [e for e in rows if e.get("material")]
    material_out = [e for e in unique if e.get("material")]
    material_dropped = max(0, len({e["fingerprint"] for e in material_in}) - len({e["fingerprint"] for e in material_out}))

    # Ranked egress plan (SHADOW — not executed here)
    for i, e in enumerate(unique):
        dec = {
            "ts": _now_iso(),
            "fingerprint": e.get("fingerprint"),
            "rank": i + 1,
            "action": "EMIT" if e.get("material") or e.get("severity") in ("critical", "high") else "DIGEST",
            "severity": e.get("severity"),
            "material": e.get("material"),
            "producer": e.get("producer"),
            "mode": "SHADOW",
        }
        _append_jsonl(DECISIONS_PATH, dec)

    compression = (suppressed / ingested) if ingested else 0.0
    metrics = {
        "ts": _now_iso(),
        "window_hours": hours,
        "ingested": ingested,
        "unique": len(unique),
        "suppressed_dupes": suppressed,
        "compression_ratio": round(compression, 4),
        "material_in": len(material_in),
        "material_out": len(material_out),
        "material_dropped": material_dropped,
        "zero_material_drops": material_dropped == 0,
        "by_severity": dict(Counter(e.get("severity") for e in unique)),
        "by_producer": dict(Counter(e.get("producer") for e in rows)),
        "egress_cutover_allowed": False,  # never auto-cutover
    }
    try:
        BROKER_DIR.mkdir(parents=True, exist_ok=True)
        METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    except Exception:
        pass

    proof = {
        "ts": _now_iso(),
        "zero_material_drops": metrics["zero_material_drops"],
        "material_dropped": material_dropped,
        "compression_ratio": metrics["compression_ratio"],
        "ingested": ingested,
        "unique": len(unique),
        "egress_cutover": "BLOCKED" if material_dropped > 0 or ingested == 0 else "ELIGIBLE_OPERATOR_GATE",
        "note": (
            "Egress cutover requires operator gate + sustained zero material drops. "
            "Broker remains SHADOW; legacy telegram_alert still owns delivery."
        ),
    }
    try:
        PROOF_PATH.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    except Exception:
        pass

    return {"ok": True, "metrics": metrics, "proof": proof, "top": unique[:10]}


def wrap_send_hook(message: str, *, producer: str = "send_telegram", **kwargs: Any) -> dict[str, Any]:
    """Call from chokepoint: ingest only; never suppress the real send."""
    return ingest(message, producer=producer, alert_type=kwargs.get("alert_type") or "", bypass_router=bool(kwargs.get("bypass_router")))


def load_metrics() -> dict[str, Any]:
    if METRICS_PATH.exists():
        try:
            return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def load_proof() -> dict[str, Any]:
    if PROOF_PATH.exists():
        try:
            return json.loads(PROOF_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"egress_cutover": "NO_DATA"}
