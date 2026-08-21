"""Held-book living thesis coverage SLA (READ_ONLY_ADVISORY).

Phase 1 spine: every held ticker should be CURRENT (or an explicit gap).
Reuses symbol_thesis_attach / acquisition — does not invent theses.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "HeldBookThesisCoverage@v1"
REVISION_SCHEMA = "ThesisRevisionLedger@v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_ticker(sym: str) -> bool:
    from scripts.lib.holdings_universe import is_held_equity_ticker

    return is_held_equity_ticker(sym)


def list_held_tickers(*, root: Path | None = None) -> list[str]:
    """Held equity tickers — authoritative coverage denominator.

    Delegates to holdings_universe.held_equity_tickers (CASH/CUSIP out).
    """
    from scripts.lib.holdings_universe import held_equity_tickers

    root = root or _project_root()
    out = held_equity_tickers(root=root)
    if out:
        return out
    # Fail-soft CIO snapshot if holdings.json empty
    try:
        from scripts.lib.data_broker.cio_portfolio import get_cio_snapshot
        from scripts.lib.holdings_universe import is_held_equity_ticker

        snap = get_cio_snapshot(max_age_s=60) or {}
        hd = (snap.get("domains") or {}).get("holdings_detail") or {}
        positions = hd.get("positions")
        if positions is None and isinstance(hd.get("data"), dict):
            positions = hd["data"].get("positions")
        tickers = []
        for p in positions or []:
            if isinstance(p, dict):
                sym = str(p.get("symbol") or "").upper()
                if is_held_equity_ticker(sym):
                    tickers.append(sym)
        return sorted(set(tickers))
    except Exception:
        return []


def coverage_row_for_symbol(symbol: str, *, root: Path | None = None) -> dict[str, Any]:
    root = root or _project_root()
    try:
        from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol

        fields = thesis_fields_for_symbol(symbol, root=root) or {}
    except Exception as exc:
        fields = {"thesis_state": "INSUFFICIENT_DATA", "error": type(exc).__name__}
    state = str(fields.get("thesis_state") or "INSUFFICIENT_DATA")
    current = bool(fields.get("has_current_symbol_thesis")) or state == "CURRENT"
    return {
        "symbol": symbol.upper(),
        "thesis_state": state,
        "has_current_symbol_thesis": current,
        "portfolio_role": fields.get("portfolio_role"),
        "symbol_thesis_version": fields.get("symbol_thesis_version"),
        "research_gaps": list(fields.get("research_gaps") or [])[:5],
        "needs_coverage": not current and state in {
            "RESEARCH_REQUIRED", "INSUFFICIENT_DATA", "STALE", "CONFLICTED", "NONE", ""
        },
    }


def build_held_coverage_report(*, root: Path | None = None) -> dict[str, Any]:
    """SLA report for held book only."""
    root = root or _project_root()
    held = list_held_tickers(root=root)
    rows = [coverage_row_for_symbol(s, root=root) for s in held]
    current_n = sum(1 for r in rows if r.get("has_current_symbol_thesis"))
    need = [r for r in rows if r.get("needs_coverage")]
    by_state: dict[str, int] = {}
    for r in rows:
        st = str(r.get("thesis_state") or "NONE")
        by_state[st] = by_state.get(st, 0) + 1
    total = len(rows) or 1
    pct = round(100.0 * current_n / total, 2) if rows else 0.0
    return {
        "schema": SCHEMA,
        "as_of": _now(),
        "authority": AUTHORITY,
        "held_count": len(rows),
        "current_count": current_n,
        "held_current_pct": pct,
        "sla_target_pct": 80.0,
        "sla_met": pct >= 80.0,
        "by_state": by_state,
        "needs_coverage": [r["symbol"] for r in need],
        "needs_coverage_n": len(need),
        "rows": rows,
        "root": str(root),
    }


def write_coverage_report(
    report: dict[str, Any],
    *,
    root: Path | None = None,
) -> Path:
    root = root or _project_root()
    path = root / "data" / "cio" / "held_thesis_coverage_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    try:
        from scripts.lib.holdings_universe import write_snapshot

        write_snapshot(root=root)
    except Exception:
        pass
    # append history line
    hist = root / "data" / "cio" / "held_thesis_coverage_history.jsonl"
    with hist.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "as_of": report.get("as_of"),
            "held_count": report.get("held_count"),
            "current_count": report.get("current_count"),
            "held_current_pct": report.get("held_current_pct"),
            "needs_coverage_n": report.get("needs_coverage_n"),
            "sla_met": report.get("sla_met"),
        }, sort_keys=True) + "\n")
    return path


def run_held_coverage_acquire(
    *,
    root: Path | None = None,
    limit: int = 5,
    max_llm: int = 3,
    apply: bool = False,
    symbols: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Enqueue/run acquisition for held gaps via existing acquisition runner."""
    root = root or _project_root()
    report = build_held_coverage_report(root=root)
    write_coverage_report(report, root=root)
    targets = symbols or list(report.get("needs_coverage") or [])
    targets = [s.upper() for s in targets if _is_ticker(s)][: max(0, int(limit))]
    if not targets:
        return {
            "ok": True,
            "authority": AUTHORITY,
            "mode": "apply" if apply else "dry",
            "targets": [],
            "skipped": "no_held_gaps",
            "report": {
                "held_current_pct": report.get("held_current_pct"),
                "sla_met": report.get("sla_met"),
                "needs_coverage_n": report.get("needs_coverage_n"),
            },
        }

    from scripts.run_symbol_thesis_acquisition import run as run_acquisition_batch

    result = run_acquisition_batch(
        root=root,
        symbols=targets,
        limit=len(targets),
        max_llm=max_llm,
        apply=apply,
        canary=False,
    )
    # Refresh report after attempt
    after = build_held_coverage_report(root=root)
    write_coverage_report(after, root=root)
    return {
        "ok": True,
        "authority": AUTHORITY,
        "mode": "apply" if apply else "dry",
        "targets": targets,
        "acquisition": result,
        "report_before": {
            "held_current_pct": report.get("held_current_pct"),
            "needs_coverage_n": report.get("needs_coverage_n"),
        },
        "report_after": {
            "held_current_pct": after.get("held_current_pct"),
            "needs_coverage_n": after.get("needs_coverage_n"),
            "sla_met": after.get("sla_met"),
        },
    }


# ── Thesis revision ledger (Phase 1 stub for Phase 2 catalyst loop) ─────────


def revision_ledger_path(root: Path | None = None) -> Path:
    root = root or _project_root()
    return root / "data" / "cio" / "thesis_revision_ledger.jsonl"


def append_thesis_revision(
    *,
    symbol: str,
    reason: str,
    catalyst_id: str | None = None,
    severity: str | None = None,
    thesis_version_before: str | None = None,
    thesis_version_after: str | None = None,
    impact: str | None = None,
    recommendation: str | None = None,
    confidence: float | None = None,
    evidence_refs: Optional[list[dict[str, Any]]] = None,
    root: Path | None = None,
    dry_notify: bool = True,
) -> dict[str, Any]:
    """Append a revision ledger row (READ_ONLY). Notify always dry in Phase 1."""
    root = root or _project_root()
    row = {
        "schema": REVISION_SCHEMA,
        "ts": _now(),
        "symbol": symbol.upper(),
        "reason": reason,
        "catalyst_id": catalyst_id,
        "severity": severity,
        "thesis_version_before": thesis_version_before,
        "thesis_version_after": thesis_version_after,
        "impact": impact or "DATA_UNAVAILABLE",
        "recommendation": recommendation or "REVIEW",
        "confidence": confidence,
        "evidence_refs": evidence_refs or [],
        "notify": {"dry": True, "sent": False} if dry_notify else {"dry": False},
        "authority": AUTHORITY,
    }
    path = revision_ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return row


def reassess_held_from_catalysts(
    *,
    root: Path | None = None,
    limit: int = 20,
    min_severity: str = "medium",
) -> dict[str, Any]:
    """Phase 1/2 skeleton: held symbols with medium+ catalysts → revision ledger.

    Does not auto-publish thesis versions. Notify remains dry.
    """
    root = root or _project_root()
    held = list_held_tickers(root=root)
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    min_r = rank.get(str(min_severity).lower(), 1)
    written: list[dict[str, Any]] = []
    scanned = 0
    try:
        from scripts.db_adapter import _execute as _db
    except Exception:
        try:
            from db_adapter import _execute as _db  # type: ignore
        except Exception as exc:
            return {
                "ok": False,
                "error": f"db:{type(exc).__name__}",
                "authority": AUTHORITY,
                "written": [],
            }

    try:
        from scripts.lib.data_broker.catalyst_record import get_catalyst_record
    except Exception:
        from lib.data_broker.catalyst_record import get_catalyst_record  # type: ignore

    for sym in held[: max(1, int(limit) * 2)]:
        if len(written) >= limit:
            break
        scanned += 1
        try:
            rec = get_catalyst_record(lambda sql, params=None, fetch="all": _db(sql, params, fetch=fetch), sym)
        except Exception:
            continue
        if not isinstance(rec, dict) or not rec:
            continue
        # Normalize severity from pack or fields
        sev = str(
            rec.get("severity")
            or (rec.get("primary") or {}).get("severity")
            or rec.get("max_severity")
            or "low"
        ).lower()
        if rank.get(sev, 0) < min_r:
            # Also accept verified medium+ lists
            items = rec.get("catalysts") or rec.get("items") or []
            hit = None
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    s2 = str(it.get("severity") or "low").lower()
                    if rank.get(s2, 0) >= min_r:
                        hit = it
                        sev = s2
                        break
            if not hit and rank.get(sev, 0) < min_r:
                continue
        else:
            hit = rec.get("primary") if isinstance(rec.get("primary"), dict) else rec

        cov = coverage_row_for_symbol(sym, root=root)
        cat_id = None
        headline = None
        if isinstance(hit, dict):
            cat_id = str(hit.get("catalyst_id") or hit.get("id") or hit.get("event_id") or "") or None
            headline = hit.get("headline") or hit.get("title")
        row = append_thesis_revision(
            symbol=sym,
            reason="catalyst_medium_plus",
            catalyst_id=cat_id,
            severity=sev,
            thesis_version_before=cov.get("symbol_thesis_version"),
            impact=f"Held name has {sev} catalyst; thesis should be reassessed",
            recommendation="REASSESS_THESIS" if cov.get("needs_coverage") else "MONITOR_THESIS",
            confidence=0.55,
            evidence_refs=[{
                "domain": "catalyst",
                "symbol": sym,
                "severity": sev,
                "headline": (str(headline)[:160] if headline else None),
                "catalyst_id": cat_id,
            }],
            root=root,
            dry_notify=True,
        )
        written.append(row)

    return {
        "ok": True,
        "authority": AUTHORITY,
        "scanned_held": scanned,
        "held_total": len(held),
        "min_severity": min_severity,
        "revisions_written": len(written),
        "symbols": [w["symbol"] for w in written],
        "notify": "dry",
        "ledger": str(revision_ledger_path(root)),
    }
