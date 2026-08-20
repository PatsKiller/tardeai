"""Register Advisory Desk evidence gaps into data_gap_registry (fail-soft).

Authority: READ_ONLY_ADVISORY — queues research/enrichment only, never broker writes.

Previously the desk showed DATA_UNAVAILABLE / gaps but did not enqueue fulfillment.
This module registers requeueable gaps for holdings + re-entry READY/NEAR so
``data_gap_resolver`` / overnight workers can chase them (deduped).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.advisory_quality_label import GAP_TYPE_MAP, classify_advisory_quality

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "data" / "cio" / "advisory_gap_requeue_ledger.jsonl"
AUTHORITY = "READ_ONLY_ADVISORY"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _conn():
    try:
        import psycopg2
    except Exception:
        return None
    try:
        pw = os.environ.get("DB_PASSWORD", "")
        env_path = ROOT / ".env"
        if not pw and env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("DB_PASSWORD="):
                    pw = line.split("=", 1)[1].strip().strip("'\"")
        if not pw:
            return None
        return psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=pw,
        )
    except Exception:
        return None


def _append_ledger(rec: dict[str, Any]) -> None:
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    except Exception:
        pass


def register_advisory_gaps(
    rows: list[dict[str, Any]],
    *,
    max_register: int = 40,
    enabled: Optional[bool] = None,
) -> dict[str, Any]:
    """Insert open gaps for material rows. Idempotent per symbol+gap_type while open."""
    if enabled is None:
        enabled = os.environ.get("ADVISORY_GAP_REQUEUE", "1").strip().lower() not in {
            "0", "false", "no", "off",
        }
    out: dict[str, Any] = {
        "ok": True,
        "enabled": enabled,
        "registered": 0,
        "skipped_dup": 0,
        "skipped_policy": 0,
        "errors": 0,
        "authority": AUTHORITY,
        "as_of": _now(),
    }
    if not enabled:
        out["skip"] = "ADVISORY_GAP_REQUEUE off"
        return out

    candidates: list[tuple[str, str, str, str]] = []  # symbol, gap_type, detail, severity
    for row in rows or []:
        rcls = str(row.get("row_class") or "")
        if rcls not in ("holding", "closed_journal", "watchlist"):
            out["skipped_policy"] += 1
            continue
        # Re-entry: only READY/NEAR (and MISSING*) — not hub noise
        if rcls == "closed_journal":
            st = str(row.get("reentry_state") or "").upper()
            if not any(x in st for x in ("READY", "NEAR", "MISSING")):
                out["skipped_policy"] += 1
                continue
        dq = row.get("data_quality") or {}
        classified = classify_advisory_quality(row, dq)
        if not classified.get("requeueable"):
            out["skipped_policy"] += 1
            continue
        sym = str(row.get("symbol") or "").upper()
        if not sym or sym.startswith("ALLOC:") or len(sym) > 8:
            out["skipped_policy"] += 1
            continue
        for gap in classified.get("requeue_gaps") or []:
            gtype = GAP_TYPE_MAP.get(gap, "explicit")
            detail = (
                f"advisory_desk:{classified.get('kind')}:{gap} "
                f"label={classified.get('label')}"
            )
            severity = "high" if rcls == "holding" or "READY" in str(row.get("reentry_state") or "").upper() else "medium"
            candidates.append((sym, gtype, detail, severity))

    # Dedupe within this pass
    seen: set[tuple[str, str]] = set()
    uniq: list[tuple[str, str, str, str]] = []
    for c in candidates:
        key = (c[0], c[1])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    uniq = uniq[: max(0, int(max_register))]

    conn = _conn()
    if conn is None:
        # Still ledger so ops can see intent without DB
        for sym, gtype, detail, severity in uniq:
            _append_ledger({
                "as_of": _now(), "symbol": sym, "gap_type": gtype,
                "detail": detail, "severity": severity, "status": "ledger_only_no_db",
            })
            out["registered"] += 1
        out["ok"] = True
        out["note"] = "no_db_connection_ledger_only"
        return out

    try:
        cur = conn.cursor()
        for sym, gtype, detail, severity in uniq:
            try:
                cur.execute(
                    """
                    SELECT id FROM data_gap_registry
                    WHERE symbol = %s AND gap_type = %s AND status IN ('open', 'enriching')
                    LIMIT 1
                    """,
                    [sym, gtype],
                )
                if cur.fetchone():
                    out["skipped_dup"] += 1
                    continue
                cur.execute(
                    """
                    INSERT INTO data_gap_registry
                        (symbol, gap_type, gap_detail, detected_by, severity, status)
                    VALUES (%s, %s, %s, 'advisory_desk_quality', %s, 'open')
                    """,
                    [sym, gtype, detail[:500], severity],
                )
                conn.commit()
                out["registered"] += 1
                _append_ledger({
                    "as_of": _now(), "symbol": sym, "gap_type": gtype,
                    "detail": detail, "severity": severity, "status": "open",
                })
            except Exception:
                conn.rollback()
                out["errors"] += 1
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out
